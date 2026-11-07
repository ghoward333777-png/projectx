"""The Digital Synaptic Network (DSN) and network memory: one source of wording for every QueryBook document.

The Bible (Pass 120, Chapter 131), the Composite Feature Registry v71 (features 392-407, ALG-22 to ALG-25, FIG. 58-59) and the
provisional (FIG. 58-59, claims 363-374) are all generated from this file, so they say the same thing. The code it describes:
querybook/apps/_core/qbdsn.py (answer routing), querybook/apps/_core/qbsynapse.py (network memory; the prototype's copy is
querybook/QueryBook-v9.64/qb_synapse.py), the wiring in qbbulk.py, qbcommons.py, control/ui, and in the prototype qb_chat.py,
qb_agents.py, qb_api.py and network.html; and the stress test querybook/sim/dsn_stress.py.
"""
DATE = "November 7, 2026"
DATE_ISO = "2026-11-07"
CITE = "DSN 2026-11-07"
FIG_R, FIG_N = 58, 59
FIG_R_TITLE = "Digital Synaptic Network: Answer Routing with Learned Pathways and Shadow Comparison"
FIG_N_TITLE = "Network Memory: Learning Synapses, Engrams, Assemblies and Networks of Networks"
BUILT = "Built — applications (Control Panel 1.34–1.35)"
BUILT_N = "Built — prototype v9.64 and applications (Control Panel 1.35)"
MOD_R = "qbdsn, qbbulk (applications); control/ui"
MOD_N = "qb_synapse (v9.64); qbsynapse (applications)"

# ------------------------------------------------------------------------------------------- Bible Chapter 131
TITLE = "The Digital Synaptic Network (DSN) and Network Memory"
INTRO = [
    "The Digital Synaptic Network borrows the communication economics of neurons — local work, sparse signalling, thresholds, "
    "inhibition and connections that change with use — for the way QueryBook's agents find and share knowledge. It has two parts. "
    "Answer routing decides which agents (in the applications, the dataset stores of the bulk harvest) are asked for a lookup: every "
    "one in turn (Central), only those its learned pathways point to (DSN), or Central with the DSN compared beside it (Shadow). "
    "Network memory treats the relationships between agents as a layer of memory: agents that succeed together form digital synapses "
    "that strengthen with repeated success, weaken with joint failure, fade when unused and are consolidated when long proven; strongly "
    "bound agents form assemblies, and assemblies linked through their members form networks of networks.",
    "Both parts are governed by the same rules as every QueryBook fact. Learned pathways and synapses hold relationships, never facts; "
    "they never change what an answer says; and every one of them can be inspected — its strength, its threshold, the contexts it "
    "formed in, its good and bad outcomes, its evidence and its history. The design principle is stated plainly: do not only make the "
    "agents smarter, make the connections between them able to learn — and keep those connections auditable.",
]
SUBSECTIONS = [
    ("131.1 Answer routing: Central, Shadow and DSN",
     ["Central asks every dataset store in turn until enough facts are found; it is the default. DSN asks only the stores whose learned "
      "pathways for the kind of lookup are at or above threshold, strongest first, and stops when enough facts are found; when the strong "
      "pathways find nothing, every remaining store is asked, so routing never hides a fact. Shadow answers with Central and runs the DSN "
      "on the same lookup in the background, logging every difference. The setting is changed by the administrator (with the admin "
      "passphrase when one is set) on the Control Panel, and changes apply between lookups, never during one."]),
    ("131.2 Learned pathways",
     ["The kind of a lookup is the first word of its subject, lower case, digits removed (a lookup beginning with a number is kind #). For "
      "each kind and each store the DSN keeps a pathway with a strength (neutral 0.5), the facts found and the empty answers. A store that "
      "returns facts is strengthened (strength + 0.10 × (1 − strength)); a store that returns nothing is weakened (strength − 0.15 × "
      "strength); a pathway below the threshold of 0.30 is not asked first; weak pathways recover slowly toward neutral (0.2% of the gap "
      "per lookup), and every 25th lookup of a kind tries one weak pathway again. A new kind starts neutral, so its first lookups ask every "
      "store and learn. Pathways are saved in the shared folder and capped at 2,000 kinds, the least recently used forgotten first."]),
    ("131.3 The Shadow comparison and its verdict",
     ["Every Shadow lookup records the lookup, its kind, whether Central's answer was complete, whether the DSN agreed, the facts it missed "
      "and added, whether it fell back to every store, and for each method the facts returned, the stores asked and the time taken. When "
      "Central returns fewer facts than the limit its answer is complete and the two answers are compared fact by fact; otherwise both are "
      "compared by whether the DSN also filled the limit. The health report states the routing in force and summarises the last 24 hours: "
      "lookups compared, agreement, lookups with missed facts, stores asked and median time for each method, and a verdict — too few "
      "lookups yet (under 50), keep Central (the DSN missed facts), no reason to switch (matched but not faster), or DSN is safe to try "
      "(matched every answer and was faster)."]),
    ("131.4 Re-checking learned routes",
     ["Routes learned on one set of stores can be wrong for another. When the DSN is switched back on after Central, every pathway is "
      "pulled halfway back to neutral, so it is re-checked by the lookups that follow rather than trusted."]),
    ("131.5 The stress test",
     ["A standard-library stress test (querybook/sim/dsn_stress.py) compares six engines on the same seeded questions over the same facts: "
      "the prototype as installed without a language model (A0), with a planned first lookup (A1), its pipeline chained step by step (A2, "
      "the control), conventional broadcast multi-agent messaging in text (B), the DSN without learning (C0) and with learning (C). "
      "Stresses include wrong, missing and contradicted facts; lying, dead, slow and biased agents; up to 10,560 agents and one million "
      "facts; poisoned learning feedback; faults that change mid-run; and 32 parallel requests. Communication is modelled (0.5 ms plus "
      "bytes at 100 MB/s per message; 250 ms timeout for a dead agent). It ships with a bundled Python for Windows and launchers that say "
      "why they stop.",
      "A learning-over-time study runs one long stream of recurring questions, reported every 500, scored against the real world rather "
      "than the store, with the faulty agents changed half-way and the agents' areas re-sharded at three quarters. It compares today's DSN "
      "with three upgrades — agents that learn verified facts and shortcuts (C+1), new pathways found by probing (C+2), and feedback on "
      "accuracy by outside audit (C+3) — and with the central pipeline given the same fact learning."]),
    ("131.6 What the stress test found",
     ["With faulty agents the DSN answered correctly far more often than broadcast messaging (100% against 31%; with every stress at once "
      "72% against 26%, with no wrong answers against 4.6%) while sending about five messages of 60–80 bytes per question against "
      "hundreds to thousands. The chained central pipeline was not beaten: 99.9% correct with every stress at once, and faster in its "
      "worst case on one machine (0.2 ms against 4.2 ms). Learning synapses alone did not change accuracy; they cut worst-case time and "
      "messages. In the learning-over-time study accuracy rose only when agents learned facts (DSN with all three upgrades 68% → 91% "
      "right; today's DSN flat at about 27% once areas were re-sharded), learning without accuracy checks cached mistakes (wrong answers "
      "3.3% with C+2 against 1.3% with C+3), and the central pipeline with the same fact learning remained slightly ahead (73% → 93%) "
      "and faster.",
      "The conclusion is recorded as stated: on one machine the central pipeline is the faster and slightly more accurate design, which is "
      "why Central is the default; the DSN's advantages come from facts spread over many stores or computers and from learning verified "
      "facts, and Shadow exists to measure on real data whether the DSN helps before it is trusted."]),
    ("131.7 The digital synapse",
     ["A digital synapse is a relationship between two agents or processing elements. Its record holds the relationship type "
      "(co-activation, or a directed type such as checks or feeds), its strength, its activation threshold, the contexts it formed in, its "
      "reliability as counts of good and bad outcomes, its provenance (the last five pieces of evidence), its history (the last twelve "
      "changes), when it formed, when it was last used, and whether it is consolidated. The threshold is 0.30 plus 0.40 times the share of "
      "bad outcomes, so an unreliable synapse needs more to pass activation. Every synapse explains itself in plain lines."]),
    ("131.8 Plasticity",
     ["A new synapse forms weak (0.20, below threshold): one coincidence is not a relationship. Each joint success potentiates it "
      "(strength + 0.10 × (1 − strength)), so about two successes carry it over threshold and about five bind its agents into an assembly; "
      "a joint failure depresses it (strength − 0.25 × strength) and raises its threshold. An unused synapse fades by 5% a day; one with at "
      "least 20 good outcomes and four times as many good as bad is consolidated and fades by only 1% a day; a synapse that has faded "
      "below 0.05 and has been idle for 30 days is removed (turnover). Formation, potentiation, depression, fading and pruning are counted."]),
    ("131.9 Co-activation, episodes and directed links",
     ["Agents become linked in three ways. An episode names the agents active together in one piece of work — for example the specialists "
      "whose facts answered one question, or the stores that answered one lookup — and every pair among them (at most eight agents) is "
      "potentiated on success or depressed on failure. A single activation links an agent with every agent that succeeded within the "
      "co-activation window (600 seconds by default): fire together, wire together. A directed link records that one agent's output was "
      "used by another, for example a check asked by one application's team and answered by another's."]),
    ("131.10 Engrams, assemblies and networks of networks",
     ["For each context — a kind of problem — the network keeps its engram: the population of agents active when that problem was solved, "
      "with how often each was active. Agents joined by co-activation synapses of strength 0.50 or more form an assembly, a functional "
      "group with its members, cohesion (mean strength), joint successes and the contexts it solves. Synapses above threshold between "
      "members of different assemblies link the assemblies: networks communicating with networks, each link with its number of synapses, "
      "mean strength and contexts."]),
    ("131.11 Spreading activation",
     ["Activation spreads from the active agents along synapses above their own threshold, multiplied by the synapse's strength and a "
      "falloff of one half at each step, for two steps. The result ranks who else is likely to matter now: in the applications it orders "
      "the stores asked when the strong pathways found nothing (the strong stores' assembly partners first); in the prototype it is "
      "reported with each answer as the related specialists."]),
    ("131.12 Where network memory is wired",
     ["Prototype v9.64: every answered question is an episode for its specialists (the predicates of the facts cited), in the context of "
      "the question's planned predicates; a verified answer potentiates them, a contradiction depresses them; the answer itself is never "
      "changed and reports the assembly its specialists belong to and the related specialists. Harvesting agents are activated at the end "
      "of every clean cycle, a cycle that added facts counting as success. Applications: the stores that answered a lookup form an episode "
      "of that lookup's kind; and every cross-application check (asked by one team, answered by another) strengthens the directed link "
      "between the two teams when an answer was given and weakens it when the answer was cannot check. Each application writes its own "
      "network file, so separate processes never overwrite one another."]),
    ("131.13 Interfaces",
     ["Prototype: GET /api/network (agents, synapses, assemblies, assembly links, engrams, strongest synapses, counters, the health line, and "
      "with a=…&b=… one synapse's explanation) and the Network page. Applications: GET /api/dsn/status (routing, Shadow summary, learned "
      "pathways, network memory of the stores and of the checks between applications) and POST /api/dsn/mode; the Answer routing section "
      "of the Control Panel; and the health report, which carries the routing, the Shadow comparison and one network-memory line for each "
      "network."]),
    ("131.14 Status and limits",
     ["Answer routing is built and tested in the applications' shared core (qbdsn.py, Control Panel 1.34.0); network memory is built and "
      "tested in prototype v9.64 (qb_synapse.py) and in the applications' shared core (qbsynapse.py, Control Panel 1.35.0). Both are "
      "deterministic for the same events in the same order and use the standard library only. They record, adapt and explain how agents "
      "work together; they do not by themselves create intelligence, and no claim beyond what is built is made for them."]),
]

# ------------------------------------------------------------------------------------------------- registry v71
# (name, domain, figs, surface, role, function, rule, worked expression, status, module); numerals in NUMERAL
NEW = [
 ("Three-Way Answer Routing (Central, Shadow, DSN)", "Retrieval & Response", [58], "System", "Administrator",
  "Route each bulk fact lookup as the administrator sets: Central asks every store in turn; DSN asks only stores whose learned pathways are at or above threshold; Shadow answers with Central and runs the DSN beside it.",
  "Central is the default; the setting changes only between lookups and needs the admin passphrase when one is set.",
  '=IF("shadow"="dsn","learned pathways",IF("shadow"="shadow","Central answers; DSN compared","every store"))', BUILT, MOD_R),
 ("Learned Store Pathways per Lookup Kind", "Retrieval & Response", [58], "System", "System",
  "Keep, for each kind of lookup (first word of the subject) and each store, a pathway with strength, facts found and empty answers; strengthen on facts, weaken on empty answers, recover weak pathways slowly and retry one every 25th lookup.",
  "A pathway below 0.30 is not asked first; pathways hold routes, never facts.",
  "=0.5+0.1*(1-0.5)", BUILT, MOD_R),
 ("Complete-Answer Fallback", "Retrieval & Response", [58], "System", "Any user",
  "When the stores on strong pathways return nothing, ask every remaining store, ordered by spreading activation from the strong stores' assembly partners, and learn from the result.",
  "Routing never hides a fact that Central would have found.", None, BUILT, MOD_R),
 ("Shadow Comparison Log", "Platform Governance & Evolution", [58], "System", "Administrator / Auditor",
  "Record for every Shadow lookup whether the DSN agreed with Central, the facts missed and added, fallback, and for each method facts returned, stores asked and time.",
  "Central's answer is what the user receives; complete answers are compared fact by fact.",
  '=IF(0=0,"agreed","missed facts")', BUILT, MOD_R),
 ("Shadow Verdict in the Health Report", "Platform Governance & Evolution", [58], "System", "Operator",
  "Summarise the last 24 hours of Shadow comparison in the health report — agreement, missed lookups, stores asked and median time per method — with a verdict.",
  "No verdict to switch before 50 lookups; any missed fact gives keep Central.",
  '=IF(120<50,"too few lookups",IF(0>0,"keep Central",IF(1<1,"DSN is safe to try","no reason to switch")))', BUILT, MOD_R),
 ("Re-Check of Learned Routes on Re-Enable", "Platform Governance & Evolution", [58], "System", "Administrator",
  "When the DSN is switched back on after Central, pull every learned pathway halfway back to neutral so stale routes are re-checked rather than trusted.",
  "Applied once per switch from Central; the change is recorded in the audit log.",
  "=0.9+(0.5-0.9)/2", BUILT, MOD_R),
 ("DSN Stress-Test Harness", "Platform Governance & Evolution", [58], "Tool", "Engineer",
  "Compare six engines (prototype as installed, planned, chained; broadcast agents; DSN without and with learning) on seeded questions under data, agent, scale, poisoning, drift and load stresses with modelled communication, plus a learning-over-time study with three upgrades.",
  "Every run is seeded and scored against the known right answer; results are reported as measured, including where the DSN loses.",
  None, "Built — test tool (querybook/sim, 1.1.0)", "dsn_stress (querybook/sim)"),
 ("Digital Synapse Record", "Knowledge Substrate", [59], "System", "Engineer / Auditor",
  "Hold, for each relationship between two agents, its type, strength, activation threshold, contexts, good and bad outcomes, last five pieces of evidence, last twelve changes, formation and last-use times and consolidation.",
  "The threshold rises with the share of bad outcomes (0.30 + 0.40 × bad share); every synapse explains itself.",
  "=0.3+0.4*1/(6+1)", BUILT_N, MOD_N),
 ("Synaptic Plasticity", "Knowledge Substrate", [59], "System", "System",
  "Form a new synapse weak (0.20), potentiate it on each joint success (+0.10 × the remaining gap) and depress it on each joint failure (−25%).",
  "One coincidence is not a relationship: about two joint successes cross threshold, about five bind an assembly.",
  "=1-(1-0.2)*(1-0.1)^5", BUILT_N, MOD_N),
 ("Forgetting, Turnover and Consolidation", "Knowledge Substrate", [59], "System", "System",
  "Fade unused synapses by 5% a day (1% when consolidated after at least 20 good outcomes and four good for every bad) and remove those below 0.05 idle for 30 days.",
  "Formation, potentiation, depression, fading and pruning are counted and reported.",
  "=0.6*(1-0.05)^30", BUILT_N, MOD_N),
 ("Co-Activation Episodes, Windows and Directed Links", "Knowledge Substrate", [59], "System", "System",
  "Link agents active in one episode (up to eight, pairwise), agents succeeding within a co-activation window (600 s), and agents whose output another used (directed links).",
  "Only success forms a synapse; failure only weakens existing ones.", None, BUILT_N, MOD_N),
 ("Engrams per Context", "Knowledge Substrate", [59], "System", "Any user",
  "Keep for each kind of problem the population of agents active when it was solved, with how often each was active.",
  "Recorded only for successful episodes; at most 2,000 contexts, least recently used forgotten first.", None, BUILT_N, MOD_N),
 ("Functional Agent Assemblies", "Knowledge Substrate", [59], "System", "Any user",
  "Group agents joined by co-activation synapses of strength 0.50 or more into assemblies with members, cohesion, joint successes and the contexts they solve.",
  "An assembly has at least two members; its identifier is stable for the same members.", None, BUILT_N, MOD_N),
 ("Networks of Networks (Assembly Links)", "Knowledge Substrate", [59], "System", "Any user",
  "Link assemblies through synapses above threshold between their members, reporting the number of synapses, mean strength and contexts of each link.",
  "Only synapses above their own threshold count as links.", None, BUILT_N, MOD_N),
 ("Spreading Activation over Synapses", "Knowledge Substrate", [59, 58], "System", "System",
  "Spread activation from active agents along synapses above threshold, scaled by strength with a falloff of one half per step for two steps, to rank who else is likely to matter.",
  "Used to order fallback stores and to report related specialists; never to change an answer.",
  "=1*0.6*0.5", BUILT_N, MOD_N),
 ("Network Memory Wiring and Interfaces", "External Integration & Analysis", [59], "System", "Any user / Developer",
  "Feed network memory from prototype answers (cited predicates as specialists), harvesting-agent cycles, store lookups and cross-application checks, and expose it as /api/network, the Network page, the Control Panel and health-report lines.",
  "Answers are never changed; each application writes its own network file.", None, BUILT_N,
  "qb_chat, qb_agents, qb_api, network.html (v9.64); qbdsn, qbcommons, qbbulk, control/ui (applications)"),
]
NUMERAL = [5810, 5820, 5830, 5840, 5850, 5860, 5870, 5910, 5920, 5930, 5940, 5950, 5960, 5970, 5980, 5990]
assert len(NUMERAL) == len(NEW)

ALGOS = [
 ("ALG-22", "DSN lookup with learned pathways",
  "Three-Way Answer Routing; Learned Store Pathways per Lookup Kind; Complete-Answer Fallback; Spreading Activation over Synapses", [58, 59],
  "Lookup text; limit; stores held; learned pathways",
  "1. Take the lookup's kind (first word, lower case, digits removed). 2. Give every store without a pathway a neutral one (0.5); let weak pathways recover by 0.2% of their gap. 3. Order stores by pathway strength; those at or above 0.30 are strong; every 25th lookup of the kind adds the strongest weak one. 4. Ask strong stores in order until the limit is reached, strengthening those with facts and weakening those without. 5. If nothing was found, order the weak stores by spreading activation from the strong stores and ask them, learning likewise. 6. Record the stores that answered as one episode of the kind in the network memory.",
  "Facts; stores asked; whether every store was asked", "Yes", "qbdsn"),
 ("ALG-23", "Shadow comparison and verdict",
  "Shadow Comparison Log; Shadow Verdict in the Health Report", [58],
  "Central's answer, stores asked and time; the same lookup",
  "1. Return Central's answer to the user. 2. In the background run ALG-22 on the same lookup. 3. If Central returned fewer facts than the limit, compare the two answers fact by fact; otherwise compare whether the DSN filled the limit. 4. Log agreement, missed and added facts, fallback, stores asked and time for both. 5. For the health report, over the last 24 hours, compute agreement, missed lookups, mean stores asked and median time per method. 6. Verdict: under 50 lookups, too few; any missed lookup, keep Central; DSN faster, safe to try; otherwise no reason to switch.",
  "Log record; health-report lines and verdict", "Yes", "qbdsn"),
 ("ALG-24", "Synaptic plasticity update",
  "Digital Synapse Record; Synaptic Plasticity; Forgetting, Turnover and Consolidation; Co-Activation Episodes, Windows and Directed Links; Engrams per Context", [59],
  "Agents active (episode, single activation or directed link); context; success; evidence; time",
  "1. For an episode, take up to eight distinct agents; for a single activation, take the agents that succeeded within the window. 2. On success, record the agents in the context's engram. 3. For each pair (or the directed pair), fade the synapse for its idle time, then form it at 0.20 if absent and the outcome is a success. 4. Potentiate on success (+0.10 × (1 − strength)) or depress on failure (−25%); update good and bad counts, threshold (0.30 + 0.40 × bad share), consolidation, contexts, evidence and history. 5. Periodically fade every synapse by its idle time and remove those below 0.05 idle 30 days.",
  "Updated synapses, engram and counters", "Yes", "qb_synapse / qbsynapse"),
 ("ALG-25", "Assemblies, networks of networks and spreading activation",
  "Functional Agent Assemblies; Networks of Networks (Assembly Links); Spreading Activation over Synapses", [59],
  "The synapse records",
  "1. Union the agents joined by co-activation synapses of strength 0.50 or more; each group of two or more is an assembly with members, cohesion, joint successes and top contexts. 2. For each synapse above its threshold whose ends lie in different assemblies, add it to the link between those assemblies; report links with synapse count, mean strength and contexts. 3. For spreading activation, start the active agents at 1.0; for two steps pass activation × strength × 0.5 along synapses above threshold, keeping each agent's highest value; rank the agents.",
  "Assemblies; assembly links; ranked activation", "Yes", "qb_synapse / qbsynapse"),
]

# ------------------------------------------------------------------------------------------------- provisional
SUMMARY_I = [[("   i. A digital synaptic network by which lookups are routed to the dataset stores that learned pathways indicate, with "
               "a shadow mode that answers centrally while comparing the routed answer and reporting a verdict, and a network memory in "
               "which the relationships between agents are adaptive, auditable synapses that strengthen with joint success, weaken with "
               "joint failure, fade and are consolidated, and from which engrams, functional assemblies of agents and links between "
               "assemblies are derived (FIG. 58–59).", False)]]
SYSTEM_9 = [[("9. Learning connections between agents. QueryBook can route a lookup to the stores that have answered that kind of "
              "lookup before, compare that routing against asking every store before trusting it, and remember which of its agents "
              "work well together: each relationship records its strength, threshold, contexts, reliability, evidence and history, and "
              "groups of agents that repeatedly succeed together appear as assemblies. Answers are never changed by this memory. See "
              "FIG. 58 and FIG. 59.", False)]]
CORE = [
 [("14. Digital Synaptic Network — answer routing (FIG. 58). ", True),
  ("A lookup (5800) enters an answer router (5805) whose routing setting (5810), chosen by an administrator, is central, shadow or "
   "routed. In the central setting every dataset store (5895) is asked in turn until enough facts are found. In the routed setting a "
   "pathway table (5820) holds, for each kind of lookup and each store, a pathway with a strength, a count of facts found and a count of "
   "empty answers; the stores whose pathways are at or above a threshold are asked strongest first, a store returning facts being "
   "strengthened and a store returning none weakened, weak pathways recovering slowly and one weak pathway being retried periodically. "
   "When the strong pathways return nothing, a fallback (5830) asks every remaining store, ordered by spreading activation over the "
   "network memory of FIG. 59, so that routing never withholds a fact the central setting would find. In the shadow setting the central "
   "answer is returned and the routed lookup is run on the same lookup in the background; a comparison log (5840) records agreement, "
   "facts missed and added, fallback, and for each method the facts returned, stores asked and time; and a health report (5850) states the "
   "setting in force and a verdict over the last 24 hours, no switch being recommended before a minimum number of lookups or when any "
   "fact was missed. When routing is enabled again after the central setting, a re-check (5860) moves every pathway halfway back to "
   "neutral. A stress-test harness (5870) compares central, broadcast and routed designs under data, agent, scale and load stresses.", False)],
 [("15. Network memory (FIG. 59). ", True),
  ("Activity sources (5900) — the specialists whose facts answered one question, harvesting agents completing a cycle, the stores that "
   "answered one lookup, and a check asked by one application team and answered by another — report agents active together. A synapse "
   "store (5905) holds digital synapse records (5910), each comprising a relationship type, a strength, an activation threshold, the "
   "contexts in which it formed, counts of good and bad outcomes, recent evidence, a history of recent changes, its formation and last-use "
   "times, and a consolidation flag. A plasticity unit (5920) forms a synapse at a low strength below threshold only on a joint success, "
   "potentiates it on each joint success and depresses it on each joint failure, the threshold rising with the share of bad outcomes. A "
   "turnover unit (5930) fades every synapse according to its idle time, more slowly once consolidated by a long record of success, and "
   "removes synapses that have faded below a floor and remained idle. A co-activation unit (5940) links agents active in one episode, "
   "agents succeeding within a time window, and agents whose output another used, the last as directed links. An engram store (5950) keeps, "
   "for each context, the agents active when it was solved. An assembly detector (5960) groups agents joined by synapses above a binding "
   "strength into functional assemblies, and a link detector (5970) links assemblies through synapses above threshold between their "
   "members. A spreading-activation unit (5980) propagates activation from active agents along synapses above threshold, scaled by "
   "strength and attenuated at each step, to rank related agents. Interfaces (5990) expose the network, each synapse's explanation and a "
   "health line.", False)],
 [("16. Answers unchanged. ", True),
  ("Network memory records and reports; it never alters an answer. In the prototype each answer reports the assembly to which its "
   "specialists belong and the related specialists ranked by spreading activation, while its verdict, text and citations are the same as "
   "without the network.", False)],
 [("17. Status. ", True),
  ("The answer routing of FIG. 58 is implemented in the shared core of the applications and exercised by their self-tests; the network "
   "memory of FIG. 59 is implemented in prototype v9.64 and in the shared core of the applications and exercised by their self-tests.", False)],
]
ARCH = [[("Referring to FIG. 58 and FIG. 59: the answer router and the network memory hold relationships, never facts. Every pathway "
          "and every synapse is inspectable, the routing setting is changed only by an administrator, and the central setting remains "
          "available as the reference against which the routed setting is measured.", False)]]
BRIEF_R = [[("FIG. 58 ", True),
            ("is a block diagram of the digital synaptic network's answer routing, showing a lookup entering an answer router with a "
             "central, shadow or routed setting, a pathway table of learned store pathways, a complete-answer fallback ordered by spreading "
             "activation, a shadow comparison log and health-report verdict, a re-check of pathways on re-enable, and a stress-test harness.", False)]]
BRIEF_N = [[("FIG. 59 ", True),
            ("is a block diagram of the network memory, showing activity sources feeding a synapse store of digital synapse records, a "
             "plasticity unit, a turnover unit with consolidation, a co-activation unit, an engram store, an assembly detector, a detector of "
             "links between assemblies, a spreading-activation unit and the interfaces through which the network is inspected.", False)]]
NOTE = [[("[Drafting note: FIG. 58 and FIG. 59 are added to the drawing set, which now comprises FIG. 1–59, one figure per sheet.]", False)]]
CLAIMS = [
 ("363.  ", "The method of claim 1, further comprising receiving a lookup for facts held in a plurality of stores; selecting, according to "
  "a routing setting chosen by an administrator, between asking every store in turn, asking only the stores whose learned pathways for a "
  "kind of the lookup are at or above a threshold, and a shadow setting in which the answer obtained by asking every store is returned while "
  "the lookup is also performed by the learned pathways and the two results are compared."),
 ("364.  ", "The method of claim 363, wherein each learned pathway comprises a strength, a count of facts found and a count of empty "
  "answers for a kind of lookup and a store; wherein the strength of a pathway is increased when its store returns facts and decreased when "
  "it returns none; and wherein, when the stores whose pathways are at or above the threshold return no facts, every remaining store is asked."),
 ("365.  ", "The method of claim 363, wherein each comparison in the shadow setting records whether the results agreed, the facts missed and "
  "added, and for each method the facts returned, the stores asked and the time taken; and further comprising reporting, over a period, the "
  "agreement, the lookups with missed facts and a verdict, wherein no change to the routing setting is recommended before a minimum number of "
  "lookups or when any fact was missed."),
 ("366.  ", "The method of claim 364, further comprising, when routing by learned pathways is enabled after the setting of asking every "
  "store, moving the strength of every learned pathway toward a neutral value, whereby pathways learned on an earlier set of stores are "
  "re-checked rather than trusted."),
 ("367.  ", "The method of claim 1, further comprising maintaining, for pairs of agents of the system, synapse records each comprising a "
  "relationship type, a strength, an activation threshold, contexts in which the synapse formed, counts of good and bad outcomes, recent "
  "evidence and a history of changes; increasing the strength of a synapse when the agents it joins succeed together; and decreasing the "
  "strength and raising the threshold when they fail together."),
 ("368.  ", "The method of claim 367, wherein a synapse is formed only upon a joint success and at a strength below its threshold; wherein "
  "the strength of every synapse decays according to the time since it was last used, at a lower rate for a synapse consolidated by a record "
  "of good outcomes; and wherein a synapse whose strength has decayed below a floor and which has remained unused for a period is removed."),
 ("369.  ", "The method of claim 367, further comprising recording, for each of a plurality of contexts, the agents active when a problem of "
  "that context was solved, as an engram of the context."),
 ("370.  ", "The method of claim 367, further comprising grouping agents joined by synapses at or above a binding strength into assemblies, "
  "each reported with its members, a cohesion and the contexts it solves; and linking assemblies through synapses above threshold between "
  "their members, each link reported with its number of synapses, mean strength and contexts."),
 ("371.  ", "The method of claim 364, further comprising maintaining synapses between the stores, each strengthened when the stores it "
  "joins answer the same lookup; propagating activation from the stores whose pathways are at or above the threshold along synapses whose "
  "strength is at or above their own threshold, scaled by the strength and attenuated at each step; and ordering by the resulting ranking "
  "the remaining stores asked when the stores whose pathways are at or above the threshold return no facts."),
 ("372.  ", "The method of claim 367, wherein the agents active together in answering a question are specialists corresponding to the "
  "predicates of the facts cited in the answer; wherein a verified answer increases and a contradicted answer decreases the strength of the "
  "synapses among them; and wherein the answer's verdict, text and citations are unchanged by the synapses, the answer further reporting the "
  "agents most strongly connected to its specialists."),
 ("373.  ", "The method of claim 367, wherein a request for a check made by a team of agents of one application and answered by a team of "
  "agents of another application is recorded as a directed synapse between the teams, strengthened when an answer was given and weakened "
  "when the answering team could not check."),
 ("374.  ", "The method of claim 367, further comprising exposing, through an interface, the synapse records, the assemblies, the links "
  "between assemblies, the engrams and an explanation of any one synapse comprising its strength, threshold, contexts, outcomes, evidence and "
  "history."),
]
CLAIM_NOTE = ("[Drafting note: claims 363–374 are added for the digital synaptic network and network memory (FIG. 58–59); the claim count "
              "in the Claim Set heading is to be read as 374.]")

# ------------------------------------------------------------------------------------------------- figure keys
FIG_KEY_R = [
 ("5800", "Lookup (subject text, limit)"), ("5805", "Answer router"),
 ("5810", "Routing setting: Central · Shadow · DSN (administrator)"), ("5820", "Learned pathway table: kind × store → strength, facts, empty"),
 ("5830", "Complete-answer fallback: every store, ordered by spreading activation"), ("5840", "Shadow comparison log"),
 ("5850", "Health report: routing, 24-hour comparison, verdict"), ("5860", "Re-check on re-enable: pathways halfway to neutral"),
 ("5870", "Stress-test harness: six engines, stresses, learning over time"), ("5895", "Dataset stores (agents)"),
 ("5899", "Answer returned (Central's in Shadow)"),
]
FIG_KEY_N = [
 ("5900", "Activity sources: answers, agent cycles, store lookups, cross-application checks"), ("5905", "Synapse store"),
 ("5910", "Digital synapse record: type, strength, threshold, contexts, good/bad, evidence, history"),
 ("5920", "Plasticity: weak formation, potentiation, depression, threshold rise"),
 ("5930", "Turnover: fading by idle time, consolidation, pruning"), ("5940", "Co-activation: episodes, time window, directed links"),
 ("5950", "Engram store: agents active per context"), ("5960", "Assembly detector: synapses ≥ binding strength"),
 ("5970", "Assembly links: networks of networks"), ("5980", "Spreading activation: strength × falloff, above threshold"),
 ("5990", "Interfaces: /api/network, Network page, Control Panel, health lines"),
]
