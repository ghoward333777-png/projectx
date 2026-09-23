//! Admin: API keys and outbound webhooks. Public: the key-authenticated JSON API.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use crate::routes::customers::CsrfOnly;
use axum::async_trait;
use axum::extract::{FromRequestParts, Path, Query, State};
use axum::http::request::Parts;
use axum::http::{header, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::{Form, Json};
use minijinja::context;
use mms_core::integrations::ApiKey;
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
pub struct PageQuery {
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
    #[serde(default)]
    new_key: String,
}

pub async fn page(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<PageQuery>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    let keys = state.integrations.keys().await?;
    let endpoints = state.integrations.endpoints().await?;
    let deliveries = state.integrations.deliveries(50).await?;
    let site_name = state.settings.get("general.site_name").await?;
    let mode = state.settings.get("commerce.mode").await?;
    let mut mappings = Vec::new();
    if mms_core::commerce_bridge::is_system(&mode) {
        for m in state.commerce_bridge.mappings(&mode).await? {
            let title = state
                .products
                .by_id(m.product_id)
                .await?
                .map(|p| p.title)
                .unwrap_or_default();
            mappings.push(context! { title, external_id => m.external_id, external_url => m.external_url, synced_at => m.synced_at });
        }
    }
    let bridge = context! { mode => mode.clone(), label => mms_core::commerce_bridge::system_label(&mode), active => mms_core::commerce_bridge::is_system(&mode), mappings, events => state.commerce_bridge.events(30).await?, cart_url => state.settings.get("commerce.cart_url").await?, unlinked => state.settings.get("commerce.unlinked").await? };
    Ok(Html(state.render("integrations.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "integrations", keys, endpoints, deliveries, events => mms_core::integrations::EVENTS, notice => q.notice, error => q.error, new_key => q.new_key, public_url => state.config.server.public_url.trim_end_matches('/'), bridge })?).into_response())
}

pub async fn create_key(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    match state
        .integrations
        .create_key(
            f.get("name").map(String::as_str).unwrap_or(""),
            f.get("scopes").map(String::as_str).unwrap_or("read"),
        )
        .await
    {
        Ok(plain) => Ok(
            Redirect::to(&state.url(&format!("/admin/integrations?new_key={plain}")))
                .into_response(),
        ),
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/integrations?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn revoke_key(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.integrations.revoke_key(id).await?;
    Ok(Redirect::to(&state.url("/admin/integrations?notice=Key+revoked.")).into_response())
}

pub async fn create_endpoint(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let events: Vec<String> = f
        .iter()
        .filter(|(k, v)| k.starts_with("ev_") && v.as_str() == "1")
        .map(|(k, _)| k[3..].to_string())
        .collect();
    match state.integrations.create_endpoint(f.get("url").map(String::as_str).unwrap_or(""), &events.join(",")).await {
        Ok(_) => Ok(Redirect::to(&state.url("/admin/integrations?notice=Webhook+added.+Copy+its+signing+secret+into+the+receiving+system.")).into_response()),
        Err(e) => Ok(Redirect::to(&state.url(&format!("/admin/integrations?error={}", crate::routes::media::urlencoding(&e.to_string())))).into_response()),
    }
}

pub async fn delete_endpoint(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.integrations.delete_endpoint(id).await?;
    Ok(Redirect::to(&state.url("/admin/integrations?notice=Webhook+removed.")).into_response())
}

pub async fn test_endpoint(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.admin_only() {
        return Ok(r);
    }
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    crate::routes::shop::emit(
        &state,
        "order.paid",
        serde_json::json!({ "test": true, "number": "ORD-TEST" }),
    )
    .await?;
    Ok(Redirect::to(&state.url(
        "/admin/integrations?notice=Test+event+queued+for+every+endpoint+subscribed+to+order.paid.",
    ))
    .into_response())
}

// ----- key-authenticated JSON API -----

/// `Authorization: Bearer mms_…`. Administrators signed in with a session may also call these.
pub struct ApiCaller {
    pub key: Option<ApiKey>,
}

#[async_trait]
impl FromRequestParts<AppState> for ApiCaller {
    type Rejection = Response;

    async fn from_request_parts(
        parts: &mut Parts,
        state: &AppState,
    ) -> Result<Self, Self::Rejection> {
        if let Some(bearer) = parts
            .headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "))
        {
            return match state.integrations.authenticate(bearer).await {
                Ok(Some(key)) => Ok(ApiCaller { key: Some(key) }),
                _ => Err((StatusCode::UNAUTHORIZED, Json(serde_json::json!({ "error": { "code": "unauthorized", "message": "Invalid API key" } }))).into_response()),
            };
        }
        match AdminUser::from_request_parts(parts, state).await {
            Ok(_) => Ok(ApiCaller { key: None }),
            Err(_) => Err((StatusCode::UNAUTHORIZED, Json(serde_json::json!({ "error": { "code": "unauthorized", "message": "Send an API key as a Bearer token" } }))).into_response()),
        }
    }
}

pub async fn api_orders(
    State(state): State<AppState>,
    _c: ApiCaller,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let orders = state
        .commerce
        .orders(
            q.get("q").map(String::as_str).unwrap_or(""),
            q.get("status").map(String::as_str).unwrap_or(""),
            None,
        )
        .await?;
    Ok(Json(serde_json::json!({ "data": orders })).into_response())
}

pub async fn api_order(
    State(state): State<AppState>,
    _c: ApiCaller,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(o) = state.commerce.order_by_uuid(&uuid).await? else {
        return Ok((
            StatusCode::NOT_FOUND,
            Json(
                serde_json::json!({ "error": { "code": "not_found", "message": "No such order" } }),
            ),
        )
            .into_response());
    };
    let items = state.commerce.items(o.id).await?;
    let payments = state.commerce.payments(o.id).await?;
    Ok(
        Json(serde_json::json!({ "data": { "order": o, "items": items, "payments": payments } }))
            .into_response(),
    )
}

pub async fn api_products(
    State(state): State<AppState>,
    _c: ApiCaller,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let products = state
        .products
        .list_admin(
            q.get("q").map(String::as_str).unwrap_or(""),
            q.get("type").map(String::as_str).unwrap_or(""),
            q.get("status").map(String::as_str).unwrap_or(""),
        )
        .await?;
    Ok(Json(serde_json::json!({ "data": products })).into_response())
}

pub async fn api_customers(
    State(state): State<AppState>,
    _c: ApiCaller,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let like = format!("%{}%", q.get("q").map(String::as_str).unwrap_or("").trim());
    let rows = sqlx::query_as::<_, (String, String, String, String, String)>("SELECT uuid, email, name, role, status FROM users WHERE email LIKE ? OR name LIKE ? ORDER BY id DESC LIMIT 500")
        .bind(&like).bind(&like).fetch_all(&state.db.pool).await?;
    Ok(Json(serde_json::json!({ "data": rows.into_iter().map(|(uuid, email, name, role, status)| serde_json::json!({ "uuid": uuid, "email": email, "name": name, "role": role, "status": status })).collect::<Vec<_>>() })).into_response())
}

pub async fn api_entitlements(
    State(state): State<AppState>,
    _c: ApiCaller,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(uid) = sqlx::query_scalar::<_, i64>("SELECT id FROM users WHERE uuid = ?")
        .bind(&uuid)
        .fetch_optional(&state.db.pool)
        .await?
    else {
        return Ok((StatusCode::NOT_FOUND, Json(serde_json::json!({ "error": { "code": "not_found", "message": "No such customer" } }))).into_response());
    };
    Ok(
        Json(serde_json::json!({ "data": state.entitlements.for_user(uid).await? }))
            .into_response(),
    )
}

/// Write scope: grant a product, page or site pass by hand (the same thing the admin UI does).
#[derive(Deserialize)]
pub struct GrantBody {
    customer: String,
    #[serde(default)]
    product: String,
    #[serde(default)]
    scope: String,
    #[serde(default)]
    scope_ref: String,
    #[serde(default)]
    days: i64,
}

pub async fn api_grant(
    State(state): State<AppState>,
    c: ApiCaller,
    Json(b): Json<GrantBody>,
) -> AppResult<Response> {
    if c.key.as_ref().map(|k| k.scopes != "write").unwrap_or(false) {
        return Ok((StatusCode::FORBIDDEN, Json(serde_json::json!({ "error": { "code": "forbidden", "message": "This key is read-only" } }))).into_response());
    }
    let Some(uid) =
        sqlx::query_scalar::<_, i64>("SELECT id FROM users WHERE uuid = ? OR email = ?")
            .bind(&b.customer)
            .bind(&b.customer)
            .fetch_optional(&state.db.pool)
            .await?
    else {
        return Ok((StatusCode::NOT_FOUND, Json(serde_json::json!({ "error": { "code": "not_found", "message": "No such customer" } }))).into_response());
    };
    let now = mms_core::now();
    let ends = (b.days > 0).then(|| mms_core::commerce::add_days(&now, b.days));
    let source_ref = format!("api:{}", uuid::Uuid::new_v4());
    let (scope, scope_ref, product_id) = if !b.product.is_empty() {
        let Some(p) = state.products.by_slug(&b.product).await? else {
            return Ok((StatusCode::NOT_FOUND, Json(serde_json::json!({ "error": { "code": "not_found", "message": "No such product" } }))).into_response());
        };
        state
            .commerce
            .grant_for_product(uid, &p, "manual", &source_ref, &now)
            .await?;
        return Ok(Json(serde_json::json!({ "data": { "granted": true } })).into_response());
    } else {
        match b.scope.as_str() {
            "site" => ("site", String::new(), None),
            "page" | "category" => (b.scope.as_str(), b.scope_ref.clone(), None),
            _ => return Ok((StatusCode::BAD_REQUEST, Json(serde_json::json!({ "error": { "code": "invalid", "message": "Give a product slug or a scope of site, page or category" } }))).into_response()),
        }
    };
    state
        .entitlements
        .grant(mms_core::entitlements::Grant {
            user_id: uid,
            product_id,
            scope,
            scope_ref: &scope_ref,
            source: "manual",
            source_ref: &source_ref,
            starts_at: &now,
            ends_at: ends.as_deref(),
        })
        .await?;
    Ok(Json(serde_json::json!({ "data": { "granted": true } })).into_response())
}
