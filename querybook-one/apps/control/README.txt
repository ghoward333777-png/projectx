QueryBook Control Panel
=======================

One place to see and manage the three QueryBook applications (Language Builder; Math, Science & Engineering;
History & News). Double-click START-WINDOWS.bat (Windows) or START-MAC.command (Mac). It opens at
http://127.0.0.1:8100/ in your browser. Leave its window open while you use it.

  Overview         each application: running or not, version, health, harvest switch, facts, last harvest turn;
                   Start / Stop / Open / Harvest now; alerts; monitoring
  Mass harvesting  start or stop all harvesting at once, or a selection of applications and online harvesters
  Targeting        topics, applications, harvesters, sources to concentrate on (first, or only), with a budget boost
  Filtering        what may enter the shared facts: words to leave out / require, years, domains, licence classes;
                   preview it on the facts already shared before applying
  Shared facts     search the facts all three applications share
  Audit trail      every action taken here, with what changed and the outcome
  Diagnostics      a Diagnose button in every section, and "Run all diagnostics"
  Assistant        type plain requests ("stop all harvesting", "focus on volcanoes in history", "exclude football",
                   "find Marie Curie", "any alerts?"). It works by fixed rules - no AI model - so it only does what it
                   recognises, says what it changed, and asks before stopping anything.

Targeting and filtering change what all three applications harvest, so they need the admin passphrase once the admin
has set one (the same passphrase as the harvesting policy). The applications obey them from their next harvest turn.

Self-test: python app.py --selftest
