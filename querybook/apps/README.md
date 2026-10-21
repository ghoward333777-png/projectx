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
(another folder: environment variable `QB_COMMONS_DATA`, or the page **Harvesting & shared facts**). It is
protected exactly like each application's own database (one transaction per write, WAL, full sync,
checked at start-up, verified backups in `commons/backups/`). Their own work — word cards, saved
answers, sources and feeds — stays in their own databases.

Each application has a **team of four agents**, run in order as one harvest cycle, automatically when the
harvesting engine gives the application its turn (switch off on the page), or with **Run this team
now** or `python app.py harvest`:

| Agent | Duty |
|---|---|
| **Strategist** | Surveys what the application knows and what the Commons lacks; devises the strategy — ranked goals with reasons, the sources allowed under the licence policy, a budget for the cycle |
| **Planner** | Turns the strategy into a plan of bounded tasks (for example "Share Finnish translations of words 251–500") |
| **Harvester** | Executes the tasks and stages what it finds — facts, evidence, reasoning, and checks to ask of the other applications. Nothing is written yet |
| **Curator** | Saves the staged facts (duplicates merge, evidence accumulates; a failed save is rolled back whole and its cursor stays put), answers the checks the other applications asked of this one, recomputes each fact's status and takes a backup |

| Team | Harvests | Answers for the others |
|---|---|---|
| Language Builder | English meanings (Webster 1913, public domain), most common words first; translations into the 16 languages only from an approved source — the bundled MUSE dictionaries are CC BY-NC, so the registry blocks them | Is the English word in the dictionary? Is the translation in the bilingual dictionary? |
| Math, Science & Engineering | Constants (CODATA 2018), elements (IUPAC), unit definitions, molar masses and derived constants (recomputed), its own verified saved answers; re-checks the shared values | Is the lifespan possible? Are the dates in order? Is it a real calendar date? Does the arithmetic or unit conversion hold? Is it a chemical element? |
| History & News | Facts with documented sources (each source is separate evidence; never AI services); refreshes your feeds; headlines (copyrighted text) are blocked by the registry unless the admin accepts that restriction | Does a documented source record it? |

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

## The harvesting engine, policy registry and admin approvals

Page **Harvesting & shared facts** (all three applications); code `_core/qbharvest.py`.

**Policy registry.** Every source a harvest task names is a registry entry with its stated licence and a
*licence class*. Only `public-domain`, `cc0`, `facts` (bare facts and measurements, not copyrightable),
`us-federal`, `computed` (QueryBook's own calculations) and `user-facts` (facts you entered with your own
citations) are harvested. `attribution`, `share-alike`, `non-commercial`, `no-derivatives`,
`copyrighted-text`, `terms-of-service` and `unknown` are blocked, because each would put a condition on
QueryBook. A source the planner names that is not in the registry is registered as *pending / unknown*
and blocked until classified. Third-party wording (quotes) is stored only from public-domain, CC0,
US-federal or computed sources; from anything else only the fact itself is kept. Seeded: Webster 1913
(approved), CODATA, IUPAC, SI definitions, computed values, your saved answers and your history sources
(approved), MUSE bilingual dictionaries (blocked: CC BY-NC) and news headlines (blocked: copyrighted text).

**Researched sources (October 2026): chemistry, architecture, geography, programming, mathematics, civil
engineering, quantum computing.** Each publisher's own terms were checked on the web and the results are
seeded into the registry (`RESEARCHED_SOURCES`). Nothing is approved automatically: the 14 unrestricted
ones arrive as *pending* with an approval request each; the 8 restricted ones arrive *blocked* with why.

| Subject | Pending your approval (unrestricted) | Blocked (restriction) |
|---|---|---|
| All | Wikidata structured data (CC0) | — |
| Chemistry | PubChem computed properties (US federal; NCBI-computed values only) | NIST Chemistry WebBook (SRD copyright), OpenStax (CC BY), Khan Academy (BY-NC-SA) |
| Architecture | HABS/HAER/HALS (public domain), Vitruvius 1914 translation, pre-1931 Gutenberg texts | MIT OCW (BY-NC-SA) |
| Geography | Natural Earth (public domain), USGS GNIS, Census Gazetteer, archived World Factbook (ended Feb 2026; facts kept "as of" their edition) | — |
| Programming | NIST Dictionary of Algorithms and Data Structures (except CRC Press entries) | Python docs (PSF notice) |
| Mathematics | pre-1931 Gutenberg texts, arXiv CC0 papers, QueryBook's own computation | OEIS (CC BY-SA), NIST DLMF (copyright claimed) |
| Civil engineering | HAER, FHWA federal-authored reports, USACE manuals marked for public release | — |
| Quantum computing | NIST FIPS 203/204/205, arXiv CC0 papers | Qiskit textbook (Apache 2.0 notice) |

**Second round — all areas of language, STEM and history** (24 more; 16 pending, 8 blocked):

| Area | Pending your approval (unrestricted) | Blocked (restriction) |
|---|---|---|
| Language | Tatoeba CC0 sentences, Common Voice sentence text (CC0), US Foreign Service Institute courses (federal; mirrors only — verify each) | Wiktionary (CC BY-SA), Princeton WordNet (notice required), PanLex (its two licence statements conflict) |
| STEM | NASA, NOAA, USDA FoodData Central (CC0), NCBI Taxonomy, Smithsonian Open Access (CC0) | Wikipedia text (CC BY-SA — use Wikidata), CK-12 (non-commercial), Saylor (CC BY), LibreTexts (per-page, often NC) |
| History | National Archives (records marked "Unrestricted"), Chronicling America newspapers over 95 years old, Foreign Relations of the US, Army Center of Military History, Europeana / DPLA / Met / Rijksmuseum metadata (CC0) | OpenStreetMap (ODbL share-alike) |

In total 46 researched sources: 30 pending approval, 16 blocked.

**Admin decision, 19 October 2026:** "I approve all the above sources — provided they do not risk
copyright issues." Applied by `Registry.ensure()` (`ADMIN_DECISIONS`) to every source still pending that
was never decided in the app: 28 approved, each recorded as a policy version with the admin's words and
its conditions. Two are **held back** under the condition, because a program cannot check their copyright
reliably: the FSI courses (only on unofficial mirrors) and FHWA reports (many are contractor-written).
Approve those by hand in the app if a document checks out. Researched sources are **facts only**: no
wording from them is ever stored, whatever their class.

## Avatar library (Language Builder → Speech → Avatars)

Portraits become talking avatars. Import PNG/JPEG/WebP files, a folder or a .zip; each portrait is measured in the
browser at **478 face points with depth** and checked (front-facing, closed mouth, face size). Only portraits that show
nobody real (the admin confirms they are AI-generated) or a real person who agreed (name and consent recorded) can be
added; everything an avatar says is labelled as synthetic.

When an avatar speaks, the Visual Speech Engine drives **all 52 ARKit face channels** frame by frame — jaw, lips
(open, close, funnel, pucker, press, roll, stretch, smile, frown, dimple, upper up, lower down, shrug), cheeks (puff,
squint), nose (sneer), eyelids (blink, squint, wide), eye direction (8 gaze channels), brows (inner up, outer up, down)
and tongue — with co-articulation, lip closure on p/b/m, blinks at phrase breaks, brow raises and nods on stressed
words, and slight left/right asymmetry. The renderer (`ui/avatarface.js`) moves each channel's region of the 3D mesh and
turns the head in 3D using the landmarks' depth.
The mouth is shaped like a real one: the lips part as a lens that tapers to the corners (not a slot), the lip lines are
constraints of the face mesh (no skin is stretched across the opening, on any face shape), the lips are told apart by
their own landmark rows rather than a straight corner-to-corner line, mouth widening is soft-limited to about 10%, and
the teeth follow the curve of the upper lip. The portrait's own mouth is used until the lips part beyond it.
**Mouth fit**: each face's mouth is sized from its own anatomy — millimetre scale from the iris (≈11.7 mm; face
height as a cross-check), mouth width and lip thickness measured from the landmarks, the opening on "aa" set to about
0.28 × mouth width (9–16 mm, as in conversational speech), the opening's outline taken from the person's own lower lip,
and the teeth limited to ~3 mm. The studio shows the numbers for the selected face.

**Lips move like lips.** Each lip moves as a solid band — all of its landmark rows together — so it keeps its own
thickness and width while talking; the skin around the lips (relaxed over the mesh, lips pinned) takes up the motion.
Rounding (o, u, w) moves the corners, not the middle of the lips; pressing (p, b, m) draws the outer edges in without the
lips ever crossing; a blink closes along a corner-to-corner curve with the iris tucked under the lid.

**Both lips curve open.** On a vowel the lower lip drops (about 70% of the opening) and the upper lip arches up toward its
middle (about 30%), both tapering to the corners, so the opening is the oval of a real mouth, never a flat-topped slot.

**Aesthetic guardrail** (`_mouthInside`, `aesthetic()`): the inside of the mouth is drawn as a real one looks in speech —
a deep, warm shade of this person's own lips (not black), the tongue resting on the floor of the mouth (it rises for
th/l, never floats), six upper front teeth as one row hanging from the upper lip's curve with a faint scallop and fine
separations, darker toward the corners, coloured from this face's own eye whites, and a smooth, feathered edge (no
facets). Gums are never shown in speech. The check, on the rendered pixels of an open "aa": teeth no brighter and no
bluer than the sclera, at most ~3 mm and a third of the opening, the cavity 8–60% of the lips' brightness, no
lip-coloured flesh inside the opening; the opening on "aa" is held to conversational size (0.24 × mouth width, 8–13 mm).
It is part of the movement check, so it runs on every face and is reported in the studio.

**Lip line from the photo.** The face tracker can put the line where the lips meet too low or too high on glossy or
stylised lips; then part of one lip moves with the other and shows as a flap of "gum". With the mouth closed in the
portrait, the true line is found in the photo — the crease between the lips, a valley darker than the lip above and
below it, sampled across the mouth and fitted with a smooth curve through the corners — and the lip landmarks are moved
onto it (rows inside each lip re-spaced). When the tracker already agrees, nothing changes.

**Movement quality control** (`DepthFace.qc()` / `autotune()`, run every time a face is built): 24 poses (every viseme,
strong vowels, smile, blinks, gaze) are checked on the mesh — upper-lip thickness 0.88–1.15 and width 0.90–1.07 of the
portrait, lower-lip thickness 0.85–1.20, mouth width 0.80–1.10, no triangle turned over, lips never crossing. A failing
pose softens only the channel to blame, for that face. The result is kept with the avatar (`qc.json`), shown in the
studio, flagged in the library, and *Check movement of every face* re-runs it for the whole library. The studio shows all 52 channels as sliders, expression presets, and
exports the motion as a 52-channel CSV (Live Link Face / Blender / Unreal order). Any Speech-lab result can be shown on
a library avatar.

**Choosing a face.** Speech → Speak is four numbered steps — ① the face (large preview of the chosen face plus every
face as a tile), ② the voice, ③ the text, ④ *Speak with the chosen face*. The chosen face appears at once and speaks
with mouth shapes while the 52-channel motion is computed; if that motion fails the same face keeps speaking. The strip — 2D, 3D/VR and a thumbnail of every analysed
avatar; the choice is remembered in the browser and every talking face (Speak, Ask) uses it. The same strip sits
under each talking face, so one click switches who speaks. The Avatar studio opens on a face with the same strip: clicking another face
keeps the speech playing on the new face, and **Every face in turn** plays the speech while the faces take turns. The installer ships a **starter set of 20 AI-generated
portraits and 3 full-body avatars** (`language/avatars_starter/`, already analysed) that is added once on first start; avatars you delete
stay deleted. Full-length or group photos are cropped to the face automatically when analysed (the original is kept),
unless they are imported as full-body photos.

**Full-body avatars.** A second row under the faces holds full-body avatars — the whole figure is shown, the face
speaks with all 52 channels exactly as a face avatar does, and the body breathes (chest and shoulders rise, the head
with them) and shifts its weight in a slow sway that grows with height above the hips; the edge of the picture stays
still, so the background never slides. The first is *Pamela* (AI-generated): her head is in the face library and she
stands as three full-body avatars (track, stadium, water bottle). To add more, tick *full-body photos* when importing:
the photo is kept whole, and when the face is too small for the tracker it is found through zoomed windows over the
picture. The Quality lab keeps testing face avatars, whose mouths fill the frame.

**Calibrated against a reference video of the same model.** Full-body motion was measured frame by frame with the
face tracker against a Gemini video of Pamela speaking the same lines, and tuned until the measures met it: the mouth
opens mostly by lifting the upper lip and dropping the lower lip (a speaking smile) with less jaw and little rounding
(opening, lower-lip drop and width now within ~10% of the reference); brows move 3–5× more; blinks really close (the
lid is drawn with her own lid skin and a lash line, and stays shut ~0.25 s); the head turns, nods and tilts up to about
10° with the hair and the torso following; breathing and weight shift; and the camera cuts every 2.5 s between a wide
and a close shot with a slow push-in (switch it off under the face: *camera cuts and push-ins*). What a single photo
cannot do: turn the head as far as the reference (~18°: beyond ~10° the hair tears), move the arms into new gestures,
or change the camera angle — those need a generative video model.

**Turnaround: her own side and back views.** A full-body avatar can carry a turnaround — a short video of the person
turning on the spot (front → side → back → side → front). *Avatar studio → Import a turnaround video* reads it frame
by frame: every frame is aligned to the face where the tracker sees it (front to ~60° either way); behind, where no face
shows, the person detector's outline (shoulder width and head top, calibrated on the frames facing the camera) carries
the size and position across, shot by shot, so camera cuts and zooms in the source do not make her jump. The part
where she actually turns is found and kept. Then *↻ Turn around* (under the talking face, and in the studio) — or the
words "turn around" in the text, at the moment they are spoken — cuts to a medium shot, fades into her real turn, and
fades back to the talking photo, at her own pace (a real turn on the spot takes ~7–8 s; if the speech ends or pauses
mid-turn she finishes turning). Full-length clips work too: where the face is too small for the tracker, it is found in
a zoomed square around the head. Pamela ships with two: a full-length one on her track avatar (97 frames) and a closer
one on her stadium avatar (81 frames).

**Moves: a motion library per full-body avatar.** The turnaround is one move among many. *Avatar studio → Moves →
Find the moves in it* reads any video of the person (one pass: face, outline and camera cuts in every frame), suggests one
move per camera shot, and lets you name each, set its times, the words that start it, and its camera: *still camera*
(the body travels through the picture — a cartwheel, a walk towards you; the camera is taken from frames where she
stands upright facing it, and a close-up stays a close-up) or *follow her* (on the spot, like a turn). Each move gets a
button under the talking face, and its words in a script set it off as they are spoken; moves named close together
play one after another, and a move named twice in one sentence plays once. Pamela's track avatar ships with nine:
turn around, arm swings, boxing, side kick, cartwheel, walk to you, high knee, water break, and swimming (a drone view
in a pool, played as a cutaway). The words: "turn around"; "arm swings / stretch / warm up"; "box / punch / fight";
"kick"; "cartwheel / flip"; "walk / come closer"; "high knee / march"; "water / drink / bottle"; "swim / pool /
backstroke". In the calibrated speaking smile
the upper front teeth now show as they do in the reference (up to ~9 mm, never brighter than the eye whites).

## Quality lab (Speech → 🎬 Quality lab)

Every avatar test is a quality sample. The chosen face says a test script (four built-in scripts cover every mouth
shape, or your own text) and the picture and sound are **recorded as a video holding every word** (a test is marked
incomplete otherwise). The video is then measured with the face tracker frame by frame — lip opening, wide openings,
widening/narrowing, upper- and lower-lip thickness change, lip speed, jitter, closures, lips-to-sound timing — exactly
as **human reference clips** are measured (record yourself reading the script with the webcam, or add clips you may
use: public domain, Creative Commons, government works, your own). Each measure scores 100 inside the human range;
until references exist, provisional ranges are used and say so. Each test proposes the next **candidate calibration**
(jaw, spread, rounding, closure, upper-lip arch, teeth, smoothing, timing) and the next test uses it. Only the admin
(passphrase) **approves** a calibration; every face outside the lab speaks with the approved one, and *Ship approved
with the installer* writes `calibration.json` next to the program so packaged installs start with it.

**Self-learning from real speakers.** A reference clip given with its words is aligned (its audio against its words by
the speech engine), every frame is labelled with the sound being made, and the **human motion model** is rebuilt: the
mouth shape of each sound (in the tracker's units), blink rate, head sway and brow movement. The speech engine uses it
for every face (a speaker's own learned shapes still win). The **motion graph** links languages, words, sounds and
emotions to the measured movement (`lang —uses_word→ word —articulated_as→ viseme`, `word —moves_mouth/moves_head→`,
`viseme —shaped_under→ emotion`, `emotion —moves_head→`), rebuilt deterministically from every learned clip; look up any
node in the lab. **Sources**: record yourself, add files you may use, or fetch from allowed archives — Voice of America
(news in ~40+ languages, public domain as a US government work, except third-party footage), US government .gov/.mil,
Wikimedia Commons, Internet Archive, Zenodo, the GRID corpus. YouTube, broadcasters and film/TV sites are refused: their
terms forbid downloading and the footage is copyrighted. The **self-learning loop** records test after test (rotating
scripts and faces), scores each against the human references, calibrates the next, and resumes whenever the lab is
open, until the admin approves.

**Ingest example videos** (Quality lab): one button fetches talking clips from the automatic sources — NASA briefings and
interviews (public domain, with caption files) and Wikimedia Commons speeches (public domain / CC BY / CC BY-SA per file,
captions when the file has them) — politely (one request at a time, waiting when a site asks). Each clip is scanned for
close-ups (one face, large and facing the camera, ≥ 3 s; up to 90 s per clip), measured, and learned from: the caption
lines inside each close-up give the words, aligned with its speech. Clips with no clear talking face are dropped. The
**library** lists where to see how talking should look (NASA, Wikimedia Commons, Voice of America, GRID, CREMA-D, RAVDESS,
Seeing Speech, your own recordings), what each teaches, its licence, and whether the button ingests it.

**The whole face talks.** Cheeks lift with spread and open vowels, the lower lids narrow with them and with emphasis,
the eyes widen on raised brows, brows move more on stressed words, the nose wrinkles on f/v; all scaled to what real
speakers do once clips are learned. Skin creases deepen and fade with the muscles — forehead lines, frown lines, crow's
feet, under-eye bunching and smile lines — drawn along the moving mesh in this face's own skin tone.

**Under every talking face**: ▶ Play / ❚❚ Pause with the clock, and ⬇ Download video (MP4: recorded in the browser as
H.264 where it can, otherwise converted with ffmpeg when installed, else WebM).

**Matched against a reference speaker.** A Gemini-generated reading of an articulation script was measured frame by
frame with the same tracker as the prototype's own recording, and the engine retuned toward it: a larger opening (0.34 ×
mouth width on "aa"), the jaw as a hinge (the chin travels ≈1.35× the lower lip, the jawline drops with it), rounding that
narrows the mouth to ~0.6–0.7 and spreading up to ~1.2 of its width, stronger lip presses and lower-lip pull, lower teeth
on wide openings, a slight smile while talking, livelier brows and lower lids, deeper nods, less upper-lip lift and less
smoothing (20 ms). Quality-control limits were widened to match (mouth width 0.60–1.25). The Quality lab's provisional
human ranges are centred on the reference's measures.

**Speed.** The face is drawn with whichever method is faster on the computer, timed when the face loads: WebGL (the
graphics card warps the photo as one textured mesh) or the 2D canvas. A slow draw was the main reason recordings ran at
~7 frames a second.

## Staying awake, the log, and the system's own logs (all three applications)

While an application runs it asks the computer **not to sleep** (Windows: a power request, `SetThreadExecutionState`;
macOS: `caffeinate -i`; Linux: `systemd-inhibit`). The screen and screen saver may still switch on; the work goes on.
Long work in the browser (learning loop, ingesting, recording, speaking) holds a **screen wake lock** while it runs, so
the screen saver does not pause the page. To let the computer sleep, start with `--allow-sleep` or set `QB_ALLOW_SLEEP=1`.

The **log file** (`<data folder>/<app>.log`, five older copies kept) marks every session, notes when a previous run did not
stop cleanly, and a heartbeat records any stretch when the program was paused (the computer slept). At start-up each
application **reads the system's own logs** — Windows Event Log (sleep, wake with its wake source, modern-standby screen
off/on, unexpected shutdowns and restarts), the sleep / hibernate / screen-off timeouts, the screen-saver settings and what
is blocking sleep (`powercfg /requests`); macOS `pmset`; Linux `journalctl` — and writes what it found to the log.
Diagnostics → *Power, sleep and the log* shows it all and offers **Download the log**.

## Agents: pick your agents, learn from the best, Open Claw as knowledge (`_core/qbagents.py`, all three applications)

**Non-LLM reasoning.** Every agent is a deterministic program — measurements, statistics and stated rules; the same
input always gives the same result, with the measures and examples that produced it. No agent calls or imitates an
AI model: requests to AI-model services (29 hosts: OpenAI, Anthropic, Google Gemini/Vertex, Mistral, Groq, OpenRouter,
Hugging Face inference, local Ollama …) are refused by the one network function every agent uses. The tab shows a
purity audit (no model libraries imported, hosts blocked, imported lines kept vs quarantined).

**Pick your agents** (tick to use, untick to switch off; the admin passphrase guards it once set):
Reader (text — typed, any of 40+ document formats via the Open Claw Artifact Segmenter, or a web page), Listener
(any recording or the microphone: pauses, phrasing, speaking rate, loudness dynamics, pitch range and melody),
Watcher (any video or the camera, measured frame by frame in the page: movement, stillness, rhythm, cuts, light,
colour), Live feed (JSON/CSV addresses read on a schedule), Toucher (pen and touch pressure, speed, smoothness,
rhythm on a drawing pad; contact force from tactile sensors via Devices), Mover (phone motion, wearables, heart rate,
gaze via Devices), Any sensor (smell, taste, temperature … any numeric channels), Mentor, Open Claw importer.

**Skills — learn from the best.** Name a skill and the agent that measures it; add exemplars of best-in-class
performers (title, performer, source, licence — own work, public domain, Creative Commons, government work or
permission — and a 1–5 rating). The Mentor builds a mastery profile: per measure the rating-weighted median, the
p10–p90 range, a robust spread, and a weight that grows with how consistently the masters share it. Every sample you
score gets 0–100, a verdict, the closest exemplar, and the advice that would close the biggest gaps ("average sentence
length: yours 16 words, masters 5.5 → write shorter sentences"). Each new exemplar makes a candidate profile; the
admin adopts one.

**Open Claw — agents, skills and tools as knowledge.** Search ClawHub, index every ClawHub skill (its public
read-only API, page by page; suspicious skills skipped; flagged skills refused), import any skill as a zip, read
your own Open Claw installation (`~/.openclaw`: each agent's AGENTS.md, SOUL.md, IDENTITY.md, TOOLS.md, HEARTBEAT.md,
every skill folder, the tools allow/deny configuration, plugins and MCP servers; credentials, sessions and keys are
never read and secrets in openclaw.json are redacted; USER.md and memory only when you tick it), or upload a skill
folder. Each becomes a playbook: checklist steps, commands (listed, never run), required tools and settings, facts,
terms and links are kept; every line that instructs a language model — personas, tone, prompts, "respond with…",
"think step by step" — is quarantined, shown with the reason, and never used; scripts are listed, never executed.
A text skill can use a playbook: its key terms become a measure ("playbook terms covered").

## Self-improvement: the Engineer (`_core/qbengineer.py`, Agents tab → 5, all three applications)

QueryBook reads its own program and suggests improvements to itself — with deterministic program analysis, no AI model.
**Its skills:** Python read with the language's own parser — imports never used (fix), `== None` (fix), bare `except:`
that also swallows Ctrl+C (fix), mutable default arguments, very long or very branchy functions, TODO/FIXME notes
(advice); the pages' JavaScript — `console.log` / `debugger` left in (fix), functions nothing calls (advice); and the
running program — errors in its own log, traced to the file and line (advice), and work that is regularly slow, from
its activity record (advice).

**Nothing changes without the admin.** Every finding is a proposal with its evidence; a fix carries the exact change
(a unified diff). Approving needs the admin passphrase. An approved fix is first made in a copy of the program, compiled,
and the program's whole self-test is run on that copy; only if it passes is the change made — the originals backed up,
a one-click revert, the result recorded (restart QueryBook to run the improved program). A shared core file is changed in
every application and the master copy. Approved advice becomes a to-do item. **It learns from the admin:** proposals are
ranked by severity and by what the admin has approved or rejected before, and a skill rejected three times without an
approval is muted until the admin unmutes it.

## Devices: one API for cameras, glasses, robots, wearables (`_core/qbdevices.py`)

Every application has a **Devices** tab and the same device API (`GET /api/devices/openapi.json`):

* **Register** a device (admin passphrase) → it gets its own key (`qbd_…`, shown once; only a SHA-256 is stored).
  Devices that record people, body signals or location need the person named and their consent confirmed.
* **Send events**: `POST /api/devices/ingest` with `Authorization: Bearer qbd_…` and `{"events": [...]}` — kinds:
  heart, ecg, imu, steps, gaze, face, pose, transcript, location, detection, touch, state, note. Events outside the
  device's consent are refused with the reason. Media files (≤ 25 MB) go to an admin inbox via `/api/devices/upload`.
* **Observations, not recordings**: heart rate and movement become per-minute statistics, ECG only a summary;
  detections, transcripts, touches, fixations and places become dated observations ("when did I last see the cup?").
  Raw events are deleted after 30 days (configurable).
* **Home network**: tick "Accept devices on my home network" to open a second listener (port 9101 / 9102 / 9103) that
  answers **only** the device endpoints — the application pages stay on this computer. Use on a trusted network.
* **Built in**: webcam pan/tilt/zoom controls; Bluetooth heart-rate straps from the browser; imports of Apple Health
  export.xml, ARKit face CSV (Live Link Face), Pupil Labs gaze/fixations CSV, BVH motion capture, JSON-lines events.
* **Bridges** (`bridges/`, shipped as `extras/device-bridges`): ROS 2 (Stretch 3, TurtleBot 4, Unitree), Unitree SDK,
  Polar (heart rate + H10 ECG), Pupil Labs Neon, Tobii Glasses 3, GelSight Mini, Rokoko Studio Live, an iPhone ARKit
  sender (Swift) and a Meta glasses sender (Kotlin, with Meta's Wearables Device Access Toolkit). The client library
  is tested against QueryBook; the bridges follow each maker's SDK but have not been run on the real hardware yet.

| Device | Connection |
|---|---|
| Insta360 Link 2 Pro, Logitech MX Brio | built in (browser camera + PTZ) |
| iPhone 17 Pro | ARKit CSV import; Swift sender |
| Pixel 10 Pro | video import (Language Builder) |
| Ray-Ban Meta Gen 2, Meta Ray-Ban Display | Kotlin sender with Meta's toolkit |
| Unitree G1 EDU, Unitree Go2 EDU | `unitree_bridge.py` or `ros2_bridge.py` |
| Hello Robot Stretch 3, TurtleBot 4 | `ros2_bridge.py` |
| GelSight Mini | `gelsight_bridge.py` |
| Polar H10, Polar Verity Sense | built in (Bluetooth heart rate); `polar_bridge.py` for ECG |
| Apple Watch Ultra 3 | Apple Health export import |
| Rokoko Smartsuit Pro II | BVH import; `rokoko_bridge.py` live |
| Pupil Labs Neon | CSV import; `pupil_neon_bridge.py` live |
| Tobii Pro Glasses 3 | `tobii_bridge.py` (template) |
| DJI Mic 2, Rode Wireless PRO | recordings → Language Builder speech-to-text; transcript events |

## Master control (start and stop harvesting)

Top of the **Harvesting & shared facts** page, the same in all three applications (the switches live in the
shared database, so pressing Stop in one application stops all three):

* **▶ Start all harvesting** — master switch on, all three applications and every online harvester on;
  the engine gives the next turn at once.
* **■ Stop all harvesting** — master switch off: no application starts a harvest, and one already
  running stops after its current task (the rest of its turn is skipped and logged). "Run this team
  now" is refused until you start again.
* **Start selected / Stop selected** — tick applications and online harvesters. Start selected runs
  *only* the ticked ones (ticking a harvester also turns its application on); Stop selected stops the
  ticked ones and leaves the rest running.

From the command line: `python app.py harvest-engine stop` (all), `harvest-engine start`,
`harvest-engine start stem usda-foods` (only these), `harvest-engine stop language`.

## Online harvesters (`_core/qbonline.py`)

Approving a source makes it allowed; a harvester turns it into facts. Running now:

| Harvester | Application | Source | Facts |
|---|---|---|---|
| Countries | History & News | Wikidata (CC0) | capital, continent, ISO code — most-linked countries first |
| Cities and towns | History & News | Natural Earth (public domain) | country, region, coordinates, capital — largest first |
| FRUS volumes | History & News | Office of the Historian (US federal) | title, publication year, years covered (550+ volumes) |
| Met highlights | History & News | The Met Open Access (CC0) | artist, date, medium, culture, department |
| Programming languages | Math & Science | Wikidata | first appeared, designers, developers |
| Chemical compounds | Math & Science | Wikidata | formula, CAS number — most-referenced first |
| Species | Math & Science | NCBI Taxonomy (US federal) | common name, group — mammals, birds, reptiles, amphibians, fish, insects, plants, fungi |
| The world's languages | Language Builder | Wikidata | ISO 639-3 code, writing systems |

Each is a task in its application's plan, so the engine's rotation, the registry check, the harvest log
and the learner apply to it exactly as to the built-in tasks. Requests go one at a time with a pause
between calls to the same site and a named user agent; a site that answers "too many requests" fails
only that task for the turn (logged with why), and the cursor stays put. Switch off per application on
the Harvesting page, or set `QB_OFFLINE=1`. Self-tests never go online.

**Harvesters that need a free key** wait, idle, until the key is pasted on the Harvesting page (API keys —
admin passphrase required). Keys are kept in `<commons folder>/api-keys.json` (owner-only), never in the
database, its backups, the code or the logs; requests never put a key in an error message.

| Harvester | Application | Key | How to get the key |
|---|---|---|---|
| Smithsonian history & culture, science & technology (CC0 records only) | History & News, Math & Science | api.data.gov | form at api.data.gov/signup — shown at once; one key serves Smithsonian and USDA |
| Food composition per 100 g (USDA FoodData Central) | Math & Science | api.data.gov | (same key) |
| National Archives records online ("Unrestricted" only) | History & News | nara | email Catalog_API@nara.gov for a read-only v2 key |
| DPLA records by topic | History & News | dpla | **Request my DPLA key** on the page — DPLA emails it |
| Europeana records by topic | History & News | europeana | free Europeana account → My Profile → Manage API key |

**Engine.** One engine gives the three teams turns — language, STEM, history — so they never harvest at
once. Each running application asks every `schedule.tick_s` (30 s) whether it is its turn; the claim is
one transaction, so two applications can never both win. The turn goes to the highest score: +3 for an
application that has not harvested yet or harvests fast, extra for checks other applications are waiting
on (`rotation.check_weight`), minus `rotation.repeat_penalty` for the one that had the last turn. An
application whose turns found nothing new backs off 1, 4, 16 … minutes (up to `rotation.idle_backoff_max_s`),
which cuts volume once a source is exhausted. A turn that runs past `rotation.turn_timeout_s` is closed.

**Learning, never applied without you.** After each cycle the learning agent reads the harvest log and
may recommend: larger batches (≥ 90 % new facts at ≤ 10 s per task over 3 runs), smaller batches
(≤ 10 % new), pausing a task that failed 3 of its last 5 runs, classifying the licence of a source plans
keep asking for, or a higher check weight when checks wait too long. A recommendation is made once
(fingerprinted) and changes nothing until the **admin** approves it with the admin passphrase
(PBKDF2-SHA256, set on first use; only a salted hash is stored). Approving a restricted licence class
also needs an explicit "accept the restriction" tick. Every change — approved recommendation, source
decision, parameter — is a numbered **policy version** with who and why.

**Harvest log.** Every task — *harvested*, *blocked*, *failed* or *refreshed* — is logged with its
application, domain, source key, licence class, why it was harvested, items, new, merged, seconds,
engine turn and policy version. Entries are SHA-256 hash-chained (**Verify the chain** detects any later
edit) and appended after each cycle to `commons/archives/harvest-YYYY-MM.jsonl`. Each shared fact's
evidence points at the log entry that brought it in (`evidence.harvest_id`). Export as CSV from the page.

```
python app.py harvest-engine status        # rotation, recent turns, pending approvals
python app.py harvest-engine turn          # ask for one engine turn now
python app.py harvest-engine log 50        # the last 50 log entries
python app.py harvest-engine verify        # check the hash chain
python app.py harvest-engine review        # run the learning agent, list pending recommendations
python app.py harvest-admin set-pass       # set or change the admin passphrase
python app.py harvest-admin approve 3      # approve recommendation #3 (asks for the passphrase)
python app.py harvest-admin source KEY approved cc0
```

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
python tools/test_commons.py         # the shared database and the three teams, end to end (68 checks)
python language/app.py --selftest     # 186 checks
python stem/app.py --selftest         # 86 checks
python facts/app.py --selftest        # 44 checks
python tools/run_all_tests.py         # all of the above
```

## For developers

* `_core/qbcore.py` (database, backups, web server, old-store reader), `_core/qbcommons.py` (the
  Commons and the agent teams), `_core/qbharvest.py` (registry, engine, log, approvals, learner) and `_core/ui/qb.css`, `qb.js` are shared. Each application's team
  is its `harvest.py`. Each application carries its **own copy** so it can be shipped alone; after editing
  `_core/`, run `python tools/sync_core.py`. The self-tests fail if a copy differs from the master.
* `python tools/package.py` builds one zip per application in `dist/`.
* The web servers listen on 127.0.0.1 only and refuse requests from other sites.
