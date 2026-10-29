"""qbconnections — every outside service the QueryBook suite connects to, on one page (Control Panel → API & connections).

One catalogue: what each connection is for, which program uses it, how it authenticates (none, a free key, a paid key, a
service account), where its key is kept (never shown — only whether it is set), the policy-registry source it serves,
when the harvest log last used it, and a reachability test (one request to a public address, never with a key, so a test
costs nothing). Standard library only.
"""
import json, os, time, urllib.error, urllib.parse, urllib.request

VERSION = "1.0.0"
UA = "QueryBook-connections/%s (+https://github.com/ghoward333777-png/projectx; reachability test)" % VERSION

# category, id, name, used by, purpose, test url, auth, key (api-keys.json service) or where the key is kept, registry source, docs
_C = [
    # open-data sources read page by page (online harvesters, qbonline)
    ("Open data (harvesters)", "wikidata-api", "Wikidata API", "all three", "countries, languages, battles, treaties, rivers, compounds …",
     "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q42&props=labels&languages=en&format=json", "none", None, "wikidata",
     "https://www.wikidata.org/wiki/Wikidata:Data_access"),
    ("Open data (harvesters)", "natural-earth", "Natural Earth (GitHub)", "History & News", "cities and towns with coordinates",
     "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/README.md", "none", None, "natural-earth", "https://www.naturalearthdata.com/"),
    ("Open data (harvesters)", "frus", "Office of the Historian (FRUS)", "History & News", "Foreign Relations of the United States volumes",
     "https://history.state.gov/", "none", None, "frus", "https://history.state.gov/developer"),
    ("Open data (harvesters)", "met-api", "The Met Collection API", "History & News", "highlighted artworks",
     "https://collectionapi.metmuseum.org/public/collection/v1/departments", "none", None, "met-open-access", "https://metmuseum.github.io/"),
    ("Open data (harvesters)", "ncbi-eutils", "NCBI E-utilities", "STEM", "species with common names",
     "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?retmode=json", "none", None, "ncbi-taxonomy", "https://www.ncbi.nlm.nih.gov/books/NBK25501/"),
    ("Open data (harvesters)", "usgs-earthquakes", "USGS earthquake catalog", "STEM", "major earthquakes since 1900",
     "https://earthquake.usgs.gov/fdsnws/event/1/version", "none", None, "usgs-earthquakes", "https://earthquake.usgs.gov/fdsnws/event/1/"),
    ("Open data (harvesters)", "federal-register", "Federal Register API", "History & News", "executive orders and proclamations",
     "https://www.federalregister.gov/api/v1/documents.json?per_page=1", "none", None, "federal-register", "https://www.federalregister.gov/developers"),
    ("Open data (harvesters)", "pubchem-rest", "PubChem PUG REST", "STEM", "compound formula, weight, IUPAC name",
     "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/property/MolecularFormula/JSON", "none", None, "pubchem-computed",
     "https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest"),
    ("Open data (harvesters)", "smithsonian", "Smithsonian Open Access API", "STEM, History & News", "CC0 museum records",
     "https://api.si.edu/openaccess/api/v1.0/", "free key", "api.data.gov", "smithsonian-open-access", "https://edan.si.edu/openaccess/apidocs/"),
    ("Open data (harvesters)", "usda-fdc-api", "USDA FoodData Central API", "STEM", "food composition",
     "https://api.nal.usda.gov/fdc/v1/", "free key", "api.data.gov", "usda-fooddata-central", "https://fdc.nal.usda.gov/api-guide"),
    ("Open data (harvesters)", "nara-api", "National Archives Catalog API", "History & News", "unrestricted archival records",
     "https://catalog.archives.gov/api/v2/", "free key", "nara", "nara-catalog", "https://www.archives.gov/research/catalog/help/api"),
    ("Open data (harvesters)", "dpla-api", "DPLA API", "History & News", "library records by topic", "https://api.dp.la/v2/", "free key", "dpla",
     "dpla-metadata", "https://pro.dp.la/developers"),
    ("Open data (harvesters)", "europeana-api", "Europeana API", "History & News", "cultural heritage records",
     "https://api.europeana.eu/record/v2/search.json", "free key", "europeana", "europeana-metadata", "https://pro.europeana.eu/page/apis"),
    # whole files (bulk harvesting, qbbulk)
    ("Bulk datasets", "ncbi-ftp", "NCBI FTP over HTTPS (PubChem, Taxonomy)", "Control Panel bulk agents", "compound properties, taxonomy",
     "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/", "none", None, "pubchem-computed", "https://ftp.ncbi.nlm.nih.gov/"),
    ("Bulk datasets", "noaa-ncei", "NOAA NCEI (GHCN-Daily)", "Control Panel bulk agents", "daily weather observations",
     "https://www.ncei.noaa.gov/pub/data/ghcn/daily/", "none", None, "noaa", "https://www.ncei.noaa.gov/"),
    ("Bulk datasets", "usgs-gnis-files", "USGS National Map downloads (GNIS)", "Control Panel bulk agents", "US place and feature names",
     "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_National_Text.zip", "none", None, "usgs-gnis",
     "https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data"),
    ("Bulk datasets", "fdc-downloads", "USDA FoodData Central downloads", "Control Panel bulk agents", "foods and nutrients",
     "https://fdc.nal.usda.gov/download-datasets", "none", None, "usda-fooddata-central", "https://fdc.nal.usda.gov/download-datasets"),
    ("Bulk datasets", "tatoeba-downloads", "Tatoeba downloads", "Control Panel bulk agents", "CC0 example sentences",
     "https://downloads.tatoeba.org/exports/", "none", None, "tatoeba-cc0", "https://tatoeba.org/en/downloads"),
    ("Bulk datasets", "wikidata-sparql", "Wikidata Query Service (SPARQL)", "Control Panel bulk agents", "recurring-event slots, one query a series",
     "https://query.wikidata.org/sparql?query=ASK%7B%7D&format=json", "none", None, "wikidata", "https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual"),
    ("Bulk datasets", "mit-learn-api", "MIT Learn API (MIT OpenCourseWare catalog)", "Control Panel bulk agents",
     "every free MIT course: number, title, department, instructors, term, topics", "https://api.learn.mit.edu/api/v1/courses/?platform=ocw&limit=1",
     "none", None, "mit-ocw-catalog", "https://ocw.mit.edu/pages/privacy-and-terms-of-use/"),
    ("Bulk datasets", "wikidata-dumps", "Wikidata entity dumps", "Control Panel bulk agents (16 lanes)", "every Wikidata item, streamed in byte ranges",
     "https://dumps.wikimedia.org/wikidatawiki/entities/", "none", None, "wikidata", "https://www.wikidata.org/wiki/Wikidata:Database_download"),
    # Google Cloud and Gemini
    ("Google", "google-stt", "Google Speech-to-Text", "Language Builder", "transcripts with word times", "https://speech.googleapis.com/",
     "paid key", "Language Builder → Settings → Google", None, "https://cloud.google.com/speech-to-text/docs"),
    ("Google", "google-tts", "Google Text-to-Speech", "Language Builder", "spoken words and lessons", "https://texttospeech.googleapis.com/",
     "paid key", "Language Builder → Settings → Google", None, "https://cloud.google.com/text-to-speech/docs"),
    ("Google", "google-storage", "Google Cloud Storage", "all four", "backup mirror", "https://storage.googleapis.com/", "service account",
     "each program → Diagnostics → Google Cloud", None, "https://cloud.google.com/storage/docs"),
    ("Google", "google-monitoring", "Google Cloud Monitoring", "all four", "health metrics", "https://monitoring.googleapis.com/", "service account",
     "each program → Diagnostics → Google Cloud", None, "https://cloud.google.com/monitoring/docs"),
    ("Google", "youtube-data", "YouTube Data API", "History & News", "video sources", "https://www.googleapis.com/youtube/v3/", "paid key",
     "History & News → Settings", None, "https://developers.google.com/youtube/v3"),
    ("Google", "gemini", "Google Gemini API", "exemplar generator, fact gatherer (outside the applications)",
     "exemplar clips and images; web-grounded fact gathering", "https://generativelanguage.googleapis.com/", "paid key", "gemini", None,
     "https://ai.google.dev/gemini-api/docs"),
    # voices and video (Language Builder; consent-gated)
    ("Voice and video", "elevenlabs", "ElevenLabs", "Language Builder", "voices (cloning only with consent)", "https://api.elevenlabs.io/",
     "paid key", "Language Builder → Settings → Speech", None, "https://elevenlabs.io/docs"),
    ("Voice and video", "heygen", "HeyGen", "Language Builder", "talking-photo narration", "https://api.heygen.com/", "paid key",
     "Language Builder → Author persona", None, "https://docs.heygen.com/"),
    ("Voice and video", "d-id", "D-ID", "Language Builder", "talking-photo narration", "https://api.d-id.com/", "paid key",
     "Language Builder → Author persona", None, "https://docs.d-id.com/"),
    # LLM fact gatherers: they find facts on the web; a fact is kept only after the cited page itself confirms it (qbgather)
    ("LLM fact gatherers", "perplexity", "Perplexity (Sonar)", "fact gatherer (outside the applications)", "recent facts with cited pages",
     "https://api.perplexity.ai/", "paid key", "perplexity", "llm-gathered-web", "https://docs.perplexity.ai/"),
    ("LLM fact gatherers", "anthropic", "Anthropic Claude (web search)", "fact gatherer (outside the applications)", "recent facts with cited pages",
     "https://api.anthropic.com/", "paid key", "anthropic", "llm-gathered-web", "https://platform.claude.com/docs/"),
    ("LLM fact gatherers", "openai", "OpenAI (web search)", "fact gatherer (outside the applications)", "recent facts with cited pages",
     "https://api.openai.com/", "paid key", "openai", "llm-gathered-web", "https://platform.openai.com/docs/"),
    ("LLM fact gatherers", "gemini-grounding", "Google Gemini with Google Search", "fact gatherer (outside the applications)",
     "recent facts with cited pages", "https://generativelanguage.googleapis.com/", "paid key", "gemini", "llm-gathered-web",
     "https://ai.google.dev/gemini-api/docs/google-search"),
    # monitoring
    ("Monitoring", "github", "GitHub (issues for diagnostics)", "all four", "report problems to the project's repository",
     "https://api.github.com/", "token", "each program → Diagnostics → GitHub", None, "https://docs.github.com/rest"),
]
FIELDS = ("category", "id", "name", "used_by", "purpose", "test_url", "auth", "key", "registry", "docs")
CATALOG = [dict(zip(FIELDS, row)) for row in _C]


def connections(commons=None, key_services=None):
    """the catalogue with live state: key set (never the key), registry approval, last use in the harvest log"""
    import qbonline as ol
    keys = ol.load_keys(commons.folder) if commons is not None else {}
    services = key_services or ol.KEY_SERVICES
    last = {}
    if commons is not None:
        for r in commons.store.query("SELECT source_key, max(at) AS at, count(*) AS n FROM harvest_log WHERE decision = 'harvested' GROUP BY source_key"):
            last[r["source_key"]] = (r["at"], r["n"])
    out = []
    for c in CATALOG:
        row = dict(c)
        if c["key"] in services:
            row["key_status"] = "set" if c["key"] in keys else "not set"
            row["key_where"] = "Harvesting page → API keys (%s)" % services[c["key"]]["title"]
        elif c["auth"] == "none":
            row["key_status"], row["key_where"] = "no key needed", ""
        else:
            row["key_status"], row["key_where"] = "kept in the program", c["key"] or ""
        if c["registry"] and commons is not None:
            ok, cls, why = commons.registry.check(c["registry"])
            row["approved"], row["licence_class"] = ok, cls
        else:
            row["approved"], row["licence_class"] = None, None
        row["last_used"], row["uses"] = last.get(c["registry"], (None, 0)) if c["registry"] else (None, 0)
        out.append(row)
    return out


def test(conn_id, timeout=10):
    """one request to the connection's public address, without any key: reachable? how fast? (401/403 = reachable, needs a key)"""
    c = next((x for x in CATALOG if x["id"] == conn_id), None)
    if c is None:
        raise ValueError("unknown connection")
    t0 = time.time()
    req = urllib.request.Request(c["test_url"], headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(4096)
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        return {"id": conn_id, "reachable": False, "status": None, "ms": int((time.time() - t0) * 1000), "detail": type(e).__name__ + ": " + str(e)[:200]}
    ms = int((time.time() - t0) * 1000)
    reach = code < 500                                  # any answer below 500 means the service is there and talking
    detail = {401: "reachable — needs a key", 403: "reachable — needs a key or refuses anonymous requests",
              404: "reachable — its root address has no page (normal for an API)", 421: "reachable — needs a proper API request",
              429: "reachable — asking us to slow down"}.get(code, "reachable" if reach else "the service answered with an error (%d)" % code)
    return {"id": conn_id, "reachable": reach, "status": code, "ms": ms, "detail": detail}


def add_routes(api, commons):
    @api.get("/api/connections")
    def conns(p):
        """every outside service the suite connects to: purpose, key set or not, approval, last use"""
        rows = connections(commons)
        return {"connections": rows, "categories": list(dict.fromkeys(r["category"] for r in rows)), "version": VERSION}

    @api.post("/api/connections/test")
    def conns_test(p):
        """test one connection (or all with all: true): one keyless request each"""
        import concurrent.futures
        ids = [x["id"] for x in CATALOG] if p.get("all") else [p.get("id")]
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            return {"results": list(ex.map(lambda i: test(i), ids))}


# ------------------------------------------------------------------------------------------------ one-click Google setup
def google_folders(program_dir, own_folder=None):
    """every QueryBook application's data folder on this computer (where its private Google settings live)"""
    import qbcore as core
    root = os.path.dirname(program_dir)
    out = {a: core.data_folder(a, os.path.join(root, a)) for a in ("language", "stem", "facts")}
    if own_folder:
        out["control"] = own_folder
    return out


def google_setup_status(commons, program_dir, own_folder=None):
    import gcloud
    path = os.path.join(commons.folder, "google-setup-run.json")
    try:
        with open(path) as f:
            run = json.load(f)
    except (OSError, ValueError):
        run = None
    if run:
        run["alive"] = not run.get("finished") and time.time() - run.get("heartbeat", 0) < 1200
    apps = {a: gcloud.Settings(f).public() for a, f in google_folders(program_dir, own_folder).items()}
    return {"gcloud": bool(gcloud.find_gcloud()), "install": gcloud.GCLOUD_INSTALL, "run": run,
            "apps": {a: {"api_key_set": v["api_key_set"], "project_id": v["project_id"], "backups": bool(v["service_account"])} for a, v in apps.items()}}


def google_setup_start(commons, passphrase, program_dir, own_folder=None):
    """admin: run the one-click setup as its own process (it waits for the user to press Allow on Google's page)"""
    import subprocess, sys, gcloud
    commons.approvals._require(passphrase or "")
    st = google_setup_status(commons, program_dir, own_folder)
    if st["run"] and st["run"]["alive"]:
        return dict(st, summary="the Google setup is already running")
    if not st["gcloud"]:
        return dict(st, summary="Install Google's command-line tool (gcloud) on this computer first: " + gcloud.GCLOUD_INSTALL)
    path = os.path.join(commons.folder, "google-setup-run.json")
    kw = {"creationflags": 0x00000008 | 0x00000200} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen([sys.executable, os.path.join(program_dir, "gcloud.py"), "--folders", json.dumps(google_folders(program_dir, own_folder)),
                      "--commons", commons.folder, "--status", path], cwd=program_dir, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    with commons.store.write() as db:
        commons.agent_log(db, "control", "One-click Google setup started")
    return dict(st, summary="Google setup started — a Google sign-in page opens on this computer: choose your account and press Allow")


def add_google_setup(api, commons, program_dir, own_folder=None):
    @api.get("/api/google/setup")
    def gs_status(p):
        return google_setup_status(commons, program_dir, own_folder)

    @api.post("/api/google/setup")
    def gs_start(p):
        return google_setup_start(commons, p.get("passphrase"), program_dir, own_folder)


# ------------------------------------------------------------------------------------------------ API registration
# For every service that needs a key: where to sign up (and whether "Sign in with Google" is offered there), what it costs,
# where QueryBook keeps the key, and a check WITH the key that costs nothing (a free read, or a request the service refuses
# for a missing body — a bad key is refused earlier, with 401/403). The person signs up and accepts each service's terms;
# QueryBook never signs up for them.
# id: (title, cost, sign-up page, Google sign-in, store, check: (method, url with {k}, headers with {k}, body))
REGISTRATION = {
    "api.data.gov": ("api.data.gov — Smithsonian and USDA FoodData", "free", "https://api.data.gov/signup/", False, "commons:api.data.gov",
                     ("GET", "https://api.nal.usda.gov/fdc/v1/foods/search?query=apple&pageSize=1&api_key={k}", {}, None)),
    "europeana": ("Europeana", "free", "https://pro.europeana.eu/pages/get-api", False, "commons:europeana",
                  ("GET", "https://api.europeana.eu/record/v2/search.json?query=moon&rows=1&wskey={k}", {}, None)),
    "dpla": ("Digital Public Library of America", "free", "https://pro.dp.la/developers/policies", False, "commons:dpla",
             ("GET", "https://api.dp.la/v2/items?q=moon&page_size=1&api_key={k}", {}, None)),
    "nara": ("US National Archives Catalog", "free", "mailto:Catalog_API@nara.gov?subject=Catalog%20API%20v2%20key%20request", False, "commons:nara",
             None),                                     # the catalog answers without a key too: nothing to check it against
    "youtube": ("YouTube Data API v3", "free (10,000 units a day)", "https://console.cloud.google.com/apis/credentials", True, "google:youtube_key",
                ("GET", "https://www.googleapis.com/youtube/v3/videos?part=id&id=dQw4w9WgXcQ&key={k}", {}, None)),
    "gemini": ("Google Gemini — fact gatherer, exemplar tools", "paid per use", "https://aistudio.google.com/apikey", True, "commons:gemini",
               ("GET", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1&key={k}", {}, None)),
    "openai": ("OpenAI — fact gatherer", "paid per use", "https://platform.openai.com/api-keys", True, "commons:openai",
               ("GET", "https://api.openai.com/v1/models", {"Authorization": "Bearer {k}"}, None)),
    "anthropic": ("Anthropic Claude — fact gatherer", "paid per use", "https://platform.claude.com/settings/keys", True, "commons:anthropic",
                  ("GET", "https://api.anthropic.com/v1/models", {"x-api-key": "{k}", "anthropic-version": "2023-06-01"}, None)),
    "perplexity": ("Perplexity — fact gatherer", "paid per use", "https://www.perplexity.ai/account/api", True, "commons:perplexity",
                   ("POST", "https://api.perplexity.ai/v1/agent", {"Authorization": "Bearer {k}", "Content-Type": "application/json"}, b"{}")),
    "elevenlabs": ("ElevenLabs — voices", "free tier, then paid", "https://elevenlabs.io/app/settings/api-keys", True, "language:elevenlabs",
                   ("GET", "https://api.elevenlabs.io/v1/voices", {"xi-api-key": "{k}"}, None)),
    "heygen": ("HeyGen — talking-photo video", "paid", "https://app.heygen.com/settings?nav=API", True, "language:heygen",
               ("GET", "https://api.heygen.com/v2/user/remaining_quota", {"X-Api-Key": "{k}"}, None)),
    "did": ("D-ID — talking-photo video", "free trial, then paid", "https://studio.d-id.com/account-settings", True, "language:did",
            ("GET", "https://api.d-id.com/credits", {"Authorization": "Basic {k}"}, None)),
}
DPLA_REQUEST = "https://api.dp.la/v2/api_key/"


def _stored(store, commons, folders):
    import qbonline as ol, gcloud
    kind, _, name = store.partition(":")
    if kind == "commons":
        return ol.load_keys(commons.folder).get(name) or ""
    if kind == "google":
        return gcloud.Settings(folders["facts"]).load().get(name) or ""
    if kind == "language":
        try:
            with open(os.path.join(folders["language"], "speech_keys.json"), encoding="utf-8") as f:
                return ((json.load(f) or {}).get(name) or {}).get("api_key") or ""
        except (OSError, ValueError):
            return ""
    return ""


def _store(store, key, commons, folders):
    import qbonline as ol, gcloud
    kind, _, name = store.partition(":")
    if kind == "commons":
        ol.save_key(commons.folder, name, key)
    elif kind == "google":
        for f in folders.values():
            os.makedirs(f, exist_ok=True)
            gcloud.Settings(f).save({name: key})
    elif kind == "language":
        path = os.path.join(folders["language"], "speech_keys.json")
        os.makedirs(folders["language"], exist_ok=True)
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except (OSError, ValueError):
            cfg = {}
        cfg.setdefault(name, {})["api_key"] = key
        fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        os.replace(path + ".tmp", path)


def check_key(reg_id, key, opener=None):
    """one request WITH the key that costs nothing: works / refused (bad key) / unreachable. Never returns the key."""
    if REGISTRATION[reg_id][5] is None:
        return {"id": reg_id, "works": None, "why": "saved — this service answers without a key, so it cannot be checked here"}
    method, url, headers, body = REGISTRATION[reg_id][5]
    q = urllib.parse.quote(key, safe="")
    req = urllib.request.Request(url.replace("{k}", q), data=body, method=method,
                                 headers=dict({"User-Agent": UA}, **{h: v.replace("{k}", key) for h, v in headers.items()}))
    t0 = time.time()
    try:
        with (opener or urllib.request.urlopen)(req, timeout=20) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            text = e.read(4000).decode("utf-8", "replace").lower()
        except Exception:
            text = ""
        if any(w in text for w in ("api key not valid", "api_key_invalid", "invalid api key", "invalid_api_key", "incorrect api key")):
            return {"id": reg_id, "works": False, "code": code, "why": "refused the key (HTTP %d: not a valid key)" % code, "ms": round((time.time() - t0) * 1000)}
    except Exception as e:
        return {"id": reg_id, "works": None, "why": "could not reach the service: %s" % type(e).__name__}
    works = code < 400 or code in (400, 404, 405, 422)       # refused for the request, not for the key
    why = "accepted" if works else "refused the key (HTTP %d)" % code
    if code == 429:
        works, why = True, "accepted (the service says: slow down)"
    return {"id": reg_id, "works": works, "code": code, "why": why, "ms": round((time.time() - t0) * 1000)}


def registration(commons, folders):
    out = []
    for rid, (title, cost, signup, google, store, _chk) in REGISTRATION.items():
        k = _stored(store, commons, folders)
        out.append({"id": rid, "title": title, "cost": cost, "signup": signup, "google_sign_in": google, "set": bool(k),
                    "hint": ("…" + k[-4:]) if k else "", "kept": store.split(":")[0]})
    return out


def add_registration(api, commons, program_dir, own_folder=None):
    folders = google_folders(program_dir, own_folder)

    def _admin(p):
        if commons.approvals.admin_set():
            commons.approvals._require(p.get("passphrase") or "")

    @api.get("/api/registration")
    def reg_list(p):
        return {"services": registration(commons, folders), "google": "Speech, Text-to-Speech, backups and health reports: "
                "use Google — one-click setup above"}

    @api.post("/api/registration/save")
    def reg_save(p):
        """save a key the person created (admin passphrase once one is set), then check it with one free request"""
        import qbcore as core
        rid, key = p.get("id"), "".join(str(p.get("key") or "").split())
        if rid not in REGISTRATION:
            raise core.UserError("Unknown service.")
        if not key:
            raise core.UserError("Paste the key first.")
        _admin(p)
        res = check_key(rid, key)
        if res["works"] is False and not p.get("save_anyway"):
            return dict(res, saved=False)
        _store(REGISTRATION[rid][4], key, commons, folders)
        with commons.store.write() as db:
            commons.agent_log(db, "control", "API key saved for %s (%s)" % (REGISTRATION[rid][0], res["why"]))
        return dict(res, saved=True)

    @api.post("/api/registration/test")
    def reg_test(p):
        import qbcore as core
        rid = p.get("id")
        if rid not in REGISTRATION:
            raise core.UserError("Unknown service.")
        k = _stored(REGISTRATION[rid][4], commons, folders)
        return check_key(rid, k) if k else {"id": rid, "works": None, "why": "no key saved yet"}

    @api.post("/api/registration/dpla")
    def reg_dpla(p):
        """DPLA's own way to issue a key: it is emailed to the address given (sent only at the person's request)"""
        import qbcore as core, re
        email = (p.get("email") or "").strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise core.UserError("Type your email address.")
        _admin(p)
        req = urllib.request.Request(DPLA_REQUEST + urllib.parse.quote(email), data=b"", method="POST", headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            return {"ok": False, "why": "could not reach DPLA: %s" % type(e).__name__}
        return {"ok": code < 400, "why": "DPLA is emailing your key — paste it here when it arrives" if code < 400 else "DPLA refused (HTTP %d)" % code}


def self_test():
    out = []
    ok = lambda n, c: out.append((n, bool(c)))
    ids = [c["id"] for c in CATALOG]
    ok("every connection has a unique id, a test address and a purpose", len(ids) == len(set(ids)) and all(c["test_url"].startswith("https://")
                                                                                                           and c["purpose"] for c in CATALOG))
    ok("keys are named, never stored here", not any(len(str(c["key"] or "")) > 60 for c in CATALOG))
    import tempfile, types, shutil, io
    tmp = tempfile.mkdtemp()
    try:
        folders = {a_: os.path.join(tmp, a_) for a_ in ("language", "stem", "facts", "control")}
        com = types.SimpleNamespace(folder=tmp)
        for rid, key in (("openai", "sk-TESTKEY-0001"), ("youtube", "AIzaYOUTUBE-TEST-0001"), ("elevenlabs", "el-TEST-0001")):
            _store(REGISTRATION[rid][4], key, com, folders)
        import gcloud
        rows = {r["id"]: r for r in registration(com, folders)}
        ok("registration: keys kept where each program reads them (shared key file, every app's Google settings, the "
           "Language Builder's voice keys), shown only as their last four characters",
           rows["openai"]["hint"] == "…0001" and rows["youtube"]["set"] and rows["elevenlabs"]["set"] and not rows["perplexity"]["set"]
           and gcloud.Settings(folders["stem"]).youtube_key() == "AIzaYOUTUBE-TEST-0001"
           and "sk-TESTKEY" not in json.dumps(list(rows.values())))
        def bad400(req, timeout=20):
            raise urllib.error.HTTPError(req.full_url, 400, "x", {}, io.BytesIO(b'{"error": {"message": "API key not valid. Please pass a valid API key."}}'))
        ok("registration: a 400 that says the key is not valid counts as refused; a service that needs no key is saved unchecked",
           check_key("gemini", "k", bad400)["works"] is False and check_key("nara", "k")["works"] is None)
        class _R(io.BytesIO):
            def __init__(self, code): super().__init__(b"{}"); self.status = code
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def op(code):
            def f(req, timeout=20):
                if code >= 400:
                    raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
                return _R(code)
            return f
        ok("registration: a key is judged by the service's answer — 200 works, 401/403 refused, 400 for an empty request "
           "still means the key was accepted", check_key("openai", "k", op(200))["works"] and check_key("openai", "k", op(401))["works"] is False
           and check_key("perplexity", "k", op(400))["works"] and check_key("anthropic", "k", op(403))["works"] is False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    res = self_test()
    for n, g in res:
        print(("  [OK]   " if g else "  [FAIL] ") + n)
    print("\n  %d of %d checks passed" % (sum(1 for x in res if x[1]), len(res)))
    sys.exit(0 if all(x[1] for x in res) else 1)
