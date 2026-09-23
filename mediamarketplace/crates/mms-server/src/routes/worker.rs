//! Background job worker: polls the jobs table and runs handlers.

use crate::app::AppState;
use std::time::Duration;

pub fn spawn(state: AppState) {
    // Daily pass housekeeping (expiry, renewal notices), first run shortly after start.
    let hk = state.clone();
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(30)).await;
            let _ = hk
                .jobs
                .enqueue("passes.housekeeping", serde_json::json!({}))
                .await;
            tokio::time::sleep(Duration::from_secs(24 * 3600)).await;
        }
    });
    // Google posts due for publishing, hourly.
    let gp = state.clone();
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(3600)).await;
            let _ = gp.jobs.enqueue("google.posts", serde_json::json!({})).await;
        }
    });
    tokio::spawn(async move {
        loop {
            match state.jobs.claim().await {
                Ok(Some(job)) => {
                    let result =
                        run(&state, &job.r#type, job.args.as_deref().unwrap_or("{}")).await;
                    match result {
                        Ok(()) => {
                            let _ = state.jobs.complete(job.id).await;
                        }
                        Err(e) => {
                            tracing::warn!(job = job.id, kind = %job.r#type, error = %e, "job failed");
                            let _ = state.jobs.fail(&job, &e.to_string()).await;
                        }
                    }
                }
                Ok(None) => tokio::time::sleep(Duration::from_secs(2)).await,
                Err(e) => {
                    tracing::error!(error = %e, "job queue unavailable");
                    tokio::time::sleep(Duration::from_secs(10)).await;
                }
            }
        }
    });
}

/// Runs one job. Also used directly by tests and by handlers that want synchronous processing.
pub async fn run(state: &AppState, kind: &str, args: &str) -> anyhow::Result<()> {
    let args: serde_json::Value = serde_json::from_str(args).unwrap_or_default();
    match kind {
        "thumbnail" => {
            let id = args
                .get("media")
                .and_then(|v| v.as_i64())
                .ok_or_else(|| anyhow::anyhow!("media id missing"))?;
            state.media.generate_thumbnails(id).await
        }
        "webhook.deliver" => {
            let id = args
                .get("delivery")
                .and_then(|v| v.as_i64())
                .ok_or_else(|| anyhow::anyhow!("delivery id missing"))?;
            state.integrations.deliver(id).await
        }
        "video.mark" => {
            let session = args.get("session").and_then(|v| v.as_str()).unwrap_or("");
            crate::routes::protection::mark_video_job(state, session).await
        }
        "google.posts" => crate::routes::google::publish_due(state).await,
        "mail.pass_reminders" => {
            // Holders with a fresh notice get one email per notice.
            let rows: Vec<(i64, String, String, i64)> = sqlx::query_as("SELECT n.id, u.email, u.name, n.days_left FROM pass_notices n JOIN users u ON u.id = n.user_id WHERE n.created_at > ? AND u.status = 'active'")
                .bind(mms_core::commerce::add_days(&mms_core::now(), -1)).fetch_all(&state.db.pool).await?;
            let site = state.settings.get("general.site_name").await?;
            for (_, email, name, days) in rows {
                let text = format!("Hello {name},\n\nyour site pass at {site} ends in {days} day{}. Renew from My media: {}/account\n", if days == 1 { "" } else { "s" }, state.config.server.public_url.trim_end_matches('/'));
                crate::routes::ops::send_quietly(
                    state,
                    &email,
                    &format!(
                        "Your {site} pass ends in {days} day{}",
                        if days == 1 { "" } else { "s" }
                    ),
                    &text,
                    None,
                    None,
                    "pass_reminder",
                )
                .await;
            }
            Ok(())
        }
        "rates.refresh" => {
            let n = state.currency.refresh().await?;
            tracing::info!(rates = n, "currency rates refreshed");
            Ok(())
        }
        "retention.prune" => {
            let months: i64 = state
                .settings
                .get("privacy.retention_months")
                .await?
                .parse()
                .unwrap_or(24);
            let sessions = state.protection.prune(months).await?;
            let cutoff = mms_core::commerce::add_days(&mms_core::now(), -(months.max(1) * 30));
            let audit = sqlx::query("DELETE FROM audit_log WHERE logged_at < ?")
                .bind(&cutoff)
                .execute(&state.db.pool)
                .await?
                .rows_affected();
            let plays = sqlx::query("DELETE FROM playback_sessions WHERE started_at < ?")
                .bind(&cutoff)
                .execute(&state.db.pool)
                .await?
                .rows_affected();
            tracing::info!(sessions, audit, plays, "retention prune");
            Ok(())
        }
        "passes.housekeeping" => {
            let (expired, notices) = state.commerce.pass_housekeeping().await?;
            tracing::info!(expired, notices, "pass housekeeping");
            Ok(())
        }
        other => anyhow::bail!("unknown job type {other}"),
    }
}
