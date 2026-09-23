=== MediaMarketplace Studio ===
Contributors: mediamarketplace
Tags: media, marketplace, video, audio, digital downloads, memberships
Requires at least: 6.4
Tested up to: 6.7
Requires PHP: 8.1
Stable tag: 0.2.0
License: GPLv3 or later

A complete media marketplace that runs inside your WordPress site. No WooCommerce, no external services.

== Description ==

MediaMarketplace Studio sells and protects digital media: video, audio, images, PDFs, live
sessions, meetings, private pages and site passes. Everything runs on your own server: the
plugin bundles the marketplace server, starts it on activation and reaches it at
https://your-site/mms/. Administrators open the store admin from the WordPress menu; members
sign in with one click.

Requirements: a Linux server (VPS, dedicated or in-house virtual machine) with x86_64 CPU where
PHP may start processes. Shared hosting that forbids background processes is not supported.

== Installation ==

1. Plugins > Add New Plugin > Upload Plugin, choose the zip, Install Now, Activate.
2. Open MediaMarketplace > Status and check the server is running.
3. Place [mms_showcase] on a page. Click MediaMarketplace in the menu to manage the store.

== Changelog ==

= 0.2.0 =
* Bundled server, in-site proxy at /mms/, one-click admin sign-in, status page.
