//! Support chat: remote support agents, conversations and the AI first-line assistant.
//!
//! Agents are people the administrator invites by link. They get a store account with
//! the `agent` flag and no role: they are neither staff (no admin pages) nor customers
//! (nothing to buy). Conversations are between a visitor (a signed-in customer or a
//! guest with a name and email) and, in turn, the assistant and an agent. The assistant
//! is Claude with four tools; it hands over to people the moment it is asked to or is
//! unsure. Everything is plain HTTP with polling, so it works through the CMS proxy.

use crate::db::Db;
use anyhow::{bail, Result};
use serde::Serialize;
use sha2::{Digest, Sha256};

pub const STATUSES: &[&str] = &["open", "waiting", "assigned", "closed"];
pub const INVITE_DAYS: i64 = 14;
/// An agent is "online" when its console polled within this many seconds.
pub const ONLINE_SECONDS: i64 = 120;
pub const ASSISTANT_MAX_TURNS: i64 = 4;

pub fn token_hash(token: &str) -> String {
    let d = Sha256::digest(token.as_bytes());
    d.iter().map(|b| format!("{b:02x}")).collect()
}

pub fn new_token() -> String {
    uuid::Uuid::new_v4().simple().to_string() + &uuid::Uuid::new_v4().simple().to_string()
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Invite {
    pub id: i64,
    pub email: String,
    pub name: String,
    pub invited_by: Option<i64>,
    pub status: String,
    pub created_at: String,
    pub expires_at: String,
    pub accepted_at: Option<String>,
    pub user_id: Option<i64>,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Conversation {
    pub id: i64,
    pub uuid: String,
    pub user_id: Option<i64>,
    pub guest_name: String,
    pub guest_email: String,
    pub visitor_token_hash: String,
    pub site_uuid: String,
    pub page_url: String,
    pub subject: String,
    pub status: String,
    pub assigned_to: Option<i64>,
    pub ai_turns: i64,
    pub rating: Option<i64>,
    pub rating_note: String,
    pub visitor_read_id: i64,
    pub agent_read_id: i64,
    pub created_at: String,
    pub updated_at: String,
    pub last_message_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct ChatMessage {
    pub id: i64,
    pub conversation_id: i64,
    pub sender: String,
    pub sender_id: Option<i64>,
    pub sender_name: String,
    pub body: String,
    pub internal: i64,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Agent {
    pub id: i64,
    pub uuid: String,
    pub email: String,
    pub name: String,
    pub role: String,
    pub agent: i64,
    pub last_seen_at: Option<String>,
}

const CONV_SELECT: &str = "SELECT id, uuid, user_id, guest_name, guest_email, visitor_token_hash, site_uuid, page_url, subject, status, assigned_to, ai_turns, rating, rating_note, visitor_read_id, agent_read_id, created_at, updated_at, last_message_at FROM chat_conversations";
const MSG_SELECT: &str = "SELECT id, conversation_id, sender, sender_id, sender_name, body, internal, created_at FROM chat_messages";

#[derive(Clone)]
pub struct Support {
    db: Db,
}

impl Support {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    // ----- agents and invites -----

    /// Creates an invite and returns the plain token (shown once, stored hashed).
    pub async fn create_invite(
        &self,
        email: &str,
        name: &str,
        invited_by: Option<i64>,
    ) -> Result<(Invite, String)> {
        let email = email.trim().to_lowercase();
        if !email.contains('@') {
            bail!("a valid email address is required");
        }
        let token = new_token();
        let now = crate::now();
        let expires = crate::commerce::add_days(&now, INVITE_DAYS);
        sqlx::query(
            "UPDATE agent_invites SET status = 'revoked' WHERE email = ? AND status = 'pending'",
        )
        .bind(&email)
        .execute(&self.db.pool)
        .await?;
        let id = sqlx::query("INSERT INTO agent_invites (token_hash, email, name, invited_by, status, created_at, expires_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)")
            .bind(token_hash(&token)).bind(&email).bind(name.trim()).bind(invited_by).bind(&now).bind(&expires)
            .execute(&self.db.pool).await?.last_insert_rowid();
        Ok((self.invite_by_id(id).await?.expect("just created"), token))
    }

    pub async fn invite_by_id(&self, id: i64) -> Result<Option<Invite>> {
        Ok(sqlx::query_as::<_, Invite>("SELECT id, email, name, invited_by, status, created_at, expires_at, accepted_at, user_id FROM agent_invites WHERE id = ?").bind(id).fetch_optional(&self.db.pool).await?)
    }

    /// The pending, unexpired invite for a plain token.
    pub async fn invite_by_token(&self, token: &str) -> Result<Option<Invite>> {
        let inv = sqlx::query_as::<_, Invite>("SELECT id, email, name, invited_by, status, created_at, expires_at, accepted_at, user_id FROM agent_invites WHERE token_hash = ?").bind(token_hash(token.trim())).fetch_optional(&self.db.pool).await?;
        Ok(inv.filter(|i| i.status == "pending" && i.expires_at.as_str() > crate::now().as_str()))
    }

    pub async fn invites(&self) -> Result<Vec<Invite>> {
        Ok(sqlx::query_as::<_, Invite>("SELECT id, email, name, invited_by, status, created_at, expires_at, accepted_at, user_id FROM agent_invites ORDER BY id DESC LIMIT 200").fetch_all(&self.db.pool).await?)
    }

    pub async fn revoke_invite(&self, id: i64) -> Result<()> {
        sqlx::query(
            "UPDATE agent_invites SET status = 'revoked' WHERE id = ? AND status = 'pending'",
        )
        .bind(id)
        .execute(&self.db.pool)
        .await?;
        Ok(())
    }

    pub async fn mark_invite_accepted(&self, id: i64, user_id: i64) -> Result<()> {
        sqlx::query("UPDATE agent_invites SET status = 'accepted', accepted_at = ?, user_id = ? WHERE id = ?").bind(crate::now()).bind(user_id).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }

    /// Everyone who can work the chat: flagged agents plus staff and administrators.
    pub async fn agents(&self) -> Result<Vec<Agent>> {
        Ok(sqlx::query_as::<_, Agent>("SELECT id, uuid, email, name, role, agent, last_seen_at FROM users WHERE status = 'active' AND (agent = 1 OR role IN ('admin','staff')) ORDER BY agent DESC, name").fetch_all(&self.db.pool).await?)
    }

    pub async fn online_agents(&self) -> Result<Vec<Agent>> {
        let cutoff = chrono::Utc::now() - chrono::Duration::seconds(ONLINE_SECONDS);
        let cutoff = cutoff.format("%Y-%m-%dT%H:%M:%SZ").to_string();
        Ok(self
            .agents()
            .await?
            .into_iter()
            .filter(|a| {
                a.last_seen_at
                    .as_deref()
                    .map(|t| t >= cutoff.as_str())
                    .unwrap_or(false)
            })
            .collect())
    }

    // ----- conversations -----

    #[allow(clippy::too_many_arguments)]
    pub async fn start(
        &self,
        user_id: Option<i64>,
        guest_name: &str,
        guest_email: &str,
        visitor_token: &str,
        site_uuid: &str,
        page_url: &str,
        subject: &str,
    ) -> Result<Conversation> {
        if user_id.is_none() {
            let email = guest_email.trim();
            if guest_name.trim().is_empty() || !email.contains('@') {
                bail!("Please give your name and a valid email address");
            }
        }
        let now = crate::now();
        let uuid = uuid::Uuid::new_v4().to_string();
        sqlx::query("INSERT INTO chat_conversations (uuid, user_id, guest_name, guest_email, visitor_token_hash, site_uuid, page_url, subject, status, created_at, updated_at, last_message_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)")
            .bind(&uuid).bind(user_id).bind(guest_name.trim()).bind(guest_email.trim().to_lowercase()).bind(if visitor_token.is_empty() { String::new() } else { token_hash(visitor_token) })
            .bind(site_uuid).bind(page_url.chars().take(300).collect::<String>()).bind(subject.trim().chars().take(140).collect::<String>()).bind(&now).bind(&now).bind(&now)
            .execute(&self.db.pool).await?;
        Ok(self.by_uuid(&uuid).await?.expect("just created"))
    }

    pub async fn by_uuid(&self, uuid: &str) -> Result<Option<Conversation>> {
        Ok(
            sqlx::query_as::<_, Conversation>(&format!("{CONV_SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn by_id(&self, id: i64) -> Result<Option<Conversation>> {
        Ok(
            sqlx::query_as::<_, Conversation>(&format!("{CONV_SELECT} WHERE id = ?"))
                .bind(id)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    /// May this visitor (signed-in user id, or the guest token) read the conversation?
    pub fn visitor_may_open(c: &Conversation, user_id: Option<i64>, visitor_token: &str) -> bool {
        match c.user_id {
            Some(uid) => user_id == Some(uid),
            None => {
                !c.visitor_token_hash.is_empty()
                    && !visitor_token.is_empty()
                    && c.visitor_token_hash == token_hash(visitor_token)
            }
        }
    }

    pub async fn list(
        &self,
        status: &str,
        assigned_to: Option<i64>,
        limit: i64,
    ) -> Result<Vec<Conversation>> {
        Ok(sqlx::query_as::<_, Conversation>(&format!("{CONV_SELECT} WHERE (? = '' OR status = ?) AND (? IS NULL OR assigned_to = ?) ORDER BY last_message_at DESC LIMIT ?"))
            .bind(status).bind(status).bind(assigned_to).bind(assigned_to).bind(limit).fetch_all(&self.db.pool).await?)
    }

    pub async fn for_visitor(&self, user_id: i64) -> Result<Vec<Conversation>> {
        Ok(sqlx::query_as::<_, Conversation>(&format!(
            "{CONV_SELECT} WHERE user_id = ? ORDER BY last_message_at DESC LIMIT 50"
        ))
        .bind(user_id)
        .fetch_all(&self.db.pool)
        .await?)
    }

    pub async fn counts(&self) -> Result<serde_json::Value> {
        let mut out = serde_json::Map::new();
        for s in STATUSES {
            let n: i64 =
                sqlx::query_scalar("SELECT COUNT(*) FROM chat_conversations WHERE status = ?")
                    .bind(s)
                    .fetch_one(&self.db.pool)
                    .await?;
            out.insert(s.to_string(), serde_json::json!(n));
        }
        let rated: (i64, Option<f64>) = sqlx::query_as(
            "SELECT COUNT(rating), AVG(rating) FROM chat_conversations WHERE rating IS NOT NULL",
        )
        .fetch_one(&self.db.pool)
        .await?;
        out.insert("rated".into(), serde_json::json!(rated.0));
        out.insert(
            "rating_avg".into(),
            serde_json::json!(rated.1.unwrap_or(0.0)),
        );
        let ai: i64 =
            sqlx::query_scalar("SELECT COALESCE(SUM(ai_turns), 0) FROM chat_conversations")
                .fetch_one(&self.db.pool)
                .await?;
        out.insert("assistant_replies".into(), serde_json::json!(ai));
        Ok(serde_json::Value::Object(out))
    }

    pub async fn add_message(
        &self,
        conv: &Conversation,
        sender: &str,
        sender_id: Option<i64>,
        sender_name: &str,
        body: &str,
        internal: bool,
    ) -> Result<ChatMessage> {
        let body = body.trim();
        if body.is_empty() {
            bail!("The message is empty");
        }
        let body: String = body.chars().take(4000).collect();
        let now = crate::now();
        let id = sqlx::query("INSERT INTO chat_messages (conversation_id, sender, sender_id, sender_name, body, internal, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
            .bind(conv.id).bind(sender).bind(sender_id).bind(sender_name).bind(&body).bind(internal as i64).bind(&now)
            .execute(&self.db.pool).await?.last_insert_rowid();
        sqlx::query("UPDATE chat_conversations SET last_message_at = ?, updated_at = ?, ai_turns = ai_turns + ?, visitor_read_id = CASE WHEN ? = 'visitor' THEN ? ELSE visitor_read_id END, agent_read_id = CASE WHEN ? = 'agent' THEN ? ELSE agent_read_id END WHERE id = ?")
            .bind(&now).bind(&now).bind((sender == "assistant") as i64).bind(sender).bind(id).bind(sender).bind(id).bind(conv.id).execute(&self.db.pool).await?;
        Ok(
            sqlx::query_as::<_, ChatMessage>(&format!("{MSG_SELECT} WHERE id = ?"))
                .bind(id)
                .fetch_one(&self.db.pool)
                .await?,
        )
    }

    /// Messages after `after`; internal notes only for agents.
    pub async fn messages(
        &self,
        conv_id: i64,
        after: i64,
        include_internal: bool,
    ) -> Result<Vec<ChatMessage>> {
        Ok(sqlx::query_as::<_, ChatMessage>(&format!(
            "{MSG_SELECT} WHERE conversation_id = ? AND id > ? AND (internal = 0 OR ?) ORDER BY id"
        ))
        .bind(conv_id)
        .bind(after)
        .bind(include_internal)
        .fetch_all(&self.db.pool)
        .await?)
    }

    pub async fn set_status(&self, id: i64, status: &str) -> Result<()> {
        if !STATUSES.contains(&status) {
            bail!("unknown status {status}");
        }
        sqlx::query("UPDATE chat_conversations SET status = ?, updated_at = ? WHERE id = ?")
            .bind(status)
            .bind(crate::now())
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn assign(&self, id: i64, agent_id: Option<i64>) -> Result<()> {
        sqlx::query("UPDATE chat_conversations SET assigned_to = ?, status = CASE WHEN ? IS NULL THEN 'waiting' ELSE 'assigned' END, updated_at = ? WHERE id = ? AND status <> 'closed'")
            .bind(agent_id).bind(agent_id).bind(crate::now()).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn mark_read(&self, id: i64, who: &str, message_id: i64) -> Result<()> {
        let col = if who == "agent" {
            "agent_read_id"
        } else {
            "visitor_read_id"
        };
        sqlx::query(&format!(
            "UPDATE chat_conversations SET {col} = MAX({col}, ?) WHERE id = ?"
        ))
        .bind(message_id)
        .bind(id)
        .execute(&self.db.pool)
        .await?;
        Ok(())
    }

    pub async fn rate(&self, id: i64, rating: i64, note: &str) -> Result<()> {
        if !(1..=5).contains(&rating) {
            bail!("rating must be 1 to 5");
        }
        sqlx::query("UPDATE chat_conversations SET rating = ?, rating_note = ?, updated_at = ? WHERE id = ?").bind(rating).bind(note.trim().chars().take(500).collect::<String>()).bind(crate::now()).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }
}

// ----- the assistant -----

/// What the assistant may tell visitors without a human: how the store works. The
/// store's own policy text (Settings → Support chat) is added at run time.
pub const HELP: &[(&str, &str)] = &[
    ("open", "Opening purchases: everything a customer bought is under My media (the My media link on the site, or the store's sign-in page). Videos and audio play in the player; images open full size with a download button when the product allows it; PDFs open in the page; live events show the stream during their window; meetings and consultations reveal their join link. A site pass opens the whole library until it ends."),
    ("receipts", "Receipts: every paid order has a numbered receipt as PDF and web page under My media → Orders, and it is emailed when the store has email set up. Orders placed through the site's own shop (WooCommerce or VirtueMart) also appear there."),
    ("passes", "Site passes: My media → Passes shows recurring passes; Cancel renewal keeps the pass open until the paid period ends and stops the next charge. Renewal notices appear 7, 3 and 1 days before a pass ends, with a Renew now button."),
    ("signin", "Signing in: members of the site use the My media link, which signs them in with their site account. Customers who registered at the store directly sign in at the store's sign-in page. Five failed attempts lock the address for thirty minutes."),
    ("downloads", "Downloads: a Download button appears when the product allows downloading. Protected images and videos may carry the buyer's email as a watermark; that is normal and identifies the copy as theirs."),
    ("refunds", "Refunds and cancellations are decided by the store's staff, never by the assistant. When a visitor asks for a refund, a chargeback, a cancellation of a paid order, or anything about money, hand over to an agent."),
    ("agreements", "Agreements: private pages ask visitors to sign an agreement first; the signed copy is under My media → Agreements. If the agreement text changed, signing again is required before the page opens."),
    ("privacy", "Privacy: customers can download everything the store holds about them and delete their account under My media → Privacy. Deleting removes personal details and access; order records stay for accounting without name or email."),
];

pub fn help(topic: &str) -> Option<&'static str> {
    HELP.iter().find(|(t, _)| *t == topic).map(|(_, h)| *h)
}

pub const ASSISTANT_RULES: &str = "You are the support assistant of a media store built with MediaMarketplace Studio. You talk to a visitor in the store's support chat. Be brief, warm and concrete: two to five sentences, plain language, no lists unless asked. Use read_help for how the store works and the store's policy text you were given. Use lookup_customer to see the visitor's own orders, passes and access when they are signed in; never guess about their records and never mention other customers. Hand over to a human agent with escalate when the visitor asks for a person, when money is involved (refunds, charges, cancellations), when their records show a problem you cannot fix, or when you are not sure. When the visitor's question is answered and they seem done, call resolve. Never invent order numbers, prices, dates or policies. Never claim to have changed anything: you cannot change accounts, orders or access.";

/// Tool definitions for the assistant's Messages API call.
pub fn assistant_tools() -> Vec<serde_json::Value> {
    serde_json::json!([
        { "name": "read_help", "description": "How the store works, by topic: open, receipts, passes, signin, downloads, refunds, agreements, privacy.", "input_schema": { "type": "object", "properties": { "topic": { "type": "string" } }, "required": ["topic"] } },
        { "name": "lookup_customer", "description": "The signed-in visitor's own account: orders with numbers and status, active passes and access, recent receipts. Returns 'guest' when the visitor is not signed in.", "input_schema": { "type": "object", "properties": {} } },
        { "name": "escalate", "description": "Hand the conversation to a human support agent. Give a one-line reason and a short summary for the agent.", "input_schema": { "type": "object", "properties": { "reason": { "type": "string" }, "summary": { "type": "string" } }, "required": ["reason"] } },
        { "name": "resolve", "description": "Mark the question as answered. The visitor can still write again.", "input_schema": { "type": "object", "properties": { "note": { "type": "string" } } } }
    ]).as_array().cloned().unwrap_or_default()
}

/// Turns the conversation into Messages API messages: visitor turns are user turns,
/// assistant and agent turns are assistant turns (agents' words are shown as such).
pub fn transcript_for_model(messages: &[ChatMessage]) -> Vec<serde_json::Value> {
    let mut out: Vec<serde_json::Value> = Vec::new();
    for m in messages.iter().filter(|m| m.internal == 0) {
        let (role, text) = match m.sender.as_str() {
            "visitor" => ("user", m.body.clone()),
            "agent" => (
                "assistant",
                format!("[Human agent {}]: {}", m.sender_name, m.body),
            ),
            "assistant" => ("assistant", m.body.clone()),
            _ => continue,
        };
        if let Some(last) = out.last_mut() {
            if last["role"] == role {
                let joined = format!("{}\n\n{}", last["content"].as_str().unwrap_or(""), text);
                last["content"] = serde_json::Value::String(joined);
                continue;
            }
        }
        out.push(serde_json::json!({ "role": role, "content": text }));
    }
    // The model must be answering a user turn.
    if out.last().map(|m| m["role"] == "assistant").unwrap_or(true) {
        out.push(serde_json::json!({ "role": "user", "content": "(The visitor is waiting.)" }));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn invites_conversations_and_messages() {
        let db = Db::memory().await.unwrap();
        let s = Support::new(db.clone());
        let users = crate::users::Users::new(db.clone());
        let owner = users
            .create(
                "owner@example.com",
                "Owner",
                Some("a-long-password"),
                "admin",
            )
            .await
            .unwrap();
        let sam = users
            .create("sam@example.com", "Sam", None, "customer")
            .await
            .unwrap();
        users.set_agent(sam.id, true).await.unwrap();
        assert!(users.by_id(sam.id).await.unwrap().unwrap().is_agent());
        assert_eq!(
            s.agents().await.unwrap().len(),
            2,
            "staff and flagged agents"
        );
        let (inv, token) = s
            .create_invite("Agent@Example.com", "Sam", Some(owner.id))
            .await
            .unwrap();
        assert_eq!(inv.email, "agent@example.com");
        assert!(s.invite_by_token(&token).await.unwrap().is_some());
        assert!(s.invite_by_token("nope").await.unwrap().is_none());
        s.mark_invite_accepted(inv.id, sam.id).await.unwrap();
        assert!(
            s.invite_by_token(&token).await.unwrap().is_none(),
            "accepted invites stop working"
        );
        assert!(s.create_invite("bad", "", None).await.is_err());

        assert!(
            s.start(None, "", "x", "tok", "", "", "").await.is_err(),
            "guests need a name and email"
        );
        let c = s
            .start(
                None,
                "Ada",
                "ada@example.com",
                "tok-1",
                "site-1",
                "https://site/store",
                "Cannot open my film",
            )
            .await
            .unwrap();
        assert!(Support::visitor_may_open(&c, None, "tok-1"));
        assert!(!Support::visitor_may_open(&c, None, "tok-2"));
        assert!(!Support::visitor_may_open(&c, Some(1), ""));
        let m1 = s
            .add_message(&c, "visitor", None, "Ada", "Hello?", false)
            .await
            .unwrap();
        let m2 = s
            .add_message(&c, "assistant", None, "Assistant", "Hi Ada.", false)
            .await
            .unwrap();
        let note = s
            .add_message(&c, "agent", Some(sam.id), "Sam", "internal note", true)
            .await
            .unwrap();
        assert_eq!(s.messages(c.id, 0, false).await.unwrap().len(), 2);
        assert_eq!(s.messages(c.id, m1.id, true).await.unwrap().len(), 2);
        assert_eq!(s.by_id(c.id).await.unwrap().unwrap().ai_turns, 1);
        assert_eq!(note.internal, 1);
        s.assign(c.id, Some(sam.id)).await.unwrap();
        assert_eq!(s.by_id(c.id).await.unwrap().unwrap().status, "assigned");
        s.assign(c.id, None).await.unwrap();
        assert_eq!(s.by_id(c.id).await.unwrap().unwrap().status, "waiting");
        s.set_status(c.id, "closed").await.unwrap();
        s.rate(c.id, 5, "great").await.unwrap();
        assert!(s.rate(c.id, 9, "").await.is_err());
        let counts = s.counts().await.unwrap();
        assert_eq!(counts["closed"], 1);
        assert_eq!(counts["rated"], 1);
        assert_eq!(m2.sender, "assistant");
        let t = transcript_for_model(&s.messages(c.id, 0, true).await.unwrap());
        assert_eq!(t.len(), 3, "{t:?}");
        assert_eq!(t[2]["content"], "(The visitor is waiting.)");
        assert!(help("refunds").unwrap().contains("hand over"));
        assert_eq!(assistant_tools().len(), 4);
    }
}
