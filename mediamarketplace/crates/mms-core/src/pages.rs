//! Private pages: gated content behind a signup template, an agreement and, when
//! the page is paid, the linked product. Access keys, attempt limiting, lockouts
//! and the signed-agreement PDF live here too.

use crate::db::Db;
use crate::entitlements::{Entitlements, Grant, Subject};
use anyhow::{bail, Result};
use serde::Serialize;
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Page {
    pub id: i64,
    pub uuid: String,
    pub title: String,
    pub content: String,
    pub agreement: String,
    pub agreement_version: i64,
    pub signup_template: String,
    pub protection: String,
    pub product_id: Option<i64>,
    pub incentive: String,
    pub quiz_question: String,
    pub quiz_answer: String,
    pub jurisdiction: String,
    pub min_age: i64,
    pub status: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Agreement {
    pub id: i64,
    pub uuid: String,
    pub page_id: i64,
    pub user_id: i64,
    pub agreement_version: i64,
    pub agreement_hash: String,
    pub signer_name: String,
    pub method: String,
    pub confirmations: String,
    pub ip: String,
    pub user_agent: String,
    pub status: String,
    pub signed_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct AccessKey {
    pub id: i64,
    pub page_id: i64,
    pub hint: String,
    pub max_uses: i64,
    pub uses: i64,
    pub expires_at: Option<String>,
    pub status: String,
    pub created_at: String,
}

/// The ten signup templates and the confirmations each one requires the server
/// to see before a signature counts.
pub const SIGNUP_TEMPLATES: &[(&str, &str, &[&str], &str)] = &[
    (
        "simple_cta",
        "Simple CTA",
        &["agree"],
        "A headline, the agreement and one button.",
    ),
    (
        "terms_highlighted",
        "Terms highlighted",
        &["agree"],
        "Key terms as bullets above the button.",
    ),
    (
        "dual_action",
        "Dual action required",
        &["read", "agree"],
        "\"I have read\" must be ticked before \"I agree\".",
    ),
    (
        "checkbox",
        "Checkbox confirmation",
        &["agree"],
        "The checkbox enables the button.",
    ),
    (
        "consent_first",
        "Consent-first CTA",
        &["consent", "agree"],
        "A consent statement comes before any field.",
    ),
    (
        "third_party",
        "Third-party sign-in",
        &["agree"],
        "Sign in with the site account first, then agree.",
    ),
    (
        "progressive",
        "Progressive disclosure",
        &["scrolled", "agree"],
        "The agreement is revealed section by section; reading to the end is required.",
    ),
    (
        "incentive",
        "Incentive-based CTA",
        &["agree"],
        "Shows the bonus the signup unlocks.",
    ),
    (
        "legal",
        "Legal consent CTA",
        &["age", "purposes", "agree"],
        "Jurisdiction-aware copy, age gate and consent purposes.",
    ),
    (
        "gamified",
        "Gamified entry",
        &["quiz", "agree"],
        "Progress steps with an optional quiz question.",
    ),
];

pub const PROTECTION_LEVELS: &[(&str, &str)] = &[
    ("public", "Public with agreement"),
    ("members", "Site members only"),
    ("paid", "Paid (linked product)"),
    ("paid_key", "Paid plus access key"),
    ("invite", "Invite only (access key)"),
];

pub fn template_requirements(slug: &str) -> &'static [&'static str] {
    SIGNUP_TEMPLATES
        .iter()
        .find(|(s, _, _, _)| *s == slug)
        .map(|(_, _, r, _)| *r)
        .unwrap_or(&["agree"])
}

pub fn agreement_hash(text: &str, version: i64) -> String {
    let mut h = Sha256::new();
    h.update(version.to_string().as_bytes());
    h.update(b"\n");
    h.update(text.as_bytes());
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

/// Why a visitor cannot see the page yet.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub enum Gate {
    Open,
    SignIn,
    NeedsKey,
    NeedsSignature,
    NeedsPurchase,
    LockedOut { until: String },
    Unavailable,
}

#[derive(Clone)]
pub struct Pages {
    db: Db,
    entitlements: Entitlements,
}

const SELECT: &str = "SELECT id, uuid, title, content, agreement, agreement_version, signup_template, protection, product_id, incentive, quiz_question, quiz_answer, jurisdiction, min_age, status, created_at, updated_at FROM private_pages";
const AGREEMENT_SELECT: &str = "SELECT id, uuid, page_id, user_id, agreement_version, agreement_hash, signer_name, method, confirmations, ip, user_agent, status, signed_at FROM agreements";

#[derive(Debug, Clone, Default)]
pub struct PageDraft {
    pub title: String,
    pub content: String,
    pub agreement: String,
    pub signup_template: String,
    pub protection: String,
    pub product_id: Option<i64>,
    pub incentive: String,
    pub quiz_question: String,
    pub quiz_answer: String,
    pub jurisdiction: String,
    pub min_age: i64,
    pub status: String,
}

impl Pages {
    pub fn new(db: Db) -> Self {
        Self {
            entitlements: Entitlements::new(db.clone()),
            db,
        }
    }

    fn validate(d: &PageDraft) -> Result<()> {
        if d.title.trim().is_empty() {
            bail!("A title is required");
        }
        if !SIGNUP_TEMPLATES
            .iter()
            .any(|(s, ..)| *s == d.signup_template)
        {
            bail!("Unknown signup template");
        }
        if !PROTECTION_LEVELS.iter().any(|(s, _)| *s == d.protection) {
            bail!("Unknown protection level");
        }
        if matches!(d.protection.as_str(), "paid" | "paid_key") && d.product_id.is_none() {
            bail!("A paid page needs a linked product");
        }
        if !matches!(d.status.as_str(), "draft" | "published" | "archived") {
            bail!("Unknown status");
        }
        Ok(())
    }

    pub async fn create(&self, d: &PageDraft) -> Result<Page> {
        Self::validate(d)?;
        let now = crate::now();
        let uuid = uuid::Uuid::new_v4().to_string();
        sqlx::query("INSERT INTO private_pages (uuid, title, content, agreement, agreement_version, signup_template, protection, product_id, incentive, quiz_question, quiz_answer, jurisdiction, min_age, status, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
            .bind(&uuid).bind(d.title.trim()).bind(&d.content).bind(&d.agreement).bind(&d.signup_template).bind(&d.protection).bind(d.product_id).bind(&d.incentive).bind(&d.quiz_question).bind(&d.quiz_answer).bind(&d.jurisdiction).bind(d.min_age).bind(&d.status).bind(&now).bind(&now)
            .execute(&self.db.pool).await?;
        Ok(self.by_uuid(&uuid).await?.expect("just created"))
    }

    /// A changed agreement text bumps the version: existing signatures are marked
    /// superseded and signers are asked again.
    pub async fn update(&self, id: i64, d: &PageDraft) -> Result<()> {
        Self::validate(d)?;
        let Some(cur) = self.by_id(id).await? else {
            bail!("page missing")
        };
        let now = crate::now();
        let mut version = cur.agreement_version;
        if cur.agreement.trim() != d.agreement.trim() {
            version += 1;
            sqlx::query("UPDATE agreements SET status = 'superseded' WHERE page_id = ? AND status = 'signed'")
                .bind(id).execute(&self.db.pool).await?;
        }
        sqlx::query("UPDATE private_pages SET title = ?, content = ?, agreement = ?, agreement_version = ?, signup_template = ?, protection = ?, product_id = ?, incentive = ?, quiz_question = ?, quiz_answer = ?, jurisdiction = ?, min_age = ?, status = ?, updated_at = ? WHERE id = ?")
            .bind(d.title.trim()).bind(&d.content).bind(&d.agreement).bind(version).bind(&d.signup_template).bind(&d.protection).bind(d.product_id).bind(&d.incentive).bind(&d.quiz_question).bind(&d.quiz_answer).bind(&d.jurisdiction).bind(d.min_age).bind(&d.status).bind(&now).bind(id)
            .execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn delete(&self, id: i64) -> Result<()> {
        sqlx::query("DELETE FROM private_pages WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn by_id(&self, id: i64) -> Result<Option<Page>> {
        Ok(sqlx::query_as::<_, Page>(&format!("{SELECT} WHERE id = ?"))
            .bind(id)
            .fetch_optional(&self.db.pool)
            .await?)
    }

    pub async fn by_uuid(&self, uuid: &str) -> Result<Option<Page>> {
        Ok(
            sqlx::query_as::<_, Page>(&format!("{SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn list(&self) -> Result<Vec<Page>> {
        Ok(
            sqlx::query_as::<_, Page>(&format!("{SELECT} ORDER BY id DESC"))
                .fetch_all(&self.db.pool)
                .await?,
        )
    }

    // ----- gate -----

    /// The single decision for a visitor on a page. `key_ok` says a valid access key
    /// was presented in this session.
    pub async fn gate(
        &self,
        page: &Page,
        user_id: Option<i64>,
        subject: &str,
        key_ok: bool,
        now: &str,
    ) -> Result<Gate> {
        if page.status != "published" {
            return Ok(Gate::Unavailable);
        }
        if let Some(until) = self.locked_until(subject).await? {
            if until.as_str() > now {
                return Ok(Gate::LockedOut { until });
            }
        }
        let Some(uid) = user_id else {
            return Ok(Gate::SignIn);
        };
        if matches!(page.protection.as_str(), "paid_key" | "invite") && !key_ok {
            // The key is the invitation: a site pass alone does not open these pages.
            let entitled = self
                .entitlements
                .check_exact(uid, "page", &page.uuid, now)
                .await?;
            if !entitled {
                return Ok(Gate::NeedsKey);
            }
        }
        let signed = self.current_agreement(page, uid).await?.is_some();
        if !signed {
            return Ok(Gate::NeedsSignature);
        }
        if matches!(page.protection.as_str(), "paid" | "paid_key") {
            let entitled = self
                .entitlements
                .check(uid, &Subject::Page(page.uuid.clone()), now)
                .await?;
            if !entitled {
                return Ok(Gate::NeedsPurchase);
            }
        }
        Ok(Gate::Open)
    }

    pub async fn current_agreement(&self, page: &Page, user_id: i64) -> Result<Option<Agreement>> {
        Ok(sqlx::query_as::<_, Agreement>(&format!("{AGREEMENT_SELECT} WHERE page_id = ? AND user_id = ? AND agreement_version = ? AND status = 'signed'"))
            .bind(page.id).bind(user_id).bind(page.agreement_version).fetch_optional(&self.db.pool).await?)
    }

    /// Records a signature after checking the template's required confirmations.
    /// Returns the agreement and whether the page is free to open now.
    #[allow(clippy::too_many_arguments)]
    pub async fn sign(
        &self,
        page: &Page,
        user_id: i64,
        signer_name: &str,
        method: &str,
        signature: Option<&str>,
        confirmations: &[String],
        quiz_answer: &str,
        ip: &str,
        user_agent: &str,
        site_name: &str,
    ) -> Result<Agreement> {
        if page.status != "published" {
            bail!("This page is not available");
        }
        let name = signer_name.trim();
        if name.len() < 2 {
            bail!("Type your full name to sign");
        }
        if method == "drawn" && signature.map(|s| s.len() < 100).unwrap_or(true) {
            bail!("Draw your signature before continuing");
        }
        for req in template_requirements(&page.signup_template) {
            match *req {
                "quiz" => {
                    if !page.quiz_question.trim().is_empty()
                        && quiz_answer.trim().to_lowercase()
                            != page.quiz_answer.trim().to_lowercase()
                    {
                        bail!("That answer is not right; try again");
                    }
                }
                r => {
                    if !confirmations.iter().any(|c| c == r) {
                        bail!(
                            "Please confirm every step before signing ({})",
                            match r {
                                "agree" => "I agree",
                                "read" => "I have read the agreement",
                                "consent" => "consent",
                                "scrolled" => "read to the end",
                                "age" => "age",
                                "purposes" => "consent purposes",
                                other => other,
                            }
                        );
                    }
                }
            }
        }
        let now = crate::now();
        let hash = agreement_hash(&page.agreement, page.agreement_version);
        let uuid = uuid::Uuid::new_v4().to_string();
        let (email,): (String,) = sqlx::query_as("SELECT email FROM users WHERE id = ?")
            .bind(user_id)
            .fetch_one(&self.db.pool)
            .await?;
        let pdf = agreement_pdf(
            page,
            name,
            &email,
            method,
            confirmations,
            ip,
            user_agent,
            &now,
            &hash,
            site_name,
        );
        sqlx::query("INSERT INTO agreements (uuid, page_id, user_id, agreement_version, agreement_hash, signer_name, method, signature, confirmations, ip, user_agent, pdf, status, signed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'signed', ?) ON CONFLICT(page_id, user_id, agreement_version) DO UPDATE SET status = 'signed', signer_name = excluded.signer_name, signed_at = excluded.signed_at, pdf = excluded.pdf")
            .bind(&uuid).bind(page.id).bind(user_id).bind(page.agreement_version).bind(&hash).bind(name).bind(method).bind(signature).bind(confirmations.join(",")).bind(ip).bind(user_agent).bind(&pdf).bind(&now)
            .execute(&self.db.pool).await?;
        if matches!(page.protection.as_str(), "public" | "members" | "invite") {
            self.entitlements
                .grant(Grant {
                    user_id,
                    product_id: None,
                    scope: "page",
                    scope_ref: &page.uuid,
                    source: "free",
                    source_ref: &page.uuid,
                    starts_at: &now,
                    ends_at: None,
                })
                .await?;
        }
        Ok(self
            .current_agreement(page, user_id)
            .await?
            .expect("just signed"))
    }

    pub async fn agreements(
        &self,
        page_id: Option<i64>,
        user_id: Option<i64>,
    ) -> Result<Vec<Agreement>> {
        Ok(sqlx::query_as::<_, Agreement>(&format!("{AGREEMENT_SELECT} WHERE (? IS NULL OR page_id = ?) AND (? IS NULL OR user_id = ?) ORDER BY id DESC"))
            .bind(page_id).bind(page_id).bind(user_id).bind(user_id).fetch_all(&self.db.pool).await?)
    }

    pub async fn agreement_pdf_by_uuid(
        &self,
        uuid: &str,
        user_id: Option<i64>,
    ) -> Result<Option<Vec<u8>>> {
        Ok(sqlx::query_scalar::<_, Vec<u8>>(
            "SELECT pdf FROM agreements WHERE uuid = ? AND (? IS NULL OR user_id = ?)",
        )
        .bind(uuid)
        .bind(user_id)
        .bind(user_id)
        .fetch_optional(&self.db.pool)
        .await?)
    }

    /// Revokes a signer: the agreement is marked revoked and the page entitlement withdrawn.
    pub async fn revoke(&self, agreement_id: i64) -> Result<()> {
        let a = sqlx::query_as::<_, Agreement>(&format!("{AGREEMENT_SELECT} WHERE id = ?"))
            .bind(agreement_id)
            .fetch_optional(&self.db.pool)
            .await?;
        let Some(a) = a else { return Ok(()) };
        sqlx::query("UPDATE agreements SET status = 'revoked' WHERE id = ?")
            .bind(a.id)
            .execute(&self.db.pool)
            .await?;
        if let Some(page) = self.by_id(a.page_id).await? {
            sqlx::query("UPDATE entitlements SET status = 'revoked', updated_at = ? WHERE user_id = ? AND scope = 'page' AND scope_ref = ? AND status = 'active'")
                .bind(crate::now()).bind(a.user_id).bind(&page.uuid).execute(&self.db.pool).await?;
        }
        Ok(())
    }

    // ----- access keys -----

    /// Generates a key, stores only its hash and returns the plain key once.
    pub async fn create_key(
        &self,
        page_id: i64,
        max_uses: i64,
        expires_at: Option<&str>,
    ) -> Result<String> {
        use rand::RngCore;
        let mut b = [0u8; 12];
        rand::thread_rng().fill_bytes(&mut b);
        let plain: String = b.iter().map(|x| format!("{x:02X}")).collect::<String>();
        let plain = format!("{}-{}-{}", &plain[..8], &plain[8..16], &plain[16..]);
        sqlx::query("INSERT INTO access_keys (page_id, key_hash, hint, max_uses, uses, expires_at, created_at) VALUES (?, ?, ?, ?, 0, ?, ?)")
            .bind(page_id).bind(key_hash(&plain)).bind(format!("{}…", &plain[..4])).bind(max_uses.max(0)).bind(expires_at.filter(|e| !e.is_empty())).bind(crate::now())
            .execute(&self.db.pool).await?;
        Ok(plain)
    }

    pub async fn keys(&self, page_id: i64) -> Result<Vec<AccessKey>> {
        Ok(sqlx::query_as::<_, AccessKey>("SELECT id, page_id, hint, max_uses, uses, expires_at, status, created_at FROM access_keys WHERE page_id = ? ORDER BY id DESC")
            .bind(page_id).fetch_all(&self.db.pool).await?)
    }

    pub async fn revoke_key(&self, id: i64) -> Result<()> {
        sqlx::query("UPDATE access_keys SET status = 'revoked' WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    /// Consumes one use of a key for a user. Failures count towards the lockout.
    #[allow(clippy::too_many_arguments)]
    pub async fn use_key(
        &self,
        page: &Page,
        user_id: i64,
        plain: &str,
        subject: &str,
        limit: i64,
        window_secs: i64,
        lockout_secs: i64,
    ) -> Result<bool> {
        let now = crate::now();
        if let Some(until) = self.locked_until(subject).await? {
            if until.as_str() > now.as_str() {
                bail!("Too many attempts. Try again after {}", until);
            }
        }
        let hash = key_hash(plain.trim());
        let row: Option<(i64, i64, i64, Option<String>)> = sqlx::query_as("SELECT id, max_uses, uses, expires_at FROM access_keys WHERE page_id = ? AND key_hash = ? AND status = 'active'")
            .bind(page.id).bind(&hash).fetch_optional(&self.db.pool).await?;
        let ok = match row {
            Some((id, max_uses, uses, expires)) => {
                let alive =
                    (max_uses == 0 || uses < max_uses) && expires.map(|e| e > now).unwrap_or(true);
                if alive {
                    sqlx::query("UPDATE access_keys SET uses = uses + 1, status = CASE WHEN max_uses > 0 AND uses + 1 >= max_uses THEN 'used' ELSE status END WHERE id = ?")
                        .bind(id).execute(&self.db.pool).await?;
                    self.entitlements
                        .grant(Grant {
                            user_id,
                            product_id: None,
                            scope: "page",
                            scope_ref: &page.uuid,
                            source: "manual",
                            source_ref: &format!("key:{id}"),
                            starts_at: &now,
                            ends_at: None,
                        })
                        .await?;
                }
                alive
            }
            None => false,
        };
        self.record_attempt(subject, page.id, ok, limit, window_secs, lockout_secs)
            .await?;
        Ok(ok)
    }

    // ----- attempts and lockouts -----

    pub async fn record_attempt(
        &self,
        subject: &str,
        page_id: i64,
        ok: bool,
        limit: i64,
        window_secs: i64,
        lockout_secs: i64,
    ) -> Result<()> {
        let now = crate::now();
        sqlx::query("INSERT INTO access_attempts (subject, page_id, ok, at) VALUES (?, ?, ?, ?)")
            .bind(subject)
            .bind(page_id)
            .bind(ok as i64)
            .bind(&now)
            .execute(&self.db.pool)
            .await?;
        if ok {
            sqlx::query("DELETE FROM lockouts WHERE subject = ?")
                .bind(subject)
                .execute(&self.db.pool)
                .await?;
            return Ok(());
        }
        let since = crate::commerce::add_days(&now, 0);
        let since = shift_secs(&since, -window_secs);
        let failures: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM access_attempts WHERE subject = ? AND ok = 0 AND at > ?",
        )
        .bind(subject)
        .bind(&since)
        .fetch_one(&self.db.pool)
        .await?;
        if failures >= limit.max(1) {
            let prior: i64 = sqlx::query_scalar(
                "SELECT COALESCE(MAX(count), 0) FROM lockouts WHERE subject = ?",
            )
            .bind(subject)
            .fetch_one(&self.db.pool)
            .await?;
            let count = prior + 1;
            // Exponential: 30 min, 60, 120 ... capped at a day.
            let secs = (lockout_secs.max(60) * (1i64 << (count - 1).min(10))).min(86_400);
            let until = shift_secs(&now, secs);
            sqlx::query("INSERT INTO lockouts (subject, count, until) VALUES (?, ?, ?) ON CONFLICT(subject) DO UPDATE SET count = excluded.count, until = excluded.until")
                .bind(subject).bind(count).bind(&until).execute(&self.db.pool).await?;
            sqlx::query("DELETE FROM access_attempts WHERE subject = ? AND ok = 0")
                .bind(subject)
                .execute(&self.db.pool)
                .await?;
        }
        Ok(())
    }

    pub async fn locked_until(&self, subject: &str) -> Result<Option<String>> {
        Ok(
            sqlx::query_scalar("SELECT until FROM lockouts WHERE subject = ?")
                .bind(subject)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }
}

fn shift_secs(now: &str, secs: i64) -> String {
    let base = chrono::DateTime::parse_from_rfc3339(now)
        .map(|d| d.with_timezone(&chrono::Utc))
        .unwrap_or_else(|_| chrono::Utc::now());
    (base + chrono::Duration::seconds(secs))
        .format("%Y-%m-%dT%H:%M:%SZ")
        .to_string()
}

pub fn key_hash(plain: &str) -> String {
    let mut h = Sha256::new();
    h.update(plain.trim().to_ascii_uppercase().as_bytes());
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

#[allow(clippy::too_many_arguments)]
fn agreement_pdf(
    page: &Page,
    name: &str,
    email: &str,
    method: &str,
    confirmations: &[String],
    ip: &str,
    ua: &str,
    when: &str,
    hash: &str,
    site: &str,
) -> Vec<u8> {
    let mut d = crate::pdf::Document::new(&format!("Agreement - {}", page.title));
    d.text(16.0, true, site);
    d.text(
        13.0,
        true,
        &format!(
            "Agreement for \"{}\" (version {})",
            page.title, page.agreement_version
        ),
    );
    d.space(6.0);
    d.paragraph(10.0, &page.agreement);
    d.space(10.0);
    d.rule();
    d.text(11.0, true, "Signed");
    d.text(10.0, false, &format!("By {name} <{email}> on {when}"));
    d.text(
        10.0,
        false,
        &format!(
            "Method: {}; confirmations: {}",
            if method == "drawn" {
                "drawn signature"
            } else {
                "typed name and checkbox"
            },
            confirmations.join(", ")
        ),
    );
    d.text(
        10.0,
        false,
        &format!(
            "IP {ip}; browser {}",
            ua.chars().take(90).collect::<String>()
        ),
    );
    d.text(9.0, false, &format!("Agreement hash SHA-256 {hash}"));
    d.finish()
}

/// A small, safe Markdown subset for page content: headings, paragraphs, lists,
/// bold, italics and https links. Everything else is escaped.
pub fn markdown(src: &str) -> String {
    fn esc(s: &str) -> String {
        s.replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
    }
    fn inline(s: &str) -> String {
        let mut out = esc(s);
        // [text](https://...)
        while let Some(start) = out.find('[') {
            let Some(mid) = out[start..].find("](") else {
                break;
            };
            let Some(end) = out[start + mid..].find(')') else {
                break;
            };
            let text = out[start + 1..start + mid].to_string();
            let href = out[start + mid + 2..start + mid + end].to_string();
            let rep = if href.starts_with("https://") || href.starts_with('/') {
                format!("<a href=\"{href}\" rel=\"noopener\">{text}</a>")
            } else {
                text.clone()
            };
            out.replace_range(start..start + mid + end + 1, &rep);
        }
        let mut parts = out.split("**");
        let mut r = String::from(parts.next().unwrap_or(""));
        let mut open = false;
        for p in parts {
            r.push_str(if open { "</b>" } else { "<b>" });
            r.push_str(p);
            open = !open;
        }
        if open {
            r.push_str("</b>");
        }
        let mut parts = r.split('_');
        let mut r2 = String::from(parts.next().unwrap_or(""));
        let mut open = false;
        let rest: Vec<&str> = parts.collect();
        if rest.len() % 2 == 0 {
            for p in rest {
                r2.push_str(if open { "</i>" } else { "<i>" });
                r2.push_str(p);
                open = !open;
            }
            r2
        } else {
            r
        }
    }
    let mut html = String::new();
    let mut para: Vec<String> = Vec::new();
    let mut list: Vec<String> = Vec::new();
    let flush = |html: &mut String, para: &mut Vec<String>, list: &mut Vec<String>| {
        if !para.is_empty() {
            html.push_str(&format!("<p>{}</p>\n", inline(&para.join(" "))));
            para.clear();
        }
        if !list.is_empty() {
            html.push_str("<ul>");
            for l in list.iter() {
                html.push_str(&format!("<li>{}</li>", inline(l)));
            }
            html.push_str("</ul>\n");
            list.clear();
        }
    };
    for line in src.lines() {
        let t = line.trim();
        if t.is_empty() {
            flush(&mut html, &mut para, &mut list);
        } else if let Some(h) = t.strip_prefix("### ") {
            flush(&mut html, &mut para, &mut list);
            html.push_str(&format!("<h3>{}</h3>\n", inline(h)));
        } else if let Some(h) = t.strip_prefix("## ") {
            flush(&mut html, &mut para, &mut list);
            html.push_str(&format!("<h2>{}</h2>\n", inline(h)));
        } else if let Some(h) = t.strip_prefix("# ") {
            flush(&mut html, &mut para, &mut list);
            html.push_str(&format!("<h1>{}</h1>\n", inline(h)));
        } else if let Some(item) = t.strip_prefix("- ").or_else(|| t.strip_prefix("* ")) {
            if !para.is_empty() {
                flush(&mut html, &mut para, &mut list);
            }
            list.push(item.to_string());
        } else {
            if !list.is_empty() {
                flush(&mut html, &mut para, &mut list);
            }
            para.push(t.to_string());
        }
    }
    flush(&mut html, &mut para, &mut list);
    html
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn markdown_is_safe_and_small() {
        let h = markdown("# Title\n\nHello **world** and _you_ <script>x</script>\n\n- one\n- [two](https://x.io)\n- [bad](javascript:alert)");
        assert_eq!(h, "<h1>Title</h1>\n<p>Hello <b>world</b> and <i>you</i> &lt;script&gt;x&lt;/script&gt;</p>\n<ul><li>one</li><li><a href=\"https://x.io\" rel=\"noopener\">two</a></li><li>bad</li></ul>\n");
    }

    async fn seed(db: &Db) -> (Pages, i64, Page) {
        let now = crate::now();
        sqlx::query("INSERT INTO users (uuid, email, name, role, status, created_at, updated_at) VALUES ('u1','u@x.io','Una','customer','active',?,?)").bind(&now).bind(&now).execute(&db.pool).await.unwrap();
        let pages = Pages::new(db.clone());
        let page = pages
            .create(&PageDraft {
                title: "Members".into(),
                content: "# Secret".into(),
                agreement: "Be nice.".into(),
                signup_template: "dual_action".into(),
                protection: "invite".into(),
                status: "published".into(),
                ..Default::default()
            })
            .await
            .unwrap();
        (pages, 1, page)
    }

    #[tokio::test]
    async fn gate_keys_signature_and_lockout() {
        let db = Db::memory().await.unwrap();
        let (pages, uid, page) = seed(&db).await;
        let now = crate::now();
        assert_eq!(
            pages.gate(&page, None, "ip:1", false, &now).await.unwrap(),
            Gate::SignIn
        );
        assert_eq!(
            pages
                .gate(&page, Some(uid), "ip:1", false, &now)
                .await
                .unwrap(),
            Gate::NeedsKey
        );
        let key = pages.create_key(page.id, 1, None).await.unwrap();
        assert!(!pages
            .use_key(&page, uid, "WRONG-KEY", "ip:1", 3, 900, 60)
            .await
            .unwrap());
        assert!(
            pages
                .use_key(&page, uid, &key.to_lowercase(), "ip:1", 3, 900, 60)
                .await
                .unwrap(),
            "keys are case-insensitive"
        );
        assert!(
            !pages
                .use_key(&page, uid, &key, "ip:1", 3, 900, 60)
                .await
                .unwrap(),
            "single use"
        );
        assert_eq!(
            pages
                .gate(&page, Some(uid), "ip:1", false, &now)
                .await
                .unwrap(),
            Gate::NeedsSignature,
            "the key granted the page; the agreement is still owed"
        );
        // Required confirmations are enforced server-side.
        let err = pages
            .sign(
                &page,
                uid,
                "Una Doe",
                "typed",
                None,
                &["agree".into()],
                "",
                "1.1.1.1",
                "UA",
                "Demo",
            )
            .await
            .unwrap_err();
        assert!(err.to_string().contains("I have read"));
        let a = pages
            .sign(
                &page,
                uid,
                "Una Doe",
                "typed",
                None,
                &["read".into(), "agree".into()],
                "",
                "1.1.1.1",
                "UA",
                "Demo",
            )
            .await
            .unwrap();
        assert_eq!(a.agreement_hash, agreement_hash("Be nice.", 1));
        assert!(pages
            .agreement_pdf_by_uuid(&a.uuid, Some(uid))
            .await
            .unwrap()
            .unwrap()
            .starts_with(b"%PDF"));
        assert_eq!(
            pages
                .gate(&page, Some(uid), "ip:1", false, &now)
                .await
                .unwrap(),
            Gate::Open
        );
        // Changing the agreement asks again; the old signature is superseded.
        let mut d = PageDraft {
            title: page.title.clone(),
            content: page.content.clone(),
            agreement: "Be nicer.".into(),
            signup_template: page.signup_template.clone(),
            protection: page.protection.clone(),
            status: "published".into(),
            ..Default::default()
        };
        pages.update(page.id, &d).await.unwrap();
        let page = pages.by_id(page.id).await.unwrap().unwrap();
        assert_eq!(page.agreement_version, 2);
        assert_eq!(
            pages
                .gate(&page, Some(uid), "ip:1", false, &now)
                .await
                .unwrap(),
            Gate::NeedsSignature
        );
        d.status = "draft".into();
        pages.update(page.id, &d).await.unwrap();
        let page = pages.by_id(page.id).await.unwrap().unwrap();
        assert_eq!(
            pages
                .gate(&page, Some(uid), "ip:1", false, &now)
                .await
                .unwrap(),
            Gate::Unavailable
        );
        // Lockout after repeated bad keys, exponential on repeat.
        d.status = "published".into();
        pages.update(page.id, &d).await.unwrap();
        let page = pages.by_id(page.id).await.unwrap().unwrap();
        for _ in 0..3 {
            let _ = pages.use_key(&page, uid, "NOPE", "ip:2", 3, 900, 60).await;
        }
        let until = pages.locked_until("ip:2").await.unwrap().unwrap();
        assert!(matches!(
            pages
                .gate(&page, Some(uid), "ip:2", false, &now)
                .await
                .unwrap(),
            Gate::LockedOut { .. }
        ));
        assert!(
            pages
                .use_key(&page, uid, "NOPE", "ip:2", 3, 900, 60)
                .await
                .is_err(),
            "locked out subjects cannot try"
        );
        assert!(until > now);
    }
}
