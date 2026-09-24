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

/// Video thumbnails and durations need ffmpeg and a sample clip:
/// MMS_TEST_FFMPEG=/path/to/ffmpeg MMS_TEST_VIDEO=/path/to/clip.webm cargo test
#[tokio::test]
async fn video_upload_gets_thumbnail_and_duration_with_ffmpeg() {
    let (Ok(ffmpeg), Ok(sample)) = (
        std::env::var("MMS_TEST_FFMPEG"),
        std::env::var("MMS_TEST_VIDEO"),
    ) else {
        eprintln!("MMS_TEST_FFMPEG / MMS_TEST_VIDEO not set; skipping");
        return;
    };
    let tmp = std::env::temp_dir().join(format!("mms-video-{}", uuid::Uuid::new_v4()));
    let mut config =
        mms_core::config::Config::generate(tmp.clone(), "127.0.0.1:0", "http://localhost:8090");
    config.media.ffmpeg_path = ffmpeg;
    let db = mms_core::db::Db::memory().await.unwrap();
    let st = app::AppState::new(config, db).unwrap();
    let data = std::fs::read(&sample).unwrap();
    let name = std::path::Path::new(&sample)
        .file_name()
        .unwrap()
        .to_str()
        .unwrap();
    let m = st
        .media
        .store_upload(name, &data, true, None)
        .await
        .unwrap();
    assert_eq!(m.r#type, "video");
    st.media.generate_thumbnails(m.id).await.unwrap();
    let m = st.media.by_id(m.id).await.unwrap().unwrap();
    assert_eq!(m.status, "ready");
    assert!(
        m.thumbnail_path
            .as_deref()
            .map(|t| t.ends_with("320.jpg"))
            .unwrap_or(false),
        "video thumbnail: {:?}",
        m.thumbnail_path
    );
    for size in mms_core::media::THUMB_SIZES {
        assert!(st
            .media
            .public_root()
            .join("thumbs")
            .join(&m.uuid)
            .join(format!("{size}.jpg"))
            .exists());
    }
    assert!(
        m.duration_ms.unwrap_or(0) > 1000,
        "duration probed: {:?}",
        m.duration_ms
    );
    std::fs::remove_dir_all(tmp).ok();
}

fn json_req(method: &str, uri: &str, body: &str, cookie: &str, csrf: &str) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header(header::CONTENT_TYPE, "application/json")
        .header(header::COOKIE, cookie)
        .header("x-mms-csrf", csrf)
        .body(Body::from(body.to_string()))
        .unwrap()
}

#[tokio::test]
async fn phase_two_widgets_templates_schemes_and_site_templates() {
    let st = state().await;
    let app = app::router(st.clone());
    let (cookie, csrf) = admin_session(&app).await;

    // A site so widget embeds have an origin to trust.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/bridges",
            &format!("_csrf={csrf}&name=Site&host=joomla&origin=https%3A%2F%2Fwww.example.com"),
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

    // The template gallery lists all 35 built-in widget templates and the 12 site templates.
    let res = app
        .clone()
        .oneshot(get("/admin/templates", Some(&cookie)))
        .await
        .unwrap();
    let status = res.status();
    let body = text(res).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(
        body.matches("template-card").count(),
        35,
        "35 widget templates"
    );
    let res = app
        .clone()
        .oneshot(get("/admin/site-templates", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert_eq!(body.matches("/apply\"").count(), 12, "12 site templates");

    // A template preview renders real HTML.
    let res = app
        .clone()
        .oneshot(get("/admin/templates/video-hero/preview", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert!(text(res).await.contains("Watch the masterclass"));

    // Create a widget from a template; it opens in the builder.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/widgets",
            &format!("_csrf={csrf}&name=Home+hero&template=video-hero"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let loc = res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .to_string();
    let uuid = loc.rsplit('/').next().unwrap().to_string();
    assert!(loc.starts_with("/admin/widgets/"));
    let res = app.clone().oneshot(get(&loc, Some(&cookie))).await.unwrap();
    let status = res.status();
    let body = text(res).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert!(body.contains("id=\"bb-data\"") && body.contains("mms-builder.js"));

    // Unpublished widgets are not embeddable.
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/widget/{uuid}?site={site}"), None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);

    // The builder saves through the JSON API with the CSRF header; without it the save is refused.
    let definition = r#"{"schema_version":1,"root":{"id":"root","kind":"container","props":{},"children":[{"id":"h","kind":"text","props":{"text":"Hello from the builder","style":"heading"},"animation":{"kind":"fade","trigger":"in-view","delay":0}},{"id":"b","kind":"button","props":{"label":"Buy now","href":"https://www.example.com/store"}}]}}"#;
    let save = format!(
        r#"{{"name":"Home hero","definition":{definition},"custom_css":".mms-text{{color:red}} body{{background:url(http://evil.example/x.png)}}","theme":"auto","scheme":"night","status":"published"}}"#
    );
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            &format!("/api/v1/widgets/{uuid}"),
            &save,
            &cookie,
            "wrong",
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            &format!("/api/v1/widgets/{uuid}"),
            &save,
            &cookie,
            &csrf,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(body.contains("\"status\":\"published\""), "{body}");

    // A broken definition is rejected with a 400, not a 500.
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            &format!("/api/v1/widgets/{uuid}"),
            r#"{"name":"x","definition":{"root":{"kind":"spaceship"}}}"#,
            &cookie,
            &csrf,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::BAD_REQUEST);

    // Live preview renders unsaved definitions.
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            &format!("/api/v1/widgets/{uuid}/preview"),
            &format!(r#"{{"definition":{definition},"scheme":"warm"}}"#),
            &cookie,
            &csrf,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(body.contains("Hello from the builder") && body.contains("Buy now"));

    // Versions accumulate and can be restored.
    let res = app
        .clone()
        .oneshot(get(
            &format!("/api/v1/widgets/{uuid}/versions"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("\"version\":1") && body.contains("\"version\":2"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/widgets/{uuid}/restore"),
            &format!("_csrf={csrf}&version=1"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    // Restoring re-publishes nothing: put it back to the built version and publish again.
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            &format!("/api/v1/widgets/{uuid}"),
            &save,
            &cookie,
            &csrf,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    // Published widgets embed for registered sites only, with a frame-ancestors policy,
    // scoped custom CSS and the dangerous url() stripped.
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/widget/{uuid}?site=unknown"), None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/widget/{uuid}?site={site}"), None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(
        res.headers()[header::CONTENT_SECURITY_POLICY],
        "frame-ancestors 'self' https://www.example.com"
    );
    let body = text(res).await;
    assert!(body.contains("Hello from the builder"));
    assert!(body.contains("mms-widget.js"));
    assert!(
        !body.contains("evil.example"),
        "non-https url() must be stripped"
    );
    assert!(
        body.contains(&format!(".mms-w-{uuid} .mms-text{{color:red}}")),
        "custom css is scoped: {body}"
    );
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/widget?site={site}&id={uuid}"), None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    // Exports: CMS snippets, a standalone HTML file and a template file.
    for (target, needle) in [
        (
            "wordpress",
            format!("[mms_embed kind=\"widget\" id=\"{uuid}\"]"),
        ),
        ("joomla", format!("{{mms_embed kind=widget id={uuid}}}")),
        ("html", "<!doctype html>".to_string()),
        ("json", "\"format\": \"mmstpl\"".to_string()),
    ] {
        let res = app
            .clone()
            .oneshot(get(
                &format!("/admin/widgets/{uuid}/export/{target}"),
                Some(&cookie),
            ))
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::OK, "{target}");
        assert!(res.headers()[header::CONTENT_DISPOSITION]
            .to_str()
            .unwrap()
            .starts_with("attachment;"));
        let body = text(res).await;
        assert!(body.contains(&needle), "{target}: {body}");
        if target == "html" {
            assert!(body.contains("http://localhost:8090/static/mms.css"));
        }
    }

    // Save as a user template, export it, re-import it, then build a widget from it.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/widgets/{uuid}/save-template"),
            &format!("_csrf={csrf}&name=My+hero&category=custom"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get("/admin/templates", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("My hero") && body.contains("/admin/templates/user-my-hero/export"));
    let user_slug = "user-my-hero".to_string();
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/templates/{user_slug}/export"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let exported = text(res).await;
    assert!(exported.contains("\"format\": \"mmstpl\""));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/templates/import",
            &format!(
                "_csrf={csrf}&json={}",
                routes::media::urlencoding(&exported.replace("My hero", "Imported hero"))
            ),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert!(res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .contains("Template+imported"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/templates/import",
            &format!("_csrf={csrf}&json=%7B%22format%22%3A%22other%22%7D"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .contains("error="));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/widgets",
            &format!("_csrf={csrf}&template={user_slug}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert!(res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .starts_with("/admin/widgets/"));

    // Widgets list shows both, filterable by status.
    let res = app
        .clone()
        .oneshot(get("/admin/widgets?status=published", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("Home hero") && !body.contains("My hero</a>"));

    // Duplicate and delete.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/widgets/{uuid}/duplicate"),
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let copy = res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .rsplit('/')
        .next()
        .unwrap()
        .to_string();
    assert_ne!(copy, uuid);
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/widgets/{copy}/delete"),
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get(&format!("/admin/widgets/{copy}"), Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);

    // Colour schemes: built-ins plus a user scheme with validated hex values; brand kit saves.
    let res = app
        .clone()
        .oneshot(get("/admin/schemes", Some(&cookie)))
        .await
        .unwrap();
    let status = res.status();
    let body = text(res).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    for s in [
        "<code>default</code>",
        "<code>night</code>",
        "<code>warm</code>",
        "<code>forest</code>",
        "<code>plum</code>",
        "<code>mono</code>",
    ] {
        assert!(body.contains(s), "{s}");
    }
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/schemes",
            &format!("_csrf={csrf}&name=Ocean&accent=%231d6fa5&accent-2=%2300a3a3&bg=%23f4f9fc&surface=%23ffffff&text=%23102030&muted=%23607080"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .contains("Scheme+saved"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/schemes",
            &format!("_csrf={csrf}&name=Bad&accent=red&accent-2=%2300a3a3&bg=%23f4f9fc&surface=%23ffffff&text=%23102030&muted=%23607080"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .contains("error="));
    let res = app
        .clone()
        .oneshot(get("/admin/schemes", Some(&cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Ocean"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/schemes/user-ocean/delete",
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);

    // Site templates: applying creates published widgets, rollback deletes them again.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/site-templates/photographer/apply",
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert!(res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .contains("5+widgets+created"));
    let res = app
        .clone()
        .oneshot(get("/admin/widgets?status=published", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("Home · ") && body.contains("Prints · "));
    let res = app
        .clone()
        .oneshot(get("/admin/site-templates", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("/admin/site-applications/1/rollback"));
    let res = app
        .clone()
        .oneshot(get(
            "/admin/site-templates/photographer/export",
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/site-applications/1/rollback",
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get("/admin/widgets", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(!body.contains("Home · "), "rolled back widgets are gone");
    assert!(
        body.contains("Home hero"),
        "hand-built widgets survive a rollback"
    );

    // Builder and widget assets are embedded in the binary.
    for f in ["mms-builder.js", "mms-builder.css", "mms-widget.js"] {
        let res = app
            .clone()
            .oneshot(get(&format!("/static/{f}"), None))
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::OK, "{f}");
    }

    // The site-wide scheme moved to the template's scheme.
    assert_eq!(st.settings.get("general.scheme").await.unwrap(), "warm");
}

/// Merges every Set-Cookie of a response into an existing cookie header value.
fn merge_cookies(existing: &str, res: &axum::response::Response) -> String {
    let mut jar: Vec<(String, String)> = existing
        .split(';')
        .filter_map(|c| c.trim().split_once('='))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
    for v in res.headers().get_all(header::SET_COOKIE) {
        let first = v.to_str().unwrap().split(';').next().unwrap();
        if let Some((k, val)) = first.split_once('=') {
            jar.retain(|(name, _)| name != k);
            if !val.is_empty() {
                jar.push((k.to_string(), val.to_string()));
            }
        }
    }
    jar.iter()
        .map(|(k, v)| format!("{k}={v}"))
        .collect::<Vec<_>>()
        .join("; ")
}

fn location(res: &axum::response::Response) -> String {
    res.headers()[header::LOCATION]
        .to_str()
        .unwrap()
        .to_string()
}

async fn customer_csrf(app: &axum::Router, cookie: &str) -> String {
    let res = app
        .clone()
        .oneshot(get("/checkout", Some(cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    body.split("name=\"_csrf\" value=\"")
        .nth(1)
        .map(|s| s.split('"').next().unwrap().to_string())
        .unwrap_or_default()
}

#[tokio::test]
async fn phase_three_cart_checkout_orders_receipts_subscriptions_pages_api() {
    let st = state().await;
    let app = app::router(st.clone());
    let (admin_cookie, csrf) = admin_session(&app).await;
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/bridges",
            &format!("_csrf={csrf}&name=Site&host=wordpress&origin=https%3A%2F%2Fwww.example.com"),
            Some(&admin_cookie),
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

    // Catalogue: a film, a 30-day pass, a recurring pass, a private-page product.
    let now = mms_core::now();
    for (uuid, slug, t, title, price, settings) in [
        ("p1", "film", "video", "Film", 4900, "{}"),
        (
            "p2",
            "pass",
            "site_pass",
            "Month pass",
            9900,
            r#"{"validity":"days","days":"30","scope":"site"}"#,
        ),
        (
            "p3",
            "club",
            "site_pass",
            "Club",
            1900,
            r#"{"validity":"recurring","interval":"month","scope":"site"}"#,
        ),
        ("p4", "vault", "private_page", "Vault access", 1000, "{}"),
        ("p5", "free-guide", "pdf", "Free guide", 0, "{}"),
    ] {
        sqlx::query("INSERT INTO products (uuid, slug, type, title, price_cents, currency, settings, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'USD', ?, 'published', ?, ?)")
            .bind(uuid).bind(slug).bind(t).bind(title).bind(price).bind(settings).bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();
    }
    // Coupon and tax from the admin pages.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/coupons",
            &format!("_csrf={csrf}&code=save10&kind=percent&amount=10&max_uses=5"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Coupon+created"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/tax",
            &format!("_csrf={csrf}&country=DE&name=VAT&rate=19"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Tax+rate+saved"));

    // A guest adds the film through the embedded Buy button, then registers.
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/checkout?site={site}&product=film"),
            None,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let mut cookie = merge_cookies("", &res);
    assert!(cookie.contains("mms_cart="));
    let body = text(res).await;
    assert!(
        body.contains("1 × Film")
            && body.contains("Continue to secure checkout")
            && body.contains("target=\"_top\"")
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/register",
            "name=Ada&email=ada%40example.com&password=a-strong-passphrase&return=%2Fcheckout",
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    cookie = merge_cookies(&cookie, &res);
    // The guest cart follows the new account; the pass joins it.
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/add", "product=pass", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(location(&res), "/cart");
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/coupon", "code=SAVE10", Some(&cookie)))
        .await
        .unwrap();
    assert!(location(&res).contains("Coupon+applied"));
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/country", "country=de", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(location(&res), "/cart");
    let res = app
        .clone()
        .oneshot(get("/cart", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("Film") && body.contains("Month pass"),
        "{body}"
    );
    assert!(
        body.contains("USD 148.00")
            && body.contains("-USD 14.80")
            && body.contains("VAT")
            && body.contains("USD 158.51"),
        "{body}"
    );

    // Checkout offers the test gateway (test mode is on by default) and completes.
    let res = app
        .clone()
        .oneshot(get("/checkout", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(body.contains("Test payment") && body.contains("name=\"gateway\" value=\"test\""));
    let ccsrf = body
        .split("name=\"_csrf\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={ccsrf}&gateway=test"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let loc = location(&res);
    assert!(
        loc.starts_with("http://localhost:8090/checkout/test/"),
        "{loc}"
    );
    let order_uuid = loc.rsplit('/').next().unwrap().to_string();
    let res = app
        .clone()
        .oneshot(get(&format!("/checkout/test/{order_uuid}"), Some(&cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Pay USD 158.51"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/checkout/test/{order_uuid}"),
            &format!("_csrf={ccsrf}&result=paid"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let ret = location(&res);
    let res = app.clone().oneshot(get(&ret, Some(&cookie))).await.unwrap();
    assert_eq!(location(&res), format!("/checkout/done/{order_uuid}"));
    let res = app
        .clone()
        .oneshot(get(&format!("/checkout/done/{order_uuid}"), Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("Thank you") && body.contains("Receipt MMS-"),
        "{body}"
    );
    // Access granted: film and the whole library; cart emptied; coupon counted.
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/product/film?site={site}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains(">Open<"));
    let res = app
        .clone()
        .oneshot(get("/account", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("Your site pass is active"));
    let res = app
        .clone()
        .oneshot(get("/cart", Some(&cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Your cart is empty"));
    // Receipt PDF and order history for the customer.
    let res = app
        .clone()
        .oneshot(get(
            &format!("/account/receipts/{order_uuid}/pdf"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.headers()[header::CONTENT_TYPE], "application/pdf");
    assert!(bytes(res).await.starts_with(b"%PDF"));
    let res = app
        .clone()
        .oneshot(get("/account/orders", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("ORD-") && body.contains("paid") && body.contains("MMS-"));
    // A second customer cannot read that receipt.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/register",
            "name=Bob&email=bob%40example.com&password=another-passphrase",
            None,
        ))
        .await
        .unwrap();
    let bob = merge_cookies("", &res);
    let res = app
        .clone()
        .oneshot(get(
            &format!("/account/receipts/{order_uuid}/pdf"),
            Some(&bob),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);

    // Admin sees the order, refunds it, access goes away.
    let res = app
        .clone()
        .oneshot(get("/admin/orders?status=paid", Some(&admin_cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("ada@example.com") && body.contains("USD 158.51"));
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/orders/{order_uuid}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("Refund and revoke access") && body.contains("VAT (19"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/orders/{order_uuid}/refund"),
            &format!("_csrf={csrf}&reason=test"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Refunded"));
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/product/film?site={site}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(!text(res).await.contains(">Open<"));

    // Free items complete without a gateway.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/cart/add",
            "product=free-guide",
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let ccsrf = customer_csrf(&app, &cookie).await;
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={ccsrf}&gateway="),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).starts_with("/checkout/done/"));
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/product/free-guide?site={site}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains(">Open<"));

    // Recurring pass: a subscription record, cancel at period end, renewal and end via webhooks.
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/add", "product=club", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get("/checkout", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("recurring") || body.contains("Test payment"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={ccsrf}&gateway=test"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let club_order = location(&res).rsplit('/').next().unwrap().to_string();
    let res = app
        .clone()
        .oneshot(get(
            &format!("/checkout/return/test?order={club_order}&result=paid"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get("/account/subscriptions", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("Club") && body.contains("every month") && body.contains("Cancel renewal"),
        "{body}"
    );
    let sub_uuid = body
        .split("/account/subscriptions/")
        .nth(1)
        .unwrap()
        .split('/')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/account/subscriptions/{sub_uuid}/cancel"),
            &format!("_csrf={ccsrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("will+not+renew"));
    let renew = serde_json::json!({ "id": "evt_renew_1", "kind": "renewed", "subscription_id": format!("sub_test_{club_order}"), "period_end": "2030-01-01T00:00:00Z" }).to_string();
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/webhooks/test")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(renew.clone()))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/webhooks/test")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(renew))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(
        text(res).await,
        "duplicate",
        "webhooks are idempotent by event id"
    );
    let ents = st.entitlements.for_user(2).await.unwrap();
    assert!(ents.iter().any(
        |e| e.source == "subscription" && e.ends_at.as_deref() == Some("2030-01-01T00:00:00Z")
    ));
    let ended = serde_json::json!({ "id": "evt_end_1", "kind": "ended", "subscription_id": format!("sub_test_{club_order}") }).to_string();
    app.clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/webhooks/test")
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(ended))
                .unwrap(),
        )
        .await
        .unwrap();
    let ents = st.entitlements.for_user(2).await.unwrap();
    assert!(ents
        .iter()
        .filter(|e| e.source == "subscription")
        .all(|e| e.status == "revoked"));
    assert!(
        !st.entitlements
            .check(
                2,
                &mms_core::entitlements::Subject::Product(1),
                &mms_core::now()
            )
            .await
            .unwrap(),
        "an ended subscription takes the pass with it"
    );
    let res = app
        .clone()
        .oneshot(get("/webhooks/stripe", None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::METHOD_NOT_ALLOWED);
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/webhooks/stripe")
                .body(Body::from("{}"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(
        res.status(),
        StatusCode::NOT_FOUND,
        "Stripe is not configured"
    );

    // Passes admin: holders, extend.
    let res = app
        .clone()
        .oneshot(get("/admin/passes", Some(&admin_cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("ada@example.com") && body.contains("Extend days"));
    let eid = body
        .split("/admin/passes/")
        .nth(1)
        .unwrap()
        .split('/')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/passes/{eid}/extend"),
            &format!("_csrf={csrf}&days=10"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Pass+extended"));

    // Private page: invite-only with a key, dual-action signup, then a paid page through checkout.
    let res = app.clone().oneshot(form("POST", "/admin/pages", &format!("_csrf={csrf}&title=Members+vault&content=%23+Secret%0A%0AHello+**members**&agreement=Be+nice.%0A%0ADo+not+share.&signup_template=dual_action&protection=invite&status=published"), Some(&admin_cookie))).await.unwrap();
    let page_uuid = location(&res)
        .split("/admin/pages/")
        .nth(1)
        .unwrap()
        .split('?')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/pages/{page_uuid}/keys"),
            &format!("_csrf={csrf}&max_uses=1"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let key = location(&res).split("new_key=").nth(1).unwrap().to_string();
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{page_uuid}?site={site}"), None))
        .await
        .unwrap();
    let status = res.status();
    if status != StatusCode::OK {
        panic!("page gate {status}: {}", text(res).await);
    }
    assert_eq!(
        res.headers()[header::CONTENT_SECURITY_POLICY],
        "frame-ancestors 'self' https://www.example.com"
    );
    assert!(text(res).await.contains("Sign in or create"));
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{page_uuid}"), Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    let page = st.pages.by_uuid(&page_uuid).await.unwrap().unwrap();
    let decision = st
        .pages
        .gate(&page, Some(2), "ip:x", false, &mms_core::now())
        .await
        .unwrap();
    assert!(
        body.contains("needs an access key"),
        "gate={decision:?} protection={} ents={:?}",
        page.protection,
        st.entitlements
            .for_user(2)
            .await
            .unwrap()
            .iter()
            .map(|e| (e.scope.clone(), e.scope_ref.clone(), e.status.clone()))
            .collect::<Vec<_>>()
    );
    let pcsrf = body
        .split("name=\"_csrf\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/page/{page_uuid}/key"),
            &format!("_csrf={pcsrf}&key=WRONG"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("not+valid"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/page/{page_uuid}/key"),
            &format!("_csrf={pcsrf}&key={key}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Key+accepted"));
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{page_uuid}"), Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("I have read the agreement")
            && body.contains("Be nice.")
            && body.contains("id=\"sig\""),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/page/{page_uuid}/sign"),
            &format!("_csrf={pcsrf}&name=Ada+Lovelace&agree=1"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(
        location(&res).contains("I+have+read"),
        "server enforces the template's confirmations"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/page/{page_uuid}/sign"),
            &format!("_csrf={pcsrf}&name=Ada+Lovelace&read=1&agree=1"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Thank+you"));
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{page_uuid}"), Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("<h1>Secret</h1>")
            && body.contains("Hello <b>members</b>")
            && body.contains("Licensed to ada@example.com"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(get("/account/agreements", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("Members vault") && body.contains("/pdf"));
    let ag = body
        .split("/account/agreements/")
        .nth(1)
        .unwrap()
        .split("/pdf")
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(get(&format!("/account/agreements/{ag}/pdf"), Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.headers()[header::CONTENT_TYPE], "application/pdf");
    assert!(bytes(res).await.starts_with(b"%PDF"));
    let res = app
        .clone()
        .oneshot(get(&format!("/account/agreements/{ag}/pdf"), Some(&bob)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/pages/{page_uuid}/signers.csv"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let csv = text(res).await;
    assert!(csv.starts_with("signed_at,name,email") && csv.contains("Ada Lovelace"));
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/pages/{page_uuid}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let body = text(res).await;
    let agreement_id = body
        .split("/signers/")
        .nth(1)
        .unwrap()
        .split('/')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/pages/{page_uuid}/signers/{agreement_id}/revoke"),
            &format!("_csrf={csrf}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Signer+revoked"));
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{page_uuid}"), Some(&cookie)))
        .await
        .unwrap();
    assert!(
        text(res).await.contains("needs an access key"),
        "revoking withdraws the page"
    );
    // Paid page: Bob (no site pass) signs, is sent to checkout, pays, then the page opens.
    // Ada, who holds a site pass, gets paid pages without paying again.
    let res = app.clone().oneshot(form("POST", "/admin/pages", &format!("_csrf={csrf}&title=Paid+vault&content=Paid+secret&agreement=Pay+first.&signup_template=checkbox&protection=paid&product_id=4&status=published"), Some(&admin_cookie))).await.unwrap();
    let paid_uuid = location(&res)
        .split("/admin/pages/")
        .nth(1)
        .unwrap()
        .split('?')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{paid_uuid}"), Some(&bob)))
        .await
        .unwrap();
    let body = text(res).await;
    let bcsrf = body
        .split("name=\"_csrf\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/page/{paid_uuid}/sign"),
            &format!("_csrf={bcsrf}&name=Bob+Builder&agree=1"),
            Some(&bob),
        ))
        .await
        .unwrap();
    assert_eq!(location(&res), "/checkout");
    let bob = merge_cookies(&bob, &res);
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{paid_uuid}"), Some(&bob)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Buy access"), "signed but unpaid");
    let res = app
        .clone()
        .oneshot(get("/checkout", Some(&bob)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("Vault access"), "{body}");
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={bcsrf}&gateway=test"),
            Some(&bob),
        ))
        .await
        .unwrap();
    let vault_order = location(&res).rsplit('/').next().unwrap().to_string();
    app.clone()
        .oneshot(get(
            &format!("/checkout/return/test?order={vault_order}&result=paid"),
            Some(&bob),
        ))
        .await
        .unwrap();
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{paid_uuid}"), Some(&bob)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Paid secret"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/page/{paid_uuid}/sign"),
            &format!("_csrf={pcsrf}&name=Ada+Lovelace&agree=1"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(
        location(&res).contains("Thank+you"),
        "site pass holders are not charged for paid pages"
    );
    let res = app
        .clone()
        .oneshot(get(&format!("/page/{paid_uuid}"), Some(&cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Paid secret"));
    // Declined payment cancels the order and keeps the cart.
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/add", "product=film", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={ccsrf}&gateway=test"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let bad_order = location(&res).rsplit('/').next().unwrap().to_string();
    let res = app
        .clone()
        .oneshot(get(
            &format!("/checkout/return/test?order={bad_order}&result=fail"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Declined"));
    assert_eq!(
        st.commerce
            .order_by_uuid(&bad_order)
            .await
            .unwrap()
            .unwrap()
            .status,
        "cancelled"
    );

    // API keys and outbound webhooks.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/integrations/keys",
            &format!("_csrf={csrf}&name=Zapier&scopes=read"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let api_key = location(&res).split("new_key=").nth(1).unwrap().to_string();
    let res = app
        .clone()
        .oneshot(get("/api/v1/orders", None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/v1/orders?status=paid")
                .header(header::AUTHORIZATION, format!("Bearer {api_key}"))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(body.contains("\"number\":\"ORD-") && body.contains(&club_order));
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/grants")
                .header(header::AUTHORIZATION, format!("Bearer {api_key}"))
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    r#"{"customer":"bob@example.com","product":"film"}"#,
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(
        res.status(),
        StatusCode::FORBIDDEN,
        "read keys cannot grant"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/integrations/keys",
            &format!("_csrf={csrf}&name=CRM&scopes=write"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let write_key = location(&res).split("new_key=").nth(1).unwrap().to_string();
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/v1/grants")
                .header(header::AUTHORIZATION, format!("Bearer {write_key}"))
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    r#"{"customer":"bob@example.com","product":"film"}"#,
                ))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/product/film?site={site}"), Some(&bob)))
        .await
        .unwrap();
    assert!(text(res).await.contains(">Open<"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/integrations/webhooks",
            &format!("_csrf={csrf}&url=http%3A%2F%2F127.0.0.1%3A9%2Fhook&ev_order.paid=1"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Webhook+added"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/integrations/webhooks/test",
            &format!("_csrf={csrf}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Test+event+queued"));
    let job = st.jobs.claim().await.unwrap().expect("a delivery job");
    assert_eq!(job.r#type, "webhook.deliver");
    assert!(
        routes::worker::run(&st, &job.r#type, job.args.as_deref().unwrap_or("{}"))
            .await
            .is_err(),
        "nothing listens on port 9"
    );
    let res = app
        .clone()
        .oneshot(get("/admin/integrations", Some(&admin_cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(body.contains("order.paid") && body.contains("whsec_") && body.contains("Zapier"));
    // Pass housekeeping job runs.
    routes::worker::run(&st, "passes.housekeeping", "{}")
        .await
        .unwrap();
}

fn multipart_fields(
    boundary: &str,
    fields: &[(&str, &str)],
    file: Option<(&str, &str, &[u8])>,
) -> Vec<u8> {
    let mut body = Vec::new();
    for (name, value) in fields {
        body.extend_from_slice(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").as_bytes());
    }
    if let Some((name, filename, data)) = file {
        body.extend_from_slice(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").as_bytes());
        body.extend_from_slice(data);
        body.extend_from_slice(b"\r\n");
    }
    body.extend_from_slice(format!("--{boundary}--\r\n").as_bytes());
    body
}

#[tokio::test]
async fn phase_four_marked_images_identify_violations_and_notices() {
    let st = state().await;
    let app = app::router(st.clone());
    let (admin_cookie, csrf) = admin_session(&app).await;

    // A private image and a product for it.
    let boundary = "----mmsp4";
    let body = multipart(
        boundary,
        &csrf,
        true,
        &[("Portrait.png", &png_bytes(640, 480))],
    );
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/admin/media/upload")
                .header(header::COOKIE, &admin_cookie)
                .header(
                    header::CONTENT_TYPE,
                    format!("multipart/form-data; boundary={boundary}"),
                )
                .body(Body::from(body))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let (items, _) = st
        .media
        .list(&mms_core::media::MediaQuery {
            per_page: 10,
            page: 1,
            ..Default::default()
        })
        .await
        .unwrap();
    let media = items[0].clone();
    let now = mms_core::now();
    sqlx::query("INSERT INTO products (uuid, slug, type, title, price_cents, currency, media_id, settings, status, created_at, updated_at) VALUES ('pp1', 'portrait', 'image', 'Portrait', 0, 'USD', ?, '{}', 'published', ?, ?)")
        .bind(media.id).bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();

    // A customer gets the free item and opens the viewer.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/register",
            "name=Ada&email=ada%40example.com&password=a-strong-passphrase",
            None,
        ))
        .await
        .unwrap();
    let mut cookie = merge_cookies("", &res);
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/add", "product=portrait", Some(&cookie)))
        .await
        .unwrap();
    cookie = merge_cookies(&cookie, &res);
    let ccsrf = customer_csrf(&app, &cookie).await;
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={ccsrf}&gateway="),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).starts_with("/checkout/done/"));
    let res = app
        .clone()
        .oneshot(get("/embed/player/portrait", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(
        body.contains("protected-image") && body.contains("carries a forensic mark"),
        "{body}"
    );
    let src = body
        .split("<img class=\"full\" src=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();

    // The delivered file is a per-viewer PNG with the session code inside.
    let res = app.clone().oneshot(get(&src, Some(&cookie))).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(res.headers()[header::CONTENT_TYPE], "image/png");
    assert_eq!(res.headers()[header::CONTENT_DISPOSITION], "inline");
    let delivered = bytes(res).await;
    let img = image::load_from_memory(&delivered).unwrap();
    let code = mms_core::protection::decode_lsb(&img).expect("invisible mark");
    let session = st.protection.by_code(code).await.unwrap().expect("session");
    assert_eq!(
        (session.user_id, session.media_id, session.kind.as_str()),
        (Some(2), Some(media.id), "image")
    );
    // Same viewer, same copy; the stamp text is burned in (pixels differ from the original).
    let res = app.clone().oneshot(get(&src, Some(&cookie))).await.unwrap();
    assert_eq!(bytes(res).await, delivered);
    assert_ne!(
        img.as_bytes(),
        image::load_from_memory(&png_bytes(640, 480))
            .unwrap()
            .to_rgba8()
            .as_raw()
            .as_slice()
    );
    // Another viewer's link does not work with this session.
    let res = app.clone().oneshot(get(&src, None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);

    // Protection dashboard lists the session; the identify tool names the viewer.
    let res = app
        .clone()
        .oneshot(get("/admin/protection", Some(&admin_cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("ada@example.com") && body.contains("Identify a leaked copy"),
        "{body}"
    );
    let b2 = "----mmsid";
    let body = multipart_fields(
        b2,
        &[("_csrf", &csrf)],
        Some(("file", "leak.png", &delivered)),
    );
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/admin/protection/identify")
                .header(header::COOKIE, &admin_cookie)
                .header(
                    header::CONTENT_TYPE,
                    format!("multipart/form-data; boundary={b2}"),
                )
                .body(Body::from(body))
                .unwrap(),
        )
        .await
        .unwrap();
    let loc = location(&res);
    assert!(
        loc.contains("Identified+by+invisible+mark") && loc.contains("ada%40example.com"),
        "{loc}"
    );
    let clean = png_bytes(64, 64);
    let body = multipart_fields(b2, &[("_csrf", &csrf)], Some(("file", "clean.png", &clean)));
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/admin/protection/identify")
                .header(header::COOKIE, &admin_cookie)
                .header(
                    header::CONTENT_TYPE,
                    format!("multipart/form-data; boundary={b2}"),
                )
                .body(Body::from(body))
                .unwrap(),
        )
        .await
        .unwrap();
    assert!(location(&res).contains("No+mark+found"));

    // Level 1 serves the original but still inline.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/settings",
            &format!("_csrf={csrf}&protection.image_level=1"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains("Settings saved."));
    // Rights owner for notices.
    st.settings
        .set("copyright.owner_name", "Ada Owner")
        .await
        .unwrap();
    st.settings
        .set("copyright.owner_email", "legal@example.com")
        .await
        .unwrap();

    // Scans page prepares searches (from the public thumbnail); recording keeps a history.
    routes::worker::run(&st, "thumbnail", &format!("{{\"media\":{}}}", media.id))
        .await
        .unwrap();
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/protection/scans?media={}", media.uuid),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("tineye.com/search") && body.contains("Videntifier"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/protection/scans",
            &format!(
                "_csrf={csrf}&media={}&service=tineye&matches=2&result=two+copies",
                media.uuid
            ),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Scan+recorded"));

    // A violation with the leaked file as evidence links to the viewer automatically.
    let b3 = "----mmsviol";
    let body = multipart_fields(
        b3,
        &[
            ("_csrf", &csrf),
            ("url", "https://pirate.example/gallery/1"),
            ("media", &media.uuid),
            ("note", "found on a forum"),
        ],
        Some(("evidence", "leak.png", &delivered)),
    );
    let res = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/admin/protection/violations")
                .header(header::COOKIE, &admin_cookie)
                .header(
                    header::CONTENT_TYPE,
                    format!("multipart/form-data; boundary={b3}"),
                )
                .body(Body::from(body))
                .unwrap(),
        )
        .await
        .unwrap();
    let loc = location(&res);
    assert!(loc.contains("linked+to+the+viewer"), "{loc}");
    let vuuid = loc
        .split("/admin/protection/violations/")
        .nth(1)
        .unwrap()
        .split('?')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/protection/violations/{vuuid}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("pirate.example")
            && body.contains("issued to <b>ada@example.com</b>")
            && body.contains("Generate DMCA notice"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/protection/violations/{vuuid}/notice"),
            &format!("_csrf={csrf}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Notice+generated"));
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/protection/violations/{vuuid}/notice.pdf"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.headers()[header::CONTENT_TYPE], "application/pdf");
    assert!(bytes(res).await.starts_with(b"%PDF"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/protection/violations/{vuuid}"),
            &format!("_csrf={csrf}&status=removed&note=host+complied"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Updated"));
    let res = app
        .clone()
        .oneshot(get(
            "/admin/protection/violations?status=removed",
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains("pirate.example"));
    let res = app
        .clone()
        .oneshot(get(
            &format!("/admin/protection/violations/{vuuid}/evidence"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.headers()[header::CONTENT_TYPE], "image/png");
    // Retention job runs.
    routes::worker::run(&st, "retention.prune", "{}")
        .await
        .unwrap();
}

#[tokio::test]
async fn phase_five_to_seven_currency_gateways_players_google_privacy_backups_roles() {
    let st = state().await;
    let app = app::router(st.clone());
    let (admin_cookie, csrf) = admin_session(&app).await;
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/bridges",
            &format!("_csrf={csrf}&name=Site&host=wordpress&origin=https%3A%2F%2Fwww.example.com"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let site = text(res)
        .await
        .split("<dt>Site ID</dt><dd><code>")
        .nth(1)
        .unwrap()
        .split('<')
        .next()
        .unwrap()
        .to_string();
    let now = mms_core::now();
    sqlx::query("INSERT INTO products (uuid, slug, type, title, price_cents, currency, settings, status, created_at, updated_at) VALUES ('p1', 'film', 'external', 'Film', 10000, 'USD', '{\"external_url\":\"https://x.io\"}', 'published', ?, ?)").bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();

    // Multi-currency: rates stored, shopper switches to EUR, checkout charges in EUR through Stripe-like gateways.
    st.currency
        .store_rates(&[
            ("EUR".into(), 1.0),
            ("USD".into(), 1.25),
            ("GBP".into(), 0.8),
        ])
        .await
        .unwrap();
    st.settings
        .set("store.display_currencies", "EUR,GBP")
        .await
        .unwrap();
    st.settings
        .set("store.charge_in_display_currency", "1")
        .await
        .unwrap();
    let res = app
        .clone()
        .oneshot(get(
            &format!("/embed/showcase?site={site}&currency=EUR"),
            None,
        ))
        .await
        .unwrap();
    let status = res.status();
    let cur_cookie = merge_cookies("", &res);
    if status != StatusCode::OK {
        panic!("showcase {status}: {}", text(res).await);
    }
    assert!(cur_cookie.contains("mms_cur=EUR"));
    let body = text(res).await;
    assert!(
        body.contains("≈ EUR 80.00") && body.contains("currency-switch"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/register",
            "name=Ada&email=ada%40example.com&password=a-strong-passphrase",
            Some(&cur_cookie),
        ))
        .await
        .unwrap();
    let mut cookie = merge_cookies(&cur_cookie, &res);
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/add", "product=film", Some(&cookie)))
        .await
        .unwrap();
    cookie = merge_cookies(&cookie, &res);
    let res = app
        .clone()
        .oneshot(get("/checkout", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("Prices shown in EUR") && body.contains("id=\"checkout-form\""),
        "{body}"
    );
    // The test gateway charges the base currency (only Stripe/PayPal convert); orders record the base and rate.
    let ccsrf = customer_csrf(&app, &cookie).await;
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={ccsrf}&gateway=test"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let order_uuid = location(&res).rsplit('/').next().unwrap().to_string();
    let o = st
        .commerce
        .order_by_uuid(&order_uuid)
        .await
        .unwrap()
        .unwrap();
    assert_eq!((o.currency.as_str(), o.total_cents), ("USD", 10000));
    // A converted order through the commerce API directly (what Stripe/PayPal would get).
    let cart = st.commerce.cart("fx-cart", Some(2)).await.unwrap();
    st.commerce
        .add(
            &cart,
            &st.products.by_slug("film").await.unwrap().unwrap(),
            1,
        )
        .await
        .unwrap();
    let eur = st
        .commerce
        .create_order_in(&cart, 2, "USD", Some(("EUR", 0.8)))
        .await
        .unwrap();
    assert_eq!(
        (eur.currency.as_str(), eur.total_cents, eur.fx_rate),
        ("EUR", 8000, 0.8)
    );

    // Square and Authorize.net appear at checkout with their card forms once configured.
    for (k, v) in [
        ("payments.square_access_token", "sq0atp-x"),
        ("payments.square_location_id", "L1"),
        ("payments.square_application_id", "sandbox-sq0idb-x"),
        ("payments.authnet_login_id", "login"),
        ("payments.authnet_transaction_key", "key"),
        ("payments.authnet_client_key", "client"),
    ] {
        st.settings.set(k, v).await.unwrap();
    }
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/add", "product=film", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get("/checkout", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("value=\"square\"")
            && body.contains("id=\"square-card\"")
            && body.contains("value=\"authnet\"")
            && body.contains("name=\"an_number\"")
            && body.contains("sandbox.web.squarecdn.com"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(get("/static/mms-checkout.js", None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    // A token-based gateway without a token fails cleanly (no network call).
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={ccsrf}&gateway=square"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("token"), "{}", location(&res));

    // Apple Pay domain file.
    let res = app
        .clone()
        .oneshot(get(
            "/.well-known/apple-developer-merchantid-domain-association",
            None,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::NOT_FOUND);
    st.settings
        .set("payments.apple_pay_domain_file", "7B227073...")
        .await
        .unwrap();
    let res = app
        .clone()
        .oneshot(get(
            "/.well-known/apple-developer-merchantid-domain-association",
            None,
        ))
        .await
        .unwrap();
    assert_eq!(text(res).await, "7B227073...");

    // Players: the page carries the licence configuration and the vendored players are served.
    st.settings.set("players.default", "clappr").await.unwrap();
    st.settings
        .set("players.kaltura_partner", "12345")
        .await
        .unwrap();
    sqlx::query("INSERT INTO products (uuid, slug, type, title, price_cents, currency, settings, status, created_at, updated_at) VALUES ('p2', 'clip', 'external', 'Clip', 0, 'USD', '{\"external_url\":\"https://x.io\"}', 'published', ?, ?)").bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/remove", "product_id=1", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(form("POST", "/cart/add", "product=clip", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/checkout/start",
            &format!("_csrf={ccsrf}&gateway="),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).starts_with("/checkout/done/"));
    let res = app
        .clone()
        .oneshot(get("/embed/player/clip", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("window.MMS_PLAYERS = {\"kaltura_partner\":\"12345\"}"),
        "{body}"
    );
    for f in ["vendor/clappr.min.js", "vendor/vimeo-player.min.js"] {
        let res = app
            .clone()
            .oneshot(get(&format!("/static/{f}"), None))
            .await
            .unwrap();
        assert_eq!(res.status(), StatusCode::OK, "{f}");
    }

    // Google Business Profile: page, consent redirect, posts, review drafts without a key.
    let res = app
        .clone()
        .oneshot(get("/admin/google", Some(&admin_cookie)))
        .await
        .unwrap();
    assert!(text(res).await.contains("Enter the OAuth client ID"));
    st.settings
        .set("google.client_id", "abc.apps.googleusercontent.com")
        .await
        .unwrap();
    st.settings
        .set("google.client_secret", "shh")
        .await
        .unwrap();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/google/connect",
            &format!("_csrf={csrf}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    let loc = location(&res);
    assert!(
        loc.starts_with(
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=abc.apps.googleusercontent.com"
        ) && loc.contains(&format!("state={csrf}")),
        "{loc}"
    );
    let res = app
        .clone()
        .oneshot(get(
            "/admin/google/callback?state=wrong&code=x",
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app.clone().oneshot(form("POST", "/admin/google/posts", &format!("_csrf={csrf}&location=locations%2F1&summary=October+masterclass+dates+are+out.&cta_type=LEARN_MORE&cta_url=https%3A%2F%2Fx.io&scheduled_at=2030-01-01+09%3A00"), Some(&admin_cookie))).await.unwrap();
    assert!(location(&res).contains("Post+saved"));
    sqlx::query("INSERT INTO google_reviews (remote_name, location, reviewer, rating, comment, reviewed_at, synced_at) VALUES ('r1','locations/1','Ada',5,'Loved it',?,?)").bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/google/reviews/1/draft",
            &format!("_csrf={csrf}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("API+key"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/google/reviews/1/reply",
            &format!("_csrf={csrf}&action=save&reply=Thank+you+Ada"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Draft+saved"));
    let res = app
        .clone()
        .oneshot(get("/admin/google", Some(&admin_cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("October masterclass")
            && body.contains("Thank you Ada")
            && body.contains("Connect Google account"),
        "{body}"
    );
    routes::worker::run(&st, "google.posts", "{}")
        .await
        .unwrap();

    // Email: not configured means nothing is sent and nothing fails.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/mail/test",
            &format!("_csrf={csrf}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("SMTP+host"));
    routes::worker::run(&st, "mail.pass_reminders", "{}")
        .await
        .unwrap();

    // Staff role: can run the store, cannot touch settings or integrations.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/register",
            "name=Sam&email=sam%40example.com&password=staff-passphrase",
            None,
        ))
        .await
        .unwrap();
    let staff = merge_cookies("", &res);
    let sam_uuid: String =
        sqlx::query_scalar("SELECT uuid FROM users WHERE email = 'sam@example.com'")
            .fetch_one(&st.db.pool)
            .await
            .unwrap();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/customers/{sam_uuid}/role"),
            &format!("_csrf={csrf}&role=staff"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(get("/admin/orders", Some(&staff)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK, "staff run the store");
    let res = app
        .clone()
        .oneshot(get("/admin/settings", Some(&staff)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(get("/admin/integrations", Some(&staff)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(get("/admin/backups", Some(&staff)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);

    // Login lockout after repeated failures.
    for _ in 0..5 {
        app.clone()
            .oneshot(form(
                "POST",
                "/login",
                "email=ada%40example.com&password=wrong",
                None,
            ))
            .await
            .unwrap();
    }
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/login",
            "email=ada%40example.com&password=a-strong-passphrase",
            None,
        ))
        .await
        .unwrap();
    assert!(text(res).await.contains("Too many attempts"));

    // Privacy: export, then erase; the account is gone but the order stays.
    let res = app
        .clone()
        .oneshot(get("/account/export.json", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let body = text(res).await;
    assert!(
        body.contains("\"email\": \"ada@example.com\"") && body.contains("ORD-2026-"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(get("/account/privacy", Some(&cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    let pcsrf = body
        .split("name=\"_csrf\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/account/erase",
            &format!("_csrf={pcsrf}&confirm=nope"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("Type+DELETE"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/account/erase",
            &format!("_csrf={pcsrf}&confirm=DELETE"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let (email, status): (String, String) =
        sqlx::query_as("SELECT email, status FROM users WHERE id = 2")
            .fetch_one(&st.db.pool)
            .await
            .unwrap();
    assert!(email.starts_with("erased-") && status == "disabled");
    assert_eq!(
        st.commerce
            .order_by_uuid(&order_uuid)
            .await
            .unwrap()
            .unwrap()
            .status,
        "pending"
    );
    let res = app
        .clone()
        .oneshot(get("/account", Some(&cookie)))
        .await
        .unwrap();
    assert_eq!(
        res.status(),
        StatusCode::SEE_OTHER,
        "erased accounts are signed out"
    );

    // Backups: create, list, download.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/backups",
            &format!("_csrf={csrf}"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert!(
        location(&res).contains("Backup+created"),
        "{}",
        location(&res)
    );
    let res = app
        .clone()
        .oneshot(get("/admin/backups", Some(&admin_cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    let name = body
        .split("/admin/backups/")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    assert!(name.starts_with("mms-backup-"));
    let res = app
        .clone()
        .oneshot(get(&format!("/admin/backups/{name}"), Some(&admin_cookie)))
        .await
        .unwrap();
    assert_eq!(res.headers()[header::CONTENT_TYPE], "application/gzip");
    assert!(bytes(res).await.len() > 20);
    let res = app
        .clone()
        .oneshot(get("/admin/backups/../mms.toml", Some(&admin_cookie)))
        .await
        .unwrap();
    assert_ne!(res.status(), StatusCode::OK);
}

/// Signs a sell-through request the way the WooCommerce module and the VirtueMart
/// plugin do (see `MmsRuntime::signRequest`).
fn shop_req(
    method: &str,
    path: &str,
    body: &str,
    site: &str,
    secret: &str,
    ts: i64,
) -> Request<Body> {
    // The signature covers the path without the query string.
    let sig = mms_core::commerce_bridge::request_signature(
        secret,
        ts,
        method,
        path.split('?').next().unwrap(),
        body.as_bytes(),
    );
    Request::builder()
        .method(method)
        .uri(path)
        .header(header::CONTENT_TYPE, "application/json")
        .header("x-mms-site", site)
        .header("x-mms-timestamp", ts.to_string())
        .header("x-mms-signature", sig)
        .body(Body::from(body.to_string()))
        .unwrap()
}

#[tokio::test]
async fn phase_eight_sell_through_woocommerce_and_virtuemart() {
    let tmp = std::env::temp_dir().join(format!("mms-http-{}", uuid::Uuid::new_v4()));
    let mut config = mms_core::config::Config::generate(tmp, "127.0.0.1:0", "http://shop.example");
    let site = "22222222-2222-4333-8444-555555555555";
    let secret = "shop-shared-secret";
    config.bridges.push(mms_core::config::BridgeConfig {
        uuid: site.into(),
        name: "Shop site".into(),
        host: "wordpress".into(),
        origin: "https://shop.example".into(),
        secret: secret.into(),
        admin_sso: true,
    });
    config.validate().unwrap();
    let db = mms_core::db::Db::memory().await.unwrap();
    let st = app::AppState::new(config, db).unwrap();
    routes::bridges::sync_from_config(&st).await.unwrap();
    let app = app::router(st.clone());
    let (admin_cookie, _csrf) = admin_session(&app).await;
    let now = mms_core::now();
    for (uuid, slug, t, title, price, settings) in [
        ("p1", "film", "video", "Film", 4900, "{}"),
        (
            "p2",
            "club",
            "site_pass",
            "Club",
            1900,
            r#"{"validity":"recurring","interval":"month","scope":"site"}"#,
        ),
        ("p3", "vault", "private_page", "Vault access", 1000, "{}"),
    ] {
        sqlx::query("INSERT INTO products (uuid, slug, type, title, price_cents, currency, settings, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'USD', ?, 'published', ?, ?)")
            .bind(uuid).bind(slug).bind(t).bind(title).bind(price).bind(settings).bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();
    }
    let ts = chrono::Utc::now().timestamp();

    // Unsigned, badly signed and stale requests are refused.
    let res = app
        .clone()
        .oneshot(get("/api/v1/commerce/status", None))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);
    let res = app
        .clone()
        .oneshot(shop_req(
            "GET",
            "/api/v1/commerce/status",
            "",
            site,
            "wrong",
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    let res = app
        .clone()
        .oneshot(shop_req(
            "GET",
            "/api/v1/commerce/status",
            "",
            site,
            secret,
            ts - 3600,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);

    // Status and catalogue.
    let res = app
        .clone()
        .oneshot(shop_req(
            "GET",
            "/api/v1/commerce/status",
            "",
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    let status = res.status();
    let body = text(res).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let j: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(j["data"]["mode"], "native");
    assert_eq!(j["data"]["products"], 3);
    let res = app
        .clone()
        .oneshot(shop_req(
            "GET",
            "/api/v1/commerce/catalog?system=woocommerce",
            "",
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    let cat = j["data"].as_array().unwrap();
    assert_eq!(cat.len(), 3);
    let film = cat.iter().find(|p| p["slug"] == "film").unwrap();
    assert_eq!(film["price_cents"], 4900);
    assert_eq!(film["page_url"], "http://shop.example/embed/product/film");
    assert!(film["external_id"].is_null());
    assert_eq!(
        cat.iter().find(|p| p["slug"] == "club").unwrap()["recurring"],
        true
    );

    // Native mode: the product page still uses the store's own checkout.
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/product/film?site={site}"), None))
        .await
        .unwrap();
    assert!(text(res).await.contains("/embed/checkout?site="));

    // Link products to WooCommerce products and switch checkout there.
    let body = r#"{"system":"woocommerce","links":[{"slug":"film","external_id":"101","external_url":"https://shop.example/product/film"},{"slug":"club","external_id":"102"},{"slug":"nope","external_id":"103"}]}"#;
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/link",
            body,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["data"]["linked"], 2);
    assert_eq!(j["data"]["unknown"][0], "nope");
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/mode",
            r#"{"mode":"woocommerce","unlinked":"hide"}"#,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(
        st.settings.get("commerce.mode").await.unwrap(),
        "woocommerce"
    );

    // Buy buttons now point at the WooCommerce cart; an unlinked product hides its button.
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/product/film?site={site}"), None))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains(
            r#"href="https://shop.example/?add-to-cart=101&amp;quantity=1" target="_top""#
        ),
        "{body}"
    );
    assert!(!body.contains("/embed/checkout?site="));
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/product/vault?site={site}"), None))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("Not available for purchase yet") && !body.contains("/embed/checkout"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(get("/admin/integrations", Some(&admin_cookie)))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains("Checkout runs in <b>WooCommerce</b>") && body.contains("#101"),
        "{body}"
    );

    // The shop reports a paid order for a new customer: the store creates the account,
    // the order, the receipt and the entitlement, exactly once.
    let order = r#"{"system":"woocommerce","external_id":"5001","status":"paid","customer":{"id":"77","email":"buyer@example.com","name":"Buyer"},"currency":"USD","items":[{"external_id":"101","quantity":1,"unit_cents":4900},{"slug":"missing","quantity":1,"unit_cents":100}],"tax_cents":490}"#;
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/orders",
            order,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["data"]["granted_now"], true, "{j}");
    assert_eq!(j["data"]["entitlements"], 1);
    assert_eq!(j["data"]["order"]["total_cents"], 5390);
    assert_eq!(j["data"]["skipped"][0], "missing");
    let order_uuid = j["data"]["order"]["uuid"].as_str().unwrap().to_string();
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/orders",
            order,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(
        j["data"]["granted_now"], false,
        "second report is idempotent: {j}"
    );
    assert_eq!(j["data"]["order"]["uuid"], order_uuid);
    let o = st
        .commerce
        .order_by_external("woocommerce", "5001")
        .await
        .unwrap()
        .unwrap();
    assert_eq!(o.status, "paid");
    assert_eq!(o.gateway, "woocommerce");
    assert!(
        st.commerce.receipt(o.id).await.unwrap().is_some(),
        "receipt issued"
    );
    let buyer = st
        .users
        .by_email("buyer@example.com")
        .await
        .unwrap()
        .unwrap();
    let ents = st.entitlements.for_user(buyer.id).await.unwrap();
    assert_eq!(ents.len(), 1);
    assert_eq!(ents[0].product_id, Some(1));

    // The shop's "My account" asks what this customer may open.
    let res = app
        .clone()
        .oneshot(shop_req(
            "GET",
            "/api/v1/commerce/customers/77",
            "",
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["data"]["known"], true);
    assert_eq!(
        j["data"]["entitlements"][0]["open_path"],
        "/embed/player/film"
    );
    let res = app
        .clone()
        .oneshot(shop_req(
            "GET",
            "/api/v1/commerce/orders/woocommerce/5001",
            "",
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["data"]["order"]["number"], o.number);

    // Refund in the shop: access revoked, order refunded.
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/orders",
            r#"{"system":"woocommerce","external_id":"5001","status":"refunded"}"#,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["data"]["outcome"], "refunded: access revoked");
    assert!(st
        .entitlements
        .for_user(buyer.id)
        .await
        .unwrap()
        .iter()
        .all(|e| e.status != "active"));
    assert_eq!(
        st.commerce
            .order_by_external("woocommerce", "5001")
            .await
            .unwrap()
            .unwrap()
            .status,
        "refunded"
    );

    // A subscription (WooCommerce Subscriptions) for the recurring pass: active, renewed, cancelled.
    let sub = r#"{"system":"woocommerce","external_id":"9001","status":"active","customer":{"id":"77","email":"buyer@example.com","name":"Buyer"},"product_external_id":"102","period_end":"2099-01-01T00:00:00Z"}"#;
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/subscriptions",
            sub,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let s = st
        .commerce
        .subscription_by_external("woocommerce", "9001")
        .await
        .unwrap()
        .unwrap();
    assert_eq!(s.status, "active");
    assert!(st
        .entitlements
        .for_user(buyer.id)
        .await
        .unwrap()
        .iter()
        .any(|e| e.scope == "site" && e.status == "active"));
    let res = app.clone().oneshot(shop_req("POST", "/api/v1/commerce/subscriptions", r#"{"system":"woocommerce","external_id":"9001","status":"renewed","period_end":"2099-02-01T00:00:00Z"}"#, site, secret, ts)).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(
        st.commerce
            .subscription_by_external("woocommerce", "9001")
            .await
            .unwrap()
            .unwrap()
            .period_end
            .as_deref(),
        Some("2099-02-01T00:00:00Z")
    );
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/subscriptions",
            r#"{"system":"woocommerce","external_id":"9001","status":"cancelled"}"#,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert!(
        st.entitlements
            .for_user(buyer.id)
            .await
            .unwrap()
            .iter()
            .all(|e| e.status != "active"),
        "cancelled subscription revokes the pass"
    );

    // A pending order that is later cancelled never grants anything.
    let res = app.clone().oneshot(shop_req("POST", "/api/v1/commerce/orders", r#"{"system":"woocommerce","external_id":"5002","status":"pending","customer":{"id":"78","email":"other@example.com"},"items":[{"slug":"film","unit_cents":4900}]}"#, site, secret, ts)).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/orders",
            r#"{"system":"woocommerce","external_id":"5002","status":"cancelled"}"#,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["data"]["outcome"], "cancelled");
    let other = st
        .users
        .by_email("other@example.com")
        .await
        .unwrap()
        .unwrap();
    assert!(st.entitlements.for_user(other.id).await.unwrap().is_empty());

    // VirtueMart: the same API with its own cart address, and the mode is independent.
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/link",
            r#"{"system":"virtuemart","links":[{"slug":"film","external_id":"7"}]}"#,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/mode",
            r#"{"mode":"virtuemart","unlinked":"native"}"#,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/product/film?site={site}"), None))
        .await
        .unwrap();
    let body = text(res).await;
    assert!(
        body.contains(
            "option=com_virtuemart&amp;view=cart&amp;task=add&amp;virtuemart_product_id[]=7"
        ) || body.contains("option=com_virtuemart&view=cart&task=add&virtuemart_product_id[]=7"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/product/vault?site={site}"), None))
        .await
        .unwrap();
    assert!(
        text(res).await.contains("/embed/checkout?site="),
        "unlinked products fall back to the native checkout"
    );
    let res = app.clone().oneshot(shop_req("POST", "/api/v1/commerce/orders", r#"{"system":"virtuemart","external_id":"VM-31","status":"paid","customer":{"id":"5","email":"vm@example.com","name":"VM Buyer"},"currency":"EUR","items":[{"external_id":"7","quantity":1,"unit_cents":4500}]}"#, site, secret, ts)).await.unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["data"]["granted_now"], true, "{j}");
    assert_eq!(j["data"]["order"]["currency"], "EUR");

    // Back to native: nothing external remains in the Buy button.
    let res = app
        .clone()
        .oneshot(shop_req(
            "POST",
            "/api/v1/commerce/mode",
            r#"{"mode":"native"}"#,
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/product/film?site={site}"), None))
        .await
        .unwrap();
    assert!(text(res).await.contains("/embed/checkout?site="));
    let res = app
        .clone()
        .oneshot(shop_req(
            "GET",
            "/api/v1/commerce/status",
            "",
            site,
            secret,
            ts,
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["data"]["linked"]["woocommerce"], 2);
    assert_eq!(j["data"]["linked"]["virtuemart"], 1);
    assert!(j["data"]["events"].as_array().unwrap().len() >= 6);
}

/// A canned Messages API response with the given content blocks.
fn model_turn(stop: &str, content: serde_json::Value) -> serde_json::Value {
    serde_json::json!({ "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5", "stop_reason": stop, "content": content, "usage": { "input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 900 } })
}

fn tool_use(id: &str, name: &str, input: serde_json::Value) -> serde_json::Value {
    serde_json::json!({ "type": "tool_use", "id": id, "name": name, "input": input })
}

/// Runs every queued job the way the worker would.
async fn drain_jobs(st: &app::AppState) {
    for _ in 0..20 {
        let Some(job) = st.jobs.claim().await.unwrap() else {
            break;
        };
        match routes::worker::run(st, &job.r#type, job.args.as_deref().unwrap_or("{}")).await {
            Ok(()) => st.jobs.complete(job.id).await.unwrap(),
            Err(e) => st.jobs.fail(&job, &e.to_string()).await.unwrap(),
        }
    }
}

#[tokio::test]
async fn phase_nine_setup_wizards_team_with_scripted_model() {
    // Without a key and without a script the wizards are off.
    let plain = state().await;
    let app_plain = app::router(plain.clone());
    let (cookie, _) = admin_session(&app_plain).await;
    let body = text(
        app_plain
            .clone()
            .oneshot(get("/admin/wizards", Some(&cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Add an Anthropic API key") && body.contains("Concierge"),
        "{body}"
    );

    // The scripted model: what Claude would answer, turn by turn.
    let script = vec![
        // Concierge: reads the overview, asks two questions.
        model_turn(
            "tool_use",
            serde_json::json!([{ "type": "text", "text": "Let me look at the store." }, tool_use("t1", "read_store_overview", serde_json::json!({}))]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "t2",
                "ask_admin",
                serde_json::json!({ "questions": [{ "key": "country", "question": "Which country is the business in?", "options": ["United Kingdom", "United States"] }, { "key": "sells", "question": "What do you sell?" }] })
            )]),
        ),
        // After the answers: a two-step plan and a summary.
        model_turn(
            "tool_use",
            serde_json::json!([
                tool_use(
                    "t3",
                    "plan_team",
                    serde_json::json!({ "steps": [{ "wizard": "store_setup", "brief": "UK film studio, GBP." }, { "wizard": "catalogue", "brief": "One film to sell at £49." }, { "wizard": "concierge", "brief": "must be ignored" }] })
                ),
                tool_use(
                    "t4",
                    "finish",
                    serde_json::json!({ "summary": "Two specialists will run: store setup, then the catalogue.", "checklist": [{ "item": "Interview done", "status": "done" }] })
                )
            ]),
        ),
        // Store setup specialist.
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "t5",
                "read_settings",
                serde_json::json!({ "section": "store" })
            )]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([
                tool_use(
                    "t6",
                    "propose_settings",
                    serde_json::json!({ "changes": [
            { "key": "general.site_name", "value": "Ada Films", "reason": "The brief names the studio" },
            { "key": "store.currency", "value": "GBP", "reason": "UK business" },
            { "key": "payments.stripe_secret_key", "value": "", "reason": "Type your Stripe key" },
            { "key": "media.max_upload_mb", "value": "lots", "reason": "invalid, must be rejected" },
            { "key": "nonsense.key", "value": "x", "reason": "unknown, must be rejected" }
        ] })
                ),
                tool_use(
                    "t7",
                    "finish",
                    serde_json::json!({ "summary": "Store name and currency proposed; type the Stripe key.", "checklist": [{ "item": "Store name and currency", "status": "done" }, { "item": "Stripe key", "status": "needs_admin", "note": "secret" }] })
                )
            ]),
        ),
        // Catalogue specialist.
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "t8",
                "list_media",
                serde_json::json!({ "type": "video" })
            )]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([
                tool_use(
                    "t9",
                    "propose_category",
                    serde_json::json!({ "name": "Films", "reason": "One category" })
                ),
                tool_use(
                    "t10",
                    "propose_product",
                    serde_json::json!({ "type": "video", "title": "The Film", "slug": "the-film", "description": "A film.", "price_cents": 4900, "currency": "gbp", "media_uuid": "m-1", "categories": ["Films"], "status": "published", "settings": { "preview_length": "30" }, "reason": "The uploaded video has no product" })
                ),
                tool_use(
                    "t11",
                    "finish",
                    serde_json::json!({ "summary": "One product proposed.", "checklist": [] })
                )
            ]),
        ),
        // The form assistant in the drawer.
        model_turn(
            "tool_use",
            serde_json::json!([{ "type": "text", "text": "A short prefix keeps receipts readable." }, tool_use("t12", "propose_settings", serde_json::json!({ "changes": [{ "key": "store.receipt_prefix", "value": "ADA", "reason": "Matches the studio name" }] })), tool_use("t13", "finish", serde_json::json!({ "summary": "Use ADA as the receipt prefix." }))]),
        ),
    ];
    let mut st = state().await;
    st.wizard_transport = mms_core::wizards::Transport::scripted(script);
    let app = app::router(st.clone());
    let (cookie, csrf) = admin_session(&app).await;
    let now = mms_core::now();
    sqlx::query("INSERT INTO media (uuid, type, original_path, private, mime, bytes, hash_sha256, title, status, created_at, updated_at) VALUES ('m-1', 'video', 'x.mp4', 1, 'video/mp4', 10, 'h', 'Raw film', 'ready', ?, ?)")
        .bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();

    let body = text(
        app.clone()
            .oneshot(get("/admin/wizards", Some(&cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        !body.contains("Add an Anthropic API key") && body.contains("Set up my store"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/wizards/start",
            &format!("_csrf={csrf}&wizard=concierge&brief=We+make+films"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let loc = location(&res);
    let uuid = loc.rsplit('/').next().unwrap().to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/wizards/start",
            &format!("_csrf={csrf}&wizard=assist"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(
        res.status(),
        StatusCode::BAD_REQUEST,
        "the drawer wizard cannot be started as a session"
    );

    // Turn 1 and 2: overview, then questions.
    drain_jobs(&st).await;
    let s = st.wizards.session_by_uuid(&uuid).await.unwrap().unwrap();
    assert_eq!(s.status, "waiting", "{}", s.error);
    assert_eq!(s.turns, 2);
    let body = text(app.clone().oneshot(get(&loc, Some(&cookie))).await.unwrap()).await;
    assert!(
        body.contains("Which country is the business in?")
            && body.contains("United Kingdom")
            && body.contains("Send answers"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("{loc}/answer"),
            &format!("_csrf={csrf}&q_country=United+Kingdom&q_sells=Films"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let msgs = st.wizards.messages(s.id).await.unwrap();
    let last = msgs.last().unwrap();
    assert_eq!(last["content"][0]["tool_use_id"], "t2");
    assert!(last["content"][0]["content"]
        .as_str()
        .unwrap()
        .contains("United Kingdom"));
    assert_eq!(
        msgs[2]["content"][0]["tool_use_id"], "t1",
        "the overview result was delivered in its own turn"
    );

    // Turn 3: the plan, then the two specialists run one after another.
    drain_jobs(&st).await;
    let s = st.wizards.session_by_uuid(&uuid).await.unwrap().unwrap();
    assert_eq!(s.status, "done", "{}", s.error);
    assert!(s.context.contains("Administrator's answers") && s.context.contains("Films"));
    let plan: Vec<serde_json::Value> = serde_json::from_str(&s.plan).unwrap();
    assert_eq!(plan.len(), 2, "the concierge step is dropped: {plan:?}");
    drain_jobs(&st).await;
    drain_jobs(&st).await;
    let children = st.wizards.children(s.id).await.unwrap();
    assert_eq!(children.len(), 2);
    assert!(
        children.iter().all(|c| c.status == "done"),
        "{:?}",
        children
            .iter()
            .map(|c| (&c.wizard, &c.status, &c.error))
            .collect::<Vec<_>>()
    );
    assert!(
        children[0].context.contains("Concierge summary")
            && children[0].context.contains("United Kingdom")
    );
    let body = text(app.clone().oneshot(get(&loc, Some(&cookie))).await.unwrap()).await;
    assert!(
        body.contains("The team&#x27;s plan") || body.contains("The team's plan"),
        "{body}"
    );
    assert!(
        body.contains("Store setup")
            && body.contains("Catalogue")
            && body.contains("Two specialists will run")
    );

    // Store setup proposals: valid ones kept, the invalid and unknown ones rejected.
    let setup = &children[0];
    let props = st.wizards.proposals(setup.id).await.unwrap();
    assert_eq!(props.len(), 3, "{props:?}");
    assert!(props[2].needs_input == 1 && props[2].payload.contains("stripe_secret_key"));
    let setup_url = format!("/admin/wizards/{}", setup.uuid);
    let body = text(
        app.clone()
            .oneshot(get(&setup_url, Some(&cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Ada Films")
            && body.contains("type=\"password\"")
            && body.contains("needs admin"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("{setup_url}/proposals/{}/apply", props[0].uuid),
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert_eq!(
        st.settings.get("general.site_name").await.unwrap(),
        "Ada Films"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("{setup_url}/apply-all"),
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(
        location(&res).contains("1+applied") && location(&res).contains("1+left"),
        "{}",
        location(&res)
    );
    assert_eq!(st.settings.get("store.currency").await.unwrap(), "GBP");
    assert_eq!(
        st.settings.get("payments.stripe_secret_key").await.unwrap(),
        "",
        "secrets are never applied without input"
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("{setup_url}/proposals/{}/apply", props[2].uuid),
            &format!("_csrf={csrf}&value=sk_test_123"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert_eq!(
        st.settings.get("payments.stripe_secret_key").await.unwrap(),
        "sk_test_123"
    );
    assert!(st
        .wizards
        .proposals(setup.id)
        .await
        .unwrap()
        .iter()
        .all(|p| p.status == "applied"));
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("{setup_url}/proposals/{}/apply", props[0].uuid),
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(
        location(&res).contains("error=already"),
        "applying twice is refused"
    );

    // Catalogue proposals create the category and the product through the normal code path.
    let cat = &children[1];
    let props = st.wizards.proposals(cat.id).await.unwrap();
    assert_eq!(props.len(), 2);
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/wizards/{}/apply-all", cat.uuid),
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("2+applied"), "{}", location(&res));
    let p = st
        .products
        .by_slug("the-film")
        .await
        .unwrap()
        .expect("product created");
    assert_eq!(
        (
            p.price_cents,
            p.currency.as_str(),
            p.status.as_str(),
            p.media_id
        ),
        (4900, "GBP", "published", Some(1))
    );
    assert_eq!(st.products.categories().await.unwrap().len(), 1);
    assert_eq!(st.products.category_ids(p.id).await.unwrap().len(), 1);

    // The drawer: one question, one answer, one proposal applied from JSON.
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            "/admin/wizards/ask",
            r#"{"page":"settings#store","question":"What receipt prefix should I use?"}"#,
            &cookie,
            &csrf,
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["status"], "done", "{j}");
    assert_eq!(j["answer"], "Use ADA as the receipt prefix.");
    assert_eq!(j["proposals"][0]["payload"]["key"], "store.receipt_prefix");
    let sess = j["session"].as_str().unwrap();
    let pid = j["proposals"][0]["uuid"].as_str().unwrap();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/wizards/{sess}/proposals/{pid}/apply"),
            &format!("_csrf={csrf}&_format=json"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["status"], "applied", "{j}");
    assert_eq!(
        st.settings.get("store.receipt_prefix").await.unwrap(),
        "ADA"
    );

    // The script is spent: the next session fails cleanly and says so.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/wizards/start",
            &format!("_csrf={csrf}&wizard=auditor"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let audit_url = location(&res);
    drain_jobs(&st).await;
    let s = st
        .wizards
        .session_by_uuid(audit_url.rsplit('/').next().unwrap())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(s.status, "failed");
    assert!(s.error.contains("no more responses"));
    let body = text(
        app.clone()
            .oneshot(get(&audit_url, Some(&cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(body.contains("The wizard stopped"), "{body}");
    // Everything a wizard applied is in the audit log.
    let applied: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM audit_log WHERE action = 'wizard.applied'")
            .fetch_one(&st.db.pool)
            .await
            .unwrap();
    assert_eq!(applied, 6);
}

#[tokio::test]
async fn phase_eleven_media_intake_and_analytics_wizards() {
    let script = vec![
        // Media intake: lists the library, proposes details for the real file and for a
        // file that does not exist, asks about rights, then classifies and gates.
        model_turn(
            "tool_use",
            serde_json::json!([tool_use("i1", "list_media", serde_json::json!({}))]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([
                tool_use(
                    "i2",
                    "propose_media_meta",
                    serde_json::json!({ "uuid": "m-1", "title": "Sunrise over the harbour", "caption": "A four-minute film of the harbour at first light.", "tags": "harbour, sunrise, film, coastal, calm", "reason": "The title was the file name and the file had no caption or tags." })
                ),
                tool_use(
                    "i3",
                    "propose_media_meta",
                    serde_json::json!({ "uuid": "nope", "title": "Ghost", "reason": "x" })
                ),
            ]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "i4",
                "ask_admin",
                serde_json::json!({ "questions": [{ "key": "rights", "question": "Who owns the rights to these files?" }, { "key": "adult", "question": "Is any of the content for adults only?", "options": ["No", "Yes"] }] })
            )]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([
                tool_use(
                    "i5",
                    "propose_category",
                    serde_json::json!({ "name": "Adults only", "reason": "The owner said the film is for adults." })
                ),
                tool_use(
                    "i6",
                    "propose_page",
                    serde_json::json!({ "title": "Adults only", "content": "## Restricted films\n\nConfirm your age to continue.", "agreement": "I confirm that I am 18 or older. Rights owner: Harbour Films.", "signup_template": "legal", "protection": "members", "jurisdiction": "England and Wales", "min_age": 18, "reason": "Age gate for the restricted film." })
                ),
            ]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "i7",
                "finish",
                serde_json::json!({ "summary": "Every file now has a title, caption and tags; the restricted film sits behind an age gate.", "checklist": [{ "item": "Titles, captions and tags", "status": "done" }, { "item": "Rights and licensing recorded", "status": "done", "note": "Harbour Films owns everything" }, { "item": "Classification and age gating", "status": "done" }] })
            )]),
        ),
        // Analytics: reads the report, proposes one coupon, finishes with the review.
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "a1",
                "read_analytics",
                serde_json::json!({ "months": 6 })
            )]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "a2",
                "propose_coupon",
                serde_json::json!({ "code": "comeback20", "kind": "percent", "amount": 20, "max_uses": 50, "reason": "Nothing has sold yet; a launch discount gets the first buyers in." })
            )]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "a3",
                "finish",
                serde_json::json!({ "summary": "No paid orders yet, so there is no trend to read. One published product has never sold and one file has no product.", "checklist": [{ "item": "Sales and revenue reviewed", "status": "done" }, { "item": "Recommended actions", "status": "todo", "note": "Apply the launch coupon and give the unsold file a product" }] })
            )]),
        ),
    ];
    let mut st = state().await;
    st.wizard_transport = mms_core::wizards::Transport::scripted(script);
    let app = app::router(st.clone());
    let (cookie, csrf) = admin_session(&app).await;
    let now = mms_core::now();
    sqlx::query("INSERT INTO media (uuid, type, original_path, private, mime, bytes, hash_sha256, title, alt, status, created_at, updated_at) VALUES ('m-1', 'video', 'harbour.mp4', 1, 'video/mp4', 10, 'h', 'harbour.mp4', 'Boats at dawn', 'ready', ?, ?)")
        .bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();

    let body = text(
        app.clone()
            .oneshot(get("/admin/wizards", Some(&cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Media intake") && body.contains("Analytics"),
        "{body}"
    );

    // ----- Media intake -----
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/wizards/start",
            &format!("_csrf={csrf}&wizard=media_intake"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let url = location(&res);
    let uuid = url.rsplit('/').next().unwrap().to_string();
    drain_jobs(&st).await;
    let s = st.wizards.session_by_uuid(&uuid).await.unwrap().unwrap();
    assert_eq!(s.status, "waiting", "{}", s.error);
    let props = st.wizards.proposals(s.id).await.unwrap();
    assert_eq!(props.len(), 1, "the unknown uuid never became a proposal");
    assert_eq!(props[0].kind, "media_meta");
    let payload: serde_json::Value = serde_json::from_str(&props[0].payload).unwrap();
    assert_eq!(
        payload["alt"], "Boats at dawn",
        "a field left out keeps its value"
    );
    assert_eq!(payload["was"]["title"], "harbour.mp4");
    let msgs = st.wizards.messages(s.id).await.unwrap();
    let results = msgs
        .iter()
        .filter(|m| m["role"] == "user")
        .map(|m| m["content"].to_string())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(results.contains("unknown media uuid"), "{results}");

    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("{url}/answer"),
            &format!("_csrf={csrf}&q_rights=Harbour+Films&q_adult=Yes"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    drain_jobs(&st).await;
    let s = st.wizards.session_by_uuid(&uuid).await.unwrap().unwrap();
    assert_eq!(s.status, "done", "{}", s.error);
    assert_eq!(st.wizards.proposals(s.id).await.unwrap().len(), 3);
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("{url}/apply-all"),
            &format!("_csrf={csrf}"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    assert!(location(&res).contains("3+applied"), "{}", location(&res));
    let m = st.media.by_uuid("m-1").await.unwrap().unwrap();
    assert_eq!(m.title.as_deref(), Some("Sunrise over the harbour"));
    assert_eq!(m.alt.as_deref(), Some("Boats at dawn"));
    assert_eq!(
        m.tags.as_deref(),
        Some("harbour, sunrise, film, coastal, calm")
    );
    assert!(st
        .products
        .categories()
        .await
        .unwrap()
        .iter()
        .any(|c| c.name == "Adults only"));
    let pages = st.pages.list().await.unwrap();
    let page = pages
        .iter()
        .find(|p| p.title == "Adults only")
        .expect("gate page");
    assert_eq!((page.signup_template.as_str(), page.min_age), ("legal", 18));

    // ----- Analytics -----
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/wizards/start",
            &format!("_csrf={csrf}&wizard=analytics"),
            Some(&cookie),
        ))
        .await
        .unwrap();
    let url = location(&res);
    let uuid = url.rsplit('/').next().unwrap().to_string();
    drain_jobs(&st).await;
    let s = st.wizards.session_by_uuid(&uuid).await.unwrap().unwrap();
    assert_eq!(s.status, "done", "{}", s.error);
    let msgs = st.wizards.messages(s.id).await.unwrap();
    let report = msgs
        .iter()
        .filter(|m| m["role"] == "user")
        .map(|m| m["content"].to_string())
        .find(|c| c.contains("revenue_by_month"))
        .expect("the report reached the model");
    assert!(
        report.contains(r#"\"months\":6"#) && report.contains("media_without_product"),
        "{report}"
    );
    let props = st.wizards.proposals(s.id).await.unwrap();
    assert_eq!((props.len(), props[0].kind.as_str()), (1, "coupon"));
    let body = text(app.clone().oneshot(get(&url, Some(&cookie))).await.unwrap()).await;
    assert!(
        body.contains("no trend to read") && body.contains("COMEBACK20"),
        "{body}"
    );
}

#[tokio::test]
async fn phase_ten_support_chat_agents_assistant_and_handover() {
    let tmp = std::env::temp_dir().join(format!("mms-http-{}", uuid::Uuid::new_v4()));
    let mut config = mms_core::config::Config::generate(tmp, "127.0.0.1:0", "http://shop.example");
    let site = "33333333-2222-4333-8444-555555555555";
    config.bridges.push(mms_core::config::BridgeConfig {
        uuid: site.into(),
        name: "Site".into(),
        host: "wordpress".into(),
        origin: "https://shop.example".into(),
        secret: "s".into(),
        admin_sso: true,
    });
    config.validate().unwrap();
    let db = mms_core::db::Db::memory().await.unwrap();
    let mut st = app::AppState::new(config, db).unwrap();
    routes::bridges::sync_from_config(&st).await.unwrap();
    st.wizard_transport = mms_core::wizards::Transport::scripted(vec![
        model_turn(
            "tool_use",
            serde_json::json!([tool_use(
                "h1",
                "read_help",
                serde_json::json!({ "topic": "open" })
            )]),
        ),
        model_turn(
            "end_turn",
            serde_json::json!([{ "type": "text", "text": "Everything you bought is under My media; open the film from there." }]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([{ "type": "text", "text": "I'll hand you to a member of the team for the refund." }, tool_use("h2", "escalate", serde_json::json!({ "reason": "refund request", "summary": "Guest Ada wants a refund for a film" }))]),
        ),
        model_turn(
            "end_turn",
            serde_json::json!([{ "type": "text", "text": "Hi Ada, I can refund the film today; you will get the money back within five days." }]),
        ),
        model_turn(
            "tool_use",
            serde_json::json!([tool_use("h3", "lookup_customer", serde_json::json!({}))]),
        ),
        model_turn(
            "end_turn",
            serde_json::json!([{ "type": "text", "text": "Your order is paid and the film is open in My media." }]),
        ),
    ]);
    let app = app::router(st.clone());
    let (admin_cookie, csrf) = admin_session(&app).await;

    // Invite a contractor, who joins by link, sets a password and lands in the console; admin pages stay closed.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/admin/chat/invite",
            &format!("_csrf={csrf}&email=sam%40example.com&name=Sam"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let loc = location(&res);
    let token = loc
        .split("token%3D")
        .nth(1)
        .unwrap_or("")
        .split(|c: char| !c.is_ascii_alphanumeric())
        .next()
        .unwrap()
        .to_string();
    assert_eq!(token.len(), 64, "{loc}");
    let body = text(
        app.clone()
            .oneshot(get(&format!("/agent/join?token={token}"), None))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Join the support team") && body.contains("sam@example.com"),
        "{body}"
    );
    let res = app.clone().oneshot(form("POST", "/agent/join", &format!("token={token}&name=Sam+Agent&password=contractor-pass&password_repeat=contractor-pass"), None)).await.unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER, "{}", text(res).await);
    let agent_cookie = cookie_of(&res);
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/agent/join",
            &format!("token={token}&password=contractor-pass&password_repeat=contractor-pass"),
            None,
        ))
        .await
        .unwrap();
    assert!(
        text(res).await.contains("no longer valid"),
        "an invite works once"
    );
    let sam = st.users.by_email("sam@example.com").await.unwrap().unwrap();
    assert!(sam.is_agent() && !sam.is_staff() && sam.role == "customer");
    let body = text(
        app.clone()
            .oneshot(get("/agent", Some(&agent_cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Support console") && body.contains("Nothing here right now"),
        "{body}"
    );
    assert_eq!(
        app.clone()
            .oneshot(get("/admin", Some(&agent_cookie)))
            .await
            .unwrap()
            .status(),
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        app.clone()
            .oneshot(get("/admin/chat", Some(&agent_cookie)))
            .await
            .unwrap()
            .status(),
        StatusCode::FORBIDDEN
    );
    let body = text(
        app.clone()
            .oneshot(get("/admin/chat", Some(&admin_cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Sam Agent") && body.contains("accepted"),
        "{body}"
    );
    // Signing in at the store's own login sends an agent to the console.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            "/login",
            "email=sam%40example.com&password=contractor-pass",
            None,
        ))
        .await
        .unwrap();
    assert_eq!(location(&res), "/agent");

    // A guest on the site: the assistant answers first.
    assert_eq!(
        app.clone()
            .oneshot(get("/embed/chat?site=nope", None))
            .await
            .unwrap()
            .status(),
        StatusCode::FORBIDDEN
    );
    let res = app
        .clone()
        .oneshot(get(&format!("/embed/chat?site={site}"), None))
        .await
        .unwrap();
    assert_eq!(
        res.headers()[header::CONTENT_SECURITY_POLICY],
        "frame-ancestors 'self' https://shop.example"
    );
    assert!(text(res).await.contains("Start chat"));
    let res = app.clone().oneshot(json_req("POST", "/chat/start", &format!(r#"{{"site":"{site}","name":"Ada","email":"ada@example.com","subject":"My film","message":"How do I open my film?"}}"#), "", "")).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let visitor_cookie = cookie_of(&res);
    assert!(visitor_cookie.contains("mms_chat="));
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    let conv = j["conversation"].as_str().unwrap().to_string();
    assert_eq!(j["status"], "open");
    assert_eq!(
        j["messages"].as_array().unwrap().len(),
        1,
        "only the replies come back: {j}"
    );
    assert_eq!(j["messages"][0]["sender"], "assistant");
    assert!(j["messages"][0]["body"]
        .as_str()
        .unwrap()
        .contains("My media"));
    // Nobody else can read it.
    assert_eq!(
        app.clone()
            .oneshot(get(&format!("/chat/{conv}/messages?after=0"), None))
            .await
            .unwrap()
            .status(),
        StatusCode::FORBIDDEN
    );
    // Money question: the assistant hands over.
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            &format!("/chat/{conv}/send"),
            r#"{"body":"I want a refund. Get me a human."}"#,
            &visitor_cookie,
            "",
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["status"], "waiting", "{j}");
    let bodies: Vec<&str> = j["messages"]
        .as_array()
        .unwrap()
        .iter()
        .map(|m| m["body"].as_str().unwrap())
        .collect();
    assert!(
        bodies.iter().any(|b| b.contains("hand you"))
            && bodies
                .iter()
                .any(|b| b.contains("connected to a support agent")),
        "Sam's console polls count as online: {bodies:?}"
    );
    let c = st.support.by_uuid(&conv).await.unwrap().unwrap();
    assert_eq!(c.ai_turns, 2);
    let notes = st.support.messages(c.id, 0, true).await.unwrap();
    assert!(
        notes
            .iter()
            .any(|m| m.internal == 1 && m.body.contains("refund request")),
        "the hand-over note is internal"
    );

    // The agent sees it in the queue, takes it, replies; the visitor sees the reply.
    let body = text(
        app.clone()
            .oneshot(get("/agent?tab=waiting", Some(&agent_cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Ada") && body.contains("My film") && body.contains("guest"),
        "{body}"
    );
    let body = text(
        app.clone()
            .oneshot(get(&format!("/agent/c/{conv}"), Some(&agent_cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Internal note")
            && body.contains("refund request")
            && body.contains("Take this conversation"),
        "{body}"
    );
    let agent_csrf = body
        .split("name=\"_csrf\" value=\"")
        .nth(1)
        .unwrap()
        .split('"')
        .next()
        .unwrap()
        .to_string();
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/agent/c/{conv}/reply"),
            &format!(
                "_csrf={agent_csrf}&_format=json&body=Hi+Ada%2C+I+will+refund+the+film+today."
            ),
            Some(&agent_cookie),
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["message"]["sender"], "agent", "{j}");
    let res = app
        .clone()
        .oneshot(get(
            &format!("/chat/{conv}/messages?after=0"),
            Some(&visitor_cookie),
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["status"], "assigned");
    assert_eq!(j["agent"], "Sam Agent");
    assert!(
        j["messages"]
            .as_array()
            .unwrap()
            .iter()
            .any(|m| m["sender"] == "agent"
                && m["body"].as_str().unwrap().contains("refund the film")),
        "{j}"
    );
    assert!(
        !j["messages"]
            .as_array()
            .unwrap()
            .iter()
            .any(|m| m["internal"] == true),
        "visitors never see internal notes"
    );
    assert_eq!(
        j["online"], true,
        "the agent's console polls count as online"
    );
    // AI draft for the agent, close, rating, reopening.
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/agent/c/{conv}/suggest"),
            &format!("_csrf={agent_csrf}"),
            Some(&agent_cookie),
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert!(j["draft"].as_str().unwrap().contains("five days"), "{j}");
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/agent/c/{conv}/close"),
            &format!("_csrf={agent_csrf}"),
            Some(&agent_cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            &format!("/chat/{conv}/rate"),
            r#"{"rating":5,"note":"quick"}"#,
            &visitor_cookie,
            "",
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(st.support.counts().await.unwrap()["rated"], 1);
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            &format!("/chat/{conv}/send"),
            r#"{"body":"One more thing"}"#,
            &visitor_cookie,
            "",
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(
        j["status"], "assigned",
        "writing again reopens with the same agent: {j}"
    );

    // A signed-in customer: the assistant may look up their own records.
    let now = mms_core::now();
    sqlx::query("INSERT INTO products (uuid, slug, type, title, price_cents, currency, status, created_at, updated_at) VALUES ('p1','film','video','Film',4900,'USD','published',?,?)").bind(&now).bind(&now).execute(&st.db.pool).await.unwrap();
    let res = app.clone().oneshot(form("POST", "/register", "email=bob%40example.com&name=Bob&password=bobs-long-password&password_repeat=bobs-long-password", None)).await.unwrap();
    let bob_cookie = cookie_of(&res);
    let bob = st.users.by_email("bob@example.com").await.unwrap().unwrap();
    let film = st.products.by_slug("film").await.unwrap().unwrap();
    let order = st
        .commerce
        .create_external_order(
            bob.id,
            "woocommerce",
            "77",
            "USD",
            &[(film, 1, 4900)],
            0,
            0,
            "GB",
        )
        .await
        .unwrap();
    routes::shop::complete_paid(&st, &order, "woocommerce", Some("77"), None, None)
        .await
        .map_err(|e| e.0)
        .unwrap();
    let body = text(
        app.clone()
            .oneshot(get("/account/help", Some(&bob_cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains("Help") && body.contains("/embed/chat"),
        "{body}"
    );
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            "/chat/start",
            r#"{"subject":"Order","message":"Is my order paid?"}"#,
            &bob_cookie,
            "",
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["status"], "open", "{j}");
    assert!(j["messages"][0]["body"].as_str().unwrap().contains("paid"));
    let bob_conv = j["conversation"].as_str().unwrap().to_string();
    let body = text(
        app.clone()
            .oneshot(get(&format!("/agent/c/{bob_conv}"), Some(&agent_cookie)))
            .await
            .unwrap(),
    )
    .await;
    assert!(
        body.contains(&order.number) && body.contains("<h3>Access</h3>"),
        "agents see the customer's records: {body}"
    );
    let res = app
        .clone()
        .oneshot(get("/embed/chat", Some(&bob_cookie)))
        .await
        .unwrap();
    assert!(
        text(res)
            .await
            .contains(&format!("data-existing=\"{bob_conv}\"")),
        "the open conversation resumes"
    );

    // Modes: agents only skips the assistant; off refuses; guests can be blocked.
    st.settings.set("chat.mode", "agents_only").await.unwrap();
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            "/chat/start",
            &format!(
                r#"{{"site":"{site}","name":"Cy","email":"cy@example.com","message":"Hello"}}"#
            ),
            "",
            "",
        ))
        .await
        .unwrap();
    let j: serde_json::Value = serde_json::from_slice(&bytes(res).await).unwrap();
    assert_eq!(j["status"], "waiting", "{j}");
    st.settings.set("chat.guest", "0").await.unwrap();
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            "/chat/start",
            &format!(
                r#"{{"site":"{site}","name":"Di","email":"di@example.com","message":"Hello"}}"#
            ),
            "",
            "",
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);
    st.settings.set("chat.mode", "off").await.unwrap();
    let res = app
        .clone()
        .oneshot(json_req(
            "POST",
            "/chat/start",
            r#"{"message":"Hello"}"#,
            &bob_cookie,
            "",
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::FORBIDDEN);

    // Agent status is granted and removed by administrators only.
    assert_eq!(
        app.clone()
            .oneshot(form(
                "POST",
                &format!("/admin/customers/{}/agent", sam.uuid),
                &format!("_csrf={agent_csrf}&agent=0"),
                Some(&agent_cookie)
            ))
            .await
            .unwrap()
            .status(),
        StatusCode::FORBIDDEN
    );
    let res = app
        .clone()
        .oneshot(form(
            "POST",
            &format!("/admin/customers/{}/agent", sam.uuid),
            &format!("_csrf={csrf}&agent=0"),
            Some(&admin_cookie),
        ))
        .await
        .unwrap();
    assert_eq!(res.status(), StatusCode::SEE_OTHER);
    assert_eq!(
        app.clone()
            .oneshot(get("/agent", Some(&agent_cookie)))
            .await
            .unwrap()
            .status(),
        StatusCode::FORBIDDEN
    );
    let body = text(
        app.clone()
            .oneshot(get(
                &format!("/admin/customers/{}", sam.uuid),
                Some(&admin_cookie),
            ))
            .await
            .unwrap(),
    )
    .await;
    assert!(body.contains("Make support agent"), "{body}");
}
