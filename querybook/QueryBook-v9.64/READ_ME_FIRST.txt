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

NEW IN v9.64
------------
OPEN CLAW (ingest any file)
  Open  http://127.0.0.1:8099/openclaw  and drop in a PDF, Word or Excel file, PowerPoint,
  web page, e-mail, image, recording, video or ZIP. QueryBook turns it into cited facts and
  seals the file's fingerprint. Text in a file that tries to give an AI orders is flagged and
  never followed.

CERTIFICATES ON THE BLOCKCHAIN (real NFTs)
  On the same page, QueryBook can certify a file or fact as an NFT on a public test network
  (Sepolia by default; nothing costs real money):
    1. Note the wallet address shown on the page.
    2. Get free test coins for it once from a Sepolia faucet (the page shows a link).
    3. Click "Deploy contract" once, then tick "also certify on the blockchain" when you ingest.
  Anyone can verify a certificate on the blockchain without trusting your PC.

SECURITY (protection against OpenClaw-style attacks)
  Open  http://127.0.0.1:8099/security . Every AI agent now goes through a gateway with its own
  permissions, and traps catch attackers: fake admin commands, fake keys and fake secret
  files. An attacker who touches a trap is quietly moved into a fake world while QueryBook
  records what it does. The security log can't be quietly altered. Details: SECURITY-SPEC.md.
  Two files, .env.production.bak and qb_admin_credentials.json.bak, appear in this folder.
  They are deliberate decoys full of fake keys. Leave them alone.

CONNECT OPENCLAW
  See openclaw\README.txt. In short: run   py qb_mcp.py --openclaw-config   and paste the
  result into OpenClaw's settings.
