//! Template gallery, site templates, brand kit and colour schemes.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use crate::routes::widgets::{all_schemes, render_widget};
use axum::extract::{Path, Query, State};
use axum::http::{header, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use mms_core::templates::{self, CATEGORIES};
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
pub struct GalleryQuery {
    #[serde(default)]
    category: String,
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
}

pub async fn gallery(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<GalleryQuery>,
) -> AppResult<Response> {
    let builtin: Vec<_> = templates::widget_templates().into_iter().filter(|t| q.category.is_empty() || t.category == q.category).map(|t| context! { slug => t.slug, name => t.name, category => t.category, description => t.description, builtin => true }).collect();
    let user: Vec<_> = state.widgets.user_templates().await?.into_iter().map(|t| context! { slug => t.slug, name => t.name, category => t.category, description => "Saved from a widget", builtin => false }).collect();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("templates.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "templates", builtin, user_templates => user, categories => CATEGORIES, category => q.category, notice => q.notice, error => q.error })?).into_response())
}

/// Live preview of a template with sample content at any width.
pub async fn preview(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(slug): Path<String>,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let (definition, css, scheme) = if let Some(t) = templates::widget_template(&slug) {
        (
            serde_json::to_string(&t.definition)?,
            String::new(),
            t.scheme,
        )
    } else if let Some(t) = state.widgets.user_template(&slug).await? {
        (t.definition, t.custom_css, "default".to_string())
    } else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let theme = q.get("theme").cloned().unwrap_or_else(|| "auto".into());
    let scheme = q
        .get("scheme")
        .cloned()
        .filter(|s| !s.is_empty())
        .unwrap_or(scheme);
    let r = render_widget(
        &state,
        &definition,
        &css,
        &theme,
        &scheme,
        "preview",
        "preview",
    )
    .await?;
    let html = state.render("embed_widget.html", context! { name => slug, html => minijinja::Value::from_safe_string(r.html), css => minijinja::Value::from_safe_string(r.css), site_name => "Preview" })?;
    Ok((
        [(
            header::CONTENT_SECURITY_POLICY,
            "frame-ancestors 'self'".to_string(),
        )],
        Html(html),
    )
        .into_response())
}

#[derive(Deserialize)]
pub struct CsrfOnly {
    _csrf: String,
}

pub async fn delete_user_template(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(slug): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.widgets.delete_user_template(&slug).await?;
    Ok(Redirect::to(&state.url("/admin/templates?notice=Template+removed.")).into_response())
}

pub async fn export_template(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(slug): Path<String>,
) -> AppResult<Response> {
    let body = if let Some(t) = templates::widget_template(&slug) {
        serde_json::json!({ "format": "mmstpl", "version": 1, "name": t.name, "category": t.category, "definition": t.definition, "custom_css": "", "scheme": t.scheme })
    } else if let Some(t) = state.widgets.user_template(&slug).await? {
        serde_json::json!({ "format": "mmstpl", "version": 1, "name": t.name, "category": t.category, "definition": serde_json::from_str::<serde_json::Value>(&t.definition)?, "custom_css": t.custom_css, "scheme": "default" })
    } else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    Ok((
        [
            (
                header::CONTENT_TYPE,
                "application/json; charset=utf-8".to_string(),
            ),
            (
                header::CONTENT_DISPOSITION,
                format!("attachment; filename=\"{slug}.mmstpl.json\""),
            ),
        ],
        serde_json::to_string_pretty(&body)?,
    )
        .into_response())
}

/// Imports a .mmstpl.json pasted or uploaded as text.
pub async fn import_template(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let raw = f.get("json").cloned().unwrap_or_default();
    let v: serde_json::Value = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            return Ok(Redirect::to(&state.url(&format!(
                "/admin/templates?error={}",
                crate::routes::media::urlencoding(&format!("Not valid JSON: {e}"))
            )))
            .into_response())
        }
    };
    if v.get("format").and_then(|f| f.as_str()) != Some("mmstpl") {
        return Ok(Redirect::to(
            &state.url("/admin/templates?error=Not+a+MediaMarketplace+template+file"),
        )
        .into_response());
    }
    let name = v
        .get("name")
        .and_then(|n| n.as_str())
        .unwrap_or("Imported template");
    let category = v
        .get("category")
        .and_then(|n| n.as_str())
        .unwrap_or("custom");
    let definition = v
        .get("definition")
        .map(|d| d.to_string())
        .unwrap_or_default();
    let css = v.get("custom_css").and_then(|c| c.as_str()).unwrap_or("");
    match state
        .widgets
        .import_template(name, name, category, &definition, css)
        .await
    {
        Ok(_) => Ok(
            Redirect::to(&state.url("/admin/templates?notice=Template+imported.")).into_response(),
        ),
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/templates?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

// ----- site templates -----

pub async fn sites(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<GalleryQuery>,
) -> AppResult<Response> {
    let sites: Vec<_> = templates::site_templates().into_iter().map(|s| context! { slug => s.slug, name => s.name, industry => s.industry, description => s.description, scheme => s.scheme, pages => s.pages.iter().map(|(p, w)| context!{ name => p, widgets => w }).collect::<Vec<_>>() }).collect();
    let applications: Vec<(i64, String, String, i64)> = sqlx::query_as("SELECT id, template, applied_at, rolled_back FROM site_applications ORDER BY id DESC LIMIT 20").fetch_all(&state.db.pool).await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("site_templates.html", context! {
        user => admin.user, csrf => admin.csrf, site_name, active => "templates", sites, notice => q.notice, error => q.error,
        applications => applications.iter().map(|(id, t, at, rb)| context!{ id, template => t, applied_at => at, rolled_back => rb }).collect::<Vec<_>>(),
    })?).into_response())
}

/// Applies a site template: creates published widgets per page, sets the scheme,
/// records the application. Returns how many widgets were created.
pub async fn apply_site_template(
    state: &AppState,
    slug: &str,
    admin_id: i64,
) -> anyhow::Result<usize> {
    let Some(site) = templates::site_template(slug) else {
        anyhow::bail!("unknown site template {slug}");
    };
    let mut created = Vec::new();
    for (page, widgets) in &site.pages {
        for (i, wt) in widgets.iter().enumerate() {
            let Some(t) = templates::widget_template(wt) else {
                continue;
            };
            let name = format!("{page} · {} ({})", t.name, i + 1);
            let w = state
                .widgets
                .create(
                    &name,
                    &serde_json::to_string(&t.definition)?,
                    Some(&t.slug),
                    Some(admin_id),
                )
                .await?;
            state
                .widgets
                .save(
                    w.id,
                    &name,
                    &w.definition,
                    "",
                    "auto",
                    &site.scheme,
                    "published",
                )
                .await?;
            created.push(w.id);
        }
    }
    state
        .settings
        .set("general.scheme", &site.scheme)
        .await
        .ok();
    sqlx::query("INSERT INTO site_applications (template, widget_ids, scheme_slug, applied_at) VALUES (?, ?, ?, ?)")
        .bind(slug).bind(serde_json::to_string(&created)?).bind(&site.scheme).bind(mms_core::now())
        .execute(&state.db.pool).await?;
    state
        .audit
        .record(
            Some(admin_id),
            "site_template.applied",
            "site_template",
            Some(slug),
            None,
            Some(serde_json::json!({ "widgets": created.len() })),
        )
        .await?;
    Ok(created.len())
}

pub async fn apply_site(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(slug): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(site) = templates::site_template(&slug) else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let n = apply_site_template(&state, &slug, admin.user.id).await?;
    Ok(Redirect::to(&state.url(&format!("/admin/site-templates?notice={}", crate::routes::media::urlencoding(&format!("{} applied: {} widgets created and published. Place them with the snippets under Widgets.", site.name, n))))).into_response())
}

pub async fn rollback_site(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let row: Option<(String, i64)> =
        sqlx::query_as("SELECT widget_ids, rolled_back FROM site_applications WHERE id = ?")
            .bind(id)
            .fetch_optional(&state.db.pool)
            .await?;
    if let Some((ids, 0)) = row {
        let ids: Vec<i64> = serde_json::from_str(&ids).unwrap_or_default();
        for wid in ids {
            state.widgets.delete(wid).await?;
        }
        sqlx::query("UPDATE site_applications SET rolled_back = 1 WHERE id = ?")
            .bind(id)
            .execute(&state.db.pool)
            .await?;
        state
            .audit
            .record(
                Some(admin.user.id),
                "site_template.rolled_back",
                "site_application",
                Some(&id.to_string()),
                None,
                None,
            )
            .await?;
    }
    Ok(Redirect::to(&state.url("/admin/site-templates?notice=Rolled+back.")).into_response())
}

pub async fn export_site(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(slug): Path<String>,
) -> AppResult<Response> {
    let Some(site) = templates::site_template(&slug) else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let widgets: Vec<_> = site.pages.iter().flat_map(|(_, w)| w.iter()).filter_map(|w| templates::widget_template(w)).map(|t| serde_json::json!({ "slug": t.slug, "name": t.name, "category": t.category, "definition": t.definition })).collect();
    let scheme = templates::builtin_schemes()
        .into_iter()
        .find(|s| s.slug == site.scheme);
    let body = serde_json::json!({ "format": "mmssite", "version": 1, "name": site.name, "industry": site.industry, "scheme": scheme.map(|s| serde_json::json!({ "slug": s.slug, "name": s.name, "vars": s.vars })), "pages": site.pages.iter().map(|(p, w)| serde_json::json!({ "name": p, "widgets": w })).collect::<Vec<_>>(), "widget_templates": widgets });
    let _ = state;
    Ok((
        [
            (
                header::CONTENT_TYPE,
                "application/json; charset=utf-8".to_string(),
            ),
            (
                header::CONTENT_DISPOSITION,
                format!("attachment; filename=\"{slug}.mmssite.json\""),
            ),
        ],
        serde_json::to_string_pretty(&body)?,
    )
        .into_response())
}

/// Imports a .mmssite.json: its widget templates become user templates and its scheme a custom scheme.
pub async fn import_site(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let v: serde_json::Value =
        match serde_json::from_str(f.get("json").map(String::as_str).unwrap_or("")) {
            Ok(v) => v,
            Err(_) => {
                return Ok(
                    Redirect::to(&state.url("/admin/site-templates?error=Not+valid+JSON"))
                        .into_response(),
                )
            }
        };
    if v.get("format").and_then(|f| f.as_str()) != Some("mmssite") {
        return Ok(Redirect::to(
            &state.url("/admin/site-templates?error=Not+a+site+template+file"),
        )
        .into_response());
    }
    let mut n = 0;
    for t in v
        .get("widget_templates")
        .and_then(|w| w.as_array())
        .cloned()
        .unwrap_or_default()
    {
        let slug = t.get("slug").and_then(|s| s.as_str()).unwrap_or("imported");
        let name = t.get("name").and_then(|s| s.as_str()).unwrap_or(slug);
        let cat = t
            .get("category")
            .and_then(|s| s.as_str())
            .unwrap_or("custom");
        if let Some(def) = t.get("definition") {
            if state
                .widgets
                .import_template(slug, name, cat, &def.to_string(), "")
                .await
                .is_ok()
            {
                n += 1;
            }
        }
    }
    if let Some(s) = v.get("scheme") {
        if let (Some(slug), Some(name), Some(vars)) = (
            s.get("slug").and_then(|x| x.as_str()),
            s.get("name").and_then(|x| x.as_str()),
            s.get("vars"),
        ) {
            let slug = format!("user-{}", mms_core::products::slugify(slug));
            sqlx::query("INSERT INTO colour_schemes (slug, name, vars, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(slug) DO UPDATE SET name = excluded.name, vars = excluded.vars")
                .bind(&slug).bind(name).bind(vars.to_string()).bind(mms_core::now()).execute(&state.db.pool).await?;
        }
    }
    let _ = admin;
    Ok(Redirect::to(&state.url(&format!(
        "/admin/site-templates?notice={}+widget+templates+imported+under+Templates.",
        n
    )))
    .into_response())
}

// ----- colour schemes and brand kit -----

pub async fn schemes(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<GalleryQuery>,
) -> AppResult<Response> {
    let all = all_schemes(&state).await?;
    let rows: Vec<_> = all.iter().map(|s| {
        let get = |k: &str| s.vars.iter().find(|(n, _)| n == k).map(|(_, v)| v.clone()).unwrap_or_default();
        let text_on_bg = templates::contrast_ratio(&get("text"), &get("bg")).unwrap_or(0.0);
        let white_on_accent = templates::contrast_ratio("#ffffff", &get("accent")).unwrap_or(0.0);
        context! { slug => s.slug, name => s.name, builtin => s.builtin, vars => s.vars, accent => get("accent"), accent2 => get("accent-2"), bg => get("bg"), surface => get("surface"), text => get("text"),
                   text_contrast => format!("{text_on_bg:.1}"), text_ok => text_on_bg >= 4.5, accent_contrast => format!("{white_on_accent:.1}"), accent_ok => white_on_accent >= 4.5 }
    }).collect();
    let brand = brand_kit(&state).await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("schemes.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "templates", schemes => rows, brand, notice => q.notice, error => q.error, current => state.settings.get("general.scheme").await? })?).into_response())
}

pub async fn brand_kit(state: &AppState) -> anyhow::Result<serde_json::Value> {
    let raw = state.settings.get("brand.kit").await?;
    Ok(serde_json::from_str(&raw).unwrap_or_else(|_| serde_json::json!({ "logo": "", "font": "system-ui, sans-serif", "radius": 10, "shadow": "soft" })))
}

pub async fn create_scheme(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let g = |k: &str| f.get(k).cloned().unwrap_or_default();
    let name = g("name");
    if name.trim().is_empty() {
        return Ok(
            Redirect::to(&state.url("/admin/schemes?error=A+name+is+required")).into_response(),
        );
    }
    let vars: Vec<(String, String)> = ["accent", "accent-2", "bg", "surface", "text", "muted"]
        .iter()
        .map(|k| ((*k).to_string(), g(k).trim().to_string()))
        .collect();
    if vars.iter().any(|(_, v)| {
        !(v.starts_with('#')
            && (v.len() == 7 || v.len() == 4)
            && v[1..].chars().all(|c| c.is_ascii_hexdigit()))
    }) {
        return Ok(Redirect::to(
            &state.url("/admin/schemes?error=Colours+must+be+hex+values+like+%23336699"),
        )
        .into_response());
    }
    let slug = format!("user-{}", mms_core::products::slugify(&name));
    sqlx::query("INSERT INTO colour_schemes (slug, name, vars, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(slug) DO UPDATE SET name = excluded.name, vars = excluded.vars")
        .bind(&slug).bind(name.trim()).bind(serde_json::to_string(&vars)?).bind(mms_core::now()).execute(&state.db.pool).await?;
    Ok(Redirect::to(&state.url("/admin/schemes?notice=Scheme+saved.")).into_response())
}

pub async fn delete_scheme(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(slug): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    sqlx::query("DELETE FROM colour_schemes WHERE slug = ?")
        .bind(&slug)
        .execute(&state.db.pool)
        .await?;
    Ok(Redirect::to(&state.url("/admin/schemes?notice=Scheme+removed.")).into_response())
}

pub async fn save_brand(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let g = |k: &str| f.get(k).cloned().unwrap_or_default();
    let kit = serde_json::json!({ "logo": g("logo"), "font": g("font").chars().take(120).collect::<String>(), "radius": g("radius").parse::<i64>().unwrap_or(10).clamp(0, 40), "shadow": if matches!(g("shadow").as_str(), "none" | "soft" | "strong") { g("shadow") } else { "soft".into() } });
    state.settings.set("brand.kit", &kit.to_string()).await?;
    if !g("scheme").is_empty() {
        state.settings.set("general.scheme", &g("scheme")).await?;
    }
    Ok(Redirect::to(&state.url("/admin/schemes?notice=Branding+saved.")).into_response())
}
