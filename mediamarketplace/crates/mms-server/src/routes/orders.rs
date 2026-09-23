//! Admin: orders, refunds, coupons, tax rates and site passes.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use crate::routes::customers::CsrfOnly;
use axum::extract::{Path, Query, State};
use axum::http::{header, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use mms_core::commerce::money;
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
pub struct ListQuery {
    #[serde(default)]
    q: String,
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
    let orders = state.commerce.orders(&q.q, &q.status, None).await?;
    let mut rows = Vec::new();
    for o in orders {
        let (email,): (String,) = sqlx::query_as("SELECT email FROM users WHERE id = ?")
            .bind(o.user_id)
            .fetch_one(&state.db.pool)
            .await?;
        rows.push(context! { total => money(o.total_cents, &o.currency), email, o });
    }
    let stats = state.commerce.stats().await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("orders.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "orders", rows, q => q.q, status => q.status, notice => q.notice, error => q.error, stats, revenue => money(stats["revenue_cents"].as_i64().unwrap_or(0), &state.settings.get("store.currency").await?) })?).into_response())
}

pub async fn detail(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let Some(o) = state.commerce.order_by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let items = state.commerce.items(o.id).await?;
    let payments = state.commerce.payments(o.id).await?;
    let receipt = state.commerce.receipt(o.id).await?.map(|(n, _, _)| n);
    let (email, name, cuuid): (String, String, String) =
        sqlx::query_as("SELECT email, name, uuid FROM users WHERE id = ?")
            .bind(o.user_id)
            .fetch_one(&state.db.pool)
            .await?;
    let subs = state
        .commerce
        .subscriptions_for(o.user_id)
        .await?
        .into_iter()
        .filter(|s| s.order_id == Some(o.id))
        .collect::<Vec<_>>();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("order_detail.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "orders", o, items => items.iter().map(|i| context!{ i, total => money(i.total_cents, &o.currency), unit => money(i.unit_cents, &o.currency) }).collect::<Vec<_>>(), payments, receipt, email, name, cuuid, subs,
        subtotal => money(o.subtotal_cents, &o.currency), discount => money(o.discount_cents, &o.currency), tax => money(o.tax_cents, &o.currency), total => money(o.total_cents, &o.currency), notice => q.notice, error => q.error })?).into_response())
}

pub async fn refund(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(o) = state.commerce.order_by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if o.status != "paid" {
        return Ok(Redirect::to(&state.url(&format!(
            "/admin/orders/{uuid}?error=Only+paid+orders+can+be+refunded"
        )))
        .into_response());
    }
    let reason = f.get("reason").cloned().unwrap_or_default();
    let mut external = None;
    if o.total_cents > 0 && o.gateway != "free" {
        match crate::routes::shop::gateway_named(&state, &o.gateway).await? {
            Some(gw) => match gw.refund(o.external_id.as_deref().unwrap_or(""), o.total_cents, &o.currency).await {
                Ok(id) => external = Some(id),
                Err(e) => return Ok(Redirect::to(&state.url(&format!("/admin/orders/{uuid}?error={}", crate::routes::media::urlencoding(&e.to_string())))).into_response()),
            },
            None => return Ok(Redirect::to(&state.url(&format!("/admin/orders/{uuid}?error=The+payment+method+used+for+this+order+is+no+longer+configured"))).into_response()),
        }
    }
    state
        .commerce
        .mark_refunded(&o, external.as_deref(), &reason)
        .await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "order.refunded",
            "order",
            Some(&o.uuid),
            None,
            Some(serde_json::json!({ "reason": reason })),
        )
        .await?;
    crate::routes::shop::emit(
        &state,
        "order.refunded",
        serde_json::json!({ "order": o.uuid, "number": o.number, "reason": reason }),
    )
    .await?;
    Ok(Redirect::to(&state.url(&format!(
        "/admin/orders/{uuid}?notice=Refunded+and+access+revoked."
    )))
    .into_response())
}

pub async fn receipt_pdf(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(o) = state.commerce.order_by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let Some((number, _, pdf)) = state.commerce.receipt(o.id).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    Ok((
        [
            (header::CONTENT_TYPE, "application/pdf".to_string()),
            (
                header::CONTENT_DISPOSITION,
                format!("inline; filename=\"{number}.pdf\""),
            ),
        ],
        pdf,
    )
        .into_response())
}

// ----- coupons and tax -----

pub async fn coupons(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let coupons = state.commerce.coupons().await?;
    let rates = state.commerce.tax_rates().await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("coupons.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "orders", coupons, rates, notice => q.notice, error => q.error })?).into_response())
}

pub async fn create_coupon(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let g = |k: &str| f.get(k).cloned().unwrap_or_default();
    let amount: i64 = if g("kind") == "fixed" {
        (g("amount").parse::<f64>().unwrap_or(0.0) * 100.0).round() as i64
    } else {
        g("amount").parse().unwrap_or(0)
    };
    let target = match state
        .commerce
        .create_coupon(
            &g("code"),
            &g("kind"),
            amount,
            g("max_uses").parse().unwrap_or(0),
            Some(&g("expires_at")),
        )
        .await
    {
        Ok(()) => "/admin/coupons?notice=Coupon+created.".to_string(),
        Err(e) => format!(
            "/admin/coupons?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        ),
    };
    Ok(Redirect::to(&state.url(&target)).into_response())
}

pub async fn coupon_status(
    State(state): State<AppState>,
    admin: AdminUser,
    Path((id, status)): Path<(i64, String)>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.commerce.set_coupon_status(id, &status).await?;
    Ok(Redirect::to(&state.url("/admin/coupons?notice=Coupon+updated.")).into_response())
}

pub async fn set_tax(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let g = |k: &str| f.get(k).cloned().unwrap_or_default();
    let rate_bp = (g("rate").parse::<f64>().unwrap_or(-1.0) * 100.0).round() as i64;
    let target = match state
        .commerce
        .set_tax_rate(&g("country"), &g("name"), rate_bp)
        .await
    {
        Ok(()) => "/admin/coupons?notice=Tax+rate+saved.".to_string(),
        Err(e) => format!(
            "/admin/coupons?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        ),
    };
    Ok(Redirect::to(&state.url(&target)).into_response())
}

pub async fn delete_tax(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.commerce.delete_tax_rate(id).await?;
    Ok(Redirect::to(&state.url("/admin/coupons?notice=Tax+rate+removed.")).into_response())
}

// ----- site passes -----

pub async fn passes(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let now = mms_core::now();
    let rows = sqlx::query_as::<_, (i64, i64, String, String, String, String, Option<String>, String, String)>(
        "SELECT e.id, u.id, u.uuid, u.email, u.name, e.scope, e.ends_at, e.status, e.source FROM entitlements e JOIN users u ON u.id = e.user_id WHERE e.scope IN ('site','category') ORDER BY e.status = 'active' DESC, e.ends_at IS NULL DESC, e.ends_at ASC LIMIT 500",
    ).fetch_all(&state.db.pool).await?;
    let holders: Vec<_> = rows
        .into_iter()
        .map(
            |(eid, _uid, cuuid, email, name, scope, ends_at, status, source)| {
                let expiring = ends_at
                    .as_deref()
                    .map(|e| e > now.as_str() && e < mms_core::commerce::add_days(&now, 7).as_str())
                    .unwrap_or(false);
                context! { eid, cuuid, email, name, scope, ends_at, status, source, expiring }
            },
        )
        .collect();
    let stats = state.commerce.stats().await?;
    let subs = sqlx::query_as::<_, (String, String, String, String, Option<String>, i64)>("SELECT s.uuid, u.email, p.title, s.status, s.period_end, s.cancel_at_period_end FROM subscriptions s JOIN users u ON u.id = s.user_id JOIN products p ON p.id = s.product_id ORDER BY s.id DESC LIMIT 200").fetch_all(&state.db.pool).await?;
    let currency = state.settings.get("store.currency").await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("passes.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "orders", holders, stats, mrr => money(stats["mrr_cents"].as_i64().unwrap_or(0), &currency),
        subs => subs.into_iter().map(|(uuid, email, title, status, period_end, cape)| context!{ uuid, email, title, status, period_end, cancel_at_period_end => cape == 1 }).collect::<Vec<_>>(), notice => q.notice, error => q.error })?).into_response())
}

pub async fn extend_pass(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let days: i64 = f.get("days").and_then(|d| d.parse().ok()).unwrap_or(30);
    let now = mms_core::now();
    let current: Option<Option<String>> =
        sqlx::query_scalar("SELECT ends_at FROM entitlements WHERE id = ?")
            .bind(id)
            .fetch_optional(&state.db.pool)
            .await?;
    let base = current
        .flatten()
        .filter(|e| e.as_str() > now.as_str())
        .unwrap_or(now.clone());
    let new_end = mms_core::commerce::add_days(&base, days);
    sqlx::query(
        "UPDATE entitlements SET ends_at = ?, status = 'active', updated_at = ? WHERE id = ?",
    )
    .bind(&new_end)
    .bind(&now)
    .bind(id)
    .execute(&state.db.pool)
    .await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "pass.extended",
            "entitlement",
            Some(&id.to_string()),
            None,
            Some(serde_json::json!({ "days": days, "ends_at": new_end })),
        )
        .await?;
    Ok(Redirect::to(&state.url("/admin/passes?notice=Pass+extended.")).into_response())
}
