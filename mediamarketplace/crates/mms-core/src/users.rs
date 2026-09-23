use crate::db::Db;
use crate::password;
use anyhow::{anyhow, Result};
use serde::Serialize;

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct User {
    pub id: i64,
    pub uuid: String,
    pub email: String,
    pub name: String,
    pub role: String,
    pub status: String,
    #[serde(skip)]
    pub password_hash: Option<String>,
}

impl User {
    pub fn is_admin(&self) -> bool {
        self.role == "admin" && self.status == "active"
    }
}

#[derive(Clone)]
pub struct Users {
    db: Db,
}

impl Users {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub async fn count_admins(&self) -> Result<i64> {
        Ok(
            sqlx::query_scalar("SELECT COUNT(*) FROM users WHERE role = 'admin'")
                .fetch_one(&self.db.pool)
                .await?,
        )
    }

    pub async fn create(
        &self,
        email: &str,
        name: &str,
        plain_password: Option<&str>,
        role: &str,
    ) -> Result<User> {
        let email = email.trim().to_lowercase();
        anyhow::ensure!(
            email.contains('@') && email.len() >= 5,
            "a valid email address is required"
        );
        anyhow::ensure!(
            matches!(role, "admin" | "staff" | "customer"),
            "invalid role"
        );
        let hash = match plain_password {
            Some(p) => Some(password::hash(p)?),
            None => None,
        };
        let now = crate::now();
        let uuid = uuid::Uuid::new_v4().to_string();
        let id = sqlx::query("INSERT INTO users (uuid, email, name, password_hash, role, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)")
            .bind(&uuid).bind(&email).bind(name.trim()).bind(hash).bind(role).bind(&now).bind(&now)
            .execute(&self.db.pool)
            .await
            .map_err(|e| if e.to_string().contains("UNIQUE") { anyhow!("a user with that email already exists") } else { e.into() })?
            .last_insert_rowid();
        self.by_id(id)
            .await?
            .ok_or_else(|| anyhow!("user vanished after insert"))
    }

    pub async fn by_id(&self, id: i64) -> Result<Option<User>> {
        Ok(sqlx::query_as::<_, User>(
            "SELECT id, uuid, email, name, role, status, password_hash FROM users WHERE id = ?",
        )
        .bind(id)
        .fetch_optional(&self.db.pool)
        .await?)
    }

    pub async fn by_email(&self, email: &str) -> Result<Option<User>> {
        Ok(sqlx::query_as::<_, User>(
            "SELECT id, uuid, email, name, role, status, password_hash FROM users WHERE email = ?",
        )
        .bind(email.trim().to_lowercase())
        .fetch_optional(&self.db.pool)
        .await?)
    }

    /// Returns the user when the email/password pair is valid and the account is active.
    pub async fn authenticate(&self, email: &str, plain: &str) -> Result<Option<User>> {
        let Some(user) = self.by_email(email).await? else {
            return Ok(None);
        };
        let Some(hash) = user.password_hash.as_deref() else {
            return Ok(None);
        };
        if user.status == "active" && password::verify(plain, hash) {
            Ok(Some(user))
        } else {
            Ok(None)
        }
    }

    /// Finds or creates the local user for a bridged host identity (single sign-on).
    pub async fn link_identity(
        &self,
        host: &str,
        external_id: &str,
        email: &str,
        name: &str,
    ) -> Result<User> {
        let existing: Option<i64> = sqlx::query_scalar(
            "SELECT user_id FROM user_identities WHERE host = ? AND external_id = ?",
        )
        .bind(host)
        .bind(external_id)
        .fetch_optional(&self.db.pool)
        .await?;
        if let Some(id) = existing {
            if let Some(u) = self.by_id(id).await? {
                return Ok(u);
            }
        }
        let user = match self.by_email(email).await? {
            Some(u) => u,
            None => self.create(email, name, None, "customer").await?,
        };
        sqlx::query("INSERT OR IGNORE INTO user_identities (user_id, host, external_id, created_at) VALUES (?, ?, ?, ?)")
            .bind(user.id).bind(host).bind(external_id).bind(crate::now())
            .execute(&self.db.pool).await?;
        Ok(user)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn create_authenticate_and_link() {
        let db = Db::memory().await.unwrap();
        let users = Users::new(db);
        assert_eq!(users.count_admins().await.unwrap(), 0);
        let admin = users
            .create(
                "Admin@Example.com",
                "Admin",
                Some("a-long-password"),
                "admin",
            )
            .await
            .unwrap();
        assert_eq!(admin.email, "admin@example.com");
        assert!(admin.is_admin());
        assert_eq!(users.count_admins().await.unwrap(), 1);
        assert!(users
            .authenticate("admin@example.com", "a-long-password")
            .await
            .unwrap()
            .is_some());
        assert!(users
            .authenticate("admin@example.com", "nope")
            .await
            .unwrap()
            .is_none());
        assert!(users
            .create(
                "admin@example.com",
                "Dup",
                Some("another-password"),
                "admin"
            )
            .await
            .is_err());

        let linked = users
            .link_identity("wordpress", "7", "shopper@example.com", "Shopper")
            .await
            .unwrap();
        assert_eq!(linked.role, "customer");
        let again = users
            .link_identity("wordpress", "7", "changed@example.com", "X")
            .await
            .unwrap();
        assert_eq!(again.id, linked.id);
        let by_email = users
            .link_identity("joomla", "99", "shopper@example.com", "Shopper")
            .await
            .unwrap();
        assert_eq!(by_email.id, linked.id);
    }
}
