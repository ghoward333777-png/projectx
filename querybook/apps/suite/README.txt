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
    * Devices tab and device API: register cameras, phones, smart glasses, robots, wearables, motion suits,
      eye trackers and microphones; each gets its own key and sends observations (not recordings) through one
      documented API (OpenAPI). Consent is required for devices that record people, body signals or location.
      Built in: webcam pan/tilt/zoom, Bluetooth heart-rate straps, imports from Apple Health, iPhone ARKit
      (Live Link Face), Pupil Labs, BVH motion capture. Bridge programs for robots (ROS 2, Unitree), Polar,
      Pupil Labs, Tobii, GelSight, Rokoko, iPhone and Meta glasses are in extras/device-bridges.
    * Master control (top of the Harvesting page): Start all / Stop all harvesting, or tick
      applications and online harvesters and Start selected / Stop selected. One switch for all three
      applications; a running harvest stops after its current task.
    * Harvesting engine + policy registry (tab "Harvesting & shared facts"). One engine takes turns
      between language, STEM and history, gives the turn to whichever has the most to gain, and backs
      off a source that stops producing new facts. Every source has a licence class; only sources that
      put no restriction on QueryBook (public domain, CC0, bare facts, US federal, computed, your own
      cited facts) are harvested — MUSE (non-commercial) and news headlines (copyrighted) are blocked.
      Every task is logged with its source and why, hash-chained and archived monthly
      (commons/archives). A learning agent recommends faster or leaner settings; nothing changes until
      you approve it with your admin passphrase (set it on first use).
    * 46 researched sources are in the registry — chemistry, architecture, geography, programming,
      mathematics, civil engineering, quantum computing, and education and data sites across all of
      language, STEM and history: 30 unrestricted ones wait for your approval, 16 restricted ones are
      blocked with the reason.
    * Your approval of 19 October is applied: 28 sources approved (facts only, never their wording),
      2 held back because their copyright cannot be checked by a program (FSI courses, FHWA reports).
    * Online harvesters now collect facts from the approved sources: countries (Wikidata), cities
      (Natural Earth), US diplomatic history volumes (FRUS), the Met's highlighted artworks, programming
      languages and chemical compounds (Wikidata), species (NCBI Taxonomy) and the world's languages
      (Wikidata). They need an internet connection; switch them off on the Harvesting page.
    * Six more harvesters wait for free API keys (Harvesting page -> API keys): Smithsonian (two),
      USDA food composition, National Archives, DPLA and Europeana. The page explains how to get each
      key; "Request my DPLA key" asks DPLA to email you one. Keys stay on your computer only.
    * Shared facts & agents: one shared fact database (the Commons, ~/QueryBook-Data/commons) used by
      all three. Each application has a team of four agents — Strategist, Planner, Harvester, Curator —
      that devise a harvest strategy, plan it, carry it out and save and manage the facts, when the
      engine gives them their turn, or on demand. The applications check each other's facts (lifespans, dates, dictionary
      words) and keep every answer with its evidence and reasoning. Tab: "Harvesting & shared facts".
  Language Builder (1.23.0)
    * Lips move as solid bands: the upper lip keeps its width and thickness, the lower lip rides the jaw smoothly,
      rounding moves the corners, lips never cross, blinks close cleanly.
    * Movement quality control on every avatar (24 poses checked against human limits, folds, crossing lips) with
      per-face correction; results shown in the studio and library ("Check movement of every face").
    * Mouth fit: every face's talking mouth is sized and shaped from its own anatomy (mouth width, lips, iris scale);
      the opening follows the person's own lip outline. The studio shows the measurements.
    * Natural talking mouth: lens-shaped opening (no square slot), widening limited to ~10%, teeth that follow
      the lips, and no skin stretched across the open mouth on any face.
    * Speak is now 4 numbered steps: 1 choose the face (big preview + every face), 2 voice, 3 text, 4 Speak.
      The chosen face always does the speaking (fixed: it used to fall back to the plain face).
    * Avatar studio: opens on a face; click any face in the strip and the speech carries on with that face;
      "Every face in turn" plays the speech while each face takes a turn.
    * Choose a face: Speech -> Speak shows thumbnails of every avatar (plus 2D and 3D/VR); click one and that
      face speaks. 19 AI-generated starter avatars come installed and ready. Full-length photos are cropped to
      the face automatically when analysed.
    * Avatar library (Speech -> Avatars): import portraits (files, a folder or a .zip); each becomes a talking
      avatar measured at 478 face points with depth and animated with all 52 ARKit face channels — lips, jaw,
      cheeks, nose, eyelids, gaze, brows and tongue — with natural co-articulation, blinks, brow raises and 3D head
      motion. Studio with expression presets, a slider for each of the 52 channels and a 52-channel CSV export.
      AI-generated portraits need a "no real person" confirmation; real people need their consent.
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
  Math, Science & Engineering (1.8.0) and History & News (1.8.0)
    * The harvesting engine, registry and approvals (see above).

EXTRAS
  extras/device-bridges/  — small programs that connect robots, eye trackers, touch sensors, motion suits, phones and
  smart glasses to QueryBook's device API. See its README.md.
  extras/visual-speech-engine-stage2/  — the trainable (PyTorch) version of the Visual Speech Engine for
  developers with GPUs and licensed data. Not needed to run QueryBook; see its README.md.
