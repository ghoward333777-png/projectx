# Book Intelligence Studio — engine invariants

Dependency-free PHP 8.1+ app (no Composer, no database, no API keys). Run locally with
`php -S 127.0.0.1:8082` and run every test in `tests/` (plain `php tests/<name>.php`)
before shipping. A JS mirror of the whole engine lives outside the repo for the test
dashboard; any change to outline or prose generation must be ported there and verified
byte-for-byte (compare `word/document.xml` md5 across engines) before publishing.

## Manuscript composition rules (do not regress)

These rules fixed the "bad manuscript" defect where drafts printed the editorial plan
as prose. Keep them intact in `BookIntelligenceEngine::composeExpandedChapterDraft()`:

- **Never emit meta-language.** No "Editorial development plan", no talk of outlines,
  purposes, drafting, chapters explaining themselves, or readers being taught how the
  book is built. The prose discusses the subject; it never discusses writing about it.
- **Strip instruction verbs from outline clauses** before using them in prose or
  headings (`$subject()` in the composer). Outline details are imperatives addressed
  to the writer; the manuscript must convert them to subjects.
- **Sections come from the chapter's own detail clauses** — heading per clause
  (≤52 chars, word-boundary cut, trailing stopwords trimmed), five paragraphs per
  section from the rotating discussion templates. No generic scaffold headings.
- **Close every chapter with a `The takeaway` section.**
  `IllustrationStudio::takeawayQuote()` and the Quality Lab takeaway metric read it.
- **Genre-aware outlines** in `suggestTableOfContents()`: social/cultural topics get
  the narrated-history arc (current state → past contrast → origins → evidence →
  solutions; concrete titles, never "systems"/"frameworks"); practical topics get the
  how-to arc; curated outlines exist for teen jobs and gender-relations topics.
  `reviewOutline()` (the Nonfiction Outline Editor) scores outlines against 12 rules —
  keep new outlines passing 100.
- **Word contents page**: plain text + dot-leader tab + page number from the page
  plan. No `<w:hyperlink>` anywhere in the export; keep the chapter bookmarks.
- **User-supplied outlines** via `AmazonBookWriter::parseOutline()` (one chapter per
  line, optional `| purpose | detail`) must keep flowing into `writeBook()` untouched.

## Manuscript development (first run ends in prose)

The engine draft is pass 1 — development directions, never the finished book.
`ManuscriptDeveloper` + `bin/develop-manuscript.php` execute passes 2 (AI
writer per chapter) and 3 (AI editor per chapter) and assemble the developed
chapters back through the exporters; `writeBook()` accepts finished texts via
`developed_chapters`. Keep the writer/editor prompts carrying the hard rules
(real prose only, follow the draft directions, no fabricated precision, "The
takeaway" closer, exact format contract). Default Anthropic model:
`claude-opus-5`. `BookProjectStore` records every generation's TOC + manuscript
under `projects/` — keep the auto-save in `amazon-book-writer.php` and the CLI.

## Prose quality controls

- **Hygiene**: `ManuscriptHygiene::clean()` runs on every developed chapter and
  `cleanLine()` on every pasted outline row — NFC normalization (skipped
  gracefully without ext-intl), invisible-character stripping, exotic spaces to
  ordinary spaces, LF line endings, collapsed runs, one blank line between
  paragraphs. Deterministic; keep it that way.
- **Rhythm**: the style contract carries a RHYTHM AND VARIETY section (sentence
  and paragraph variation, banned filler transitions, no repeated openings) and
  each chapter gets a rotating cadence directive so neighbours don't share one
  voice.
- **Revision**: the editor prompt does structural work (reorder weak argument
  order, compress circling passages, spend the words on the thinnest claim) and
  `ManuscriptDeveloper::revisionReport()` flags chapters wanting a human pass —
  deterministic, local, no API cost — surfaced in the writer results page.

## Housekeeping

- New app files must be added to `SitePackageExporter::FILES` or the hosting zip
  self-test fails.
- Deterministic output is a feature: same inputs must produce the same book.
- Voice cloning stays behind the explicit consent gate (`voice_consent` / `--consent`).

## MediaMarketplace Studio (`mediamarketplace/`)

A separate product in this repo: a media marketplace **server in Rust**
(`crates/mms-core`, `crates/mms-server`; Axum + SQLite via sqlx) that ships **inside a
WordPress plugin and a Joomla package** (`packages/`). The PHP runtime
(`packages/shared/MmsRuntime.php`) starts the binary on localhost and proxies
`https://site/mms/...` to it. One install, one server. No WooCommerce or VirtueMart anywhere.

- Run `cargo test` inside `mediamarketplace/` and `php tests/mms-packages-contract.php`
  from the repo root before shipping (build the release binary first so the contract test
  exercises the real start/proxy/sign-in path). `./build/package.sh` makes the zips.
- The SSO token format (`base64url(json).base64url(hmac)` over the raw JSON, canonical
  claim order `sub, email, name, host, [role], exp`) is shared by `mms-core::signer` and
  `MmsRuntime::signToken`; the fixture in `signer.rs` and the contract test must stay identical.
- `public_url` decides the mount path (`https://site/mms` → `/mms`); every link, redirect
  and cookie must go through `AppState::url` / the `base` template global.
- Settings are declared once in `mms-core::settings::DEFINITIONS`; secrets are encrypted
  at rest via `mms-core::secrets`. Schema changes go in new `crates/mms-core/migrations/*.sql`
  files, never by editing an applied migration.
- Embeds are only served to registered bridge sites and carry a `frame-ancestors` policy
  for that site's origin. Never add a public embed route without the site check.
- Widgets: `mms-core::render` is the one renderer (builder preview, embed, gallery,
  export all go through it) and must stay deterministic; custom CSS always passes
  `scope_css`. Widget templates (35) and site templates (12) are code in
  `mms-core::templates`; keep the counts, the HTTP test asserts them. New templates
  in `crates/mms-server/templates/` must be registered in `templates.rs`, new static
  files in `routes/embed.rs::static_file`, new settings in `settings::DEFINITIONS`.
- CMS placement has three equal forms and the contract test checks them: WordPress
  blocks (`blocks/*/block.json`, no build step) and shortcodes; Joomla menu item
  types (`com_mediamarketplace/site`), `{mms_*}` tags and `mod_mms_embed`. All render
  the same `data-mms-embed` markup from `MmsRuntime::embed`.
- Commerce: `mms-core::commerce::totals` is the one money calculation (discount, then
  tax on the discounted amount, half-up rounding); `Commerce::mark_paid` is idempotent
  and is the only place that grants for an order; `routes::shop::complete_paid` wraps
  it (subscription record, audit, webhooks) and is what the return URL and the
  webhook both call. Gateways implement `mms-core::gateways::Gateway`; the test gateway
  stays behind `payments.test_mode`; card data never touches the server.
- Private pages: `Pages::gate` is the single access decision; every signup template
  posts to the same endpoint and `Pages::sign` enforces the template's required
  confirmations server-side. Keys are stored hashed. A changed agreement bumps the
  version and supersedes signatures. Site passes never bypass invite keys.
- Receipts and agreements use the native writer `mms-core::pdf`; keep its output
  byte-stable for the same input.
- Deliverable documents are Word (`docs/*.docx`), never Markdown. Notes inside
  `mediamarketplace/` are `.txt`.
