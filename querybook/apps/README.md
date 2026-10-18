# QueryBook — three dedicated applications

The full-featured QueryBook prototype grew too large: its interface kept changing and its store was
damaged. These three applications replace it with one small, separate program for each kind of
knowledge. Each has its own folder, its own database, its own port and its own launcher, and none of
them changes the old QueryBook store. The facts they stand behind go into one **shared database, the
Commons**, where the three check each other's facts (see below). Each still runs on its own: if the
Commons cannot be opened, the application carries on with its own work.

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

## Talking face, camera and lip-reading (Language Builder → Speech)

* **Transcribe audio files (MP3, M4A, OGG, WAV — any length):** live captions while the file plays
  (Google Speech-to-Text hears it in pieces cut at pauses, sent ahead of the voice, so each word lights up
  as it is spoken), or the whole file as a background job — in pieces of at most 50 s with the API key, or
  through Google's long-audio recognition via Cloud Storage (service account + bucket; used automatically
  for recordings over 10 minutes). Timed transcript, TXT / SRT / VTT / JSON downloads, ingestion.
  Recordings over 50 s anywhere in the app (Listen & analyse, ingestion) are transcribed whole.
* **Live captions from the microphone:** words appear as you speak — a grey draft from the browser's own
  recognizer where available, replaced by Google Speech-to-Text a second or two later (speech is cut at
  pauses, at most every 6 s). Stop to download or ingest the recording and its transcript.
* **Talking face:** after Speak or Ask, a face moves its mouth in time with the voice — 2D (SVG) or 3D
  (three.js, bundled) with **Enter VR** for WebXR headsets. Mouth shapes are the 15 standard visemes
  (Oculus/Meta set), timed from the measured audio, or exactly from Google Speech-to-Text word times.
  Export JSON, CSV or Rhubarb TSV for animation tools.
* **Face & video:** camera, screen/tab capture or a video file. The face is tracked on this computer
  (MediaPipe Face Landmarker 0.10.14, bundled; nothing is uploaded) with live checks against the
  recommended set-up, recording to WebM, and an avatar that copies the mouth (2D/3D/VR).
* **Sync check:** cross-correlates lip opening with loudness and reports the offset in milliseconds
  (ITU-R BT.1359 limits: sound more than 45 ms early or 125 ms late is noticeable).
* **Lip-reading v1:** each frame is read as one of seven mouth classes; words are matched by dynamic
  time warping and every guess lists the words that look identical on the lips. With a script, the app
  scores how well the lips agree with it against chance — a mismatch suggests dubbing or another speaker.
* **Overdub:** new words in any voice, fitted phrase by phrase into the original speaking time without
  changing pitch, exported as a new video. Needs the consent box; always labelled **SYNTHETIC VOICE**.
* **Camera with the voice (ingestion, queries, answers):** tick the camera box in Ask by voice or
  Listen & analyse, or use step 4 of Face & video. The recognizer's possible readings (browser
  alternatives, Google Speech-to-Text alternatives, typed text) are scored by sound confidence and by
  how well the lips agree — the lips count for more when the picture is good — so a misheard
  "mouse in Finnish" becomes the "house in Spanish" the lips said. The face's expression is fused with
  the vocal mode (crying and laughing sound alike but look opposite), the answer's voice and the
  talking face's expression follow the asker's mood, and a speaker check says whether the voice
  belongs to the face (lips moving, lips matching the words, sync). Every result is in the speech log.
* **Teach and improve — the ingestion reservoir (speech-visual domain):** every recording with a face
  and known words (a teaching sentence, a video with its script, Speech-to-Text at ≥ 85% confidence) is
  deposited as numbers only — never pictures. Labels come from the words and the audio; a recording
  that does not fit its sentence is kept out. The learner (`lipcoach.py`) fits a mouth-shape reader for
  this camera and speaker, the shapes it confuses, the computer's camera/microphone delay, the
  lip-sync timing weights (from exact word times) and the talking face's mouth shapes. About one
  recording in four is held back for testing (fixed by its hash); a learned version is used only when
  it beats the current one there. Every version is kept with its scores and can be rolled back; the
  reservoir exports and imports, so several computers can pool what they learn. Deterministic: the
  same reservoir always gives the same version.
* **Photo Real Lab and the Author Narrator:** an AI narrator that looks and sounds like the author, only with
  the author's signed consent (fingerprints of the photo and voice sample are kept; everything is labelled
  "AI narrator"). Voice: Google custom voice, ElevenLabs clone, or the offline voice tuned to the sample.
  Face: the photo-driven face in the app, HeyGen, D-ID, or a local model (Wav2Lip, SadTalker, any command).
  The lab starts from one perfect sample (the author reading the reference passage on camera), fits the
  author's own mouth model to it (lip lead, response time, a shape per sound) and keeps the author's real
  frames per sound (the real-mouth library the narrator is composed from). Every narration is measured
  frame by frame against what the author's mouth would do for the same words and released only if it
  passes the gate; the in-app face is calibrated in a closed loop until it does. Findings are UFCS 1.0
  fact packets in the "photoreal" graph domain, exportable to the QueryBook store.
* **Visual Speech Engine (Face & video):** lip sync and lip reading rebuilt along the Visual Speech Engine
  specification, without any AI model. *Audio:* sounds and their timing, pitch/energy/voicing/speaking rate at 100 per
  second, an 8-number emotion vector and a voice fingerprint. *Face:* head pose (from the face mesh's transformation
  matrix), camera steadiness, a first-order lighting estimate and a geometric "same face throughout?" check — numbers
  only. *Lip sync:* every sound pulls the mouth toward its shape with a strength that fades in time (Cohen–Massaro
  coarticulation), so neighbours blend, lips round ahead of "oo" and every p/b/m closes; plus jaw, brows and head
  nods on stressed words, blinks and glances at pauses, scaled by the emotion; your own mouth shapes once the
  reservoir has learned them. Exports ARKit-named blendshape curves (CSV) and JSON; a preview face plays it.
  *Lip reading:* soft scores for all 15 mouth shapes (Gaussian models calibrated by analysis-by-synthesis, or your
  learned model) decoded by a hidden-Markov word network with word-frequency priors; with a script, forced alignment
  gives each word's timing and agreement. Results appear next to lip-reading v1 in "Analyse video". **Benchmark**
  (button, or `python app.py vse-bench`): on 64 synthetic utterances (4 speakers, sentences the decoder was never tuned
  on) the look-alike word error rate fell from 96% (v1) to 61%, exact words from 98% to 71%, and the script check
  told right from wrong scripts 100% of the time (v1: 91%). These are synthetic speakers, a regression check; teach
  the reservoir (step 5) and the same benchmark measures your own face. API: `/api/vse/lip_sync`, `/api/vse/lip_read`,
  `/api/vse/benchmark`, `/api/vse/job?id=`. Stage 2 — trainable PyTorch models with the same formats, API and
  benchmark — is the separate package `querybook/vse/`.
* **Object scan (Face & video):** recognizes 80 kinds of everyday object (people, cars, cups, phones, books,
  animals…) in the camera, a shared screen or a video file, on this computer (MediaPipe Object Detector,
  EfficientDet-Lite0, bundled, Apache 2.0). Each object is followed from frame to frame; click its box, or name a
  kind, to follow it and see it enlarged. **Record the enlarged view** opens it in the analysis steps, so a face
  far away (a telephoto lens on a phone) can be lip-read — only with the box ticked that the person knows and
  agrees, or that it is a public talk or broadcast; expect a few words from a short expected list, not
  conversations. What was seen is saved as numbers only (what, when, how sure, where in the picture), never as
  pictures, and is kept apart from facts. Ask about it by typing or voice, here or in Ask by voice: "what is
  this in Spanish?", "when did I last see a cup?", "did I see a dog today?", "how many people did I see
  yesterday?", "what did I see in session 3?".
* **Silent questions:** a question mouthed without sound is matched against the questions QueryBook
  answers (pattern by pattern, with known words and language names in the gaps); the best readings and
  their look-alike words are offered to tap. Guided mode: tap the question and language, mouth the word.
* **Best capture:** whole face, forehead to chin, 40–60% of the picture's height (not just the mouth);
  mouth ≥ 150 px wide; 1080p (720p works, 4K adds nothing); 60 fps best, 30 minimum; face the camera
  within 20°; even front light; nothing over the mouth; mic 20–30 cm away.

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

## The Commons: one shared fact database and three harvest teams

All three applications use one shared SQLite database for facts: `~/QueryBook-Data/commons/commons.sqlite`
(another folder: environment variable `QB_COMMONS_DATA`, or the page **Shared facts & agents**). It is
protected exactly like each application's own database (one transaction per write, WAL, full sync,
checked at start-up, verified backups in `commons/backups/`). Their own work — word cards, saved
answers, sources and feeds — stays in their own databases.

Each application has a **team of four agents**, run in order as one harvest cycle, automatically a
little after start-up and then every 30 minutes (switch off on the page), or with **Run this team
now** or `python app.py harvest`:

| Agent | Duty |
|---|---|
| **Strategist** | Surveys what the application knows and what the Commons lacks; devises the strategy — ranked goals with reasons, the sources allowed under the licence policy, a budget for the cycle |
| **Planner** | Turns the strategy into a plan of bounded tasks (for example "Share Finnish translations of words 251–500") |
| **Harvester** | Executes the tasks and stages what it finds — facts, evidence, reasoning, and checks to ask of the other applications. Nothing is written yet |
| **Curator** | Saves the staged facts (duplicates merge, evidence accumulates; a failed save is rolled back whole and its cursor stays put), answers the checks the other applications asked of this one, recomputes each fact's status and takes a backup |

| Team | Harvests | Answers for the others |
|---|---|---|
| Language Builder | English meanings (Webster 1913, public domain), most common words first; translations into the 16 languages (MUSE, CC BY-NC — left out under the commercial policy) | Is the English word in the dictionary? Is the translation in the bilingual dictionary? |
| Math, Science & Engineering | Constants (CODATA 2018), elements (IUPAC), unit definitions, molar masses and derived constants (recomputed), its own verified saved answers; re-checks the shared values | Is the lifespan possible? Are the dates in order? Is it a real calendar date? Does the arithmetic or unit conversion hold? Is it a chemical element? |
| History & News | Facts with documented sources (each source is separate evidence; never AI services); refreshes your feeds and shares headlines as *reported*, not confirmed | Does a documented source record it? |

**Cooperation.** A fact can carry checks for the application able to answer them: History & News asks
Math & Science whether a person's birth and death dates give a possible lifespan; Math & Science asks
the Language Builder whether each element's name is a dictionary word. The answer is kept with the fact
as evidence, with the reasoning steps. Applications never run each other's code; they cooperate only
through the shared database, so a check waits until the answering application's team next runs.

**Status of a shared fact**, from its evidence alone: *verified* (recomputed), *corroborated* (two
independent sources, or a source plus another application's confirming check), *sourced*, *reported*
(news), *unsourced*, *disputed* (support and contradiction — no winner is picked) or *rejected*.
Consistency checks (lifespan, dates, dictionary word) can refute a fact but never raise one.

**Licence policy** (shared by all three): *research* uses every source and marks non-commercial ones;
*commercial* never harvests a source whose licence forbids commercial use.

The agents are deterministic programs, not AI models: the same inputs always give the same strategy,
plan and shared facts.

## Google Cloud (optional, all three applications)

Diagnostics → **Google Cloud** connects an application to your Google Cloud project. Nothing to install;
credentials stay in the data folder (`google.json`, owner-only), are sent only to Google and are never
shown or logged. **Copy settings from …** reuses what another QueryBook application already has.

| Service | Needs | What it does |
|---|---|---|
| Cloud Storage | service account + bucket | every verified backup is also uploaded (resumable, MD5-checked) to `querybook/<app>/<computer>/`; the newest N are kept; any copy can be downloaded and restored |
| Cloud Monitoring | service account | health, failed and warned checks, errors and uptime written after every diagnostics run; **Create alert** adds a policy for "silent for 3 hours or a check failed" |
| Speech-to-Text | API key | Language Builder: words with timings and confidence for recordings and spoken questions; falls back to the browser's recognizer |
| Text-to-Speech / Gemini TTS | API key | Language Builder voices use the same key |
| YouTube Data API v3 | API key | History & News: search YouTube or add a video by link; videos are "reported by" a channel until promoted to a fact (source kind "video channel") |

* **Easiest — one paste sets up all three applications:** Diagnostics → Google Cloud → open Google Cloud with
  Cloud Shell, press *Copy the setup commands*, paste them into Cloud Shell and press Enter. Using only Google's own
  command-line tool in your project, they switch on the APIs, create an API key **restricted** to Text-to-Speech,
  Speech-to-Text, YouTube and Gemini voices, a backup bucket, and a service account with only the Storage Object
  Admin (on that bucket) and Monitoring Editor roles. They print one `QBSETUP-…` code: paste it into any
  application and every QueryBook application on the computer is configured. Safe to run again.
* **API key:** https://aistudio.google.com/apikey (or Cloud console → APIs & Services → Credentials).
* **Service account:** Cloud console → IAM → Service accounts → create, give it *Storage Object Admin* and
  *Monitoring Editor*, then Keys → Add key → JSON, and choose that file on the Diagnostics page. Requests are
  signed with RS256 implemented in the standard library (checked byte-for-byte against OpenSSL).
* **Test all Google services** tries each one and shows the result and time; diagnostics check sign-in, the
  newest cloud backup and the last Monitoring report every hour. Gemini assistants and agents are deliberately
  not connected: History & News uses human sources and Math & Science exact computation.

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
python tools/test_commons.py         # the shared database and the three teams, end to end (38 checks)
python language/app.py --selftest     # 186 checks
python stem/app.py --selftest         # 86 checks
python facts/app.py --selftest        # 44 checks
python tools/run_all_tests.py         # all of the above
```

## For developers

* `_core/qbcore.py` (database, backups, web server, old-store reader), `_core/qbcommons.py` (the
  Commons and the agent teams) and `_core/ui/qb.css`, `qb.js` are shared. Each application's team
  is its `harvest.py`. Each application carries its **own copy** so it can be shipped alone; after editing
  `_core/`, run `python tools/sync_core.py`. The self-tests fail if a copy differs from the master.
* `python tools/package.py` builds one zip per application in `dist/`.
* The web servers listen on 127.0.0.1 only and refuse requests from other sites.
