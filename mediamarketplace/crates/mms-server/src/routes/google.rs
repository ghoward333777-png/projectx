//! Google Business Profile: connection, locations, posts and reviews with AI drafts.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use crate::routes::customers::CsrfOnly;
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use serde::Deserialize;
use std::collections::HashMap;

async fn client(state: &AppState) -> AppResult<(String, String)> {
    Ok((
        state.settings.get("google.client_id").await?,
        state.settings.get("google.client_secret").await?,
    ))
}

fn redirect_uri(state: &AppState) -> String {
    format!(
        "{}/admin/google/callback",
        state.config.server.public_url.trim_end_matches('/')
    )
}

#[derive(Deserialize)]
pub struct PageQuery {
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
}

pub async fn page(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<PageQuery>,
) -> AppResult<Response> {
    let (id, secret) = client(&state).await?;
    let account = state.google.account().await?;
    let locations = state.google.locations().await?;
    let posts = state.google.posts().await?;
    let reviews = state.google.reviews().await?;
    let maps_key = state.settings.get("google.maps_api_key").await?;
    let ai_ready = !state
        .settings
        .get("ai.anthropic_api_key")
        .await?
        .trim()
        .is_empty();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("google.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "google", configured => !id.trim().is_empty() && !secret.trim().is_empty(), account, locations, posts, reviews, maps_key, ai_ready, redirect_uri => redirect_uri(&state), notice => q.notice, error => q.error })?).into_response())
}

pub async fn connect(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let (id, _) = client(&state).await?;
    if id.trim().is_empty() {
        return Ok(Redirect::to(
            &state.url("/admin/google?error=Enter+the+OAuth+client+under+Settings+first"),
        )
        .into_response());
    }
    // The CSRF token doubles as the OAuth state; only this session can complete the flow.
    Ok(Redirect::to(&mms_core::google::consent_url(
        id.trim(),
        &redirect_uri(&state),
        &admin.csrf,
    ))
    .into_response())
}

pub async fn callback(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    if q.get("state").map(String::as_str) != Some(admin.csrf.as_str()) {
        return Ok((StatusCode::FORBIDDEN, "OAuth state mismatch").into_response());
    }
    let Some(code) = q.get("code") else {
        return Ok(Redirect::to(&state.url(&format!(
                "/admin/google?error={}",
                crate::routes::media::urlencoding(
                    q.get("error")
                        .map(String::as_str)
                        .unwrap_or("Google returned no code")
                )
            )))
        .into_response());
    };
    let (id, secret) = client(&state).await?;
    match state
        .google
        .exchange_code(id.trim(), secret.trim(), &redirect_uri(&state), code)
        .await
    {
        Ok(()) => {
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "google.connected",
                    "google",
                    None,
                    None,
                    None,
                )
                .await?;
            Ok(Redirect::to(
                &state.url("/admin/google?notice=Google+connected.+Sync+to+load+your+locations."),
            )
            .into_response())
        }
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/google?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn disconnect(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.google.disconnect().await?;
    Ok(Redirect::to(&state.url("/admin/google?notice=Disconnected.")).into_response())
}

pub async fn sync(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let (id, secret) = client(&state).await?;
    let msg = match state.google.sync_locations(id.trim(), secret.trim()).await {
        Ok(n) => match state.google.sync_reviews(id.trim(), secret.trim()).await {
            Ok(r) => format!(
                "notice={}",
                crate::routes::media::urlencoding(&format!(
                    "{n} locations and {r} reviews synced."
                ))
            ),
            Err(e) => format!(
                "error={}",
                crate::routes::media::urlencoding(&e.to_string())
            ),
        },
        Err(e) => format!(
            "error={}",
            crate::routes::media::urlencoding(&e.to_string())
        ),
    };
    Ok(Redirect::to(&state.url(&format!("/admin/google?{msg}"))).into_response())
}

pub async fn create_post(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let g = |k: &str| f.get(k).cloned().unwrap_or_default();
    match state
        .google
        .create_post(
            &g("location"),
            &g("summary"),
            &g("cta_type"),
            &g("cta_url"),
            &g("media_url"),
            Some(&g("scheduled_at").replace(' ', "T")),
        )
        .await
    {
        Ok(p) => {
            if g("publish_now") == "1" {
                state.google.mark_scheduled_now(&p.uuid).await?;
                state
                    .jobs
                    .enqueue("google.posts", serde_json::json!({}))
                    .await?;
            }
            Ok(Redirect::to(&state.url("/admin/google?notice=Post+saved.")).into_response())
        }
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/google?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn publish_post(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.google.mark_scheduled_now(&uuid).await?;
    state
        .jobs
        .enqueue("google.posts", serde_json::json!({}))
        .await?;
    Ok(
        Redirect::to(&state.url("/admin/google?notice=Publishing+in+the+background."))
            .into_response(),
    )
}

pub async fn delete_post(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    state.google.delete_post(&uuid).await?;
    Ok(Redirect::to(&state.url("/admin/google?notice=Post+deleted.")).into_response())
}

pub async fn draft_reply(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let key = state.settings.get("ai.anthropic_api_key").await?;
    let model = state.settings.get("ai.model").await?;
    let site = state.settings.get("general.site_name").await?;
    let tone = state.settings.get("google.reply_tone").await?;
    match state
        .google
        .draft_reply(&key, &model, &site, &tone, id)
        .await
    {
        Ok(_) => Ok(Redirect::to(
            &state.url("/admin/google?notice=Draft+ready.+Edit+it+and+approve+to+post."),
        )
        .into_response()),
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/google?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn post_reply(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(id): Path<i64>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let text = f.get("reply").cloned().unwrap_or_default();
    if f.get("action").map(String::as_str) == Some("save") {
        state.google.save_draft(id, &text).await?;
        return Ok(Redirect::to(&state.url("/admin/google?notice=Draft+saved.")).into_response());
    }
    let (cid, secret) = client(&state).await?;
    match state
        .google
        .post_reply(cid.trim(), secret.trim(), id, &text)
        .await
    {
        Ok(()) => {
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "google.reply_posted",
                    "review",
                    Some(&id.to_string()),
                    None,
                    None,
                )
                .await?;
            Ok(Redirect::to(&state.url("/admin/google?notice=Reply+posted.")).into_response())
        }
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/google?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

/// Worker job: publish every due post.
pub async fn publish_due(state: &AppState) -> anyhow::Result<()> {
    let (id, secret) = client(state).await.map_err(|e| e.0)?;
    for p in state.google.due_posts().await? {
        if let Err(e) = state
            .google
            .publish_post(id.trim(), secret.trim(), &p)
            .await
        {
            tracing::warn!(post = %p.uuid, error = %e, "google post failed");
        }
    }
    Ok(())
}
