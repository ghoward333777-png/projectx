MediaMarketplace Studio
=======================

A complete media marketplace that installs as ONE package into a WordPress or Joomla
site and runs entirely on that site's server. No WooCommerce, no VirtueMart, no
separate server, no vendor account.

How it works
------------
  The package contains the marketplace server (mms-server, a Rust binary for Linux
  x86_64) and a small PHP runtime. On activation the runtime starts the binary on
  127.0.0.1 and proxies https://your-site/mms/... to it. Administrators open the
  store admin from the CMS menu; members sign in with one click.

Layout
------
  crates/mms-core        domain library: config, SQLite migrations, secrets, tokens, users, entitlements, settings, health
  crates/mms-server      the server: CLI, admin UI, SSO, embeds, JSON API
  packages/shared        MmsRuntime.php: starts, supervises and proxies the server (shipped in both packages)
  packages/wordpress     WordPress plugin "MediaMarketplace Studio"
  packages/joomla        Joomla package "MediaMarketplace Studio" (system plugin + admin component + module)
  build/package.sh       builds dist/mediamarketplace-studio-{wordpress,joomla}-<version>.zip

Develop
-------
  cargo test                              Rust tests
  ./build/package.sh                      release build + both zips
  php ../tests/mms-packages-contract.php  PHP checks, and a real start/proxy/sign-in run when the release binary exists

Requirements on the website's server
------------------------------------
  Linux x86_64 (VPS, dedicated or in-house virtual machine), PHP 8.1+ with curl,
  PHP allowed to start processes (exec/proc_open). Shared hosting that forbids
  background processes is not supported.

The specification and guides live in ../docs/ as Word documents.
