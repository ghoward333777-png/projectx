//! Product admin: the ten types, categories.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use mms_core::media::MediaQuery;
use mms_core::products::{settings_fields, type_label, ProductDraft, TYPES};
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
pub struct ListQuery {
    #[serde(default)]
    q: String,
    #[serde(default, rename = "type")]
    r#type: String,
    #[serde(default)]
    status: String,
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
}

pub async fn list(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let items = state
        .products
        .list_admin(&q.q, &q.r#type, &q.status)
        .await?;
    let categories = state.products.categories().await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("products.html", context! {
        user => admin.user, csrf => admin.csrf, site_name, active => "products",
        items => items.iter().map(|p| context!{ p, type_label => type_label(&p.r#type) }).collect::<Vec<_>>(),
        categories, types => TYPES, q => q.q, type_filter => q.r#type, status_filter => q.status, notice => q.notice, error => q.error,
    })?).into_response())
}

#[derive(Deserialize)]
pub struct NewQuery {
    #[serde(default = "default_type", rename = "type")]
    r#type: String,
}

fn default_type() -> String {
    "video".into()
}

pub async fn new_form(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<NewQuery>,
) -> AppResult<Response> {
    render_form(&state, &admin, None, &q.r#type, "").await
}

async fn render_form(
    state: &AppState,
    admin: &AdminUser,
    product: Option<&mms_core::products::Product>,
    r#type: &str,
    error: &str,
) -> AppResult<Response> {
    let media_type = match r#type {
        "video" | "audio" | "image" | "pdf" => r#type.to_string(),
        _ => String::new(),
    };
    let (media, _) = state
        .media
        .list(&MediaQuery {
            r#type: media_type,
            per_page: 200,
            page: 1,
            ..Default::default()
        })
        .await?;
    let (images, _) = state
        .media
        .list(&MediaQuery {
            r#type: "image".into(),
            per_page: 200,
            page: 1,
            ..Default::default()
        })
        .await?;
    let categories = state.products.categories().await?;
    let selected: Vec<i64> = match product {
        Some(p) => state.products.category_ids(p.id).await?,
        None => vec![],
    };
    let settings = product
        .map(|p| p.settings_json())
        .unwrap_or_else(|| serde_json::json!({}));
    let fields: Vec<_> = settings_fields(r#type)
        .iter()
        .map(|(k, label, kind, help)| {
            let (kind, options) = match kind.strip_prefix("select:") {
                Some(o) => ("select", o.split(',').map(String::from).collect::<Vec<_>>()),
                None => (*kind, vec![]),
            };
            let value = settings
                .get(*k)
                .map(|v| match v {
                    serde_json::Value::String(s) => s.clone(),
                    other => other.to_string(),
                })
                .unwrap_or_default();
            context! { key => k, label, kind, help, options, value }
        })
        .collect();
    let currency = state.settings.get("store.currency").await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("product_form.html", context! {
        user => admin.user, csrf => admin.csrf, site_name, active => "products",
        product, ptype => r#type, type_label => type_label(r#type), types => TYPES, fields, media, images, categories, selected, currency, error,
        needs_media => matches!(r#type, "video" | "audio" | "image" | "pdf"),
    })?).into_response())
}

fn draft_from(f: &HashMap<String, String>, default_currency: &str) -> anyhow::Result<ProductDraft> {
    let g = |k: &str| f.get(k).cloned().unwrap_or_default();
    let r#type = g("type");
    let price: f64 = if g("price").trim().is_empty() {
        0.0
    } else {
        g("price")
            .trim()
            .parse()
            .map_err(|_| anyhow::anyhow!("price must be a number"))?
    };
    let mut settings = serde_json::Map::new();
    for (k, _, kind, _) in settings_fields(&r#type) {
        let raw = g(&format!("s_{k}"));
        let v = match *kind {
            "bool" => serde_json::Value::Bool(raw == "1"),
            "int" => serde_json::Value::from(raw.trim().parse::<i64>().unwrap_or(0)),
            _ => serde_json::Value::String(raw.trim().to_string()),
        };
        settings.insert((*k).to_string(), v);
    }
    let cats: Vec<i64> = f
        .iter()
        .filter(|(k, v)| k.starts_with("cat_") && v.as_str() == "1")
        .filter_map(|(k, _)| k[4..].parse().ok())
        .collect();
    let cur = g("currency");
    Ok(ProductDraft {
        r#type,
        title: g("title"),
        slug: g("slug"),
        description: g("description"),
        price_cents: (price * 100.0).round() as i64,
        currency: if cur.trim().is_empty() {
            default_currency.to_string()
        } else {
            cur.trim().to_string()
        },
        media_id: g("media_id").parse().ok(),
        preview_media_id: g("preview_media_id").parse().ok(),
        settings: serde_json::Value::Object(settings),
        featured: g("featured") == "1",
        status: if g("status").is_empty() {
            "draft".into()
        } else {
            g("status")
        },
        category_ids: cats,
    })
}

pub async fn create(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let currency = state.settings.get("store.currency").await?;
    let draft = match draft_from(&f, &currency) {
        Ok(d) => d,
        Err(e) => {
            return render_form(
                &state,
                &admin,
                None,
                f.get("type").map(String::as_str).unwrap_or("video"),
                &e.to_string(),
            )
            .await
        }
    };
    match state.products.create(&draft).await {
        Ok(p) => {
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "product.created",
                    "product",
                    Some(&p.uuid),
                    None,
                    None,
                )
                .await?;
            Ok(Redirect::to(&state.url(&format!(
                "/admin/products?notice=Created+{}",
                crate::routes::media::urlencoding(&p.title)
            )))
            .into_response())
        }
        Err(e) => render_form(&state, &admin, None, &draft.r#type, &e.to_string()).await,
    }
}

pub async fn edit_form(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(p) = state.products.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let t = p.r#type.clone();
    render_form(&state, &admin, Some(&p), &t, "").await
}

pub async fn update(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(p) = state.products.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let currency = state.settings.get("store.currency").await?;
    let draft = match draft_from(&f, &currency) {
        Ok(d) => d,
        Err(e) => return render_form(&state, &admin, Some(&p), &p.r#type, &e.to_string()).await,
    };
    match state.products.update(p.id, &draft).await {
        Ok(()) => {
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "product.updated",
                    "product",
                    Some(&uuid),
                    None,
                    None,
                )
                .await?;
            Ok(Redirect::to(&state.url("/admin/products?notice=Saved.")).into_response())
        }
        Err(e) => render_form(&state, &admin, Some(&p), &draft.r#type, &e.to_string()).await,
    }
}

#[derive(Deserialize)]
pub struct CsrfOnly {
    _csrf: String,
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
    if let Some(p) = state.products.by_uuid(&uuid).await? {
        state.products.delete(p.id).await?;
        state
            .audit
            .record(
                Some(admin.user.id),
                "product.deleted",
                "product",
                Some(&uuid),
                None,
                None,
            )
            .await?;
    }
    Ok(Redirect::to(&state.url("/admin/products?notice=Deleted.")).into_response())
}

#[derive(Deserialize)]
pub struct CategoryForm {
    _csrf: String,
    name: String,
}

pub async fn create_category(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<CategoryForm>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let target = match state.products.create_category(&f.name).await {
        Ok(_) => "/admin/products?notice=Category+added.".to_string(),
        Err(e) => format!(
            "/admin/products?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        ),
    };
    Ok(Redirect::to(&state.url(&target)).into_response())
}

pub async fn delete_category(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.products.delete_category(id).await?;
    Ok(Redirect::to(&state.url("/admin/products?notice=Category+removed.")).into_response())
}
