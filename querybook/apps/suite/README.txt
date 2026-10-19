QUERYBOOK — the three applications in one installer
===================================================

INSTALL
  1. Unzip this file anywhere (Desktop, Documents, a USB drive).
  2. Python 3.8 or newer is needed (https://www.python.org/downloads/ — on Windows tick
     "Add python.exe to PATH"). Nothing else to install: standard Python only.
  3. Start:
       Windows: double-click START-ALL-WINDOWS.bat     (or START-WINDOWS.bat inside one application's folder)
       Mac:     double-click START-ALL-MAC.command     (first time: right-click -> Open -> Open)
       Any:     python app.py   inside an application's folder
     Each application opens in your browser and keeps its window open while you use it:
       Language Builder              http://127.0.0.1:8101/
       Math, Science & Engineering   http://127.0.0.1:8102/
       History & News                http://127.0.0.1:8103/
  4. Your data lives OUTSIDE these folders (~/QueryBook-Data/...), so installing a newer version over
     this one never touches it. To upgrade: close the applications, unzip the new version, start again.

WHAT'S NEW IN THIS RELEASE
  All three applications
    * Harvesting engine + policy registry (tab "Harvesting & shared facts"). One engine takes turns
      between language, STEM and history, gives the turn to whichever has the most to gain, and backs
      off a source that stops producing new facts. Every source has a licence class; only sources that
      put no restriction on QueryBook (public domain, CC0, bare facts, US federal, computed, your own
      cited facts) are harvested — MUSE (non-commercial) and news headlines (copyrighted) are blocked.
      Every task is logged with its source and why, hash-chained and archived monthly
      (commons/archives). A learning agent recommends faster or leaner settings; nothing changes until
      you approve it with your admin passphrase (set it on first use).
    * Shared facts & agents: one shared fact database (the Commons, ~/QueryBook-Data/commons) used by
      all three. Each application has a team of four agents — Strategist, Planner, Harvester, Curator —
      that devise a harvest strategy, plan it, carry it out and save and manage the facts, when the
      engine gives them their turn, or on demand. The applications check each other's facts (lifespans, dates, dictionary
      words) and keep every answer with its evidence and reasoning. Tab: "Harvesting & shared facts".
  Language Builder (1.16.0)
    * Visual Speech Engine (Speech -> Face & video): full-face lip sync from words + a recording
      (coarticulation, jaw, brows, head nods, blinks, gaze, emotion), ARKit blendshape export and a
      preview face; a new lip reader (soft scores for 15 mouth shapes + word decoding) shown next to the
      old one in "Analyse video"; face analysis (head pose, camera steadiness, lighting, same-face check);
      a benchmark button that measures both lip readers.
    * Object scan (Face & video): recognizes 80 kinds of everyday object in the camera, a shared screen or
      a video file, follows them, zooms on one (record the enlarged view for lip-reading — consent box
      required for people), saves what was seen as numbers only, and answers questions: "what is this in
      Spanish?", "when did I last see a cup?", "how many people did I see today?".
    * Speech-to-Text for MP3 and other audio files of any length, live captions while a file plays,
      live captions from the microphone.
  Math, Science & Engineering (1.4.0) and History & News (1.4.0)
    * The harvesting engine, registry and approvals (see above).

EXTRAS
  extras/visual-speech-engine-stage2/  — the trainable (PyTorch) version of the Visual Speech Engine for
  developers with GPUs and licensed data. Not needed to run QueryBook; see its README.md.
