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
     Control Panel (one page for all three): START-CONTROL-PANEL-WINDOWS.bat / START-CONTROL-PANEL-MAC.command
       QueryBook Control Panel       http://127.0.0.1:8100/
     Each application opens in your browser and keeps its window open while you use it:
       Language Builder              http://127.0.0.1:8101/
       Math, Science & Engineering   http://127.0.0.1:8102/
       History & News                http://127.0.0.1:8103/
  4. Your data lives OUTSIDE these folders (~/QueryBook-Data/...), so installing a newer version over
     this one never touches it. To upgrade: close the applications, unzip the new version, start again.

WHAT'S NEW IN THIS RELEASE
  Campaign Manager (Control Panel 1.3.0) - Control Panel -> "Campaign manager"
    * Feed it a directive (Word, Markdown or text) and it designs an executable harvest campaign: waves T0 -> T30 ->
      specialized modeling, every task's camera views and takes as generation requests, the real anchor set, the expert
      reviewer, and a day-by-day schedule at the Google video tool's real daily budget. A scope guard holds back weapons,
      targeting and identifying real people, whatever a directive asks.
    * Ready on first start: the QueryBook Synthetic-Video Directive (122 tasks, 19 categories), refined by the focus
      directive "Market Need for Verifiable AI Answers" - aviation maintenance, energy and pharma procedures lead.
    * Focus directives: a document with a Sector table and a recommended first move re-ranks the open campaign
      ("focus tasks only" runs just the focus).
    * Assistant: walks you through what is missing and applies what you tell it ("I acknowledge the scope", "use the
      default reviewers", "15 requests a day", "exclude MED-07", "explain ROB-09"), every change audited. Optional: with an
      Anthropic key it also answers open questions with Claude - advisory only, it never changes or launches anything.
    * Compile writes one plan per wave for the exemplar generator; Launch (admin passphrase) hands a wave to the video tool.
  Harvesting that keeps going (all applications: STEM and History 1.14.0, Language 1.48.1)
    * Sites that ask us to slow down (Wikidata, NCBI: HTTP 429) are waited for, not failed; their tasks resume later and
      never lead to "pause this source" recommendations.
    * A turn held up by waiting sources gets a short pause, not the 1 minute -> 4 hour idle back-off that made STEM,
      History and Language seem to stop after a few seconds.
    * Turns follow each other within seconds while harvesting is under way; an application closed mid-turn no longer
      blocks the others for 15 minutes; the schedule restarts itself after any error.

  Harvesting (all applications: STEM and History 1.13.0, Control Panel 1.2.0)
    * Master switch: one ON/OFF button for all harvesting, at the top of the Harvesting page.
    * Harvest campaigns: name a selection of applications, online harvesters and Google tools, start and stop it together,
      and see its progress (new facts, exemplar takes) since it started.
    * Google tools: Gemini Omni, Veo, TTS, Nano Banana, drill texts and second-opinion transcripts - each switched on
      separately by the admin, used only for examples to learn from (never facts), run by the separate exemplar generator
      (extras/exemplar-generator), within a daily budget, on the paid tier.
    * Nine more open sources: battles, treaties, rivers, mountains, minerals, writing systems (Wikidata, CC0), earthquakes
      since 1900 (USGS), executive orders and proclamations (Federal Register), compound properties (PubChem).
    * Exemplars tab in the Control Panel: approve the best take of each item; start or stop the exemplar generator.
  Language Builder (1.47.0)
    * Speech motion library: Pamela's avatars now speak with her own recorded mouth movement, sound by sound, from her
      exemplar clips (Avatar studio -> Speech motion library to build one for another person). Teeth follow the jaw.
    * Lip-reading curriculum test (Visual Speech Engine): five stages, scored stage by stage.
  All four applications - the Self-Knowledge Layer (Control Panel 1.1.0, STEM and History 1.12.0, Language 1.46.1)
    * QueryBook describes itself accurately, with sources: ask "are you neuromorphic?", "do you improve yourself?" or
      "what is section 21?" and it answers built, partly built, specified (not yet built) or not planned - with the
      design-document sections and the program files that prove it. It checks every claim against its own code each
      time, and reports a contradiction instead of repeating a claim it cannot prove. No AI model.
    * Control Panel: new Self-knowledge tab (ask box, the twelve reasoning aspects, the eight-step process, every section,
      contradictions); the assistant answers questions about QueryBook itself. Every application: /api/self.
  Control Panel (new, 1.0.0) - one separate page to show and manage all three applications
    * Applications: running or not, version, health, harvest switch, facts, last harvest turn; Start / Stop / Open /
      Harvest now for each (it can start them for you).
    * Mass harvesting: start or stop all harvesting at once, or a selection of applications and online harvesters,
      and set every running application harvesting now.
    * Special targeting: topics, applications, harvesters and sources to concentrate on - first, or only - with a
      budget boost. Special filtering: words to leave out or require, a year range, domains, licence classes, with a
      dry run on the facts already shared. All three applications obey both from their next harvest turn.
    * Every function has a Diagnose button and a Clear button; every action goes to the audit trail (transparency);
      the panel monitors everything every 20 s and raises alerts that clear themselves when the cause ends.
    * Assistant: type plain requests - "stop all harvesting", "focus on volcanoes in history", "exclude football",
      "find Marie Curie", "any alerts?". It is rule-based (no AI model): it does only what it recognises, says what it
      changed and asks before stopping anything.
    * Target and filter changes need the admin passphrase once the admin has set one.
  Language Builder (1.46.0)
    * Mouth shape, measured edge by edge against her Gemini clip (the tooth-side lip edges found in the pixels, every
      frame): our opening was one oval scaled up and down; hers changes form with each sound. Full-body avatars now:
      - the opening narrows into the corners where the lips press (end taper 0.49 -> 0.42, hers 0.33);
      - rounded sounds (oh, oo, w, r, sh) lift the middle of the upper lip above the corners and drop the lower lip
        with it - a tall rounded opening, not a smile-lens (top-middle lift on rounded words 0.074 -> 0.113, hers 0.119);
      - the portrait's smile curve is taken out of the corners at rest (ends-up 0.024 -> 0.011, hers 0.015);
      - more of the teeth: longer, brighter upper teeth and the lower teeth on mid openings (teeth 4% -> 13% of the
        opening, dark 69% -> 51%; hers 23% / 30%); a lighter tongue;
      - overall the average opening shape is 2.5x closer to hers.
    * Delivery check: the pucker limit follows her own clip (she narrows 29% on "our") - 32% instead of 24%.
  Language Builder (1.45.0)
    * Calibration bench (Avatar studio): choose her original clip and its words; the app makes our face say the same
      words with the same voice and shows three columns - her original, our approved calibration, and a trial you set
      with sliders. Each has a level, same-scale mouth close-up with the tracked lip outline and her outline laid over
      ours, live width / opening / upper-lip numbers, the words, full / half / quarter speed, frame stepping, jump to the
      worst words, and Record (WebM, or MP4 through ffmpeg). Re-render the trial, compare the scores, then send it to the
      Quality Lab (the admin approves it there). New slider: rounding at rest.
    * Full-body avatars, tuned on the bench against her Gemini clip (same voice, same words, same tracker): the mouth
      no longer keeps the portrait's smile (14% too wide -> matches hers), open vowels and r no longer open 2-3x hers
      ("ah" 0.093 -> 0.051, hers 0.042), the lips no longer trail her by two frames, and the head no longer tilts and
      turns 4-5x as much as hers (tilt range 5.5 -> 1.7 deg, hers 1.1). Word-by-word distance from her 1.19 -> 0.89.
  Language Builder (1.44.0)
    * The upper lip moves with the words. Measured word by word against her two Gemini originals, our upper lip used to
      make under a tenth of each opening (hers: about a third) and sank on "ee" words. Now every sound has its own
      upper-lip lift (most on ee, i, eh and s; less on m, b, p), the upper lip flares up as the lips round, and its
      middle rises with the corners on a smile: lift 0.04 -> 0.09 (hers 0.08-0.10), share of the opening 0.07 -> 0.25.
  Language Builder (1.43.0)
    * Fix: on full-body avatars the background and the whole region above the face moved with no reason (up to a quarter
      of a face height). The person's outline is now found in the photo and everything outside it stays perfectly still;
      the head and hair move only with the head's own turn, never with the brows. Also fixed: a jump at the very first
      frame, small eye folds during blinks, and smears at the cheekbones.
    * Check delivery (under every talking face): every frame measured - background, forehead and head region, hair,
      jumps, lips, smears - with a timeline and a box on the picture for each problem, and a comparison with the
      person's own original clips.
    * Flag a problem: pause, drag a box around what is wrong, say why. Each flag keeps the exact moment and a picture;
      Avatar studio -> Flags re-checks them, records fixed / still wrong, and "Improve from flags" proposes a better
      calibration to the Quality Lab (the admin approves it).
    * Reference clips and Reproduce & compare: add the original creator's clips of the person speaking; the app makes
      her say the same words with the same voice, plays both side by side and compares them word by word.
      Pamela ships with her two Gemini speaking clips.
    * Upper lip arches up in the middle as the mouth opens (it lifted as a block); brows move with the voice all through
      speech, as in her original clips.
  Language Builder (1.42.0)
    * Fix: the lower lip's edge stayed straight (looking swollen) while the upper lip curved. The lower teeth and the
      tongue showed as a flat light band along the lower lip; now the lower teeth appear only on a wide-open vowel, small
      and shaded, the tongue sits lower and darker, and the lower lip's edge curves and has its own soft shadow.
    * Fix: exaggerated pucker. Rounding now narrows the mouth by up to ~18% (was ~27%) and no longer thickens the lips
      (was up to +24%); the lip opening tapers evenly to both corners; on full-body avatars the upper lip no longer lifts
      while the lips close or round.
  Language Builder (1.41.0)
    * Five new faces in the avatar library: Man - gym, Man - park, Man - street, Woman - braids, Woman - curls
      (AI-generated portraits supplied by the admin; already analysed; all pass the mouth quality checks).
  Language Builder (1.40.0), Math, Science & Engineering and History & News (1.11.0)
    * Obey the Control Panel's targeting and filtering; record their address for the panel; stop when the panel asks.
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
  Language Builder (1.39.0)
    * Lips: rounding words (you, two, true, shoe, food, w, r, sh, o) now pucker properly - the lips gather toward the
      middle (about 25-30% narrower) and grow fuller as they push forward. "Tree", "three", "true" round on the tr.
      The vowel of bird, her, girl, first is said with rounded lips; the short oo of book, put, look rounds lightly.
      The speaking smile relaxes while the lips round. Spread vowels (me, thee, see) keep their upward curl.
      Measured on 52 test words: lip-shape score 62 -> 100 (full body), 64 -> 99 (face).
    * Teeth: each tooth has its own form - light down its middle, a greyer biting edge, gaps and small notches
      between teeth; up to ~5 mm of tooth on a wide-open vowel.
    * Tongue: on wide-open vowels the top of the tongue shows - domed, moist, lit at the tip, with its middle groove.
  Language Builder (1.38.0)
    * Fix: the top of the head stayed still while the face nodded (the forehead stretched). Hair and skull now move
      with the face, up to the top of the picture.
    * Full body fixes from the first test: the head moves as one piece (no "paper face"), no chest/arm shear, gentler
      brows and lip lift (no worried frown or sneer), smaller teeth, close-ups never blurrier than the photo.
    * Moves can have several takes (Pamela's swimming has two); each avatar learns the person's body proportions
      from their standing footage and uses them to align new videos.
    * (all three apps) Self-improvement: the Engineer reads QueryBook's own code, log and activity record and
      proposes improvements - exact fixes or advice. Nothing changes without the admin; every approved fix is
      tested on a copy with the whole self-test first, backed up, and can be reverted. Agents tab -> 5.
    * Moves: a motion library for full-body avatars, from videos of the person. Pamela (track) ships with nine -
      turn around, arm swings, boxing, side kick, cartwheel, walk, high knee, water break, swimming - on buttons
      under the face and set off by their words in a script.
    * Full-length turnaround for Pamela (track avatar); turnarounds play at the person's own pace and finish even
      when the speech ends; full-length clips work (the face is found by zooming on the head).
    * Turnaround for full-body avatars: import a video of the person turning on the spot; she turns around on
      "Turn around" or when the text says "turn around". Pamela (stadium) ships with hers. Teeth show in the speaking smile.
    * Full-body avatars calibrated against a reference video of the same model: speaking-smile mouth (upper lip lifts,
      lower lip drops), stronger brows, real blinks, head turns and tilts with hair and torso following, camera cuts
      between wide and close shots (can be switched off). Fix: a streak beside the head on big head moves.
    * (all three apps) Agents tab: pick your agents (text, sound, video, live data, touch, body, any sensor),
      learn from best-in-class exemplars (mastery profile, 0-100 score, advice), and Open Claw agents, skills and
      tools taken in as knowledge - read, never run; model instructions quarantined. No LLM anywhere.
    * Full-body avatars: a second row under the faces. The whole figure breathes and sways while the face speaks.
      First model: Pamela (AI-generated): her head joins the face library, and she stands as three full-body avatars.
      Import your own with "full-body photos" ticked.
    * Talking face retuned against a Gemini reference reading (measured frame by frame): wider opening, jaw that
      swings like a hinge, stronger rounding/spreading, lip presses, lower teeth, smile, brows, nods.
    * Faster drawing: WebGL (graphics card) or 2D canvas, whichever is faster on the computer - smooth, full-rate video.
    * (all three apps) Keeps the computer awake while running; long work keeps the screen awake; the log marks
      every session and every sleep; the system's own logs (sleep, wake, unexpected shutdowns, power and screen-saver
      settings) are checked at start-up. Diagnostics -> Power, sleep and the log; Download the log.
    * Fix: the mouth kept still after 30 s of speech - lip sync now analyses the whole recording.
    * Play / pause and Download video (MP4) right under the talking face.
    * The whole face talks: cheeks, eyelids, brows, nose, and skin creases (forehead, frown lines, crow's feet,
      smile lines) that deepen and fade with the muscles.
    * Ingest example videos: NASA (public domain, with captions) and Wikimedia Commons clips are fetched, scanned for
      close-ups and learned from; a library of sources that show how talking should look.
    * Self-learning from real speakers: reference clips with their words teach the mouth shape of every sound, blink
      rate, head and brow movement; a motion graph links languages, words, sounds and emotions to measured movement.
      Fetch from Voice of America (40+ languages, public domain), US government, Wikimedia Commons, Internet Archive.
    * Self-learning loop: test after test, scored and calibrated automatically until the admin approves.
    * Quality lab (Speech -> Quality lab): each avatar test is recorded as a video with every word, measured
      against human reference clips (your webcam or clips you may use), scored, and used to calibrate the next test.
      Only the admin approves a calibration; all faces then speak with it.
    * Fix: no "gum" flaps - the line where the lips meet is found in the photo (the crease between the lips)
      when the face tracker puts it on the lip itself.
    * Both lips curve open (upper lip arches, lower lip drops) - the oval of a real mouth.
    * Aesthetic guardrail: realistic inside of the mouth (colours from the person's own lips and eye whites, a row of
      upper teeth that follows the lip, resting tongue, no gums, smooth edges), checked on the rendered pixels.
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
