QUERYBOOK HISTORY & NEWS
========================

Facts from sources written by people - every fact shows where it came from.
  - Each fact has its sources: books, encyclopedias, newspapers, news agencies, government
    records, archives, museums. Web addresses of AI chat and AI-writing services are refused.
  - The same fact entered twice is kept once, with all its sources.
  - Facts that disagree (two birth dates, two capitals) are both kept and marked DISPUTED.
  - Dates: 1215, 15 June 1215, 44 BC, c. 1200, 1990s, 12th century. Timeline and "on this day".
  - News: add RSS/Atom feeds of outlets you trust. Headlines are kept as what the outlet
    reported until you choose "Add as fact". Feeds are only fetched when you press Fetch.
  - Import from a spreadsheet (CSV) - every line is checked first; nothing is added if any
    line has a problem. Export everything to CSV at any time.

HOW TO START
  Windows : double-click START-WINDOWS.bat
  Mac     : double-click START-MAC.command (first time: right-click -> Open -> Open)
  Other   : python3 app.py
It opens in your web browser at http://127.0.0.1:8103/
Leave the small window open while you use it. Close it to stop.
You need Python 3.8 or newer (free from https://www.python.org/downloads/). Nothing else.

WHERE YOUR DATA IS
  ~/QueryBook-Data/facts   (on Windows: C:\Users\<you>\QueryBook-Data\facts)
  (one database file plus a "backups" folder). It is outside this program folder, so replacing
  or updating the program never touches it. To keep the data somewhere else, e.g. a USB drive:
      python app.py set-data E:\QB-Data\facts

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
