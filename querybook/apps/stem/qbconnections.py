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
    ("Bulk datasets", "wikidata-dumps", "Wikidata entity dumps", "bulk agents (planned)", "every Wikidata item, streamed",
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


def self_test():
    out = []
    ok = lambda n, c: out.append((n, bool(c)))
    ids = [c["id"] for c in CATALOG]
    ok("every connection has a unique id, a test address and a purpose", len(ids) == len(set(ids)) and all(c["test_url"].startswith("https://")
                                                                                                           and c["purpose"] for c in CATALOG))
    ok("keys are named, never stored here", not any(len(str(c["key"] or "")) > 60 for c in CATALOG))
    return out
