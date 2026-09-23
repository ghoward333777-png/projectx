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

#[derive(serde::Deserialize)]
pub struct SessionStart {
    product: String,
    #[serde(default)]
    player: String,
}

/// Opens a playback session for analytics (and, later, Level 2 watermark binding).
pub async fn playback_session(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Json(body): Json<SessionStart>,
) -> Result<Response, crate::errors::AppError> {
    let Some(p) = state.products.by_slug(&body.product).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let now = mms_core::now();
    let uuid = uuid::Uuid::new_v4().to_string();
    sqlx::query("INSERT INTO playback_sessions (uuid, user_id, product_id, media_id, player, started_at, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)")
        .bind(&uuid).bind(user.map(|u| u.id)).bind(p.id).bind(p.media_id).bind(body.player.chars().take(32).collect::<String>()).bind(&now).bind(&now)
        .execute(&state.db.pool).await?;
    Ok(Json(serde_json::json!({ "data": { "session": uuid } })).into_response())
}

#[derive(serde::Deserialize)]
pub struct Heartbeat {
    session: String,
    #[serde(default)]
    position_ms: i64,
    #[serde(default)]
    duration_ms: Option<i64>,
    #[serde(default)]
    ended: bool,
}

pub async fn playback_heartbeat(
    State(state): State<AppState>,
    Json(body): Json<Heartbeat>,
) -> Result<Response, crate::errors::AppError> {
    let now = mms_core::now();
    sqlx::query("UPDATE playback_sessions SET position_ms = ?, duration_ms = COALESCE(?, duration_ms), last_seen = ?, ended_at = CASE WHEN ? THEN ? ELSE ended_at END WHERE uuid = ?")
        .bind(body.position_ms.max(0)).bind(body.duration_ms).bind(&now).bind(body.ended).bind(&now).bind(&body.session)
        .execute(&state.db.pool).await?;
    Ok(Json(serde_json::json!({ "data": { "ok": true } })).into_response())
}

#[derive(serde::Deserialize)]
pub struct RatingBody {
    product: String,
    stars: i64,
    #[serde(default)]
    review: String,
}

/// One rating per entitled customer per product.
pub async fn rate(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Json(body): Json<RatingBody>,
) -> Result<Response, crate::errors::AppError> {
    let Some(u) = user else {
        return Ok((StatusCode::UNAUTHORIZED, Json(serde_json::json!({ "error": { "code": "unauthenticated", "message": "Sign in first" } }))).into_response());
    };
    let Some(p) = state.products.by_slug(&body.product).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if !state
        .entitlements
        .check(
            u.id,
            &mms_core::entitlements::Subject::Product(p.id),
            &mms_core::now(),
        )
        .await?
    {
        return Ok((StatusCode::FORBIDDEN, Json(serde_json::json!({ "error": { "code": "not_entitled", "message": "Only customers who own this item can rate it" } }))).into_response());
    }
    if let Err(e) = state
        .products
        .rate(
            p.id,
            u.id,
            body.stars,
            &body.review.chars().take(2000).collect::<String>(),
            true,
        )
        .await
    {
        return Ok((
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({ "error": { "code": "invalid", "message": e.to_string() } })),
        )
            .into_response());
    }
    Ok(Json(serde_json::json!({ "data": { "ok": true } })).into_response())
}
