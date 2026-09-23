use crate::db::Db;
use anyhow::Result;

#[derive(Clone)]
pub struct Audit {
    db: Db,
}

impl Audit {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub async fn record(
        &self,
        actor_id: Option<i64>,
        action: &str,
        subject_type: &str,
        subject_id: Option<&str>,
        ip: Option<&str>,
        details: Option<serde_json::Value>,
    ) -> Result<()> {
        sqlx::query("INSERT INTO audit_log (actor_id, action, subject_type, subject_id, ip, details, logged_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
            .bind(actor_id).bind(action).bind(subject_type).bind(subject_id).bind(ip)
            .bind(details.map(|d| d.to_string())).bind(crate::now())
            .execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn recent(
        &self,
        limit: i64,
    ) -> Result<Vec<(String, String, String, Option<String>)>> {
        let rows = sqlx::query_as::<_, (String, String, String, Option<String>)>("SELECT logged_at, action, subject_type, subject_id FROM audit_log ORDER BY id DESC LIMIT ?")
            .bind(limit).fetch_all(&self.db.pool).await?;
        Ok(rows)
    }
}
