MediaMarketplace Studio
=======================

A self-hosted media marketplace server written in Rust, with thin bridge plugins
for WordPress and Joomla. No WooCommerce, no VirtueMart, no vendor account.

Layout
------
  crates/mms-core      domain library: config, SQLite migrations, secrets, tokens, users, entitlements, settings, health
  crates/mms-server    the mms-server binary: CLI, admin UI, SSO, embeds, JSON API
  bridges/wordpress    WordPress plugin "MediaMarketplace Bridge"
  bridges/joomla       Joomla package "MediaMarketplace Bridge" (system plugin + module)
  deploy/              Dockerfile, docker-compose.yml, systemd unit, INSTALL.txt

Develop
-------
  cargo build                      build everything
  cargo test                       run all Rust tests
  cargo run -p mms-server -- init  create ./mms.toml and ./data
  cargo run -p mms-server          serve on 127.0.0.1:8090
  php ../tests/mms-bridge-contract.php   bridge plugin checks

The design specification lives in ../docs/MediaMarketplace-Studio-Design-Specification.docx.
