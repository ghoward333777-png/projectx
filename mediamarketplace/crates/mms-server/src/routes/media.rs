//! Media library admin, public thumbnails and signed file delivery.

use crate::app::AppState;
use crate::auth::{AdminUser, MaybeUser};
use crate::errors::AppResult;
use axum::body::Body;
use axum::extract::{Multipart, Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use mms_core::media::MediaQuery;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tokio::io::{AsyncReadExt, AsyncSeekExt};

#[derive(Deserialize)]
pub struct ListQuery {
    #[serde(default)]
    q: String,
    #[serde(default, rename = "type")]
    r#type: String,
    #[serde(default = "one")]
    page: i64,
    #[serde(default)]
    notice: String,
}

fn one() -> i64 {
    1
}

pub async fn list(
    State(state): State<AppState>,
    admin: AdminUser,
    Query(q): Query<ListQuery>,
) -> AppResult<Response> {
    let (items, total) = state
        .media
        .list(&MediaQuery {
            q: q.q.clone(),
            r#type: q.r#type.clone(),
            folder_id: None,
            page: q.page,
            per_page: 48,
        })
        .await?;
    let counts = state.media.counts_by_type().await?;
    let site_name = state.settings.get("general.site_name").await?;
    let pages = (total + 47) / 48;
    Ok(Html(state.render("media.html", context! {
        user => admin.user, csrf => admin.csrf, site_name, active => "media",
        items, total, page => q.page, pages, q => q.q, type_filter => q.r#type, notice => q.notice,
        counts => counts.iter().map(|(t, n)| context!{ t, n }).collect::<Vec<_>>(),
        max_mb => state.media.max_bytes() / 1024 / 1024,
    })?).into_response())
}

/// Multi-file upload from the library page (multipart, one part per file, plus _csrf and private).
pub async fn upload(
    State(state): State<AppState>,
    admin: AdminUser,
    mut form: Multipart,
) -> AppResult<Response> {
    let mut csrf_ok = false;
    let mut private = false;
    let mut files: Vec<(String, Vec<u8>)> = Vec::new();
    while let Some(field) = form.next_field().await? {
        match field.name().unwrap_or("") {
            "_csrf" => csrf_ok = admin.csrf_error(&field.text().await?).is_none(),
            "private" => private = field.text().await? == "1",
            // "files", "files[]" or "files[0]" (the PHP proxy re-indexes repeated fields)
            n if n.starts_with("files") => {
                let name = field.file_name().unwrap_or("upload").to_string();
                let data = field.bytes().await?;
                if !data.is_empty() {
                    files.push((name, data.to_vec()));
                }
            }
            _ => {}
        }
    }
    if !csrf_ok {
        return Ok((StatusCode::FORBIDDEN, "Invalid form token").into_response());
    }
    let mut stored = 0;
    let mut errors = Vec::new();
    for (name, data) in files {
        match state
            .media
            .store_upload(&name, &data, private, Some(admin.user.id))
            .await
        {
            Ok(m) => {
                stored += 1;
                state
                    .jobs
                    .enqueue("thumbnail", serde_json::json!({ "media": m.id }))
                    .await?;
                state
                    .audit
                    .record(
                        Some(admin.user.id),
                        "media.uploaded",
                        "media",
                        Some(&m.uuid),
                        None,
                        Some(serde_json::json!({ "name": name, "bytes": m.bytes })),
                    )
                    .await?;
            }
            Err(e) => errors.push(format!("{name}: {e}")),
        }
    }
    let notice = if errors.is_empty() {
        format!("{stored} file(s) uploaded; thumbnails are being generated.")
    } else {
        format!("{stored} uploaded. Problems: {}", errors.join(" · "))
    };
    Ok(
        Redirect::to(&state.url(&format!("/admin/media?notice={}", urlencoding(&notice))))
            .into_response(),
    )
}

pub async fn detail(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
) -> AppResult<Response> {
    let Some(m) = state.media.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let site_name = state.settings.get("general.site_name").await?;
    let signed = state.url(&format!(
        "/m/{}",
        file_token(&state, &m.uuid, Some(admin.user.id), 3600)
    ));
    Ok(Html(state.render("media_detail.html", context! { user => admin.user, csrf => admin.csrf, site_name, active => "media", m, signed_url => signed })?).into_response())
}

pub async fn update(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<HashMap<String, String>>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(f.get("_csrf").map(String::as_str).unwrap_or("")) {
        return Ok(r);
    }
    let Some(m) = state.media.by_uuid(&uuid).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let g = |k: &str| f.get(k).cloned().unwrap_or_default();
    state
        .media
        .update_meta(m.id, &g("title"), &g("alt"), &g("caption"), &g("tags"))
        .await?;
    Ok(Redirect::to(&state.url(&format!("/admin/media/{uuid}"))).into_response())
}

#[derive(Deserialize)]
pub struct CsrfOnly {
    _csrf: String,
}

pub async fn delete(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    if let Some(m) = state.media.by_uuid(&uuid).await? {
        state.media.delete(m.id).await?;
        state
            .audit
            .record(
                Some(admin.user.id),
                "media.deleted",
                "media",
                Some(&uuid),
                None,
                None,
            )
            .await?;
    }
    Ok(Redirect::to(&state.url("/admin/media?notice=Deleted.")).into_response())
}

pub async fn rethumb(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<CsrfOnly>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    if let Some(m) = state.media.by_uuid(&uuid).await? {
        state
            .jobs
            .enqueue("thumbnail", serde_json::json!({ "media": m.id }))
            .await?;
    }
    Ok(Redirect::to(&state.url(&format!("/admin/media/{uuid}"))).into_response())
}

/// Public files: thumbnails and public originals under the public media root.
pub async fn public_file(
    State(state): State<AppState>,
    Path(path): Path<String>,
    headers: HeaderMap,
) -> AppResult<Response> {
    if path.contains("..") || path.starts_with('/') {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }
    let abs = state.media.public_root().join(&path);
    serve_file(&abs, &headers, "public, max-age=86400").await
}

#[derive(Serialize, Deserialize)]
struct FileClaims {
    m: String,
    u: i64,
    exp: i64,
}

/// Signed, expiring URL for a media original (public or private).
pub fn file_token(state: &AppState, media_uuid: &str, user_id: Option<i64>, ttl: i64) -> String {
    state.signer.sign(&FileClaims {
        m: media_uuid.to_string(),
        u: user_id.unwrap_or(0),
        exp: chrono::Utc::now().timestamp() + ttl,
    })
}

pub async fn signed_file(
    State(state): State<AppState>,
    MaybeUser(user, _): MaybeUser,
    Path(token): Path<String>,
    headers: HeaderMap,
) -> AppResult<Response> {
    let Ok(claims) = state
        .signer
        .verify::<FileClaims>(&token, chrono::Utc::now().timestamp())
    else {
        return Ok((StatusCode::FORBIDDEN, "This link has expired").into_response());
    };
    // A token issued to a user is only valid for that user's session.
    if claims.u != 0 && user.as_ref().map(|u| u.id) != Some(claims.u) {
        return Ok((StatusCode::FORBIDDEN, "Sign in to open this file").into_response());
    }
    let Some(m) = state.media.by_uuid(&claims.m).await? else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    let mut res = serve_file(
        &state.media.original_path(&m),
        &headers,
        "private, no-store",
    )
    .await?;
    res.headers_mut().insert(
        header::CONTENT_TYPE,
        m.mime
            .parse()
            .unwrap_or(header::HeaderValue::from_static("application/octet-stream")),
    );
    Ok(res)
}

/// Streams a file with single-range support (needed for video and audio seeking).
async fn serve_file(
    abs: &std::path::Path,
    headers: &HeaderMap,
    cache: &'static str,
) -> AppResult<Response> {
    let Ok(meta) = tokio::fs::metadata(abs).await else {
        return Ok(StatusCode::NOT_FOUND.into_response());
    };
    if !meta.is_file() {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }
    let len = meta.len();
    let mime = mime_guess::from_path(abs)
        .first_or_octet_stream()
        .to_string();
    let mut file = tokio::fs::File::open(abs).await?;
    let range = headers
        .get(header::RANGE)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| parse_range(v, len));
    let (status, start, end) = match range {
        Some((s, e)) => (StatusCode::PARTIAL_CONTENT, s, e),
        None => (StatusCode::OK, 0, len.saturating_sub(1)),
    };
    if len == 0 {
        return Ok((status, [(header::CONTENT_TYPE, mime)], Body::empty()).into_response());
    }
    file.seek(std::io::SeekFrom::Start(start)).await?;
    let take = file.take(end - start + 1);
    let body = Body::from_stream(tokio_util::io::ReaderStream::new(take));
    let mut res = (status, body).into_response();
    let h = res.headers_mut();
    h.insert(header::CONTENT_TYPE, mime.parse().unwrap());
    h.insert(
        header::ACCEPT_RANGES,
        header::HeaderValue::from_static("bytes"),
    );
    h.insert(
        header::CONTENT_LENGTH,
        (end - start + 1).to_string().parse().unwrap(),
    );
    h.insert(
        header::CACHE_CONTROL,
        header::HeaderValue::from_static(cache),
    );
    if status == StatusCode::PARTIAL_CONTENT {
        h.insert(
            header::CONTENT_RANGE,
            format!("bytes {start}-{end}/{len}").parse().unwrap(),
        );
    }
    Ok(res)
}

fn parse_range(v: &str, len: u64) -> Option<(u64, u64)> {
    let spec = v.strip_prefix("bytes=")?;
    let (a, b) = spec.split_once('-')?;
    let end_default = len.checked_sub(1)?;
    let (start, end) = if a.is_empty() {
        let n: u64 = b.parse().ok()?;
        (len.saturating_sub(n), end_default)
    } else {
        let s: u64 = a.parse().ok()?;
        let e = if b.is_empty() {
            end_default
        } else {
            b.parse::<u64>().ok()?.min(end_default)
        };
        (s, e)
    };
    (start <= end && start < len).then_some((start, end))
}

pub fn urlencoding(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            b' ' => out.push('+'),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}
