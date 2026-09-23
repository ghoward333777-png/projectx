//! Background job queue over the `jobs` table. Handlers live in the server.

use crate::db::Db;
use anyhow::Result;
use serde::Serialize;

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Job {
    pub id: i64,
    pub r#type: String,
    pub args: Option<String>,
    pub status: String,
    pub attempts: i64,
    pub last_error: Option<String>,
    pub run_at: String,
}

#[derive(Clone)]
pub struct Jobs {
    db: Db,
}

impl Jobs {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub async fn enqueue(&self, kind: &str, args: serde_json::Value) -> Result<i64> {
        let now = crate::now();
        let id = sqlx::query("INSERT INTO jobs (type, args, status, attempts, run_at, created_at, updated_at) VALUES (?, ?, 'queued', 0, ?, ?, ?)")
            .bind(kind).bind(args.to_string()).bind(&now).bind(&now).bind(&now)
            .execute(&self.db.pool).await?.last_insert_rowid();
        Ok(id)
    }

    /// Claims the next due job, marking it running. Single-process safe (SQLite serialises writes).
    pub async fn claim(&self) -> Result<Option<Job>> {
        let now = crate::now();
        let job = sqlx::query_as::<_, Job>("SELECT id, type, args, status, attempts, last_error, run_at FROM jobs WHERE status = 'queued' AND run_at <= ? ORDER BY id LIMIT 1")
            .bind(&now).fetch_optional(&self.db.pool).await?;
        let Some(job) = job else { return Ok(None) };
        let r = sqlx::query("UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ? AND status = 'queued'")
            .bind(&now).bind(job.id).execute(&self.db.pool).await?;
        if r.rows_affected() == 0 {
            return Ok(None);
        }
        Ok(Some(Job {
            status: "running".into(),
            attempts: job.attempts + 1,
            ..job
        }))
    }

    pub async fn complete(&self, id: i64) -> Result<()> {
        sqlx::query("UPDATE jobs SET status = 'done', updated_at = ? WHERE id = ?")
            .bind(crate::now())
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    /// Fails the job; retries with backoff up to three attempts.
    pub async fn fail(&self, job: &Job, error: &str) -> Result<()> {
        let now = crate::now();
        if job.attempts >= 3 {
            sqlx::query(
                "UPDATE jobs SET status = 'failed', last_error = ?, updated_at = ? WHERE id = ?",
            )
            .bind(error)
            .bind(&now)
            .bind(job.id)
            .execute(&self.db.pool)
            .await?;
        } else {
            let retry = (chrono::Utc::now() + chrono::Duration::seconds(30 * job.attempts))
                .format("%Y-%m-%dT%H:%M:%SZ")
                .to_string();
            sqlx::query("UPDATE jobs SET status = 'queued', last_error = ?, run_at = ?, updated_at = ? WHERE id = ?").bind(error).bind(retry).bind(&now).bind(job.id).execute(&self.db.pool).await?;
        }
        Ok(())
    }

    pub async fn counts(&self) -> Result<(i64, i64, i64)> {
        let row: (i64, i64, i64) = sqlx::query_as("SELECT COALESCE(SUM(status='queued'),0), COALESCE(SUM(status='running'),0), COALESCE(SUM(status='failed'),0) FROM jobs").fetch_one(&self.db.pool).await?;
        Ok(row)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn claim_complete_and_retry() {
        let db = Db::memory().await.unwrap();
        let jobs = Jobs::new(db);
        let id = jobs
            .enqueue("thumbnail", serde_json::json!({ "media": 1 }))
            .await
            .unwrap();
        let job = jobs.claim().await.unwrap().unwrap();
        assert_eq!(job.id, id);
        assert_eq!(job.attempts, 1);
        assert!(
            jobs.claim().await.unwrap().is_none(),
            "a running job is not claimed twice"
        );
        jobs.fail(&job, "boom").await.unwrap();
        let (queued, _, failed) = jobs.counts().await.unwrap();
        assert_eq!((queued, failed), (1, 0), "first failure retries later");
        jobs.complete(id).await.unwrap();
    }
}
