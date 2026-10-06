QUERYBOOK UFCS-FQL LAB - HOW TO START (Windows)
================================================

EASIEST WAY - just double-click:

    START_LAB.bat

That's it. It will:
  - on the FIRST run only, download a private copy of PHP, ffmpeg and zstd
    into this folder's "runtime" subfolder (about 235 MB, a few minutes),
  - start the lab,
  - open it in your browser at  http://127.0.0.1:8091/

Leave the little black window open while you use the lab. Close it to stop.
After the first run it starts in a few seconds and works offline.


IF SOMETHING LOOKS WRONG
------------------------
Double-click:

    CHECK_LAB.bat

It prints a plain-English report and marks each item as:
    [OK]        working
    [OPTIONAL]  safe to ignore
    [PROBLEM]   needs fixing - it tells you how

Only [PROBLEM] items matter.


NEED PYTHON?
------------
If the launcher says Python is missing: install it from
https://www.python.org/downloads/ and TICK "Add Python to PATH" during setup.
Then double-click START_LAB.bat again.


NO ROOM OR SLOW INTERNET?
-------------------------
Skip the 200 MB video download (the lab runs, video features stay off):
open a Command Prompt in this folder and run

    py qb_lab.py --no-video


NOTHING IS INSTALLED SYSTEM-WIDE
--------------------------------
Everything lives inside this folder. To remove the lab, delete the folder.
Every download is checked against its published SHA-256 fingerprint first.
