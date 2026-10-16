QueryBook Language Builder
==========================
Builds English first, then 16 other European languages, by itself - phonics and sub-language
first, no AI model. Start it (START-WINDOWS.bat / START-MAC.command / python app.py): the first
time, the build starts automatically (about 2 minutes) and the Build page shows every step.

  python app.py build      build in this window (build --again to rebuild)
  python app.py verify     proof for third parties: rebuild from nothing in a sealed store with the
                           network blocked; prints a SHA-256 fingerprint anyone can reproduce

Previous notes
--------------
QUERYBOOK LANGUAGE & SPEECH
===========================

Learn words in 17 languages: English first, then Spanish, French, German, Italian, Portuguese,
Dutch, Swedish, Danish, Norwegian, Finnish, Polish, Czech, Greek, Romanian, Hungarian, Catalan.
  - Choose "I speak" (your own language) and the language to learn. English can be learned
    from any of the others; other pairs are linked through English.
  - New words arrive a few each day, most common first (your own words first of all).
  - Words come back for review after 1, 2, 4, 8, 16, 32 and 64 days; a miss brings a word back today.
  - Practise with flashcards, multiple choice, typing, listening (write what you hear) and speaking.
  - Look words up in both directions; English definitions from Webster's 1913 dictionary.
  - Answers are checked by rule (accents forgiven with a reminder), never by an AI model.

SPEECH
  Listening uses your computer's own voices through the browser. To add a voice:
    Windows: Settings -> Time & language -> Speech -> Add voices
    Mac: System Settings -> Accessibility -> Spoken Content -> System voice -> Manage voices
  If a language has no voice, the application can use espeak-ng instead: install it, or copy
  the "espeak" folder from the old QueryBook into this folder.
  Speaking practice uses your browser's speech recognition (Chrome, Edge or Safari). In Chrome
  and Edge the recording is processed online by the browser maker.

WORD LISTS
  Translations: MUSE bilingual dictionaries (Facebook AI Research), CC BY-NC 4.0 - demonstration
  data for non-commercial use; replace before any commercial release.
  Definitions and word order: Webster's Unabridged Dictionary (1913), public domain.
  Translations are lower case (German nouns are normally capitalized). Add corrections under
  "My words".

HOW TO START
  Windows : double-click START-WINDOWS.bat
  Mac     : double-click START-MAC.command (first time: right-click -> Open -> Open)
  Other   : python3 app.py
It opens in your web browser at http://127.0.0.1:8101/
Leave the small window open while you use it. Close it to stop.
You need Python 3.8 or newer (free from https://www.python.org/downloads/). Nothing else.

WHERE YOUR DATA IS
  ~/QueryBook-Data/language   (on Windows: C:\Users\<you>\QueryBook-Data\language)
  (one database file plus a "backups" folder). It is outside this program folder, so replacing
  or updating the program never touches it. To keep the data somewhere else, e.g. a USB drive:
      python app.py set-data E:\QB-Data\language

SAFETY
  - Every change is saved completely or not at all, even if the computer crashes.
  - The database is checked each time the application starts. If it is ever damaged, the
    application will not write to it and shows a red notice.
  - Backups are made automatically (the newest 10 are kept). To restore one, close the
    application and run:   python app.py restore      (lists them)
                           python app.py restore 1    (restores the newest)
  - Importing from the old QueryBook only READS the old store. It never changes it.

DIAGNOSTICS AND MONITORING
  The Diagnostics page shows the application's own health checks (run when it starts and every
  hour) and can run the full self-test. From the command line: python app.py diagnose
  The monitoring connection sends these health reports to the developers' GitHub repository,
  so problems can be fixed from there: at once when something fails, plus a daily check-in.
  Reports never contain your facts, words, answers, your name or your folders. To switch it on,
  follow "How to make the token" on the Diagnostics page (a GitHub token with Issues access only).

CHECK THAT EVERYTHING WORKS
      python app.py --selftest
