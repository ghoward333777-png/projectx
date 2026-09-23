use crate::app::AppState;
use crate::auth::{self, AdminUser, MaybeUser};
use crate::errors::AppResult;
use axum::extract::State;
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use axum_extra::extract::CookieJar;
use minijinja::context;
use serde::Deserialize;
use std::collections::HashMap;

pub async fn index(State(state): State<AppState>) -> AppResult<Response> {
    if state.users.count_admins().await? == 0 {
        return Ok(Redirect::to(&state.url("/setup")).into_response());
    }
    Ok(Redirect::to(&state.url("/admin")).into_response())
}

pub async fn login_form(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
) -> AppResult<Response> {
    if state.users.count_admins().await? == 0 {
        return Ok(Redirect::to(&state.url("/setup")).into_response());
    }
    if user.map(|u| u.is_admin()).unwrap_or(false) {
        return Ok(Redirect::to(&state.url("/admin")).into_response());
    }
    Ok(Html(state.render("login.html", context! { error => "" })?).into_response())
}

#[derive(Deserialize)]
pub struct LoginForm {
    email: String,
    password: String,
}

pub async fn login(
    State(state): State<AppState>,
    jar: CookieJar,
    Form(f): Form<LoginForm>,
) -> AppResult<Response> {
    match state.users.authenticate(&f.email, &f.password).await? {
        Some(user) if user.is_admin() => {
            state
                .audit
                .record(
                    Some(user.id),
                    "auth.login",
                    "user",
                    Some(&user.uuid),
                    None,
                    None,
                )
                .await?;
            Ok((
                jar.add(auth::session_cookie(&state, user.id)),
                Redirect::to(&state.url("/admin")),
            )
                .into_response())
        }
        _ => {
            state
                .audit
                .record(
                    None,
                    "auth.login_failed",
                    "user",
                    Some(&f.email),
                    None,
                    None,
                )
                .await?;
            Ok(Html(state.render(
                "login.html",
                context! { error => "Email or password is incorrect." },
            )?)
            .into_response())
        }
    }
}

pub async fn logout(
    State(state): State<AppState>,
    admin: AdminUser,
    jar: CookieJar,
) -> AppResult<Response> {
    state
        .audit
        .record(
            Some(admin.user.id),
            "auth.logout",
            "user",
            Some(&admin.user.uuid),
            None,
            None,
        )
        .await?;
    Ok((
        jar.add(auth::clear_cookie(&state)),
        Redirect::to(&state.url("/admin/login")),
    )
        .into_response())
}

pub async fn dashboard(State(state): State<AppState>, admin: AdminUser) -> AppResult<Response> {
    let count = |sql: &'static str| {
        let pool = state.db.pool.clone();
        async move { sqlx::query_scalar::<_, i64>(sql).fetch_one(&pool).await }
    };
    let products = count("SELECT COUNT(*) FROM products").await?;
    let media = count("SELECT COUNT(*) FROM media").await?;
    let customers = count("SELECT COUNT(*) FROM users WHERE role = 'customer'").await?;
    let bridges = count("SELECT COUNT(*) FROM bridge_sites WHERE status = 'active'").await?;
    let recent = state.audit.recent(10).await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("dashboard.html", context! {
        user => admin.user, csrf => admin.csrf, site_name, version => mms_core::version(),
        products, media, customers, bridges,
        recent => recent.iter().map(|(t, a, s, id)| context!{ at => t, action => a, subject => s, id => id }).collect::<Vec<_>>(),
        active => "dashboard",
    })?).into_response())
}

pub async fn settings_form(State(state): State<AppState>, admin: AdminUser) -> AppResult<Response> {
    render_settings(&state, &admin, "", "").await
}

async fn render_settings(
    state: &AppState,
    admin: &AdminUser,
    notice: &str,
    error: &str,
) -> AppResult<Response> {
    let values = state.settings.display_values().await?;
    let sections: Vec<_> = mms_core::settings::SECTIONS
        .iter()
        .map(|(id, label)| {
            let fields: Vec<_> = values
                .iter()
                .filter(|(d, _)| d.section == *id)
                .map(|(d, v)| context! { key => d.key, label => d.label, kind => d.kind, value => v, help => d.help, options => d.options })
                .collect();
            context! { id, label, fields }
        })
        .collect();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("settings.html", context! { user => admin.user, csrf => admin.csrf, site_name, sections, notice, error, active => "settings" })?).into_response())
}

pub async fn settings_save(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(fields): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(fields.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    for def in mms_core::settings::DEFINITIONS {
        let Some(raw) = fields.get(def.key) else {
            continue;
        };
        // A masked secret left untouched must not overwrite the stored value.
        if def.kind == mms_core::settings::Kind::Secret && (raw.is_empty() || raw.contains('•')) {
            continue;
        }
        if let Err(e) = state.settings.set(def.key, raw).await {
            return render_settings(&state, &admin, "", &e.to_string()).await;
        }
    }
    state
        .audit
        .record(
            Some(admin.user.id),
            "settings.saved",
            "settings",
            None,
            None,
            None,
        )
        .await?;
    render_settings(&state, &admin, "Settings saved.", "").await
}

pub async fn health(State(state): State<AppState>, admin: AdminUser) -> AppResult<Response> {
    let report = mms_core::health::run(&state.config, &state.db).await;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render(
        "health.html",
        context! { user => admin.user, csrf => admin.csrf, site_name, report, active => "health" },
    )?)
    .into_response())
}
