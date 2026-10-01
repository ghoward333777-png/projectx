QueryBook — complete package
=============================

You have Python installed, so this is a two-step, no-questions setup.

WINDOWS
-------
1. Plug in your external drive.
2. Unzip this folder anywhere (e.g. your Desktop).
3. Double-click  START-WINDOWS.bat
4. It lists your drives and asks where to save. Type the drive letter
   of your external drive (for example:  E ) and press Enter.

That's it. Your browser opens the QueryBook dashboard. A small black
"server" window also opens — leave it open while QueryBook runs; close
it to stop. Next time it remembers your drive — just press Enter.

MAC
---
1. Plug in your external drive.
2. Unzip this folder anywhere.
3. Double-click  START-MAC.command
   (First time only: if macOS blocks it, right-click the file -> Open ->
    click "Open". You only do this once.)
4. It lists your mounted drives and asks where to save. Type the number
   next to your external drive and press Enter.

Next time it remembers your drive — just press Enter.


MONITOR THE STATION FROM ANOTHER DEVICE  (no static IP, nothing to type)
-----------------------------------------------------------------------
You develop on one device and the station learns on another. To watch the
station from your dev device, you do NOT build or type any URL:

  * On the STATION: when it starts, its black server window now prints the
    exact, complete links to open the Monitor — e.g.
        http://192.168.1.23:8090/monitor      (your LAN)
        http://100.x.x.x:8090/monitor         (Tailscale, if installed)
    The Monitor page itself also shows these under "Open this station on
    another device" with copy buttons.

  * On your DEV device: double-click  FIND-STATION-WINDOWS.bat  (or
    FIND-STATION-MAC.command). It listens on your network and prints the
    exact link to click — it finds the station automatically. No IP, no
    static address, no URL building. (Equivalent command: python qb_api.py
    discover.) Both devices must be on the same network (LAN / hotspot /
    Tailscale).

For password-protected remote access over the internet, use the
START-REMOTE launchers (they set a password and bind to all interfaces).


USING IT
--------
On the dashboard:
  * Domain selector      choose which domain to harvest (mathematics,
                         geometry, arithmetic) — next to "Start harvest".
  * "Start harvest"      collect a batch of facts in the chosen domain.
  * "Run 24x7"           collect continuously until you press Stop.
  * "24x7 Awake: OFF"    click to turn ON — keeps the computer from going
                         to sleep in ANY mode (harvesting, paused, or idle)
                         until you turn it off. It stays on across restarts.

Speed (new):
  * Fastest harvesting     at startup, type C (Windows) or i (Mac) to save on the
                           INTERNAL drive — far faster than USB. Copy the store
                           folder to an external drive later; it is just files.
  * Drive Offload          Console panel: harvest on the internal drive while the
                           app copies the store to your external/USB drive IN
                           PARALLEL, so the slow drive never bottlenecks harvesting.
                           The external copy is a complete, usable store.
  * Harvest Meter          Console panel: live facts/sec (average, live, peak),
                           elapsed time, and per-Fact-Unit creation time — metered
                           at any point in the collection.
  * I/O tuned              fast compression (level 1) and no per-batch fsync remove
                           the external-drive write stall; larger write batches.
                           (Set QB_GZIP_LEVEL to raise compression if you prefer.)

Reliability (new):
  * Store Health card    self-test, counters, a per-domain breakdown, and any
                         agents needing attention — refreshes on its own.
  * Self-heal            an agent that hits a transient error auto-restarts with
                         backoff (up to 6 tries); roadmap agents are left alone.
  * Per-domain counts    each agent and the Domain Navigator show the facts THAT
                         domain contributed, not the whole-store total.
  * "Clear stopped / errored"  one click removes finished/errored agents.

Top menu:
  * Language Lab   teach QueryBook English from scratch. Paste text, fetch one or
                   more phonics/grammar pages, OR load text files from your
                   computer; it learns the STRUCTURE of English (letters, sounds,
                   syllables, word patterns) with no LLM and stores every
                   measurement as a Fact Unit. Watch the four Transition Gate
                   thresholds fill in, and see the Learning-progress chart plot
                   them over time.

                   PHASE 2 — SEMANTIC GROUNDING (NEW, and NO LLM):
                   Once Phase 1 has learned words, click "Start Phase 2 —
                   dictionary + store grounding". It attaches MEANING from two
                   sources QueryBook can point to and audit:
                     (a) a bundled PUBLIC-DOMAIN dictionary (Webster's 1913) —
                         writes  english word "x" · means · <definition>, and
                     (b) self-grounding — links each word to the verified Fact
                         Units it already appears in in your store.
                   It is fully deterministic: no internet, no API key, no LLM.
                   Every meaning carries a real source you can check. (LLMs are
                   deliberately locked out of Phase 2 — a live API test can prove
                   a connection works but never that a meaning is TRUE. A future
                   "suggestor" mode may propose meanings that are accepted only
                   when they agree with the dictionary.)
                   (Phases 3-4 — multilingual, speech — remain roadmap and refuse
                   rather than fabricate; the page says so plainly.)
  * Guide          the full online user guide for every feature.
  * Chat           ask questions; get cited answers or an honest "UNKNOWN".

Facts are saved on the external drive you choose at startup, e.g.:
  Windows:  E:\QueryBook\store
  Mac:      /Volumes/YourDrive/QueryBook/store

Your choice is remembered in the file  querybook_store.txt  next to the
launcher, so you only pick once (press Enter to reuse it next time).

CHANGING THE DRIVE LATER
------------------------
Just run the launcher again and type a different drive letter (Windows)
or number (Mac). If the drive you used before is unplugged, it will tell
you and ask again.


CONNECTING CLAUDE (ANTHROPIC) - OPTIONAL
-----------------------------------------
QueryBook harvests facts AND learns English (Phases 1 and 2) on its own with
no API key. An LLM is only needed for the smarter chat/extraction layer -
never for language learning. To use Claude for chat:

1. Set your key once, in the SAME window before launching:
     Windows:  set ANTHROPIC_API_KEY=your-key-here
     Mac:      export ANTHROPIC_API_KEY=your-key-here
2. On the dashboard, in "LLM Providers", use "Quick add - Claude (Anthropic)".
   Pick a model and click "Add Claude":
     Haiku 4.5   - fast & cheap (default; best for harvesting)
     Sonnet 5    - balanced
     Opus 4.8 / Opus 5 / Opus 5.5 - high quality
     Fable 5.1   - most capable
   To switch models later, pick a different one and click "Add Claude" again.

   You can also PASTE your key straight into the key box on that card; it is
   stored only in your local store folder and never shown back in the page.

3. Press "Test" next to the provider. It makes ONE live API call and tells you
   exactly what happened: "Working", or the precise reason it is blocked
   (bad key, no credits, wrong model name, or network). No more guessing why
   Phase 2 will not start.

IMPORTANT - API KEY vs claude.ai SUBSCRIPTION:
Phase 2 (and the smart chat layer) use the Anthropic *API*, which needs an
API key from console.anthropic.com that starts with "sk-ant-", with billing/
credits set up under Plans & Billing. A claude.ai chat subscription (Pro /
Team, or a "Claude Haiku" chat plan) lets you chat at claude.ai but does NOT
work as an API key here. If Test says "bad key" or "no credits", that is the
usual cause.

Base URL is https://api.anthropic.com/v1. The key is read from the
ANTHROPIC_API_KEY environment variable, or from the key you paste into the
dashboard (stored locally in your store folder, never echoed back).


IF THE SCREEN GOES BLACK AND YOU THINK IT PAUSED
------------------------------------------------
QueryBook now keeps a heartbeat log so you can SEE what happened:
     <your store folder>\keepawake.log
Open it. If you see a line like
     *** SLEEP DETECTED: process frozen for ... ***
then the PC actually slept. Turn on "24x7 Awake" on the dashboard, and/or
set Windows Sleep to "Never" (Settings -> System -> Power).
If there is NO such line, QueryBook kept running fine and only the screen
turned off — nothing was lost.


WHAT'S IN THIS FOLDER
---------------------
START-WINDOWS.bat / START-MAC.command   the launchers (double-click these)
qb_api.py                               the local server + dashboard
ufcs_store.py                           the fact store engine
qb_agents.py                            24x7 background agents
qb_keepawake.py                         keep-awake + sleep watchdog
qb_chat.py                              grounded chat answering
qb_selftest.py                          quality-control self-tests (run at startup)
qb_web_harvest.py                       optional web harvesting
qb_language.py                          Language Lab engine (learn English structure)
dashboard.html / chat.html / console.html   the pages
language.html                           the Language Lab page
guide.html                              the online user guide

Nothing here needs the internet, an account, or an API key. Everything
runs locally on your own machine.
