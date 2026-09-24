use crate::db::Db;
use crate::secrets::Secrets;
use anyhow::Result;
use serde::Serialize;

/// Kind of value a setting holds; drives validation and the admin form control.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Bool,
    Int,
    Text,
    Secret,
    Select,
}

#[derive(Debug, Clone, Serialize)]
pub struct Definition {
    pub key: &'static str,
    pub section: &'static str,
    pub label: &'static str,
    pub kind: Kind,
    pub default: &'static str,
    pub help: &'static str,
    pub options: &'static [(&'static str, &'static str)],
}

pub const SECTIONS: &[(&str, &str)] = &[
    ("general", "General"),
    ("store", "Store"),
    ("commerce", "Sell through (WooCommerce / VirtueMart)"),
    ("payments", "Payments"),
    ("media", "Media"),
    ("players", "Players"),
    ("access", "Access control"),
    ("protection", "Protection and watermarks"),
    ("copyright", "Copyright services"),
    ("privacy", "Privacy"),
    ("ai", "AI"),
    ("google", "Google Business Profile"),
    ("mail", "Email (SMTP)"),
    ("chat", "Support chat"),
];

/// Every setting, declared once. The admin settings screen renders from this list.
pub const DEFINITIONS: &[Definition] = &[
    Definition {
        key: "general.site_name",
        section: "general",
        label: "Store name",
        kind: Kind::Text,
        default: "MediaMarketplace",
        help: "Shown in emails, receipts and embeds.",
        options: &[],
    },
    Definition {
        key: "general.log_level",
        section: "general",
        label: "Log level",
        kind: Kind::Select,
        default: "info",
        help: "",
        options: &[
            ("debug", "Debug"),
            ("info", "Info"),
            ("warn", "Warning"),
            ("error", "Error"),
        ],
    },
    Definition {
        key: "general.scheme",
        section: "general",
        label: "Colour scheme",
        kind: Kind::Text,
        default: "default",
        help: "Slug of the colour scheme widgets and embeds use (Templates → Colour schemes).",
        options: &[],
    },
    Definition {
        key: "brand.kit",
        section: "general",
        label: "Brand kit",
        kind: Kind::Text,
        default: "{}",
        help: "Managed on the Colour schemes page: logo, fonts and brand colours as JSON.",
        options: &[],
    },
    Definition {
        key: "store.currency",
        section: "store",
        label: "Base currency (ISO 4217)",
        kind: Kind::Text,
        default: "USD",
        help: "Prices are stored in this currency.",
        options: &[],
    },
    Definition {
        key: "store.receipt_prefix",
        section: "store",
        label: "Receipt number prefix",
        kind: Kind::Text,
        default: "MMS",
        help: "",
        options: &[],
    },
    Definition {
        key: "store.receipt_footer",
        section: "store",
        label: "Receipt footer",
        kind: Kind::Text,
        default: "Thank you for your purchase.",
        help: "Printed at the bottom of every receipt (VAT number, address, terms).",
        options: &[],
    },
    Definition {
        key: "store.grace_days",
        section: "store",
        label: "Site pass grace period (days)",
        kind: Kind::Int,
        default: "3",
        help: "Days after a pass ends during which the customer can still renew at the same price.",
        options: &[],
    },
    Definition {
        key: "payments.test_mode",
        section: "payments",
        label: "Test payments",
        kind: Kind::Bool,
        default: "1",
        help:
            "Offers a \"test payment\" that completes without charging. Turn off before going live.",
        options: &[],
    },
    Definition {
        key: "payments.stripe_secret_key",
        section: "payments",
        label: "Stripe secret key",
        kind: Kind::Secret,
        default: "",
        help: "sk_live_… or sk_test_…; Stripe appears at checkout once set.",
        options: &[],
    },
    Definition {
        key: "payments.stripe_webhook_secret",
        section: "payments",
        label: "Stripe webhook signing secret",
        kind: Kind::Secret,
        default: "",
        help: "whsec_… for the endpoint <your site>/mms/webhooks/stripe.",
        options: &[],
    },
    Definition {
        key: "payments.paypal_client_id",
        section: "payments",
        label: "PayPal client ID",
        kind: Kind::Text,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "payments.paypal_secret",
        section: "payments",
        label: "PayPal secret",
        kind: Kind::Secret,
        default: "",
        help: "PayPal appears at checkout once the client ID and secret are set.",
        options: &[],
    },
    Definition {
        key: "payments.paypal_webhook_id",
        section: "payments",
        label: "PayPal webhook ID",
        kind: Kind::Text,
        default: "",
        help: "For the endpoint <your site>/mms/webhooks/paypal.",
        options: &[],
    },
    Definition { key: "payments.square_access_token", section: "payments", label: "Square access token", kind: Kind::Secret, default: "", help: "Square appears at checkout once the token, location and application id are set.", options: &[] },
    Definition { key: "payments.square_location_id", section: "payments", label: "Square location id", kind: Kind::Text, default: "", help: "", options: &[] },
    Definition { key: "payments.square_application_id", section: "payments", label: "Square application id", kind: Kind::Text, default: "", help: "Used by the card form in the browser.", options: &[] },
    Definition { key: "payments.square_sandbox", section: "payments", label: "Square sandbox", kind: Kind::Bool, default: "1", help: "", options: &[] },
    Definition { key: "payments.authnet_login_id", section: "payments", label: "Authorize.net API login id", kind: Kind::Text, default: "", help: "", options: &[] },
    Definition { key: "payments.authnet_transaction_key", section: "payments", label: "Authorize.net transaction key", kind: Kind::Secret, default: "", help: "Authorize.net appears at checkout once login id, transaction key and public client key are set.", options: &[] },
    Definition { key: "payments.authnet_client_key", section: "payments", label: "Authorize.net public client key", kind: Kind::Text, default: "", help: "Used by Accept.js in the browser.", options: &[] },
    Definition { key: "payments.authnet_sandbox", section: "payments", label: "Authorize.net sandbox", kind: Kind::Bool, default: "1", help: "", options: &[] },
    Definition { key: "payments.apple_pay_domain_file", section: "payments", label: "Apple Pay domain association file", kind: Kind::Text, default: "", help: "Paste the contents of the file Stripe or Square gives you; it is served at /.well-known/apple-developer-merchantid-domain-association.", options: &[] },
    Definition { key: "commerce.mode", section: "commerce", label: "Checkout runs in", kind: Kind::Select, default: "native", help: "Native: the store's own cart and payment methods. WooCommerce or VirtueMart: Buy buttons send shoppers to the shop's cart; the shop takes the money and tells the store to grant access. Products must be linked first (Integrations → Sell through).", options: &[("native", "The store's own checkout (native)"), ("woocommerce", "WooCommerce (WordPress)"), ("virtuemart", "VirtueMart (Joomla)")] },
    Definition { key: "commerce.cart_url", section: "commerce", label: "Add-to-cart address", kind: Kind::Text, default: "", help: "Optional. Where a Buy button sends the shopper; {external_id} is replaced by the shop's product id and {origin} by the site address. Empty uses the shop's standard address.", options: &[] },
    Definition { key: "commerce.unlinked", section: "commerce", label: "Products without a shop product", kind: Kind::Select, default: "native", help: "What a Buy button does for a product that is not linked to a shop product while checkout runs in the shop.", options: &[("native", "Use the store's own checkout"), ("hide", "Hide the Buy button")] },
    Definition { key: "store.display_currencies", section: "store", label: "Display currencies", kind: Kind::Text, default: "", help: "Comma-separated codes shoppers may switch to (e.g. EUR,GBP,USD). Rates come from the European Central Bank daily.", options: &[] },
    Definition { key: "store.charge_in_display_currency", section: "store", label: "Charge in the shopper's currency", kind: Kind::Bool, default: "0", help: "When on, Stripe and PayPal charge the converted amount; other methods charge the base currency.", options: &[] },
    Definition {
        key: "payments.paypal_sandbox",
        section: "payments",
        label: "PayPal sandbox",
        kind: Kind::Bool,
        default: "1",
        help: "",
        options: &[],
    },
    Definition {
        key: "media.max_upload_mb",
        section: "media",
        label: "Maximum upload size (MB)",
        kind: Kind::Int,
        default: "512",
        help: "",
        options: &[],
    },
    Definition {
        key: "media.ffmpeg_path",
        section: "media",
        label: "ffmpeg binary",
        kind: Kind::Text,
        default: "ffmpeg",
        help: "Used for video thumbnails, transcoding and Level 3 watermarking.",
        options: &[],
    },
    Definition {
        key: "players.default",
        section: "players",
        label: "Default player",
        kind: Kind::Select,
        default: "plyr",
        help: "",
        options: &[
            ("plyr", "Plyr"),
            ("videojs", "Video.js"),
            ("clappr", "Clappr"),
            ("native", "Browser native"),
            ("vimeo", "Vimeo SDK (vimeo.com sources)"),
            ("jwplayer", "JW Player (licence)"),
            ("bitmovin", "Bitmovin (licence)"),
            ("theoplayer", "THEOplayer (licence)"),
            ("kaltura", "Kaltura (partner id)"),
            ("flowplayer", "Flowplayer (token)"),
            ("projekktor", "Projekktor (library URL)"),
        ],
    },
    Definition { key: "players.jwplayer_library", section: "players", label: "JW Player library URL", kind: Kind::Text, default: "", help: "From your JW Player dashboard (https://cdn.jwplayer.com/libraries/….js).", options: &[] },
    Definition { key: "players.jwplayer_key", section: "players", label: "JW Player licence key", kind: Kind::Secret, default: "", help: "", options: &[] },
    Definition { key: "players.bitmovin_key", section: "players", label: "Bitmovin player key", kind: Kind::Secret, default: "", help: "", options: &[] },
    Definition { key: "players.theoplayer_license", section: "players", label: "THEOplayer licence", kind: Kind::Secret, default: "", help: "", options: &[] },
    Definition { key: "players.theoplayer_library", section: "players", label: "THEOplayer library URL", kind: Kind::Text, default: "", help: "Leave empty for the THEO CDN.", options: &[] },
    Definition { key: "players.kaltura_partner", section: "players", label: "Kaltura partner id", kind: Kind::Text, default: "", help: "", options: &[] },
    Definition { key: "players.kaltura_uiconf", section: "players", label: "Kaltura UI conf id", kind: Kind::Text, default: "", help: "", options: &[] },
    Definition { key: "players.flowplayer_token", section: "players", label: "Flowplayer token", kind: Kind::Secret, default: "", help: "", options: &[] },
    Definition { key: "players.projekktor_library", section: "players", label: "Projekktor library URL", kind: Kind::Text, default: "", help: "", options: &[] },
    Definition {
        key: "access.signed_url_ttl",
        section: "access",
        label: "Signed URL lifetime (seconds)",
        kind: Kind::Int,
        default: "600",
        help: "",
        options: &[],
    },
    Definition {
        key: "access.attempt_limit",
        section: "access",
        label: "Failed attempts before lockout",
        kind: Kind::Int,
        default: "5",
        help: "",
        options: &[],
    },
    Definition {
        key: "access.attempt_window",
        section: "access",
        label: "Attempt window (seconds)",
        kind: Kind::Int,
        default: "900",
        help: "",
        options: &[],
    },
    Definition {
        key: "access.lockout_seconds",
        section: "access",
        label: "Lockout duration (seconds)",
        kind: Kind::Int,
        default: "1800",
        help: "",
        options: &[],
    },
    Definition {
        key: "protection.image_level",
        section: "protection",
        label: "Image protection",
        kind: Kind::Select,
        default: "2",
        help: "1: visible overlay in the viewer and download blocking. 2: also a forensic mark and the viewer's email burned into every delivered image (lossless copy per viewer).",
        options: &[("0", "Off"), ("1", "Level 1: overlay"), ("2", "Level 2: forensic mark and stamp")],
    },
    Definition {
        key: "protection.video_level",
        section: "protection",
        label: "Video watermark level",
        kind: Kind::Select,
        default: "1",
        help: "1: moving overlay with the viewer's email. 2: adds a low-contrast session code burned into a per-viewer copy (needs ffmpeg). 3: the per-viewer copy is also what downloads carry.",
        options: &[("1", "Level 1: overlay"), ("2", "Level 2: session code in the picture"), ("3", "Level 3: marked downloads")],
    },
    Definition {
        key: "protection.stamp_text",
        section: "protection",
        label: "Visible stamp text",
        kind: Kind::Text,
        default: "{email} · {site}",
        help: "Placeholders: {email}, {name}, {site}, {date}, {session}.",
        options: &[],
    },
    Definition {
        key: "protection.stamp_position",
        section: "protection",
        label: "Stamp position",
        kind: Kind::Select,
        default: "bottom_right",
        help: "",
        options: &[("bottom_right", "Bottom right"), ("bottom_left", "Bottom left"), ("top_right", "Top right"), ("top_left", "Top left"), ("center", "Centre")],
    },
    Definition {
        key: "protection.stamp_opacity",
        section: "protection",
        label: "Stamp opacity (percent)",
        kind: Kind::Int,
        default: "45",
        help: "",
        options: &[],
    },
    Definition {
        key: "protection.grid_opacity",
        section: "protection",
        label: "Video session code opacity (percent)",
        kind: Kind::Int,
        default: "30",
        help: "Lower is less visible but harder to decode from a screenshot.",
        options: &[],
    },
    Definition {
        key: "copyright.owner_name",
        section: "copyright",
        label: "Rights owner name",
        kind: Kind::Text,
        default: "",
        help: "Signs takedown notices.",
        options: &[],
    },
    Definition {
        key: "copyright.owner_company",
        section: "copyright",
        label: "Company (optional)",
        kind: Kind::Text,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.owner_email",
        section: "copyright",
        label: "Contact email for notices",
        kind: Kind::Text,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.owner_address",
        section: "copyright",
        label: "Postal address",
        kind: Kind::Text,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.videntifier_key",
        section: "copyright",
        label: "Videntifier API key",
        kind: Kind::Secret,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.scoredetect_key",
        section: "copyright",
        label: "ScoreDetect API key",
        kind: Kind::Secret,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.copysentry_key",
        section: "copyright",
        label: "Copysentry API key",
        kind: Kind::Secret,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.dmca_key",
        section: "copyright",
        label: "DMCA.com API key",
        kind: Kind::Secret,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.bolster_key",
        section: "copyright",
        label: "Bolster.ai API key",
        kind: Kind::Secret,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.oxylabs_key",
        section: "copyright",
        label: "Oxylabs API key",
        kind: Kind::Secret,
        default: "",
        help: "",
        options: &[],
    },
    Definition {
        key: "copyright.urlbox_key",
        section: "copyright",
        label: "Urlbox API key",
        kind: Kind::Secret,
        default: "",
        help: "",
        options: &[],
    },
    Definition { key: "google.client_id", section: "google", label: "OAuth client ID", kind: Kind::Text, default: "", help: "A Google Cloud OAuth client (web application) with the Business Profile APIs enabled. Redirect URI: <your site>/mms/admin/google/callback.", options: &[] },
    Definition { key: "google.client_secret", section: "google", label: "OAuth client secret", kind: Kind::Secret, default: "", help: "", options: &[] },
    Definition { key: "google.maps_api_key", section: "google", label: "Maps API key (embeds)", kind: Kind::Text, default: "", help: "For the map on the Google page and the map widget component.", options: &[] },
    Definition { key: "google.reply_tone", section: "google", label: "Review reply tone", kind: Kind::Text, default: "warm and professional", help: "Guides the AI draft.", options: &[] },
    Definition { key: "mail.smtp_host", section: "mail", label: "SMTP host", kind: Kind::Text, default: "", help: "Leave empty to keep receipts and notices in the store only.", options: &[] },
    Definition { key: "mail.smtp_port", section: "mail", label: "SMTP port", kind: Kind::Int, default: "587", help: "", options: &[] },
    Definition { key: "mail.smtp_user", section: "mail", label: "SMTP username", kind: Kind::Text, default: "", help: "", options: &[] },
    Definition { key: "mail.smtp_password", section: "mail", label: "SMTP password", kind: Kind::Secret, default: "", help: "", options: &[] },
    Definition { key: "mail.from", section: "mail", label: "From address", kind: Kind::Text, default: "", help: "e.g. Demo Studio <store@example.com>", options: &[] },
    Definition { key: "mail.tls", section: "mail", label: "Encryption", kind: Kind::Select, default: "starttls", help: "", options: &[("starttls", "STARTTLS (587)"), ("tls", "TLS (465)"), ("none", "None (local relay only)")] },
    Definition { key: "backup.dir", section: "privacy", label: "Backup folder", kind: Kind::Text, default: "", help: "Absolute path for backups; empty keeps them under the data folder (backups/).", options: &[] },
    Definition {
        key: "privacy.retention_months",
        section: "privacy",
        label: "Watermark session and audit retention (months)",
        kind: Kind::Int,
        default: "24",
        help: "",
        options: &[],
    },
    Definition {
        key: "ai.anthropic_api_key",
        section: "ai",
        label: "Anthropic API key",
        kind: Kind::Secret,
        default: "",
        help: "Enables the setup wizards, the form assistant and Google review replies.",
        options: &[],
    },
    Definition {
        key: "ai.model",
        section: "ai",
        label: "Claude model",
        kind: Kind::Text,
        default: "claude-opus-5",
        help: "",
        options: &[],
    },    Definition { key: "chat.mode", section: "chat", label: "Support chat", kind: Kind::Select, default: "assistant_first", help: "Assistant first: the AI assistant answers at once and hands over to a human agent when asked or unsure. Agents only: every conversation waits for an agent. Off: the chat is hidden.", options: &[("assistant_first", "Assistant first, then agents"), ("agents_only", "Agents only"), ("off", "Off")] },
    Definition { key: "chat.greeting", section: "chat", label: "Greeting", kind: Kind::Text, default: "Hi! Ask us anything about your purchases, passes or downloads.", help: "The first line visitors see.", options: &[] },
    Definition { key: "chat.offline_message", section: "chat", label: "Message when no agent is online", kind: Kind::Text, default: "Our support team is not online right now. Leave your message and we will reply by email.", help: "", options: &[] },
    Definition { key: "chat.policy", section: "chat", label: "Support policy and facts for the assistant", kind: Kind::Text, default: "", help: "Plain text the assistant may use: refund policy, delivery times, opening hours, what agents can and cannot do. It never invents facts beyond this and the customer's own records.", options: &[] },
    Definition { key: "chat.notify_agents", section: "chat", label: "Email agents when a visitor is waiting", kind: Kind::Bool, default: "1", help: "Needs SMTP under Email.", options: &[] },
    Definition { key: "chat.canned", section: "chat", label: "Canned replies", kind: Kind::Text, default: "Thanks for your patience. | I have opened your library again; please refresh My media. | Your receipt is under My media → Orders.", help: "Replies agents can insert with one click, separated by |.", options: &[] },
    Definition { key: "chat.guest", section: "chat", label: "Allow guests to chat", kind: Kind::Bool, default: "1", help: "Off: visitors must sign in to the store first.", options: &[] },
    Definition { key: "ai.effort", section: "ai", label: "Wizard effort", kind: Kind::Select, default: "medium", help: "How hard the setup wizards think per step. Medium fits most stores; high costs more and takes longer.", options: &[("low", "Low"), ("medium", "Medium"), ("high", "High")] },

];

pub fn definition(key: &str) -> Option<&'static Definition> {
    DEFINITIONS.iter().find(|d| d.key == key)
}

/// Validate and normalise a raw form value for a setting.
pub fn validate(key: &str, raw: &str) -> Result<String> {
    let def = definition(key).ok_or_else(|| anyhow::anyhow!("unknown setting {key}"))?;
    let raw = raw.trim();
    Ok(match def.kind {
        Kind::Bool => {
            if matches!(raw, "1" | "true" | "on" | "yes") {
                "1".into()
            } else {
                "0".into()
            }
        }
        Kind::Int => {
            let n: i64 = raw
                .parse()
                .map_err(|_| anyhow::anyhow!("{} must be a whole number", def.label))?;
            anyhow::ensure!(n >= 0, "{} must not be negative", def.label);
            n.to_string()
        }
        Kind::Select => {
            anyhow::ensure!(
                def.options.iter().any(|(v, _)| *v == raw),
                "{} has an invalid option",
                def.label
            );
            raw.into()
        }
        Kind::Text | Kind::Secret => {
            anyhow::ensure!(
                !raw.contains('\0'),
                "{} contains an invalid character",
                def.label
            );
            raw.into()
        }
    })
}

#[derive(Clone)]
pub struct SettingsStore {
    db: Db,
    secrets: Secrets,
}

impl SettingsStore {
    pub fn new(db: Db, secrets: Secrets) -> Self {
        Self { db, secrets }
    }

    /// Plain value, decrypted for secrets; the default when unset.
    pub async fn get(&self, key: &str) -> Result<String> {
        let def = definition(key).ok_or_else(|| anyhow::anyhow!("unknown setting {key}"))?;
        let row: Option<Option<String>> =
            sqlx::query_scalar("SELECT value FROM settings WHERE name = ?")
                .bind(key)
                .fetch_optional(&self.db.pool)
                .await?;
        match row.flatten() {
            None => Ok(def.default.to_string()),
            Some(v) if def.kind == Kind::Secret => self.secrets.decrypt(&v),
            Some(v) => Ok(v),
        }
    }

    pub async fn set(&self, key: &str, raw: &str) -> Result<()> {
        let def = definition(key).ok_or_else(|| anyhow::anyhow!("unknown setting {key}"))?;
        let clean = validate(key, raw)?;
        let stored = if def.kind == Kind::Secret {
            self.secrets.encrypt(&clean)?
        } else {
            clean
        };
        sqlx::query("INSERT INTO settings (name, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")
            .bind(key)
            .bind(stored)
            .bind(crate::now())
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    /// Values for the admin form: secrets are masked, never returned in clear.
    pub async fn display_values(&self) -> Result<Vec<(&'static Definition, String)>> {
        let mut out = Vec::with_capacity(DEFINITIONS.len());
        for def in DEFINITIONS {
            let v = self.get(def.key).await?;
            out.push((
                def,
                if def.kind == Kind::Secret {
                    Secrets::mask(&v)
                } else {
                    v
                },
            ));
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn defaults_validation_and_secret_masking() {
        let db = Db::memory().await.unwrap();
        let store = SettingsStore::new(db, Secrets::from_master_key(b"k"));
        assert_eq!(store.get("store.currency").await.unwrap(), "USD");
        store.set("store.currency", " eur ").await.unwrap();
        assert_eq!(store.get("store.currency").await.unwrap(), "eur");
        assert!(store.set("access.attempt_limit", "many").await.is_err());
        assert!(store.set("players.default", "flash").await.is_err());
        store
            .set("ai.anthropic_api_key", "sk-ant-secret-1234")
            .await
            .unwrap();
        assert_eq!(
            store.get("ai.anthropic_api_key").await.unwrap(),
            "sk-ant-secret-1234"
        );
        let raw: String =
            sqlx::query_scalar("SELECT value FROM settings WHERE name = 'ai.anthropic_api_key'")
                .fetch_one(&store.db.pool)
                .await
                .unwrap();
        assert!(raw.starts_with("x1:"));
        let shown = store.display_values().await.unwrap();
        let (_, masked) = shown
            .iter()
            .find(|(d, _)| d.key == "ai.anthropic_api_key")
            .unwrap();
        assert!(masked.ends_with("1234") && !masked.contains("secret"));
    }
}
