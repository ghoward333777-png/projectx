# SlowDating — Feature Technical Specification

One entry per feature: what it does, the exact rules it enforces, where it lives in the
code, and its API surface. Companion to [`DESIGN_SPEC.md`](DESIGN_SPEC.md) (architecture,
data model, business model) and [`openapi.yaml`](openapi.yaml) (full request/response
schemas). Reference implementation: dependency-free PHP 8.1+, JSON file storage, no
Composer, no database, no API keys.

---

## 1. Accounts & identity

**Purpose** — Three principals (member, partner, admin), each with platform-issued IDs
and strong-password auth.

**Rules**
- User IDs are always platform-generated: `U<yyyymmdd>-<5 chars from A-Z0-9 minus I/L/O/U/1/0-lookalikes>`;
  partners `p_<12 hex>`, admins `adm_<12 hex>`. Users never choose IDs.
- Email must validate (`FILTER_VALIDATE_EMAIL`) and be unique per principal type.
- Sessions are opaque 48-hex bearer tokens; only `sha256(token)` is stored, mapped to
  `{subject_id, kind, issued_at}`. A token authenticates exactly one principal kind —
  member routes never resolve for partner/admin tokens and vice versa.

**Implementation** — `SlowDatingEngine::signupMember/login/signupPartner/partnerLogin/createAdmin/adminLogin/authenticate/issueToken/newUserId`.
**API** — `POST /auth/signup`, `POST /auth/login`, `POST /partners/v1/signup|login`, `POST /admin/v1/bootstrap|login`.

## 2. Strong-password policy & auto-generation

**Purpose** — No weak password ever enters the system, for any principal.

**Rules**
- Policy: ≥ 12 chars, ≥ 1 uppercase, ≥ 1 lowercase, ≥ 1 digit, ≥ 1 symbol, not on the
  common-password blacklist. Violations return the specific problems.
- Auto-generation (opt-in, or default when no password given): 16–24 chars (default 20)
  guaranteed to contain all four classes, from an ambiguity-reduced alphabet, via
  `random_int`. Returned exactly once at creation (`auto_password`), never stored raw.
- Storage: `password_hash(PASSWORD_DEFAULT)`; verification via `password_verify`.

**Implementation** — `SlowDatingEngine::generateStrongPassword/passwordProblems`.

## 3. Member profiles

**Purpose** — The searchable identity: demographics, lifestyle, and preference facts.

**Fields** — `display_name`, `age` (int, **≥ 18 enforced**), `gender`, `zip_code`,
`interests[]`, `hobbies[]`, `outdoor_activities[]` (comma-string or array input,
lower-cased, de-duplicated), `dating_type` ∈ {long_term, short_term, casual, marriage,
slow_dating}, `faith`, `politics`, `income_range` ∈ {under_30k, 30k_60k, 60k_100k,
100k_150k, 150k_plus}, `automobile` ∈ {none, economy, sedan, luxury, sports, suv, truck,
ev}, `occupation_category`. Unknown enum values are rejected with 422.

**Implementation** — `SlowDatingEngine::profile/updateProfile/defaultProfile`.
**API** — `GET|PATCH /users/me/profile`.

## 4. YouTube profile videos

**Purpose** — Let members add video to profiles without accepting arbitrary markup or hosts.

**Rules**
- Accepted URL shapes only: `youtube.com/watch?v=`, `youtu.be/<key>`, `/embed/<key>`,
  `/shorts/<key>`; the key must match `[A-Za-z0-9_-]{5,20}`. Any other host → 422.
- The stored `embed_url` is always derived server-side from the parsed key — user input
  never reaches the page as markup. Max 5 videos per profile; duplicates rejected.

**Implementation** — `SlowDatingEngine::addProfileVideo/removeProfileVideo/youtubeVideoKey`.
**API** — `POST|GET /users/me/profile/videos`, `DELETE /users/me/profile/videos/{id}`.

## 5. Membership billing

**Purpose** — The $19/year hybrid-revenue anchor plus premium tiers.

**Rules** — Tiers: `member` $19, `vip` $79, `elite` $199 per year; subscribing sets
`membership_expires_at = now + 365 days` and logs a `membership_purchase` analytics
event. `free` is the default tier. VIP/Elite gates early chat unlock (§9).

**Implementation** — `SlowDatingEngine::subscribeMembership`, `MEMBERSHIP_PRICES`.
**API** — `POST /users/me/billing/subscribe`.

## 6. Slow chat — pairing & pacing

**Purpose** — One chat per member pair; message size and frequency limited early, widening
on a fixed schedule.

**Rules**
- `startChat` is idempotent per pair (canonical `pair_key = min|max` of the two IDs);
  starting a chat credits the recipient a `chat_request` popularity event. Self-chat rejected.
- Pacing by chat age (per sender, per chat, per UTC day):

| Chat age | Msgs/day | Max chars |
|---|---|---|
| Days 0–6 | 5 | 280 |
| 7–13 | 10 | 500 |
| 14–20 | 20 | 1,000 |
| 21+ | 40 | 2,000 |
| Unlocked | ∞ | ∞ |

- Over-limit sends are rejected with a plain-language 422 explaining the current stage.

**Implementation** — `SlowDatingEngine::startChat/sendMessage/chatStatus/pacingFor`, `PACING`.
**API** — `POST|GET /chats`, `POST|GET /chats/{id}/messages`, `GET /chats/{id}/status`.

## 7. Slow chat — the 30-day / 10-conversation unlock

**Purpose** — The product's defining rule: contact exchange is earned, not instant.

**Rules**
- A chat unlocks to real time when **both** hold: age ≥ 30 days **and** completed
  sessions ≥ 10. A *completed session* = a UTC calendar day on which **both**
  participants sent ≥ 1 message (a conversation, not a monologue).
- `chatStatus` reports `stage` (slow_chat | real_time), `age_days`,
  `completed_sessions`, both thresholds, and `contact_sharing_allowed`.

**Implementation** — `SlowDatingEngine::chatStatus/completedSessions`, `UNLOCK_DAYS=30`, `UNLOCK_SESSIONS=10`.

## 8. Contact-data erasure (pre-unlock filtering)

**Purpose** — Personal contact data cannot cross the chat before the unlock — erased, not
just blocked.

**Rules**
- Applied to every message while locked; matched spans are replaced with
  `[contact info removed]` **before storage** (the original text is never persisted or
  logged). The response reports `contact_data_removed` (count).
- Patterns: email addresses; phone-like runs (`\+?\d[\d\s().-]{6,}\d`); `http(s)://` and
  `www.` URLs; `@handles`; `instagram|snap(chat)|telegram|whatsapp|signal` + handle.
- After unlock, messages pass unfiltered — contact sharing is the earned feature.

**Implementation** — `SlowDatingEngine::filterContactData` (called from `sendMessage`).

## 9. Early unlock (premium)

**Purpose** — The "skip the wait" upsell, gated to paid tiers.

**Rules** — `POST /chats/{id}/unlock`: caller must be a participant **and** `vip` or
`elite`; sets `early_unlock=true` (chat behaves as unlocked), logs an `early_unlock`
analytics event. Non-VIP → 422.

**Implementation** — `SlowDatingEngine::purchaseEarlyUnlock`.

## 10. Red-flag safety detection

**Purpose** — Deterministic detection of predatory chat patterns, active in every stage.

**Rules** — Four pattern families: money requests (wire/gift cards/crypto/bank details),
urgency pressure ("last chance", "don't tell anyone"), off-platform pushes (text/call
me, WhatsApp/Telegram/Snapchat), coercion ("prove you love", "send a photo or"). A hit
tags the stored message `red_flags[]` and writes a `safety_events` record protecting the
**recipient** (`protected_user_id`, `actor_user_id`, `chat_id`, `flags`, timestamp). The
message still delivers (filtered per §8) so victims keep evidence and context.

**Implementation** — `RED_FLAG_PATTERNS`, `SlowDatingEngine::logSafetyEvent/safetyEventsFor`.
**API** — `GET /users/me/safety/events`.

## 11. Popularity rating

**Purpose** — A privacy-preserving 0–100 desirability signal from engagement *received*.

**Rules**
- Event weights: photo_received 5, compliment 4, chat_request 3, event_invite 3,
  message_received 2, like 2, profile_view 1, coupon_target 1. Events are written by the
  engine as side-effects (chat start, message receipt, compliment detection via phrase
  patterns, profile views, targeted-coupon delivery) or via the internal event API.
- Normalization: `score = min(100, round(raw / cohort_avg × 50))` — cohort average sits
  at 50; cohorts are **per gender** so one gender's traffic never distorts the other's.
- Also reported: percentile within cohort and trend (rising/stable/falling: last 7 days'
  weighted events vs the prior 7).
- Privacy: other members see only score/percentile/trend. The metric breakdown (raw
  counts per event type) is **owner-only** (403 otherwise). Viewing another profile's
  popularity records a `profile_view` for them.

**Implementation** — `POPULARITY_WEIGHTS`, `SlowDatingEngine::recordPopularityEvent/popularity/popularityBreakdown/popularityTrend/rawPopularity`.
**API** — `GET /users/{id|me}/popularity`, `GET /users/me/popularity/breakdown`, `POST /popularity/events`, `GET /users/search/popular` (min score defaults 60).

## 12. Member search

**Purpose** — Find members by every profile dimension plus popularity.

**Filters** — `zip_code` + `zip_radius_km`, `gender`, `age_min/max`, `interests`,
`hobbies`, `outdoor_activities` (each: all requested items must be present),
`shared_categories` (generic classifications derived from raw items — e.g. "escape
rooms" reads as Adventures and Games), `dating_type`, `faith`, `politics`,
`income_range`, `education`, `automobile`, `occupation_category`, `family_plans`,
`smoking`, `drinking`, `pets`, `min_popularity`, `max_popularity`, `limit` (default 50).
Results ordered by popularity desc, then user_id (deterministic); include distance when
a zip filter is given.

**Implementation** — `SlowDatingEngine::searchUsers/profileMatchesFilters`.
**API** — `GET /users/search`.

## 13. Zip-code proximity model

**Purpose** — Deterministic distance without a geo dataset; swappable for a real one.

**Rules** — Digits-only comparison; identical zips → 0 km; then by shared leading digits
(of 5): 4→2 km, 3→5 km… 0→400 km; missing zip → 999 km. Single choke-point method — a
production geo lookup replaces it without touching callers.

**Implementation** — `SlowDatingEngine::zipProximityKm`.

## 14. Compatibility matching

**Purpose** — Ranked matches from an 11-factor weighted score (weights sum to 1.0).

| Factor | Weight | Scoring (0.0–1.0) |
|---|---|---|
| distance | .20 | `1 − km/200`, floor 0 |
| interests | .15 | Jaccard overlap (empty side → neutral 0.5) |
| dating_type | .15 | exact 1.0 / unspecified 0.6 / mismatch 0.2 |
| hobbies | .10 | Jaccard |
| faith | .08 | exact / unspecified / mismatch |
| politics | .07 | exact / unspecified / mismatch |
| popularity_balance | .07 | `1 − |a−b|/100` |
| income | .05 | `1 − bracket_distance × 0.2`, floor 0.2 |
| occupation | .05 | exact / unspecified / mismatch |
| outdoor_activities | .05 | Jaccard |
| automobile | .03 | same 1.0, else neutral 0.7 |

`match_score = round(Σ factor×weight × 100)`. Responses carry the factor breakdown,
shared interests/hobbies, distance, and up to 2 recommended venues near the candidate.
`GET /matches/search` accepts the full §12 filter set; results ordered by score desc.

**Implementation** — `MATCH_WEIGHTS`, `SlowDatingEngine::matchesFor/compatibilityFactors/overlap/categoryAffinity/incomeAffinity`.

## 15. AI date concierge

**Purpose** — Read the chat both members are having on-platform (the consent boundary)
and suggest vetted venues that fit its topics. Deterministic and explainable.

**Rules** — Lower-cased chat text is scanned against a keyword→affinity map (jazz,
italian, pasta, wine, danc-, puzzle, escape, coffee, dinner, cruise, hik-, …), each
keyword mapping to atmosphere tags + venue categories; no hits falls back to `dinner`.
Active venues are scored per topic: tag hit = 2, category hit = 1; ranked by strength,
then proximity to the first participant's zip, then id. Top 3 returned, each with a
human-readable `reason` ("You both talked about jazz — Blue Note Lounge fits that mood").

**Implementation** — `CONCIERGE_TOPICS`, `SlowDatingEngine::conciergeSuggestions/venuesNear`.
**API** — `GET /chats/{id}/concierge`.

## 16. Partner accounts & plans

**Purpose** — Self-service onboarding for venues/vendors with tiered capability gates.

**Rules** — Signup: business name + unique email + password (§2 policy, auto-gen
offered) + plan ∈ {basic, pro, elite}. Gates: targeted coupons and contests require
pro/elite; basic keeps listings, random coupons, events, products. Plan changes take
effect immediately.

**Implementation** — `SlowDatingEngine::signupPartner/partner/changePartnerPlan`.
**API** — `GET /partners/v1/me`, `GET|POST /partners/v1/billing/plan[/change]`.

## 17. Venues

**Purpose** — The date-compatible inventory the concierge, coupons, events, and matching
draw from.

**Rules** — Fields: name (required), address, zip_code, category ∈ {restaurant, lounge,
cruise, tour, experience, bodyguard, vendor}, `atmosphere_tags[]` (quiet, romantic,
no_kids, jazz, dance_friendly, game_night, outdoor…), `safety_score` (default 70),
status active/inactive. Only active venues surface. Ownership enforced: a partner can
only manage their own venues (`requireVenue(venueId, partnerId)`).

**Implementation** — `SlowDatingEngine::createVenue/updateVenue/venuesForPartner/venuesNear`.
**API** — `GET|POST /partners/v1/venues`, `PATCH /partners/v1/venues/{id}`.

## 18. Coupons — random & targeted

**Purpose** — Partner offers delivered into member wallets; the platform's precision-
marketing engine.

**Rules**
- Common: positive `discount_amount`, `discount_type` ∈ {percent, fixed}, validity
  window (default 30 days), `max_recipients` cap; recipients selected deterministically
  (sorted user ids, sliced to cap); `estimated_reach` returned; `coupon_created`
  analytics event logged.
- **Random**: recipients = members within 40 km of the venue.
- **Targeted** (pro/elite only): segment by gender, age_min/max, zip_radius_km (default
  40), interests, relationship stage — e.g. "women 18–30 within 20 km". Each targeted
  delivery credits the recipient a `coupon_target` popularity event.
- **Wallet & redemption**: members see coupons issued to them and not yet redeemed;
  redemption checks recipient, validity window, and single-use (deterministic redemption
  id makes double-redeem impossible); logs `coupon_redemption` analytics.

**Implementation** — `SlowDatingEngine::createRandomCoupon/createTargetedCoupon/createCoupon/selectCouponRecipients/couponsForMember/redeemCoupon`.
**API** — `POST …/coupons/random|targeted`, `GET …/coupons`, `GET /users/me/coupons`, `POST /coupons/{id}/redeem`.

## 19. Events & ticketing

**Purpose** — Singles nights and experiences with capacity-controlled ticket sales.

**Rules** — Event: title (required), description, date_time (default now+7d), capacity
(≥1, default 50), tags[], ticket_price. Ticket purchase: capacity enforced across all
sold quantities (sold-out → 422); `total_amount = quantity × price`; logs
`ticket_purchase` analytics; **auto-enters every eligible contest** (§20). External
ticket sales enter through the webhook (§23) with `source: external`.

**Implementation** — `SlowDatingEngine::createEvent/eventsForVenue/buyTicket`.
**API** — `POST|GET …/events`, `POST /events/{id}/tickets`.

## 20. Contests

**Purpose** — Ticket-driven promotions: buy a ticket, you're in the draw.

**Rules** — Pro/elite only. Fields: prize (required), rules, optional `event_id` tie
(empty = any ticket at the venue), start/end/draw dates (defaults now / +30d / +31d).
Eligibility is strictly `ticket_buyers`; entries are created automatically at purchase
time (internal or webhook), one per member per contest (deterministic entry id), only
inside the entry window. Partner-facing stats are aggregated only
(`entries_count`, `winner_selected`) — never member identities.

**Implementation** — `SlowDatingEngine::createContest/contestsForVenue/contestEntries/enterEligibleContests`.
**API** — `POST|GET …/contests`, `GET /partners/v1/contests/{id}/entries`.

## 21. Marketplace (store & orders)

**Purpose** — Partner-listed products sold inside the site.

**Rules** — Product: name + positive price required, category (default gift), inventory
≥ 0, status active. Store lists active products (all venues or one). Orders: quantity
clamped ≥ 1, must not exceed inventory (else 422); inventory decremented atomically with
the order; `total_price = quantity × price`; logs `order_placed` analytics.

**Implementation** — `SlowDatingEngine::createProduct/products/placeOrder`.
**API** — `POST|GET …/products`, `GET /products`, `POST /orders`.

## 22. Admin console & leaderboard rewards

**Purpose** — Operations: rank members by real engagement and grant free benefits to the
top cohorts.

**Rules**
- **Admin lifecycle**: first admin via one-time bootstrap (rejected once any admin
  exists); afterwards only an existing admin creates admins.
- **Leaderboard**: all members ranked by **raw** weighted engagement received (normalized
  scores are per-gender and not cross-comparable), ties by normalized score then id.
- **Reward campaigns**: cohort must be exactly 10, 50, or 100; benefit type ∈
  {free_membership (tier applied immediately for 365 days), gift_certificate (positive
  amount), product (must exist), event_tickets (event must exist, qty ≥ 1, default 2),
  promo_trip (description required — e.g. all-expense trips to company promotions)}.
  Every grant writes a per-member reward record {campaign_id, rank, type, detail,
  granted_by, granted_at}; campaign logs a `reward_campaign` analytics event; members
  see their grants in the wallet.

**Implementation** — `SlowDatingEngine::createAdmin/adminLogin/topMembers/grantTopMemberRewards/rewardsFor`, `REWARD_COHORTS`, `REWARD_TYPES`.
**API** — `GET /admin/v1/leaderboard?count=N`, `POST /admin/v1/rewards/top`, `POST /admin/v1/admins`, `GET /users/me/rewards`.

## 23. Inbound webhooks

**Purpose** — External ticketing, reservation, and bodyguard systems report into the
platform.

**Rules** — All three endpoints require header `X-Webhook-Signature` matching env
`SLOWDATING_WEBHOOK_SECRET` via constant-time `hash_equals`; unsigned/mismatched → 401.
Unknown `user_external_id`s are recorded as null (never invent members).
- `POST /webhooks/tickets/purchased` → ticket record (`source: external`), contest
  auto-entry, `ticket_purchase` analytics.
- `POST /webhooks/bookings/created` → venue booking record + `booking_created` analytics.
- `POST /webhooks/bodyguard/booked` → chaperone booking record (surfaced to safety) +
  `bodyguard_booking` analytics.

**Implementation** — `SlowDatingEngine::ingestTicketWebhook/ingestBookingWebhook/ingestBodyguardWebhook`, `SlowDatingApi` webhook guard.

## 24. Partner analytics

**Purpose** — Per-venue performance rollup.

**Rules** — Returns coupons created, redemptions, events, tickets sold, ticket revenue
(2-dp), contest entries — computed live from the underlying records, no separate
counters to drift. Backed by the append-only `analytics_events` log (type, user, venue,
details, timestamp) written at every monetizable action.

**Implementation** — `SlowDatingEngine::venueAnalytics/logAnalytics`.
**API** — `GET /partners/v1/venues/{id}/analytics`.

## 25. Safety Center

**Purpose** — Public, reviewable safety education — women-first.

**Rules** — Static curated content (never generated at runtime): red flags,
first-date checklist, exit strategies; served publicly (`GET /safety/resources`), to
members (`/users/me/safety/resources`), and as the `safety-center.php` page, which also
explains the built-in protections (filtering, pacing, detection, vetted venues,
chaperones, popularity privacy).

**Implementation** — `SlowDatingEngine::safetyResources`.

## 26. Web application (SaaS UI)

**Purpose** — Desktop- and mobile-compatible pages over the same engine; no frameworks.

**Pages & behavior**
- `index.php` — member app: signup/login (auto-password offer), tabbed views (Matches,
  Search with every §12 filter, Chats with pacing badges + unlock progress + live
  filter notices + concierge cards, Profile with videos and owner-only popularity
  breakdown, Coupons & rewards, Store, Membership). Chat logs auto-scroll to newest.
- `partner-portal.php` — partner signup/login, plan management, venue creation, all §18–21
  actions, live analytics tiles.
- `admin.php` — bootstrap/login, reward-campaign form (§22), leaderboard, grants log.
- `safety-center.php` — §25 content.
- `site-tour.php` — public slideshow of every page: 11 real captures under
  `assets/tour/`, captions, arrows/dots/keyboard nav, 6-s autoplay with pause,
  `prefers-reduced-motion` starts paused.
- `smart-dating.php` — public education library: 9 relationship-science articles
  (structured PHP array → index cards + per-article view with prev/next; catalog at
  `?format=json`).
- Shared frame `ui.php`: one responsive stylesheet (16 px gutters, 640 px breakpoint),
  all user content HTML-escaped, session-held tokens.

## 27. HTTP API layer

**Purpose** — The whole REST contract as one testable router.

**Rules** — `SlowDatingApi::route(method, path, query, body, headers, now)` →
`[status, payload]`; used by `api.php` over HTTP (PATH_INFO or `?route=/…` fallback for
shared hosts) and called directly by the contract tests. Bearer parsing, role scoping,
webhook signature guard. Errors: `{error_code, message}` with 401 / 403 / 404 / 422;
`InvalidArgumentException` maps to 422, anything else to 500.

## 28. Storage

**Purpose** — Plain-file persistence consistent with the repository's no-database rule.

**Rules** — `SlowDatingStore`: one JSON file per collection under `dating/state/`
(gitignored), records keyed by id; collection names validated `[a-z_]+`; in-process
cache with write-through flush; `all/get/put/delete/count/where` API. Collections:
users, tokens, chats, partners, venues, coupons, redemptions, events, tickets,
contests, contest_entries, products, orders, popularity_events, safety_events, admins,
rewards, bookings, analytics_events.

## 29. Demo seeder

**Purpose** — One command puts the whole platform in a demonstrable state.

**Rules** — `php dating/bin/seed-demo.php` wipes `dating/state/` and seeds: six members
with full profiles and layered popularity, a day-12 slow chat containing a filtered
contact-sharing attempt, an unlocked 36-day chat with open contact exchange, three
partners (pro lounge / elite experience / basic restaurant) with targeted + random
coupons, a ticketed singles event, a contest with auto-entries, store products, an
admin, and two executed top-10 reward campaigns. Prints the three demo logins.

## 30. 2026 feature pack — trust, co-pilot, communities

**Purpose** — The capabilities that separate 2026's winning apps from swipe-only ones:
safety/trust signals, intent clarity, an AI co-pilot, anti-fatigue curation, personality
depth, and niche community identity. All deterministic, like the rest of the engine.

**Rules**
- **Verification & trust badges**: a member requests verification
  (`requestVerification`, states none → pending → verified); admins review a queue and
  approve/reject (`reviewVerification`, admin-gated). Verified profiles carry a
  `verified` flag in every card row (Browse, Search, Matches, Communities, daily drop).
- **Profile prompts**: up to 3 answers (1–200 chars) from an 8-prompt catalog
  (`PROMPTS`); stored with their question text; unknown prompts rejected.
- **Profile coach**: `profileCoach()` scores 0–100 from profile facts (25), interest
  lists (15), real+private pictures (20), prompts (15), video (10), saved preferences
  (10), verification (10) — and returns the concrete suggestions that would raise it.
- **Ice breakers**: `iceBreakers(chat, viewer)` builds up to 3 deterministic openers
  from the other member's prompt answers and the pair's shared interests (participant-only).
- **Conversation health**: `conversationHealth(chat)` scores reply balance (50%) and
  two-sided-day ratio (50%), minus 15 per red flag, clamped 5–100, labeled
  thriving / steady / needs care, with plain-language notes.
- **Daily drop**: `dailyDrop(user)` curates `DAILY_DROP_SIZE` (3) members from the
  member's Browse pool, ordered by `md5(date + user + candidate)` — same member, same
  day, same drop; a new set every day. Anti-swipe-fatigue by construction.
- **Niche communities**: fixed catalog (`COMMUNITIES`: creatives, tech founders,
  spiritual & mindful, single parents, LGBTQ+, fitness, travelers, entrepreneurs);
  join/leave; each community has a member grid ranked by popularity.
- **Intent clarity**: the member's `dating_type` shows as a badge on match and search
  cards alongside the trust badge.

**API** — `POST /users/me/verification`; `GET|POST /admin/v1/verifications[/{userId}]`;
`POST /users/me/prompts`; `GET /users/me/coach`; `GET /users/me/daily-drop`;
`GET /communities`, `GET /communities/{slug}`, `POST|DELETE /users/me/communities/{slug}`;
`GET /chats/{id}/icebreakers`, `GET /chats/{id}/health`.

## 31. Meet-up intent advertising (second ad + keys)

**Purpose** — Advertisers reach couples at the exact moment they start arranging a real
date, matched to what the date will be — without the platform ever knowing or revealing
the actual meeting place.

**Rules**
- **The second ad**: Pro/Elite partners create a meet-up ad per venue (headline,
  message, optional offer) and purchase **keys** from a fixed catalog (`AD_KEYS`:
  italian_restaurant, movies, coffee, jazz_lounge, wine_bar, dancing, escape_room,
  fine_dining, outdoors, dessert), each key defined by the date-talk phrases it matches.
  Unknown keys and non-Pro plans are rejected; each launch logs an `ad_key_purchase`.
- **Intent detection**: `meetupIntent(chat)` scans only the last 12 on-platform
  messages (the concierge's consent boundary) for meet-up phrases ("are you free",
  "saturday", "meet up", …) and, when found, maps the conversation to matching keys.
- **Flashing**: `meetupAdsForChat` fires only when intent AND keys are present; ads
  must belong to active venues within 40 km of either participant; Elite plans rank
  first, then proximity; **one ad per matched key, max two** — so "Italian, then a
  movie" surfaces both the restaurant and the theater. Each flash logs a
  `meetup_ad_impression`, counted in venue analytics.
- **Privacy**: the meeting place stays private — detection reads topics, never
  addresses; advertisers see only aggregate impression counts, never identities or
  chat content.

**API** — `POST /partners/v1/venues/{id}/ads/meetup`, `GET …/ads`, `GET /chats/{id}/ads`.

## 32. Perks & income for popular members

**Purpose** — Popular members are the product's best advertisement; the platform pays
them for the attention they attract and the energy they put in.

**Eligibility** — `earnEligibility`: top 25% of the member's gender cohort
(`EARN_TOP_PERCENTILE`) **or** popularity score ≥ 60 (`EARN_MIN_SCORE`). Enrollment
(`enrollEarnProgram` / `withdrawEarnProgram`) is per program; ineligible members are
rejected with the requirement spelled out.

**Programs** (`EARN_PROGRAMS`) — nine, six live and three opt-in for after launch:
- **profile_ads** — display ads run next to the profile; every `profile_view` credits
  $0.05 (`EARN_RATES.profile_ad_impression`) to enrolled members.
- **premium_gallery** — the *Premium Members Only gallery*: up to 12 photos
  (`GALLERY_MAX_PHOTOS`), separate from the three profile pictures, magic-byte
  validated like all uploads. Only paid-tier members can open another member's
  gallery (`viewGallery`); each visit pays the owner $0.25, once per viewer per day
  (deduped ledger key). Bytes served via `photo.php?gallery=<id>` to the owner or a
  premium viewer only.
- **chat_responder / chat_initiator** — stay logged in 4–8 hours keeping chats alive.
  `claimActivityEarnings` counts *active hours* (UTC hours with ≥1 message sent) per
  day, split by whether the member started the chat (`participants[0]`); ≥4 hours pays
  $1.50/hour, capped at 8, idempotent per day. Deterministic from chat records.
- **date_scheduler** — scheduling dates on the web: buying a ticket to an advertised
  partner event pays 10% of the ticket total back (`buyTicket` hook, deduped per ticket).
- **testimonials** — partner-scripted testimonial videos (§ below).
- **video_dates / multiplayer_games / future_programs** — consent opt-ins now;
  details announced after launch (videoed real dates, ad-revenue-sharing multi-player
  games, programs TBA).

**Ledger** — every payout is an `earnings` record (program, amount, note, timestamp);
`earningsFor` totals it; dedupe keys make activity days, gallery visits, ticket shares,
and testimonial payouts idempotent.

**Portal** — `earn.php` ("Perks & income" in the nav): standing (score, percentile,
total earned), all nine program cards with enroll/withdraw, chat-hour claiming, gallery
management, testimonial offers + submission tracking, and the ledger. API:
`GET /users/me/earn`, `POST /users/me/earn/enroll|withdraw`,
`GET /users/me/earn/earnings`, `POST /users/me/earn/activity/claim`,
`GET|POST /users/me/gallery`, `DELETE /users/me/gallery/{id}`, `GET /users/{id}/gallery`,
`GET /earn/testimonials`, `POST /earn/testimonials/{scriptId}/submit`,
`GET /users/me/testimonials`.

**Testimonial workflow** — a partner publishes a scripted offer with a payout
(`createTestimonialScript`; positive payout and non-empty script required). Enrolled
members submit a recorded video URL (`submitTestimonial`). The partner reviews
(`reviewTestimonial`): **accept** (pays the member the offer's payout, once),
**reject**, **edit** (replaces the script — the member re-records), or **extend**
(appends to the script — the member records the addition); every review is kept in the
submission's history. Partner API: `POST|GET /partners/v1/venues/{id}/testimonials`,
`POST /partners/v1/testimonials/{id}/review`.

## 33. Photo reveal timeframe & the "Peek early" perk

**Purpose** — First impressions run on common interests and conversation, not
appearance.

**Rules**
- Admin sets `photo_reveal_days` (0–30, `setPhotoRevealDays`, default 0): real
  pictures stay behind the generated artwork until a pair's chat is that many days
  old — day 0 reveals at the first chat, day 1 after one day, and so on.
- `canSeeRealPhotos(viewer, owner)`: owners always see their own pictures; **premium
  (paid-tier) members hold the "Peek early" perk and see every member's real pictures
  immediately**; everyone else needs a chat with that member aged past the reveal day
  — no chat, no real pictures anywhere.
- Enforced in `avatar.php` for both contexts: the global uploads mode (Browse,
  Matches, Search cards) and the per-chat picture choice. The generated artwork is
  always the fallback; the private picture still additionally requires the owner's
  per-chat choice.
- The perk is described plainly on the signup page and in the membership tab.

**API** — `GET /admin/v1/settings` returns `avatar_mode` + `photo_reveal_days`;
`PATCH /admin/v1/settings` accepts either or both.

## 34. Engineering invariants & tests

- **Determinism**: every time-dependent rule takes an explicit `$now`; identical inputs
  produce identical pacing, unlock, popularity, matching, targeting, and concierge
  output. Randomness confined to credentials (passwords, tokens, id suffixes).
- **Erased means erased**: pre-unlock contact data is never stored or logged.
- **Privacy**: no raw engagement counts beyond the owner; contest entries aggregated.
- **Tests**: `php tests/dating-engine-contract.php` (≈50 assertions across every engine
  feature) and `php tests/dating-api-contract.php` (full HTTP contract incl. auth
  scoping, plan gates, webhooks). Both run in the repo suite; all new app files are
  registered in `SitePackageExporter::FILES` so the hosting-zip self-test ships them.
