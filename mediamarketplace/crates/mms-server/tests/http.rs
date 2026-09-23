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
    let tmp = std::env::temp_dir().join(format!("mms-http-{}", uuid::Uuid::new_v4()));
    let config = mms_core::config::Config::generate(tmp, "127.0.0.1:0", "http://localhost:8090");
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
