use crate::db::Db;
use anyhow::Result;
use serde::Serialize;

/// What a user is asking to access.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Subject {
    Product(i64),
    Page(String),
    Category(String),
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Entitlement {
    pub id: i64,
    pub user_id: i64,
    pub product_id: Option<i64>,
    pub scope: String,
    pub scope_ref: String,
    pub source: String,
    pub source_ref: String,
    pub starts_at: String,
    pub ends_at: Option<String>,
    pub status: String,
}

#[derive(Debug, Clone)]
pub struct Grant<'a> {
    pub user_id: i64,
    pub product_id: Option<i64>,
    pub scope: &'a str,
    pub scope_ref: &'a str,
    pub source: &'a str,
    pub source_ref: &'a str,
    pub starts_at: &'a str,
    pub ends_at: Option<&'a str>,
}

#[derive(Clone)]
pub struct Entitlements {
    db: Db,
}

impl Entitlements {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    /// Idempotent: replaying the same (source, source_ref) never double-grants.
    pub async fn grant(&self, g: Grant<'_>) -> Result<i64> {
        let now = crate::now();
        sqlx::query(
            "INSERT INTO entitlements (user_id, product_id, scope, scope_ref, source, source_ref, starts_at, ends_at, status, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
             ON CONFLICT(source, source_ref, user_id, scope, scope_ref) DO UPDATE SET ends_at = excluded.ends_at, status = 'active', updated_at = excluded.updated_at",
        )
        .bind(g.user_id).bind(g.product_id).bind(g.scope).bind(g.scope_ref).bind(g.source).bind(g.source_ref)
        .bind(g.starts_at).bind(g.ends_at).bind(&now).bind(&now)
        .execute(&self.db.pool)
        .await?;
        let id: i64 = sqlx::query_scalar("SELECT id FROM entitlements WHERE source = ? AND source_ref = ? AND user_id = ? AND scope = ? AND scope_ref = ?")
            .bind(g.source).bind(g.source_ref).bind(g.user_id).bind(g.scope).bind(g.scope_ref)
            .fetch_one(&self.db.pool).await?;
        Ok(id)
    }

    /// Revokes every entitlement that came from a source reference (an order, a subscription).
    pub async fn revoke_source(&self, source: &str, source_ref: &str) -> Result<u64> {
        let r = sqlx::query("UPDATE entitlements SET status = 'revoked', updated_at = ? WHERE source = ? AND source_ref = ? AND status = 'active'")
            .bind(crate::now()).bind(source).bind(source_ref)
            .execute(&self.db.pool).await?;
        Ok(r.rows_affected())
    }

    /// The single access decision used by players, downloads, pages and the API.
    pub async fn check(&self, user_id: i64, subject: &Subject, now: &str) -> Result<bool> {
        let (scope, scope_ref, product_id) = match subject {
            Subject::Product(id) => ("product", String::new(), Some(*id)),
            Subject::Page(r) => ("page", r.clone(), None),
            Subject::Category(r) => ("category", r.clone(), None),
        };
        let n: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM entitlements
             WHERE user_id = ? AND status = 'active' AND starts_at <= ? AND (ends_at IS NULL OR ends_at > ?)
               AND (scope = 'site'
                    OR (scope = ? AND scope_ref = ? AND (? IS NULL OR product_id = ?)))",
        )
        .bind(user_id).bind(now).bind(now).bind(scope).bind(&scope_ref).bind(product_id).bind(product_id)
        .fetch_one(&self.db.pool)
        .await?;
        Ok(n > 0)
    }

    pub async fn for_user(&self, user_id: i64) -> Result<Vec<Entitlement>> {
        Ok(sqlx::query_as::<_, Entitlement>("SELECT id, user_id, product_id, scope, scope_ref, source, source_ref, starts_at, ends_at, status FROM entitlements WHERE user_id = ? ORDER BY id DESC")
            .bind(user_id).fetch_all(&self.db.pool).await?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn seed(db: &Db) -> i64 {
        let now = crate::now();
        sqlx::query("INSERT INTO users (uuid, email, name, role, status, created_at, updated_at) VALUES ('u1','u@x.io','U','customer','active',?,?)")
            .bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        sqlx::query("INSERT INTO products (uuid, slug, type, title, created_at, updated_at) VALUES ('p1','film','video','Film',?,?)")
            .bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        1
    }

    #[tokio::test]
    async fn grants_are_idempotent_time_bound_and_revocable() {
        let db = Db::memory().await.unwrap();
        let user = seed(&db).await;
        let e = Entitlements::new(db);
        let g = Grant {
            user_id: user,
            product_id: Some(1),
            scope: "product",
            scope_ref: "",
            source: "order",
            source_ref: "1001:1",
            starts_at: "2026-01-01T00:00:00Z",
            ends_at: Some("2026-02-01T00:00:00Z"),
        };
        let a = e.grant(g.clone()).await.unwrap();
        let b = e.grant(g).await.unwrap();
        assert_eq!(a, b, "replaying an order event must not double-grant");
        assert_eq!(e.for_user(user).await.unwrap().len(), 1);
        assert!(e
            .check(user, &Subject::Product(1), "2026-01-15T00:00:00Z")
            .await
            .unwrap());
        assert!(
            !e.check(user, &Subject::Product(1), "2026-03-01T00:00:00Z")
                .await
                .unwrap(),
            "expired"
        );
        assert!(
            !e.check(user, &Subject::Product(2), "2026-01-15T00:00:00Z")
                .await
                .unwrap(),
            "other product"
        );
        assert_eq!(e.revoke_source("order", "1001:1").await.unwrap(), 1);
        assert!(
            !e.check(user, &Subject::Product(1), "2026-01-15T00:00:00Z")
                .await
                .unwrap(),
            "revoked"
        );

        let pass = Grant {
            user_id: user,
            product_id: None,
            scope: "site",
            scope_ref: "",
            source: "pass",
            source_ref: "sp-1",
            starts_at: "2026-01-01T00:00:00Z",
            ends_at: None,
        };
        e.grant(pass).await.unwrap();
        assert!(
            e.check(user, &Subject::Product(2), "2030-01-01T00:00:00Z")
                .await
                .unwrap(),
            "site pass covers everything"
        );
        assert!(e
            .check(user, &Subject::Page("terms".into()), "2030-01-01T00:00:00Z")
            .await
            .unwrap());
    }
}
