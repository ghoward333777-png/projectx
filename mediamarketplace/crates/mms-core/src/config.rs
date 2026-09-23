use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// Server configuration. Loaded from a TOML file, with a few environment overrides
/// (`MMS_BIND`, `MMS_PUBLIC_URL`, `MMS_DATA_DIR`, `MMS_SECRET_KEY`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub server: ServerConfig,
    pub data_dir: PathBuf,
    pub security: SecurityConfig,
    #[serde(default)]
    pub media: MediaConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerConfig {
    /// Socket address to listen on, e.g. "127.0.0.1:8090". Put a reverse proxy in front for TLS.
    pub bind: String,
    /// Public base URL as seen by browsers and bridge plugins, e.g. "https://media.example.com".
    pub public_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecurityConfig {
    /// Random secret (base64). Derives the cookie signing key and the secrets encryption key.
    pub secret_key: String,
    /// Session lifetime in seconds.
    #[serde(default = "default_session_ttl")]
    pub session_ttl_seconds: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MediaConfig {
    #[serde(default = "default_max_upload_mb")]
    pub max_upload_mb: u64,
    #[serde(default = "default_ffmpeg")]
    pub ffmpeg_path: String,
}

impl Default for MediaConfig {
    fn default() -> Self {
        Self {
            max_upload_mb: default_max_upload_mb(),
            ffmpeg_path: default_ffmpeg(),
        }
    }
}

fn default_session_ttl() -> u64 {
    60 * 60 * 12
}
fn default_max_upload_mb() -> u64 {
    512
}
fn default_ffmpeg() -> String {
    "ffmpeg".to_string()
}

impl Config {
    /// A fresh configuration for `init`, with a newly generated secret key.
    pub fn generate(data_dir: PathBuf, bind: &str, public_url: &str) -> Self {
        use base64::Engine;
        use rand::RngCore;
        let mut key = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut key);
        Self {
            server: ServerConfig {
                bind: bind.to_string(),
                public_url: public_url.trim_end_matches('/').to_string(),
            },
            data_dir,
            security: SecurityConfig {
                secret_key: base64::engine::general_purpose::STANDARD.encode(key),
                session_ttl_seconds: default_session_ttl(),
            },
            media: MediaConfig::default(),
        }
    }

    pub fn load(path: &Path) -> Result<Self> {
        let text = std::fs::read_to_string(path)
            .with_context(|| format!("reading config {}", path.display()))?;
        let mut cfg: Config =
            toml::from_str(&text).with_context(|| format!("parsing config {}", path.display()))?;
        cfg.apply_env();
        cfg.validate()?;
        Ok(cfg)
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let text = toml::to_string_pretty(self)?;
        std::fs::write(path, text).with_context(|| format!("writing config {}", path.display()))
    }

    fn apply_env(&mut self) {
        if let Ok(v) = std::env::var("MMS_BIND") {
            self.server.bind = v;
        }
        if let Ok(v) = std::env::var("MMS_PUBLIC_URL") {
            self.server.public_url = v.trim_end_matches('/').to_string();
        }
        if let Ok(v) = std::env::var("MMS_DATA_DIR") {
            self.data_dir = PathBuf::from(v);
        }
        if let Ok(v) = std::env::var("MMS_SECRET_KEY") {
            self.security.secret_key = v;
        }
    }

    pub fn validate(&self) -> Result<()> {
        anyhow::ensure!(
            !self.server.bind.is_empty(),
            "server.bind must not be empty"
        );
        anyhow::ensure!(
            self.server.public_url.starts_with("http://")
                || self.server.public_url.starts_with("https://"),
            "server.public_url must start with http:// or https://"
        );
        anyhow::ensure!(
            self.secret_key_bytes()
                .map(|k| k.len() >= 32)
                .unwrap_or(false),
            "security.secret_key must be at least 32 bytes of base64"
        );
        Ok(())
    }

    pub fn secret_key_bytes(&self) -> Result<Vec<u8>> {
        use base64::Engine;
        base64::engine::general_purpose::STANDARD
            .decode(self.security.secret_key.trim())
            .context("security.secret_key is not valid base64")
    }

    pub fn database_path(&self) -> PathBuf {
        self.data_dir.join("mms.sqlite")
    }
    pub fn media_public_dir(&self) -> PathBuf {
        self.data_dir.join("media").join("public")
    }
    pub fn media_private_dir(&self) -> PathBuf {
        self.data_dir.join("media").join("private")
    }

    pub fn database_url(&self) -> String {
        format!("sqlite://{}?mode=rwc", self.database_path().display())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_config_round_trips_and_validates() {
        let cfg = Config::generate(
            PathBuf::from("/tmp/mms"),
            "127.0.0.1:8090",
            "http://localhost:8090/",
        );
        cfg.validate().unwrap();
        let text = toml::to_string(&cfg).unwrap();
        let back: Config = toml::from_str(&text).unwrap();
        assert_eq!(back.server.public_url, "http://localhost:8090");
        assert_eq!(back.security.secret_key, cfg.security.secret_key);
        assert_eq!(back.media.max_upload_mb, 512);
    }

    #[test]
    fn rejects_short_secret() {
        let mut cfg = Config::generate(PathBuf::from("/tmp/mms"), "127.0.0.1:8090", "http://x");
        cfg.security.secret_key = "c2hvcnQ=".into();
        assert!(cfg.validate().is_err());
    }
}
