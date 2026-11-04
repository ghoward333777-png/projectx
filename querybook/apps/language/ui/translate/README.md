# QueryBook Translate

An offline-first universal translator for phones and tablets, built to the
*QueryBook Translate — Product & Engineering Specification*. It has a
deterministic, provenance-tracked core that **never makes up a translation**.
Every result shows a coverage meter and per-word sources. Unknown words are
passed through and flagged. Identical input always gives identical output.

- **Lightweight.** No dependencies or build step. The app shell is about 210 KB and
  each language pack is 1–14 KB, so a whole language (core + travel +
  medical) is under 30 KB. The Android APK is 1.5 MB.
- **Cross-platform.** One codebase runs as an installable web app (Android, iPhone,
  iPad, desktop) and inside native Android and iOS/iPadOS shells that add the
  device's own on-device speech engines.
- **Expandable.** 139 languages and 202 dialects are in the registry. A language
  gets a dictionary by adding one reviewable TSV file. Domain packs (travel, medical,
  …) add vocabulary and sense priority. Packs can also be imported on the device or
  published to a cloud QueryBook store, with no app update needed.

## Run it

```bash
php -S 127.0.0.1:8083 -t translate      # or any static server
open http://127.0.0.1:8083/
```

Install on a device: on Android, Chrome ▸ *Install app*. On iPhone or iPad, Safari ▸ Share ▸ *Add to
Home Screen*. After the first launch it runs with the radios off.

## Phone and tablet apps (internal admin)

`translate/admin/` is a password-protected admin page. Serve the repository root
(`php -S 127.0.0.1:8082`) and open `/translate/admin/`. It offers:

| Download | What it is |
| --- | --- |
| **Android APK** | `dist/QueryBookTranslate-android-debug.apk`, debug-signed for internal sideloading. Rebuild with `tools/build-android.sh`; CI also uploads one. |
| **Android project** | Android Studio / Gradle project (Java, WebView + `SpeechRecognizer` + `TextToSpeech`) with the web app in `assets/www`. |
| **iPhone & iPad project** | Universal Xcode project (SwiftUI + `WKWebView`, Apple on-device `SFSpeechRecognizer` + `AVSpeechSynthesizer`). Build and sign on a Mac. |
| **Web edition** | Static bundle for any HTTPS host. |

Each download can be **pre-connected to a cloud QueryBook store**. The admin
enters the store URL (and key, if the store requires one), and it is baked into
the app's `config.json`. The connection stays optional, and users can change it in
Settings.

The admin page stays locked until a password is set:
`php translate/admin/set-password.php` (or set `QBT_ADMIN_PASSWORD_HASH`).

### Cloud QueryBook store

`translate/store/` serves the pack catalog to connected apps:

```
GET <store>/catalog.json                 bundled + admin-published packs
GET <store>/packs/<lang>/<domain>.json   one pack (the device verifies its sha256)
GET <store>/health
```

`<store>` is `https://host/translate/store/index.php/`. On Apache the bundled
`.htaccess` also allows `https://host/translate/store/`. Set `QBT_STORE_KEY` to require
`Authorization: Bearer <key>`. The admin publishes new or updated packs from the
admin page. A published pack overrides a bundled one with the same id. Connected apps see
it on their next catalog refresh, download it once and keep it offline.

## Architecture (spec §5–§6)

```
src/core/      deterministic engine (no DOM; unit-tested in Node)
  hygiene.js     NFC, invisible chars, exotic spaces, width folding (ZWJ/ZWNJ kept)
  scripts.js     Unicode script detection, RTL, spaced/unspaced, cased
  tokenize.js    word / number / punctuation tokens, script-boundary splits
  lexicon.js     concept-pivot dictionary built from base + domain packs
  mt.js          longest-match phrases, dictionary segmentation for CJK/Thai,
                 inflection / elision / compound / particle fallbacks,
                 coverage %, per-word provenance, script-aware assembly
  lid.js         dictionary-scored language + dialect ID with confidence;
                 asks the user to confirm below 40 %
  translit.js    Cyrillic, Greek, Arabic-script, Hebrew/Yiddish, 9 Brahmic scripts,
                 Hangul, Kana, Georgian, Armenian, Ethiopic; dictionary Pinyin/kana;
                 honest refusal elsewhere (packs may add a character map)
  g2p.js         IPA with syllables: Spanish (dialect-aware, stress rules),
                 Italian, Japanese kana, Korean, Hindi; stress only where decidable
  qc.js          permanent QC battery (covenant, determinism, round trips, …)
  engine.js      pipeline + stage timings
src/platform/  storage (IndexedDB), pack manager (download/verify/load/unload,
               store source), speech roles (ASR/TTS ladders), cloud router,
               native bridge
src/app.js     UI: Translate · Converse · Phrasebook · Languages · Monitor
native/        Android and iOS/iPadOS shells
admin/, store/ internal admin downloads and the cloud pack store (PHP, no deps)
```

**The trust layer.** Every result shows:
- a coverage meter;
- wavy underlines on untranslated words, dotted for kept names;
- a tap-to-see-source provenance panel (pack, version, concept, dialect, alternatives, review status);
- a determinism fingerprint;
- an offline / cloud badge.

**Speech is honest.** Recognized speech is shown as editable, untrusted text, and
low-confidence turns ask for confirmation. The TTS ladder picks an on-device voice
for the exact dialect, then the language. Otherwise it **refuses**: it never plays
a substitute voice, and the written translation and IPA stay available.

**The cloud is never on the critical path.** The on-device result always renders
first. The router asks the cloud only when the device is online, the user has opted
in, a gateway is configured, and coverage is low. Any cloud answer without coverage
and provenance is rejected.

## Add a language or dialect

1. Add a row to `data/languages.json` (code, names, script, tier, dialects).
2. Write `packs/src/<code>.tsv`. Each line is `concept<TAB>forms`, using the concepts
   listed in `packs/src/concepts.tsv`. Cell syntax: `form ; alternative | xx-YY: dialect form`,
   readings in `{braces}`, `∅` for "no separate word". Optional `@rules {…}`
   (`suffixes`, `elision`, `split`, `particles`, `invertedQuestion`, `translit`)
   and `@norm colloquial<TAB>standard[<TAB>dialect]` lines.
3. `node tools/build-packs.mjs` writes `packs/<code>/<domain>.json` and the catalog.

Shipped dictionaries: 12 Tier-1 languages × 3 domains (212 concepts, with dialect
variants for en, es, fr, de, pt, zh, ar). They are self-authored seed lexicons and
are marked *pending native-speaker review* in their provenance.

## Test

```bash
node --test translate/tests/*.test.mjs        # engine contract (24 tests)
node translate/tools/build-packs.mjs --check  # packs match sources
php tests/translate-admin-contract.php        # admin downloads + store
```

## Honest limits

- The output is a dictionary gloss. Whole phrases are natural, but multi-entry
  sentences follow source word order. The app says so whenever this happens.
- Inflection is handled by suffix rules plus listed forms. Words outside the
  dictionary are flagged rather than guessed.
- On the web build, speech uses the browser's engines. Recognition may need a
  network unless the device offers on-device recognition (check it in the Monitor).
  The native shells use the device's on-device recognizers where available.
- iPhone/iPad binaries must be signed with an Apple developer account. The
  project builds unsigned for the simulator in CI.
- The learned Language Expression Layer described in the Bible is roadmap. This
  app runs entirely on the deterministic path.
