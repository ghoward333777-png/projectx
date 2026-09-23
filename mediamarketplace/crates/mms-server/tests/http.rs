//! End-to-end HTTP tests against an in-memory database.

use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;

#[path = "../src/app.rs"]
#[allow(dead_code)]
mod app;
#[path = "../src/auth.rs"]
#[allow(dead_code)]
mod auth;
#[path = "../src/errors.rs"]
#[allow(dead_code)]
mod errors;
#[path = "../src/routes/mod.rs"]
#[allow(dead_code)]
mod routes;
#[path = "../src/templates.rs"]
#[allow(dead_code)]
mod templates;

async fn state() -> app::AppState {
    state_at("http://localhost:8090").await
}

async fn state_at(public_url: &str) -> app::AppState {
    let tmp = std::env::temp_dir().join(format!("mms-http-{}", uuid::Uuid::new_v4()));
    let config = mms_core::config::Config::generate(tmp, "127.0.0.1:0", public_url);
    let db = mms_core::db::Db::memory().await.unwrap();
    app::AppState::new(config, db).unwrap()
}

fn form(method: &str, uri: &str, body: &str, cookie: Option<&str>) -> Request<Body> {
    let mut b = Request::builder()
        .method(method)
        .uri(uri)
        .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded");
    if let Some(c) = cookie {
        b = b.header(header::COOKIE, c);
    }
    b.body(Body::from(body.to_string())).unwrap()
}

fn get(uri: &str, cookie: Option<&str>) -> Request<Body> {
    form("GET", uri, "", cookie)
}

async fn bytes(res: axum::response::Response) -> Vec<u8> {
    res.into_body().collect().await.unwrap().to_bytes().to_vec()
}

async fn text(res: axum::response::Response) -> String {
    String::from_utf8(res.into_body().collect().await.unwrap().to_bytes().to_vec()).unwrap()
}

fn cookie_of(res: &axum::response::Response) -> String {
    res.headers()
        .get(header::SET_COOKIE)
        .unwrap()
        .to_str()
        .unwrap()
        .split(';')
        .next()
        .unwrap()
        .to_string()
}

#[tokio::test]
async fn first_run_setup_then_login_settings_bridges_sso_and_embed() {
    let st = state().await;
    let app = app::router(st.clone());

    // Fresh install redirects to the setup wizard.
    let res = app.clone().oneshot(get("/", None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert_eq!(res.headers()[header::LOCATION], "/setup");

    // Admin endpoints require login and the API refuses anonymous callers.
    let res = app.clone().oneshot(get("/admin", None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app.clone().oneshot(get("/api/v1/me", None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);

    // Create the first administrator.
    let res = app.clone().oneshot(form("POST", "/setup", "email=admin%40example.com&name=Admin&password=correct-horse-battery&password_repeat=correct-horse-battery", None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let cookie = cookie_of(&res);
    assert!(cookie.starts_with("mms_session="));

    // Setup is closed afterwards.
    let res = app.clone().oneshot(get("/setup", None)).await.unwrap();
    assert_eq!(res.headers()[header::LOCATION], "/admin/login");

    // Dashboard and health render for the admin.
    let res = app
        .clone()
        .oneshot(get("/admin", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(body.contains("Dashboard") && body.contains("admin@example.com"));
    let csrf = body
        .split("name=\"_csrf\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();

    let res = app
        .clone()
        .oneshot(get("/api/v1/health", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(body.contains("\"checks\"") && body.contains("\"database\""));

    // Login with wrong password fails, right password succeeds.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/login",
            "email=admin%40example.com&password=nope",
            None,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert!(text(res).await.contains("incorrect"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/login",
            "email=admin%40example.com&password=correct-horse-battery",
            None,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);

    // Settings: CSRF enforced, then saved and rendered back with the secret masked.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/settings",
            "_csrf=bad&store.currency=EUR",
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/settings",
            &format!("_csrf={csrf}&store.currency=EUR&ai.anthropic_api_key=sk-ant-1234567890"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(
        body.contains("Settings saved")
            && body.contains("value=\"EUR\"")
            && !body.contains("sk-ant-1234567890")
    );
    assert_eq!(
        st.settings.get("ai.anthropic_api_key").await.unwrap(),
        "sk-ant-1234567890"
    );

    // Bridge site creation returns a secret once.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/bridges",
            &format!(
                "_csrf={csrf}&name=Main&host=wordpress&origin=https%3A%2F%2Fwww.example.com%2F"
            ),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("Copy these into the bridge plugin"));
    let site_uuid = body
        .split("<dt>Site ID</dt><dd><code>")
        .nth(1)
        .unwrap()
        .split('<')
        .next()
        .unwrap()
        .to_string();
    let secret = body
        .split("<dt>Secret</dt><dd><code>")
        .nth(1)
        .unwrap()
        .split('<')
        .next()
        .unwrap()
        .to_string();
    assert_eq!(secret.len(), 64);

    // Embeds are only served to known sites and carry a frame-ancestors policy for that origin.
    let res = app
        .clone()
        .oneshot(get("/embed/showcase?site=unknown", None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/showcase?site={site_uuid}"), None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(
        res.headers()[header::CONTENT_SECURITY_POLICY],
        "frame-ancestors 'self' https://www.example.com"
    );
    assert!(text(res).await.contains("No products published yet"));
    let now = mms_core::now();
    sqlx::query("INSERT INTO products (uuid, slug, type, title, price_cents, currency, status, created_at, updated_at) VALUES ('p-1','pass','site_pass','Pass',14900,'USD','published',?,?)")
        .bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/showcase?site={site_uuid}"), None))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("USD 149.00") && body.contains(">Site pass<"),
        "money and label filters: {body}"
    );

    // SSO: a token signed with the site secret logs the visitor in as a customer.
    let signer = mms_core::signer::Signer::from_shared_secret(&secret);
    let exp = chrono::Utc::now().timestamp() + 60;
    let token = signer.sign_raw(format!(r#"{{"sub":"7","email":"shopper@example.com","name":"Shopper","host":"wordpress","exp":{exp}}}"#).as_bytes());
    let res = app
        .clone()
        .oneshot(get(
            &format!("/sso?site={site_uuid}&token={token}&return=%2Faccount"),
            None,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER, "sso should redirect");
    assert_eq!(res.headers()[header::LOCATION], "/account");
    let shopper_cookie = cookie_of(&res);
    let res = app
        .clone()
        .oneshot(get("/api/v1/me", Some(&shopper_cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(body.contains("shopper@example.com") && body.contains("\"customer\""));
    let res = app
        .clone()
        .oneshot(get("/api/v1/me/entitlements", Some(&shopper_cookie)))
        .await
        .unwrap();
    assert_eq!(text(res).await, r#"{"data":[]}"#);

    // A customer is not an administrator.
    let res = app
        .clone()
        .oneshot(get("/admin", Some(&shopper_cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);

    // Wrong host claim, tampered token and open redirects are rejected.
    let bad_host = signer.sign_raw(
        format!(r#"{{"sub":"7","email":"s@example.com","name":"S","host":"joomla","exp":{exp}}}"#)
            .as_bytes(),
    );
    let res = app
        .clone()
        .oneshot(get(
            &format!("/sso?site={site_uuid}&token={bad_host}"),
            None,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(get(&format!("/sso?site={site_uuid}&token={token}x"), None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        routes::sso::safe_return(Some("https://evil.example")),
        "/account"
    );
    assert_eq!(routes::sso::safe_return(Some("//evil.example")), "/account");
    assert_eq!(routes::sso::safe_return(Some("/my/media")), "/my/media");

    // Logout clears the session.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/logout",
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert!(res.headers()[header::SET_COOKIE]
        .to_str()
        .unwrap()
        .contains("Max-Age=0"));
}

/// Single-server installs mount the store under the website's own domain, e.g. https://www.example.com/store.
#[tokio::test]
async fn serves_under_a_path_prefix_when_public_url_has_one() {
    let st = state_at("https://www.example.com/store").await;
    let app = app::router(st.clone());

    let res = app.clone().oneshot(get("/setup", None)).await.unwrap();
    assert_eq!(
        res.status(),
        StatusCode::NOT_FOUND,
        "root paths are not served"
    );

    let res = app.clone().oneshot(get("/store/", None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert_eq!(res.headers()[header::LOCATION], "/store");
    let res = app.clone().oneshot(get("/store", None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert_eq!(res.headers()[header::LOCATION], "/store/setup");

    let res = app
        .clone()
        .oneshot(get("/store/setup", None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(
        body.contains("action=\"/store/setup\"") && body.contains("href=\"/store/static/mms.css\""),
        "links carry the prefix: {body}"
    );

    let res = app.clone().oneshot(form("POST", "/store/setup", "email=admin%40example.com&name=Admin&password=correct-horse-battery&password_repeat=correct-horse-battery", None)).await.unwrap();
    assert_eq!(res.headers()[header::LOCATION], "/store/admin");
    let cookie = cookie_of(&res);

    let res = app
        .clone()
        .oneshot(get("/store/admin", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert!(text(res).await.contains("href=\"/store/admin/bridges\""));

    let res = app
        .clone()
        .oneshot(get("/store/admin", None))
        .await
        .unwrap();
    assert_eq!(res.headers()[header::LOCATION], "/store/admin/login");

    let res = app
        .clone()
        .oneshot(get("/store/embed.js", None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
}

/// The bundled packages declare their site in mms.toml and sign admins in without the setup wizard.
#[tokio::test]
async fn config_declared_bridge_with_admin_sso() {
    let tmp = std::env::temp_dir().join(format!("mms-http-{}", uuid::Uuid::new_v4()));
    let mut config =
        mms_core::config::Config::generate(tmp, "127.0.0.1:0", "https://www.example.com/mms");
    config.bridges.push(mms_core::config::BridgeConfig {
        uuid: "11111111-2222-4333-8444-555555555555".into(),
        name: "Bundled site".into(),
        host: "joomla".into(),
        origin: "https://www.example.com".into(),
        secret: "s3cret-from-the-plugin".into(),
        admin_sso: true,
    });
    config.validate().unwrap();
    let db = mms_core::db::Db::memory().await.unwrap();
    let st = app::AppState::new(config, db).unwrap();
    assert_eq!(routes::bridges::sync_from_config(&st).await.unwrap(), 1);
    assert_eq!(
        routes::bridges::sync_from_config(&st).await.unwrap(),
        1,
        "upsert is idempotent"
    );
    let app = app::router(st.clone());

    let signer = mms_core::signer::Signer::from_shared_secret("s3cret-from-the-plugin");
    let exp = chrono::Utc::now().timestamp() + 60;
    let token = signer.sign_raw(format!(r#"{{"sub":"1","email":"owner@example.com","name":"Owner","host":"joomla","role":"admin","exp":{exp}}}"#).as_bytes());
    let res = app
        .clone()
        .oneshot(get(
            &format!(
                "/mms/sso?site=11111111-2222-4333-8444-555555555555&token={token}&return=%2Fadmin"
            ),
            None,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert_eq!(res.headers()[header::LOCATION], "/mms/admin");
    let cookie = cookie_of(&res);
    assert!(cookie.contains("mms_session="));
    let res = app
        .clone()
        .oneshot(get("/mms/admin", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(
        res.status(),
        StatusCode::OK,
        "host administrator became a server administrator"
    );

    // Embeds work for the declared site with its origin policy.
    let res = app
        .clone()
        .oneshot(get(
            "/mms/embed/showcase?site=11111111-2222-4333-8444-555555555555",
            None,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(
        res.headers()[header::CONTENT_SECURITY_POLICY],
        "frame-ancestors 'self' https://www.example.com"
    );

    // A plain member token never gains admin rights.
    let member = signer.sign_raw(
        format!(r#"{{"sub":"2","email":"m@example.com","name":"M","host":"joomla","exp":{exp}}}"#)
            .as_bytes(),
    );
    let res = app
        .clone()
        .oneshot(get(
            &format!("/mms/sso?site=11111111-2222-4333-8444-555555555555&token={member}"),
            None,
        ))
        .await
        .unwrap();
    let c2 = cookie_of(&res);
    let res = app
        .clone()
        .oneshot(get("/mms/admin", Some(&c2)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
}

fn multipart(boundary: &str, csrf: &str, private: bool, files: &[(&str, &[u8])]) -> Vec<u8> {
    let mut body = Vec::new();
    let mut part = |name: &str, filename: Option<&str>, ctype: Option<&str>, data: &[u8]| {
        body.extend_from_slice(
            format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"").as_bytes(),
        );
        if let Some(f) = filename {
            body.extend_from_slice(format!("; filename=\"{f}\"").as_bytes());
        }
        body.extend_from_slice(b"\r\n");
        if let Some(c) = ctype {
            body.extend_from_slice(format!("Content-Type: {c}\r\n").as_bytes());
        }
        body.extend_from_slice(b"\r\n");
        body.extend_from_slice(data);
        body.extend_from_slice(b"\r\n");
    };
    part("_csrf", None, None, csrf.as_bytes());
    part("private", None, None, if private { b"1" } else { b"0" });
    for (name, data) in files {
        part("files", Some(name), Some("application/octet-stream"), data);
    }
    body.extend_from_slice(format!("--{boundary}--\r\n").as_bytes());
    body
}

fn png_bytes(w: u32, h: u32) -> Vec<u8> {
    let img = image::RgbImage::from_fn(w, h, |x, y| {
        image::Rgb([(x % 255) as u8, (y % 255) as u8, 90])
    });
    let mut buf = std::io::Cursor::new(Vec::new());
    image::DynamicImage::ImageRgb8(img)
        .write_to(&mut buf, image::ImageFormat::Png)
        .unwrap();
    buf.into_inner()
}

async fn admin_session(app: &axum::Router) -> (String, String) {
    let res = app.clone().oneshot(form("POST", "/setup", "email=admin%40example.com&name=Admin&password=correct-horse-battery&password_repeat=correct-horse-battery", None)).await.unwrap();
    let cookie = cookie_of(&res);
    let res = app
        .clone()
        .oneshot(get("/admin", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    let csrf = body
        .split("name=\"_csrf\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    (cookie, csrf)
}

#[tokio::test]
async fn phase_one_media_products_showcase_player_flow() {
    let st = state().await;
    let app = app::router(st.clone());
    let (cookie, csrf) = admin_session(&app).await;

    // A site for embeds.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/bridges",
            &format!("_csrf={csrf}&name=Site&host=wordpress&origin=https%3A%2F%2Fwww.example.com"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let body = text(res).await;
    let site = body
        .split("<dt>Site ID</dt><dd><code>")
        .nth(1)
        .unwrap()
        .split('<')
        .next()
        .unwrap()
        .to_string();

    // Upload two images (one fake) in one batch through the admin form.
    let boundary = "----mmsboundary";
    let body = multipart(
        boundary,
        &csrf,
        false,
        &[
            ("Studio_Lighting.png", &png_bytes(800, 450)),
            ("bogus.jpg", b"not an image"),
        ],
    );
    let req = Request::builder()
        .method("POST")
        .uri("/admin/media/upload")
        .header(header::COOKIE, &cookie)
        .header(
            header::CONTENT_TYPE,
            format!("multipart/form-data; boundary={boundary}"),
        )
        .body(Body::from(body))
        .unwrap();
    let res = app.clone().oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let loc = res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .to_string();
    assert!(
        loc.contains("1+uploaded") && loc.contains("bogus.jpg"),
        "one stored, one refused: {loc}"
    );

    // The thumbnail job runs (the worker would do this in the background).
    let (items, total) = st
        .media
        .list(&mms_core::media::MediaQuery {
            per_page: 10,
            page: 1,
            ..Default::default()
        })
        .await
        .unwrap();
    assert_eq!(total, 1);
    let m = &items[0];
    assert_eq!(m.status, "processing");
    let job = st.jobs.claim().await.unwrap().unwrap();
    routes::worker::run(&st, &job.r#type, job.args.as_deref().unwrap())
        .await
        .unwrap();
    st.jobs.complete(job.id).await.unwrap();
    let m = st.media.by_id(m.id).await.unwrap().unwrap();
    assert_eq!(m.status, "ready");
    let thumb = m.thumbnail_path.clone().unwrap();

    // Library list and detail render; the thumbnail is served publicly with caching.
    let res = app
        .clone()
        .oneshot(get("/admin/media?q=lighting", Some(&cookie)))
        .await
        .unwrap();
    let status = res.status();
    let body = text(res).await;
    assert!(
        body.contains("Studio Lighting") && body.contains(&format!("/media/{thumb}")),
        "status {status}"
    );
    let res = app
        .clone()
        .oneshot(get(&format!("/media/{thumb}"), None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(res.headers()[header::CONTENT_TYPE], "image/jpeg");
    let res = app
        .clone()
        .oneshot(get("/media/../mms.toml", None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND, "no path traversal");
    let res = app
        .clone()
        .oneshot(get(&format!("/admin/media/{}", m.uuid), Some(&cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("SHA-256"));

    // Metadata edit is searchable afterwards.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/media/{}", m.uuid),
            &format!("_csrf={csrf}&title=Lighting+lesson&alt=A+lamp&caption=&tags=studio"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get("/admin/media?q=lamp", Some(&cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Lighting lesson"));

    // Create a category and an image product through the admin form.
    app.clone()
        .oneshot(form(
            "POST",
            "/admin/categories",
            &format!("_csrf={csrf}&name=Textures"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let cat_id: i64 = sqlx::query_scalar("SELECT id FROM categories WHERE slug = 'textures'")
        .fetch_one(&st.db.pool)
        .await
        .unwrap();
    let res = app
        .clone()
        .oneshot(get("/admin/products/new?type=image", Some(&cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Resolutions for sale"));
    let res = app.clone().oneshot(form("POST", "/admin/products", &format!("_csrf={csrf}&type=image&title=Coastal+Textures&description=Forty+textures&price=29&currency=USD&media_id={}&status=published&featured=1&cat_{cat_id}=1&s_resolutions=1920,original&s_licence=Commercial", m.id), Some(&cookie))).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER, "product created");
    let p = st
        .products
        .by_slug("coastal-textures")
        .await
        .unwrap()
        .unwrap();
    assert_eq!(p.price_cents, 2900);
    assert_eq!(p.setting("resolutions"), "1920,original");
    // Video products need a media file; the form reports it instead of crashing.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/products",
            &format!("_csrf={csrf}&type=video&title=No+file&price=1&status=draft"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains("need a media file"));
    let res = app
        .clone()
        .oneshot(get("/admin/products", Some(&cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Coastal Textures"));

    // Showcase: card with thumbnail, price, category filter, search, sorting, list view; product page.
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/showcase?site={site}"), None))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("Coastal Textures")
            && body.contains(&thumb)
            && body.contains("USD 29.00")
            && body.contains("Textures"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/showcase?site={site}&category=textures&sort=price_asc&view=list"),
            None,
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains("Coastal Textures"));
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/showcase?site={site}&q=nothing-like-this"),
            None,
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains("Nothing matches"));
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/product/coastal-textures?site={site}"),
            None,
        ))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("Coastal Textures")
            && body.contains("Buy")
            && body.contains("Sign in")
            && body.contains("Licence")
    );
    assert_eq!(
        st.products.by_id(p.id).await.unwrap().unwrap().views,
        1,
        "views counted"
    );

    // A customer registers, sees an empty My media, cannot open the player.
    let res = app.clone().oneshot(form("POST", "/register", "name=Shopper&email=shopper%40example.com&password=a-strong-passphrase&return=%2Faccount", None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert_eq!(res.headers()[header::LOCATION], "/account");
    let shopper = cookie_of(&res);
    let res = app
        .clone()
        .oneshot(get("/account", Some(&shopper)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Nothing here yet"));
    let res = app
        .clone()
        .oneshot(get("/embed/player/coastal-textures", Some(&shopper)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(get("/admin/media", Some(&shopper)))
        .await
        .unwrap();
    assert_eq!(
        res.status(),
        StatusCode::FORBIDDEN,
        "customers never reach the admin"
    );

    // The admin grants access manually; the player page now serves a signed link.
    let shopper_uuid: String =
        sqlx::query_scalar("SELECT uuid FROM users WHERE email = 'shopper@example.com'")
            .fetch_one(&st.db.pool)
            .await
            .unwrap();
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/customers/{shopper_uuid}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains("Grant access manually"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/customers/{shopper_uuid}/grant"),
            &format!("_csrf={csrf}&scope=product&product_id={}&days=30", p.id),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get("/account", Some(&shopper)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Coastal Textures"));
    let res = app
        .clone()
        .oneshot(get("/embed/player/coastal-textures", Some(&shopper)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    let signed = body
        .split("src=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    assert!(signed.starts_with("/m/"), "signed media link: {signed}");

    // Signed delivery honours ranges and refuses other users and expired links.
    let res = app
        .clone()
        .oneshot(get(&signed, Some(&shopper)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(res.headers()[header::CONTENT_TYPE], "image/png");
    assert_eq!(res.headers()[header::CACHE_CONTROL], "private, no-store");
    let req = Request::builder()
        .uri(&signed)
        .header(header::COOKIE, &shopper)
        .header(header::RANGE, "bytes=0-3")
        .body(Body::empty())
        .unwrap();
    let res = app.clone().oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::PARTIAL_CONTENT);
    assert_eq!(res.headers()[header::CONTENT_LENGTH], "4");
    assert!(res.headers()[header::CONTENT_RANGE]
        .to_str()
        .unwrap()
        .starts_with("bytes 0-3/"));
    assert_eq!(&bytes(res).await[..4], b"\x89PNG");
    let res = app.clone().oneshot(get(&signed, None)).await.unwrap();
    assert_eq!(
        res.status(),
        StatusCode::FORBIDDEN,
        "token bound to the customer"
    );
    let res = app
        .clone()
        .oneshot(get("/m/not-a-token", Some(&shopper)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);

    // Playback sessions and ratings through the API.
    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/playback/session")
        .header(header::COOKIE, &shopper)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            r#"{"product":"coastal-textures","player":"plyr"}"#,
        ))
        .unwrap();
    let res = app.clone().oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let session = text(res)
        .await
        .split("\"session\":\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/playback/heartbeat")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(format!(
            r#"{{"session":"{session}","position_ms":42000,"duration_ms":90000,"ended":true}}"#
        )))
        .unwrap();
    assert_eq!(
        app.clone().oneshot(req).await.unwrap().status(),
        StatusCode::OK
    );
    let pos: i64 = sqlx::query_scalar("SELECT position_ms FROM playback_sessions WHERE uuid = ?")
        .bind(&session)
        .fetch_one(&st.db.pool)
        .await
        .unwrap();
    assert_eq!(pos, 42000);
    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/ratings")
        .header(header::COOKIE, &shopper)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            r#"{"product":"coastal-textures","stars":5,"review":"Superb"}"#,
        ))
        .unwrap();
    assert_eq!(
        app.clone().oneshot(req).await.unwrap().status(),
        StatusCode::OK
    );
    let req = Request::builder()
        .method("POST")
        .uri("/api/v1/ratings")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(r#"{"product":"coastal-textures","stars":1}"#))
        .unwrap();
    assert_eq!(
        app.clone().oneshot(req).await.unwrap().status(),
        StatusCode::UNAUTHORIZED,
        "anonymous cannot rate"
    );
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/product/coastal-textures?site={site}"),
            Some(&shopper),
        ))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("★ 5.0") && body.contains("Superb") && body.contains(">Open<"),
        "entitled view with rating: {body}"
    );

    // Player scripts and vendored players are embedded.
    for path in [
        "/static/mms-player.js",
        "/static/vendor/plyr.min.js",
        "/static/vendor/video.min.js",
        "/static/vendor/plyr.svg",
    ] {
        assert_eq!(
            app.clone().oneshot(get(path, None)).await.unwrap().status(),
            StatusCode::OK,
            "{path}"
        );
    }

    // Deleting media removes files and the product loses its file reference.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/media/{}/delete", m.uuid),
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert!(st.media.by_id(m.id).await.unwrap().is_none());
    assert!(st
        .products
        .by_id(p.id)
        .await
        .unwrap()
        .unwrap()
        .media_id
        .is_none());
}

/// Video thumbnails and durations need ffmpeg; this uses the Playwright build when present.
#[tokio::test]
async fn video_upload_gets_thumbnail_and_duration_with_ffmpeg() {
    let ffmpeg = "/opt/pw-browsers/ffmpeg-1011/ffmpeg-linux";
    if !std::path::Path::new(ffmpeg).exists() {
        eprintln!("ffmpeg not present; skipping");
        return;
    }
    let tmp = std::env::temp_dir().join(format!("mms-video-{}", uuid::Uuid::new_v4()));
    let mut config =
        mms_core::config::Config::generate(tmp.clone(), "127.0.0.1:0", "http://localhost:8090");
    config.media.ffmpeg_path = ffmpeg.to_string();
    let db = mms_core::db::Db::memory().await.unwrap();
    let st = app::AppState::new(config, db).unwrap();
    let sample = tmp.join("sample.mp4");
    std::fs::create_dir_all(&tmp).unwrap();
    let ok = std::process::Command::new(ffmpeg)
        .args([
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=6:size=320x240:rate=10",
            "-pix_fmt",
            "yuv420p",
        ])
        .arg(&sample)
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    if !ok {
        eprintln!("ffmpeg could not synthesise a sample; skipping");
        return;
    }
    let data = std::fs::read(&sample).unwrap();
    let m = st
        .media
        .store_upload("sample.mp4", &data, true, None)
        .await
        .unwrap();
    assert_eq!(m.r#type, "video");
    st.media.generate_thumbnails(m.id).await.unwrap();
    let m = st.media.by_id(m.id).await.unwrap().unwrap();
    assert_eq!(m.status, "ready");
    assert!(
        m.thumbnail_path
            .as_deref()
            .map(|t| t.ends_with("640.jpg"))
            .unwrap_or(false),
        "video thumbnail: {:?}",
        m.thumbnail_path
    );
    let d = m.duration_ms.unwrap_or(0);
    assert!((5500..=6500).contains(&d), "duration probed: {d}");
    std::fs::remove_dir_all(tmp).ok();
}
