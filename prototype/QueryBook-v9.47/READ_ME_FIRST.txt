QUERYBOOK — HOW TO START
========================

ONE CLICK. That's the whole thing:

    Windows :  double-click   START_QUERYBOOK.bat
    Mac     :  double-click   START-MAC.command
               (first time: right-click -> Open -> Open to clear the prompt)

It will:
  • find Python for you (and try to install it automatically if it's missing),
  • run a quick self-check,
  • start the app and open it in your browser at  http://127.0.0.1:8099/dashboard

Leave the little window open while you use QueryBook. Close it to stop.


THE FIRST TIME — WHERE IS YOUR DATA?
------------------------------------
On the very first launch QueryBook asks ONE question in that window:

    QueryBook — WHERE IS YOUR DATA?
    Stores found (most data first):
      [1] E:\QB\mystore        1,200,000 facts · language model 6,000 words
      [2] C:\Users\you\.querybook\store     0 facts
    Store [E:\QB\mystore]:

  • Type the NUMBER of your store (e.g. the one on your external drive), or
  • type the FULL PATH to the folder that holds  blocks\ , index.sqlite ,
    language_model.json , or
  • just press ENTER to accept the suggested one, or
  • type  scan  to search every drive.

Your facts and learned languages live in that folder. Nothing is moved or
erased — QueryBook just reads and writes the one you pick.

After you choose, IT WON'T ASK AGAIN FOR 50 LAUNCHES. It remembers your choice
in  (your home folder)\.querybook\config.json .

To change it any time:
    Windows :  py qb_api.py configure        (or  python qb_api.py configure)
    Mac     :  python3 qb_api.py configure

If your external drive is unplugged, QueryBook will NOT quietly start blank —
it tells you and asks again so your data is never lost.


IF SOMETHING LOOKS WRONG — SELF-DIAGNOSTIC
------------------------------------------
The one-click starter runs a self-check for you every time. To run it on its own:

    Windows :  double-click   CHECK_QUERYBOOK.bat
    Mac     :  double-click   CHECK-QUERYBOOK.command

It prints a plain-English report and marks each item:
    [OK]        working
    [OPTIONAL]  safe to ignore (e.g. offline speech not installed)
    [PROBLEM]   needs fixing — it tells you how

Only [PROBLEM] items matter. [OPTIONAL] items never stop the app from running.
It also shows where your data is, how many facts and learned words it holds,
and whether any auto-recovery safeguards have fired.


YOUR DATA IS PROTECTED
----------------------
  • Your store is pinned to the folder you chose and used on every launch, so an
    upgrade never opens a blank library by mistake.
  • The learned-language model is written safely (atomic writes + a backup) and
    can never be reset to zero by a crash, a full disk, or two things saving at
    once — if a file is ever damaged it is recovered from the backup.
  • Lost a store? Run  qb_find_store  (FIND-STATION-WINDOWS.bat /
    FIND-STATION-MAC.command) — it scans every drive, read-only, and shows where
    your data is.


AUTOMATIC BACKUPS — NO DATA LOSS, EVER
--------------------------------------
Every time QueryBook starts it makes a SECOND copy of your whole library in
another folder on your drive, and syncs any other backup locations you add.
It is safe by design:

  • If your main store is ever behind a backup (for example it got reset), the
    main store is RESTORED from the richest copy BEFORE the app opens.
  • A copy that already has data is never overwritten blindly — its current
    state is snapshotted aside first, so nothing is ever erased.
  • The SQLite index is copied with the live-safe online-backup method, so the
    copy is consistent even while QueryBook is running.

By default the second copy goes to  <your store>_backup2  on the same drive.
To choose where copies go — a different folder, and/or a Google Drive folder
that your Drive app then uploads for you (no API keys needed):

    Windows :  py qb_api.py backup-config
    Mac     :  python3 qb_api.py backup-config

Off-site cloud copies to Bunny.net and OVH Cloud are also supported. Turn them
on by editing the LOCAL, private file  (home)\.querybook\cloud.json  (created by
backup-config) and setting  "enabled": true  with your storage keys. That file
stays on your machine and is never shared or committed.

Run a full backup on demand any time:

    Windows :  py qb_api.py backup
    Mac     :  python3 qb_api.py backup

The System Monitor page shows every backup location, the last sync time, and a
"Back up now" button.


HOURLY EMAIL ALERTS TO A SYS ADMIN
----------------------------------
QueryBook can email a health digest on a schedule (hourly by default):
FAIL ALERTS (self-test failures, blocked/errored agents, backup errors),
ERROR CODES (error/warning log entries), and the APPLICATION LOG.

Set it up (one time):
    Windows :  py qb_api.py mail-config
    Mac     :  python3 qb_api.py mail-config

It asks for the recipient (default ghowardbiz777@gmail.com), the SMTP server,
the sending account, and a password. For Gmail, create an APP PASSWORD at
Google Account -> Security -> App passwords and use host smtp.gmail.com port 587.
Credentials are saved in a LOCAL, private file  (home)\.querybook\mail.json
(never shared, never committed). Then restart QueryBook.

Send a test immediately:
    py qb_api.py mail-test        (Mac: python3 qb_api.py mail-test)

You can also turn it on/off and send a test from the System Monitor page
("Email alerts to the sys admin" card).


NEED PYTHON MANUALLY?
---------------------
If auto-install didn't work: get Python from https://www.python.org/downloads/
On Windows, TICK "Add Python to PATH" during setup. Then start QueryBook again.
