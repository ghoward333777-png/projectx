QueryBook stress test — current design vs the Digital Synaptic Network (DSN)
============================================================================

What it does
  Six engines answer the same questions over the same facts, under increasing stress, and every result is scored
  against the known right answer:
    A0  today's QueryBook, as installed without an AI model (the prototype's own qb_chat.answer() and ufcs_store)
    A1  today's QueryBook with a planned first lookup (what an AI planner gives it)
    A2  today's pipeline chained step by step (a small change, no agents) — the control
    B   conventional multi-agent: a coordinator asks every agent, text messages
    C0  DSN without learning: subscriptions, synapses, Fact-Unit-ID messages, thresholds, inhibition
    C   DSN with learning synapses
  Every preset ends with a LEARNING OVER TIME study: one long stream of questions (popular ones recur, as in real use),
  reported every 500 questions, scored against the real world. It compares today's DSN with three upgrades —
  C+1 agents learn facts, C+2 new pathways, C+3 feedback on accuracy — and the central pipeline with the same learning.
  Half-way the faulty agents change (F); at three quarters the agents' areas are re-sharded (R).
  Stresses: wrong and missing facts, lying / dead / slow agents, up to 10,560 agents, up to 1 million facts, poisoned
  learning feedback, the faulty agents changing mid-run, 32 requests at once — alone, and all at once.

What you need
  Nothing to install on Windows: the ZIP carries its own Python (python folder, the official 64-bit embeddable
  Python 3.12.10 from python.org, about 11 MB) and the launchers use it. On a Mac or Linux, or if the python folder is
  removed, Python 3.8 or newer is used instead (standard library only).
  The folder must hold dsn_stress.py, qb_chat.py and ufcs_store.py (the last two are the prototype's own files).

FIRST: extract the ZIP
  Right-click QueryBook-StressTest.zip → "Extract All..." → open the extracted folder. Double-clicking a launcher while
  it is still inside the ZIP makes Windows copy only that one file, and the test cannot start (the launcher now says so).

How long it takes, and what you see
  The window shows a line for every scenario and engine. The quick run takes about 2–10 minutes; if a window closes or
  ends within seconds, it shows why (Python missing, files not extracted, or an error — also saved in
  dsn-results\error.txt). Send that text.

Run it (Windows: double-click; Mac/Linux: the command shown)
  RUN-QUICK.bat     python dsn_stress.py quick      a few minutes — check it works
  RUN-STRESS.bat    python dsn_stress.py stress     30–60 minutes
  RUN-EXTREME.bat   python dsn_stress.py extreme    several hours: 1 million facts, 10,000 questions, every stress
  RUN-LEARNING.bat  python dsn_stress.py learning   about 1 minute: only the learning-over-time study
  Self-check:       python dsn_stress.py self-test

  Free disk space needed: about 2 GB (quick, stress) or about 8 GB (extreme), for the fact stores it builds.
  Let the PC stay awake for the extreme run (Settings → System → Power: Sleep "Never" while it runs).

Results
  In the dsn-results folder beside the script: a report (dsn-stress-<preset>-<date>.md — open it in any text editor or
  Word), the same numbers as JSON, and run-log.txt. Send the .md file (or the whole folder zipped) for analysis.

Reading the numbers
  Correct          the engine said what a perfect reader of the same store must say
  Wrong answer     it stated something false, or answered what the store does not know (the worst outcome)
  No answer        it declined or could not get there (safe, but unhelpful)
  Missed conflict  the store holds two trusted values and the engine did not say so
  False alarm      it reported a conflict that a lying agent invented
  Messages/q, Bytes/q, Agents woken/q   communication per question
  p50 / p99 ms     typical and worst-1% time per question: real compute + modelled communication
                   (0.5 ms + bytes at 100 MB/s per message; a dead agent waited for costs a 250 ms timeout)
  Every run is seeded: the same command gives the same numbers on any machine (times differ with the machine).
