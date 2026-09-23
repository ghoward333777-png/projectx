//! MediaMarketplace Studio core library.
//!
//! Everything that is not HTTP lives here: configuration, database access and
//! migrations, encryption of secrets, signed tokens shared with the WordPress and
//! Joomla bridge plugins, password hashing, settings, users and health checks.

pub mod audit;
pub mod backup;
pub mod commerce;
pub mod commerce_bridge;
pub mod config;
pub mod copyright;
pub mod currency;
pub mod db;
pub mod entitlements;
pub mod gateways;
pub mod google;
pub mod health;
pub mod integrations;
pub mod jobs;
pub mod mail;
pub mod media;
pub mod pages;
pub mod password;
pub mod pdf;
pub mod privacy;
pub mod products;
pub mod protection;
pub mod render;
pub mod secrets;
pub mod settings;
pub mod signer;
pub mod templates;
pub mod users;
pub mod widgets;

pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// UTC timestamp in the canonical storage format (RFC 3339, second precision).
pub fn now() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

/// Percent-encodes a query value (shared by the copyright and Google helpers).
pub fn copyright_urlencode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}
