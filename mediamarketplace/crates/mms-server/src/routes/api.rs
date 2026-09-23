use crate::app::AppState;
use crate::auth::{AdminUser, MaybeUser};
use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;

pub async fn health(State(state): State<AppState>, _admin: AdminUser) -> Response {
    let report = mms_core::health::run(&state.config, &state.db).await;
    let status = if report.status == mms_core::health::Status::Fail {
        StatusCode::SERVICE_UNAVAILABLE
    } else {
        StatusCode::OK
    };
    (
        status,
        Json(serde_json::json!({ "data": report, "meta": { "version": mms_core::version() } })),
    )
        .into_response()
}

pub async fn me(MaybeUser(user, _): MaybeUser) -> Response {
    match user {
        Some(u) => Json(serde_json::json!({ "data": u })).into_response(),
        None => (StatusCode::UNAUTHORIZED, Json(serde_json::json!({ "error": { "code": "unauthenticated", "message": "Sign in first" } }))).into_response(),
    }
}

pub async fn my_entitlements(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
) -> Result<Response, crate::errors::AppError> {
    let Some(u) = user else {
        return Ok((StatusCode::UNAUTHORIZED, Json(serde_json::json!({ "error": { "code": "unauthenticated", "message": "Sign in first" } }))).into_response());
    };
    let rows = state.entitlements.for_user(u.id).await?;
    Ok(Json(serde_json::json!({ "data": rows })).into_response())
}

/// Unauthenticated liveness probe used by the bundled packages' supervisor.
pub async fn ping() -> Response {
    Json(serde_json::json!({ "ok": true, "version": mms_core::version() })).into_response()
}
