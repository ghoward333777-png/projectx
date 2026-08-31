# Book Intelligence Studio — PHP

This is the standalone, dependency-free PHP implementation of Book Intelligence Studio.
It includes topic prospecting, competitive scanning, blueprint and table-of-contents generation,
media planning, probability modeling, deterministic manuscript drafting, editable chapter blocks,
JSON endpoints, and an **Amazon Book Writer** that packages the manuscript for Amazon KDP.

## Requirements

- PHP 8.1 or newer
- No Composer packages or API keys are required

## Run locally

From this directory, start PHP's built-in server:

```bash
php -S 127.0.0.1:8082 -t .
```

Then open:

- `http://127.0.0.1:8082/index.php` — strategy workspace
- `http://127.0.0.1:8082/generate-book.php` — editable TOC and manuscript generator
- `http://127.0.0.1:8082/amazon-book-writer.php` — Amazon KDP publishing package builder
- `http://127.0.0.1:8082/index.php?format=json` — generated strategy kit JSON
- `http://127.0.0.1:8082/index.php?format=json&part=toc` — table of contents JSON
- `http://127.0.0.1:8082/index.php?format=json&part=jobs` — 120-job catalog JSON
- `http://127.0.0.1:8082/index.php?format=json&part=book&style=journalistic&length=1000` — book draft JSON
- `http://127.0.0.1:8082/amazon-book-writer.php?topic=Leadership&format=json` — KDP package JSON

The application uses PHP session state for the last topic and deterministic heuristics,
so it runs without third-party credentials.

## Amazon Book Writer

`amazon-book-writer.php` runs the full pipeline (strategy kit → manuscript draft → KDP
package) and produces everything the KDP setup screens ask for:

- **Listing metadata** — title and subtitle within the 200-character limit, a book
  description within the 4,000-character limit, exactly seven backend search keywords
  (each ≤ 50 characters), and up to three browse category suggestions.
- **Print plan** — 6 x 9 in trim, black & white interior, and a KDP page estimate that
  respects the 24–828 page paperback limits.
- **Pricing & royalty estimates** — paperback printing cost, minimum and suggested list
  prices, and per-copy royalty using the published `(60% × list price) − printing cost`
  model; Kindle pricing with automatic 70%/35% plan selection and delivery-fee estimate.
- **Publishing checklist** — the ordered KDP flow from manuscript review to proof copy.
- **Exports** — a KDP-ready single-file HTML manuscript (title page, copyright page,
  linked table of contents, chapters; opens in Kindle Create or Word) and a metadata
  JSON file that mirrors the KDP setup screens.

All prices and royalties are directional planning estimates from published KDP rate
cards — confirm live numbers inside KDP before publishing.

## Run the contract tests

```bash
php tests/rich-chapter-contract.php
php tests/amazon-book-writer-contract.php
```

## Included files

- `BookIntelligenceEngine.php` — dependency-free application engine
- `AmazonBookWriter.php` — Amazon KDP packaging: metadata, pricing, checklist, exports
- `index.php` — strategy analysis and JSON endpoint
- `generate-book.php` — editable TOC, writing-style, page-style, and manuscript interface
- `amazon-book-writer.php` — Amazon KDP publishing package interface and exports
- `data/teen-jobs.json` — canonical teen-job catalog
- `tests/rich-chapter-contract.php` — PHP output contract checks
- `tests/amazon-book-writer-contract.php` — Amazon Book Writer contract checks
