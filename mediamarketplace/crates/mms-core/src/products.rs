//! Products: the ten media product types, categories, ratings and showcase queries.

use crate::db::Db;
use anyhow::{anyhow, Result};
use serde::Serialize;

pub const TYPES: &[(&str, &str)] = &[
    ("video", "Video"),
    ("audio", "Audio"),
    ("image", "Image"),
    ("pdf", "PDF"),
    ("live", "Live video"),
    ("private_page", "Private page"),
    ("site_pass", "Site pass"),
    ("meeting", "Meeting"),
    ("consultation", "Consultation"),
    ("external", "External page"),
];

pub fn type_label(t: &str) -> &'static str {
    TYPES
        .iter()
        .find(|(k, _)| *k == t)
        .map(|(_, l)| *l)
        .unwrap_or("Product")
}

/// Which settings each type exposes in the admin form. `(key, label, kind, help)`.
pub fn settings_fields(
    t: &str,
) -> &'static [(&'static str, &'static str, &'static str, &'static str)] {
    match t {
        "video" => &[
            ("preview_start", "Preview clip start (seconds)", "int", "Hover preview and free sample start here."),
            ("preview_length", "Preview clip length (seconds)", "int", "0 disables the preview."),
            ("download_allowed", "Allow download after purchase", "bool", ""),
            ("player", "Player", "player", "Leave empty for the store default."),
        ],
        "audio" => &[
            ("preview_start", "Preview clip start (seconds)", "int", ""),
            ("preview_length", "Preview clip length (seconds)", "int", "0 disables the preview."),
            ("download_allowed", "Allow download after purchase", "bool", ""),
            ("visualiser", "Visualiser", "select:bars,wave,circle,none", ""),
            ("player", "Player", "player", ""),
        ],
        "image" => &[
            ("resolutions", "Resolutions for sale", "text", "Comma separated widths, e.g. 1920,3840,original"),
            ("licence", "Licence text", "textarea", ""),
        ],
        "pdf" => &[
            ("preview_pages", "Free preview pages", "int", ""),
            ("download_allowed", "Allow download", "bool", ""),
            ("print_allowed", "Allow printing", "bool", ""),
            ("stamp_buyer", "Stamp buyer name on downloads", "bool", ""),
        ],
        "live" => &[
            ("provider", "Provider", "select:youtube,vimeo,mux,custom", ""),
            ("stream_url", "Stream or embed URL", "text", ""),
            ("starts_at", "Starts (UTC, YYYY-MM-DD HH:MM)", "text", ""),
            ("ends_at", "Ends (UTC, YYYY-MM-DD HH:MM)", "text", ""),
            ("chat_embed", "Chat embed URL", "text", ""),
        ],
        "private_page" => &[
            ("page_uuid", "Private page", "text", "The page this product unlocks (Phase 3)."),
            ("signup_template", "Signup template", "select:simple_cta,terms_highlighted,dual_action,checkbox,consent_first,third_party,progressive,incentive,legal,gamified", ""),
        ],
        "site_pass" => &[
            ("validity", "Validity", "select:days,date,lifetime,recurring", ""),
            ("days", "Days (when validity is days)", "int", ""),
            ("until", "End date (when validity is date)", "text", "YYYY-MM-DD"),
            ("interval", "Renewal interval (when validity is recurring)", "select:month,year", "Recurring passes are billed through Stripe."),
            ("scope", "Scope", "select:site,categories", ""),
        ],
        "meeting" => &[
            ("provider", "Provider", "select:zoom,google_meet,jitsi,custom", ""),
            ("join_url", "Join link (revealed after purchase)", "text", ""),
            ("duration_minutes", "Duration (minutes)", "int", ""),
            ("capacity", "Seats", "int", ""),
        ],
        "consultation" => &[
            ("provider", "Provider", "select:zoom,google_meet,jitsi,custom", ""),
            ("join_url", "Join link (revealed after booking)", "text", ""),
            ("duration_minutes", "Duration (minutes)", "int", ""),
            ("intake_questions", "Intake questions (one per line)", "textarea", ""),
        ],
        "external" => &[
            ("external_url", "External URL (revealed after purchase)", "text", ""),
            ("open_in", "Open in", "select:new_tab,same_tab", ""),
            ("disclosure", "Disclosure text", "textarea", ""),
        ],
        _ => &[],
    }
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Product {
    pub id: i64,
    pub uuid: String,
    pub slug: String,
    pub r#type: String,
    pub title: String,
    pub description: Option<String>,
    pub price_cents: i64,
    pub currency: String,
    pub media_id: Option<i64>,
    pub preview_media_id: Option<i64>,
    pub settings: Option<String>,
    pub featured: i64,
    pub rating_avg: f64,
    pub rating_count: i64,
    pub purchases: i64,
    pub views: i64,
    pub status: String,
    pub created_at: String,
}

impl Product {
    pub fn settings_json(&self) -> serde_json::Value {
        self.settings
            .as_deref()
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or_else(|| serde_json::json!({}))
    }
    pub fn setting(&self, key: &str) -> String {
        self.settings_json()
            .get(key)
            .map(|v| match v {
                serde_json::Value::String(s) => s.clone(),
                other => other.to_string(),
            })
            .unwrap_or_default()
    }
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Category {
    pub id: i64,
    pub slug: String,
    pub name: String,
    pub icon: Option<String>,
    pub sort_order: i64,
}

#[derive(Debug, Clone, Default)]
pub struct ProductDraft {
    pub r#type: String,
    pub title: String,
    pub slug: String,
    pub description: String,
    pub price_cents: i64,
    pub currency: String,
    pub media_id: Option<i64>,
    pub preview_media_id: Option<i64>,
    pub settings: serde_json::Value,
    pub featured: bool,
    pub status: String,
    pub category_ids: Vec<i64>,
}

#[derive(Debug, Default, Clone)]
pub struct ShowcaseQuery {
    pub q: String,
    pub r#type: String,
    pub category: String,
    pub sort: String,
    pub featured_only: bool,
    pub page: i64,
    pub per_page: i64,
}

/// A showcase card: product plus resolved thumbnail.
#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Card {
    pub uuid: String,
    pub slug: String,
    pub r#type: String,
    pub title: String,
    pub description: Option<String>,
    pub price_cents: i64,
    pub currency: String,
    pub featured: i64,
    pub rating_avg: f64,
    pub rating_count: i64,
    pub purchases: i64,
    pub thumbnail_path: Option<String>,
    pub duration_ms: Option<i64>,
    pub created_at: String,
}

pub fn slugify(s: &str) -> String {
    let mut out = String::new();
    let mut dash = false;
    for c in s.to_lowercase().chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c);
            dash = false;
        } else if !dash && !out.is_empty() {
            out.push('-');
            dash = true;
        }
    }
    out.trim_end_matches('-').to_string()
}

#[derive(Clone)]
pub struct Products {
    db: Db,
}

impl Products {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    fn validate(d: &ProductDraft) -> Result<()> {
        anyhow::ensure!(
            TYPES.iter().any(|(k, _)| *k == d.r#type),
            "unknown product type"
        );
        anyhow::ensure!(!d.title.trim().is_empty(), "a title is required");
        anyhow::ensure!(d.price_cents >= 0, "price must not be negative");
        anyhow::ensure!(
            d.currency.len() == 3,
            "currency must be a three-letter code"
        );
        anyhow::ensure!(
            matches!(d.status.as_str(), "draft" | "published" | "archived"),
            "invalid status"
        );
        if matches!(d.r#type.as_str(), "video" | "audio" | "image" | "pdf") {
            anyhow::ensure!(
                d.media_id.is_some(),
                "{} products need a media file",
                type_label(&d.r#type)
            );
        }
        Ok(())
    }

    pub async fn create(&self, d: &ProductDraft) -> Result<Product> {
        Self::validate(d)?;
        let mut slug = if d.slug.trim().is_empty() {
            slugify(&d.title)
        } else {
            slugify(&d.slug)
        };
        if slug.is_empty() {
            slug = "product".into();
        }
        // Make the slug unique.
        let base = slug.clone();
        let mut n = 1;
        while sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM products WHERE slug = ?")
            .bind(&slug)
            .fetch_one(&self.db.pool)
            .await?
            > 0
        {
            n += 1;
            slug = format!("{base}-{n}");
        }
        let now = crate::now();
        let id = sqlx::query(
            "INSERT INTO products (uuid, slug, type, title, description, price_cents, currency, media_id, preview_media_id, settings, featured, status, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(uuid::Uuid::new_v4().to_string()).bind(&slug).bind(&d.r#type).bind(d.title.trim()).bind(d.description.trim()).bind(d.price_cents)
        .bind(d.currency.to_uppercase()).bind(d.media_id).bind(d.preview_media_id).bind(d.settings.to_string()).bind(d.featured as i64).bind(&d.status).bind(&now).bind(&now)
        .execute(&self.db.pool).await?.last_insert_rowid();
        self.set_categories(id, &d.category_ids).await?;
        self.by_id(id)
            .await?
            .ok_or_else(|| anyhow!("product vanished"))
    }

    /// Updates everything except the type once the product has sales.
    pub async fn update(&self, id: i64, d: &ProductDraft) -> Result<()> {
        Self::validate(d)?;
        let current = self
            .by_id(id)
            .await?
            .ok_or_else(|| anyhow!("product not found"))?;
        if current.purchases > 0 && current.r#type != d.r#type {
            anyhow::bail!("the type cannot change after the first sale");
        }
        let slug = if d.slug.trim().is_empty() {
            current.slug.clone()
        } else {
            slugify(&d.slug)
        };
        let clash: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM products WHERE slug = ? AND id <> ?")
                .bind(&slug)
                .bind(id)
                .fetch_one(&self.db.pool)
                .await?;
        anyhow::ensure!(clash == 0, "another product already uses that slug");
        sqlx::query("UPDATE products SET slug = ?, type = ?, title = ?, description = ?, price_cents = ?, currency = ?, media_id = ?, preview_media_id = ?, settings = ?, featured = ?, status = ?, updated_at = ? WHERE id = ?")
            .bind(&slug).bind(&d.r#type).bind(d.title.trim()).bind(d.description.trim()).bind(d.price_cents).bind(d.currency.to_uppercase()).bind(d.media_id).bind(d.preview_media_id)
            .bind(d.settings.to_string()).bind(d.featured as i64).bind(&d.status).bind(crate::now()).bind(id)
            .execute(&self.db.pool).await?;
        self.set_categories(id, &d.category_ids).await?;
        Ok(())
    }

    async fn set_categories(&self, id: i64, cats: &[i64]) -> Result<()> {
        sqlx::query("DELETE FROM product_categories WHERE product_id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        for c in cats {
            sqlx::query(
                "INSERT OR IGNORE INTO product_categories (product_id, category_id) VALUES (?, ?)",
            )
            .bind(id)
            .bind(c)
            .execute(&self.db.pool)
            .await?;
        }
        Ok(())
    }

    pub async fn category_ids(&self, id: i64) -> Result<Vec<i64>> {
        Ok(
            sqlx::query_scalar("SELECT category_id FROM product_categories WHERE product_id = ?")
                .bind(id)
                .fetch_all(&self.db.pool)
                .await?,
        )
    }

    pub async fn delete(&self, id: i64) -> Result<()> {
        sqlx::query("DELETE FROM products WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn by_id(&self, id: i64) -> Result<Option<Product>> {
        Ok(
            sqlx::query_as::<_, Product>(&format!("{SELECT} WHERE id = ?"))
                .bind(id)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn by_slug(&self, slug: &str) -> Result<Option<Product>> {
        Ok(
            sqlx::query_as::<_, Product>(&format!("{SELECT} WHERE slug = ?"))
                .bind(slug)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn by_uuid(&self, uuid: &str) -> Result<Option<Product>> {
        Ok(
            sqlx::query_as::<_, Product>(&format!("{SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    /// Admin list: every status, newest first.
    pub async fn list_admin(&self, q: &str, r#type: &str, status: &str) -> Result<Vec<Product>> {
        let like = format!("%{}%", q.trim());
        Ok(sqlx::query_as::<_, Product>(&format!("{SELECT} WHERE (? = '' OR title LIKE ?) AND (? = '' OR type = ?) AND (? = '' OR status = ?) ORDER BY id DESC LIMIT 500"))
            .bind(q.trim()).bind(&like).bind(r#type).bind(r#type).bind(status).bind(status)
            .fetch_all(&self.db.pool).await?)
    }

    /// Storefront query: published products with search, filters, sort and paging.
    pub async fn showcase(&self, q: &ShowcaseQuery) -> Result<(Vec<Card>, i64)> {
        let per = q.per_page.clamp(1, 96);
        let page = q.page.max(1);
        let like = format!("%{}%", q.q.trim());
        let order = match q.sort.as_str() {
            "price_asc" => "p.price_cents ASC, p.id DESC",
            "price_desc" => "p.price_cents DESC, p.id DESC",
            "rating" => "p.rating_avg DESC, p.rating_count DESC, p.id DESC",
            "bestselling" => "p.purchases DESC, p.id DESC",
            "az" => "p.title COLLATE NOCASE ASC",
            _ => "p.featured DESC, p.id DESC",
        };
        let where_sql = "p.status = 'published' AND (? = '' OR p.title LIKE ? OR p.description LIKE ?) AND (? = '' OR p.type = ?) AND (? = 0 OR p.featured = 1)
            AND (? = '' OR EXISTS (SELECT 1 FROM product_categories pc JOIN categories c ON c.id = pc.category_id WHERE pc.product_id = p.id AND c.slug = ?))";
        let total: i64 = sqlx::query_scalar(&format!(
            "SELECT COUNT(*) FROM products p WHERE {where_sql}"
        ))
        .bind(q.q.trim())
        .bind(&like)
        .bind(&like)
        .bind(&q.r#type)
        .bind(&q.r#type)
        .bind(q.featured_only as i64)
        .bind(&q.category)
        .bind(&q.category)
        .fetch_one(&self.db.pool)
        .await?;
        let rows = sqlx::query_as::<_, Card>(&format!(
            "SELECT p.uuid, p.slug, p.type, p.title, p.description, p.price_cents, p.currency, p.featured, p.rating_avg, p.rating_count, p.purchases,
                    COALESCE(pm.thumbnail_path, m.thumbnail_path) AS thumbnail_path, m.duration_ms, p.created_at
             FROM products p LEFT JOIN media m ON m.id = p.media_id LEFT JOIN media pm ON pm.id = p.preview_media_id
             WHERE {where_sql} ORDER BY {order} LIMIT ? OFFSET ?"))
            .bind(q.q.trim()).bind(&like).bind(&like).bind(&q.r#type).bind(&q.r#type).bind(q.featured_only as i64).bind(&q.category).bind(&q.category).bind(per).bind((page - 1) * per)
            .fetch_all(&self.db.pool).await?;
        Ok((rows, total))
    }

    pub async fn record_view(&self, id: i64) -> Result<()> {
        sqlx::query("UPDATE products SET views = views + 1 WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    // ----- categories -----

    pub async fn categories(&self) -> Result<Vec<Category>> {
        Ok(sqlx::query_as::<_, Category>(
            "SELECT id, slug, name, icon, sort_order FROM categories ORDER BY sort_order, name",
        )
        .fetch_all(&self.db.pool)
        .await?)
    }

    pub async fn create_category(&self, name: &str) -> Result<Category> {
        let name = name.trim();
        anyhow::ensure!(!name.is_empty(), "a category name is required");
        let slug = slugify(name);
        sqlx::query("INSERT INTO categories (slug, name, created_at) VALUES (?, ?, ?)")
            .bind(&slug)
            .bind(name)
            .bind(crate::now())
            .execute(&self.db.pool)
            .await
            .map_err(|e| {
                if e.to_string().contains("UNIQUE") {
                    anyhow!("that category already exists")
                } else {
                    e.into()
                }
            })?;
        Ok(sqlx::query_as::<_, Category>(
            "SELECT id, slug, name, icon, sort_order FROM categories WHERE slug = ?",
        )
        .bind(&slug)
        .fetch_one(&self.db.pool)
        .await?)
    }

    pub async fn delete_category(&self, id: i64) -> Result<()> {
        sqlx::query("DELETE FROM categories WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    // ----- ratings -----

    /// One rating per user per product; approved ratings update the aggregate.
    pub async fn rate(
        &self,
        product_id: i64,
        user_id: i64,
        stars: i64,
        review: &str,
        auto_approve: bool,
    ) -> Result<()> {
        anyhow::ensure!((1..=5).contains(&stars), "stars must be between 1 and 5");
        let status = if auto_approve { "approved" } else { "pending" };
        sqlx::query("INSERT INTO ratings (product_id, user_id, stars, review, status, created_at) VALUES (?, ?, ?, ?, ?, ?)
                     ON CONFLICT(product_id, user_id) DO UPDATE SET stars = excluded.stars, review = excluded.review, status = excluded.status, created_at = excluded.created_at")
            .bind(product_id).bind(user_id).bind(stars).bind(review.trim()).bind(status).bind(crate::now())
            .execute(&self.db.pool).await?;
        self.recompute_rating(product_id).await
    }

    pub async fn recompute_rating(&self, product_id: i64) -> Result<()> {
        sqlx::query("UPDATE products SET rating_avg = COALESCE((SELECT AVG(stars) FROM ratings WHERE product_id = ? AND status = 'approved'), 0),
                                         rating_count = (SELECT COUNT(*) FROM ratings WHERE product_id = ? AND status = 'approved') WHERE id = ?")
            .bind(product_id).bind(product_id).bind(product_id)
            .execute(&self.db.pool).await?;
        Ok(())
    }
}

const SELECT: &str = "SELECT id, uuid, slug, type, title, description, price_cents, currency, media_id, preview_media_id, settings, featured, rating_avg, rating_count, purchases, views, status, created_at FROM products";

#[cfg(test)]
mod tests {
    use super::*;

    fn draft(t: &str, title: &str, price: i64) -> ProductDraft {
        ProductDraft {
            r#type: t.into(),
            title: title.into(),
            slug: String::new(),
            description: "d".into(),
            price_cents: price,
            currency: "usd".into(),
            media_id: None,
            preview_media_id: None,
            settings: serde_json::json!({}),
            featured: false,
            status: "published".into(),
            category_ids: vec![],
        }
    }

    #[tokio::test]
    async fn create_search_sort_categories_and_ratings() {
        let db = Db::memory().await.unwrap();
        let now = crate::now();
        sqlx::query("INSERT INTO users (uuid, email, name, role, status, created_at, updated_at) VALUES ('u','u@x.io','U','customer','active',?,?)").bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        let p = Products::new(db);
        assert!(
            p.create(&draft("video", "Film", 100)).await.is_err(),
            "video needs media"
        );
        let pass = p
            .create(&draft("site_pass", "All Access Pass", 14900))
            .await
            .unwrap();
        assert_eq!(pass.slug, "all-access-pass");
        assert_eq!(pass.currency, "USD");
        let pass2 = p
            .create(&draft("site_pass", "All Access Pass", 100))
            .await
            .unwrap();
        assert_eq!(pass2.slug, "all-access-pass-2", "slugs stay unique");
        let cat = p.create_category("Courses").await.unwrap();
        let mut d = draft("meeting", "Coaching call", 5000);
        d.category_ids = vec![cat.id];
        d.featured = true;
        let meeting = p.create(&d).await.unwrap();
        assert_eq!(p.category_ids(meeting.id).await.unwrap(), vec![cat.id]);

        let (cards, total) = p
            .showcase(&ShowcaseQuery {
                per_page: 10,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!(total, 3);
        assert_eq!(cards[0].slug, "coaching-call", "featured first");
        let (cards, _) = p
            .showcase(&ShowcaseQuery {
                sort: "price_asc".into(),
                per_page: 10,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!(cards[0].price_cents, 100);
        let (cards, _) = p
            .showcase(&ShowcaseQuery {
                category: "courses".into(),
                per_page: 10,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!(cards.len(), 1);
        let (cards, _) = p
            .showcase(&ShowcaseQuery {
                q: "coach".into(),
                per_page: 10,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!(cards.len(), 1);
        let (_, total) = p
            .showcase(&ShowcaseQuery {
                r#type: "site_pass".into(),
                per_page: 10,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!(total, 2);

        p.rate(meeting.id, 1, 4, "Good", true).await.unwrap();
        p.rate(meeting.id, 1, 5, "Great", true).await.unwrap();
        let m = p.by_id(meeting.id).await.unwrap().unwrap();
        assert_eq!(
            (m.rating_avg, m.rating_count),
            (5.0, 1),
            "one rating per user, updated in place"
        );
        assert!(p.rate(meeting.id, 1, 9, "", true).await.is_err());

        let mut upd = draft("meeting", "Coaching call", 6000);
        upd.status = "draft".into();
        p.update(meeting.id, &upd).await.unwrap();
        let (_, total) = p
            .showcase(&ShowcaseQuery {
                per_page: 10,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!(total, 2, "drafts are hidden");
        p.delete(meeting.id).await.unwrap();
        assert!(p.by_id(meeting.id).await.unwrap().is_none());
    }
}
