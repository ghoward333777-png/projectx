//! Session cookies and request extractors.

use crate::app::AppState;
use axum::async_trait;
use axum::extract::FromRequestParts;
use axum::http::request::Parts;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Redirect, Response};
use axum_extra::extract::cookie::{Cookie, CookieJar, SameSite};
use mms_core::users::User;
use serde::{Deserialize, Serialize};

pub const SESSION_COOKIE: &str = "mms_session";

#[derive(Serialize, Deserialize)]
struct SessionClaims {
    uid: i64,
    exp: i64,
    /// Random nonce so two logins never share a token; also used as the CSRF secret.
    n: String,
}

pub fn now_unix() -> i64 {
    chrono::Utc::now().timestamp()
}

/// Builds the session cookie for a user.
pub fn session_cookie(state: &AppState, user_id: i64) -> Cookie<'static> {
    use rand::RngCore;
    let mut nonce = [0u8; 16];
    rand::thread_rng().fill_bytes(&mut nonce);
    let claims = SessionClaims {
        uid: user_id,
        exp: now_unix() + state.config.security.session_ttl_seconds as i64,
        n: hex(&nonce),
    };
    let token = state.signer.sign(&claims);
    let mut c = Cookie::new(SESSION_COOKIE, token);
    c.set_path(cookie_path(state));
    c.set_http_only(true);
    c.set_same_site(SameSite::Lax);
    c.set_secure(state.config.server.public_url.starts_with("https://"));
    c
}

pub fn cookie_path(state: &AppState) -> String {
    if state.base.is_empty() {
        "/".to_string()
    } else {
        state.base.to_string()
    }
}

pub fn clear_cookie(state: &AppState) -> Cookie<'static> {
    let mut c = Cookie::new(SESSION_COOKIE, "");
    c.set_path(cookie_path(state));
    c.set_http_only(true);
    c.set_max_age(time::Duration::ZERO);
    c
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// CSRF token bound to the current session token.
pub fn csrf_token(state: &AppState, session_token: &str) -> String {
    use hmac::{Hmac, Mac};
    let mut mac =
        Hmac::<sha2::Sha256>::new_from_slice(session_token.as_bytes()).expect("any key length");
    mac.update(b"csrf");
    mac.update(state.config.security.secret_key.as_bytes());
    hex(&mac.finalize().into_bytes())
}

/// The logged-in user, if any. Never fails; handlers decide what anonymous means.
pub struct MaybeUser(pub Option<User>, pub Option<String>);

#[async_trait]
impl FromRequestParts<AppState> for MaybeUser {
    type Rejection = std::convert::Infallible;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let jar = CookieJar::from_headers(&parts.headers);
        let Some(token) = jar.get(SESSION_COOKIE).map(|c| c.value().to_string()) else {
            return Ok(MaybeUser(None, None));
        };
        let Ok(claims) = state.signer.verify::<SessionClaims>(&token, now_unix()) else {
            return Ok(MaybeUser(None, None));
        };
        match state.users.by_id(claims.uid).await {
            Ok(Some(u)) if u.status == "active" => Ok(MaybeUser(Some(u), Some(token))),
            _ => Ok(MaybeUser(None, None)),
        }
    }
}

/// An authenticated administrator; redirects to the login page otherwise.
pub struct AdminUser {
    pub user: User,
    pub csrf: String,
}

pub enum AdminRejection {
    Login(String),
    Forbidden,
}

impl IntoResponse for AdminRejection {
    fn into_response(self) -> Response {
        match self {
            AdminRejection::Login(base) => {
                Redirect::to(&format!("{base}/admin/login")).into_response()
            }
            AdminRejection::Forbidden => {
                (StatusCode::FORBIDDEN, "Administrator access required").into_response()
            }
        }
    }
}

#[async_trait]
impl FromRequestParts<AppState> for AdminUser {
    type Rejection = AdminRejection;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let MaybeUser(user, token) = MaybeUser::from_request_parts(parts, state)
            .await
            .expect("infallible");
        match (user, token) {
            (Some(user), Some(token)) if user.is_staff() => {
                let csrf = csrf_token(state, &token);
                Ok(AdminUser { user, csrf })
            }
            (Some(_), _) => Err(AdminRejection::Forbidden),
            _ => Err(AdminRejection::Login(state.base.to_string())),
        }
    }
}

impl AdminUser {
    /// A 403 for staff on administrator-only pages.
    pub fn admin_only(&self) -> Option<Response> {
        if self.user.is_admin() {
            None
        } else {
            Some((StatusCode::FORBIDDEN, "Administrator access required").into_response())
        }
    }

    /// Returns a 403 response when the submitted CSRF token does not match the session.
    pub fn csrf_error(&self, submitted: &str) -> Option<Response> {
        if submitted == self.csrf {
            None
        } else {
            Some(
                (
                    StatusCode::FORBIDDEN,
                    "Invalid or expired form token. Go back and try again.",
                )
                    .into_response(),
            )
        }
    }
}

/// A support agent (flagged agent, staff or administrator) with a CSRF token.
/// Agents are not staff: they never reach admin pages.
pub struct AgentUser {
    pub user: User,
    pub csrf: String,
}

pub enum AgentRejection {
    Login(String),
    Forbidden,
}

impl IntoResponse for AgentRejection {
    fn into_response(self) -> Response {
        match self {
            AgentRejection::Login(base) => {
                Redirect::to(&format!("{base}/login?return=%2Fagent")).into_response()
            }
            AgentRejection::Forbidden => {
                (StatusCode::FORBIDDEN, "Support agent access required").into_response()
            }
        }
    }
}

#[async_trait]
impl FromRequestParts<AppState> for AgentUser {
    type Rejection = AgentRejection;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        let MaybeUser(user, token) = MaybeUser::from_request_parts(parts, state)
            .await
            .expect("infallible");
        match (user, token) {
            (Some(user), Some(token)) if user.is_agent() => {
                let csrf = csrf_token(state, &token);
                Ok(AgentUser { user, csrf })
            }
            (Some(_), _) => Err(AgentRejection::Forbidden),
            _ => Err(AgentRejection::Login(state.base.to_string())),
        }
    }
}

impl AgentUser {
    pub fn csrf_error(&self, submitted: &str) -> Option<Response> {
        if submitted == self.csrf {
            None
        } else {
            Some(
                (
                    StatusCode::FORBIDDEN,
                    "Form token mismatch; reload and try again",
                )
                    .into_response(),
            )
        }
    }
}
