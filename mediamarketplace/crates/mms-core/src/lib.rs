//! MediaMarketplace Studio core library.
//!
//! Everything that is not HTTP lives here: configuration, database access and
//! migrations, encryption of secrets, signed tokens shared with the WordPress and
//! Joomla bridge plugins, password hashing, settings, users and health checks.

pub mod audit;
pub mod commerce;
pub mod config;
pub mod db;
pub mod entitlements;
pub mod gateways;
pub mod health;
pub mod integrations;
pub mod jobs;
pub mod media;
pub mod pages;
pub mod password;
pub mod pdf;
pub mod products;
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
