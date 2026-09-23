//! MediaMarketplace Studio core library.
//!
//! Everything that is not HTTP lives here: configuration, database access and
//! migrations, encryption of secrets, signed tokens shared with the WordPress and
//! Joomla bridge plugins, password hashing, settings, users and health checks.

pub mod audit;
pub mod config;
pub mod db;
pub mod entitlements;
pub mod health;
pub mod password;
pub mod secrets;
pub mod settings;
pub mod signer;
pub mod users;

pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// UTC timestamp in the canonical storage format (RFC 3339, second precision).
pub fn now() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}
