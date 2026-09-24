//! Customers and manual access grants.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use mms_core::entitlements::Grant;
use mms_core::users::User;
use serde::Deserialize;

#[derive(Deserialize)]
pub struct ListQuery {
    #[serde(default)]
    q: String,
}

pub async fn list(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let like = format!("%{}%", q.q.trim());
    let users = sqlx::query_as::<_, User>("SELECT id, uuid, email, name, role, status, password_hash, agent FROM users WHERE (? = '' OR email LIKE ? OR name LIKE ?) ORDER BY id DESC LIMIT 500")
        .bind(q.q.trim()).bind(&like).bind(&like).fetch_all(&state.db.pool).await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("customers.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "customers", users, q => q.q })?).into_response())
}

pub async fn detail(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(c) = sqlx::query_as::<_, User>(
        "SELECT id, uuid, email, name, role, status, password_hash, agent FROM users WHERE uuid = ?",
    )
    .bind(&uuid)
    .fetch_optional(&state.db.pool)
    .await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let grants = state.entitlements.for_user(c.id).await?;
    let mut rows = Vec::new();
    for g in grants {
        let title = match g.product_id {
            Some(pid) => state
                .products
                .by_id(pid)
                .await?
                .map(|p| p.title)
                .unwrap_or_else(|| "(deleted product)".into()),
            None => format!("{} access", g.scope),
        };
        rows.push(context! { g, title });
    }
    let products = state.products.list_admin("", "", "published").await?;
    let identities = sqlx::query_as::<_, (String, String)>(
        "SELECT host, external_id FROM user_identities WHERE user_id = ?",
    )
    .bind(c.id)
    .fetch_all(&state.db.pool)
    .await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("customer_detail.html", context! {
        user => admin.user, csrf => admin.csrf, site_name, active => "customers", c, grants => rows, products,
        identities => identities.iter().map(|(h, e)| context!{ host => h, external_id => e }).collect::<Vec<_>>(),
    })?).into_response())
}

#[derive(Deserialize)]
pub struct GrantForm {
    _csrf: String,
    #[serde(default)]
    product_id: String,
    #[serde(default)]
    scope: String,
    #[serde(default)]
    days: String,
}

pub async fn grant(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<GrantForm>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(c) = sqlx::query_as::<_, User>(
        "SELECT id, uuid, email, name, role, status, password_hash, agent FROM users WHERE uuid = ?",
    )
    .bind(&uuid)
    .fetch_optional(&state.db.pool)
    .await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let now = chrono::Utc::now();
    let ends = f
        .days
        .trim()
        .parse::<i64>()
        .ok()
        .filter(|d| *d > 0)
        .map(|d| {
            (now + chrono::Duration::days(d))
                .format("%Y-%m-%dT%H:%M:%SZ")
                .to_string()
        });
    let starts = now.format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let source_ref = format!("{}:{}", admin.user.id, now.timestamp());
    if f.scope == "site" {
        state
            .entitlements
            .grant(Grant {
                user_id: c.id,
                product_id: None,
                scope: "site",
                scope_ref: "",
                source: "manual",
                source_ref: &source_ref,
                starts_at: &starts,
                ends_at: ends.as_deref(),
            })
            .await?;
    } else if let Ok(pid) = f.product_id.parse::<i64>() {
        state
            .entitlements
            .grant(Grant {
                user_id: c.id,
                product_id: Some(pid),
                scope: "product",
                scope_ref: "",
                source: "manual",
                source_ref: &source_ref,
                starts_at: &starts,
                ends_at: ends.as_deref(),
            })
            .await?;
    }
    state
        .audit
        .record(
            Some(admin.user.id),
            "entitlement.granted",
            "user",
            Some(&c.uuid),
            None,
            Some(serde_json::json!({ "scope": f.scope, "product": f.product_id })),
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/customers/{uuid}"))).into_response())
}

#[derive(Deserialize)]
pub struct CsrfOnly {
    pub _csrf: String,
}

pub async fn revoke(
    State(state): State<AppState>,
    admin: AdminUser,
    Path((uuid, id)): Path<(String, i64)>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    sqlx::query("UPDATE entitlements SET status = 'revoked', updated_at = ? WHERE id = ?")
        .bind(mms_core::now())
        .bind(id)
        .execute(&state.db.pool)
        .await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "entitlement.revoked",
            "entitlement",
            Some(&id.to_string()),
            None,
            None,
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/customers/{uuid}"))).into_response())
}
