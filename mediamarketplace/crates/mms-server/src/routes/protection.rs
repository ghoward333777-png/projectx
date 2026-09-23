//! Image protection, forensic watermarking and copyright tooling.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use crate::routes::customers::CsrfOnly;
use axum::extract::{Multipart, Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use mms_core::copyright::{search_link, Owner, SERVICES};
use mms_core::media::Media;
use mms_core::protection::{self, Corner};
use mms_core::users::User;
use serde::Deserialize;
use std::collections::HashMap;
use std::path::PathBuf;

/// Settings the delivery path needs, read once per request.
pub struct Levels {
    pub image: i64,
    pub video: i64,
    pub stamp_text: String,
    pub corner: Corner,
    pub stamp_opacity: f32,
    pub grid_opacity: f32,
}

pub async fn levels(state: &AppState) -> AppResult<Levels> {
    Ok(Levels {
        image: state
            .settings
            .get("protection.image_level")
            .await?
            .parse()
            .unwrap_or(2),
        video: state
            .settings
            .get("protection.video_level")
            .await?
            .parse()
            .unwrap_or(1),
        stamp_text: state.settings.get("protection.stamp_text").await?,
        corner: Corner::parse(&state.settings.get("protection.stamp_position").await?),
        stamp_opacity: state
            .settings
            .get("protection.stamp_opacity")
            .await?
            .parse::<f32>()
            .unwrap_or(45.0)
            / 100.0,
        grid_opacity: state
            .settings
            .get("protection.grid_opacity")
            .await?
            .parse::<f32>()
            .unwrap_or(30.0)
            / 100.0,
    })
}

fn marked_dir(state: &AppState, media_uuid: &str) -> PathBuf {
    state
        .config
        .data_dir
        .join("media")
        .join("marked")
        .join(media_uuid)
}

pub fn stamp_for(template: &str, user: &User, site: &str, session: &str) -> String {
    template
        .replace("{email}", &user.email)
        .replace("{name}", &user.name)
        .replace("{site}", site)
        .replace("{date}", &mms_core::now()[..10])
        .replace("{session}", &session[..8.min(session.len())])
}

/// The per-viewer copy of an image: visible stamp plus the invisible session code,
/// written once as PNG and reused. Returns the path.
pub async fn marked_image(
    state: &AppState,
    m: &Media,
    user: &User,
    ip: &str,
    ua: &str,
) -> AppResult<PathBuf> {
    let lv = levels(state).await?;
    let session = state
        .protection
        .session_for(user.id, m.id, None, 2, "image", ip, ua)
        .await?;
    let dir = marked_dir(state, &m.uuid);
    let path = dir.join(format!("{}.png", user.id));
    if tokio::fs::metadata(&path).await.is_ok() {
        return Ok(path);
    }
    tokio::fs::create_dir_all(&dir).await?;
    let site = state.settings.get("general.site_name").await?;
    let text = stamp_for(&lv.stamp_text, user, &site, &session.uuid);
    let src = state.media.original_path(m);
    let code = session.code as u32;
    let corner = lv.corner;
    let opacity = lv.stamp_opacity;
    let out = path.clone();
    tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
        let data = std::fs::read(&src)?;
        let mut img = image::load_from_memory(&data)?;
        if !text.trim().is_empty() {
            protection::stamp_text(&mut img, &text, corner, opacity);
        }
        protection::embed_lsb(&mut img, code);
        img.save_with_format(&out, image::ImageFormat::Png)?;
        Ok(())
    })
    .await??;
    Ok(path)
}

/// Where the per-viewer video copy lives (produced by the `video.mark` job).
pub fn marked_video_path(state: &AppState, m: &Media, user_id: i64) -> PathBuf {
    marked_dir(state, &m.uuid).join(format!("{user_id}.mp4"))
}

/// Ensures a marked video copy exists or is being made. Returns true when ready.
pub async fn ensure_marked_video(
    state: &AppState,
    m: &Media,
    user: &User,
    product_id: Option<i64>,
    ip: &str,
    ua: &str,
) -> AppResult<bool> {
    let path = marked_video_path(state, m, user.id);
    if tokio::fs::metadata(&path).await.is_ok() {
        return Ok(true);
    }
    let session = state
        .protection
        .session_for(user.id, m.id, product_id, 2, "video", ip, ua)
        .await?;
    let pending: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM jobs WHERE type = 'video.mark' AND status IN ('queued','running') AND args LIKE ?")
        .bind(format!("%\"session\":\"{}\"%", session.uuid)).fetch_one(&state.db.pool).await?;
    if pending == 0 {
        state
            .jobs
            .enqueue("video.mark", serde_json::json!({ "session": session.uuid }))
            .await?;
    }
    Ok(false)
}

/// The `video.mark` job: ffmpeg burns the session grid into a per-viewer copy.
pub async fn mark_video_job(state: &AppState, session_uuid: &str) -> anyhow::Result<()> {
    let Some(s) = state.protection.by_uuid(session_uuid).await? else {
        return Ok(());
    };
    let (Some(mid), Some(uid)) = (s.media_id, s.user_id) else {
        return Ok(());
    };
    let Some(m) = state.media.by_id(mid).await? else {
        return Ok(());
    };
    let out = marked_video_path(state, &m, uid);
    if tokio::fs::metadata(&out).await.is_ok() {
        return Ok(());
    }
    tokio::fs::create_dir_all(out.parent().unwrap()).await?;
    let lv = levels(state).await.map_err(|e| e.0)?;
    let (w, h) = (
        m.width.unwrap_or(1280) as u32,
        m.height.unwrap_or(720) as u32,
    );
    let filter = protection::ffmpeg_grid_filter(w, h, s.code as u32, lv.grid_opacity);
    let tmp = out.with_extension("part.mp4");
    let status = tokio::process::Command::new(&state.config.media.ffmpeg_path)
        .args(["-y", "-loglevel", "error", "-i"])
        .arg(state.media.original_path(&m))
        .args([
            "-vf",
            &filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
        ])
        .arg(&tmp)
        .status()
        .await;
    match status {
        Ok(st) if st.success() => {
            tokio::fs::rename(&tmp, &out).await?;
            Ok(())
        }
        Ok(st) => anyhow::bail!("ffmpeg exited with {st}"),
        Err(e) => anyhow::bail!("ffmpeg not available: {e}"),
    }
}

// ----- admin -----

#[derive(Deserialize)]
pub struct PageQuery {
    #[serde(default)]
    notice: String,
    #[serde(default)]
    error: String,
    #[serde(default)]
    status: String,
}

pub async fn dashboard(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<PageQuery>,
) -> AppResult<Response> {
    let lv = levels(&state).await?;
    let sessions = state.protection.recent(30).await?;
    let mut rows = Vec::new();
    for s in sessions {
        let email: Option<String> = match s.user_id {
            Some(u) => {
                sqlx::query_scalar("SELECT email FROM users WHERE id = ?")
                    .bind(u)
                    .fetch_optional(&state.db.pool)
                    .await?
            }
            None => None,
        };
        let media: Option<String> = match s.media_id {
            Some(m) => state
                .media
                .by_id(m)
                .await?
                .map(|m| m.title.unwrap_or(m.original_path)),
            None => None,
        };
        rows.push(context! { s, email, media });
    }
    let counts = state.copyright.counts().await?;
    let (sessions_total,): (i64,) = sqlx::query_as("SELECT COUNT(*) FROM mark_sessions")
        .fetch_one(&state.db.pool)
        .await?;
    let ffmpeg_ok = tokio::process::Command::new(&state.config.media.ffmpeg_path)
        .arg("-version")
        .output()
        .await
        .map(|o| o.status.success())
        .unwrap_or(false);
    let mut services = Vec::new();
    for sv in SERVICES {
        let configured = if sv.mode == "link" {
            true
        } else {
            !state
                .settings
                .get(sv.setting)
                .await
                .unwrap_or_default()
                .trim()
                .is_empty()
        };
        services.push(context! { sv, configured });
    }
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("protection.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "protection", image_level => lv.image, video_level => lv.video, rows, counts, sessions_total, ffmpeg_ok, services, notice => q.notice, error => q.error })?).into_response())
}

/// Upload a suspected leak; the store says which viewer it was issued to.
pub async fn identify(
    State(state): State<AppState>,
    admin: AdminUser,
    mut multipart: Multipart,
) -> AppResult<Response> {
    let mut csrf = String::new();
    let mut file: Vec<u8> = Vec::new();
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| anyhow::anyhow!(e))?
    {
        match field.name().unwrap_or("") {
            "_csrf" => csrf = field.text().await.unwrap_or_default(),
            "file" => {
                file = field
                    .bytes()
                    .await
                    .map_err(|e| anyhow::anyhow!(e))?
                    .to_vec()
            }
            _ => {}
        }
    }
    if let Some(r) = admin.csrf_error(&csrf) {
        return Ok(r);
    }
    if file.is_empty() {
        return Ok(
            Redirect::to(&state.url("/admin/protection?error=Choose+an+image+file+first"))
                .into_response(),
        );
    }
    let msg = match state.protection.identify(&file).await {
        Ok(Some((s, how))) => {
            let email: Option<String> = match s.user_id {
                Some(u) => sqlx::query_scalar("SELECT email FROM users WHERE id = ?").bind(u).fetch_optional(&state.db.pool).await?,
                None => None,
            };
            state.audit.record(Some(admin.user.id), "protection.identified", "mark_session", Some(&s.uuid), None, Some(serde_json::json!({ "how": how }))).await?;
            format!("notice=Identified+by+{}:+session+{}+issued+to+{}+on+{}", how.replace(' ', "+"), &s.uuid[..8], email.unwrap_or_else(|| "unknown".into()).replace('@', "%40"), &s.created_at[..10])
        }
        Ok(None) => "error=No+mark+found.+Marks+survive+lossless+copies+and+full-frame+screenshots,+not+heavy+re-encoding.".to_string(),
        Err(e) => format!("error={}", crate::routes::media::urlencoding(&e.to_string())),
    };
    Ok(Redirect::to(&state.url(&format!("/admin/protection?{msg}"))).into_response())
}

// ----- scans -----

pub async fn scans(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<HashMap<String, String>>,
) -> AppResult<Response> {
    let (media, _) = state
        .media
        .list(&mms_core::media::MediaQuery {
            per_page: 200,
            page: 1,
            ..Default::default()
        })
        .await?;
    let selected = q.get("media").cloned().unwrap_or_default();
    let public = state.config.server.public_url.trim_end_matches('/');
    let mut links = Vec::new();
    let mut chosen: Option<Media> = None;
    if !selected.is_empty() {
        if let Some(m) = state.media.by_uuid(&selected).await? {
            let url = if m.private == 1 {
                m.thumbnail_path
                    .as_ref()
                    .map(|t| format!("{public}/media/{t}"))
            } else {
                Some(format!("{public}/media/{}", m.original_path))
            };
            for sv in SERVICES {
                let link = url.as_deref().and_then(|u| search_link(sv.slug, u));
                let configured = sv.mode == "link"
                    || !state
                        .settings
                        .get(sv.setting)
                        .await
                        .unwrap_or_default()
                        .trim()
                        .is_empty();
                links.push(context! { sv, link, configured });
            }
            chosen = Some(m);
        }
    }
    let history = state
        .copyright
        .scans(chosen.as_ref().map(|m| m.id), 50)
        .await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("protection_scans.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "protection", media, selected, chosen, links, history, notice => q.get("notice").cloned().unwrap_or_default() })?).into_response())
}

/// Records that a link-mode search was opened (so the history shows what was checked).
pub async fn record_scan(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let media = f.get("media").cloned().unwrap_or_default();
    let service = f.get("service").cloned().unwrap_or_default();
    if let Some(m) = state.media.by_uuid(&media).await? {
        let matches: i64 = f.get("matches").and_then(|v| v.parse().ok()).unwrap_or(0);
        state
            .copyright
            .record_scan(
                m.id,
                &service,
                "link",
                "manual",
                f.get("result").map(String::as_str),
                matches,
            )
            .await?;
    }
    Ok(Redirect::to(&state.url(&format!(
        "/admin/protection/scans?media={media}&notice=Scan+recorded."
    )))
    .into_response())
}

// ----- violations -----

pub async fn violations(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<PageQuery>,
) -> AppResult<Response> {
    let list = state.copyright.list(&q.status).await?;
    let mut rows = Vec::new();
    for v in list {
        let media = match v.media_id {
            Some(m) => state
                .media
                .by_id(m)
                .await?
                .map(|m| m.title.unwrap_or(m.original_path)),
            None => None,
        };
        rows.push(context! { v, media });
    }
    let (media, _) = state
        .media
        .list(&mms_core::media::MediaQuery {
            per_page: 200,
            page: 1,
            ..Default::default()
        })
        .await?;
    let counts = state.copyright.counts().await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("violations.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "protection", rows, media, counts, status => q.status, notice => q.notice, error => q.error })?).into_response())
}

pub async fn report_violation(
    State(state): State<AppState>,
    admin: AdminUser,
    mut multipart: Multipart,
) -> AppResult<Response> {
    let mut f: HashMap<String, String> = HashMap::new();
    let mut evidence: Vec<u8> = Vec::new();
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| anyhow::anyhow!(e))?
    {
        let name = field.name().unwrap_or("").to_string();
        if name == "evidence" {
            evidence = field
                .bytes()
                .await
                .map_err(|e| anyhow::anyhow!(e))?
                .to_vec();
        } else {
            f.insert(name, field.text().await.unwrap_or_default());
        }
    }
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let media_id = match f.get("media").filter(|m| !m.is_empty()) {
        Some(u) => state.media.by_uuid(u).await?.map(|m| m.id),
        None => None,
    };
    // If the evidence is a marked image, tie the violation to the viewer it was issued to.
    let mark = if evidence.is_empty() {
        None
    } else {
        state
            .protection
            .identify(&evidence)
            .await
            .ok()
            .flatten()
            .map(|(s, _)| s.id)
    };
    match state
        .copyright
        .report(
            f.get("url").map(String::as_str).unwrap_or(""),
            media_id,
            None,
            "manual",
            f.get("note").map(String::as_str).unwrap_or(""),
            (!evidence.is_empty()).then_some(evidence.as_slice()),
            mark,
        )
        .await
    {
        Ok(v) => {
            if !evidence.is_empty() {
                let dir = state.config.data_dir.join("evidence");
                tokio::fs::create_dir_all(&dir).await?;
                tokio::fs::write(dir.join(format!("{}.bin", v.uuid)), &evidence).await?;
            }
            state
                .audit
                .record(
                    Some(admin.user.id),
                    "violation.reported",
                    "violation",
                    Some(&v.uuid),
                    None,
                    Some(serde_json::json!({ "url": v.url, "mark_session": mark })),
                )
                .await?;
            Ok(Redirect::to(&state.url(&format!("/admin/protection/violations/{}?notice=Violation+recorded.{}", v.uuid, if mark.is_some() { "+The+evidence+carries+a+forensic+mark+and+is+linked+to+the+viewer+it+was+issued+to." } else { "" }))).into_response())
        }
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/protection/violations?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn violation(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Query(q): Query<PageQuery>,
) -> AppResult<Response> {
    let Some(v) = state.copyright.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let events = state.copyright.events(v.id).await?;
    let media = match v.media_id {
        Some(m) => state.media.by_id(m).await?,
        None => None,
    };
    let session = match v.mark_session {
        Some(id) => sqlx::query_as::<_, mms_core::protection::MarkSession>("SELECT id, code, uuid, user_id, media_id, product_id, level, kind, ip, user_agent, created_at FROM mark_sessions WHERE id = ?").bind(id).fetch_optional(&state.db.pool).await?,
        None => None,
    };
    let viewer: Option<String> = match session.as_ref().and_then(|s| s.user_id) {
        Some(u) => {
            sqlx::query_scalar("SELECT email FROM users WHERE id = ?")
                .bind(u)
                .fetch_optional(&state.db.pool)
                .await?
        }
        None => None,
    };
    let has_notice = state.copyright.notice_pdf(v.id).await?.is_some();
    let owner_ready = !state
        .settings
        .get("copyright.owner_name")
        .await?
        .trim()
        .is_empty();
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render("violation.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "protection", v, events, media, session, viewer, has_notice, owner_ready, notice => q.notice, error => q.error })?).into_response())
}

pub async fn violation_status(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(v) = state.copyright.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    match state
        .copyright
        .set_status(
            v.id,
            f.get("status").map(String::as_str).unwrap_or(""),
            f.get("note").map(String::as_str).unwrap_or(""),
        )
        .await
    {
        Ok(()) => Ok(Redirect::to(&state.url(&format!(
            "/admin/protection/violations/{uuid}?notice=Updated."
        )))
        .into_response()),
        Err(e) => Ok(Redirect::to(&state.url(&format!(
            "/admin/protection/violations/{uuid}?error={}",
            crate::routes::media::urlencoding(&e.to_string())
        )))
        .into_response()),
    }
}

pub async fn generate_notice(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(v) = state.copyright.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let owner = Owner {
        name: state.settings.get("copyright.owner_name").await?,
        company: state.settings.get("copyright.owner_company").await?,
        email: state.settings.get("copyright.owner_email").await?,
        address: state.settings.get("copyright.owner_address").await?,
        site_name: state.settings.get("general.site_name").await?,
        store_url: state.config.server.public_url.clone(),
    };
    if owner.name.trim().is_empty() || owner.email.trim().is_empty() {
        return Ok(Redirect::to(&state.url(&format!("/admin/protection/violations/{uuid}?error=Enter+the+rights+owner+name+and+email+under+Settings+%E2%86%92+Copyright+services+first"))).into_response());
    }
    let m = match v.media_id {
        Some(id) => state.media.by_id(id).await?,
        None => None,
    };
    let title = m
        .as_ref()
        .and_then(|m| m.title.clone())
        .unwrap_or_else(|| "the work".into());
    let product: Option<String> = match v.media_id {
        Some(id) => {
            sqlx::query_scalar("SELECT slug FROM products WHERE media_id = ? LIMIT 1")
                .bind(id)
                .fetch_optional(&state.db.pool)
                .await?
        }
        None => None,
    };
    let original = match product {
        Some(slug) => format!(
            "{}/embed/product/{slug}",
            state.config.server.public_url.trim_end_matches('/')
        ),
        None => state.config.server.public_url.clone(),
    };
    state
        .copyright
        .generate_notice(v.id, &owner, &title, &original)
        .await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "violation.notice_generated",
            "violation",
            Some(&v.uuid),
            None,
            None,
        )
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/protection/violations/{uuid}?notice=Notice+generated.+Download+it+below+and+send+it+to+the+host%27s+abuse+address."))).into_response())
}

pub async fn notice_pdf(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(v) = state.copyright.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    match state.copyright.notice_pdf(v.id).await? {
        Some(pdf) => Ok((
            [
                (header::CONTENT_TYPE, "application/pdf".to_string()),
                (
                    header::CONTENT_DISPOSITION,
                    format!("attachment; filename=\"dmca-notice-{}.pdf\"", v.host),
                ),
            ],
            pdf,
        )
            .into_response()),
        None => Ok(StatusCode::NOT_FOUND.into_response()),
    }
}

pub async fn evidence(
    State(state): State<AppState>,
    _admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let path = state
        .config
        .data_dir
        .join("evidence")
        .join(format!("{uuid}.bin"));
    match tokio::fs::read(&path).await {
        Ok(bytes) => {
            let mime = infer::get(&bytes)
                .map(|t| t.mime_type())
                .unwrap_or("application/octet-stream");
            Ok(([(header::CONTENT_TYPE, mime.to_string())], bytes).into_response())
        }
        Err(_) => Ok(StatusCode::NOT_FOUND.into_response()),
    }
}

/// Client details for session records.
pub fn client(headers: &HeaderMap) -> (String, String) {
    (
        crate::routes::shop::client_ip(headers),
        crate::routes::shop::user_agent(headers),
    )
}
