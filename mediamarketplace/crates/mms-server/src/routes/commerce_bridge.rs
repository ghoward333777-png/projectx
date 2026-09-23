//! The "sell through" API used by the WooCommerce module of the WordPress plugin and
//! the VirtueMart plugin of the Joomla package. Every request is signed with the
//! bridge site's secret (see `mms_core::commerce_bridge::request_signature`), so only
//! the site the store runs in can report orders. Money never moves here: the shop
//! took it; the store records the order, grants access and issues the receipt
//! through the same `complete_paid` path as its native checkout.

use crate::app::AppState;
use crate::auth;
use crate::errors::AppResult;
use crate::routes::bridges::{self, BridgeSite};
use axum::body::Bytes;
use axum::extract::{OriginalUri, Path, State};
use axum::http::{HeaderMap, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use mms_core::commerce_bridge::{self as bridge, is_system, system_label, LinkInput};
use mms_core::products::type_label;
use mms_core::products::Product;
use serde::Deserialize;
use serde_json::json;

fn err(code: StatusCode, msg: &str) -> Response {
    (
        code,
        Json(json!({ "error": { "code": code.as_u16(), "message": msg } })),
    )
        .into_response()
}

/// Verifies `X-MMS-Site`, `X-MMS-Timestamp` and `X-MMS-Signature` against the body.
async fn caller(
    state: &AppState,
    headers: &HeaderMap,
    method: &Method,
    path: &str,
    body: &[u8],
) -> AppResult<Result<BridgeSite, Response>> {
    let h = |n: &str| {
        headers
            .get(n)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .trim()
            .to_string()
    };
    let (site, ts, sig) = (h("x-mms-site"), h("x-mms-timestamp"), h("x-mms-signature"));
    if site.is_empty() || ts.is_empty() || sig.is_empty() {
        return Ok(Err(err(
            StatusCode::UNAUTHORIZED,
            "Missing X-MMS-Site, X-MMS-Timestamp or X-MMS-Signature",
        )));
    }
    let Some(site) = bridges::by_uuid(state, &site).await? else {
        return Ok(Err(err(StatusCode::FORBIDDEN, "Unknown bridge site")));
    };
    let ts: i64 = ts.parse().unwrap_or(0);
    if (auth::now_unix() - ts).abs() > bridge::MAX_SKEW_SECONDS {
        return Ok(Err(err(
            StatusCode::FORBIDDEN,
            "Request timestamp is too old; check the server clock",
        )));
    }
    let secret = state.secrets.decrypt(&site.secret_enc)?;
    let expected = bridge::request_signature(&secret, ts, method.as_str(), path, body);
    if !bridge::signature_matches(&expected, &sig.to_ascii_lowercase()) {
        state
            .audit
            .record(
                None,
                "commerce.rejected",
                "bridge_site",
                Some(&site.uuid),
                None,
                Some(json!({ "path": path })),
            )
            .await?;
        return Ok(Err(err(StatusCode::FORBIDDEN, "Bad request signature")));
    }
    Ok(Ok(site))
}

#[allow(clippy::result_large_err)]
fn parse<T: serde::de::DeserializeOwned>(body: &[u8]) -> Result<T, Response> {
    serde_json::from_slice(body)
        .map_err(|e| err(StatusCode::BAD_REQUEST, &format!("Invalid JSON body: {e}")))
}

/// What a Buy button should do for a product under the current settings.
pub enum Buy {
    Native,
    External(String),
    Hidden,
}

/// The site address Buy buttons point at: the bridge site whose CMS runs the chosen
/// shop, else the first connected site, else the store's own public address.
async fn shop_origin(state: &AppState, mode: &str) -> AppResult<String> {
    let host = match mode {
        "woocommerce" => "wordpress",
        "virtuemart" => "joomla",
        _ => "",
    };
    let sites = bridges::all(state).await?;
    let pick = sites
        .iter()
        .find(|s| s.status == "active" && s.host == host)
        .or_else(|| sites.iter().find(|s| s.status == "active"));
    Ok(match pick {
        Some(s) => s.origin.clone(),
        None => {
            let p = &state.config.server.public_url;
            let rest = p.find("://").map(|i| &p[i + 3..]).unwrap_or(p);
            let end = rest
                .find('/')
                .map(|i| i + p.len() - rest.len())
                .unwrap_or(p.len());
            p[..end].to_string()
        }
    })
}

pub async fn buy_for(state: &AppState, product: &Product) -> AppResult<Buy> {
    let mode = state.settings.get("commerce.mode").await?;
    if !is_system(&mode) {
        return Ok(Buy::Native);
    }
    match state.commerce_bridge.mapping(&mode, product.id).await? {
        Some(m) => {
            let template = state.settings.get("commerce.cart_url").await?;
            let origin = shop_origin(state, &mode).await?;
            Ok(bridge::buy_url(&mode, &template, &origin, &m.external_id)
                .map(Buy::External)
                .unwrap_or(Buy::Native))
        }
        None => Ok(
            if state.settings.get("commerce.unlinked").await? == "hide" {
                Buy::Hidden
            } else {
                Buy::Native
            },
        ),
    }
}

/// `(buy_url, buy_hidden)` for templates.
pub async fn buy_context(state: &AppState, product: &Product) -> AppResult<(String, bool)> {
    Ok(match buy_for(state, product).await? {
        Buy::Native => (String::new(), false),
        Buy::External(u) => (u, false),
        Buy::Hidden => (String::new(), true),
    })
}

// ----- status, catalogue, links, mode -----

pub async fn status(
    State(state): State<AppState>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    body: Bytes,
) -> AppResult<Response> {
    let site = match caller(&state, &headers, &Method::GET, uri.path(), &body).await? {
        Ok(s) => s,
        Err(r) => return Ok(r),
    };
    let mode = state.settings.get("commerce.mode").await?;
    let mut linked = serde_json::Map::new();
    for (s, _, _) in bridge::SYSTEMS {
        linked.insert(s.to_string(), json!(state.commerce_bridge.count(s).await?));
    }
    Ok(Json(json!({ "data": {
        "mode": mode, "mode_label": if is_system(&mode) { system_label(&mode) } else { "native" },
        "cart_url": state.settings.get("commerce.cart_url").await?,
        "unlinked": state.settings.get("commerce.unlinked").await?,
        "site": { "uuid": site.uuid, "host": site.host, "origin": site.origin },
        "linked": linked,
        "products": sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM products WHERE status <> 'archived'").fetch_one(&state.db.pool).await?,
        "events": state.commerce_bridge.events(20).await?,
        "version": env!("CARGO_PKG_VERSION"),
    } })).into_response())
}

pub async fn catalog(
    State(state): State<AppState>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    body: Bytes,
) -> AppResult<Response> {
    if let Err(r) = caller(&state, &headers, &Method::GET, uri.path(), &body).await? {
        return Ok(r);
    }
    let system = uri
        .query()
        .and_then(|q| q.split('&').find_map(|kv| kv.strip_prefix("system=")))
        .unwrap_or("")
        .to_string();
    let public = state
        .config
        .server
        .public_url
        .trim_end_matches('/')
        .to_string();
    let categories = state.products.categories().await?;
    let mut out = Vec::new();
    for p in state.products.list_admin("", "", "").await? {
        if p.status == "archived" {
            continue;
        }
        let cat_ids = state.products.category_ids(p.id).await?;
        let cats: Vec<String> = categories
            .iter()
            .filter(|c| cat_ids.contains(&c.id))
            .map(|c| c.name.clone())
            .collect();
        let media = match p.preview_media_id.or(p.media_id) {
            Some(id) => state.media.by_id(id).await?,
            None => None,
        };
        let image_url = media
            .and_then(|m| m.thumbnail_path)
            .map(|t| format!("{public}/media/{t}"));
        let mapping = if system.is_empty() {
            None
        } else {
            state.commerce_bridge.mapping(&system, p.id).await?
        };
        out.push(json!({
            "uuid": p.uuid, "slug": p.slug, "title": p.title, "description": p.description.clone().unwrap_or_default(),
            "type": p.r#type, "type_label": type_label(&p.r#type), "price_cents": p.price_cents, "currency": p.currency,
            "status": p.status, "featured": p.featured == 1, "categories": cats, "image_url": image_url,
            "page_url": format!("{public}/embed/product/{}", p.slug), "settings": p.settings_json(),
            "external_id": mapping.as_ref().map(|m| m.external_id.clone()), "external_url": mapping.as_ref().map(|m| m.external_url.clone()),
            "recurring": mms_core::commerce::is_recurring(&p),
        }));
    }
    Ok(Json(json!({ "data": out })).into_response())
}

#[derive(Deserialize)]
pub struct LinkBody {
    system: String,
    #[serde(default)]
    links: Vec<LinkInput>,
    #[serde(default)]
    unlink: Vec<String>,
}

pub async fn link(
    State(state): State<AppState>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    body: Bytes,
) -> AppResult<Response> {
    if let Err(r) = caller(&state, &headers, &Method::POST, uri.path(), &body).await? {
        return Ok(r);
    }
    let b: LinkBody = match parse(&body) {
        Ok(b) => b,
        Err(r) => return Ok(r),
    };
    if !is_system(&b.system) {
        return Ok(err(
            StatusCode::BAD_REQUEST,
            "system must be woocommerce or virtuemart",
        ));
    }
    let (linked, unknown) = state.commerce_bridge.link(&b.system, &b.links).await?;
    let mut unlinked = 0;
    for slug in &b.unlink {
        if let Some(p) = state.products.by_slug(slug).await? {
            state.commerce_bridge.unlink(&b.system, p.id).await?;
            unlinked += 1;
        }
    }
    state
        .audit
        .record(
            None,
            "commerce.linked",
            "bridge",
            None,
            None,
            Some(json!({ "system": b.system, "linked": linked, "unlinked": unlinked })),
        )
        .await?;
    Ok(Json(json!({ "data": { "linked": linked, "unlinked": unlinked, "unknown": unknown, "total": state.commerce_bridge.count(&b.system).await? } })).into_response())
}

#[derive(Deserialize)]
pub struct ModeBody {
    mode: String,
    #[serde(default)]
    cart_url: Option<String>,
    #[serde(default)]
    unlinked: Option<String>,
}

/// Switches checkout between the native cart and the shop. The shop plugin calls this
/// from its own settings page; the same setting is under Settings → Sell through.
pub async fn set_mode(
    State(state): State<AppState>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    body: Bytes,
) -> AppResult<Response> {
    let site = match caller(&state, &headers, &Method::POST, uri.path(), &body).await? {
        Ok(s) => s,
        Err(r) => return Ok(r),
    };
    let b: ModeBody = match parse(&body) {
        Ok(b) => b,
        Err(r) => return Ok(r),
    };
    if b.mode != "native" && !is_system(&b.mode) {
        return Ok(err(
            StatusCode::BAD_REQUEST,
            "mode must be native, woocommerce or virtuemart",
        ));
    }
    state.settings.set("commerce.mode", &b.mode).await?;
    if let Some(u) = b.cart_url {
        state.settings.set("commerce.cart_url", &u).await?;
    }
    if let Some(u) = b.unlinked {
        if matches!(u.as_str(), "native" | "hide") {
            state.settings.set("commerce.unlinked", &u).await?;
        }
    }
    state
        .audit
        .record(
            None,
            "commerce.mode",
            "bridge_site",
            Some(&site.uuid),
            None,
            Some(json!({ "mode": b.mode })),
        )
        .await?;
    Ok(Json(json!({ "data": { "mode": b.mode } })).into_response())
}

// ----- orders -----

#[derive(Deserialize, Default)]
pub struct CustomerBody {
    #[serde(default)]
    id: String,
    #[serde(default)]
    email: String,
    #[serde(default)]
    name: String,
}

#[derive(Deserialize)]
pub struct ItemBody {
    #[serde(default)]
    slug: String,
    #[serde(default)]
    external_id: String,
    #[serde(default = "one")]
    quantity: i64,
    #[serde(default)]
    unit_cents: i64,
}

fn one() -> i64 {
    1
}

#[derive(Deserialize, Default)]
pub struct SubscriptionRef {
    #[serde(default)]
    external_id: String,
    #[serde(default)]
    period_end: String,
}

#[derive(Deserialize)]
pub struct OrderBody {
    system: String,
    external_id: String,
    status: String,
    #[serde(default)]
    customer: CustomerBody,
    #[serde(default)]
    currency: String,
    #[serde(default)]
    items: Vec<ItemBody>,
    #[serde(default)]
    discount_cents: i64,
    #[serde(default)]
    tax_cents: i64,
    #[serde(default)]
    country: String,
    #[serde(default)]
    subscription: Option<SubscriptionRef>,
}

async fn resolve_user(
    state: &AppState,
    site: &BridgeSite,
    c: &CustomerBody,
) -> AppResult<Result<mms_core::users::User, Response>> {
    if c.email.trim().is_empty() {
        return Ok(Err(err(
            StatusCode::BAD_REQUEST,
            "customer.email is required",
        )));
    }
    let external = if c.id.trim().is_empty() {
        format!("email:{}", c.email.trim().to_lowercase())
    } else {
        c.id.trim().to_string()
    };
    let name = if c.name.trim().is_empty() {
        c.email.split('@').next().unwrap_or("Customer")
    } else {
        c.name.trim()
    };
    match state
        .users
        .link_identity(
            &format!("{}:{}", site.host, site.uuid),
            &external,
            c.email.trim(),
            name,
        )
        .await
    {
        Ok(u) => Ok(Ok(u)),
        Err(e) => Ok(Err(err(StatusCode::BAD_REQUEST, &e.to_string()))),
    }
}

async fn resolve_items(
    state: &AppState,
    system: &str,
    items: &[ItemBody],
) -> AppResult<(Vec<(Product, i64, i64)>, Vec<String>)> {
    let mut out = Vec::new();
    let mut skipped = Vec::new();
    for it in items {
        let p = if !it.slug.trim().is_empty() {
            state.products.by_slug(it.slug.trim()).await?
        } else if !it.external_id.trim().is_empty() {
            match state
                .commerce_bridge
                .by_external(system, it.external_id.trim())
                .await?
            {
                Some(m) => state.products.by_id(m.product_id).await?,
                None => None,
            }
        } else {
            None
        };
        match p {
            Some(p) => out.push((p, it.quantity.max(1), it.unit_cents.max(0))),
            None => skipped.push(if it.slug.is_empty() {
                it.external_id.clone()
            } else {
                it.slug.clone()
            }),
        }
    }
    Ok((out, skipped))
}

pub async fn order(
    State(state): State<AppState>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    body: Bytes,
) -> AppResult<Response> {
    let site = match caller(&state, &headers, &Method::POST, uri.path(), &body).await? {
        Ok(s) => s,
        Err(r) => return Ok(r),
    };
    let b: OrderBody = match parse(&body) {
        Ok(b) => b,
        Err(r) => return Ok(r),
    };
    if !is_system(&b.system) {
        return Ok(err(
            StatusCode::BAD_REQUEST,
            "system must be woocommerce or virtuemart",
        ));
    }
    let external_id = b.external_id.trim().to_string();
    if external_id.is_empty() {
        return Ok(err(StatusCode::BAD_REQUEST, "external_id is required"));
    }
    let status = b.status.trim().to_lowercase();
    let existing = state
        .commerce
        .order_by_external(&b.system, &external_id)
        .await?;
    let mut result = json!({});
    let outcome: String = match status.as_str() {
        "paid" | "pending" => {
            let order = match existing {
                Some(o) => o,
                None => {
                    let user = match resolve_user(&state, &site, &b.customer).await? {
                        Ok(u) => u,
                        Err(r) => return Ok(r),
                    };
                    let (items, skipped) = resolve_items(&state, &b.system, &b.items).await?;
                    if items.is_empty() {
                        state
                            .commerce_bridge
                            .record_event(
                                &b.system,
                                "order",
                                &external_id,
                                &status,
                                "ignored: no store products in the order",
                            )
                            .await?;
                        return Ok(Json(json!({ "data": { "ignored": true, "reason": "no store products in the order", "skipped": skipped } })).into_response());
                    }
                    let currency = if b.currency.trim().is_empty() {
                        state.settings.get("store.currency").await?
                    } else {
                        b.currency.trim().to_uppercase()
                    };
                    let o = state
                        .commerce
                        .create_external_order(
                            user.id,
                            &b.system,
                            &external_id,
                            &currency,
                            &items,
                            b.discount_cents,
                            b.tax_cents,
                            &b.country,
                        )
                        .await?;
                    result["skipped"] = json!(skipped);
                    o
                }
            };
            let mut granted = false;
            if status == "paid" {
                let (sub_id, period_end) = match &b.subscription {
                    Some(s) if !s.external_id.trim().is_empty() => (
                        Some(s.external_id.trim()),
                        (!s.period_end.trim().is_empty()).then(|| s.period_end.trim()),
                    ),
                    _ => (None, None),
                };
                granted = crate::routes::shop::complete_paid(
                    &state,
                    &order,
                    &b.system,
                    Some(&external_id),
                    sub_id,
                    period_end,
                )
                .await?;
            }
            let order = state.commerce.order_by_id(order.id).await?.unwrap_or(order);
            let ents = state
                .entitlements
                .for_user(order.user_id)
                .await?
                .into_iter()
                .filter(|e| e.source_ref == order.uuid)
                .count();
            result["order"] = json!({ "uuid": order.uuid, "number": order.number, "status": order.status, "total_cents": order.total_cents, "currency": order.currency });
            result["granted_now"] = json!(granted);
            result["entitlements"] = json!(ents);
            result["receipt_url"] = json!(format!("/account/receipts/{}/pdf", order.uuid));
            if granted {
                "paid: access granted".into()
            } else {
                format!("{}: already recorded", order.status)
            }
        }
        "refunded" | "cancelled" => match existing {
            Some(o) if o.status == "paid" => {
                state
                    .commerce
                    .mark_refunded(
                        &o,
                        Some(&external_id),
                        &format!("{} in {}", status, system_label(&b.system)),
                    )
                    .await?;
                state
                    .audit
                    .record(
                        Some(o.user_id),
                        "order.refunded",
                        "order",
                        Some(&o.uuid),
                        None,
                        Some(json!({ "number": o.number, "gateway": b.system })),
                    )
                    .await?;
                crate::routes::shop::emit(
                    &state,
                    "order.refunded",
                    json!({ "order": o.uuid, "number": o.number, "gateway": b.system }),
                )
                .await?;
                result["order"] =
                    json!({ "uuid": o.uuid, "number": o.number, "status": "refunded" });
                "refunded: access revoked".into()
            }
            Some(o) if o.status == "pending" => {
                state.commerce.cancel(o.id).await?;
                result["order"] =
                    json!({ "uuid": o.uuid, "number": o.number, "status": "cancelled" });
                "cancelled".into()
            }
            Some(o) => format!("{}: nothing to do", o.status),
            None => "ignored: order never reached the store".into(),
        },
        _ => {
            return Ok(err(
                StatusCode::BAD_REQUEST,
                "status must be paid, pending, refunded or cancelled",
            ))
        }
    };
    state
        .commerce_bridge
        .record_event(&b.system, "order", &external_id, &status, &outcome)
        .await?;
    result["outcome"] = json!(outcome);
    Ok(Json(json!({ "data": result })).into_response())
}

pub async fn order_status(
    State(state): State<AppState>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    Path((system, external_id)): Path<(String, String)>,
    body: Bytes,
) -> AppResult<Response> {
    if let Err(r) = caller(&state, &headers, &Method::GET, uri.path(), &body).await? {
        return Ok(r);
    }
    let Some(o) = state
        .commerce
        .order_by_external(&system, &external_id)
        .await?
    else {
        return Ok(err(StatusCode::NOT_FOUND, "No such order"));
    };
    let items = state.commerce.items(o.id).await?;
    let ents: Vec<_> = state
        .entitlements
        .for_user(o.user_id)
        .await?
        .into_iter()
        .filter(|e| e.source_ref == o.uuid)
        .collect();
    Ok(
        Json(json!({ "data": { "order": o, "items": items, "entitlements": ents } }))
            .into_response(),
    )
}

// ----- subscriptions (WooCommerce Subscriptions; VirtueMart has none natively) -----

#[derive(Deserialize)]
pub struct SubscriptionBody {
    system: String,
    external_id: String,
    status: String,
    #[serde(default)]
    customer: CustomerBody,
    #[serde(default)]
    slug: String,
    #[serde(default)]
    product_external_id: String,
    #[serde(default)]
    period_end: String,
    #[serde(default)]
    order_external_id: String,
}

pub async fn subscription(
    State(state): State<AppState>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    body: Bytes,
) -> AppResult<Response> {
    let site = match caller(&state, &headers, &Method::POST, uri.path(), &body).await? {
        Ok(s) => s,
        Err(r) => return Ok(r),
    };
    let b: SubscriptionBody = match parse(&body) {
        Ok(b) => b,
        Err(r) => return Ok(r),
    };
    if !is_system(&b.system) {
        return Ok(err(
            StatusCode::BAD_REQUEST,
            "system must be woocommerce or virtuemart",
        ));
    }
    let external_id = b.external_id.trim().to_string();
    let status = b.status.trim().to_lowercase().replace('-', "_");
    let period_end = (!b.period_end.trim().is_empty()).then(|| b.period_end.trim().to_string());
    let existing = state
        .commerce
        .subscription_by_external(&b.system, &external_id)
        .await?;
    let outcome: String = match (status.as_str(), existing) {
        ("active" | "renewed", Some(sub)) => {
            let end = period_end.clone().unwrap_or_else(|| {
                mms_core::commerce::add_days(
                    &mms_core::now(),
                    if sub.interval == "year" { 365 } else { 31 },
                )
            });
            state.commerce.renew_subscription(&sub, &end).await?;
            crate::routes::shop::emit(
                &state,
                "subscription.renewed",
                json!({ "subscription": sub.uuid, "period_end": end, "gateway": b.system }),
            )
            .await?;
            format!("active until {end}")
        }
        ("active" | "renewed", None) => {
            let user = match resolve_user(&state, &site, &b.customer).await? {
                Ok(u) => u,
                Err(r) => return Ok(r),
            };
            let product = if !b.slug.trim().is_empty() {
                state.products.by_slug(b.slug.trim()).await?
            } else {
                match state
                    .commerce_bridge
                    .by_external(&b.system, b.product_external_id.trim())
                    .await?
                {
                    Some(m) => state.products.by_id(m.product_id).await?,
                    None => None,
                }
            };
            let Some(p) = product else {
                return Ok(err(
                    StatusCode::NOT_FOUND,
                    "No store product for this subscription (give slug or product_external_id)",
                ));
            };
            let order_id = if b.order_external_id.trim().is_empty() {
                None
            } else {
                state
                    .commerce
                    .order_by_external(&b.system, b.order_external_id.trim())
                    .await?
                    .map(|o| o.id)
            };
            let end = period_end.clone().unwrap_or_else(|| {
                mms_core::commerce::add_days(
                    &mms_core::now(),
                    if mms_core::commerce::recurring_interval(&p) == "year" {
                        365
                    } else {
                        31
                    },
                )
            });
            let sub = state
                .commerce
                .create_subscription(
                    user.id,
                    p.id,
                    order_id,
                    &b.system,
                    Some(&external_id),
                    &mms_core::commerce::recurring_interval(&p),
                    Some(&end),
                )
                .await?;
            state.commerce.renew_subscription(&sub, &end).await?;
            format!("created, active until {end}")
        }
        ("pending_cancel", Some(sub)) => {
            state
                .commerce
                .set_subscription_status(&sub, "cancelled", true)
                .await?;
            "cancels at period end".into()
        }
        ("cancelled" | "expired" | "ended" | "on_hold" | "switched", Some(sub)) => {
            state
                .commerce
                .set_subscription_status(
                    &sub,
                    if status == "on_hold" {
                        "paused"
                    } else {
                        "ended"
                    },
                    false,
                )
                .await?;
            if status == "on_hold" {
                state
                    .entitlements
                    .revoke_source("subscription", &sub.uuid)
                    .await?;
            }
            crate::routes::shop::emit(
                &state,
                "subscription.ended",
                json!({ "subscription": sub.uuid, "gateway": b.system, "status": status }),
            )
            .await?;
            format!("{status}: access revoked")
        }
        (_, None) => "ignored: unknown subscription".into(),
        _ => return Ok(err(
            StatusCode::BAD_REQUEST,
            "status must be active, renewed, pending_cancel, on_hold, cancelled, expired or ended",
        )),
    };
    state
        .commerce_bridge
        .record_event(&b.system, "subscription", &external_id, &status, &outcome)
        .await?;
    Ok(Json(json!({ "data": { "outcome": outcome } })).into_response())
}

// ----- customers -----

/// Everything a shop customer may open, for the shop's "My account" area.
pub async fn customer(
    State(state): State<AppState>,
    headers: HeaderMap,
    OriginalUri(uri): OriginalUri,
    Path(external_id): Path<String>,
    body: Bytes,
) -> AppResult<Response> {
    let site = match caller(&state, &headers, &Method::GET, uri.path(), &body).await? {
        Ok(s) => s,
        Err(r) => return Ok(r),
    };
    let host = format!("{}:{}", site.host, site.uuid);
    let uid: Option<i64> = sqlx::query_scalar(
        "SELECT user_id FROM user_identities WHERE host = ? AND external_id = ?",
    )
    .bind(&host)
    .bind(external_id.trim())
    .fetch_optional(&state.db.pool)
    .await?;
    let Some(uid) = uid else {
        return Ok(Json(json!({ "data": { "known": false, "entitlements": [] } })).into_response());
    };
    let now = mms_core::now();
    let mut ents = Vec::new();
    for e in state.entitlements.for_user(uid).await? {
        if e.status != "active"
            || e.ends_at
                .as_deref()
                .map(|t| t <= now.as_str())
                .unwrap_or(false)
        {
            continue;
        }
        let product = match e.product_id {
            Some(id) => state.products.by_id(id).await?,
            None => None,
        };
        ents.push(json!({
            "scope": e.scope, "scope_ref": e.scope_ref, "ends_at": e.ends_at, "source": e.source,
            "product": product.as_ref().map(|p| json!({ "slug": p.slug, "title": p.title, "type": p.r#type, "type_label": type_label(&p.r#type) })),
            "open_path": match (&product, e.scope.as_str()) { (Some(p), "product") => format!("/embed/player/{}", p.slug), (_, "page") => format!("/page/{}", e.scope_ref), _ => "/account".to_string() },
        }));
    }
    let orders = state.commerce.orders("", "", Some(uid)).await?;
    Ok(Json(json!({ "data": { "known": true, "user": { "uuid": state.users.by_id(uid).await?.map(|u| u.uuid) }, "entitlements": ents, "orders": orders.len(), "account_path": "/account" } })).into_response())
}
