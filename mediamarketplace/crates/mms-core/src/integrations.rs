//! API keys for the JSON API and outbound webhooks for other systems.

use crate::db::Db;
use anyhow::{bail, Result};
use hmac::{Hmac, Mac};
use serde::Serialize;
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct ApiKey {
    pub id: i64,
    pub name: String,
    pub prefix: String,
    pub scopes: String,
    pub last_used: Option<String>,
    pub status: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Endpoint {
    pub id: i64,
    pub url: String,
    pub secret: String,
    pub events: String,
    pub status: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Delivery {
    pub id: i64,
    pub endpoint_id: i64,
    pub event: String,
    pub payload: String,
    pub status: String,
    pub attempts: i64,
    pub last_status: Option<i64>,
    pub last_error: Option<String>,
    pub created_at: String,
}

pub const EVENTS: &[&str] = &[
    "order.paid",
    "order.refunded",
    "entitlement.granted",
    "agreement.signed",
    "subscription.renewed",
    "subscription.ended",
];

fn hash(plain: &str) -> String {
    let mut h = Sha256::new();
    h.update(plain.as_bytes());
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

/// `X-MMS-Signature: t=<unix>,v1=<hex hmac-sha256 over "<t>.<body>">`.
pub fn sign_payload(secret: &str, ts: i64, body: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("hmac key");
    mac.update(format!("{ts}.").as_bytes());
    mac.update(body.as_bytes());
    let sig: String = mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    format!("t={ts},v1={sig}")
}

#[derive(Clone)]
pub struct Integrations {
    db: Db,
    http: reqwest::Client,
}

impl Integrations {
    pub fn new(db: Db) -> Self {
        Self {
            db,
            http: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(15))
                .build()
                .expect("http client"),
        }
    }

    // ----- API keys -----

    /// Creates a key; the plain value is returned once and never stored.
    pub async fn create_key(&self, name: &str, scopes: &str) -> Result<String> {
        if name.trim().is_empty() {
            bail!("Give the key a name");
        }
        use rand::RngCore;
        let mut b = [0u8; 24];
        rand::thread_rng().fill_bytes(&mut b);
        let plain = format!(
            "mms_{}",
            b.iter().map(|x| format!("{x:02x}")).collect::<String>()
        );
        let scopes = if scopes == "write" { "write" } else { "read" };
        sqlx::query("INSERT INTO api_keys (name, key_hash, prefix, scopes, created_at) VALUES (?, ?, ?, ?, ?)")
            .bind(name.trim()).bind(hash(&plain)).bind(&plain[..12]).bind(scopes).bind(crate::now())
            .execute(&self.db.pool).await?;
        Ok(plain)
    }

    pub async fn keys(&self) -> Result<Vec<ApiKey>> {
        Ok(sqlx::query_as::<_, ApiKey>("SELECT id, name, prefix, scopes, last_used, status, created_at FROM api_keys ORDER BY id DESC").fetch_all(&self.db.pool).await?)
    }

    pub async fn revoke_key(&self, id: i64) -> Result<()> {
        sqlx::query("UPDATE api_keys SET status = 'revoked' WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    /// Looks a bearer token up; touches last_used.
    pub async fn authenticate(&self, bearer: &str) -> Result<Option<ApiKey>> {
        let k = sqlx::query_as::<_, ApiKey>("SELECT id, name, prefix, scopes, last_used, status, created_at FROM api_keys WHERE key_hash = ? AND status = 'active'")
            .bind(hash(bearer.trim())).fetch_optional(&self.db.pool).await?;
        if let Some(k) = &k {
            sqlx::query("UPDATE api_keys SET last_used = ? WHERE id = ?")
                .bind(crate::now())
                .bind(k.id)
                .execute(&self.db.pool)
                .await?;
        }
        Ok(k)
    }

    // ----- webhooks -----

    pub async fn create_endpoint(&self, url: &str, events: &str) -> Result<Endpoint> {
        if !url.starts_with("https://") && !url.starts_with("http://") {
            bail!("The URL must start with https:// (or http:// for local testing)");
        }
        use rand::RngCore;
        let mut b = [0u8; 24];
        rand::thread_rng().fill_bytes(&mut b);
        let secret = format!(
            "whsec_{}",
            b.iter().map(|x| format!("{x:02x}")).collect::<String>()
        );
        let events = if events.trim().is_empty() {
            "*".to_string()
        } else {
            events.trim().to_string()
        };
        let id = sqlx::query(
            "INSERT INTO webhook_endpoints (url, secret, events, created_at) VALUES (?, ?, ?, ?)",
        )
        .bind(url.trim())
        .bind(&secret)
        .bind(&events)
        .bind(crate::now())
        .execute(&self.db.pool)
        .await?
        .last_insert_rowid();
        Ok(sqlx::query_as::<_, Endpoint>("SELECT id, url, secret, events, status, created_at FROM webhook_endpoints WHERE id = ?").bind(id).fetch_one(&self.db.pool).await?)
    }

    pub async fn endpoints(&self) -> Result<Vec<Endpoint>> {
        Ok(sqlx::query_as::<_, Endpoint>("SELECT id, url, secret, events, status, created_at FROM webhook_endpoints ORDER BY id DESC").fetch_all(&self.db.pool).await?)
    }

    pub async fn delete_endpoint(&self, id: i64) -> Result<()> {
        sqlx::query("DELETE FROM webhook_endpoints WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    /// Queues one delivery per endpoint subscribed to the event. Returns delivery ids.
    pub async fn emit(&self, event: &str, payload: serde_json::Value) -> Result<Vec<i64>> {
        let now = crate::now();
        let body =
            serde_json::json!({ "event": event, "created_at": now, "data": payload }).to_string();
        let mut ids = Vec::new();
        for e in self.endpoints().await? {
            if e.status != "active" {
                continue;
            }
            let wants = e.events == "*" || e.events.split(',').any(|x| x.trim() == event);
            if !wants {
                continue;
            }
            let id = sqlx::query("INSERT INTO webhook_deliveries (endpoint_id, event, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?)")
                .bind(e.id).bind(event).bind(&body).bind(&now).bind(&now)
                .execute(&self.db.pool).await?.last_insert_rowid();
            ids.push(id);
        }
        Ok(ids)
    }

    pub async fn deliveries(&self, limit: i64) -> Result<Vec<Delivery>> {
        Ok(sqlx::query_as::<_, Delivery>("SELECT id, endpoint_id, event, payload, status, attempts, last_status, last_error, created_at FROM webhook_deliveries ORDER BY id DESC LIMIT ?").bind(limit).fetch_all(&self.db.pool).await?)
    }

    /// Attempts one delivery; errors bubble up so the job queue retries with backoff.
    pub async fn deliver(&self, delivery_id: i64) -> Result<()> {
        let Some(d) = sqlx::query_as::<_, Delivery>("SELECT id, endpoint_id, event, payload, status, attempts, last_status, last_error, created_at FROM webhook_deliveries WHERE id = ?").bind(delivery_id).fetch_optional(&self.db.pool).await? else {
            return Ok(());
        };
        if d.status == "delivered" {
            return Ok(());
        }
        let Some(e) = sqlx::query_as::<_, Endpoint>("SELECT id, url, secret, events, status, created_at FROM webhook_endpoints WHERE id = ?").bind(d.endpoint_id).fetch_optional(&self.db.pool).await? else {
            return Ok(());
        };
        let ts = chrono::Utc::now().timestamp();
        let sig = sign_payload(&e.secret, ts, &d.payload);
        let now = crate::now();
        let result = self
            .http
            .post(&e.url)
            .header("Content-Type", "application/json")
            .header("X-MMS-Signature", sig)
            .header("X-MMS-Event", &d.event)
            .body(d.payload.clone())
            .send()
            .await;
        match result {
            Ok(res) if res.status().is_success() => {
                sqlx::query("UPDATE webhook_deliveries SET status = 'delivered', attempts = attempts + 1, last_status = ?, last_error = NULL, updated_at = ? WHERE id = ?")
                    .bind(res.status().as_u16() as i64).bind(&now).bind(d.id).execute(&self.db.pool).await?;
                Ok(())
            }
            Ok(res) => {
                let code = res.status().as_u16() as i64;
                self.note_failure(
                    d.id,
                    d.attempts + 1,
                    Some(code),
                    &format!("HTTP {code}"),
                    &now,
                )
                .await?;
                bail!("endpoint answered HTTP {code}")
            }
            Err(err) => {
                self.note_failure(d.id, d.attempts + 1, None, &err.to_string(), &now)
                    .await?;
                bail!("delivery failed: {err}")
            }
        }
    }

    async fn note_failure(
        &self,
        id: i64,
        attempts: i64,
        code: Option<i64>,
        error: &str,
        now: &str,
    ) -> Result<()> {
        let status = if attempts >= 3 { "failed" } else { "queued" };
        sqlx::query("UPDATE webhook_deliveries SET status = ?, attempts = ?, last_status = ?, last_error = ?, updated_at = ? WHERE id = ?")
            .bind(status).bind(attempts).bind(code).bind(error).bind(now).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn keys_and_endpoints() {
        let db = Db::memory().await.unwrap();
        let i = Integrations::new(db.clone());
        let plain = i.create_key("Zapier", "read").await.unwrap();
        assert!(plain.starts_with("mms_"));
        let k = i.authenticate(&plain).await.unwrap().unwrap();
        assert_eq!((k.name.as_str(), k.scopes.as_str()), ("Zapier", "read"));
        assert!(i.authenticate("mms_nope").await.unwrap().is_none());
        i.revoke_key(k.id).await.unwrap();
        assert!(i.authenticate(&plain).await.unwrap().is_none());
        let e = i
            .create_endpoint("https://example.com/hook", "order.paid")
            .await
            .unwrap();
        assert!(e.secret.starts_with("whsec_"));
        assert!(i.create_endpoint("ftp://x", "").await.is_err());
        let ids = i
            .emit("order.paid", serde_json::json!({ "number": "ORD-1" }))
            .await
            .unwrap();
        assert_eq!(ids.len(), 1);
        assert!(
            i.emit("agreement.signed", serde_json::json!({}))
                .await
                .unwrap()
                .is_empty(),
            "not subscribed"
        );
        let d = &i.deliveries(10).await.unwrap()[0];
        assert!(d.payload.contains("\"event\":\"order.paid\""));
        assert_eq!(sign_payload("s", 1, "{}"), sign_payload("s", 1, "{}"));
        assert_ne!(sign_payload("s", 1, "{}"), sign_payload("t", 1, "{}"));
    }
}
