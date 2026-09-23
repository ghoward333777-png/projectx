//! GDPR: export everything the store holds about a customer as JSON, and erase by
//! anonymising the account while keeping the accounting records that must stay.

use crate::db::Db;
use anyhow::{bail, Result};

#[derive(Clone)]
pub struct Privacy {
    db: Db,
}

impl Privacy {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    async fn rows(&self, sql: &str, user_id: i64) -> Result<Vec<serde_json::Value>> {
        use sqlx::{Column, Row, TypeInfo};
        let rows = sqlx::query(sql)
            .bind(user_id)
            .fetch_all(&self.db.pool)
            .await?;
        Ok(rows
            .iter()
            .map(|r| {
                let mut m = serde_json::Map::new();
                for c in r.columns() {
                    let name = c.name();
                    let v: serde_json::Value = match c.type_info().name() {
                        "INTEGER" => r
                            .try_get::<Option<i64>, _>(name)
                            .ok()
                            .flatten()
                            .map(serde_json::Value::from)
                            .unwrap_or(serde_json::Value::Null),
                        "REAL" => r
                            .try_get::<Option<f64>, _>(name)
                            .ok()
                            .flatten()
                            .map(serde_json::Value::from)
                            .unwrap_or(serde_json::Value::Null),
                        "BLOB" => r
                            .try_get::<Option<Vec<u8>>, _>(name)
                            .ok()
                            .flatten()
                            .map(|b| serde_json::Value::from(format!("<{} bytes>", b.len())))
                            .unwrap_or(serde_json::Value::Null),
                        _ => r
                            .try_get::<Option<String>, _>(name)
                            .ok()
                            .flatten()
                            .map(serde_json::Value::from)
                            .unwrap_or(serde_json::Value::Null),
                    };
                    m.insert(name.to_string(), v);
                }
                serde_json::Value::Object(m)
            })
            .collect())
    }

    pub async fn export(&self, user_id: i64) -> Result<serde_json::Value> {
        let profile = self
            .rows(
                "SELECT uuid, email, name, role, status, created_at FROM users WHERE id = ?",
                user_id,
            )
            .await?;
        if profile.is_empty() {
            bail!("no such customer");
        }
        let out = serde_json::json!({
            "exported_at": crate::now(),
            "profile": profile[0],
            "orders": self.rows("SELECT number, status, currency, subtotal_cents, discount_cents, tax_cents, total_cents, country, gateway, paid_at, created_at FROM orders WHERE user_id = ?", user_id).await?,
            "entitlements": self.rows("SELECT scope, scope_ref, source, starts_at, ends_at, status FROM entitlements WHERE user_id = ?", user_id).await?,
            "subscriptions": self.rows("SELECT uuid, gateway, interval, status, period_end, created_at FROM subscriptions WHERE user_id = ?", user_id).await?,
            "agreements": self.rows("SELECT uuid, agreement_version, agreement_hash, signer_name, method, ip, user_agent, status, signed_at FROM agreements WHERE user_id = ?", user_id).await?,
            "ratings": self.rows("SELECT product_id, stars, review, created_at FROM ratings WHERE user_id = ?", user_id).await?,
            "playback_sessions": self.rows("SELECT product_id, player, position_ms, started_at, last_seen FROM playback_sessions WHERE user_id = ?", user_id).await?,
            "watermark_sessions": self.rows("SELECT uuid, media_id, kind, level, ip, created_at FROM mark_sessions WHERE user_id = ?", user_id).await?,
            "audit": self.rows("SELECT action, subject_type, subject_id, ip, logged_at FROM audit_log WHERE actor_id = ?", user_id).await?,
        });
        sqlx::query(
            "INSERT INTO privacy_requests (user_id, kind, created_at) VALUES (?, 'export', ?)",
        )
        .bind(user_id)
        .bind(crate::now())
        .execute(&self.db.pool)
        .await?;
        Ok(out)
    }

    /// Anonymises the account: personal fields are replaced, sessions and forensic
    /// records are removed, access is revoked. Orders and receipts stay for accounting
    /// with the name and email removed from the customer record they point to.
    pub async fn erase(&self, user_id: i64) -> Result<()> {
        let role: Option<String> = sqlx::query_scalar("SELECT role FROM users WHERE id = ?")
            .bind(user_id)
            .fetch_optional(&self.db.pool)
            .await?;
        match role.as_deref() {
            None => bail!("no such customer"),
            Some("admin") => bail!("administrators cannot be erased; demote the account first"),
            _ => {}
        }
        let now = crate::now();
        let anon = format!("erased-{user_id}@invalid.local");
        sqlx::query("UPDATE users SET email = ?, name = 'Erased customer', password_hash = NULL, status = 'disabled', updated_at = ? WHERE id = ?").bind(&anon).bind(&now).bind(user_id).execute(&self.db.pool).await?;
        sqlx::query("DELETE FROM user_identities WHERE user_id = ?")
            .bind(user_id)
            .execute(&self.db.pool)
            .await?;
        sqlx::query("UPDATE entitlements SET status = 'revoked', updated_at = ? WHERE user_id = ? AND status = 'active'").bind(&now).bind(user_id).execute(&self.db.pool).await?;
        sqlx::query("UPDATE subscriptions SET status = 'ended', updated_at = ? WHERE user_id = ? AND status = 'active'").bind(&now).bind(user_id).execute(&self.db.pool).await?;
        sqlx::query("DELETE FROM playback_sessions WHERE user_id = ?")
            .bind(user_id)
            .execute(&self.db.pool)
            .await?;
        sqlx::query("DELETE FROM mark_sessions WHERE user_id = ?")
            .bind(user_id)
            .execute(&self.db.pool)
            .await?;
        sqlx::query("DELETE FROM ratings WHERE user_id = ?")
            .bind(user_id)
            .execute(&self.db.pool)
            .await?;
        sqlx::query("DELETE FROM carts WHERE user_id = ?")
            .bind(user_id)
            .execute(&self.db.pool)
            .await?;
        sqlx::query("DELETE FROM pass_notices WHERE user_id = ?")
            .bind(user_id)
            .execute(&self.db.pool)
            .await?;
        sqlx::query("UPDATE agreements SET signer_name = 'Erased', ip = '', user_agent = '', signature = NULL WHERE user_id = ?").bind(user_id).execute(&self.db.pool).await?;
        sqlx::query("UPDATE audit_log SET ip = NULL, user_agent = NULL WHERE actor_id = ?")
            .bind(user_id)
            .execute(&self.db.pool)
            .await?;
        sqlx::query(
            "INSERT INTO privacy_requests (user_id, kind, created_at) VALUES (?, 'erase', ?)",
        )
        .bind(user_id)
        .bind(&now)
        .execute(&self.db.pool)
        .await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn export_then_erase() {
        let db = Db::memory().await.unwrap();
        let now = crate::now();
        sqlx::query("INSERT INTO users (uuid, email, name, role, status, password_hash, created_at, updated_at) VALUES ('u1','ada@x.io','Ada','customer','active','h',?,?)").bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        sqlx::query("INSERT INTO users (uuid, email, name, role, status, created_at, updated_at) VALUES ('a1','boss@x.io','Boss','admin','active',?,?)").bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        sqlx::query("INSERT INTO orders (uuid, number, user_id, status, currency, total_cents, created_at, updated_at) VALUES ('o1','ORD-1',1,'paid','USD',100,?,?)").bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        let p = Privacy::new(db.clone());
        let e = p.export(1).await.unwrap();
        assert_eq!(e["profile"]["email"], "ada@x.io");
        assert_eq!(e["orders"][0]["number"], "ORD-1");
        assert!(p
            .erase(2)
            .await
            .unwrap_err()
            .to_string()
            .contains("administrators"));
        p.erase(1).await.unwrap();
        let (email, status): (String, String) =
            sqlx::query_as("SELECT email, status FROM users WHERE id = 1")
                .fetch_one(&db.pool)
                .await
                .unwrap();
        assert!(email.starts_with("erased-") && status == "disabled");
        let (n,): (i64,) = sqlx::query_as("SELECT COUNT(*) FROM orders WHERE user_id = 1")
            .fetch_one(&db.pool)
            .await
            .unwrap();
        assert_eq!(n, 1, "accounting records stay");
        let (reqs,): (i64,) = sqlx::query_as("SELECT COUNT(*) FROM privacy_requests")
            .fetch_one(&db.pool)
            .await
            .unwrap();
        assert_eq!(reqs, 2);
    }
}
