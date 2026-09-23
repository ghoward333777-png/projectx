//! Optional "sell through" mode: a CMS shop (WooCommerce on WordPress, VirtueMart on
//! Joomla) takes the money and tells the store what was bought; the store keeps
//! granting access, issuing receipts and running everything else. The native
//! checkout stays the default; this module only holds the product mappings, the
//! request signature the shop plugins use, the Buy-button address and the event log.
//! Orders themselves still go through `Commerce::mark_paid`, the one granting point.

use crate::db::Db;
use anyhow::{bail, Result};
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;

/// The shops a site can sell through, with their standard add-to-cart address.
pub const SYSTEMS: &[(&str, &str, &str)] = &[
    ("woocommerce", "WooCommerce", "{origin}/?add-to-cart={external_id}&quantity=1"),
    (
        "virtuemart",
        "VirtueMart",
        "{origin}/index.php?option=com_virtuemart&view=cart&task=add&virtuemart_product_id[]={external_id}&quantity[]=1",
    ),
];

pub fn system_label(system: &str) -> &'static str {
    SYSTEMS
        .iter()
        .find(|(s, _, _)| *s == system)
        .map(|(_, l, _)| *l)
        .unwrap_or("Shop")
}

pub fn is_system(system: &str) -> bool {
    SYSTEMS.iter().any(|(s, _, _)| *s == system)
}

/// The address a Buy button sends the shopper to when checkout runs in the shop.
/// `template` is the optional override from settings; `{external_id}` and `{origin}`
/// are replaced. Returns `None` when the mode is native or unknown.
pub fn buy_url(mode: &str, template: &str, origin: &str, external_id: &str) -> Option<String> {
    let default = SYSTEMS
        .iter()
        .find(|(s, _, _)| *s == mode)
        .map(|(_, _, t)| *t)?;
    let t = if template.trim().is_empty() {
        default
    } else {
        template.trim()
    };
    Some(
        t.replace("{origin}", origin.trim_end_matches('/'))
            .replace("{external_id}", &urlencode(external_id)),
    )
}

fn urlencode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Request signature the shop plugins send: `HMAC-SHA256(secret, "{ts}\n{METHOD}\n{path}\n{body}")`
/// as lowercase hex in `X-MMS-Signature`, with `X-MMS-Site` (bridge uuid) and
/// `X-MMS-Timestamp` (unix seconds). The same secret signs SSO tokens, so a shop
/// that can sign people in can also report their orders, and nothing else can.
pub fn request_signature(secret: &str, ts: i64, method: &str, path: &str, body: &[u8]) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret.as_bytes()).expect("any key length");
    mac.update(ts.to_string().as_bytes());
    mac.update(b"\n");
    mac.update(method.to_ascii_uppercase().as_bytes());
    mac.update(b"\n");
    mac.update(path.as_bytes());
    mac.update(b"\n");
    mac.update(body);
    mac.finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// Constant-time comparison of two hex signatures.
pub fn signature_matches(expected: &str, given: &str) -> bool {
    let (a, b) = (expected.as_bytes(), given.as_bytes());
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// How far a timestamp may drift before a signed request is refused.
pub const MAX_SKEW_SECONDS: i64 = 300;

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Mapping {
    pub id: i64,
    pub system: String,
    pub product_id: i64,
    pub external_id: String,
    pub external_url: String,
    pub synced_at: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct LinkInput {
    pub slug: String,
    pub external_id: String,
    #[serde(default)]
    pub external_url: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct BridgeEvent {
    pub id: i64,
    pub system: String,
    pub kind: String,
    pub external_id: String,
    pub status: String,
    pub result: String,
    pub created_at: String,
}

#[derive(Clone)]
pub struct CommerceBridge {
    db: Db,
}

impl CommerceBridge {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    /// Upserts mappings. A slug the store does not know is reported back, not an error.
    pub async fn link(&self, system: &str, links: &[LinkInput]) -> Result<(usize, Vec<String>)> {
        if !is_system(system) {
            bail!("unknown shop system {system}");
        }
        let now = crate::now();
        let mut linked = 0;
        let mut unknown = Vec::new();
        for l in links {
            let external_id = l.external_id.trim();
            if external_id.is_empty() {
                continue;
            }
            let Some(pid) = sqlx::query_scalar::<_, i64>("SELECT id FROM products WHERE slug = ?")
                .bind(l.slug.trim())
                .fetch_optional(&self.db.pool)
                .await?
            else {
                unknown.push(l.slug.clone());
                continue;
            };
            // One shop product per store product and vice versa: clear stale rows first.
            sqlx::query("DELETE FROM external_products WHERE system = ? AND (product_id = ? OR external_id = ?)")
                .bind(system).bind(pid).bind(external_id).execute(&self.db.pool).await?;
            sqlx::query("INSERT INTO external_products (system, product_id, external_id, external_url, synced_at) VALUES (?, ?, ?, ?, ?)")
                .bind(system).bind(pid).bind(external_id).bind(l.external_url.trim()).bind(&now).execute(&self.db.pool).await?;
            linked += 1;
        }
        Ok((linked, unknown))
    }

    pub async fn unlink(&self, system: &str, product_id: i64) -> Result<()> {
        sqlx::query("DELETE FROM external_products WHERE system = ? AND product_id = ?")
            .bind(system)
            .bind(product_id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn mapping(&self, system: &str, product_id: i64) -> Result<Option<Mapping>> {
        Ok(sqlx::query_as::<_, Mapping>("SELECT id, system, product_id, external_id, external_url, synced_at FROM external_products WHERE system = ? AND product_id = ?")
            .bind(system).bind(product_id).fetch_optional(&self.db.pool).await?)
    }

    pub async fn by_external(&self, system: &str, external_id: &str) -> Result<Option<Mapping>> {
        Ok(sqlx::query_as::<_, Mapping>("SELECT id, system, product_id, external_id, external_url, synced_at FROM external_products WHERE system = ? AND external_id = ?")
            .bind(system).bind(external_id).fetch_optional(&self.db.pool).await?)
    }

    pub async fn mappings(&self, system: &str) -> Result<Vec<Mapping>> {
        Ok(sqlx::query_as::<_, Mapping>("SELECT id, system, product_id, external_id, external_url, synced_at FROM external_products WHERE system = ? ORDER BY product_id")
            .bind(system).fetch_all(&self.db.pool).await?)
    }

    pub async fn count(&self, system: &str) -> Result<i64> {
        Ok(
            sqlx::query_scalar("SELECT COUNT(*) FROM external_products WHERE system = ?")
                .bind(system)
                .fetch_one(&self.db.pool)
                .await?,
        )
    }

    pub async fn record_event(
        &self,
        system: &str,
        kind: &str,
        external_id: &str,
        status: &str,
        result: &str,
    ) -> Result<()> {
        sqlx::query("INSERT INTO bridge_events (system, kind, external_id, status, result, created_at) VALUES (?, ?, ?, ?, ?, ?)")
            .bind(system).bind(kind).bind(external_id).bind(status).bind(result).bind(crate::now()).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn events(&self, limit: i64) -> Result<Vec<BridgeEvent>> {
        Ok(sqlx::query_as::<_, BridgeEvent>("SELECT id, system, kind, external_id, status, result, created_at FROM bridge_events ORDER BY id DESC LIMIT ?")
            .bind(limit).fetch_all(&self.db.pool).await?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn buy_urls_follow_the_shop_conventions() {
        assert_eq!(
            buy_url("woocommerce", "", "https://site.example/", "42").unwrap(),
            "https://site.example/?add-to-cart=42&quantity=1"
        );
        assert!(buy_url("virtuemart", "", "https://site.example", "7")
            .unwrap()
            .contains("virtuemart_product_id[]=7"));
        assert_eq!(
            buy_url(
                "woocommerce",
                "{origin}/buy/{external_id}",
                "https://s.example",
                "a b"
            )
            .unwrap(),
            "https://s.example/buy/a%20b"
        );
        assert!(buy_url("native", "", "https://s.example", "1").is_none());
    }

    #[test]
    fn signature_is_stable_and_compared_in_constant_time() {
        // Fixture shared with packages/shared/MmsRuntime.php (MmsRuntime::signRequest).
        let sig = request_signature(
            "test-secret",
            1900000000,
            "post",
            "/mms/api/v1/commerce/orders",
            b"{\"a\":1}",
        );
        assert_eq!(
            sig,
            "4f5d56454d11d6ed11ea7777e15c5cfe63cf67b855ff07616b5d86fb129e9e70"
        );
        assert!(signature_matches(&sig, &sig));
        assert!(!signature_matches(&sig, &sig.replace('0', "1")));
        assert!(!signature_matches(&sig, "short"));
    }
}
