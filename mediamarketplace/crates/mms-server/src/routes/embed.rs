//! Embeddable storefront fragments consumed by the bridge plugins through iframes.

use crate::app::AppState;
use crate::errors::AppResult;
use crate::routes::bridges;
use axum::extract::{Query, State};
use axum::http::{header, StatusCode};
use axum::response::{Html, IntoResponse, Response};
use minijinja::context;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
pub struct EmbedQuery {
    site: Option<String>,
    #[serde(default)]
    category: String,
    #[serde(default = "default_view")]
    view: String,
}

fn default_view() -> String {
    "grid".into()
}

#[derive(Serialize, sqlx::FromRow)]
struct Card {
    uuid: String,
    slug: String,
    r#type: String,
    title: String,
    description: Option<String>,
    price_cents: i64,
    currency: String,
    featured: i64,
}

pub async fn showcase(
    State(state): State<AppState>,
    Query(q): Query<EmbedQuery>,
) -> AppResult<Response> {
    // Embeds are only served to registered bridge sites so the frame-ancestors policy is explicit.
    let Some(site_uuid) = q.site.as_deref() else {
        return Ok((StatusCode::BAD_REQUEST, "site parameter required").into_response());
    };
    let Some(site) = bridges::by_uuid(&state, site_uuid).await? else {
        return Ok((StatusCode::FORBIDDEN, "Unknown bridge site").into_response());
    };
    let cards = sqlx::query_as::<_, Card>("SELECT uuid, slug, type, title, description, price_cents, currency, featured FROM products WHERE status = 'published' ORDER BY featured DESC, id DESC LIMIT 48")
        .fetch_all(&state.db.pool).await?;
    let view = if q.view == "list" { "list" } else { "grid" };
    let site_name = state.settings.get("general.site_name").await?;
    let html = state.render("embed_showcase.html", context! { cards, view, category => q.category, site_name, public_url => state.config.server.public_url })?;
    Ok((
        [
            (
                header::CONTENT_SECURITY_POLICY,
                format!("frame-ancestors 'self' {}", site.origin),
            ),
            (header::CACHE_CONTROL, "private, no-store".to_string()),
        ],
        Html(html),
    )
        .into_response())
}

/// Tiny loader the bridge plugins print: turns a <div data-mms-embed> into an auto-sized iframe.
pub async fn loader() -> Response {
    (
        [
            (
                header::CONTENT_TYPE,
                "application/javascript; charset=utf-8",
            ),
            (header::CACHE_CONTROL, "public, max-age=3600"),
        ],
        include_str!("../../static/embed.js"),
    )
        .into_response()
}

pub async fn css() -> Response {
    (
        [
            (header::CONTENT_TYPE, "text/css; charset=utf-8"),
            (header::CACHE_CONTROL, "public, max-age=3600"),
        ],
        include_str!("../../static/mms.css"),
    )
        .into_response()
}
