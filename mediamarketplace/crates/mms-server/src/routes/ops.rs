//! Hardening: email helpers, privacy (export and erase), backups, roles.

use crate::app::AppState;
use crate::auth::{AdminUser, MaybeUser};
use crate::errors::AppResult;
use crate::routes::customers::CsrfOnly;
use axum::extract::{Path, Query, State};
use axum::http::{header, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use mms_core::mail::{Outgoing, Smtp};
use std::collections::HashMap;

pub async fn smtp(state: &AppState) -> AppResult<Smtp> {
    Ok(Smtp {
        host: state.settings.get("mail.smtp_host").await?,
        port: state
            .settings
            .get("mail.smtp_port")
            .await?
            .parse()
            .unwrap_or(587),
        username: state.settings.get("mail.smtp_user").await?,
        password: state.settings.get("mail.smtp_password").await?,
        from: state.settings.get("mail.from").await?,
        tls: state.settings.get("mail.tls").await?,
    })
}

/// Sends when SMTP is configured; never fails the caller.
pub async fn send_quietly(
    state: &AppState,
    to: &str,
    subject: &str,
    text: &str,
    html: Option<&str>,
    attachment: Option<(&str, &[u8], &str)>,
    kind: &str,
) {
    let Ok(cfg) = smtp(state).await else { return };
    if !cfg.configured() {
        return;
    }
    if let Err(e) = state
        .mailer
        .send(
            &cfg,
            Outgoing {
                to,
                subject,
                text,
                html,
                attachment,
                kind,
            },
        )
        .await
    {
        tracing::warn!(to, kind, error = %e, "email not sent");
    }
}

/// Email the receipt for a paid order.
pub async fn email_receipt(state: &AppState, order: &mms_core::commerce::Order) -> AppResult<()> {
    let Some((number, html, pdf)) = state.commerce.receipt(order.id).await? else {
        return Ok(());
    };
    let (email,): (String,) = sqlx::query_as("SELECT email FROM users WHERE id = ?")
        .bind(order.user_id)
        .fetch_one(&state.db.pool)
        .await?;
    let site = state.settings.get("general.site_name").await?;
    let text = format!("Thank you for your order {} at {site}. Your receipt {number} is attached. Everything you bought is under My media: {}/account", order.number, state.config.server.public_url.trim_end_matches('/'));
    send_quietly(
        state,
        &email,
        &format!("Receipt {number} from {site}"),
        &text,
        Some(&html),
        Some((&format!("{number}.pdf"), &pdf, "application/pdf")),
        "receipt",
    )
    .await;
    Ok(())
}

pub async fn test_mail(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let cfg = smtp(&state).await?;
    if !cfg.configured() {
        return Ok(Redirect::to(&state.url("/admin/integrations?error=Enter+the+SMTP+host+and+From+address+under+Settings+%E2%86%92+Email+first")).into_response());
    }
    let site = state.settings.get("general.site_name").await?;
    match state
        .mailer
        .send(
            &cfg,
            Outgoing {
                to: &admin.user.email,
                subject: &format!("Test email from {site}"),
                text: "If you can read this, the store can send email.",
                html: None,
                attachment: None,
                kind: "test",
            },
        )
        .await
    {
        Ok(_) => Ok(
            Redirect::to(&state.url("/admin/integrations?notice=Test+email+sent.")).into_response(),
        ),
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/integrations?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

// ----- privacy -----

pub async fn my_export(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Faccount%2Fprivacy")).into_response());
    };
    let data = state.privacy.export(user.id).await?;
    state
        .audit
        .record(
            Some(user.id),
            "privacy.exported",
            "user",
            Some(&user.uuid),
            None,
            None,
        )
        .await?;
    Ok((
        [
            (
                header::CONTENT_TYPE,
                "application/json; charset=utf-8".to_string(),
            ),
            (
                header::CONTENT_DISPOSITION,
                "attachment; filename=\"my-data.json\"".to_string(),
            ),
        ],
        serde_json::to_string_pretty(&data)?,
    )
        .into_response())
}

pub async fn privacy_page(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login?return=%2Faccount%2Fprivacy")).into_response());
    };
    let csrf = token
        .as_deref()
        .map(|t| crate::auth::csrf_token(&state, t))
        .unwrap_or_default();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("account_privacy.html", context! { user, site_name, csrf, tab => "privacy", error => q.get("error").cloned().unwrap_or_default() })?).into_response())
}

pub async fn my_erase(
    State(state): State<AppState>,
    MaybeUser(user, token): MaybeUser,
    jar: axum_extra::extract::CookieJar,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    let Some(user) = user else {
        return Ok(Redirect::to(&state.url("/login")).into_response());
    };
    if f.get("_csrf").map(String::as_str)
        != Some(
            token
                .as_deref()
                .map(|t| crate::auth::csrf_token(&state, t))
                .unwrap_or_default()
                .as_str(),
        )
    {
        return Ok((StatusCode::FORBIDDEN, "Invalid form token").into_response());
    }
    if f.get("confirm").map(String::as_str) != Some("DELETE") {
        return Ok(
            Redirect::to(&state.url("/account/privacy?error=Type+DELETE+to+confirm"))
                .into_response(),
        );
    }
    match state.privacy.erase(user.id).await {
        Ok(()) => {
            state
                .audit
                .record(
                    Some(user.id),
                    "privacy.erased",
                    "user",
                    Some(&user.uuid),
                    None,
                    None,
                )
                .await?;
            Ok((
                jar.remove(crate::auth::clear_cookie(&state)),
                Redirect::to(&state.url("/login?return=%2F")),
            )
                .into_response())
        }
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/account/privacy?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn admin_export(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(uid) = sqlx::query_scalar::<_, i64>("SELECT id FROM users WHERE uuid = ?")
        .bind(&uuid)
        .fetch_optional(&state.db.pool)
        .await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let data = state.privacy.export(uid).await?;
    Ok((
        [
            (
                header::CONTENT_TYPE,
                "application/json; charset=utf-8".to_string(),
            ),
            (
                header::CONTENT_DISPOSITION,
                format!("attachment; filename=\"customer-{uuid}.json\""),
            ),
        ],
        serde_json::to_string_pretty(&data)?,
    )
        .into_response())
}

pub async fn admin_erase(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(uid) = sqlx::query_scalar::<_, i64>("SELECT id FROM users WHERE uuid = ?")
        .bind(&uuid)
        .fetch_optional(&state.db.pool)
        .await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    match state.privacy.erase(uid).await {
        Ok(()) => {
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "privacy.erased",
                    "user",
                    Some(&uuid),
                    None,
                    None,
                )
                .await?;
            Ok(Redirect::to(&state.url(&format!("/admin/customers/{uuid}"))).into_response())
        }
        Err(e) => Ok((StatusCode::BAD_REQUEST, e.to_string()).into_response()),
    }
}

pub async fn set_role(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    if !admin.user.is_admin() {
        return Ok((StatusCode::FORBIDDEN, "Only administrators change roles").into_response());
    }
    let Some(uid) = sqlx::query_scalar::<_, i64>("SELECT id FROM users WHERE uuid = ?")
        .bind(&uuid)
        .fetch_optional(&state.db.pool)
        .await?
    else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let role = f.get("role").cloned().unwrap_or_default();
    if uid == admin.user.id && role != "admin" {
        return Ok((StatusCode::BAD_REQUEST, "You cannot demote yourself").into_response());
    }
    state.users.set_role(uid, &role).await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "user.role",
            "user",
            Some(&uuid),
            None,
            Some(serde_json::json!({ "role": role })),
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/customers/{uuid}"))).into_response())
}

// ----- backups -----

pub fn backup_dir(state: &AppState, setting: &str) -> std::path::PathBuf {
    if setting.trim().is_empty() {
        state.config.data_dir.join("backups")
    } else {
        std::path::PathBuf::from(setting.trim())
    }
}

pub async fn backups(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    if !admin.user.is_admin() {
        return Ok((StatusCode::FORBIDDEN, "Administrator access required").into_response());
    }
    let dir = backup_dir(&state, &state.settings.get("backup.dir").await?);
    let list = mms_core::backup::list(&dir).await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("backups.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "health", dir => dir.to_string_lossy(), list => list.iter().map(|(n, b)| context!{ name => n, size => b }).collect::<Vec<_>>(), notice => q.get("notice").cloned().unwrap_or_default(), error => q.get("error").cloned().unwrap_or_default() })?).into_response())
}

pub async fn create_backup(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    if !admin.user.is_admin() {
        return Ok((StatusCode::FORBIDDEN, "Administrator access required").into_response());
    }
    let dir = backup_dir(&state, &state.settings.get("backup.dir").await?);
    match mms_core::backup::create(&state.db.pool, &state.config.data_dir, &dir).await {
        Ok(p) => {
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "backup.created",
                    "backup",
                    p.file_name().and_then(|n| n.to_str()),
                    None,
                    None,
                )
                .await?;
            Ok(Redirect::to(&state.url("/admin/backups?notice=Backup+created.")).into_response())
        }
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/backups?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn download_backup(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(name): Path<String>,
) -> AppResult<Response> {
    if !admin.user.is_admin() {
        return Ok((StatusCode::FORBIDDEN, "Administrator access required").into_response());
    }
    if !name.starts_with("mms-backup-")
        || !name.ends_with(".tar.gz")
        || name.contains('/')
        || name.contains("..")
    {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }
    let dir = backup_dir(&state, &state.settings.get("backup.dir").await?);
    match tokio::fs::read(dir.join(&name)).await {
        Ok(bytes) => Ok((
            [
                (header::CONTENT_TYPE, "application/gzip".to_string()),
                (
                    header::CONTENT_DISPOSITION,
                    format!("attachment; filename=\"{name}\""),
                ),
            ],
            bytes,
        )
            .into_response()),
        Err(_) => Ok(StatusCode::NOT_FOUND.into_response()),
    }
}
