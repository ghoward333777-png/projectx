//! Google Business Profile: OAuth connection, locations, posts, reviews and
//! AI-drafted replies (Anthropic API). Pure helpers are tested; network calls run
//! against Google's REST APIs with the merchant's own OAuth client.

use crate::db::Db;
use anyhow::{bail, Context, Result};
use serde::Serialize;

pub const SCOPES: &str = "https://www.googleapis.com/auth/business.manage";

/// The Google consent URL for the merchant's OAuth client.
pub fn consent_url(client_id: &str, redirect_uri: &str, state: &str) -> String {
    let enc = crate::copyright_urlencode;
    format!(
        "https://accounts.google.com/o/oauth2/v2/auth?client_id={}&redirect_uri={}&response_type=code&scope={}&access_type=offline&prompt=consent&state={}",
        enc(client_id), enc(redirect_uri), enc(SCOPES), enc(state)
    )
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Account {
    pub id: i64,
    pub email: String,
    pub account_name: String,
    pub expires_at: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Location {
    pub id: i64,
    pub name: String,
    pub title: String,
    pub address: String,
    pub place_id: String,
    pub maps_url: String,
    pub synced_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Post {
    pub id: i64,
    pub uuid: String,
    pub location: String,
    pub summary: String,
    pub cta_type: String,
    pub cta_url: String,
    pub media_url: String,
    pub scheduled_at: Option<String>,
    pub status: String,
    pub remote_name: String,
    pub error: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Review {
    pub id: i64,
    pub remote_name: String,
    pub location: String,
    pub reviewer: String,
    pub rating: i64,
    pub comment: String,
    pub reply: String,
    pub draft_reply: String,
    pub reply_status: String,
    pub reviewed_at: String,
}

/// The prompt the AI gets for a review reply: brand voice, the review, hard rules.
pub fn reply_prompt(
    site_name: &str,
    tone: &str,
    reviewer: &str,
    rating: i64,
    comment: &str,
) -> String {
    format!(
        "You write short public replies to Google reviews for {site}. Tone: {tone}. Rules: thank the reviewer by first name if given; answer the specific points; never promise refunds, discounts or legal outcomes; never mention private data; at most 70 words; no hashtags; no emojis; end with an invitation to contact the studio directly for anything unresolved.\n\nReview by {reviewer} ({rating} of 5 stars):\n\"\"\"\n{comment}\n\"\"\"\n\nReply:",
        site = site_name, tone = if tone.is_empty() { "warm and professional" } else { tone }, reviewer = if reviewer.is_empty() { "a customer" } else { reviewer }, rating = rating, comment = comment.trim()
    )
}

#[derive(Clone)]
pub struct Google {
    db: Db,
    http: reqwest::Client,
}

impl Google {
    pub fn new(db: Db) -> Self {
        Self {
            db,
            http: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .expect("http"),
        }
    }

    // ----- OAuth -----

    pub async fn exchange_code(
        &self,
        client_id: &str,
        client_secret: &str,
        redirect_uri: &str,
        code: &str,
    ) -> Result<()> {
        let v: serde_json::Value = self
            .http
            .post("https://oauth2.googleapis.com/token")
            .form(&[
                ("code", code),
                ("client_id", client_id),
                ("client_secret", client_secret),
                ("redirect_uri", redirect_uri),
                ("grant_type", "authorization_code"),
            ])
            .send()
            .await
            .context("Google token request")?
            .json()
            .await?;
        let refresh = v["refresh_token"].as_str().context("Google did not return a refresh token; remove the app's access at myaccount.google.com/permissions and connect again")?;
        let access = v["access_token"].as_str().unwrap_or("");
        let expires = crate::commerce::add_days(&crate::now(), 0);
        let now = crate::now();
        sqlx::query("DELETE FROM google_accounts")
            .execute(&self.db.pool)
            .await?;
        sqlx::query("INSERT INTO google_accounts (email, refresh_token, access_token, expires_at, created_at, updated_at) VALUES ('', ?, ?, ?, ?, ?)")
            .bind(refresh).bind(access).bind(&expires).bind(&now).bind(&now).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn account(&self) -> Result<Option<Account>> {
        Ok(sqlx::query_as::<_, Account>("SELECT id, email, account_name, expires_at, created_at FROM google_accounts ORDER BY id DESC LIMIT 1").fetch_optional(&self.db.pool).await?)
    }

    pub async fn disconnect(&self) -> Result<()> {
        sqlx::query("DELETE FROM google_accounts")
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    async fn access_token(&self, client_id: &str, client_secret: &str) -> Result<String> {
        let row: Option<(String, String, String)> = sqlx::query_as("SELECT refresh_token, access_token, expires_at FROM google_accounts ORDER BY id DESC LIMIT 1").fetch_optional(&self.db.pool).await?;
        let Some((refresh, access, expires)) = row else {
            bail!("Google is not connected")
        };
        if !access.is_empty() && expires.as_str() > crate::now().as_str() {
            return Ok(access);
        }
        let v: serde_json::Value = self
            .http
            .post("https://oauth2.googleapis.com/token")
            .form(&[
                ("refresh_token", refresh.as_str()),
                ("client_id", client_id),
                ("client_secret", client_secret),
                ("grant_type", "refresh_token"),
            ])
            .send()
            .await
            .context("Google refresh")?
            .json()
            .await?;
        let access = v["access_token"]
            .as_str()
            .context("Google refused to refresh the token; connect again")?
            .to_string();
        let secs = v["expires_in"].as_i64().unwrap_or(3000).max(60) - 60;
        let expires = (chrono::Utc::now() + chrono::Duration::seconds(secs))
            .format("%Y-%m-%dT%H:%M:%SZ")
            .to_string();
        sqlx::query("UPDATE google_accounts SET access_token = ?, expires_at = ?, updated_at = ?")
            .bind(&access)
            .bind(&expires)
            .bind(crate::now())
            .execute(&self.db.pool)
            .await?;
        Ok(access)
    }

    async fn get(&self, token: &str, url: &str) -> Result<serde_json::Value> {
        let res = self
            .http
            .get(url)
            .bearer_auth(token)
            .send()
            .await
            .context("Google request")?;
        let status = res.status();
        let v: serde_json::Value = res.json().await.unwrap_or(serde_json::json!({}));
        if !status.is_success() {
            bail!(
                "Google: {}",
                v["error"]["message"].as_str().unwrap_or("request refused")
            );
        }
        Ok(v)
    }

    async fn send(
        &self,
        method: reqwest::Method,
        token: &str,
        url: &str,
        body: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let res = self
            .http
            .request(method, url)
            .bearer_auth(token)
            .json(&body)
            .send()
            .await
            .context("Google request")?;
        let status = res.status();
        let v: serde_json::Value = res.json().await.unwrap_or(serde_json::json!({}));
        if !status.is_success() {
            bail!(
                "Google: {}",
                v["error"]["message"].as_str().unwrap_or("request refused")
            );
        }
        Ok(v)
    }

    // ----- locations -----

    /// Pulls accounts and locations into `google_locations`.
    pub async fn sync_locations(&self, client_id: &str, client_secret: &str) -> Result<usize> {
        let token = self.access_token(client_id, client_secret).await?;
        let accounts = self
            .get(
                &token,
                "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
            )
            .await?;
        let mut n = 0;
        let now = crate::now();
        for a in accounts["accounts"].as_array().cloned().unwrap_or_default() {
            let name = a["name"].as_str().unwrap_or("");
            sqlx::query("UPDATE google_accounts SET account_name = ?, updated_at = ?")
                .bind(name)
                .bind(&now)
                .execute(&self.db.pool)
                .await?;
            let locs = self.get(&token, &format!("https://mybusinessbusinessinformation.googleapis.com/v1/{name}/locations?readMask=name,title,storefrontAddress,metadata")).await?;
            for l in locs["locations"].as_array().cloned().unwrap_or_default() {
                let addr = l["storefrontAddress"]["addressLines"]
                    .as_array()
                    .map(|a| {
                        a.iter()
                            .filter_map(|x| x.as_str())
                            .collect::<Vec<_>>()
                            .join(", ")
                    })
                    .unwrap_or_default();
                sqlx::query("INSERT INTO google_locations (name, title, address, place_id, maps_url, synced_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET title = excluded.title, address = excluded.address, place_id = excluded.place_id, maps_url = excluded.maps_url, synced_at = excluded.synced_at")
                    .bind(l["name"].as_str().unwrap_or("")).bind(l["title"].as_str().unwrap_or("")).bind(addr).bind(l["metadata"]["placeId"].as_str().unwrap_or("")).bind(l["metadata"]["mapsUri"].as_str().unwrap_or("")).bind(&now)
                    .execute(&self.db.pool).await?;
                n += 1;
            }
        }
        Ok(n)
    }

    pub async fn locations(&self) -> Result<Vec<Location>> {
        Ok(sqlx::query_as::<_, Location>("SELECT id, name, title, address, place_id, maps_url, synced_at FROM google_locations ORDER BY title").fetch_all(&self.db.pool).await?)
    }

    // ----- posts -----

    pub async fn create_post(
        &self,
        location: &str,
        summary: &str,
        cta_type: &str,
        cta_url: &str,
        media_url: &str,
        scheduled_at: Option<&str>,
    ) -> Result<Post> {
        if summary.trim().len() < 10 {
            bail!("Write at least a sentence for the post");
        }
        if summary.len() > 1500 {
            bail!("Google posts are limited to 1500 characters");
        }
        let now = crate::now();
        let uuid = uuid::Uuid::new_v4().to_string();
        let status = if scheduled_at.map(|s| !s.is_empty()).unwrap_or(false) {
            "scheduled"
        } else {
            "draft"
        };
        sqlx::query("INSERT INTO google_posts (uuid, location, summary, cta_type, cta_url, media_url, scheduled_at, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
            .bind(&uuid).bind(location).bind(summary.trim()).bind(cta_type).bind(cta_url).bind(media_url).bind(scheduled_at.filter(|s| !s.is_empty())).bind(status).bind(&now).bind(&now)
            .execute(&self.db.pool).await?;
        Ok(self.post_by_uuid(&uuid).await?.expect("just created"))
    }

    pub async fn post_by_uuid(&self, uuid: &str) -> Result<Option<Post>> {
        Ok(sqlx::query_as::<_, Post>("SELECT id, uuid, location, summary, cta_type, cta_url, media_url, scheduled_at, status, remote_name, error, created_at FROM google_posts WHERE uuid = ?").bind(uuid).fetch_optional(&self.db.pool).await?)
    }

    pub async fn posts(&self) -> Result<Vec<Post>> {
        Ok(sqlx::query_as::<_, Post>("SELECT id, uuid, location, summary, cta_type, cta_url, media_url, scheduled_at, status, remote_name, error, created_at FROM google_posts ORDER BY id DESC LIMIT 200").fetch_all(&self.db.pool).await?)
    }

    /// Posts that are due: scheduled in the past, or drafts asked to publish now.
    pub async fn due_posts(&self) -> Result<Vec<Post>> {
        Ok(sqlx::query_as::<_, Post>("SELECT id, uuid, location, summary, cta_type, cta_url, media_url, scheduled_at, status, remote_name, error, created_at FROM google_posts WHERE status = 'scheduled' AND (scheduled_at IS NULL OR scheduled_at <= ?)").bind(crate::now()).fetch_all(&self.db.pool).await?)
    }

    pub async fn mark_scheduled_now(&self, uuid: &str) -> Result<()> {
        sqlx::query("UPDATE google_posts SET status = 'scheduled', scheduled_at = ?, updated_at = ? WHERE uuid = ? AND status IN ('draft','failed')").bind(crate::now()).bind(crate::now()).bind(uuid).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn publish_post(
        &self,
        client_id: &str,
        client_secret: &str,
        post: &Post,
    ) -> Result<()> {
        let token = self.access_token(client_id, client_secret).await?;
        let mut body = serde_json::json!({ "languageCode": "en", "summary": post.summary, "topicType": "STANDARD" });
        if !post.cta_type.is_empty() && !post.cta_url.is_empty() {
            body["callToAction"] =
                serde_json::json!({ "actionType": post.cta_type, "url": post.cta_url });
        }
        if !post.media_url.is_empty() {
            body["media"] =
                serde_json::json!([{ "mediaFormat": "PHOTO", "sourceUrl": post.media_url }]);
        }
        let now = crate::now();
        match self
            .send(
                reqwest::Method::POST,
                &token,
                &format!(
                    "https://mybusiness.googleapis.com/v4/{}/localPosts",
                    post.location
                ),
                body,
            )
            .await
        {
            Ok(v) => {
                sqlx::query("UPDATE google_posts SET status = 'published', remote_name = ?, error = '', updated_at = ? WHERE id = ?").bind(v["name"].as_str().unwrap_or("")).bind(&now).bind(post.id).execute(&self.db.pool).await?;
                Ok(())
            }
            Err(e) => {
                sqlx::query("UPDATE google_posts SET status = 'failed', error = ?, updated_at = ? WHERE id = ?").bind(e.to_string()).bind(&now).bind(post.id).execute(&self.db.pool).await?;
                Err(e)
            }
        }
    }

    pub async fn delete_post(&self, uuid: &str) -> Result<()> {
        sqlx::query("DELETE FROM google_posts WHERE uuid = ?")
            .bind(uuid)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    // ----- reviews -----

    pub async fn sync_reviews(&self, client_id: &str, client_secret: &str) -> Result<usize> {
        let token = self.access_token(client_id, client_secret).await?;
        let now = crate::now();
        let mut n = 0;
        for loc in self.locations().await? {
            let account: String = sqlx::query_scalar(
                "SELECT account_name FROM google_accounts ORDER BY id DESC LIMIT 1",
            )
            .fetch_one(&self.db.pool)
            .await?;
            let v = self
                .get(
                    &token,
                    &format!(
                        "https://mybusiness.googleapis.com/v4/{account}/{}/reviews",
                        loc.name
                    ),
                )
                .await?;
            for r in v["reviews"].as_array().cloned().unwrap_or_default() {
                let rating = match r["starRating"].as_str().unwrap_or("") {
                    "ONE" => 1,
                    "TWO" => 2,
                    "THREE" => 3,
                    "FOUR" => 4,
                    "FIVE" => 5,
                    _ => 0,
                };
                let reply = r["reviewReply"]["comment"].as_str().unwrap_or("");
                sqlx::query("INSERT INTO google_reviews (remote_name, location, reviewer, rating, comment, reply, reply_status, reviewed_at, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(remote_name) DO UPDATE SET reply = excluded.reply, reply_status = CASE WHEN excluded.reply != '' THEN 'posted' ELSE google_reviews.reply_status END, synced_at = excluded.synced_at")
                    .bind(r["name"].as_str().unwrap_or("")).bind(&loc.name).bind(r["reviewer"]["displayName"].as_str().unwrap_or("")).bind(rating).bind(r["comment"].as_str().unwrap_or("")).bind(reply).bind(if reply.is_empty() { "none" } else { "posted" }).bind(r["createTime"].as_str().unwrap_or("")).bind(&now)
                    .execute(&self.db.pool).await?;
                n += 1;
            }
        }
        Ok(n)
    }

    pub async fn reviews(&self) -> Result<Vec<Review>> {
        Ok(sqlx::query_as::<_, Review>("SELECT id, remote_name, location, reviewer, rating, comment, reply, draft_reply, reply_status, reviewed_at FROM google_reviews ORDER BY reviewed_at DESC LIMIT 200").fetch_all(&self.db.pool).await?)
    }

    pub async fn review(&self, id: i64) -> Result<Option<Review>> {
        Ok(sqlx::query_as::<_, Review>("SELECT id, remote_name, location, reviewer, rating, comment, reply, draft_reply, reply_status, reviewed_at FROM google_reviews WHERE id = ?").bind(id).fetch_optional(&self.db.pool).await?)
    }

    /// Asks the Anthropic API for a reply draft and stores it for approval.
    pub async fn draft_reply(
        &self,
        api_key: &str,
        model: &str,
        site_name: &str,
        tone: &str,
        review_id: i64,
    ) -> Result<String> {
        let Some(r) = self.review(review_id).await? else {
            bail!("review missing")
        };
        if api_key.trim().is_empty() {
            bail!("Add an Anthropic API key under Settings → AI to draft replies");
        }
        let prompt = reply_prompt(site_name, tone, &r.reviewer, r.rating, &r.comment);
        let body = serde_json::json!({ "model": model, "max_tokens": 300, "messages": [{ "role": "user", "content": prompt }] });
        let res = self
            .http
            .post("https://api.anthropic.com/v1/messages")
            .header("x-api-key", api_key.trim())
            .header("anthropic-version", "2023-06-01")
            .header("content-type", "application/json")
            .json(&body)
            .send()
            .await
            .context("Anthropic request")?;
        let status = res.status();
        let v: serde_json::Value = res.json().await.unwrap_or(serde_json::json!({}));
        if !status.is_success() {
            bail!(
                "Anthropic: {}",
                v["error"]["message"].as_str().unwrap_or("request refused")
            );
        }
        let text = v["content"][0]["text"]
            .as_str()
            .unwrap_or("")
            .trim()
            .to_string();
        self.save_draft(review_id, &text).await?;
        Ok(text)
    }

    pub async fn save_draft(&self, review_id: i64, text: &str) -> Result<()> {
        sqlx::query(
            "UPDATE google_reviews SET draft_reply = ?, reply_status = 'drafted' WHERE id = ?",
        )
        .bind(text.trim())
        .bind(review_id)
        .execute(&self.db.pool)
        .await?;
        Ok(())
    }

    /// Posts the approved draft as the public reply.
    pub async fn post_reply(
        &self,
        client_id: &str,
        client_secret: &str,
        review_id: i64,
        text: &str,
    ) -> Result<()> {
        let Some(r) = self.review(review_id).await? else {
            bail!("review missing")
        };
        if text.trim().is_empty() {
            bail!("The reply is empty");
        }
        let token = self.access_token(client_id, client_secret).await?;
        let account: String =
            sqlx::query_scalar("SELECT account_name FROM google_accounts ORDER BY id DESC LIMIT 1")
                .fetch_one(&self.db.pool)
                .await?;
        match self
            .send(
                reqwest::Method::PUT,
                &token,
                &format!(
                    "https://mybusiness.googleapis.com/v4/{account}/{}/reply",
                    r.remote_name
                ),
                serde_json::json!({ "comment": text.trim() }),
            )
            .await
        {
            Ok(_) => {
                sqlx::query(
                    "UPDATE google_reviews SET reply = ?, reply_status = 'posted' WHERE id = ?",
                )
                .bind(text.trim())
                .bind(review_id)
                .execute(&self.db.pool)
                .await?;
                Ok(())
            }
            Err(e) => {
                sqlx::query("UPDATE google_reviews SET reply_status = 'failed' WHERE id = ?")
                    .bind(review_id)
                    .execute(&self.db.pool)
                    .await?;
                Err(e)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn consent_url_and_prompt() {
        let u = consent_url(
            "id.apps.googleusercontent.com",
            "https://site/mms/admin/google/callback",
            "st4te",
        );
        assert!(u.starts_with("https://accounts.google.com/o/oauth2/v2/auth?client_id=id.apps.googleusercontent.com&redirect_uri=https%3A%2F%2Fsite%2Fmms%2Fadmin%2Fgoogle%2Fcallback"));
        assert!(u.contains("access_type=offline") && u.contains("state=st4te"));
        let p = reply_prompt(
            "Demo Studio",
            "",
            "Ada",
            4,
            "Great lighting course, wish it was longer.",
        );
        assert!(
            p.contains("Demo Studio")
                && p.contains("warm and professional")
                && p.contains("Ada (4 of 5 stars)")
                && p.contains("at most 70 words")
        );
    }

    #[tokio::test]
    async fn posts_and_review_drafts_locally() {
        let db = Db::memory().await.unwrap();
        let g = Google::new(db.clone());
        assert!(g.account().await.unwrap().is_none());
        assert!(g
            .create_post("locations/1", "short", "", "", "", None)
            .await
            .is_err());
        let p = g
            .create_post(
                "locations/1",
                "New masterclass dates are out for October.",
                "LEARN_MORE",
                "https://demo.io",
                "",
                Some("2030-01-01T00:00:00Z"),
            )
            .await
            .unwrap();
        assert_eq!(p.status, "scheduled");
        assert!(g.due_posts().await.unwrap().is_empty(), "not due yet");
        g.mark_scheduled_now(&p.uuid).await.unwrap();
        assert!(
            g.due_posts().await.unwrap().is_empty(),
            "only drafts and failed posts move to now"
        );
        let now = crate::now();
        sqlx::query("INSERT INTO google_reviews (remote_name, location, reviewer, rating, comment, reviewed_at, synced_at) VALUES ('r1','locations/1','Ada',5,'Loved it',?,?)").bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        assert!(g
            .draft_reply("", "claude-opus-5", "Demo", "", 1)
            .await
            .unwrap_err()
            .to_string()
            .contains("API key"));
        g.save_draft(1, "Thank you, Ada!").await.unwrap();
        assert_eq!(g.review(1).await.unwrap().unwrap().reply_status, "drafted");
        assert!(g
            .post_reply("c", "s", 1, "Thanks")
            .await
            .unwrap_err()
            .to_string()
            .contains("not connected"));
    }
}
