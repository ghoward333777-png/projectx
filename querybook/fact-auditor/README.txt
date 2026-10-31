QueryBook Fact Auditor 1.0.0
============================

A separate program, not part of the QueryBook applications or the prototype. It shares no code with them and
never changes their data: it opens the fact folder READ-ONLY and audits what is there.

START
  Windows: double-click START-WINDOWS.bat      Mac: double-click START-MAC.command
  The page opens at http://127.0.0.1:8300. It finds QueryBook's shared fact folder by itself; if it doesn't,
  open Settings and type the folder (the one the Control Panel's "Move the shared folder" points at).
  Needs Python 3.8 or newer. Nothing to install.

WHAT IT SHOWS (Facts tab)
  Every fact in every store: the shared facts (commons.sqlite), every bulk shard (Wikidata lanes, PubChem,
  NCBI Taxonomy, NOAA, GNIS, USDA, Tatoeba, the calendar scaffold...) and any UFCS packet store. Page through
  them all, filter by store and status, or search. Click a fact to see:
    * its audit (Legitimacy, Accuracy, Citation), check by check, with the reason for each result
    * its Fact Unit: fingerprint, subject, predicate, object, domain, status, confidence, origin, where it is stored
    * its UFCS fact packet (UFCS 1.0: nucleus, polarity, semantic fingerprint, FUID, sources, certification,
      temporal, safety, provenance)
    * the UFCS packets associated with it: one per piece of evidence (each source, recomputation and
      consistency check), one per cross-check between applications, and for bulk facts the dataset record
      (file part, row, edition, download link, link to the exact record)
    * the other facts held about the same subject
  "Check citations & source online" fetches every citation link and, for Wikidata facts, re-reads the item
  from Wikidata and says whether Wikidata still holds that value.
  "Download these facts as UFCS packets (JSONL)" exports the listed facts with their packets and audits.

THE CHECKS
  Legitimacy  L1 source approved in the policy registry   L2 licence class has no conditions
              L3 the harvest is recorded                   L4 no third-party wording kept
              L5 the harvest log's hash chain is intact
  Accuracy    A1 the fingerprint recomputes (the record was not altered)
              A2 well-formed value (real dates, coordinates in range, no invisible characters...)
              A3 the evidence agrees (nothing contradicts it)   A4 the status is what the evidence earns
              A5 independent confirmation                  A6 no conflicting value (two birth dates...)
              A7 a possible lifespan
  Citation    C1 every source cited                        C2 every link well-formed
              C3 the exact record is cited, not just the source's home page
  Results: pass, warn (worth a look), fail (wrong or not allowed), info (nothing to judge).

THE WHOLE STORE (Audit tab)
  Audits a sample of each store (an even spread, by fingerprint) or every fact, optionally with online
  re-checks of some facts. Shows totals, results by check and by store, and every issue; download the report
  (JSON) or the issues (CSV). Reports are kept in the "reports" folder beside this program.

FROM THE COMMAND LINE
  python auditor.py --data <folder>                         the web page for that folder
  python auditor.py audit --data <folder> --sample 5000     a report without the page (--full for every fact,
                                                            --online 50 to re-check 50 facts online)
  python auditor.py self-test                               checks the auditor itself
