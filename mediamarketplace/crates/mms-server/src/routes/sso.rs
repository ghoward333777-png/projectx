//! Single sign-on from a bridged site.
//!
//! The bridge plugin signs `{sub, email, name, host, exp}` with the site's shared secret
//! and sends the visitor to `/sso?site=<uuid>&token=<token>&return=<path>`.

use crate::app::AppState;
use crate::auth;
use crate::errors::AppResult;
use crate::routes::bridges;
use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Redirect, Response};
use axum_extra::extract::CookieJar;
use mms_core::signer::Signer;
use serde::Deserialize;

#[derive(Deserialize)]
pub struct SsoQuery {
    site: String,
    token: String,
    #[serde(rename = "return")]
    return_to: Option<String>,
}

#[derive(Deserialize)]
pub struct SsoClaims {
    sub: String,
    email: String,
    #[serde(default)]
    name: String,
    host: String,
    /// Optional: "admin" asks for administrator rights; honoured only for sites with admin_sso.
    #[serde(default)]
    role: String,
    #[allow(dead_code)]
    exp: i64,
}

/// Only same-origin paths may be used as a return target.
pub fn safe_return(raw: Option<&str>) -> String {
    match raw {
        Some(p) if p.starts_with('/') && !p.starts_with("//") && !p.contains('\\') => p.to_string(),
        _ => "/account".to_string(),
    }
}

pub async fn login(
    State(state): State<AppState>,
    jar: CookieJar,
    Query(q): Query<SsoQuery>,
) -> AppResult<Response> {
    let Some(site) = bridges::by_uuid(&state, &q.site).await? else {
        return Ok((StatusCode::FORBIDDEN, "Unknown bridge site").into_response());
    };
    let secret = state.secrets.decrypt(&site.secret_enc)?;
    let claims =
        match Signer::from_shared_secret(&secret).verify::<SsoClaims>(&q.token, auth::now_unix()) {
            Ok(c) => c,
            Err(e) => {
                state
                    .audit
                    .record(
                        None,
                        "sso.rejected",
                        "bridge_site",
                        Some(&site.uuid),
                        None,
                        Some(serde_json::json!({ "reason": format!("{e:?}") })),
                    )
                    .await?;
                return Ok((StatusCode::FORBIDDEN, "Sign-on token rejected").into_response());
            }
        };
    if claims.host != site.host {
        return Ok((StatusCode::FORBIDDEN, "Sign-on token host mismatch").into_response());
    }
    let user = state
        .users
        .link_identity(
            &format!("{}:{}", site.host, site.uuid),
            &claims.sub,
            &claims.email,
            &claims.name,
        )
        .await?;
    let user = if claims.role == "admin" && site.admin_sso == 1 && user.role != "admin" {
        state.users.set_role(user.id, "admin").await?;
        state
            .audit
            .record(
                Some(user.id),
                "sso.promoted_admin",
                "user",
                Some(&user.uuid),
                None,
                Some(serde_json::json!({ "site": site.uuid })),
            )
            .await?;
        state.users.by_id(user.id).await?.unwrap_or(user)
    } else {
        user
    };
    state
        .audit
        .record(
            Some(user.id),
            "sso.login",
            "user",
            Some(&user.uuid),
            None,
            Some(serde_json::json!({ "site": site.uuid })),
        )
        .await?;
    let jar = jar.add(auth::session_cookie(&state, user.id));
    Ok((
        jar,
        Redirect::to(&state.url(&safe_return(q.return_to.as_deref()))),
    )
        .into_response())
}
