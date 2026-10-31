QUERYBOOK VIDEO STUDIO 1.0.0
============================
A separate program that makes finished videos: shots in, one checked video out.

START
  Windows: double-click START-WINDOWS.bat      Mac: START-MAC.command      Any: python app.py
  Opens http://127.0.0.1:8104/ . Needs Python 3.8+ and ffmpeg (https://ffmpeg.org/download.html) on PATH.
  Start Language Builder too (START-ALL starts every program): voices, pronunciation, narrators and lip-sync come from it.

SHOTS
  Action    a common human action (walk-toward, sit-down, wave-hello, ...). A stored clip is reused and re-shaped here in
            seconds; an action with no stored clip is generated once by the video model (Settings: Gemini key; Language
            Builder's Google setup next door is used if present) and stored. Optional voice-over, spoken by Language Builder.
  Narrator  an author persona from Language Builder saying a text, lip-synced by HeyGen, D-ID or a local lip-sync model
            (set up in Language Builder, with the narrator's recorded consent). Stored for reuse.

RESULT
  Joins with in-between frames where the ends match, optional 30/60 fps and upscaling, captions (.srt) from the measured
  word timings, sound laid under each shot. Saved in the data folder's outputs\ with a report of every check.

LIBRARY
  Add your own footage of an action (Clip library tab) — only footage you may use, with consent stated.

python app.py --selftest   runs the self-test (a stand-in Language Builder; touches nothing real).
