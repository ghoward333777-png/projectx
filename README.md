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
- `http://127.0.0.1:8082/user-guide.php` — friendly user guide
- `http://127.0.0.1:8082/download-app.php` — download the whole app as a hosting-ready .zip
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
- **Exports** — a real Word manuscript (.docx: 6 x 9 trim, Times New Roman 12pt at
  1.5 spacing, title and copyright pages, Heading 1 chapters so Word's dynamic TOC
  and navigation pane work), a KDP-ready single-file HTML manuscript, and a metadata
  JSON file that mirrors the KDP setup screens.

All prices and royalties are directional planning estimates from published KDP rate
cards — confirm live numbers inside KDP before publishing.

## How chapters are composed (the manuscript-quality fix)

Early drafts had a serious defect: the chapter composer printed its *editorial plan* as
if it were the manuscript. Chapters opened with "Editorial development plan: …" and
filled their sections with instructions about how to write the chapter ("develop the
instruction in the outline", "the detail in this outline is a design constraint").
The plan was passed off as the book. That has been fixed, and the fix is a set of
composition rules the engine now enforces — they greatly improved manuscript quality
and must be preserved in any future change to `composeExpandedChapterDraft()`:

1. **The prose follows the plan; it never recites it.** No chapter may contain
   meta-language about outlines, purposes, drafting, or "this chapter will…". The
   contract tests fail if "Editorial development plan" ever reappears.
2. **The outline's instruction verbs are stripped.** Outline details speak to the
   writer in imperatives ("Follow the war as…", "Show who is living with…"). The
   composer removes the leading verb so the text discusses the subject itself
   ("the Second World War as men shipped overseas…").
3. **Section headings come from the chapter's own material** — each detail clause
   becomes a section developed across five discussion paragraphs (the phenomenon
   stated concretely, how it arrived, a human face on it, the contrast with the era
   before, the evidence, the costs, what follows). No generic scaffold headings.
4. **Every chapter closes with "The takeaway"** — one concrete closing thought that
   the pull-quote figure and the Quality Lab takeaway metric both read.
5. **Outlines are genre-aware.** Social and cultural topics get a narrated-history
   table of contents built on the social-science method — document the current state,
   contrast the past, deconstruct the origins, support with evidence, propose
   solutions — with chapters named for eras, events, and actors (never "systems" or
   "frameworks"). Practical topics keep a how-to arc. Authors can also paste their
   own table of contents, and the Nonfiction Outline Editor agent scores every
   outline against 12 machine-checkable editorial rules.
6. **The Word contents page is standard print style** — plain text rows with dot
   leaders and page numbers from the book's page plan, no hyperlinks (invisible
   chapter bookmarks keep Word's navigation pane working).

## Editions: Kindle, paperback, hardcover, audiobook

The KDP package now plans all four editions of the same title:

- **Kindle** — the existing eBook plan (70%/35% royalty selection, delivery fee).
- **Paperback** — 6 x 9 B&W, 24–828 pages, `(60% × list) − printing cost`.
- **Hardcover** — case laminate, 75–550 pages, `$6.80` flat up to 108 pages then
  `$5.65 + $0.012/page`, 60% royalty; optional `hardcover_price` override.
- **Audiobook** — runtime estimate (~9,300 words per finished hour), Audible-style
  retail band, synthesis cost estimate, and the ACX delivery specs.

## Figures & illustrations

`IllustrationStudio.php` gives every chapter a visual layer: it finds the
important topics inside the drafted text and generates media after each one —
step-flow **diagrams**, attention **charts**, momentum **graphs**, data
**tables** (job cards or topic overviews), seeded **illustrations**, and
**AI-image** prompts. Diagrams, charts, graphs, tables, and illustrations
render instantly as SVG/HTML with no keys; the figure palette is validated
for contrast and color-vision separation on the book's paper surface.

Users can add more illustrations to any specific chapter or section from the
“Add an illustration” panel on the writer page; added items are planned,
rendered, and exported with the rest.

AI images follow the audiobook pattern: download the image manifest, then run

```bash
php bin/generate-images.php --manifest my-book-images-manifest.json --out images/
```

with your own key — Google Imagen (`GOOGLE_AI_API_KEY`), OpenAI
(`OPENAI_API_KEY`), or Stability (`STABILITY_API_KEY`). Generation is
resumable. Figures are embedded in the HTML manuscript export and appear as
captioned placeholders in the Word export.

## Native EPUB and QR-linked print media

- **EPUB builder** (`EpubExporter.php`): a native EPUB 3 package built with
  ZipArchive — stored `mimetype`, OCF container, EPUB 3 package document with
  an EPUB 2 NCX fallback, XHTML navigation, styled per-chapter XHTML with the
  Illustration Studio figures embedded inline. Deterministic identifiers.
  Download from the writer page: **Download eBook (.epub)**.
- **QR-linked print media** (`PrintMediaCompanion.php` + `QrCode.php`): every
  chapter of the print edition gets a QR code linking to a companion web page
  carrying that chapter's media. The QR codes come from the app's own
  pure-PHP encoder (byte mode, ECC M, versions 1–10, full Reed–Solomon —
  verified module-for-module against a reference encoder and decoded with
  OpenCV). Set your companion web address on the writer page, then download
  the **companion page (.html)** to upload to your site and the printable
  **QR sheet (.html)**; the HTML manuscript export embeds each chapter's QR
  automatically.

## Book Development Lab

`book-lab.php` is the quality-certification layer, powered by `QualityLab.php`:

- **Quality Scoring Engine** — 30 metrics in three groups (editorial, media,
  format), each with a note explaining the number; group scores earn
  Bronze/Silver/Gold/Platinum badges, and the weighted **Universal Nonfiction
  Rating** (45% editorial + 30% media + 25% format) certifies the whole book.
- **Document Complexity Analyzer** — pages, words, sections, TOC depth,
  figures, audio segments, case-study moments, exercises, and density.
- **KDP Compatibility Checker** — 11 explicit pass/warn checks: trim size,
  page limits for both print formats, margins, image quality, TOC, every
  metadata limit, eBook structure, and ACX audiobook specs.
- **Metadata Optimization Report** — how fully the listing uses Amazon's
  limits, plus keyword opportunities to test later.
- **QueryBook Enhancement Plan** — three quiz questions, a key takeaway, and
  a learning-path step per chapter (Read → Quiz → Apply).
- **Best-Seller Production Kit** — everything above plus the blueprint,
  chapter outline, media map, competitive gap, and best-seller probability,
  downloadable as a printable HTML report or JSON.

All scores are deterministic diagnostics computed from the draft — honest
revision guidance, not sales guarantees.

## Audiobook production

`AudiobookProducer.php` turns the manuscript into a narration package: opening and
closing credits, a per-chapter narration script, sentence-aware chunks sized to each
provider's request limit, and a synthesis manifest with ready-to-send payloads.

Three voice providers are supported:

1. **Google Cloud Text-to-Speech** — uses your Google account's API key
   (`GOOGLE_TTS_API_KEY`); Neural2/WaveNet voices, 5,000-byte request cap respected.
2. **ElevenLabs** — uses `ELEVENLABS_API_KEY`; stock voices by `voice_id`, or clone a
   voice once from sample recordings and then synthesize with the new `voice_id`.
3. **Internal voice clone** — a local engine (XTTS-style) driven by a command
   template, synthesizing from a sampled recording on your own hardware.

**Voice-cloning consent is a hard gate:** any mode that clones from a sampled human
recording refuses to produce jobs until the recorded speaker's explicit consent is
confirmed (the `voice_consent` option on the page, `--consent` on the CLI).

Synthesize from a manifest downloaded on the Amazon Book Writer page:

```bash
# Google (uses GOOGLE_TTS_API_KEY, or pass --key)
php bin/synthesize-audiobook.php --manifest my-book-audiobook-manifest.json --out audio/

# ElevenLabs one-time voice clone, then synthesis
php bin/synthesize-audiobook.php --clone-name "My Voice" --clone-sample narrator.wav --consent --key KEY
php bin/synthesize-audiobook.php --manifest manifest.json --out audio/ --key KEY

# Internal cloning engine (runs your command per chunk)
php bin/synthesize-audiobook.php --manifest manifest.json --out audio/ --consent \
  --engine-cmd 'tts --text {text} --speaker_wav {sample} --language_idx {language} --out_path {out}'
```

Synthesis is resumable (existing chunk files are skipped). Afterwards, join each
section's chunks (ffmpeg concat) and master to ACX specs: 192 kbps CBR MP3,
RMS −23…−18 dB, peaks ≤ −3 dB, 0.5–1 s of room tone at head and tail.

## Run the contract tests

```bash
php tests/rich-chapter-contract.php
php tests/amazon-book-writer-contract.php
php tests/audiobook-contract.php
php tests/site-package-contract.php
php tests/illustration-contract.php
php tests/quality-lab-contract.php
php tests/epub-contract.php
php tests/print-media-contract.php
```

## Install on a hosting site

Click **Download the app for your website (.zip)** on the front page or user guide
(or fetch `download-app.php`). The zip contains the entire app plus `INSTALL.txt`:
upload to any PHP 8.1+ host (public_html), extract, done — no database, no Composer,
no API keys.

## Included files

- `BookIntelligenceEngine.php` — dependency-free application engine
- `AmazonBookWriter.php` — Amazon KDP packaging: metadata, pricing, editions, checklist, exports
- `AudiobookProducer.php` — narration script, chunking, provider payloads, consent gate
- `IllustrationStudio.php` — per-topic diagrams, charts, graphs, tables, illustrations, AI-image prompts
- `QualityLab.php` + `book-lab.php` — 30-metric scoring, complexity, KDP compliance, production kit
- `bin/generate-images.php` — CLI image synthesis via Google Imagen, OpenAI, or Stability
- `WordManuscriptExporter.php` — dependency-free .docx (OOXML) manuscript export
- `bin/synthesize-audiobook.php` — CLI synthesis via Google TTS, ElevenLabs, or a local cloning engine
- `SitePackageExporter.php` + `download-app.php` — one-click hosting package (.zip with INSTALL.txt)
- `user-guide.php` — friendly plain-language user guide
- `index.php` — strategy analysis and JSON endpoint
- `generate-book.php` — editable TOC, writing-style, page-style, and manuscript interface
- `amazon-book-writer.php` — Amazon KDP publishing package interface and exports
- `data/teen-jobs.json` — canonical teen-job catalog
- `tests/rich-chapter-contract.php` — PHP output contract checks
- `tests/amazon-book-writer-contract.php` — Amazon Book Writer contract checks
- `tests/audiobook-contract.php` — editions and audiobook production contract checks
