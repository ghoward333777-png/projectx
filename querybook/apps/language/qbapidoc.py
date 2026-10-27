"""qbapidoc — the harvesting suite's API in plain words: what each endpoint is for, what to send, and the tasks people
actually do with it (the Control Panel's API page).

Every application lists its own endpoints itself (GET /api/routes, GET /api/openapi.json — qbcore.Api), with the
parameters read from its code; this module adds the human explanation for the harvesting endpoints and a few
"start here" recipes. An endpoint without an entry here is still listed, just without the explanation.

Kinds: "read" changes nothing; "changes" changes harvesting state; "admin" needs the admin passphrase.
"""

VERSION = "1.0.0"
PROGRAMS = {"control": ("QueryBook Control Panel", 8100), "language": ("Language Builder", 8101), "stem": ("Math, Science & Engineering", 8102),
            "facts": ("History & News", 8103)}

# path: (group, title, what it does, example parameters, kind, where it lives: "control" or "apps" (each of the three) or "all")
DOCS = {
    # watch the facts
    "/api/panel/ticker": ("Watch the facts", "Live fact counts", "UFCS fact counts per area (Language, STEM, History & News) and in total, "
                          "with arrivals in the last minute and hour — the shared fact store plus the bulk shards. Poll it every few seconds.",
                          {}, "read", "control"),
    "/api/panel/status": ("Watch the facts", "Everything the Control Panel shows", "The three applications (running, version, health, facts), "
                          "the master switch, the rules, the alerts and the harvest overview.", {}, "read", "control"),
    "/api/commons/status": ("Watch the facts", "One application's harvest team", "The team's state (strategist, planner, harvester, curator), "
                            "its last turn and the shared store's totals.", {}, "read", "apps"),
    "/api/harvest/status": ("Watch the facts", "One application's harvesting page", "Sources and their approval, the online harvesters, "
                            "budgets, the master switch and the latest harvest log entries.", {}, "read", "apps"),
    # find facts
    "/api/panel/search": ("Find facts", "Search the shared facts", "Facts whose subject, predicate or object contains the words, "
                          "optionally one area (language, stem, history) or one status (verified, corroborated, sourced, …).",
                          {"q": "Einstein", "domain": "", "status": "", "limit": 20}, "read", "control"),
    "/api/panel/fact": ("Find facts", "One fact with its evidence", "A shared fact by its id: every piece of evidence, its sources and "
                        "licences, and the reasoning steps.", {"id": 1}, "read", "control"),
    "/api/bulk/search": ("Find facts", "Look up bulk facts", "Bulk facts whose subject starts with the text, with the dataset, the file "
                         "row they came from and the publisher's page.", {"q": "PubChem CID 2244", "limit": 20}, "read", "control"),
    "/api/commons/facts": ("Find facts", "Search the shared facts (from an application)", "The same search, asked of one application.",
                           {"q": "Einstein", "limit": 20}, "read", "apps"),
    "/api/commons/fact": ("Find facts", "One fact with its evidence (from an application)", "The same as the Control Panel's, asked of "
                          "one application.", {"id": 1}, "read", "apps"),
    # start and stop
    "/api/harvest/master": ("Start and stop harvesting", "The master switch", "on: true starts every application and approved harvester; "
                            "on: false stops all harvesting (and running campaigns).", {"on": True}, "changes", "all"),
    "/api/panel/harvest": ("Start and stop harvesting", "Start or stop chosen applications", "action start or stop, for every application, "
                           "or only the ones named in apps (language, stem, facts) and harvesters.",
                           {"action": "start", "apps": ["facts"], "harvesters": [], "now": False}, "changes", "control"),
    "/api/harvest/control": ("Start and stop harvesting", "Start or stop (from an application)", "action start or stop; scope all, or "
                             "selected with apps and harvesters.", {"action": "stop", "scope": "all"}, "changes", "apps"),
    "/api/commons/run": ("Start and stop harvesting", "Run a harvest turn now", "One application's team harvests now instead of waiting "
                         "for its next turn.", {}, "changes", "apps"),
    # bulk
    "/api/bulk": ("Bulk harvesting", "Bulk datasets and agents", "Every open dataset: its source and approval, state, facts, rate, "
                  "rows done per file and size on disk; the runner; the scaffold slots filled.", {}, "read", "control"),
    "/api/bulk/start": ("Bulk harvesting", "Start bulk agents", "Starts the chosen datasets (empty = all), agents at once (1–16). "
                        "Downloads large files: admin passphrase required.",
                        {"datasets": ["calendar-scaffold", "usgs-gnis"], "agents": 4, "passphrase": ""}, "admin", "control"),
    "/api/bulk/stop": ("Bulk harvesting", "Stop bulk agents", "Every agent stops after its current batch and resumes there next time.",
                       {}, "changes", "control"),
    # campaigns
    "/api/campaigns": ("Campaigns", "Campaigns and Google tools", "Saved campaigns, the master switch, the Google exemplar tools and "
                       "their runner.", {}, "read", "all"),
    "/api/campaigns/save": ("Campaigns", "Save a campaign", "A named selection of applications, online harvesters and Google tools "
                            "(give id to change an existing one).", {"name": "History push", "apps": ["facts"], "harvesters": [], "tools": [],
                                                                      "goal": 10000}, "changes", "all"),
    "/api/campaigns/start": ("Campaigns", "Start a campaign", "Runs only the campaign's selection; Google tools need the passphrase.",
                             {"id": "c1", "passphrase": ""}, "changes", "all"),
    "/api/campaigns/stop": ("Campaigns", "Stop a campaign", "Stops the campaign's selection.", {"id": "c1"}, "changes", "all"),
    "/api/campaigns/delete": ("Campaigns", "Delete a campaign", "Removes a saved campaign.", {"id": "c1"}, "changes", "all"),
    # rules and sources
    "/api/panel/rules": ("Rules and sources", "Set targeting or filtering", "kind target (what to harvest first) or filter (what may "
                         "enter the shared facts); admin passphrase once one is set.",
                         {"kind": "filter", "rules": {"exclude_words": "", "years": [1800, 2026]}, "passphrase": ""}, "admin", "control"),
    "/api/panel/preview": ("Rules and sources", "Try a filter first", "What a filter would keep and leave out among the latest shared "
                           "facts, without saving it.", {"rules": {"exclude_words": "war"}}, "read", "control"),
    "/api/harvest/source": ("Rules and sources", "Approve or block a source", "status approved, blocked or pending for a source in the "
                            "policy registry, with the reason.", {"key": "wikidata", "status": "approved", "reason": "", "passphrase": ""},
                            "admin", "apps"),
    "/api/harvest/decide": ("Rules and sources", "Decide a recommendation", "Approve or reject one of the harvesting engine's "
                            "recommendations.", {"id": 1, "approve": True, "note": "", "passphrase": ""}, "admin", "apps"),
    # audit
    "/api/harvest/log": ("Audit and logs", "The harvest log", "Every harvest, block and failure with its source, licence class and "
                         "why; filter by app and decision (harvested, blocked, failed).", {"app": "", "decision": "", "limit": 50}, "read", "apps"),
    "/api/harvest/verify": ("Audit and logs", "Check the harvest log's chain", "Recomputes the hash chain: proves no entry was changed "
                            "or removed.", {}, "read", "apps"),
    "/api/panel/audit": ("Audit and logs", "The Control Panel's audit trail", "Every action taken from the panel (buttons, assistant, "
                         "API), newest first.", {}, "read", "control"),
    "/api/panel/alerts": ("Audit and logs", "Alerts", "What the monitor found (stopped applications, failing harvests, filters too "
                          "strict).", {}, "read", "control"),
    # outside connections
    "/api/connections": ("Outside connections", "Every outside service", "Each service the suite connects to: what for, which "
                         "program, the key it needs (set or not — never the key), the registry source and when it was last used.",
                         {}, "read", "control"),
    "/api/connections/test": ("Outside connections", "Test a connection", "One request to the service's public address, without "
                              "any key (free): reachable, how fast. all: true tests every one.", {"id": "wikidata-api"}, "read", "control"),
    # about
    "/api/self/ask": ("About QueryBook", "Ask QueryBook about itself", "An answer from its design document, checked against its own "
                      "files, with sources and status (built, partly built, specified).", {"q": "what can you harvest?"}, "read", "all"),
    "/api/routes": ("About QueryBook", "Every endpoint of a program", "This list, from the program itself, with the parameters its "
                    "code reads.", {}, "read", "all"),
    "/api/openapi.json": ("About QueryBook", "OpenAPI description", "The same list as an OpenAPI 3 document, for API tools (Postman, "
                          "Insomnia, code generators).", {}, "read", "all"),
}

# the tasks people do, in order: each is one call (program, method, path, parameters)
RECIPES = [
    ("How many facts do we have — right now?", "control", "GET", "/api/panel/ticker", {}),
    ("Find facts about a subject", "control", "POST", "/api/panel/search", {"q": "Einstein", "limit": 20}),
    ("Look up a compound, a place or a date in the bulk facts", "control", "GET", "/api/bulk/search", {"q": "Year 2030"}),
    ("Start all harvesting", "control", "POST", "/api/harvest/master", {"on": True}),
    ("Stop all harvesting", "control", "POST", "/api/harvest/master", {"on": False}),
    ("See the bulk agents and datasets", "control", "GET", "/api/bulk", {}),
    ("Start the calendar scaffold and US place names (bulk)", "control", "POST", "/api/bulk/start",
     {"datasets": ["calendar-scaffold", "usgs-gnis"], "agents": 2, "passphrase": ""}),
    ("Run a History & News harvest turn now", "facts", "POST", "/api/commons/run", {}),
    ("Read the latest harvest log entries", "facts", "POST", "/api/harvest/log", {"limit": 20}),
]


def doc(path):
    d = DOCS.get(path)
    if not d:
        return None
    group, title, text, example, kind, where = d
    return {"group": group, "title": title, "text": text, "example": example, "kind": kind, "where": where}
