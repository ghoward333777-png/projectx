//! Storefront pages framed by the website: showcase, product, player, checkout placeholder, static assets.

use crate::app::AppState;
use crate::auth::MaybeUser;
use crate::errors::AppResult;
use crate::routes::bridges;
use axum::extract::{Path, Query, State};
use axum::http::{header, StatusCode};
use axum::response::{Html, IntoResponse, Response};
use minijinja::context;
use mms_core::entitlements::Subject;
use mms_core::products::{type_label, ShowcaseQuery, TYPES};
use serde::Deserialize;

#[derive(Deserialize)]
pub struct EmbedQuery {
    site: Option<String>,
    #[serde(default)]
    q: String,
    #[serde(default, rename = "type")]
    r#type: String,
    #[serde(default)]
    category: String,
    #[serde(default)]
    sort: String,
    #[serde(default)]
    featured: String,
    #[serde(default = "one")]
    page: i64,
    #[serde(default = "default_view")]
    view: String,
    #[serde(default)]
    menu: String,
}

fn one() -> i64 {
    1
}

fn default_view() -> String {
    "grid".into()
}

/// Every embed is served only to the declared site and framed only from its origin.
async fn site_policy(state: &AppState, site: Option<&str>) -> Result<String, Response> {
    let Some(site_uuid) = site else {
        return Err((StatusCode::BAD_REQUEST, "site parameter required").into_response());
    };
    match bridges::by_uuid(state, site_uuid).await {
        Ok(Some(s)) => Ok(format!("frame-ancestors 'self' {}", s.origin)),
        Ok(None) => Err((StatusCode::FORBIDDEN, "Unknown site").into_response()),
        Err(e) => Err(crate::errors::AppError(e).into_response()),
    }
}

fn framed(csp: String, html: String) -> Response {
    (
        [
            (header::CONTENT_SECURITY_POLICY, csp),
            (header::CACHE_CONTROL, "private, no-store".to_string()),
        ],
        Html(html),
    )
        .into_response()
}

pub async fn showcase(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Query(q): Query<EmbedQuery>,
) -> AppResult<Response> {
    let csp = match site_policy(&state, q.site.as_deref()).await {
        Ok(c) => c,
        Err(r) => return Ok(r),
    };
    let per = 24;
    let (cards, total) = state
        .products
        .showcase(&ShowcaseQuery {
            q: q.q.clone(),
            r#type: q.r#type.clone(),
            category: q.category.clone(),
            sort: q.sort.clone(),
            featured_only: q.featured == "1",
            page: q.page,
            per_page: per,
        })
        .await?;
    let categories = state.products.categories().await?;
    let view = if q.view == "list" { "list" } else { "grid" };
    let site_name = state.settings.get("general.site_name").await?;
    let show_sales = true;
    let html = state.render("embed_showcase.html", context! {
        cards => cards.iter().map(|c| context!{ c, type_label => type_label(&c.r#type) }).collect::<Vec<_>>(),
        total, page => q.page, pages => (total + per - 1) / per, view, q => q.q, type_filter => q.r#type, category => q.category, sort => q.sort, featured => q.featured,
        site => q.site.clone().unwrap_or_default(), categories, types => TYPES, site_name, show_sales, user, menu => q.menu,
    })?;
    Ok(framed(csp, html))
}

#[derive(Deserialize)]
pub struct SiteQuery {
    site: Option<String>,
}

pub async fn product(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Path(slug): Path<String>,
    Query(q): Query<SiteQuery>,
) -> AppResult<Response> {
    let csp = match site_policy(&state, q.site.as_deref()).await {
        Ok(c) => c,
        Err(r) => return Ok(r),
    };
    let Some(p) = state.products.by_slug(&slug).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if p.status != "published" {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }
    state.products.record_view(p.id).await?;
    let media = match p.media_id {
        Some(id) => state.media.by_id(id).await?,
        None => None,
    };
    let preview = match p.preview_media_id {
        Some(id) => state.media.by_id(id).await?,
        None => None,
    };
    let thumb = preview
        .as_ref()
        .and_then(|m| m.thumbnail_path.clone())
        .or_else(|| media.as_ref().and_then(|m| m.thumbnail_path.clone()));
    let entitled = match &user {
        Some(u) => {
            state
                .entitlements
                .check(u.id, &Subject::Product(p.id), &mms_core::now())
                .await?
        }
        None => false,
    };
    // Free preview clip: only for streaming types with a preview length; served with a short-lived token.
    let preview_len: i64 = p.setting("preview_length").parse().unwrap_or(0);
    let preview_src = if matches!(p.r#type.as_str(), "video" | "audio") && preview_len > 0 {
        media.as_ref().map(|m| {
            state.url(&format!(
                "/m/{}",
                crate::routes::media::file_token(&state, &m.uuid, None, 600)
            ))
        })
    } else {
        None
    };
    let ratings = sqlx::query_as::<_, (i64, Option<String>, String)>("SELECT r.stars, r.review, u.name FROM ratings r JOIN users u ON u.id = r.user_id WHERE r.product_id = ? AND r.status = 'approved' ORDER BY r.id DESC LIMIT 20")
        .bind(p.id).fetch_all(&state.db.pool).await?;
    let site_name = state.settings.get("general.site_name").await?;
    let html = state.render("embed_product.html", context! {
        p, type_label => type_label(&p.r#type), media, thumb, entitled, user, preview_src, preview_start => p.setting("preview_start"), preview_len,
        ratings => ratings.iter().map(|(s, r, n)| context!{ stars => s, review => r, name => n }).collect::<Vec<_>>(),
        site => q.site.clone().unwrap_or_default(), site_name, settings => p.settings_json(),
    })?;
    Ok(framed(csp, html))
}

/// Full player for an entitled customer.
pub async fn player(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Path(slug): Path<String>,
    Query(q): Query<SiteQuery>,
) -> AppResult<Response> {
    let csp = match q.site.as_deref() {
        Some(_) => match site_policy(&state, q.site.as_deref()).await {
            Ok(c) => c,
            Err(r) => return Ok(r),
        },
        None => "frame-ancestors 'self'".to_string(), // opened from My Media on the store itself
    };
    let Some(p) = state.products.by_slug(&slug).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let Some(u) = user else {
        return Ok(axum::response::Redirect::to(
            &state.url(&format!("/login?return=%2Fembed%2Fplayer%2F{slug}")),
        )
        .into_response());
    };
    if !state
        .entitlements
        .check(u.id, &Subject::Product(p.id), &mms_core::now())
        .await?
    {
        return Ok((
            StatusCode::FORBIDDEN,
            Html("<p style=\"font-family:sans-serif\">You do not have access to this item.</p>"),
        )
            .into_response());
    }
    let media = match p.media_id {
        Some(id) => state.media.by_id(id).await?,
        None => None,
    };
    let src = media.as_ref().map(|m| {
        state.url(&format!(
            "/m/{}",
            crate::routes::media::file_token(&state, &m.uuid, Some(u.id), 3600)
        ))
    });
    let poster = media
        .as_ref()
        .and_then(|m| m.thumbnail_path.clone())
        .map(|t| state.url(&format!("/media/{t}")));
    let player = {
        let s = p.setting("player");
        if s.is_empty() {
            state.settings.get("players.default").await?
        } else {
            s
        }
    };
    let download = p.setting("download_allowed") == "true";
    let site_name = state.settings.get("general.site_name").await?;
    let html = state.render("embed_player.html", context! { p, type_label => type_label(&p.r#type), media, src, poster, player, download, user => u, site_name, settings => p.settings_json(), site => q.site.clone().unwrap_or_default() })?;
    Ok(framed(csp, html))
}

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

/// Embedded static assets: player scripts and vendored players.
pub async fn static_file(Path(path): Path<String>) -> Response {
    let (bytes, mime): (&'static [u8], &'static str) = match path.as_str() {
        "mms.css" => (
            include_bytes!("../../static/mms.css"),
            "text/css; charset=utf-8",
        ),
        "mms-player.js" => (
            include_bytes!("../../static/mms-player.js"),
            "application/javascript; charset=utf-8",
        ),
        "mms-upload.js" => (
            include_bytes!("../../static/mms-upload.js"),
            "application/javascript; charset=utf-8",
        ),
        "mms-widget.js" => (
            include_bytes!("../../static/mms-widget.js"),
            "application/javascript; charset=utf-8",
        ),
        "mms-builder.js" => (
            include_bytes!("../../static/mms-builder.js"),
            "application/javascript; charset=utf-8",
        ),
        "mms-builder.css" => (
            include_bytes!("../../static/mms-builder.css"),
            "text/css; charset=utf-8",
        ),
        "vendor/plyr.min.js" => (
            include_bytes!("../../static/vendor/plyr.min.js"),
            "application/javascript; charset=utf-8",
        ),
        "vendor/plyr.css" => (
            include_bytes!("../../static/vendor/plyr.css"),
            "text/css; charset=utf-8",
        ),
        "vendor/plyr.svg" => (
            include_bytes!("../../static/vendor/plyr.svg"),
            "image/svg+xml",
        ),
        "vendor/video.min.js" => (
            include_bytes!("../../static/vendor/video.min.js"),
            "application/javascript; charset=utf-8",
        ),
        "vendor/video-js.min.css" => (
            include_bytes!("../../static/vendor/video-js.min.css"),
            "text/css; charset=utf-8",
        ),
        _ => return StatusCode::NOT_FOUND.into_response(),
    };
    (
        [
            (header::CONTENT_TYPE, mime),
            (header::CACHE_CONTROL, "public, max-age=86400"),
        ],
        bytes,
    )
        .into_response()
}
