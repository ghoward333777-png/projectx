//! Background job worker: polls the jobs table and runs handlers.

use crate::app::AppState;
use std::time::Duration;

pub fn spawn(state: AppState) {
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
        other => anyhow::bail!("unknown job type {other}"),
    }
}
