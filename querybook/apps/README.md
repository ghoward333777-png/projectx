# QueryBook — three dedicated applications

The full-featured QueryBook prototype grew too large: its interface kept changing and its store was
damaged. These three applications replace it with one small, separate program for each kind of
knowledge. Each has its own folder, its own database, its own port and its own launcher. None of
them depends on another, and none of them changes the old QueryBook store.

| Application | Folder | Opens at | What it does |
|---|---|---|---|
| **Language Builder** | `language/` | http://127.0.0.1:8101/ | Builds English first, then Spanish, French, German, Italian, Portuguese, Dutch, Swedish, Danish, Norwegian, Finnish, Polish, Czech, Greek, Romanian, Hungarian and Catalan — automatically, without any AI model; verifiable from scratch; word look-up |
| **Math, Science & Engineering** | `stem/` | http://127.0.0.1:8102/ | Exact calculation, unit conversion with dimension checks, 35 solvable formulas, CODATA constants, the periodic table and molar masses; every saved answer can be recomputed |
| **History & News** | `facts/` | http://127.0.0.1:8103/ | Facts with their sources (books, newspapers, records — never AI services); disputes shown side by side; timeline; news feeds kept as "reported by" until you add them |

## Start

* **Windows:** double-click `START-WINDOWS.bat` in the application's folder.
* **Mac:** double-click `START-MAC.command` (first time: right-click → Open → Open).
* **Any computer with Python 3.8+:** `python app.py` in the application's folder.

Nothing to install: standard Python only. Leave the window open while you use the application.

## Language Builder (automatic) and its proof

The Language & Speech application is now the **Language Builder**, an administrator's tool that
builds QueryBook's languages before anyone runs queries. It is **automatic**: the first time it
starts it builds all 17 languages by itself (about 2 minutes); **Build all languages** runs it again.
It follows the last tested prototype (v9.50): English sub-language first (letters, phonics sounds,
syllables, rhythm, recurring words and word pairs, meanings switched off) until the one-way
**Transition Gate** opens, then meanings (Webster 1913), links into the 16 other languages,
pronunciation, then each other language — 20 steps, always in that order. The Build page shows a
status banner (what is happening and whether you need to do anything — normally nothing), the
whole-build bar with time left, the current step, every step with its start time, time taken and
result, every language, and a build log. `python app.py build` does the same in the window.

**Verify (proof)** shows third parties that it learns from scratch: it rebuilds everything in a
sealed, empty temporary database with all network connections blocked, checks that meanings are
refused before the sub-language is learned, records the learning curve from the first reading,
lists every input file with its SHA-256, checks that the code imports only the Python standard
library, and reduces everything learned to one SHA-256 **fingerprint** that must equal the
computer's own build. Anyone can run `python app.py verify` on their own computer and must get the
same fingerprint. Reports are kept in the data folder (`verification/`) and can be downloaded.

## Speech (Language Builder → Speech)

* **Speak:** one voice profile — emotion and its strength, tone, accent (the prototype's dialect rules),
  speed, pitch, volume, pauses, articulation, tremble, hoarseness, breathiness, whisper, voice age —
  sent to any of ten engines: espeak-ng, the prototype's formant voice, Windows and macOS voices
  (offline); Google Gemini TTS (30 voices, model, direction, temperature, two-speaker dialogue), Google
  Cloud Text-to-Speech (SSML, speaking rate, pitch, volume gain, sample rate, device profile, custom
  voices behind the consent gate), ElevenLabs (all models, stability, similarity, style, speaker boost,
  speed, seed, output format, v3 audio tags), OpenAI, Microsoft Azure (styles, style degree, age roles)
  and Amazon Polly (all engines, SSML effects). Every engine returns uncompressed audio; controls an
  engine lacks (tremble, hoarseness, breath, age, volume, pauses, pitch, speed) are added afterwards.
  The page shows, per control, whether it is native, added or unavailable, and the exact request.
* **Match a target:** generate → measure → adjust → repeat until pitch, speed, loudness, pauses,
  tremble and breathiness are within tolerance.
* **Listen & analyse:** volume, pauses, speaking and articulation rate, pitch and intonation, jitter,
  shimmer, harmonics-to-noise, tremor, breathiness; the **vocal mode** (whispering, crying, laughing,
  shouting, singing, speaking) with reasons; emotion, voice-age and hoarseness indicators; the words'
  language, meaning, pronunciation and stress from what the builder learned.
* **Ask by voice:** spoken questions answered out loud, responding to how they were asked.
* **Speech log:** every process with UTC timestamps and per-stage times to 0.01 s, statistics, CSV.
  Provider keys stay in the data folder (`speech_keys.json`, owner-only) and are never shown or logged.

## Transparency

* Every button shows a working bar at the top of the page and how long the action took (with the
  server's own time).
* Long work runs in the background with a progress bar, percent, speed, time left and elapsed time,
  and can be stopped.
* Every major task — start and stop, every change, imports, backups, lab runs, diagnostics,
  monitoring reports — is written to the **Activity log** (Diagnostics page) with its result and
  duration. The newest 20,000 entries are kept.

## Your data

Each application keeps one SQLite database in a data folder **outside** the program folder:

| Application | Default data folder |
|---|---|
| Language & Speech | `~/QueryBook-Data/language/` |
| Math, Science & Engineering | `~/QueryBook-Data/stem/` |
| History & News | `~/QueryBook-Data/facts/` |

(`~` is your home folder, e.g. `C:\Users\you`.) To use another folder — for example an external
drive — run `python app.py set-data E:\QB-Data\facts` once. Replacing or upgrading the program never
touches the data.

### Why the data stays safe

* Every change is one transaction under one lock (SQLite, WAL journal, full sync). A crash or power
  cut leaves the database as it was before or after a change — never half-written.
* The database is checked every time the application starts. If the check fails, the application
  **will not write** to it, shows a red notice and tells you to restore a backup.
* A checked backup is taken at start-up (when something changed) and before and after every import.
  The newest 10 are kept in `backups/` inside the data folder.
* `python app.py restore` lists the backups; `python app.py restore 1` restores the newest. The
  damaged file is set aside, not deleted.

## Redundancy

* **Backup mirror:** every checked backup can also be copied to a second folder — best on another drive.
  Each copy is proven identical (SHA-256) and passes a database check; restore lists both copies.
  Set it on the Diagnostics page or with `python app.py set-mirror E:\QB-Mirror` (`set-mirror off` stops it).
* **Voice failover (Language Builder):** the chosen voice, then espeak-ng, then the Windows or macOS voice,
  then QueryBook's own built-in voice, which needs nothing installed. Every attempt is logged.
* **Default voice bundled:** the official espeak-ng 1.51 Windows build (program, Microsoft runtime, the 17
  languages and all voice variants) ships in `language/espeak/` — Windows needs no installation, as in the
  prototype. macOS: `GET-VOICES-MAC.command`; Linux: `sudo apt install espeak-ng`.

## Diagnostics and the monitoring connection

Each application checks itself when it starts and every hour, and shows the results on its
**Diagnostics** page (also `python app.py diagnose`): Python version, program files, data folder,
free disk space, database check and layout version, database and journal size, backups (the newest
is opened and checked), errors in the last 24 hours, background work, and checks of the application's
own logic (known calculations, date and source rules, word lists and answer checking), the backup
mirror, and in the Language Builder every speech path: the default voice in all 17 languages, the
last-resort voice, the measurement chain against a known test voice, audio write/read-back, provider
keys and each provider's last result, the speech log, the language build and its proof. **Run full
self-test** runs the complete self-test from the page.

The **monitoring connection** sends these health reports to this development repository on GitHub,
as comments on one issue per application and computer
(`[QueryBook monitor] <application> · <computer name>`), so problems can be seen and fixed from the
development side:

* **When:** at once when a check fails or an error is logged (the same problem is repeated at most
  every 6 hours), plus a daily check-in. Can be changed to problems only, or hourly.
* **What:** check results, versions, operating system, and the first line of recent error messages.
  Never facts, words, answers, file names, the user's name or folders (the home folder is replaced
  by `~`), and never the token. **Preview a report** shows exactly what would be sent.
* **Setting up (once per computer):** create a fine-grained GitHub token limited to this repository
  with **Issues: Read and write** and nothing else; paste it on any application's Diagnostics page,
  tick *Monitoring connection on*, Save, and *Send a test report*. The token stays in that
  application's data folder (`monitor.json`, readable only by the user) and is only sent to GitHub.
* If GitHub cannot be reached, reports wait (up to 20) and are delivered with the next one.

## Bringing in the old QueryBook store

Each application has **Data & backups → Bring in … from the old QueryBook**. Point it at the old
store folder (the one with `blocks\`, `manifest.json` and `language_model.json`); the folder the old
QueryBook remembered is filled in for you when it can be found. Imports only **read** the old store —
they never write to it, index it or repair it. Each application takes only what belongs to it:

* **Math, Science & Engineering** takes the mathematical, geometric and calendar facts and **computes
  each one again**; only facts that come out the same are kept. Mismatches are listed.
* **History & News** takes history, culture, art and other facts, marked *needs checking* because the
  old store did not keep proper citations. The old prototype's bundled *example* headlines are skipped.
* **Language & Speech** takes the word counts from `language_model.json`, so the words the old
  QueryBook saw most can be put into your lessons.

The same import is available on the command line: `python app.py import-old E:\QB\mystore`.

## Checks

```
python tools/test_core.py            # data safety, diagnostics, monitoring (against a stand-in GitHub)
python language/app.py --selftest     # 91 checks
python stem/app.py --selftest         # 85 checks
python facts/app.py --selftest        # 36 checks
python tools/run_all_tests.py         # all of the above
```

## For developers

* `_core/qbcore.py` (database, backups, web server, old-store reader) and `_core/ui/qb.css`, `qb.js`
  are shared. Each application carries its **own copy** so it can be shipped alone; after editing
  `_core/`, run `python tools/sync_core.py`. The self-tests fail if a copy differs from the master.
* `python tools/package.py` builds one zip per application in `dist/`.
* The web servers listen on 127.0.0.1 only and refuse requests from other sites.
