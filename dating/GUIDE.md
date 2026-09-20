# SlowDating — System Overview, Administration & User Guide

The operating manual for the SlowDating platform, in three parts: **Part I** explains
how the system is put together, **Part II** tells developers and administrators how to
run, deploy, extend, and operate it, and **Part III** is the guide for the people who
use it — members and partner businesses. Companion documents: `FEATURE_SPEC.md`
(per-feature rules), `DESIGN_SPEC.md` (architecture and data model), `openapi.yaml`
(API schemas).

---

# Part I — System Overview

## What the system is

SlowDating is a self-contained dating SaaS application: a member app, a partner
portal, an admin console, public education pages, a JSON API, and inbound webhooks —
all served by dependency-free PHP 8.1+. There is no database server, no Composer, no
API key, and no build step: state lives in JSON files, and the whole application
deploys by copying one folder to any PHP-capable host.

Its defining behavior: chats start slow (limited message size and frequency), personal
contact data is erased from messages, and a conversation earns unlimited real-time
chat — and the right to share contact details — only after **30 days and 10 two-sided
conversations**.

## The pieces

| File | Role |
|---|---|
| `SlowDatingEngine.php` | Every business rule: accounts, chat pacing and filtering, popularity, matching, coupons, events, contests, store, rewards, safety, webhooks. All time-dependent methods take an explicit timestamp, so behavior is reproducible. |
| `SlowDatingStore.php` | Persistence: one JSON file per collection under `dating/state/` (gitignored), records keyed by id, write-through cache. |
| `SlowDatingApi.php` | The REST contract as one routing class — testable without a web server. |
| `api.php` | HTTP entry for the API (`PATH_INFO` routing, or `api.php?route=/…` on hosts without it). |
| `index.php` | The member app (signup/login + tabs: Matches, Search, Chats, Profile, Coupons & rewards, Store, Membership). |
| `partner-portal.php` | Partner dashboard: venues, coupons, events, contests, products, analytics. |
| `admin.php` | Admin console: leaderboard and reward campaigns. |
| `safety-center.php`, `smart-dating.php`, `site-tour.php` | Public pages: safety education, the nine-article science library, the screenshot slideshow tour. |
| `ui.php` | Shared responsive page frame and stylesheet. |
| `bin/seed-demo.php` | One-command demo world (wipes and reseeds `state/`). |

## How a request flows

1. **Browser pages** call the engine directly: form POST → engine method → JSON state
   updated → page re-renders. Sessions hold the bearer token server-side.
2. **API clients** hit `api.php`; the router authenticates the bearer token, resolves
   the route for that principal type (member, partner, or admin — tokens never cross
   roles), calls the engine, and returns JSON. Errors are always
   `{error_code, message}` with 401/403/404/422.
3. **External systems** (ticketing, reservations, bodyguard partners) POST signed
   webhooks; the signature header is compared in constant time against the
   `SLOWDATING_WEBHOOK_SECRET` environment variable.

## Where data lives

Collections under `dating/state/` (created on demand): `users`, `tokens` (SHA-256
digests only), `chats` (messages stored post-filter), `partners`, `venues`, `coupons`,
`redemptions`, `events`, `tickets`, `contests`, `contest_entries`, `products`,
`orders`, `popularity_events`, `safety_events`, `admins`, `rewards`, `bookings`,
`analytics_events`. Backing up the platform means copying this one directory.

## Invariants that must not regress

- Same inputs → same outputs, everywhere except credential generation.
- Contact data in locked chats is erased **before** storage — never persisted, never logged.
- Raw popularity counts never leave the owner's own breakdown view.
- The strong-password policy applies to members, partners, and admins alike.
- Every new app file is registered in `SitePackageExporter::FILES`, and every test in
  `tests/` passes before shipping.

---

# Part II — Developer & Administrator Guide

## Requirements

PHP 8.1 or newer. Nothing else. Optional: the `zip` extension if you use the hosting
package exporter, and `ext-intl` for the book app that shares this repository.

## Run it locally

```bash
# from the repository root
php -S 127.0.0.1:8082
# then open http://127.0.0.1:8082/dating/index.php
```

Load the demo world (six members, live chats in both phases, three partners, coupons,
an event, a contest, products, an admin, executed reward campaigns):

```bash
php dating/bin/seed-demo.php
# prints the three demo logins (member / partner / admin)
```

The seeder **wipes** `dating/state/` — demo and development use only.

## Run the tests

```bash
php tests/dating-engine-contract.php   # every engine rule
php tests/dating-api-contract.php      # the full HTTP contract
```

Both must print `… passed`. Run the whole `tests/` directory before shipping anything;
the site-package test also verifies every registered file exists.

## Deploy to shared hosting (GoDaddy, Hostinger, Bluehost, …)

1. Upload the `dating/` folder into the host's web root (`public_html`, `htdocs`, or `www`).
2. Ensure the web server can **write** to `dating/state/` (create it if needed;
   permissions `0775` typically suffice).
3. Visit `https://your-domain.com/dating/` — the member app is the index.
4. If partners' external systems will post webhooks, set the environment variable
   `SLOWDATING_WEBHOOK_SECRET` (in cPanel: *Software → Environment Variables*, or via
   `.htaccess` `SetEnv`). Webhooks are rejected until it is set.
5. Optional hardening: put `dating/state/` outside the web root by constructing the
   store with a custom path, or deny direct HTTP access to `state/` in `.htaccess`.

Note: site-builder products (GoDaddy Airo / Websites+Marketing, Wix, Squarespace)
cannot run this application — they don't execute custom PHP. Use the host's classic
web-hosting/cPanel product.

## Configuration reference

| Setting | Where | Effect |
|---|---|---|
| `SLOWDATING_WEBHOOK_SECRET` | environment variable | Shared secret for `/webhooks/*`; unset = all webhooks rejected. |
| Store directory | `new SlowDatingStore('/path')` | Relocate state (tests use a temp dir this way). |
| Pacing, unlock, weights, prices, tiers | class constants at the top of `SlowDatingEngine.php` | `PACING`, `UNLOCK_DAYS`, `UNLOCK_SESSIONS`, `POPULARITY_WEIGHTS`, `MATCH_WEIGHTS`, `MEMBERSHIP_PRICES`, `PARTNER_TIERS`, `REWARD_COHORTS`. Change here, then update `FEATURE_SPEC.md` and the tests. |

## Administer the platform

**Create the first admin (once).** Open `/dating/admin.php` and use the bootstrap
form, or:

```bash
curl -X POST https://your-domain/dating/api.php?route=/admin/v1/bootstrap \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@company.com"}'        # returns the one-time generated password
```

The bootstrap is rejected forever after the first admin exists; only an admin can
create another admin.

**Day-to-day admin work** happens in the console (`admin.php`): review the popularity
leaderboard (ranked by raw engagement received), grant reward campaigns to the top
10/50/100 (free membership, gift certificates, products, event tickets, promo trips),
and audit the grants log. Every grant records who gave what to whom, at what rank, when.

**Moderation signals.** Red-flag safety events accumulate per protected member in
`safety_events`; a member's own list is at `GET /users/me/safety/events`. Review the
collection directly for platform-wide patterns (repeat `actor_user_id`s are your
moderation queue).

**Backups.** Copy `dating/state/` on a schedule; restoring is copying it back. The
files are human-readable JSON — auditable with any text tool.

## Extend the platform

1. Add the rule to `SlowDatingEngine` (accept `?int $now` if time matters).
2. Expose it in `SlowDatingApi::route()` under the right principal, and in the
   relevant page.
3. Add assertions to both dating contract tests.
4. Register any new file in `SitePackageExporter::FILES`.
5. Update `FEATURE_SPEC.md` / `openapi.yaml`, run every test in `tests/`, ship.

The single-class engine is deliberate at this stage; the service decomposition map in
`DESIGN_SPEC.md` §9.2 says exactly which methods move to which microservice when scale
demands it — API paths don't change.

## Use the API (quick reference)

```bash
BASE=https://your-domain/dating/api.php?route=

# sign up (auto-generated strong password) and keep the token
curl -X POST "${BASE}/auth/signup" -d '{"email":"a@b.com","use_auto_password":true}'

# authenticated calls
curl -H "Authorization: Bearer $TOKEN" "${BASE}/users/search&gender=female&income_range=100k_150k&automobile=ev"
curl -H "Authorization: Bearer $TOKEN" "${BASE}/matches"
curl -X POST -H "Authorization: Bearer $TOKEN" "${BASE}/chats" -d '{"user_id":"U20260919-ABC12"}'
curl -X POST -H "Authorization: Bearer $TOKEN" "${BASE}/chats/CHAT_ID/messages" -d '{"text":"hello"}'

# signed webhook from a ticketing partner
curl -X POST "${BASE}/webhooks/tickets/purchased" \
  -H "X-Webhook-Signature: $SLOWDATING_WEBHOOK_SECRET" \
  -d '{"event_id":"evt_1","external_ticket_id":"t9","user_external_id":"U…","quantity":2,"total_amount":50}'
```

Full schemas: `openapi.yaml`. Member, partner, and admin tokens are not
interchangeable — a partner token calling a member route gets 404, by design.

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| "Could not create the state directory" | Web server can't write to `dating/state/` — create it and fix permissions. |
| Every webhook returns 401 | `SLOWDATING_WEBHOOK_SECRET` unset or header mismatch — it's `X-Webhook-Signature`, compared exactly. |
| API returns 404 for a route that exists | Wrong principal's token, or `PATH_INFO` unavailable on the host — use the `?route=/…` form. |
| "Slow-chat stage: …" errors in chat | Working as designed — the pacing quota or size cap for that chat's age. |
| Demo logins stop working | Something re-ran `bin/seed-demo.php`, which resets state. Restore from backup. |

---

# Part III — User Guide

## For members

**Joining.** Sign up with your email. Pick a strong password (at least 12 characters
mixing capitals, small letters, numbers, and symbols) or leave the box blank and the
site generates one for you — shown once, so store it in a password manager. You must
be 18 or older.

**Your profile.** Fill in what matters for matching: age, zip code, interests,
hobbies, outdoor activities, the kind of relationship you want, faith, politics,
income bracket, car, and occupation. Everything you fill in becomes searchable — by
you and about you. You can embed up to five YouTube videos. Your popularity breakdown
(who-did-what counts) is visible only to you; others see just your 0–100 rating.

**Finding people.** *Matches* ranks the community for you on eleven compatibility
ingredients and shows what you share with each person. *Search* filters by any
combination of profile facts — distance, age, interests, income, car, occupation, and
more. From either, one tap starts a slow chat.

**Chatting.** New chats are deliberately slow: five messages a day of 280 characters
in week one, loosening each week. Until a chat unlocks, phone numbers, emails, links,
and social handles are removed from messages automatically — that's the app protecting
you both, not censoring you. Your chat header always shows the pace, the day count,
and the conversation count. A chat unlocks into unlimited real-time messaging when it
is 30 days old **and** you've had 10 days of genuine two-way exchange — then contact
sharing is up to you. VIP members can unlock a chat early. Watch the concierge cards
under each chat: they suggest real nearby venues based on what you're both talking
about.

**If something feels wrong.** Messages that pressure you for money, rush you, or push
you off the platform raise an automatic safety alert on your account. Read the Safety
Center (linked on every page) for red flags, the first-date checklist, and exit
strategies. Chaperone service from professional bodyguard partners can be booked for
any date.

**Coupons, events, and the store.** Partner venues send discounts straight to your
wallet — redeem them at the venue before they expire (each works once). Buy tickets to
singles events in the app; if the venue runs a contest, your ticket enters you
automatically. The store sells date-night kits and gifts from partners.

**Rewards.** The most engaging members periodically receive free benefits from the
platform — memberships, gift certificates, tickets, even sponsored trips. If you're
granted one, it appears in *Coupons & rewards*.

**Membership.** Free accounts browse, match, and slow-chat. $19/year makes you a full
Member; $79 VIP adds early chat unlock and a profile boost; $199 Elite adds chaperone
priority and elite events.

## For partner businesses

**Getting started.** Sign up in the Partner Portal with your business name and email;
choose Basic (free), Pro, or Elite. Create a venue for each location with its
category (restaurant, lounge, cruise, tour, experience, bodyguard, vendor) and its
atmosphere tags — *quiet*, *romantic*, *no kids*, *jazz*, *dance-friendly*, *game
night*. Honest tags matter: they are exactly what the date concierge uses to recommend
you inside members' chats.

**Reaching members.** Send *random coupons* to members near your venue, or (Pro/Elite)
*targeted coupons* to a precise audience — gender, age range, radius, interests. The
form shows your estimated reach before you send. Announce singles events with capacity
and ticket price; tickets sell in the app and can never oversell. (Pro/Elite) attach a
contest to your tickets — every buyer is entered automatically, and you see entry
totals, never member identities.

**Selling products.** List date-night products with price and stock; the store handles
orders and draws down your inventory.

**Reading your numbers.** Each venue's dashboard shows coupons sent, redemptions,
tickets sold, ticket revenue, and contest entries — live, computed from the actual
records. If you sell tickets or take bookings in your own system, your provider can
report them into the platform automatically; ask the site operator for the webhook
credentials.

## Where to learn more

- **Site Tour** — every page in one minute, as a slideshow.
- **Smart Dating** — nine short articles on the science behind slow dating.
- **Safety Center** — the safety education hub, open to everyone.
