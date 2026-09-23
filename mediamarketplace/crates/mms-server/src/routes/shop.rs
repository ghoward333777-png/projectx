//! Storefront commerce: cart, checkout, gateway hand-off and return, test gateway.

use crate::app::AppState;
use crate::auth::{self, MaybeUser};
use crate::errors::AppResult;
use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use axum_extra::extract::cookie::{Cookie, SameSite};
use axum_extra::extract::CookieJar;
use minijinja::context;
use mms_core::commerce::{is_recurring, money, recurring_interval, Cart, Order};
use mms_core::gateways::{Gateway, OrderFacts, Outcome, PayPal, Stripe, TestGateway};
use mms_core::users::User;
use serde::Deserialize;
use std::collections::HashMap;

pub const CART_COOKIE: &str = "mms_cart";

/// The visitor's cart, creating the cookie when needed.
pub async fn current_cart(
    state: &AppState,
    jar: CookieJar,
    user: Option<&User>,
) -> AppResult<(Cart, CookieJar)> {
    let (token, jar) = match jar.get(CART_COOKIE).map(|c| c.value().to_string()) {
        Some(t) if t.len() >= 16 => (t, jar),
        _ => {
            let t = uuid::Uuid::new_v4().to_string();
            let mut c = Cookie::new(CART_COOKIE, t.clone());
            c.set_path(auth::cookie_path(state));
            c.set_http_only(true);
            c.set_same_site(SameSite::Lax);
            c.set_secure(state.config.server.public_url.starts_with("https://"));
            c.set_max_age(time::Duration::days(30));
            (t, jar.add(c))
        }
    };
    let cart = state.commerce.cart(&token, user.map(|u| u.id)).await?;
    Ok((cart, jar))
}

pub fn client_ip(headers: &HeaderMap) -> String {
    headers
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.split(',').next())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "local".into())
}

pub fn user_agent(headers: &HeaderMap) -> String {
    headers
        .get(header::USER_AGENT)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .chars()
        .take(200)
        .collect()
}

/// Customers get a CSRF token bound to their session, like administrators.
fn customer_csrf(state: &AppState, token: &Option<String>) -> String {
    token
        .as_deref()
        .map(|t| auth::csrf_token(state, t))
        .unwrap_or_default()
}

// ----- gateways from settings -----

pub async fn gateways(state: &AppState) -> anyhow::Result<Vec<Box<dyn Gateway>>> {
    let mut out: Vec<Box<dyn Gateway>> = Vec::new();
    let stripe_key = state.settings.get("payments.stripe_secret_key").await?;
    if !stripe_key.trim().is_empty() {
        out.push(Box::new(Stripe::new(
            stripe_key.trim(),
            state
                .settings
                .get("payments.stripe_webhook_secret")
                .await?
                .trim(),
        )));
    }
    let pp_id = state.settings.get("payments.paypal_client_id").await?;
    let pp_secret = state.settings.get("payments.paypal_secret").await?;
    if !pp_id.trim().is_empty() && !pp_secret.trim().is_empty() {
        out.push(Box::new(PayPal::new(
            pp_id.trim(),
            pp_secret.trim(),
            state
                .settings
                .get("payments.paypal_webhook_id")
                .await?
                .trim(),
            state.settings.get("payments.paypal_sandbox").await? == "1",
        )));
    }
    if state.settings.get("payments.test_mode").await? == "1" {
        out.push(Box::new(TestGateway {
            base_url: state
                .config
                .server
                .public_url
                .trim_end_matches('/')
                .to_string(),
        }));
    }
    Ok(out)
}

pub async fn gateway_named(
    state: &AppState,
    name: &str,
) -> anyhow::Result<Option<Box<dyn Gateway>>> {
    Ok(gateways(state)
        .await?
        .into_iter()
        .find(|g| g.name() == name))
}

async fn facts(state: &AppState, order: &Order, user: &User) -> AppResult<OrderFacts> {
    let items = state.commerce.items(order.id).await?;
    let mut recurring = None;
    for it in &items {
        if let Some(pid) = it.product_id {
            if let Some(p) = state.products.by_id(pid).await? {
                if is_recurring(&p) {
                    recurring = Some((recurring_interval(&p), p.title.clone()));
                }
            }
        }
    }
    let public = state.config.server.public_url.trim_end_matches('/');
    Ok(OrderFacts {
        uuid: order.uuid.clone(),
        number: order.number.clone(),
        currency: order.currency.clone(),
        total_cents: order.total_cents,
        customer_email: user.email.clone(),
        lines: items
            .iter()
            .map(|i| (i.title.clone(), i.unit_cents, i.quantity))
            .collect(),
        recurring,
        success_url: format!("{public}/checkout/return/GATEWAY?order={}", order.uuid),
        cancel_url: format!("{public}/checkout/cancel/{}", order.uuid),
    })
}

/// Everything that happens once money has arrived. Idempotent.
pub async fn complete_paid(
    state: &AppState,
    order: &Order,
    gateway: &str,
    external_id: Option<&str>,
    subscription_id: Option<&str>,
    period_end: Option<&str>,
) -> AppResult<bool> {
    let prefix = state.settings.get("store.receipt_prefix").await?;
    let site_name = state.settings.get("general.site_name").await?;
    let footer = state.settings.get("store.receipt_footer").await?;
    let first = state
        .commerce
        .mark_paid(order, gateway, external_id, &prefix, &site_name, &footer)
        .await?;
    if !first {
        return Ok(false);
    }
    if let Some(sub) = subscription_id {
        for it in state.commerce.items(order.id).await? {
            if let Some(pid) = it.product_id {
                if let Some(p) = state.products.by_id(pid).await? {
                    if is_recurring(&p) {
                        state
                            .commerce
                            .create_subscription(
                                order.user_id,
                                p.id,
                                Some(order.id),
                                gateway,
                                Some(sub),
                                &recurring_interval(&p),
                                period_end,
                            )
                            .await?;
                    }
                }
            }
        }
    }
    state
        .audit
        .record(Some(order.user_id), "order.paid", "order", Some(&order.uuid), None, Some(serde_json::json!({ "number": order.number, "total_cents": order.total_cents, "gateway": gateway })))
        .await?;
    emit(state, "order.paid", serde_json::json!({ "order": order.uuid, "number": order.number, "total_cents": order.total_cents, "currency": order.currency, "user_id": order.user_id, "gateway": gateway })).await?;
    for e in state.entitlements.for_user(order.user_id).await? {
        if e.source == "order" && e.source_ref == order.uuid {
            emit(state, "entitlement.granted", serde_json::json!({ "user_id": e.user_id, "scope": e.scope, "scope_ref": e.scope_ref, "product_id": e.product_id, "ends_at": e.ends_at })).await?;
        }
    }
    Ok(true)
}

/// Queues outbound webhooks and the jobs that deliver them.
pub async fn emit(state: &AppState, event: &str, payload: serde_json::Value) -> AppResult<()> {
    for id in state.integrations.emit(event, payload).await? {
        state
            .jobs
            .enqueue("webhook.deliver", serde_json::json!({ "delivery": id }))
            .await?;
    }
    Ok(())
}

// ----- cart -----

#[derive(Deserialize)]
pub struct CartQuery {
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
}

pub async fn cart_page(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    jar: CookieJar,
    Query(q): Query<CartQuery>,
) -> AppResult<Response> {
    let (cart, jar) = current_cart(&state, jar, user.as_ref()).await?;
    let lines = state.commerce.lines(&cart).await?;
    let totals = state.commerce.cart_totals(&cart, &lines).await?;
    let currency = state.settings.get("store.currency").await?;
    let site_name = state.settings.get("general.site_name").await?;
    let html = state.render("cart.html", context! { user, site_name, cart, lines, totals, currency, notice => q.notice, error => q.error, csrf => customer_csrf(&state, &token), public_url => state.config.server.public_url })?;
    Ok((jar, Html(html)).into_response())
}

#[derive(Deserialize)]
pub struct AddForm {
    product: String,
    #[serde(default = "one")]
    quantity: i64,
    #[serde(default)]
    site: String,
}
fn one() -> i64 {
    1
}

pub async fn cart_add(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Form(f): Form<AddForm>,
) -> AppResult<Response> {
    let (cart, jar) = current_cart(&state, jar, user.as_ref()).await?;
    let Some(p) = state.products.by_slug(&f.product).await? else {
        return Ok((
            jar,
            Redirect::to(&state.url("/cart?error=That+product+does+not+exist")),
        )
            .into_response());
    };
    if let Err(e) = state.commerce.add(&cart, &p, f.quantity).await {
        return Ok((
            jar,
            Redirect::to(&state.url(&format!(
                "/cart?error={}",
                crate::routes::media::urlencoding(&e.to_string())
            ))),
        )
            .into_response());
    }
    let target = if f.site.is_empty() {
        state.url("/cart")
    } else {
        state.url(&format!(
            "/embed/checkout?site={}",
            crate::routes::media::urlencoding(&f.site)
        ))
    };
    Ok((jar, Redirect::to(&target)).into_response())
}

#[derive(Deserialize)]
pub struct LineForm {
    product_id: i64,
    #[serde(default)]
    quantity: i64,
}

pub async fn cart_update(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Form(f): Form<LineForm>,
) -> AppResult<Response> {
    let (cart, jar) = current_cart(&state, jar, user.as_ref()).await?;
    state
        .commerce
        .set_quantity(&cart, f.product_id, f.quantity)
        .await?;
    Ok((jar, Redirect::to(&state.url("/cart"))).into_response())
}

pub async fn cart_remove(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Form(f): Form<LineForm>,
) -> AppResult<Response> {
    let (cart, jar) = current_cart(&state, jar, user.as_ref()).await?;
    state.commerce.remove(&cart, f.product_id).await?;
    Ok((jar, Redirect::to(&state.url("/cart"))).into_response())
}

pub async fn cart_coupon(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    let (cart, jar) = current_cart(&state, jar, user.as_ref()).await?;
    let code = f.get("code").cloned().unwrap_or_default();
    let back = f
        .get("return")
        .cloned()
        .filter(|r| r == "/checkout")
        .unwrap_or_else(|| "/cart".into());
    let target = match state.commerce.set_coupon(&cart, &code).await {
        Ok(Some(_)) => format!("{back}?notice=Coupon+applied."),
        Ok(None) => format!("{back}?notice=Coupon+removed."),
        Err(e) => format!(
            "{back}?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        ),
    };
    Ok((jar, Redirect::to(&state.url(&target))).into_response())
}

pub async fn cart_country(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    let (cart, jar) = current_cart(&state, jar, user.as_ref()).await?;
    state
        .commerce
        .set_country(&cart, f.get("country").map(String::as_str).unwrap_or(""))
        .await?;
    let back = f
        .get("return")
        .cloned()
        .filter(|r| r == "/checkout")
        .unwrap_or_else(|| "/cart".into());
    Ok((jar, Redirect::to(&state.url(&back))).into_response())
}

// ----- checkout -----

pub async fn checkout_page(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    jar: CookieJar,
    Query(q): Query<CartQuery>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Fcheckout")).into_response());
    };
    let (cart, jar) = current_cart(&state, jar, Some(&user)).await?;
    let lines = state.commerce.lines(&cart).await?;
    if lines.is_empty() {
        return Ok((
            jar,
            Redirect::to(&state.url("/cart?notice=Your+cart+is+empty.")),
        )
            .into_response());
    }
    let totals = state.commerce.cart_totals(&cart, &lines).await?;
    let gws: Vec<_> = gateways(&state)
        .await?
        .iter()
        .map(|g| context! { name => g.name(), label => g.label() })
        .collect();
    let has_recurring = lines.iter().any(|l| is_recurring(&l.product));
    let currency = state.settings.get("store.currency").await?;
    let site_name = state.settings.get("general.site_name").await?;
    let html = state.render("checkout.html", context! { user, site_name, cart, lines, totals, currency, gateways => gws, has_recurring, notice => q.notice, error => q.error, csrf => customer_csrf(&state, &token) })?;
    Ok((jar, Html(html)).into_response())
}

#[derive(Deserialize)]
pub struct StartForm {
    _csrf: String,
    #[serde(default)]
    gateway: String,
}

pub async fn checkout_start(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    jar: CookieJar,
    Form(f): Form<StartForm>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Fcheckout")).into_response());
    };
    if f._csrf != customer_csrf(&state, &token) {
        return Ok((StatusCode::FORBIDDEN, "Invalid form token").into_response());
    }
    let (cart, jar) = current_cart(&state, jar, Some(&user)).await?;
    let currency = state.settings.get("store.currency").await?;
    let order = match state.commerce.create_order(&cart, user.id, &currency).await {
        Ok(o) => o,
        Err(e) => {
            return Ok((
                jar,
                Redirect::to(&state.url(&format!(
                    "/cart?error={}",
                    crate::routes::media::urlencoding(&e.to_string())
                ))),
            )
                .into_response())
        }
    };
    if order.total_cents == 0 {
        complete_paid(&state, &order, "free", None, None, None).await?;
        return Ok((
            jar,
            Redirect::to(&state.url(&format!("/checkout/done/{}", order.uuid))),
        )
            .into_response());
    }
    let Some(gw) = gateway_named(&state, &f.gateway).await? else {
        state.commerce.cancel(order.id).await?;
        return Ok((
            jar,
            Redirect::to(&state.url("/checkout?error=Choose+a+payment+method")),
        )
            .into_response());
    };
    let mut facts = facts(&state, &order, &user).await?;
    facts.success_url = facts.success_url.replace("GATEWAY", gw.name());
    match gw.start(&facts).await {
        Ok(started) => {
            state
                .commerce
                .set_gateway(order.id, gw.name(), Some(&started.external_id))
                .await?;
            Ok((jar, Redirect::to(&started.redirect_url)).into_response())
        }
        Err(e) => {
            state.commerce.cancel(order.id).await?;
            Ok((
                jar,
                Redirect::to(&state.url(&format!(
                    "/checkout?error={}",
                    crate::routes::media::urlencoding(&e.to_string())
                ))),
            )
                .into_response())
        }
    }
}

pub async fn checkout_return(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Path(gateway): Path<String>,
    Query(q): Query<Vec<(String, String)>>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Faccount%2Forders")).into_response());
    };
    let order_uuid = q
        .iter()
        .find(|(k, _)| k == "order")
        .map(|(_, v)| v.clone())
        .unwrap_or_default();
    let Some(order) = state.commerce.order_by_uuid(&order_uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if order.user_id != user.id {
        return Ok(StatusCode::FORBIDDEN.into_response());
    }
    if order.status == "paid" {
        return Ok(
            Redirect::to(&state.url(&format!("/checkout/done/{}", order.uuid))).into_response(),
        );
    }
    let Some(gw) = gateway_named(&state, &gateway).await? else {
        return Ok((StatusCode::BAD_REQUEST, "Unknown payment method").into_response());
    };
    let external_id = q
        .iter()
        .find(|(k, _)| k == "session_id" || k == "token")
        .map(|(_, v)| v.clone())
        .or_else(|| order.external_id.clone())
        .unwrap_or_default();
    let facts = facts(&state, &order, &user).await?;
    match gw.confirm(&facts, &external_id, &q).await {
        Ok(Outcome::Paid {
            external_id,
            subscription_id,
            period_end,
        }) => {
            complete_paid(
                &state,
                &order,
                gw.name(),
                Some(&external_id),
                subscription_id.as_deref(),
                period_end.as_deref(),
            )
            .await?;
            Ok(Redirect::to(&state.url(&format!("/checkout/done/{}", order.uuid))).into_response())
        }
        Ok(Outcome::Pending) => Ok(Redirect::to(
            &state.url(&format!("/checkout/done/{}?pending=1", order.uuid)),
        )
        .into_response()),
        Ok(Outcome::Failed(msg)) => {
            state.commerce.cancel(order.id).await?;
            Ok(Redirect::to(&state.url(&format!(
                "/checkout?error={}",
                crate::routes::media::urlencoding(&msg)
            )))
            .into_response())
        }
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/checkout?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn checkout_cancel(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    if let (Some(u), Some(o)) = (user, state.commerce.order_by_uuid(&uuid).await?) {
        if o.user_id == u.id {
            state.commerce.cancel(o.id).await?;
        }
    }
    Ok(
        Redirect::to(&state.url("/cart?notice=Payment+cancelled.+Your+cart+is+still+here."))
            .into_response(),
    )
}

pub async fn checkout_done(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Path(uuid): Path<String>,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Faccount")).into_response());
    };
    let Some(order) = state.commerce.order_by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if order.user_id != user.id {
        return Ok(StatusCode::FORBIDDEN.into_response());
    }
    let items = state.commerce.items(order.id).await?;
    let receipt = state.commerce.receipt(order.id).await?.map(|(n, _, _)| n);
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("checkout_done.html", context! { user, site_name, order, items, receipt, pending => q.contains_key("pending"), total => money(order.total_cents, &order.currency) })?).into_response())
}

/// The test gateway's "hosted page": a button that pays and one that declines.
pub async fn test_page(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Fcheckout")).into_response());
    };
    let Some(order) = state.commerce.order_by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if order.user_id != user.id || state.settings.get("payments.test_mode").await? != "1" {
        return Ok(StatusCode::FORBIDDEN.into_response());
    }
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("checkout_test.html", context! { user, site_name, order, total => money(order.total_cents, &order.currency), csrf => customer_csrf(&state, &token) })?).into_response())
}

#[derive(Deserialize)]
pub struct TestForm {
    _csrf: String,
    #[serde(default)]
    result: String,
}

pub async fn test_submit(
    State(state): State<AppState>,
    MaybeUser(_user, token): MaybeUser,
    Path(uuid): Path<String>,
    Form(f): Form<TestForm>,
) -> AppResult<Response> {
    if f._csrf != customer_csrf(&state, &token) {
        return Ok((StatusCode::FORBIDDEN, "Invalid form token").into_response());
    }
    let result = if f.result == "fail" { "fail" } else { "paid" };
    Ok(Redirect::to(&state.url(&format!(
        "/checkout/return/test?order={uuid}&result={result}"
    )))
    .into_response())
}

/// /embed/sitepass?site= lists the passes for sale through the showcase.
pub async fn embed_sitepass(
    State(state): State<AppState>,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let site = q.get("site").cloned().unwrap_or_default();
    Ok(Redirect::to(&state.url(&format!(
        "/embed/showcase?site={}&type=site_pass",
        crate::routes::media::urlencoding(&site)
    )))
    .into_response())
}

// ----- the embedded checkout entry used by Buy buttons and widgets -----

#[derive(Deserialize)]
pub struct EmbedCheckoutQuery {
    site: Option<String>,
    #[serde(default)]
    product: String,
}

pub async fn embed_checkout(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    jar: CookieJar,
    Query(q): Query<EmbedCheckoutQuery>,
) -> AppResult<Response> {
    let csp = match q.site.as_deref() {
        Some(site) => match crate::routes::bridges::by_uuid(&state, site).await? {
            Some(s) => format!("frame-ancestors 'self' {}", s.origin),
            None => return Ok((StatusCode::FORBIDDEN, "Unknown site").into_response()),
        },
        None => "frame-ancestors 'self'".to_string(),
    };
    let (cart, jar) = current_cart(&state, jar, user.as_ref()).await?;
    let mut error = String::new();
    if !q.product.is_empty() {
        match state.products.by_slug(&q.product).await? {
            Some(p) => {
                if let Err(e) = state.commerce.add(&cart, &p, 1).await {
                    error = e.to_string();
                }
            }
            None => error = "That product does not exist".into(),
        }
    }
    let lines = state.commerce.lines(&cart).await?;
    let totals = state.commerce.cart_totals(&cart, &lines).await?;
    let currency = state.settings.get("store.currency").await?;
    let site_name = state.settings.get("general.site_name").await?;
    let html = state.render("embed_checkout.html", context! { user, site_name, lines, totals, currency, error, public_url => state.config.server.public_url.trim_end_matches('/'), site => q.site.clone().unwrap_or_default() })?;
    Ok((
        jar,
        [
            (header::CONTENT_SECURITY_POLICY, csp),
            (header::CACHE_CONTROL, "private, no-store".to_string()),
        ],
        Html(html),
    )
        .into_response())
}
