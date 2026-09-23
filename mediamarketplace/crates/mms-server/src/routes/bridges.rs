//! Bridge sites: the WordPress / Joomla installations allowed to embed content and sign SSO tokens.

use crate::app::AppState;
use crate::auth::AdminUser;
use crate::errors::AppResult;
use axum::extract::{Path, State};
use axum::response::{Html, IntoResponse, Redirect, Response};
use axum::Form;
use minijinja::context;
use serde::{Deserialize, Serialize};

#[derive(Serialize, sqlx::FromRow)]
pub struct BridgeSite {
    pub id: i64,
    pub uuid: String,
    pub name: String,
    pub host: String,
    pub origin: String,
    pub secret_enc: String,
    pub status: String,
    pub created_at: String,
    pub admin_sso: i64,
}

pub async fn all(state: &AppState) -> anyhow::Result<Vec<BridgeSite>> {
    Ok(sqlx::query_as::<_, BridgeSite>("SELECT id, uuid, name, host, origin, secret_enc, status, created_at, admin_sso FROM bridge_sites ORDER BY id")
        .fetch_all(&state.db.pool).await?)
}

pub async fn by_uuid(state: &AppState, uuid: &str) -> anyhow::Result<Option<BridgeSite>> {
    Ok(sqlx::query_as::<_, BridgeSite>("SELECT id, uuid, name, host, origin, secret_enc, status, created_at, admin_sso FROM bridge_sites WHERE uuid = ? AND status = 'active'")
        .bind(uuid).fetch_optional(&state.db.pool).await?)
}

/// Origins allowed to frame embeds; used for the frame-ancestors CSP.
pub fn normalise_origin(raw: &str) -> Option<String> {
    let raw = raw.trim().trim_end_matches('/');
    if !(raw.starts_with("http://") || raw.starts_with("https://")) {
        return None;
    }
    let rest = &raw[raw.find("://")? + 3..];
    if rest.is_empty() || rest.contains('/') || rest.contains(' ') {
        return None;
    }
    Some(raw.to_string())
}

/// Upserts the bridge sites declared in mms.toml. Called once on start.
pub async fn sync_from_config(state: &AppState) -> anyhow::Result<usize> {
    let mut n = 0;
    for b in &state.config.bridges {
        let Some(origin) = normalise_origin(&b.origin) else {
            anyhow::bail!("bridge {} has an invalid origin {}", b.name, b.origin)
        };
        let now = mms_core::now();
        sqlx::query(
            "INSERT INTO bridge_sites (uuid, name, host, origin, secret_enc, status, created_at, updated_at, admin_sso)
             VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
             ON CONFLICT(uuid) DO UPDATE SET name = excluded.name, host = excluded.host, origin = excluded.origin,
                 secret_enc = excluded.secret_enc, status = 'active', updated_at = excluded.updated_at, admin_sso = excluded.admin_sso",
        )
        .bind(&b.uuid)
        .bind(&b.name)
        .bind(&b.host)
        .bind(&origin)
        .bind(state.secrets.encrypt(&b.secret)?)
        .bind(&now)
        .bind(&now)
        .bind(b.admin_sso as i64)
        .execute(&state.db.pool)
        .await?;
        n += 1;
    }
    Ok(n)
}

pub async fn list(State(state): State<AppState>, admin: AdminUser) -> AppResult<Response> {
    render(&state, &admin, None, "").await
}

async fn render(
    state: &AppState,
    admin: &AdminUser,
    new_secret: Option<(String, String)>,
    error: &str,
) -> AppResult<Response> {
    let sites = all(state).await?;
    let site_name = state.settings.get("general.site_name").await?;
    Ok(Html(state.render(
        "bridges.html",
        context! {
            user => admin.user, csrf => admin.csrf, site_name, sites, error, active => "bridges",
            public_url => state.config.server.public_url,
            new_secret => new_secret.map(|(u, s)| context!{ uuid => u, secret => s }),
        },
    )?)
    .into_response())
}

#[derive(Deserialize)]
pub struct CreateForm {
    _csrf: String,
    name: String,
    host: String,
    origin: String,
}

pub async fn create(
    State(state): State<AppState>,
    admin: AdminUser,
    Form(f): Form<CreateForm>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    let Some(origin) = normalise_origin(&f.origin) else {
        return render(
            &state,
            &admin,
            None,
            "Origin must look like https://www.example.com with no path.",
        )
        .await;
    };
    if !matches!(f.host.as_str(), "wordpress" | "joomla" | "other") {
        return render(&state, &admin, None, "Unknown host type.").await;
    }
    if f.name.trim().is_empty() {
        return render(&state, &admin, None, "A name is required.").await;
    }
    use rand::RngCore;
    let mut raw = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut raw);
    let secret: String = raw.iter().map(|b| format!("{b:02x}")).collect();
    let uuid = uuid::Uuid::new_v4().to_string();
    let now = mms_core::now();
    sqlx::query("INSERT INTO bridge_sites (uuid, name, host, origin, secret_enc, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)")
        .bind(&uuid).bind(f.name.trim()).bind(&f.host).bind(&origin).bind(state.secrets.encrypt(&secret)?).bind(&now).bind(&now)
        .execute(&state.db.pool).await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "bridge.created",
            "bridge_site",
            Some(&uuid),
            None,
            Some(serde_json::json!({ "origin": origin })),
        )
        .await?;
    render(&state, &admin, Some((uuid, secret)), "").await
}

#[derive(Deserialize)]
pub struct DeleteForm {
    _csrf: String,
}

pub async fn delete(
    State(state): State<AppState>,
    admin: AdminUser,
    Path(uuid): Path<String>,
    Form(f): Form<DeleteForm>,
) -> AppResult<Response> {
    if let Some(r) = admin.csrf_error(&f._csrf) {
        return Ok(r);
    }
    sqlx::query("DELETE FROM bridge_sites WHERE uuid = ?")
        .bind(&uuid)
        .execute(&state.db.pool)
        .await?;
    state
        .audit
        .record(
            Some(admin.user.id),
            "bridge.deleted",
            "bridge_site",
            Some(&uuid),
            None,
            None,
        )
        .await?;
    Ok(Redirect::to(&state.url("/admin/bridges")).into_response())
}
