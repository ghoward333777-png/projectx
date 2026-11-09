QUERYBOOK MATH, SCIENCE & ENGINEERING
=====================================

Answers that are computed, never guessed.
  - Calculate exactly: 0.1 + 0.2 is exactly 3/10; 2^100 and 25! in full; fractions, roots,
    trigonometry (degrees or radians), logarithms, primes, factorization, combinations.
  - Convert units with the legal definitions (an inch is exactly 2.54 cm). Units of different
    kinds are refused: "5 kg to m" is an error, not a guess.
  - Solve 35 science and engineering formulas for any quantity, entering values with units
    (60 mph, 1 atm, 20 degC).
  - Physical constants (CODATA 2018), all 118 elements (IUPAC atomic weights), molar masses.
  - Save answers; "Re-check all" computes every saved answer again and marks any difference.
  Answers that cannot be exact are marked with the approximately-equal sign.

HOW TO START
  Windows : double-click START-WINDOWS.bat
  Mac     : double-click START-MAC.command (first time: right-click -> Open -> Open)
  Other   : python3 app.py
It opens in your web browser at http://127.0.0.1:8102/
Leave the small window open while you use it. Close it to stop.
You need Python 3.8 or newer (free from https://www.python.org/downloads/). Nothing else.

WHERE YOUR DATA IS
  ~/QueryBook-Data/stem   (on Windows: C:\Users\<you>\QueryBook-Data\stem)
  (one database file plus a "backups" folder). It is outside this program folder, so replacing
  or updating the program never touches it. To keep the data somewhere else, e.g. a USB drive:
      python app.py set-data E:\QB-Data\stem

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
