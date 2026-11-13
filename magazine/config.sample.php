<?php

/**
 * Copy this file to config.php and fill in what you need. Every value can also be set
 * as an environment variable named MAGAZINE_<KEY>, for example MAGAZINE_GOOGLE_CLIENT_ID.
 * config.php is ignored by git: never commit real keys.
 */
return [
    'site_name' => 'MINDATION.AI',
    'tagline' => 'Efficient, local, verifiable, auditable AI, for the people who lead.',

    // Public address of the magazine (used for share links and Google sign-in).
    'base_url' => 'https://mindation.ai/',
    'timezone' => 'UTC',

    // Google sign-in: create an OAuth 2.0 "Web application" client at
    // https://console.cloud.google.com/apis/credentials and register this redirect URI:
    //   <base_url>index.php?p=google-callback
    'google_client_id' => '',
    'google_client_secret' => '',

    // People who become administrators when they sign in with Google using these addresses.
    'admin_emails' => [],

    // Optional second anti-robot layer: Cloudflare Turnstile keys (https://dash.cloudflare.com → Turnstile).
    // The built-in proof-of-work, honeypot, time trap, and rate limits work without it.
    'turnstile_site_key' => '',
    'turnstile_secret' => '',

    // Proof-of-work size. Higher costs robots (and slow phones) more.
    'pow_max' => 50000,
];
