//! Widgets: stored definitions with a version history, plus user-saved templates.

use crate::db::Db;
use crate::render::Definition;
use anyhow::{anyhow, Result};
use serde::Serialize;

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Widget {
    pub id: i64,
    pub uuid: String,
    pub name: String,
    pub definition: String,
    pub template_slug: Option<String>,
    pub custom_css: String,
    pub theme: String,
    pub scheme: String,
    pub status: String,
    pub version: i64,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Version {
    pub version: i64,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct UserTemplate {
    pub id: i64,
    pub slug: String,
    pub name: String,
    pub category: String,
    pub definition: String,
    pub custom_css: String,
}

#[derive(Clone)]
pub struct Widgets {
    db: Db,
}

const SELECT: &str = "SELECT id, uuid, name, definition, template_slug, custom_css, theme, scheme, status, version, created_at, updated_at FROM widgets";

impl Widgets {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub async fn create(
        &self,
        name: &str,
        definition: &str,
        template_slug: Option<&str>,
        created_by: Option<i64>,
    ) -> Result<Widget> {
        Definition::parse(definition).map_err(|e| anyhow!(e))?;
        let name = name.trim();
        anyhow::ensure!(!name.is_empty(), "a name is required");
        let now = crate::now();
        let uuid = uuid::Uuid::new_v4().to_string();
        let id = sqlx::query("INSERT INTO widgets (uuid, name, definition, template_slug, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
            .bind(&uuid).bind(name).bind(definition).bind(template_slug).bind(created_by).bind(&now).bind(&now)
            .execute(&self.db.pool).await?.last_insert_rowid();
        sqlx::query("INSERT INTO widget_versions (widget_id, version, definition, custom_css, created_at) VALUES (?, 1, ?, '', ?)")
            .bind(id).bind(definition).bind(&now).execute(&self.db.pool).await?;
        self.by_id(id)
            .await?
            .ok_or_else(|| anyhow!("widget vanished"))
    }

    /// Saves a new version. Name, theme, scheme and status are updated in place.
    #[allow(clippy::too_many_arguments)]
    pub async fn save(
        &self,
        id: i64,
        name: &str,
        definition: &str,
        custom_css: &str,
        theme: &str,
        scheme: &str,
        status: &str,
    ) -> Result<Widget> {
        Definition::parse(definition).map_err(|e| anyhow!(e))?;
        anyhow::ensure!(
            custom_css.len() <= 64 * 1024,
            "custom CSS is limited to 64 KB"
        );
        anyhow::ensure!(matches!(theme, "auto" | "light" | "dark"), "invalid theme");
        anyhow::ensure!(
            matches!(status, "draft" | "published" | "archived"),
            "invalid status"
        );
        let current = self
            .by_id(id)
            .await?
            .ok_or_else(|| anyhow!("widget not found"))?;
        let changed = current.definition != definition || current.custom_css != custom_css;
        let version = if changed {
            current.version + 1
        } else {
            current.version
        };
        let now = crate::now();
        sqlx::query("UPDATE widgets SET name = ?, definition = ?, custom_css = ?, theme = ?, scheme = ?, status = ?, version = ?, updated_at = ? WHERE id = ?")
            .bind(name.trim()).bind(definition).bind(custom_css).bind(theme).bind(scheme).bind(status).bind(version).bind(&now).bind(id)
            .execute(&self.db.pool).await?;
        if changed {
            sqlx::query("INSERT INTO widget_versions (widget_id, version, definition, custom_css, created_at) VALUES (?, ?, ?, ?, ?)")
                .bind(id).bind(version).bind(definition).bind(custom_css).bind(&now).execute(&self.db.pool).await?;
            // Keep the last 50 versions.
            sqlx::query("DELETE FROM widget_versions WHERE widget_id = ? AND version <= ? - 50")
                .bind(id)
                .bind(version)
                .execute(&self.db.pool)
                .await?;
        }
        self.by_id(id)
            .await?
            .ok_or_else(|| anyhow!("widget vanished"))
    }

    pub async fn versions(&self, id: i64) -> Result<Vec<Version>> {
        Ok(sqlx::query_as::<_, Version>("SELECT version, created_at FROM widget_versions WHERE widget_id = ? ORDER BY version DESC").bind(id).fetch_all(&self.db.pool).await?)
    }

    /// Restores an older version as a new version (history is never rewritten).
    pub async fn restore(&self, id: i64, version: i64) -> Result<Widget> {
        let row: Option<(String, String)> = sqlx::query_as("SELECT definition, custom_css FROM widget_versions WHERE widget_id = ? AND version = ?")
            .bind(id).bind(version).fetch_optional(&self.db.pool).await?;
        let (definition, css) = row.ok_or_else(|| anyhow!("version {version} not found"))?;
        let w = self
            .by_id(id)
            .await?
            .ok_or_else(|| anyhow!("widget not found"))?;
        self.save(
            id,
            &w.name,
            &definition,
            &css,
            &w.theme,
            &w.scheme,
            &w.status,
        )
        .await
    }

    pub async fn duplicate(&self, id: i64) -> Result<Widget> {
        let w = self
            .by_id(id)
            .await?
            .ok_or_else(|| anyhow!("widget not found"))?;
        let copy = self
            .create(
                &format!("{} (copy)", w.name),
                &w.definition,
                w.template_slug.as_deref(),
                None,
            )
            .await?;
        self.save(
            copy.id,
            &copy.name,
            &w.definition,
            &w.custom_css,
            &w.theme,
            &w.scheme,
            "draft",
        )
        .await
    }

    pub async fn delete(&self, id: i64) -> Result<()> {
        sqlx::query("DELETE FROM widgets WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn by_id(&self, id: i64) -> Result<Option<Widget>> {
        Ok(
            sqlx::query_as::<_, Widget>(&format!("{SELECT} WHERE id = ?"))
                .bind(id)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn by_uuid(&self, uuid: &str) -> Result<Option<Widget>> {
        Ok(
            sqlx::query_as::<_, Widget>(&format!("{SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn list(&self, q: &str, status: &str) -> Result<Vec<Widget>> {
        let like = format!("%{}%", q.trim());
        Ok(sqlx::query_as::<_, Widget>(&format!("{SELECT} WHERE (? = '' OR name LIKE ?) AND (? = '' OR status = ?) ORDER BY updated_at DESC LIMIT 500"))
            .bind(q.trim()).bind(&like).bind(status).bind(status).fetch_all(&self.db.pool).await?)
    }

    // ----- user templates -----

    pub async fn save_as_template(
        &self,
        id: i64,
        name: &str,
        category: &str,
    ) -> Result<UserTemplate> {
        let w = self
            .by_id(id)
            .await?
            .ok_or_else(|| anyhow!("widget not found"))?;
        let name = name.trim();
        anyhow::ensure!(!name.is_empty(), "a template name is required");
        let mut slug = format!("user-{}", crate::products::slugify(name));
        let mut n = 1;
        while sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM user_templates WHERE slug = ?")
            .bind(&slug)
            .fetch_one(&self.db.pool)
            .await?
            > 0
        {
            n += 1;
            slug = format!("user-{}-{n}", crate::products::slugify(name));
        }
        sqlx::query("INSERT INTO user_templates (slug, name, category, definition, custom_css, created_at) VALUES (?, ?, ?, ?, ?, ?)")
            .bind(&slug).bind(name).bind(if category.trim().is_empty() { "custom" } else { category.trim() }).bind(&w.definition).bind(&w.custom_css).bind(crate::now())
            .execute(&self.db.pool).await?;
        Ok(sqlx::query_as::<_, UserTemplate>("SELECT id, slug, name, category, definition, custom_css FROM user_templates WHERE slug = ?").bind(&slug).fetch_one(&self.db.pool).await?)
    }

    pub async fn import_template(
        &self,
        slug: &str,
        name: &str,
        category: &str,
        definition: &str,
        custom_css: &str,
    ) -> Result<UserTemplate> {
        Definition::parse(definition).map_err(|e| anyhow!(e))?;
        let slug = format!("user-{}", crate::products::slugify(slug));
        sqlx::query("INSERT INTO user_templates (slug, name, category, definition, custom_css, created_at) VALUES (?, ?, ?, ?, ?, ?)
                     ON CONFLICT(slug) DO UPDATE SET name = excluded.name, category = excluded.category, definition = excluded.definition, custom_css = excluded.custom_css")
            .bind(&slug).bind(name.trim()).bind(category.trim()).bind(definition).bind(custom_css).bind(crate::now())
            .execute(&self.db.pool).await?;
        Ok(sqlx::query_as::<_, UserTemplate>("SELECT id, slug, name, category, definition, custom_css FROM user_templates WHERE slug = ?").bind(&slug).fetch_one(&self.db.pool).await?)
    }

    pub async fn user_templates(&self) -> Result<Vec<UserTemplate>> {
        Ok(sqlx::query_as::<_, UserTemplate>("SELECT id, slug, name, category, definition, custom_css FROM user_templates ORDER BY name").fetch_all(&self.db.pool).await?)
    }

    pub async fn user_template(&self, slug: &str) -> Result<Option<UserTemplate>> {
        Ok(sqlx::query_as::<_, UserTemplate>("SELECT id, slug, name, category, definition, custom_css FROM user_templates WHERE slug = ?").bind(slug).fetch_optional(&self.db.pool).await?)
    }

    pub async fn delete_user_template(&self, slug: &str) -> Result<()> {
        sqlx::query("DELETE FROM user_templates WHERE slug = ?")
            .bind(slug)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn versions_restore_duplicate_and_templates() {
        let db = Db::memory().await.unwrap();
        let w = Widgets::new(db);
        let d1 = serde_json::to_string(&Definition::empty()).unwrap();
        let widget = w
            .create("Hero", &d1, Some("video-hero"), None)
            .await
            .unwrap();
        assert_eq!(widget.version, 1);
        let d2 = d1.replace("\"padding\":16", "\"padding\":32");
        let saved = w
            .save(
                widget.id,
                "Hero",
                &d2,
                "p{color:red}",
                "dark",
                "ocean",
                "published",
            )
            .await
            .unwrap();
        assert_eq!(saved.version, 2);
        let same = w
            .save(
                widget.id,
                "Hero renamed",
                &d2,
                "p{color:red}",
                "dark",
                "ocean",
                "published",
            )
            .await
            .unwrap();
        assert_eq!(same.version, 2, "unchanged definition makes no version");
        assert_eq!(same.name, "Hero renamed");
        assert_eq!(w.versions(widget.id).await.unwrap().len(), 2);
        let restored = w.restore(widget.id, 1).await.unwrap();
        assert_eq!(restored.version, 3);
        assert_eq!(restored.definition, d1);
        assert!(w
            .save(widget.id, "x", "{}", "", "auto", "default", "draft")
            .await
            .is_err());
        let copy = w.duplicate(widget.id).await.unwrap();
        assert_eq!(copy.name, "Hero renamed (copy)");
        assert_eq!(copy.status, "draft");
        let t = w
            .save_as_template(widget.id, "My hero", "hero")
            .await
            .unwrap();
        assert_eq!(t.slug, "user-my-hero");
        assert_eq!(w.user_templates().await.unwrap().len(), 1);
        w.delete(copy.id).await.unwrap();
        assert_eq!(w.list("", "").await.unwrap().len(), 1);
    }
}
