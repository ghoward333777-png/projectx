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
    Ok(Html(state.render("account.html", context! { user, site_name, items, site_pass, public_url => state.config.server.public_url, csrf => "" })?).into_response())
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
    Form(f): Form<LoginForm>,
) -> AppResult<Response> {
    let site_name = state.settings.get("general.site_name").await?;
    match state.users.authenticate(&f.email, &f.password).await? {
        Some(u) => {
            state.audit.record(Some(u.id), "auth.login", "user", Some(&u.uuid), None, None).await?;
            Ok((jar.add(auth::session_cookie(&state, u.id)), Redirect::to(&state.url(&crate::routes::sso::safe_return(Some(&f.return_to))))).into_response())
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
