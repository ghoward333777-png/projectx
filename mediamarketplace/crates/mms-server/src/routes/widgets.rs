//! Widget builder: admin pages, JSON API used by the builder, exports, storefront embed.

use crate::app::AppState;
use crate::auth::{AdminUser, MaybeUser};
use crate::errors::AppResult;
use crate::routes::bridges;
use axum::extract::{Path, Query, State};
use axum::http::{header, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::{Form, Json};
use minijinja::context;
use mms_core::render::{self, Definition, ProductInfo, RenderContext, ANIMATIONS, COMPONENT_KINDS};
use mms_core::templates;
use serde::Deserialize;

/// Renders a widget for a site: resolves media and products, applies scheme and custom CSS.
pub async fn render_widget(
    state: &AppState,
    definition: &str,
    custom_css: &str,
    theme: &str,
    scheme: &str,
    uuid: &str,
    site: &str,
) -> anyhow::Result<render::Rendered> {
    let def = Definition::parse(definition).map_err(|e| anyhow::anyhow!(e))?;
    // Resolve everything the renderer may ask for up front (the renderer is synchronous).
    let mut media_ids = Vec::new();
    let mut product_slugs = Vec::new();
    def.root
        .walk(&mut |c| {
            for key in ["media", "poster"] {
                if let Some(serde_json::Value::String(v)) = c.props.get(key) {
                    if !v.is_empty() {
                        media_ids.push(v.clone());
                    }
                }
            }
            if let Some(serde_json::Value::String(v)) = c.props.get("product") {
                if !v.is_empty() {
                    product_slugs.push(v.clone());
                }
            }
            Ok(())
        })
        .ok();
    let mut media_map = std::collections::HashMap::new();
    for id in media_ids {
        if let Some(m) = state.media.by_uuid(&id).await? {
            let url = match (&m.thumbnail_path, m.private == 1, m.r#type.as_str()) {
                (_, false, "video" | "audio" | "pdf") => {
                    Some(state.url(&format!("/media/{}", m.original_path)))
                }
                (Some(t), _, _) => {
                    Some(state.url(&format!("/media/{}", t.replace("320.jpg", "1280.jpg"))))
                }
                (None, false, _) => Some(state.url(&format!("/media/{}", m.original_path))),
                _ => None,
            };
            if let Some(u) = url {
                media_map.insert(id, u);
            }
        }
    }
    let mut product_map = std::collections::HashMap::new();
    for slug in product_slugs {
        if let Some(p) = state.products.by_slug(&slug).await? {
            let thumb = match p.media_id.or(p.preview_media_id) {
                Some(id) => state
                    .media
                    .by_id(id)
                    .await?
                    .and_then(|m| m.thumbnail_path)
                    .map(|t| state.url(&format!("/media/{t}"))),
                None => None,
            };
            let price = if p.price_cents == 0 {
                "Free".to_string()
            } else {
                format!(
                    "{} {}.{:02}",
                    p.currency,
                    p.price_cents / 100,
                    p.price_cents % 100
                )
            };
            let buy = match crate::routes::commerce_bridge::buy_for(state, &p)
                .await
                .map_err(|e| e.0)?
            {
                crate::routes::commerce_bridge::Buy::External(u) => Some(u),
                _ => None,
            };
            product_map.insert(
                slug.clone(),
                ProductInfo {
                    slug: p.slug.clone(),
                    title: p.title.clone(),
                    description: p.description.clone().unwrap_or_default(),
                    price,
                    thumb,
                    kind: mms_core::products::type_label(&p.r#type).to_string(),
                    buy_url: buy.clone(),
                },
            );
        }
    }
    let scheme_vars = scheme_vars(state, scheme, theme).await?;
    let media_fn = |id: &str| media_map.get(id).cloned();
    let product_fn = |slug: &str| product_map.get(slug).cloned();
    let base = state.base.to_string();
    Ok(render::render(
        &def,
        &RenderContext {
            uuid,
            base: &base,
            site,
            theme,
            scheme_vars: &scheme_vars,
            custom_css,
            media_url: &media_fn,
            product: &product_fn,
        },
    ))
}

/// Scheme variables for a slug, with the dark variant when the theme is dark.
pub async fn scheme_vars(
    state: &AppState,
    slug: &str,
    theme: &str,
) -> anyhow::Result<Vec<(String, String)>> {
    let vars = match templates::builtin_schemes()
        .into_iter()
        .find(|s| s.slug == slug)
    {
        Some(s) => s.vars,
        None => {
            let row: Option<String> =
                sqlx::query_scalar("SELECT vars FROM colour_schemes WHERE slug = ?")
                    .bind(slug)
                    .fetch_optional(&state.db.pool)
                    .await?;
            match row.and_then(|v| serde_json::from_str::<Vec<(String, String)>>(&v).ok()) {
                Some(v) => v,
                None => templates::builtin_schemes()[0].vars.clone(),
            }
        }
    };
    Ok(if theme == "dark" {
        templates::auto_dark(&vars)
    } else {
        vars
    })
}

pub async fn all_schemes(state: &AppState) -> anyhow::Result<Vec<templates::ColourScheme>> {
    let mut out = templates::builtin_schemes();
    let rows: Vec<(String, String, String)> =
        sqlx::query_as("SELECT slug, name, vars FROM colour_schemes ORDER BY name")
            .fetch_all(&state.db.pool)
            .await?;
    for (slug, name, vars) in rows {
        out.push(templates::ColourScheme {
            slug,
            name,
            vars: serde_json::from_str(&vars).unwrap_or_default(),
            builtin: false,
        });
    }
    Ok(out)
}

// ----- admin pages -----

#[derive(Deserialize)]
pub struct ListQuery {
    #[serde(default)]
    q: String,
    #[serde(default)]
    status: String,
    #[serde(default)]
    notice: String,
}

pub async fn list(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let widgets = state.widgets.list(&q.q, &q.status).await?;
    let site_name = state.settings.get("general.site_name").await?;
    let site_uuid: Option<String> = sqlx::query_scalar(
        "SELECT uuid FROM bridge_sites WHERE status = 'active' ORDER BY id LIMIT 1",
    )
    .fetch_optional(&state.db.pool)
    .await?;
    Ok(Html(state.render("widgets.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "widgets", widgets, q => q.q, status_filter => q.status, notice => q.notice, site => site_uuid })?).into_response())
}

#[derive(Deserialize)]
pub struct NewForm {
    _csrf: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    template: String,
}

/// Creates a widget (blank or from a template) and opens the builder.
pub async fn create(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<NewForm>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let (definition, scheme, custom_css, name) = if f.template.is_empty() {
        (
            serde_json::to_string(&Definition::empty())?,
            "default".to_string(),
            String::new(),
            if f.name.trim().is_empty() {
                "New widget".to_string()
            } else {
                f.name.clone()
            },
        )
    } else if let Some(t) = templates::widget_template(&f.template) {
        (
            serde_json::to_string(&t.definition)?,
            t.scheme.clone(),
            String::new(),
            if f.name.trim().is_empty() {
                t.name.clone()
            } else {
                f.name.clone()
            },
        )
    } else if let Some(t) = state.widgets.user_template(&f.template).await? {
        (
            t.definition.clone(),
            "default".to_string(),
            t.custom_css.clone(),
            if f.name.trim().is_empty() {
                t.name.clone()
            } else {
                f.name.clone()
            },
        )
    } else {
        return Ok(
            Redirect::to(&state.url("/admin/templates?error=Unknown+template")).into_response(),
        );
    };
    let w = state
        .widgets
        .create(
            &name,
            &definition,
            (!f.template.is_empty()).then_some(f.template.as_str()),
            Some(admin.user.id),
        )
        .await?;
    if !custom_css.is_empty() || scheme != "default" {
        state
            .widgets
            .save(
                w.id,
                &w.name,
                &w.definition,
                &custom_css,
                "auto",
                &scheme,
                "draft",
            )
            .await?;
    }
    state
        .audit
        .record(
            Some(admin.user.id),
            "widget.created",
            "widget",
            Some(&w.uuid),
            None,
            None,
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/widgets/{}", w.uuid))).into_response())
}

pub async fn builder(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(w) = state.widgets.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let (media, _) = state
        .media
        .list(&mms_core::media::MediaQuery {
            per_page: 200,
            page: 1,
            ..Default::default()
        })
        .await?;
    let products = state.products.list_admin("", "", "published").await?;
    let schemes = all_schemes(&state).await?;
    let versions = state.widgets.versions(w.id).await?;
    let site_uuid: Option<String> = sqlx::query_scalar(
        "SELECT uuid FROM bridge_sites WHERE status = 'active' ORDER BY id LIMIT 1",
    )
    .fetch_optional(&state.db.pool)
    .await?;
    let props: Vec<_> = COMPONENT_KINDS
        .iter()
        .map(|(k, label)| {
            let fields: Vec<_> = render::component_props(k)
                .iter()
                .map(|(key, label, kind, default)| context! { key, label, kind, default })
                .collect();
            context! { kind => k, label, fields }
        })
        .collect();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("builder.html", context! {
        user => admin.user, csrf => admin.csrf, site_name, active => "widgets", w, media, products, schemes, versions, animations => ANIMATIONS, components => props,
        site => site_uuid.unwrap_or_default(), public_url => state.config.server.public_url,
    })?).into_response())
}

// ----- JSON API used by the builder -----

#[derive(Deserialize)]
pub struct SaveBody {
    name: String,
    definition: serde_json::Value,
    #[serde(default)]
    custom_css: String,
    #[serde(default = "auto")]
    theme: String,
    #[serde(default = "default_scheme")]
    scheme: String,
    #[serde(default = "draft")]
    status: String,
}

fn auto() -> String {
    "auto".into()
}
fn default_scheme() -> String {
    "default".into()
}
fn draft() -> String {
    "draft".into()
}

fn api_error(status: StatusCode, msg: String) -> Response {
    (
        status,
        Json(serde_json::json!({ "error": { "code": "invalid", "message": msg } })),
    )
        .into_response()
}

pub async fn api_save(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    headers: axum::http::HeaderMap,
    Json(body): Json<SaveBody>,
) -> AppResult<Response> {
    if headers.get("x-mms-csrf").and_then(|v| v.to_str().ok()) != Some(admin.csrf.as_str()) {
        return Ok(api_error(
            StatusCode::FORBIDDEN,
            "Invalid form token".into(),
        ));
    }
    let Some(w) = state.widgets.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let definition = body.definition.to_string();
    match state
        .widgets
        .save(
            w.id,
            &body.name,
            &definition,
            &body.custom_css,
            &body.theme,
            &body.scheme,
            &body.status,
        )
        .await
    {
        Ok(saved) => {
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "widget.saved",
                    "widget",
                    Some(&uuid),
                    None,
                    Some(serde_json::json!({ "version": saved.version })),
                )
                .await?;
            Ok(Json(
                serde_json::json!({ "data": { "version": saved.version, "status": saved.status } }),
            )
            .into_response())
        }
        Err(e) => Ok(api_error(StatusCode::BAD_REQUEST, e.to_string())),
    }
}

#[derive(Deserialize)]
pub struct PreviewBody {
    definition: serde_json::Value,
    #[serde(default)]
    custom_css: String,
    #[serde(default = "auto")]
    theme: String,
    #[serde(default = "default_scheme")]
    scheme: String,
}

/// Live preview: renders an unsaved definition through the real renderer.
pub async fn api_preview(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(uuid): Path<String>,
    Json(body): Json<PreviewBody>,
) -> AppResult<Response> {
    let site_uuid: String = sqlx::query_scalar(
        "SELECT uuid FROM bridge_sites WHERE status = 'active' ORDER BY id LIMIT 1",
    )
    .fetch_optional(&state.db.pool)
    .await?
    .unwrap_or_default();
    match render_widget(
        &state,
        &body.definition.to_string(),
        &body.custom_css,
        &body.theme,
        &body.scheme,
        &uuid,
        &site_uuid,
    )
    .await
    {
        Ok(r) => Ok(
            Json(serde_json::json!({ "data": { "html": r.html, "css": r.css } })).into_response(),
        ),
        Err(e) => Ok(api_error(StatusCode::BAD_REQUEST, e.to_string())),
    }
}

pub async fn api_versions(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(w) = state.widgets.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    Ok(Json(serde_json::json!({ "data": state.widgets.versions(w.id).await? })).into_response())
}

#[derive(Deserialize)]
pub struct VersionForm {
    _csrf: String,
    version: i64,
}

pub async fn restore(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<VersionForm>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(w) = state.widgets.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    state.widgets.restore(w.id, f.version).await?;
    Ok(Redirect::to(&state.url(&format!("/admin/widgets/{uuid}"))).into_response())
}

#[derive(Deserialize)]
pub struct CsrfOnly {
    _csrf: String,
}

pub async fn duplicate(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(w) = state.widgets.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let copy = state.widgets.duplicate(w.id).await?;
    Ok(Redirect::to(&state.url(&format!("/admin/widgets/{}", copy.uuid))).into_response())
}

pub async fn delete(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    if let Some(w) = state.widgets.by_uuid(&uuid).await? {
        state.widgets.delete(w.id).await?;
        state
            .audit
            .record(
                Some(admin.user.id),
                "widget.deleted",
                "widget",
                Some(&uuid),
                None,
                None,
            )
            .await?;
    }
    Ok(Redirect::to(&state.url("/admin/widgets?notice=Deleted.")).into_response())
}

#[derive(Deserialize)]
pub struct SaveTemplateForm {
    _csrf: String,
    name: String,
    #[serde(default)]
    category: String,
}

pub async fn save_as_template(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<SaveTemplateForm>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(w) = state.widgets.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    state
        .widgets
        .save_as_template(w.id, &f.name, &f.category)
        .await?;
    Ok(Redirect::to(&state.url("/admin/templates?notice=Template+saved.")).into_response())
}

// ----- exports -----

pub async fn export(
    State(state): State<AppState>,
    admin: AdminUser,
    Path((uuid, target)): Path<(String, String)>,
) -> AppResult<Response> {
    let Some(w) = state.widgets.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let _ = admin;
    let site_uuid: String = sqlx::query_scalar(
        "SELECT uuid FROM bridge_sites WHERE status = 'active' ORDER BY id LIMIT 1",
    )
    .fetch_optional(&state.db.pool)
    .await?
    .unwrap_or_default();
    let body = match target.as_str() {
        "wordpress" => format!("[mms_embed kind=\"widget\" id=\"{}\"]", w.uuid),
        "joomla" => format!("{{mms_embed kind=widget id={}}}", w.uuid),
        "html" => {
            let r = render_widget(
                &state,
                &w.definition,
                &w.custom_css,
                &w.theme,
                &w.scheme,
                &w.uuid,
                &site_uuid,
            )
            .await?;
            let public = state.config.server.public_url.trim_end_matches('/');
            // Absolute asset URLs so the file works anywhere.
            let html = r
                .html
                .replace(
                    &format!("src=\"{}/", state.base),
                    &format!("src=\"{public}/"),
                )
                .replace(
                    &format!("href=\"{}/", state.base),
                    &format!("href=\"{public}/"),
                )
                .replace(&format!("url('{}/", state.base), &format!("url('{public}/"));
            format!("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>{}</title>\n<link rel=\"stylesheet\" href=\"{public}/static/mms.css\">\n<style>\n{}\n</style>\n</head>\n<body class=\"embed\">\n{}\n<script src=\"{public}/static/mms-player.js\" defer></script>\n<script src=\"{public}/static/mms-widget.js\" defer></script>\n</body>\n</html>\n", esc(&w.name), r.css, html)
        }
        "json" => serde_json::to_string_pretty(
            &serde_json::json!({ "format": "mmstpl", "version": 1, "name": w.name, "definition": serde_json::from_str::<serde_json::Value>(&w.definition)?, "custom_css": w.custom_css, "scheme": w.scheme, "theme": w.theme }),
        )?,
        _ => return Ok(StatusCode::NOT_FOUND.into_response()),
    };
    let (ctype, filename) = match target.as_str() {
        "html" => (
            "text/html; charset=utf-8",
            format!("{}.html", mms_core::products::slugify(&w.name)),
        ),
        "json" => (
            "application/json; charset=utf-8",
            format!("{}.mmstpl.json", mms_core::products::slugify(&w.name)),
        ),
        _ => (
            "text/plain; charset=utf-8",
            format!("{}-{}.txt", mms_core::products::slugify(&w.name), target),
        ),
    };
    Ok((
        [
            (header::CONTENT_TYPE, ctype.to_string()),
            (
                header::CONTENT_DISPOSITION,
                format!("attachment; filename=\"{filename}\""),
            ),
        ],
        body,
    )
        .into_response())
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

// ----- storefront embed -----

#[derive(Deserialize)]
pub struct EmbedWidgetQuery {
    site: Option<String>,
    #[serde(default)]
    id: String,
    #[serde(default)]
    theme: String,
}

pub async fn embed(
    State(state): State<AppState>,
    MaybeUser(_user, _): MaybeUser,
    Path(uuid): Path<String>,
    Query(q): Query<EmbedWidgetQuery>,
) -> AppResult<Response> {
    embed_render(state, uuid, q).await
}

/// The loader's generic form: /embed/widget?site=&id=
pub async fn embed_by_query(
    State(state): State<AppState>,
    Query(q): Query<EmbedWidgetQuery>,
) -> AppResult<Response> {
    let id = q.id.clone();
    embed_render(state, id, q).await
}

async fn embed_render(state: AppState, uuid: String, q: EmbedWidgetQuery) -> AppResult<Response> {
    let Some(site_uuid) = q.site.as_deref() else {
        return Ok((StatusCode::BAD_REQUEST, "site parameter required").into_response());
    };
    let Some(site) = bridges::by_uuid(&state, site_uuid).await? else {
        return Ok((StatusCode::FORBIDDEN, "Unknown site").into_response());
    };
    let Some(w) = state.widgets.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if w.status != "published" {
        return Ok((StatusCode::NOT_FOUND, "This widget is not published").into_response());
    }
    let theme = if matches!(q.theme.as_str(), "light" | "dark") {
        q.theme.clone()
    } else {
        w.theme.clone()
    };
    let r = render_widget(
        &state,
        &w.definition,
        &w.custom_css,
        &theme,
        &w.scheme,
        &w.uuid,
        &site.uuid,
    )
    .await?;
    let site_name = state.settings.get("general.site_name").await?;
    let html = state.render("embed_widget.html", context! { name => w.name, html => minijinja::Value::from_safe_string(r.html), css => minijinja::Value::from_safe_string(r.css), site_name })?;
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
