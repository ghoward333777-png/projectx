//! First-run wizard: creates the first administrator when none exists.

use crate::app::AppState;
use crate::auth;
use crate::errors::AppResult;
use axum::extract::State;
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use axum_extra::extract::CookieJar;
use minijinja::context;
use serde::Deserialize;

pub async fn form(State(state): State<AppState>) -> AppResult<Response> {
    if state.users.count_admins().await? > 0 {
        return Ok(Redirect::to(&state.url("/admin/login")).into_response());
    }
    Ok(Html(state.render(
        "setup.html",
        context! { error => "", site_name => "MediaMarketplace" },
    )?)
    .into_response())
}

#[derive(Deserialize)]
pub struct SetupForm {
    email: String,
    name: String,
    password: String,
    password_repeat: String,
}

pub async fn submit(
    State(state): State<AppState>,
    jar: CookieJar,
    Form(f): Form<SetupForm>,
) -> AppResult<Response> {
    if state.users.count_admins().await? > 0 {
        return Ok(Redirect::to(&state.url("/admin/login")).into_response());
    }
    if f.password != f.password_repeat {
        return Ok(Html(state.render(
            "setup.html",
            context! { error => "Passwords do not match.", site_name => "MediaMarketplace" },
        )?)
        .into_response());
    }
    match state
        .users
        .create(&f.email, &f.name, Some(&f.password), "admin")
        .await
    {
        Ok(user) => {
            state
                .audit
                .record(
                    Some(user.id),
                    "setup.admin_created",
                    "user",
                    Some(&user.uuid),
                    None,
                    None,
                )
                .await?;
            let jar = jar.add(auth::session_cookie(&state, user.id));
            Ok((jar, Redirect::to(&state.url("/admin"))).into_response())
        }
        Err(e) => Ok(Html(state.render(
            "setup.html",
            context! { error => e.to_string(), site_name => "MediaMarketplace" },
        )?)
        .into_response()),
    }
}
