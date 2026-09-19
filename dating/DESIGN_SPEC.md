# SlowDating — Consolidated Design Specification

This is the single authoritative design specification for the SlowDating platform. It
consolidates every technical specification produced during product design — business
model, feature set, slow-chat mechanics, popularity and matching algorithms, the partner
ecosystem, admin rewards, safety architecture, the API catalog with service mapping, the
data model, and webhooks — into one document. The full machine-readable API contract
lives beside it in [`openapi.yaml`](openapi.yaml). The reference implementation in this
directory is a working SaaS web application (desktop and mobile responsive) built as a
dependency-free PHP 8.1+ modular monolith whose module boundaries mirror the target
microservice architecture described in §9.

---

## 1. Product vision & business model

SlowDating is a **slow-paced, trust-first dating ecosystem**, not a swipe app:

- **Free to join, ad-monetized**, with a **$19/year membership** as the primary paid tier.
  The fee filters out bots and unserious accounts and creates predictable annual revenue;
  ads monetize the daily engagement the slow-chat cycle guarantees.
- **Contact information can only be exchanged after a chat has lived 30 days and produced
  at least 10 real conversations.** Until then, personal contact data (phone numbers,
  emails, links, social handles) is **erased and filtered** out of every message.
- **Chat starts slow and speeds up**: message size and daily frequency are limited at the
  start of a relationship and widen on a fixed schedule until the chat unlocks into
  real-time messaging.
- **Real-world outcomes**: partner venues (restaurants, lounges, cruise lines, tour and
  experience companies), a date-night store, an AI date concierge that reads the chat and
  suggests vetted places, and VIP bodyguard/chaperone services.
- **Safety-first, women-first**: proactive filtering, red-flag detection, safety
  education, vetted venues, and privacy-preserving popularity scores.

### Revenue stack

| Stream | Mechanism |
|---|---|
| Membership | $19/yr Member, $79/yr VIP (early chat unlock, boost), $199/yr Elite |
| Advertising | Slow-chat pacing maximizes sessions over the 30-day cycle → impressions |
| Partner plans | Basic (free), Pro (targeted coupons, contests, analytics), Elite (priority concierge placement, deep analytics) |
| Commerce | Marketplace orders, event ticket commissions, experience bookings |
| Premium safety | VIP chaperone bookings, priority safety services |
| Admin promotions | Leaderboard reward campaigns drive engagement and retention |

---

## 2. Accounts, identity & passwords

- **User IDs are always platform-generated** (`U<yyyymmdd>-<5 base32 chars>`); users never
  choose them.
- **All passwords must be strong.** Policy: ≥ 12 characters, at least one uppercase,
  lowercase, digit, and symbol, and not on the common-password blacklist.
- At signup the user either supplies a password (validated against the policy, rejected
  when weak) or receives an **auto-generated strong password** (16–24 chars, all four
  classes), shown exactly once.
- Only password **hashes** are stored (`password_hash`, bcrypt/Argon2 family). Sessions
  use opaque bearer tokens, stored server-side as SHA-256 digests.
- Members must be **18 or older**.
- The same policy applies to partner and admin accounts.

## 3. Profiles

Profile fields — all searchable (§6):

- `display_name`, `age`, `gender`, `zip_code`
- `interests[]`, `hobbies[]`, `outdoor_activities[]`
- `dating_type`: `long_term | short_term | casual | marriage | slow_dating`
- `faith`, `politics`
- `income_range`: `under_30k | 30k_60k | 60k_100k | 100k_150k | 150k_plus`
- `automobile`: `none | economy | sedan | luxury | sports | suv | truck | ev`
- `occupation_category` (normalized: medical, legal, tech, finance, arts, …)
- **YouTube videos** (max 5): only real YouTube URLs (`watch?v=`, `youtu.be/`, `/embed/`,
  `/shorts/`) are accepted; the embed URL is always derived server-side from the parsed
  video key — user-supplied markup never reaches the page.

## 4. Slow chat — pacing, filtering, unlock

The defining product mechanic.

### 4.1 Pacing schedule (per sender, per chat)

| Chat age | Messages/day | Max chars/message |
|---|---|---|
| Days 0–6 | 5 | 280 |
| Days 7–13 | 10 | 500 |
| Days 14–20 | 20 | 1,000 |
| Days 21+ | 40 | 2,000 |
| Unlocked | unlimited | unlimited |

### 4.2 Unlock rule

A chat unlocks into real time when **both** conditions hold:

- the chat is at least **30 days** old, **and**
- it has accumulated at least **10 completed sessions** — a session is a calendar day
  (UTC) on which **both** participants sent at least one message (a real conversation,
  not a monologue).

VIP/Elite members may purchase **early unlock** for a chat (premium upsell).

### 4.3 Contact-data erasure (until unlock)

Before unlock, every message is filtered: emails, phone-like digit runs, URLs, `www.`
hosts, `@handles`, and `instagram/snapchat/telegram/whatsapp/signal + handle` patterns are
**erased** (replaced with `[contact info removed]`) *before storage* — the removed data is
never persisted. The sender is told how many items were removed. After unlock, contact
sharing is allowed and messages flow unfiltered.

### 4.4 Red-flag detection (always on, before and after unlock)

Deterministic pattern rules raise a **safety event** on the recipient's account for:
money requests (wire/gift cards/crypto/bank details), urgency pressure, off-platform
pushes, and coercion. Safety events feed the member's safety timeline and moderation.

### 4.5 Compliment detection

Messages matching compliment patterns credit the **recipient** with a `compliment`
popularity event (§5).

## 5. Popularity rating

Members accumulate weighted engagement **received** (never sent):

| Event | Weight |
|---|---|
| photo_received | 5 |
| compliment | 4 |
| chat_request | 3 |
| event_invite | 3 |
| message_received | 2 |
| like | 2 |
| profile_view | 1 |
| coupon_target | 1 |

- **Normalization**: `score = min(100, round(raw / cohort_average × 50))` — the cohort
  average sits at 50, leaving headroom above it. Cohorts are **per gender** so one
  gender's traffic volume never distorts the other's scores.
- Profiles expose **only** the normalized score (0–100), percentile, and trend
  (rising/stable/falling from the last 7 days vs the prior 7). **Raw counts are never
  shown to other members**; the metric breakdown is owner-only.
- Members can search and sort by popularity (`min_popularity`, `max_popularity`).
- Abusive attention is excluded: red-flagged interactions do not have to be credited, and
  the moderation pipeline can void events from banned actors.

## 6. Search & matching

### 6.1 Member search (`GET /users/search`)

Filters: `zip_code` + `zip_radius_km`, `gender`, `age_min/max`, `interests`, `hobbies`,
`outdoor_activities`, `dating_type`, `faith`, `politics`, `income_range`, `automobile`,
`occupation_category`, `min_popularity`, `max_popularity`. Results are ordered by
popularity, then id (deterministic).

### 6.2 Zip-code proximity

The reference implementation ships a deterministic proxy — shared leading zip digits map
to distance bands (same zip = 0 km, 4 shared = 2 km, … none shared = 400 km) — behind a
single method (`zipProximityKm`) that production swaps for a real geo dataset without
touching callers.

### 6.3 Match scoring

`match_score = Σ factor × weight × 100`, factors each 0.0–1.0:

| Factor | Weight | Scoring |
|---|---|---|
| distance | 0.20 | `1 − km/200`, floored at 0 |
| interests | 0.15 | Jaccard overlap (empty lists neutral 0.5) |
| dating_type | 0.15 | exact 1.0 / unspecified 0.6 / mismatch 0.2 |
| hobbies | 0.10 | Jaccard overlap |
| faith | 0.08 | exact / unspecified / mismatch |
| politics | 0.07 | exact / unspecified / mismatch |
| popularity_balance | 0.07 | `1 − |a−b|/100` (matches active with active) |
| income | 0.05 | `1 − bracket distance × 0.2`, floor 0.2 |
| occupation | 0.05 | exact / unspecified / mismatch |
| outdoor_activities | 0.05 | Jaccard overlap |
| automobile | 0.03 | same 1.0, otherwise neutral 0.7 |

Match responses carry the factor breakdown, shared interests/hobbies, distance, and
recommended nearby venues. `GET /matches/search` accepts the full §6.1 filter set.

## 7. Partner ecosystem

Partner types: restaurants, lounges, cruise lines, tour companies, experience providers
(escape rooms, detective games…), bodyguard/chaperone services, marketplace vendors.

- **Self-service signup** with plan tiers: **Basic** (listing, random coupons, events),
  **Pro** (+ targeted coupons, contests, analytics), **Elite** (+ priority concierge
  placement, deep analytics).
- **Venues** carry category, zip code, and atmosphere tags (`quiet`, `romantic`,
  `no_kids`, `dance_friendly`, `jazz`, `game_night`, `outdoor`…). Only date-compatible,
  vetted venues are surfaced.
- **Random coupons**: sent to up to `max_recipients` members near the venue.
- **Targeted coupons** (Pro/Elite): segment by gender, age range, zip radius, interests,
  relationship stage — e.g. "all women 18–30 within 20 km". Targeted delivery credits
  recipients with a `coupon_target` popularity event. Coupons expire, live in the member
  wallet, and redeem exactly once.
- **Events**: singles nights with tags, capacity, ticketing (internal or external via
  webhook); announced to members.
- **Contests** (Pro/Elite): prize + rules, eligibility strictly **ticket buyers**;
  entries are created automatically at ticket purchase (internal or webhook) and reported
  only as privacy-preserving aggregates.
- **Products**: partner-listed items in the member store (date-night kits, gifts…);
  orders draw down inventory.
- **Analytics per venue**: coupons created, redemptions, events, tickets sold, ticket
  revenue, contest entries.

## 8. AI date concierge, safety center, admin rewards

### 8.1 Date concierge

Reads the chat both members are having **on the platform** (the consent boundary),
extracts topic keywords (jazz, italian, dancing, wine, escape room, cruise, hiking…), and
suggests up to 3 nearby vetted venues, ranking atmosphere-tag matches above category-only
matches, then by proximity. Deterministic and explainable — every suggestion carries its
reason ("You both talked about jazz — Blue Note Lounge fits that mood"). Elite partners
get priority placement.

### 8.2 Safety architecture (women-first)

1. **Prevention**: contact-data erasure (§4.3), slow pacing (§4.1), strong passwords (§2).
2. **Detection**: red-flag rules (§4.4) raising per-member safety events.
3. **Education**: the public Safety Center — red flags, first-date checklist, exit
   strategies.
4. **Real-world protection**: vetted venues only; VIP bodyguard/chaperone partners
   (discreet escorts, safe-arrival verification, emergency response) bookable per date,
   ingested via webhook.
5. **Privacy**: normalized popularity only; no raw attention counts; aggregated contest
   entries; webhook payloads keyed by opaque external ids.

### 8.3 Admin rewards program

Admins (bootstrap first admin, then admin-only creation) can grant **free benefits to the
top 10, top 50, or top 100 members** on the popularity leaderboard (ranked by raw
engagement received, which is comparable across gender cohorts):

- free membership (any tier — applied immediately for a year)
- gift certificates (fixed amount)
- free products and free event tickets
- **all-expense-paid trips to company promotions**

Every grant is recorded per member with the campaign id, rank, admin, and timestamp;
members see their rewards in the app.

---

## 9. Architecture

### 9.1 Reference implementation (this directory)

Dependency-free PHP 8.1+, no database, no Composer, no API keys — one JSON file per
collection (`SlowDatingStore`), all domain logic in `SlowDatingEngine`, the HTTP contract
in `SlowDatingApi` + `api.php`, and four responsive UI pages:

| File | Role |
|---|---|
| `SlowDatingStore.php` | JSON collection store (`dating/state/`, gitignored) |
| `SlowDatingEngine.php` | All domain logic (deterministic given explicit `$now`) |
| `SlowDatingApi.php` | Router: the full REST contract as a testable method |
| `api.php` | HTTP entry (`PATH_INFO` or `api.php?route=/…`) |
| `index.php` | Member app (desktop + mobile responsive) |
| `partner-portal.php` | Partner dashboard |
| `admin.php` | Admin console (leaderboard + reward campaigns) |
| `safety-center.php` | Public safety education |
| `ui.php` | Shared responsive page frame |

Tests: `php tests/dating-engine-contract.php` and `php tests/dating-api-contract.php`.

### 9.2 Target service decomposition (scale-out)

The engine's sections map 1:1 onto the production microservice plan; the API paths do not
change:

| Service | Owns | Endpoints |
|---|---|---|
| Auth | tokens, passwords | `/auth/*`, `/partners/v1/login`, `/admin/v1/login` |
| User | profiles, videos, memberships | `/users/me/profile*`, `/users/search`, `/users/me/billing/*` |
| Messaging | chats, pacing, filtering, unlock | `/chats*` |
| Matching | scoring, match search | `/matches*` |
| Popularity | events, scores, leaderboard | `/users/*/popularity*`, `/popularity/events`, `/users/search/popular` |
| Partner | partners, venues, plans | `/partners/v1/me`, `/partners/v1/venues*`, `/partners/v1/billing/*` |
| Offer | coupons, targeting, redemptions | `…/coupons/*`, `/users/me/coupons`, `/coupons/{id}/redeem` |
| Event | events, tickets | `…/events*`, `/events/{id}/tickets` |
| Contest | contests, entries | `…/contests*` |
| Marketplace | products, orders | `…/products*`, `/products`, `/orders` |
| Safety & AI | red flags, safety events, concierge | `/users/me/safety/*`, `/safety/resources`, `/chats/{id}/concierge` |
| Admin | admins, reward campaigns | `/admin/v1/*` |
| Analytics | rollups | `…/analytics` |
| Webhooks | external ingestion | `/webhooks/*` |

Production infrastructure: API gateway (auth, rate limits, routing), relational store for
core entities, document store for message content and AI logs, cache for throttle
counters and proximity lookups, and a notification service (email/SMS/push).

## 10. Data model

Collections (reference) / tables (production):

- **users**: id, email, password_hash, membership_tier, membership_expires_at, profile
  {all §3 fields}, videos[]
- **tokens**: sha256(token) → subject_id, kind (member|partner|admin), issued_at
- **chats**: id, pair_key, participants[2], started_at, early_unlock, messages[]
  (message_id, sender_id, text *post-filter*, sent_at, contact_data_removed, red_flags[])
- **popularity_events**: user_id, event_type, weight, timestamp
- **partners**: id, business_name, contact_email, password_hash, plan_tier
- **venues**: id, partner_id, name, address, zip_code, category, atmosphere_tags[],
  safety_score, status
- **coupons**: id, venue_id, type (random|targeted), discount_type, discount_amount,
  valid_from/to, max_recipients, targeting{}, recipients[]
- **redemptions**: coupon_id, user_id, redeemed_at (unique per pair)
- **events**: id, venue_id, title, description, date_time, capacity, tags[], ticket_price
- **tickets**: id, event_id, user_id, quantity, total_amount, purchased_at, source
  (internal|external)
- **contests**: id, venue_id, prize, rules, eligibility_type=ticket_buyers, event_id,
  start/end/draw dates
- **contest_entries**: contest_id, user_id, entry_date (unique per pair)
- **products** / **orders**: marketplace catalog and purchases
- **safety_events**: protected_user_id, actor_user_id, chat_id, flags[], created_at
- **admins**, **rewards** (campaign_id, user_id, reward_type, detail{rank,…},
  granted_by, granted_at), **bookings** (venue/bodyguard, from webhooks),
  **analytics_events** (type, user_id, venue_id, details, timestamp)

## 11. API catalog

Full request/response schemas in [`openapi.yaml`](openapi.yaml). Auth is
`Authorization: Bearer <token>`; errors are `{error_code, message}` with 401/403/404/422.

**Public** — `POST /auth/signup`, `POST /auth/login`, `POST /partners/v1/signup`,
`POST /partners/v1/login`, `POST /admin/v1/bootstrap`, `POST /admin/v1/login`,
`GET /safety/resources`, `POST /webhooks/*`.

**Member** — `GET|PATCH /users/me/profile`; `POST|DELETE /users/me/profile/videos[/{id}]`;
`GET /users/search`, `GET /users/search/popular`; `GET /users/{id|me}/popularity`
(viewing another profile records a `profile_view`); `GET /users/me/popularity/breakdown`
(owner-only); `POST /popularity/events` (internal); `GET /matches`, `GET /matches/search`;
`POST|GET /chats`; `POST|GET /chats/{id}/messages`; `GET /chats/{id}/status`;
`POST /chats/{id}/unlock` (VIP); `GET /chats/{id}/concierge`; `GET /users/me/coupons`;
`POST /coupons/{id}/redeem`; `GET /products`; `POST /orders`;
`POST /events/{id}/tickets`; `GET /users/me/safety/events`;
`GET /users/me/safety/resources`; `GET /users/me/rewards`;
`POST /users/me/billing/subscribe`.

**Partner** — `GET /partners/v1/me`; `GET|POST /partners/v1/venues`;
`PATCH /partners/v1/venues/{id}`; `POST …/coupons/random`, `POST …/coupons/targeted`,
`GET …/coupons`; `POST|GET …/events`; `POST|GET …/contests`;
`GET /partners/v1/contests/{id}/entries`; `POST|GET …/products`; `GET …/analytics`;
`GET /partners/v1/billing/plan`, `POST /partners/v1/billing/plan/change`.

**Admin** — `GET /admin/v1/leaderboard?count=N`; `POST /admin/v1/rewards/top`
(`{cohort: 10|50|100, benefit: {type, …}}`); `POST /admin/v1/admins`.

Tokens are role-scoped: member routes never resolve for partner/admin tokens and vice
versa.

## 12. Webhooks (ticketing, bookings, bodyguard)

Inbound `POST` endpoints authenticated with the shared secret header
`X-Webhook-Signature` (constant-time compare against `SLOWDATING_WEBHOOK_SECRET`);
unsigned calls get 401:

- `/webhooks/tickets/purchased` — `{event_id, external_ticket_id, user_external_id,
  purchase_time, quantity, total_amount}` → ticket record, contest auto-entry, analytics.
- `/webhooks/bookings/created` — `{booking_id, venue_external_id, user_external_id,
  date_time, party_size, status}` → booking record + analytics.
- `/webhooks/bodyguard/booked` — `{service_id, booking_id, user_external_id, date_time,
  duration_minutes, status}` → safety-visible booking + analytics.

## 13. Engineering invariants

- **Deterministic where the product depends on it**: every time-based rule takes an
  explicit `$now`; identical inputs produce identical pacing, unlock, popularity,
  matching, targeting, and concierge results. Randomness is confined to credentials
  (passwords, tokens, id suffixes).
- **Contact data is erased before storage** in locked chats — never stored, never logged.
- **No raw attention counts** ever leave the owner's own breakdown view.
- **Strong-password policy applies to every principal** (member, partner, admin).
- Webhook signatures verified with constant-time comparison.
- All UI pages are responsive (single stylesheet in `ui.php`, mobile breakpoint at
  640 px) and escape all user content.
- New app files must be added to `SitePackageExporter::FILES` (repository housekeeping).
