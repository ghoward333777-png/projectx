QUERYBOOK — HOW TO START (Windows)
===================================

EASIEST WAY — just double-click:

    START_QUERYBOOK.bat

That's it. It will:
  • find your existing data automatically (including a library under D:\QB),
  • start the app,
  • open it in your browser at  http://127.0.0.1:8099/

Leave the little black window open while you use QueryBook. Close it to stop.


IF SOMETHING LOOKS WRONG
------------------------
Double-click:

    CHECK_QUERYBOOK.bat

It prints a plain-English report and marks each item as:
    [OK]        working
    [OPTIONAL]  safe to ignore (e.g. offline speech not installed)
    [PROBLEM]   needs fixing — it tells you how

Only [PROBLEM] items matter. [OPTIONAL] items never stop the app from running.


YOUR DATA NEVER MOVES
---------------------
Your facts and learned languages are kept in ONE fixed folder and every
version of QueryBook uses the same one, so upgrading never loses anything.

  • If you kept data under D:\QB, the launcher finds and uses it automatically.
  • Otherwise it uses:  C:\Users\<you>\.querybook\store
  • To force a specific folder once (so every future version uses it), open a
    Command Prompt in this folder and run, for example:

        setx QB_DATA_DIR "D:\QB\mystore"

    Then just double-click START_QUERYBOOK.bat as usual.


NEED PYTHON?
------------
If the launcher says Python is missing: install it from
https://www.python.org/downloads/ and TICK "Add Python to PATH" during setup.
Then double-click START_QUERYBOOK.bat again.
