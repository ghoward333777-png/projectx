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
    ("media", "Media"),
    ("players", "Players"),
    ("access", "Access control"),
    ("privacy", "Privacy"),
    ("ai", "AI"),
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
            ("native", "Browser native"),
        ],
    },
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
        help: "Enables review replies, keyword generation and listing audits.",
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
    },
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
