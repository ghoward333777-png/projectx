//! Customer area: My Media, direct sign-in and registration.

use crate::app::AppState;
use crate::auth::{self, MaybeUser};
use crate::errors::AppResult;
use axum::extract::State;
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use axum_extra::extract::CookieJar;
use minijinja::context;
use serde::Deserialize;

pub async fn my_media(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Faccount")).into_response());
    };
    let grants = state.entitlements.for_user(user.id).await?;
    let now = mms_core::now();
    let mut items = Vec::new();
    let mut site_pass = None;
    for g in grants.iter().filter(|g| {
        g.status == "active"
            && g.ends_at
                .as_deref()
                .map(|e| e > now.as_str())
                .unwrap_or(true)
    }) {
        if g.scope == "site" {
            site_pass = Some(context! { ends_at => g.ends_at.clone() });
        } else if let Some(pid) = g.product_id {
            if let Some(p) = state.products.by_id(pid).await? {
                let thumb = match p.media_id {
                    Some(m) => state.media.by_id(m).await?.and_then(|m| m.thumbnail_path),
                    None => None,
                };
                items.push(context! { p, thumb, ends_at => g.ends_at.clone(), type_label => mms_core::products::type_label(&p.r#type) });
            }
        }
    }
    // A site pass shows the whole published library.
    if site_pass.is_some() {
        let (cards, _) = state
            .products
            .showcase(&mms_core::products::ShowcaseQuery {
                per_page: 96,
                page: 1,
                ..Default::default()
            })
            .await?;
        let owned: std::collections::HashSet<i64> =
            grants.iter().filter_map(|g| g.product_id).collect();
        for c in cards {
            if let Some(p) = state.products.by_slug(&c.slug).await? {
                if owned.contains(&p.id) {
                    continue;
                }
                items.push(context! { p, thumb => c.thumbnail_path.clone(), ends_at => None::<String>, type_label => mms_core::products::type_label(&c.r#type) });
            }
        }
    }
    let site_name = state.settings.get("general.site_name").await?;
    let pass_notice = state.commerce.pass_notice_for(user.id).await?;
    let renew_slug: Option<String> = sqlx::query_scalar("SELECT slug FROM products WHERE type = 'site_pass' AND status = 'published' ORDER BY id LIMIT 1").fetch_optional(&state.db.pool).await?;
    let renew_url = match &renew_slug {
        Some(slug) => match state.products.by_slug(slug).await? {
            Some(p) => {
                crate::routes::commerce_bridge::buy_context(&state, &p)
                    .await?
                    .0
            }
            None => String::new(),
        },
        None => String::new(),
    };
    Ok(Html(state.render("account.html", context! { user, site_name, items, site_pass, pass_notice, renew_slug, renew_url, public_url => state.config.server.public_url, csrf => "", tab => "media" })?).into_response())
}

#[derive(Deserialize)]
pub struct ReturnQuery {
    #[serde(default, rename = "return")]
    return_to: String,
}

pub async fn login_form(
    State(state): State<AppState>,
    axum::extract::Query(q): axum::extract::Query<ReturnQuery>,
) -> AppResult<Response> {
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render(
        "customer_login.html",
        context! { site_name, error => "", mode => "login", return_to => q.return_to },
    )?)
    .into_response())
}

#[derive(Deserialize)]
pub struct LoginForm {
    email: String,
    password: String,
    #[serde(default, rename = "return")]
    return_to: String,
}

pub async fn login(
    State(state): State<AppState>,
    jar: CookieJar,
    headers: axum::http::HeaderMap,
    Form(f): Form<LoginForm>,
) -> AppResult<Response> {
    let site_name = state.settings.get("general.site_name").await?;
    let subject = format!("login:{}", crate::routes::shop::client_ip(&headers));
    if let Some(until) = state.pages.locked_until(&subject).await? {
        if until.as_str() > mms_core::now().as_str() {
            return Ok(Html(state.render("customer_login.html", context! { site_name, error => format!("Too many attempts. Try again after {until}."), mode => "login", return_to => f.return_to })?).into_response());
        }
    }
    let attempt = state.users.authenticate(&f.email, &f.password).await?;
    let (limit, window, lockout) = crate::routes::pages::limits_pub(&state).await?;
    state
        .pages
        .record_attempt(&subject, 0, attempt.is_some(), limit, window, lockout)
        .await?;
    match attempt {
        Some(u) => {
            state.audit.record(Some(u.id), "auth.login", "user", Some(&u.uuid), None, None).await?;
            let dest = if u.is_agent() && !u.is_staff() && f.return_to.trim().is_empty() { "/agent".to_string() } else { crate::routes::sso::safe_return(Some(&f.return_to)) };
            Ok((jar.add(auth::session_cookie(&state, u.id)), Redirect::to(&state.url(&dest))).into_response())
        }
        None => Ok(Html(state.render("customer_login.html", context! { site_name, error => "Email or password is incorrect.", mode => "login", return_to => f.return_to })?).into_response()),
    }
}

pub async fn register_form(
    State(state): State<AppState>,
    axum::extract::Query(q): axum::extract::Query<ReturnQuery>,
) -> AppResult<Response> {
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render(
        "customer_login.html",
        context! { site_name, error => "", mode => "register", return_to => q.return_to },
    )?)
    .into_response())
}

#[derive(Deserialize)]
pub struct RegisterForm {
    name: String,
    email: String,
    password: String,
    #[serde(default, rename = "return")]
    return_to: String,
}

pub async fn register(
    State(state): State<AppState>,
    jar: CookieJar,
    Form(f): Form<RegisterForm>,
) -> AppResult<Response> {
    let site_name = state.settings.get("general.site_name").await?;
    match state.users.create(&f.email, &f.name, Some(&f.password), "customer").await {
        Ok(u) => {
            state.audit.record(Some(u.id), "auth.registered", "user", Some(&u.uuid), None, None).await?;
            Ok((jar.add(auth::session_cookie(&state, u.id)), Redirect::to(&state.url(&crate::routes::sso::safe_return(Some(&f.return_to))))).into_response())
        }
        Err(e) => Ok(Html(state.render("customer_login.html", context! { site_name, error => e.to_string(), mode => "register", return_to => f.return_to })?).into_response()),
    }
}

pub async fn logout(State(state): State<AppState>, jar: CookieJar) -> AppResult<Response> {
    Ok((
        jar.add(auth::clear_cookie(&state)),
        Redirect::to(&state.url("/login")),
    )
        .into_response())
}

// ----- orders, receipts, agreements and subscriptions -----

pub async fn orders(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Faccount%2Forders")).into_response());
    };
    let orders = state.commerce.orders("", "", Some(user.id)).await?;
    let mut rows = Vec::new();
    for o in orders {
        let items = state.commerce.items(o.id).await?;
        let receipt = state.commerce.receipt(o.id).await?.map(|(n, _, _)| n);
        rows.push(context! { total => mms_core::commerce::money(o.total_cents, &o.currency), items, receipt, o });
    }
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render(
        "account_orders.html",
        context! { user, site_name, rows, tab => "orders" },
    )?)
    .into_response())
}

pub async fn receipt(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    axum::extract::Path((uuid, format)): axum::extract::Path<(String, String)>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Faccount%2Forders")).into_response());
    };
    let Some(o) = state.commerce.order_by_uuid(&uuid).await? else {
        return Ok(axum::http::StatusCode::NOT_FOUND.into_response());
    };
    if o.user_id != user.id {
        return Ok(axum::http::StatusCode::FORBIDDEN.into_response());
    }
    let Some((number, html, pdf)) = state.commerce.receipt(o.id).await? else {
        return Ok(axum::http::StatusCode::NOT_FOUND.into_response());
    };
    use axum::http::header;
    if format == "pdf" {
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
    } else {
        Ok(Html(html).into_response())
    }
}

pub async fn agreements(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(
            Redirect::to(&state.url("/login?return=%2Faccount%2Fagreements")).into_response(),
        );
    };
    let ags = state.pages.agreements(None, Some(user.id)).await?;
    let mut rows = Vec::new();
    for a in ags {
        let page = state.pages.by_id(a.page_id).await?;
        rows.push(context! { a, title => page.as_ref().map(|p| p.title.clone()).unwrap_or_else(|| "(deleted page)".into()), page_uuid => page.as_ref().map(|p| p.uuid.clone()) });
    }
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render(
        "account_agreements.html",
        context! { user, site_name, rows, tab => "agreements" },
    )?)
    .into_response())
}

pub async fn agreement_pdf(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    axum::extract::Path(uuid): axum::extract::Path<String>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(
            Redirect::to(&state.url("/login?return=%2Faccount%2Fagreements")).into_response(),
        );
    };
    use axum::http::header;
    match state
        .pages
        .agreement_pdf_by_uuid(&uuid, Some(user.id))
        .await?
    {
        Some(pdf) => Ok((
            [
                (header::CONTENT_TYPE, "application/pdf".to_string()),
                (
                    header::CONTENT_DISPOSITION,
                    format!("inline; filename=\"agreement-{uuid}.pdf\""),
                ),
            ],
            pdf,
        )
            .into_response()),
        None => Ok(axum::http::StatusCode::NOT_FOUND.into_response()),
    }
}

pub async fn subscriptions(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    axum::extract::Query(q): axum::extract::Query<std::collections::HashMap<String, String>>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(
            Redirect::to(&state.url("/login?return=%2Faccount%2Fsubscriptions")).into_response(),
        );
    };
    let subs = state.commerce.subscriptions_for(user.id).await?;
    let mut rows = Vec::new();
    for s in subs {
        let title = state
            .products
            .by_id(s.product_id)
            .await?
            .map(|p| p.title)
            .unwrap_or_default();
        rows.push(context! { s, title });
    }
    let csrf = token
        .as_deref()
        .map(|t| auth::csrf_token(&state, t))
        .unwrap_or_default();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("account_subscriptions.html", context! { user, site_name, rows, csrf, tab => "subscriptions", notice => q.get("notice").cloned().unwrap_or_default(), error => q.get("error").cloned().unwrap_or_default() })?).into_response())
}

#[derive(Deserialize)]
pub struct CancelForm {
    _csrf: String,
}

pub async fn cancel_subscription(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    axum::extract::Path(uuid): axum::extract::Path<String>,
    Form(f): Form<CancelForm>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(
            Redirect::to(&state.url("/login?return=%2Faccount%2Fsubscriptions")).into_response(),
        );
    };
    if f._csrf
        != token
            .as_deref()
            .map(|t| auth::csrf_token(&state, t))
            .unwrap_or_default()
    {
        return Ok((axum::http::StatusCode::FORBIDDEN, "Invalid form token").into_response());
    }
    let Some(sub) = state.commerce.subscription_by_uuid(&uuid).await? else {
        return Ok(axum::http::StatusCode::NOT_FOUND.into_response());
    };
    if sub.user_id != user.id {
        return Ok(axum::http::StatusCode::FORBIDDEN.into_response());
    }
    if let (Some(gw), Some(ext)) = (
        crate::routes::shop::gateway_named(&state, &sub.gateway).await?,
        sub.external_id.as_deref(),
    ) {
        if let Err(e) = gw.cancel_subscription(ext, true).await {
            return Ok(Redirect::to(&state.url(&format!(
                "/account/subscriptions?error={}",
                crate::routes::media::urlencoding(&e.to_string())
            )))
            .into_response());
        }
    }
    // Access stays until the paid period ends; the gateway stops renewing.
    state
        .commerce
        .set_subscription_status(&sub, "active", true)
        .await?;
    state
        .audit
        .record(
            Some(user.id),
            "subscription.cancel_requested",
            "subscription",
            Some(&sub.uuid),
            None,
            None,
        )
        .await?;
    Ok(Redirect::to(&state.url("/account/subscriptions?notice=Your+pass+will+not+renew.+It+stays+open+until+the+end+of+the+period+you+paid+for.")).into_response())
}
