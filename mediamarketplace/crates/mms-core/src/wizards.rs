//! Setup Wizards: a team of AI agents that configure the store for an administrator.
//!
//! Every wizard is a persona plus a set of tools. Wizards read the store, ask the
//! administrator questions and make *proposals*; nothing is written until an
//! administrator applies a proposal, which then goes through the same code paths as a
//! manual save and lands in the audit log. The model is Claude, called through the
//! Messages API with tool use; the store owns the loop (see `routes::wizards` in the
//! server crate). This module holds the definitions, the built-in knowledge the wizards
//! read, the session and proposal store, and the transport to the model.

use crate::db::Db;
use anyhow::{bail, Context, Result};
use serde::Serialize;
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

pub const DEFAULT_MODEL: &str = "claude-opus-5";
pub const MAX_TURNS: i64 = 30;
pub const ASSIST_MAX_TURNS: i64 = 8;

#[derive(Debug, Clone, Serialize)]
pub struct WizardDef {
    pub key: &'static str,
    pub title: &'static str,
    pub blurb: &'static str,
    /// The specialist's brief: what it is for and how it works.
    pub persona: &'static str,
    /// Tools this wizard may use (names from `TOOL_NAMES`).
    pub tools: &'static [&'static str],
    /// The default goal sent as the first user message.
    pub goal: &'static str,
    /// Shown on the team page; ticked off in the final checklist.
    pub checklist: &'static [&'static str],
}

pub const WIZARDS: &[WizardDef] = &[
    WizardDef {
        key: "concierge",
        title: "Concierge",
        blurb: "Interviews you once, then briefs the specialists and runs them in order.",
        persona: "You are the Concierge, the orchestrator of the MediaMarketplace setup team. First read the store overview. Then ask the administrator the questions you still need (business type, what they sell, country and currency, whether they use WooCommerce or VirtueMart, whether visitors must sign agreements, brand colours, whether they want site passes). Ask everything in one ask_admin call. Then write a plan with plan_team: one step per specialist that is needed, each with a two- or three-sentence brief containing the facts that specialist needs. Do not configure anything yourself. Finish with a summary of the plan.",
        tools: &["read_settings", "read_store_overview", "read_guide", "ask_admin", "plan_team", "finish"],
        goal: "Set this store up for me. Ask what you need to know, then brief and run the specialists.",
        checklist: &["Interview done", "Specialists briefed", "Plan running"],
    },
    WizardDef {
        key: "store_setup",
        title: "Store setup",
        blurb: "Store name, currency, receipts, access control and retention.",
        persona: "You are the Store setup specialist. Read the current settings for the general, store, access and privacy sections. Propose the values that fit the administrator's brief: store name, base currency, receipt prefix and footer, grace days, display currencies when the audience is international, sensible lockout limits and retention. Only propose keys that exist. Do not touch payments, protection or email; other specialists own them.",
        tools: &["read_settings", "read_store_overview", "read_guide", "propose_settings", "ask_admin", "finish"],
        goal: "Configure the store's general, store, access control and privacy settings for this business.",
        checklist: &["Store name and currency", "Receipts", "Access control and retention"],
    },
    WizardDef {
        key: "catalogue",
        title: "Catalogue",
        blurb: "Turns uploaded media into priced, categorised products.",
        persona: "You are the Catalogue specialist. List the media library and the existing products. For every media file that has no product, propose a product of the matching type with a clear title, a two-sentence description, a sensible price in the store currency, categories (propose new categories first when needed) and the right type settings (preview clip for video and audio, licence text for images, preview pages for PDFs). Use the media uuid as media_uuid. Propose products as drafts unless the brief says to publish. Never propose a product for a file that already has one.",
        tools: &["read_settings", "read_store_overview", "list_media", "list_products", "read_guide", "propose_category", "propose_product", "ask_admin", "finish"],
        goal: "Create products for every media file that has none, with categories and prices that fit this business.",
        checklist: &["Categories", "Products for unassigned media", "Prices and previews"],
    },
    WizardDef {
        key: "storefront",
        title: "Storefront",
        blurb: "Site template, colour scheme, brand kit and placement.",
        persona: "You are the Storefront specialist. Read the store overview and the list of site templates. Propose the site template that matches the business (propose_site_template), the store colour scheme (general.scheme) and brand kit (brand.kit as JSON with logo, font, radius and shadow) that match the brand colours in the brief, and explain in the finish summary which widgets to place on which CMS page and with which snippet.",
        tools: &["read_settings", "read_store_overview", "list_site_templates", "read_guide", "propose_settings", "propose_site_template", "ask_admin", "finish"],
        goal: "Choose and apply the site template, colour scheme and brand kit for this business, and explain where to place the widgets.",
        checklist: &["Site template", "Colour scheme and brand kit", "Placement plan"],
    },
    WizardDef {
        key: "payments",
        title: "Payments",
        blurb: "Payment methods, webhooks, test mode and Apple Pay.",
        persona: "You are the Payments specialist. Read the payments settings and the payments guide. Propose the settings for the payment methods the administrator wants. Secret keys are never invented: propose them with an empty value so the administrator types them into the proposal card. Explain the exact webhook address and events for each provider in the finish summary, and propose switching test payments off only when a real method is configured.",
        tools: &["read_settings", "read_store_overview", "read_guide", "propose_settings", "ask_admin", "finish"],
        goal: "Set up the payment methods this store will take, with their webhooks, and turn test payments off when ready.",
        checklist: &["Payment methods", "Webhooks", "Test payments off"],
    },
    WizardDef {
        key: "private_pages",
        title: "Private pages",
        blurb: "Agreements, signup templates, keys and protection levels.",
        persona: "You are the Private pages specialist. Read the pages guide. For each private page the brief asks for, propose a page with real content (headings and paragraphs), a complete, plain-English agreement text suited to the purpose (model release, membership terms, NDA, course terms), the signup template that fits the audience, the protection level, and for paid pages the product slug to link. Write the agreement fully; do not leave placeholders except the business name in square brackets when unknown.",
        tools: &["read_settings", "read_store_overview", "list_products", "read_guide", "propose_page", "propose_product", "ask_admin", "finish"],
        goal: "Create the private pages and agreements this business needs.",
        checklist: &["Pages and agreements", "Signup templates", "Protection levels"],
    },
    WizardDef {
        key: "passes",
        title: "Passes and pricing",
        blurb: "Site passes, coupons and tax rates.",
        persona: "You are the Passes and pricing specialist. Propose site pass products (monthly and yearly recurring when Stripe is or will be used, otherwise fixed-length), a launch coupon if the brief wants one, and tax rates for the countries named in the brief with the standard VAT or sales tax rate you know for them, stated as a percentage in basis points. Explain any rate you are unsure of.",
        tools: &["read_settings", "read_store_overview", "list_products", "read_guide", "propose_product", "propose_coupon", "propose_tax_rate", "ask_admin", "finish"],
        goal: "Create the site passes, coupons and tax rates for this store.",
        checklist: &["Site passes", "Coupons", "Tax rates"],
    },
    WizardDef {
        key: "protection",
        title: "Protection",
        blurb: "Watermark levels, stamp text and copyright owner details.",
        persona: "You are the Protection specialist. Read the protection settings and the protection guide. Propose the image and video protection levels that fit the value of the content (paid originals get level 2; free previews level 1), the stamp text, position and opacity, and the rights owner name, email and address under copyright for DMCA notices. Mention in the summary that ffmpeg is needed for level 2 video if health says it is missing.",
        tools: &["read_settings", "read_store_overview", "read_guide", "propose_settings", "ask_admin", "finish"],
        goal: "Set the protection and copyright settings for this store's content.",
        checklist: &["Image and video levels", "Stamp text", "Rights owner details"],
    },
    WizardDef {
        key: "email_google",
        title: "Email and Google",
        blurb: "SMTP details and the Google Business Profile connection.",
        persona: "You are the Email and Google specialist. Read the mail and google settings. Propose the SMTP host, port, encryption and From address for the provider named in the brief (passwords are secrets: empty value, the administrator types it), and the Google OAuth client id and secret fields when the brief wants Google Business Profile. Explain the redirect address and the test email button in the summary.",
        tools: &["read_settings", "read_store_overview", "read_guide", "propose_settings", "ask_admin", "finish"],
        goal: "Configure email delivery and, if wanted, the Google Business Profile connection.",
        checklist: &["SMTP", "Google Business Profile"],
    },
    WizardDef {
        key: "sell_through",
        title: "Sell through",
        blurb: "WooCommerce or VirtueMart as the checkout, and product links.",
        persona: "You are the Sell-through specialist. Read the store overview (it says which CMS the store runs in and how many products are linked) and the sell-through guide. If the brief wants the CMS shop to take the money, propose commerce.mode and commerce.unlinked, and explain in the summary the exact steps in the CMS admin to import and link products. If the brief prefers the store's own checkout, say so and propose nothing.",
        tools: &["read_settings", "read_store_overview", "read_guide", "propose_settings", "ask_admin", "finish"],
        goal: "Decide whether checkout runs in the store or in the CMS shop, and set it up.",
        checklist: &["Checkout mode", "Product links"],
    },
    WizardDef {
        key: "auditor",
        title: "Launch auditor",
        blurb: "Reviews the whole configuration and produces a go-live checklist.",
        persona: "You are the Launch auditor. Read every settings section, the store overview and the health report. Do not propose changes unless something is plainly wrong (test payments on with real keys, no store name, HTTP only). Produce a go-live checklist with finish: each item done, todo or needs_admin with a one-line note, covering payments, email, protection, backups, HTTPS, products published, placement on the site, legal pages and privacy.",
        tools: &["read_settings", "read_store_overview", "list_products", "read_guide", "propose_settings", "finish"],
        goal: "Audit this store for launch and give me the checklist.",
        checklist: &["Configuration reviewed", "Go-live checklist"],
    },
    WizardDef {
        key: "assist",
        title: "Form assistant",
        blurb: "Answers a question on any admin page and pre-fills the form.",
        persona: "You are the Form assistant. The administrator is on one admin page and asks a question about it. Read the settings of that section (or the overview) if you need them, answer briefly in plain language, and when the question asks for a value or a change, propose it with the right propose tool so the administrator can apply it in one click. Never claim to have changed anything.",
        tools: &["read_settings", "read_store_overview", "list_media", "list_products", "list_site_templates", "read_guide", "propose_settings", "propose_product", "propose_category", "propose_page", "propose_coupon", "propose_tax_rate", "propose_site_template", "finish"],
        goal: "",
        checklist: &[],
    },
];

pub fn wizard(key: &str) -> Option<&'static WizardDef> {
    WIZARDS.iter().find(|w| w.key == key)
}

/// Wizards shown on the team page (the form assistant lives in the drawer).
pub fn team() -> Vec<&'static WizardDef> {
    WIZARDS.iter().filter(|w| w.key != "assist").collect()
}

pub const TOOL_NAMES: &[&str] = &[
    "read_settings",
    "read_store_overview",
    "list_media",
    "list_products",
    "list_site_templates",
    "read_guide",
    "propose_settings",
    "propose_product",
    "propose_category",
    "propose_page",
    "propose_coupon",
    "propose_tax_rate",
    "propose_site_template",
    "ask_admin",
    "plan_team",
    "finish",
];

/// Built-in knowledge the wizards read with `read_guide`. Short, factual, from the user guides.
pub const KNOWLEDGE: &[(&str, &str)] = &[
    ("payments", "Payments (Settings → Payments). Stripe: secret key, then a webhook at https://SITE/mms/webhooks/stripe with events checkout.session.completed, charge.refunded, invoice.paid, customer.subscription.deleted; paste its signing secret. PayPal: client id and secret, sandbox switch, webhook at https://SITE/mms/webhooks/paypal with PAYMENT.CAPTURE.COMPLETED and PAYMENT.CAPTURE.REFUNDED, paste the webhook id. Square: access token, location id, application id, sandbox switch. Authorize.net: API login id, transaction key, public client key, sandbox switch. Apple Pay: paste the domain association file. Test payments (payments.test_mode) is on after install and must be off for a live store. Recurring passes bill through Stripe only. Receipts are numbered PREFIX-year-sequence (store.receipt_prefix); the footer (store.receipt_footer) carries address, VAT number, terms."),
    ("protection", "Protection (Settings → Protection and watermarks). Image level 1: shield viewer, right-click blocked, email label. Level 2: per-viewer copy with burned-in stamp text (default '{email} · {site}', position bottom_right, opacity 45) plus an invisible session code. Video level 1: moving email overlay; level 2: per-viewer copy with a corner code (needs ffmpeg); level 3: downloads are per-viewer copies too. Identify a leaked copy on the Protection page. Copyright services: rights owner name, email and address (copyright.owner_name, copyright.owner_email, copyright.owner_address) are used in DMCA notices; API keys for Videntifier, ScoreDetect, Copysentry, DMCA.com, Bolster.ai, Oxylabs, Urlbox are stored encrypted."),
    ("pages", "Private pages. Protection levels: public (anyone with an account who signs), members (site members only), paid, paid_key (paid plus access key), invite (access key only). Signup templates: simple_cta, terms_highlighted, dual_action, checkbox, consent_first, third_party, progressive, incentive, legal, gamified. Legal template uses jurisdiction and min_age; incentive uses the incentive text; gamified uses quiz_question and quiz_answer. Content and agreement accept headings, lists, bold and links. A paid page links a product of type private_page; the visitor signs first, then pays. Changing the agreement bumps its version and every signer signs again. Access keys are generated on the page afterwards."),
    ("passes", "Site passes are products of type site_pass with settings validity (days, date, lifetime, recurring), days, end_date, interval (month or year) and scope (site or categories). Recurring passes bill through Stripe. Coupons: percent or fixed amount off the subtotal, optional max uses and expiry. Tax rates: per two-letter country code, in basis points (2000 = 20 %), applied to the discounted subtotal at checkout when the shopper picks that country."),
    ("catalogue", "Products have type, title, slug, description, price_cents, currency, media_uuid (video, audio, image, pdf), preview_media_uuid, status (draft, published, archived), featured, categories and type settings: video and audio: preview_start, preview_length (seconds), allow_download, player; image: resolutions, licence; pdf: preview_pages, allow_download, allow_print, stamp_name; live: provider, stream_url, starts_at, ends_at, chat_embed; meeting and consultation: provider, join_url, duration, seats or intake; external: url, target, disclosure; site_pass: validity, days, end_date, interval, scope. Categories appear as a menu and filter in the showcase."),
    ("storefront", "Twelve site templates: photographer, videographer, musician, course, consultant, fitness, stock, publisher, faith, events, agency, generic. Applying one creates published widgets named after their page (Home · Video hero (1)) and switches the store colour scheme. Schemes: default (Studio blue), night, sand, forest, plum, mono. Brand kit (brand.kit) is JSON: {\"logo\": media uuid or empty, \"font\": \"Inter, system-ui, sans-serif\", \"radius\": 12, \"shadow\": \"soft\"}. Widgets are placed with the MediaMarketplace Embed block or the MediaMarketplace » Widget menu item and the widget ID; the showcase with the Showcase block or menu item; the My media link with the My Media block or menu item."),
    ("sell_through", "Sell through (Settings → Sell through). commerce.mode: native (store's own checkout, default), woocommerce or virtuemart. commerce.unlinked: native or hide, for products without a shop product. In WordPress: MediaMarketplace → WooCommerce, Import store products into WooCommerce, then Sell through WooCommerce; or link a product under Product data → MediaMarketplace. In Joomla: Components → MediaMarketplace → VirtueMart, Import, then Sell through VirtueMart; or give the VirtueMart product the SKU MMS-<slug>. Refunds in the shop revoke access. WooCommerce Subscriptions keep recurring passes alive; VirtueMart has no subscriptions."),
    ("email", "Email (Settings → Email): mail.smtp_host, mail.smtp_port (587 for STARTTLS, 465 for TLS), mail.smtp_user, mail.smtp_password (secret), mail.from, mail.tls. Receipts, agreements and pass reminders are emailed once set; Send a test email is on the Integrations page. Google Business Profile (Settings → Google Business Profile): google.client_id, google.client_secret (secret), google.maps_api_key optional; the OAuth redirect is https://SITE/mms/admin/google/callback; then Connect Google account and Sync on the Google page."),
    ("privacy", "Privacy and roles. Retention (privacy.retention_months) prunes watermark sessions, playback sessions and audit entries. Backups (Health → Backups) archive the database, configuration, media and evidence; backup.dir moves the folder. Staff role runs the store without settings; administrators come from the CMS. Sign-in and access-key lockouts: access.attempt_limit, access.attempt_window (seconds), access.lockout_seconds. Customers export or erase their data under My media → Privacy."),
    ("launch", "Go-live checklist: HTTPS (health public url), a real payment method with webhook and test payments off, SMTP configured and tested, products published with prices and previews, the showcase and My media link placed on the site, protection levels chosen, rights owner details entered, private pages and agreements in place, a backup taken and downloaded, retention set, staff accounts created, receipt footer with legal details."),
];

pub fn guide(topic: &str) -> Option<&'static str> {
    KNOWLEDGE.iter().find(|(t, _)| *t == topic).map(|(_, g)| *g)
}

// ----- store -----

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Session {
    pub id: i64,
    pub uuid: String,
    pub wizard: String,
    pub parent_id: Option<i64>,
    pub status: String,
    pub brief: String,
    pub context: String,
    pub summary: String,
    pub checklist: String,
    pub questions: String,
    pub pending_tool_use: String,
    pub plan: String,
    pub error: String,
    pub turns: i64,
    pub input_tokens: i64,
    pub output_tokens: i64,
    pub cache_read_tokens: i64,
    pub created_by: Option<i64>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Message {
    pub id: i64,
    pub session_id: i64,
    pub role: String,
    pub content: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Proposal {
    pub id: i64,
    pub uuid: String,
    pub session_id: i64,
    pub wizard: String,
    pub kind: String,
    pub title: String,
    pub reason: String,
    pub payload: String,
    pub needs_input: i64,
    pub status: String,
    pub result: String,
    pub created_at: String,
    pub applied_at: Option<String>,
}

const SESSION_SELECT: &str = "SELECT id, uuid, wizard, parent_id, status, brief, context, summary, checklist, questions, pending_tool_use, plan, error, turns, input_tokens, output_tokens, cache_read_tokens, created_by, created_at, updated_at FROM wizard_sessions";
const PROPOSAL_SELECT: &str = "SELECT id, uuid, session_id, wizard, kind, title, reason, payload, needs_input, status, result, created_at, applied_at FROM wizard_proposals";

#[derive(Clone)]
pub struct Wizards {
    db: Db,
}

impl Wizards {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub async fn create_session(
        &self,
        wizard: &str,
        brief: &str,
        context: &str,
        parent_id: Option<i64>,
        created_by: Option<i64>,
    ) -> Result<Session> {
        if self::wizard(wizard).is_none() {
            bail!("unknown wizard {wizard}");
        }
        let now = crate::now();
        let uuid = uuid::Uuid::new_v4().to_string();
        sqlx::query("INSERT INTO wizard_sessions (uuid, wizard, parent_id, status, brief, context, created_by, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)")
            .bind(&uuid).bind(wizard).bind(parent_id).bind(brief.trim()).bind(context).bind(created_by).bind(&now).bind(&now)
            .execute(&self.db.pool).await?;
        Ok(self.session_by_uuid(&uuid).await?.expect("just created"))
    }

    pub async fn session_by_uuid(&self, uuid: &str) -> Result<Option<Session>> {
        Ok(
            sqlx::query_as::<_, Session>(&format!("{SESSION_SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn session_by_id(&self, id: i64) -> Result<Option<Session>> {
        Ok(
            sqlx::query_as::<_, Session>(&format!("{SESSION_SELECT} WHERE id = ?"))
                .bind(id)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn sessions(&self, limit: i64) -> Result<Vec<Session>> {
        Ok(
            sqlx::query_as::<_, Session>(&format!("{SESSION_SELECT} ORDER BY id DESC LIMIT ?"))
                .bind(limit)
                .fetch_all(&self.db.pool)
                .await?,
        )
    }

    pub async fn children(&self, parent_id: i64) -> Result<Vec<Session>> {
        Ok(sqlx::query_as::<_, Session>(&format!(
            "{SESSION_SELECT} WHERE parent_id = ? ORDER BY id"
        ))
        .bind(parent_id)
        .fetch_all(&self.db.pool)
        .await?)
    }

    pub async fn set_status(&self, id: i64, status: &str, error: &str) -> Result<()> {
        sqlx::query(
            "UPDATE wizard_sessions SET status = ?, error = ?, updated_at = ? WHERE id = ?",
        )
        .bind(status)
        .bind(error)
        .bind(crate::now())
        .bind(id)
        .execute(&self.db.pool)
        .await?;
        Ok(())
    }

    pub async fn set_waiting(
        &self,
        id: i64,
        questions: &serde_json::Value,
        tool_use_id: &str,
    ) -> Result<()> {
        sqlx::query("UPDATE wizard_sessions SET status = 'waiting', questions = ?, pending_tool_use = ?, updated_at = ? WHERE id = ?")
            .bind(questions.to_string()).bind(tool_use_id).bind(crate::now()).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn set_done(
        &self,
        id: i64,
        summary: &str,
        checklist: &serde_json::Value,
    ) -> Result<()> {
        sqlx::query("UPDATE wizard_sessions SET status = 'done', summary = ?, checklist = ?, questions = '[]', pending_tool_use = '', updated_at = ? WHERE id = ?")
            .bind(summary).bind(checklist.to_string()).bind(crate::now()).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn set_plan(&self, id: i64, plan: &serde_json::Value) -> Result<()> {
        sqlx::query("UPDATE wizard_sessions SET plan = ?, updated_at = ? WHERE id = ?")
            .bind(plan.to_string())
            .bind(crate::now())
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn add_usage(&self, id: i64, input: i64, output: i64, cache_read: i64) -> Result<()> {
        sqlx::query("UPDATE wizard_sessions SET turns = turns + 1, input_tokens = input_tokens + ?, output_tokens = output_tokens + ?, cache_read_tokens = cache_read_tokens + ?, updated_at = ? WHERE id = ?")
            .bind(input).bind(output).bind(cache_read).bind(crate::now()).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn append_message(
        &self,
        session_id: i64,
        role: &str,
        content: &serde_json::Value,
    ) -> Result<()> {
        sqlx::query("INSERT INTO wizard_messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)")
            .bind(session_id).bind(role).bind(content.to_string()).bind(crate::now()).execute(&self.db.pool).await?;
        Ok(())
    }

    /// The transcript as Messages API messages, in order.
    pub async fn messages(&self, session_id: i64) -> Result<Vec<serde_json::Value>> {
        let rows = sqlx::query_as::<_, Message>("SELECT id, session_id, role, content, created_at FROM wizard_messages WHERE session_id = ? ORDER BY id")
            .bind(session_id).fetch_all(&self.db.pool).await?;
        Ok(rows.into_iter().map(|m| serde_json::json!({ "role": m.role, "content": serde_json::from_str::<serde_json::Value>(&m.content).unwrap_or(serde_json::Value::String(m.content)) })).collect())
    }

    /// Plain-text view of the transcript for the session page: the model's visible text only.
    pub async fn transcript(&self, session_id: i64) -> Result<Vec<(String, String)>> {
        let mut out = Vec::new();
        for m in self.messages(session_id).await? {
            let role = m["role"].as_str().unwrap_or("").to_string();
            let mut text = String::new();
            match &m["content"] {
                serde_json::Value::String(s) => text.push_str(s),
                serde_json::Value::Array(blocks) => {
                    for b in blocks {
                        match b["type"].as_str().unwrap_or("") {
                            "text" => {
                                if !text.is_empty() {
                                    text.push('\n');
                                }
                                text.push_str(b["text"].as_str().unwrap_or(""));
                            }
                            "tool_use" => {
                                if !text.is_empty() {
                                    text.push('\n');
                                }
                                text.push_str(&format!(
                                    "[used {}]",
                                    b["name"].as_str().unwrap_or("tool")
                                ));
                            }
                            _ => {}
                        }
                    }
                }
                _ => {}
            }
            if !text.trim().is_empty() {
                out.push((role, text));
            }
        }
        Ok(out)
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn add_proposal(
        &self,
        session: &Session,
        kind: &str,
        title: &str,
        reason: &str,
        payload: &serde_json::Value,
        needs_input: bool,
    ) -> Result<Proposal> {
        let uuid = uuid::Uuid::new_v4().to_string();
        sqlx::query("INSERT INTO wizard_proposals (uuid, session_id, wizard, kind, title, reason, payload, needs_input, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?)")
            .bind(&uuid).bind(session.id).bind(&session.wizard).bind(kind).bind(title.trim()).bind(reason.trim()).bind(payload.to_string()).bind(needs_input as i64).bind(crate::now())
            .execute(&self.db.pool).await?;
        Ok(self.proposal_by_uuid(&uuid).await?.expect("just created"))
    }

    pub async fn proposal_by_uuid(&self, uuid: &str) -> Result<Option<Proposal>> {
        Ok(
            sqlx::query_as::<_, Proposal>(&format!("{PROPOSAL_SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn proposals(&self, session_id: i64) -> Result<Vec<Proposal>> {
        Ok(sqlx::query_as::<_, Proposal>(&format!(
            "{PROPOSAL_SELECT} WHERE session_id = ? ORDER BY id"
        ))
        .bind(session_id)
        .fetch_all(&self.db.pool)
        .await?)
    }

    pub async fn open_proposals(&self) -> Result<i64> {
        Ok(
            sqlx::query_scalar("SELECT COUNT(*) FROM wizard_proposals WHERE status = 'proposed'")
                .fetch_one(&self.db.pool)
                .await?,
        )
    }

    pub async fn set_proposal(&self, id: i64, status: &str, result: &str) -> Result<()> {
        sqlx::query("UPDATE wizard_proposals SET status = ?, result = ?, applied_at = CASE WHEN ? = 'applied' THEN ? ELSE applied_at END WHERE id = ?")
            .bind(status).bind(result).bind(status).bind(crate::now()).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }
}

// ----- transport to the model -----

/// How wizard requests reach Claude: over HTTPS, or a scripted list of canned
/// responses (tests, demos and `MMS_WIZARD_SCRIPT`).
#[derive(Clone)]
pub enum Transport {
    Http(reqwest::Client),
    Scripted(Arc<Mutex<VecDeque<serde_json::Value>>>),
}

impl Transport {
    pub fn http() -> Self {
        Self::Http(
            reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(600))
                .build()
                .expect("reqwest client"),
        )
    }

    pub fn scripted(responses: Vec<serde_json::Value>) -> Self {
        Self::Scripted(Arc::new(Mutex::new(responses.into())))
    }

    /// Loads a scripted transport from a JSON file holding an array of responses.
    pub fn from_script_file(path: &str) -> Result<Self> {
        let text = std::fs::read_to_string(path).with_context(|| format!("reading {path}"))?;
        let v: Vec<serde_json::Value> =
            serde_json::from_str(&text).context("script must be a JSON array of responses")?;
        Ok(Self::scripted(v))
    }

    pub fn is_scripted(&self) -> bool {
        matches!(self, Self::Scripted(_))
    }

    /// One Messages API call. `api_key` is ignored by the scripted transport.
    pub async fn send(&self, api_key: &str, body: &serde_json::Value) -> Result<serde_json::Value> {
        match self {
            Self::Scripted(q) => {
                let next = q.lock().expect("script lock").pop_front();
                next.ok_or_else(|| anyhow::anyhow!("the scripted model has no more responses"))
            }
            Self::Http(http) => {
                if api_key.trim().is_empty() {
                    bail!("Add an Anthropic API key under Settings → AI to use the wizards");
                }
                let res = http
                    .post("https://api.anthropic.com/v1/messages")
                    .header("x-api-key", api_key.trim())
                    .header("anthropic-version", "2023-06-01")
                    .header("content-type", "application/json")
                    .json(body)
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
                Ok(v)
            }
        }
    }
}

/// The JSON Schema tool definitions sent to the model, filtered to a wizard's tools.
pub fn tool_definitions(names: &[&str]) -> Vec<serde_json::Value> {
    let s = |props: serde_json::Value, required: &[&str]| serde_json::json!({ "type": "object", "properties": props, "required": required });
    let all = vec![
        ("read_settings", "Read the store's settings: every setting of a section with its current value (secrets masked), help text and allowed options. Sections: general, store, commerce, payments, media, players, access, protection, copyright, privacy, ai, google, mail. Omit section for all.", s(serde_json::json!({ "section": { "type": "string" } }), &[])),
        ("read_store_overview", "Read an overview of the store: name, CMS, checkout mode, counts of media, products, customers and orders, categories, existing site template applications, health report and connected site.", s(serde_json::json!({}), &[])),
        ("list_media", "List media files in the library with uuid, type, title, duration, size, privacy and whether a product already uses them.", s(serde_json::json!({ "type": { "type": "string", "description": "video, audio, image or pdf; omit for all" }, "limit": { "type": "integer" } }), &[])),
        ("list_products", "List products with slug, type, title, price, status, categories and media uuid.", s(serde_json::json!({ "status": { "type": "string" } }), &[])),
        ("list_site_templates", "List the twelve site templates with slug, industry, description, scheme and pages, and the colour schemes.", s(serde_json::json!({}), &[])),
        ("read_guide", "Read the built-in guide for a topic: payments, protection, pages, passes, catalogue, storefront, sell_through, email, privacy, launch.", s(serde_json::json!({ "topic": { "type": "string" } }), &["topic"])),
        ("propose_settings", "Propose setting changes for the administrator to apply. For secret settings give an empty value; the administrator types the secret. Each change needs a one-line reason.", s(serde_json::json!({ "changes": { "type": "array", "items": { "type": "object", "properties": { "key": { "type": "string" }, "value": { "type": "string" }, "reason": { "type": "string" } }, "required": ["key", "value", "reason"] } } }), &["changes"])),
        ("propose_product", "Propose a new product. media_uuid must come from list_media; categories are names (proposed categories are created first on apply).", s(serde_json::json!({ "type": { "type": "string" }, "title": { "type": "string" }, "slug": { "type": "string" }, "description": { "type": "string" }, "price_cents": { "type": "integer" }, "currency": { "type": "string" }, "media_uuid": { "type": "string" }, "preview_media_uuid": { "type": "string" }, "settings": { "type": "object" }, "categories": { "type": "array", "items": { "type": "string" } }, "featured": { "type": "boolean" }, "status": { "type": "string", "description": "draft or published" }, "reason": { "type": "string" } }), &["type", "title", "price_cents", "reason"])),
        ("propose_category", "Propose a product category.", s(serde_json::json!({ "name": { "type": "string" }, "reason": { "type": "string" } }), &["name"])),
        ("propose_page", "Propose a private page with its content, full agreement text, signup template and protection level. product_slug links a paid page to its product.", s(serde_json::json!({ "title": { "type": "string" }, "content": { "type": "string" }, "agreement": { "type": "string" }, "signup_template": { "type": "string" }, "protection": { "type": "string" }, "product_slug": { "type": "string" }, "incentive": { "type": "string" }, "quiz_question": { "type": "string" }, "quiz_answer": { "type": "string" }, "jurisdiction": { "type": "string" }, "min_age": { "type": "integer" }, "status": { "type": "string" }, "reason": { "type": "string" } }), &["title", "content", "agreement", "signup_template", "protection", "reason"])),
        ("propose_coupon", "Propose a coupon code.", s(serde_json::json!({ "code": { "type": "string" }, "kind": { "type": "string", "description": "percent or fixed" }, "amount": { "type": "integer", "description": "percent, or cents for fixed" }, "max_uses": { "type": "integer" }, "expires_at": { "type": "string", "description": "YYYY-MM-DD or empty" }, "reason": { "type": "string" } }), &["code", "kind", "amount", "reason"])),
        ("propose_tax_rate", "Propose a tax rate for a country.", s(serde_json::json!({ "country": { "type": "string", "description": "two-letter code" }, "name": { "type": "string" }, "rate_bp": { "type": "integer", "description": "basis points, 2000 = 20 %" }, "reason": { "type": "string" } }), &["country", "name", "rate_bp", "reason"])),
        ("propose_site_template", "Propose applying a site template (creates its widgets and switches the scheme when applied).", s(serde_json::json!({ "slug": { "type": "string" }, "reason": { "type": "string" } }), &["slug", "reason"])),
        ("ask_admin", "Ask the administrator questions and wait for the answers. Ask everything you need in one call. Options are optional choices.", s(serde_json::json!({ "questions": { "type": "array", "items": { "type": "object", "properties": { "key": { "type": "string" }, "question": { "type": "string" }, "options": { "type": "array", "items": { "type": "string" } } }, "required": ["key", "question"] } } }), &["questions"])),
        ("plan_team", "Concierge only: the specialists to run, in order, each with a brief. Wizards: store_setup, catalogue, storefront, payments, private_pages, passes, protection, email_google, sell_through, auditor.", s(serde_json::json!({ "steps": { "type": "array", "items": { "type": "object", "properties": { "wizard": { "type": "string" }, "brief": { "type": "string" } }, "required": ["wizard", "brief"] } } }), &["steps"])),
        ("finish", "End the session with a plain-language summary for the administrator and a checklist of what is done, still to do, or needs the administrator.", s(serde_json::json!({ "summary": { "type": "string" }, "checklist": { "type": "array", "items": { "type": "object", "properties": { "item": { "type": "string" }, "status": { "type": "string", "description": "done, todo or needs_admin" }, "note": { "type": "string" } }, "required": ["item", "status"] } } }), &["summary"])),
    ];
    all.into_iter()
        .filter(|(n, _, _)| names.contains(n))
        .map(|(n, d, schema)| serde_json::json!({ "name": n, "description": d, "input_schema": schema }))
        .collect()
}

/// The rules every wizard follows, prepended to its persona.
pub const RULES: &str = "Rules. You configure a MediaMarketplace Studio store for its administrator. You never change anything yourself: you read, you ask, and you make proposals with the propose tools; the administrator applies them. Only propose setting keys that read_settings returned. Never invent API keys, passwords or secrets: propose those with an empty value. Keep proposals minimal and give each a one-line reason in plain language. Ask questions only when the brief does not answer them, and ask them all at once. When you are done, call finish with a short summary written for a store owner, not a developer. Never claim something has been applied.";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn team_is_complete_and_tools_are_known() {
        assert_eq!(WIZARDS.len(), 12);
        assert_eq!(team().len(), 11);
        for w in WIZARDS {
            assert!(
                w.tools.contains(&"finish"),
                "{} must be able to finish",
                w.key
            );
            for t in w.tools {
                assert!(TOOL_NAMES.contains(t), "{} uses unknown tool {t}", w.key);
            }
            assert_eq!(tool_definitions(w.tools).len(), w.tools.len(), "{}", w.key);
        }
        assert!(guide("payments").unwrap().contains("webhooks/stripe"));
        assert!(guide("nothing").is_none());
    }

    #[tokio::test]
    async fn sessions_messages_and_proposals_round_trip() {
        let db = Db::memory().await.unwrap();
        let w = Wizards::new(db);
        let s = w
            .create_session("store_setup", "A photographer in the UK", "", None, Some(1))
            .await
            .unwrap();
        assert_eq!(s.status, "queued");
        w.append_message(s.id, "user", &serde_json::json!("Configure the store"))
            .await
            .unwrap();
        w.append_message(s.id, "assistant", &serde_json::json!([{ "type": "text", "text": "Reading settings." }, { "type": "tool_use", "id": "t1", "name": "read_settings", "input": {} }])).await.unwrap();
        assert_eq!(w.messages(s.id).await.unwrap().len(), 2);
        assert_eq!(
            w.transcript(s.id).await.unwrap()[1].1,
            "Reading settings.\n[used read_settings]"
        );
        let p = w
            .add_proposal(
                &s,
                "setting",
                "Store name",
                "The brief names the studio",
                &serde_json::json!({ "key": "general.site_name", "value": "Ada Studio" }),
                false,
            )
            .await
            .unwrap();
        assert_eq!(p.status, "proposed");
        assert_eq!(w.open_proposals().await.unwrap(), 1);
        w.set_proposal(p.id, "applied", "ok").await.unwrap();
        assert_eq!(
            w.proposal_by_uuid(&p.uuid).await.unwrap().unwrap().status,
            "applied"
        );
        w.set_waiting(
            s.id,
            &serde_json::json!([{ "key": "country", "question": "Country?" }]),
            "t2",
        )
        .await
        .unwrap();
        assert_eq!(
            w.session_by_id(s.id).await.unwrap().unwrap().status,
            "waiting"
        );
        w.set_done(s.id, "All set", &serde_json::json!([]))
            .await
            .unwrap();
        assert_eq!(
            w.session_by_uuid(&s.uuid).await.unwrap().unwrap().summary,
            "All set"
        );
        assert!(w.create_session("nope", "", "", None, None).await.is_err());
        let t = Transport::scripted(vec![serde_json::json!({ "a": 1 })]);
        assert!(t.is_scripted());
        assert_eq!(t.send("", &serde_json::json!({})).await.unwrap()["a"], 1);
        assert!(
            t.send("", &serde_json::json!({})).await.is_err(),
            "script exhausted"
        );
    }
}
