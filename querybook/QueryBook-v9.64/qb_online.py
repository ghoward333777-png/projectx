"""Online harvesters: facts from the researched sources the admin approved (see qbharvest.RESEARCHED_SOURCES).

Each harvester reads one open, unrestricted source over the internet and turns it into facts. They keep to the
registry's rules: a harvester runs only while its source is approved, it stores facts and never the source's wording,
and each fact's evidence names the source, its licence and the page it came from. Requests are polite (one at a
time, a pause between calls to the same site, a named user agent); a site that answers "too many requests" ends the
task for this turn and the engine's backoff gives it time.

Offline: set QB_OFFLINE=1, or switch online harvesting off on the Harvesting page (setting online:<app> = off).
"""
import json, os, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

VERSION = "1.0.0"
UA = "QueryBook-harvester/%s (+https://github.com/ghoward333777-png/projectx; personal research tool; one request at a time)" % VERSION
MIN_GAP_S = 1.0                     # pause between requests to the same site
_last = {}


class SourceBusy(Exception):
    """The site asked us to slow down (HTTP 429/503) or is unreachable; try again on a later turn."""


def _fetch(url, kind="json", timeout=60, headers=None):
    host = urllib.parse.urlsplit(url).netloc
    wait = MIN_GAP_S - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA, "Accept": "application/json" if kind == "json" else "*/*"}, **(headers or {})))
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                raise SourceBusy("%s asked to slow down (HTTP %d)" % (host, e.code))
            if e.code in (401, 403):
                raise SourceBusy("%s refused the API key (HTTP %d): check it on the Harvesting page" % (host, e.code))
            raise SourceBusy("%s answered HTTP %d" % (host, e.code))    # never the URL: it may carry an API key
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == 2:
                raise SourceBusy("%s unreachable: %s" % (host, e))
            time.sleep(3)
        finally:
            _last[host] = time.time()
    return json.loads(body) if kind == "json" else body


FETCH = _fetch                      # tests replace this


def enabled(ctx):
    return not os.environ.get("QB_OFFLINE") and ctx.commons.setting("online:%s" % ctx.commons.app_id, "on") != "off"


def _item(subject, predicate, obj, key, name, licence, url, why):
    return {"subject": subject, "predicate": predicate, "object": str(obj),
            "evidence": [{"method": "reference", "source": name, "licence": licence, "url": url, "source_key": key}],
            "reasoning": [why]}


# ---------------------------------------------------------------------------------------------------- Wikidata (CC0)
WD_API = "https://www.wikidata.org/w/api.php?"
WD_NAME, WD_LIC = "Wikidata", "CC0 1.0 (Wikidata structured data)"


def _wd(params):
    return FETCH(WD_API + urllib.parse.urlencode(dict(params, format="json", maxlag=5)))


def _wd_search(statement, offset, limit):
    """Item ids with a statement, the most linked-to first (the ones people ask about)."""
    r = _wd({"action": "query", "list": "search", "srsearch": "haswbstatement:" + statement, "srnamespace": 0,
             "srlimit": limit, "sroffset": offset, "srsort": "incoming_links_desc", "srprop": ""})
    hits = [h["title"] for h in r.get("query", {}).get("search", [])]
    total = r.get("query", {}).get("searchinfo", {}).get("totalhits", 0)
    return hits, total


def _wd_entities(ids, props="labels|claims"):
    out = {}
    for i in range(0, len(ids), 50):
        r = _wd({"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": props, "languages": "en"})
        out.update(r.get("entities", {}))
    return out


def _label(e):
    return ((e or {}).get("labels", {}).get("en") or {}).get("value")


def _values(e, prop):
    vals = []
    for c in (e.get("claims") or {}).get(prop, []):
        if c.get("rank") == "deprecated":
            continue
        dv = (c.get("mainsnak") or {}).get("datavalue")
        if dv:
            vals.append(dv["value"])
    return vals


def _year(v):
    """A Wikidata time value as text: year, month or day precision (no invented precision)."""
    t, prec = v.get("time", ""), v.get("precision", 9)
    sign, rest = t[0], t[1:]
    y, m, d = rest[:rest.index("-")], rest[rest.index("-") + 1:][:2], rest[rest.index("-") + 4:][:2]
    y = str(int(y))
    if sign == "-":
        y += " BC"
    if prec >= 11:
        return "%s-%s-%s" % (y, m, d)
    if prec == 10:
        return "%s-%s" % (y, m)
    return y


def _wikidata(statement, build, cursor, budget):
    ids, total = _wd_search(statement, cursor, min(int(budget), 50))
    if not ids:
        return [], None, "finished"
    ents = _wd_entities(ids)
    refs = sorted({v["id"] for e in ents.values() for p in ("P36", "P30", "P287", "P178", "P282", "P17", "P276", "P361", "P403", "P556", "P710") for v in _values(e, p)
                   if isinstance(v, dict) and "id" in v})
    names = {k: _label(v) for k, v in _wd_entities(refs, "labels").items()} if refs else {}
    items = []
    for qid in ids:
        e = ents.get(qid)
        if e and _label(e):
            items += build(qid, e, names)
    nxt = cursor + len(ids)
    return items, (nxt if nxt < min(total, 10000) else None), "%d items from Wikidata (%d–%d of %d)" % (len(items), cursor + 1, nxt, total)


def _wd_url(qid):
    return "https://www.wikidata.org/wiki/" + qid


def _wd_item(qid, subject, predicate, obj, what):
    return _item(subject, predicate, obj, "wikidata", WD_NAME, WD_LIC, _wd_url(qid), "Wikidata %s: %s." % (qid, what))


def _countries(qid, e, names):
    n, out = _label(e), []
    for v in _values(e, "P36"):
        if names.get(v.get("id")):
            out.append(_wd_item(qid, "country " + n, "capital", names[v["id"]], "capital (P36)"))
    for v in _values(e, "P30"):
        if names.get(v.get("id")):
            out.append(_wd_item(qid, "country " + n, "continent", names[v["id"]], "continent (P30)"))
    for v in _values(e, "P297")[:1]:
        out.append(_wd_item(qid, "country " + n, "ISO 3166-1 code", v, "ISO 3166-1 alpha-2 code (P297)"))
    return out


def _prog_languages(qid, e, names):
    n, out = _label(e), []
    for v in _values(e, "P571")[:1]:
        out.append(_wd_item(qid, "programming language " + n, "first appeared", _year(v), "inception (P571)"))
    for p, pred in (("P287", "designed by"), ("P178", "developed by")):
        for v in _values(e, p)[:3]:
            if names.get(v.get("id")):
                out.append(_wd_item(qid, "programming language " + n, pred, names[v["id"]], "%s (%s)" % (pred, p)))
    return out


def _compounds(qid, e, names):
    n, out = _label(e), []
    for v in _values(e, "P274")[:1]:
        out.append(_wd_item(qid, "compound " + n, "chemical formula", v, "chemical formula (P274)"))
    for v in _values(e, "P231")[:1]:
        out.append(_wd_item(qid, "compound " + n, "CAS number", v, "CAS Registry Number (P231)"))
    return out


def _languages(qid, e, names):
    n, out = _label(e), []
    for v in _values(e, "P220")[:1]:
        out.append(_wd_item(qid, "language " + n, "ISO 639-3 code", v, "ISO 639-3 code (P220)"))
    for v in _values(e, "P282")[:3]:
        if names.get(v.get("id")):
            out.append(_wd_item(qid, "language " + n, "writing system", names[v["id"]], "writing system (P282)"))
    return out


def _qty(v):
    """a Wikidata quantity with its unit, as stated (km, m or none); None for units we do not name"""
    amt, unit = v.get("amount", "").lstrip("+"), v.get("unit", "1")
    u = {"1": "", "http://www.wikidata.org/entity/Q828224": " km", "http://www.wikidata.org/entity/Q11573": " m"}.get(unit)
    return None if u is None or not amt else amt + u


def _named(qid, e, names, subj, prop, pred, n=3):
    return [_wd_item(qid, subj, pred, names[v["id"]], "%s (%s)" % (pred, prop)) for v in _values(e, prop)[:n]
            if isinstance(v, dict) and names.get(v.get("id"))]


def _when(qid, e, subj, pred="date"):
    for p in ("P585", "P580", "P571"):
        for v in _values(e, p)[:1]:
            return [_wd_item(qid, subj, pred, _year(v), "%s (%s)" % ({"P585": "point in time", "P580": "start time", "P571": "inception"}[p], p))]
    return []


def _battles(qid, e, names):
    n = _label(e); subj = n if n.lower().startswith(("battle", "siege")) else "battle " + n
    return _when(qid, e, subj) + _named(qid, e, names, subj, "P276", "location", 2) + _named(qid, e, names, subj, "P361", "part of", 2)


def _treaties(qid, e, names):
    n = _label(e); subj = n if "treaty" in n.lower() else "treaty " + n
    return _when(qid, e, subj, "signed") + _named(qid, e, names, subj, "P276", "signed at", 1)


def _rivers(qid, e, names):
    subj, out = "river " + _label(e), []
    for v in _values(e, "P2043")[:1]:
        q = _qty(v)
        if q:
            out.append(_wd_item(qid, subj, "length", q, "length (P2043)"))
    return out + _named(qid, e, names, subj, "P17", "flows through", 6) + _named(qid, e, names, subj, "P403", "flows into", 1)


def _mountains(qid, e, names):
    subj, out = "mountain " + _label(e), []
    for v in _values(e, "P2044")[:1]:
        q = _qty(v)
        if q:
            out.append(_wd_item(qid, subj, "elevation above sea level", q, "elevation (P2044)"))
    return out + _named(qid, e, names, subj, "P17", "in country", 3)


def _minerals(qid, e, names):
    subj, out = "mineral " + _label(e), []
    for v in _values(e, "P274")[:1]:
        out.append(_wd_item(qid, subj, "chemical formula", v, "chemical formula (P274)"))
    return out + _named(qid, e, names, subj, "P556", "crystal system", 1)


def _scripts(qid, e, names):
    subj, out = "writing system " + _label(e), []
    for v in _values(e, "P506")[:1]:
        out.append(_wd_item(qid, subj, "ISO 15924 code", v, "ISO 15924 code (P506)"))
    return out + _when(qid, e, subj, "first used")


# ---------------------------------------------------------------------------------------------------- US government (public domain)
USGS_EQ = "https://earthquake.usgs.gov/fdsnws/event/1/query?"


def _usgs_quakes(cursor, budget):
    """the strongest recorded earthquakes since 1900, strongest first (USGS ComCat; US government work)"""
    n = min(int(budget), 200)
    r = FETCH(USGS_EQ + urllib.parse.urlencode({"format": "geojson", "starttime": "1900-01-01", "minmagnitude": 6.5,
                                                "orderby": "magnitude", "limit": n, "offset": cursor + 1}))
    feats, items = r.get("features") or [], []
    for f in feats:
        p, g = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or []
        if p.get("mag") is None or not p.get("time"):
            continue
        day = time.strftime("%Y-%m-%d", time.gmtime(p["time"] / 1000))
        subj = "earthquake %s (%s)" % ((p.get("place") or "unknown place")[:120], day)
        url = p.get("url") or "https://earthquake.usgs.gov/earthquakes/search/"
        why = "USGS earthquake catalog event %s." % f.get("id")
        mk = lambda pred, obj: _item(subj, pred, obj, "usgs-earthquakes", "USGS Earthquake Catalog (ComCat)", "US government work", url, why)
        items += [mk("magnitude", "%s %s" % (p["mag"], p.get("magType") or "")), mk("date (UTC)", day)]
        if len(g) >= 3:
            items += [mk("coordinates", "%.3f, %.3f" % (g[1], g[0])), mk("depth", "%.0f km" % g[2])]
        if p.get("tsunami"):
            items.append(mk("tsunami flag", "yes (catalog flag)"))
    nxt = cursor + len(feats)
    return items, (nxt if len(feats) == n else None), "%d earthquakes of magnitude 6.5+ (%d–%d, strongest first)" % (len(feats), cursor + 1, nxt)


FR_API = "https://www.federalregister.gov/api/v1/documents.json?"


def _federal_register(cursor, budget):
    """presidential documents in the Federal Register since 1994 (executive orders, proclamations), oldest first"""
    n = min(int(budget), 100)
    q = [("per_page", n), ("page", cursor // n + 1), ("order", "oldest"), ("conditions[type][]", "PRESDOCU")] + \
        [("fields[]", f) for f in ("document_number", "title", "publication_date", "signing_date", "subtype", "executive_order_number",
                                   "proclamation_number", "president", "html_url")]
    r = FETCH(FR_API + urllib.parse.urlencode(q))
    docs, items = r.get("results") or [], []
    for d in docs:
        if not d.get("document_number") or not d.get("title"):
            continue
        kind = d.get("subtype") or "Presidential document"
        num = d.get("executive_order_number") or d.get("proclamation_number")
        subj = "%s%s" % (kind, " " + str(num) if num else " (Federal Register %s)" % d["document_number"])
        why = "Federal Register document %s." % d["document_number"]
        mk = lambda pred, obj: _item(subj, pred, obj, "federal-register", "Federal Register (Office of the Federal Register)", "US government work",
                                     d.get("html_url") or "https://www.federalregister.gov/", why)
        items.append(mk("title", d["title"][:300]))
        if d.get("signing_date"):
            items.append(mk("signed", d["signing_date"]))
        if d.get("publication_date"):
            items.append(mk("published", d["publication_date"]))
        if isinstance(d.get("president"), dict) and d["president"].get("name"):
            items.append(mk("issued by", d["president"]["name"]))
    nxt = cursor + len(docs)
    total = int(r.get("count") or 0)
    return items, (nxt if docs and nxt < min(total, 10000) else None), "%d presidential documents (%d–%d of %d)" % (len(docs), cursor + 1, nxt, total)


PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"


def _pubchem(cursor, budget):
    """NCBI-computed properties only (formula, weight, IUPAC name, InChIKey) — never depositor text — lowest CIDs first"""
    n = min(int(budget), 100)
    cids = list(range(cursor + 1, cursor + n + 1))
    r = FETCH(PUG + ",".join(map(str, cids)) + "/property/MolecularFormula,MolecularWeight,IUPACName,InChIKey/JSON")
    items = []
    for p in (r.get("PropertyTable") or {}).get("Properties", []):
        if not p.get("IUPACName"):
            continue
        subj = "compound %s" % p["IUPACName"][:200]
        url = "https://pubchem.ncbi.nlm.nih.gov/compound/%d" % p["CID"]
        why = "PubChem CID %d, computed properties." % p["CID"]
        mk = lambda pred, obj: _item(subj, pred, obj, "pubchem-computed", "PubChem computed properties (NCBI)", "US government work", url, why)
        items += [mk("chemical formula", p.get("MolecularFormula")), mk("molecular weight", "%s g/mol" % p.get("MolecularWeight")),
                  mk("PubChem CID", p["CID"])]
        if p.get("InChIKey"):
            items.append(mk("InChIKey", p["InChIKey"]))
    nxt = cursor + n
    return items, (nxt if nxt < 200000 else None), "%d compounds (CID %d–%d)" % (len({i["subject"] for i in items}), cursor + 1, nxt)


# ---------------------------------------------------------------------------------------------------- the others
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_populated_places_simple.geojson"


def _natural_earth(cursor, budget):
    feats = FETCH(NE_URL)["features"]
    feats.sort(key=lambda f: (-(f["properties"].get("pop_max") or 0), f["properties"].get("name") or ""))   # biggest places first
    part, items = feats[cursor:cursor + int(budget)], []
    for f in part:
        p = f["properties"]
        name, country = p.get("name"), p.get("adm0name")
        if not (name and country):
            continue
        subj = "city %s (%s)" % (name, country)
        why = "Natural Earth 1:50m populated places: %s." % (p.get("featurecla") or "place")
        mk = lambda pred, obj: _item(subj, pred, obj, "natural-earth", "Natural Earth populated places (1:50m)", "Public domain", NE_URL, why)
        items.append(mk("in country", country))
        items.append(mk("coordinates", "%.4f, %.4f" % (float(p["latitude"]), float(p["longitude"]))))
        if p.get("featurecla") == "Admin-0 capital":
            items.append(mk("is capital of", country))
        if p.get("adm1name"):
            items.append(mk("in region", p["adm1name"]))
    nxt = cursor + len(part)
    return items, (nxt if nxt < len(feats) else None), "%d places (%d–%d of %d)" % (len(part), cursor + 1, nxt, len(feats))


FRUS_URL = "https://history.state.gov/open/frus-metadata.xml"
FRUS_NS = "{http://history.state.gov/ns/1.0}"


def _frus(cursor, budget):
    root = ET.fromstring(FETCH(FRUS_URL, kind="bytes"))
    vols = list(root)
    part, items = vols[cursor:cursor + int(budget)], []
    for v in part:
        vid = v.get("id")
        title = " ".join((v.findtext(FRUS_NS + "title[@type='complete']") or "").split())
        if not (vid and title):
            continue
        subj = "FRUS volume %s" % vid
        url = "https://history.state.gov/historicaldocuments/" + vid
        why = "Office of the Historian bibliographic metadata for %s." % vid
        mk = lambda pred, obj: _item(subj, pred, obj, "frus", "Foreign Relations of the United States (Office of the Historian)",
                                     "US government work", url, why)
        items.append(mk("title", title[:300]))
        for tag, pred in (("published", "published"), ("coverage", "covers the years")):
            t = " ".join((v.findtext(FRUS_NS + tag) or "").split())
            if t:
                items.append(mk(pred, t))
    nxt = cursor + len(part)
    return items, (nxt if nxt < len(vols) else None), "%d volumes (%d–%d of %d)" % (len(part), cursor + 1, nxt, len(vols))


MET = "https://collectionapi.metmuseum.org/public/collection/"


def _met(cursor, budget):
    n = min(int(budget), 40)
    s = FETCH(MET + "v1.1/search?" + urllib.parse.urlencode({"isHighlight": "true", "q": "*", "offset": cursor, "limit": n}))
    ids, items = s.get("objectIDs") or [], []
    for oid in ids:
        o = FETCH(MET + "v1/objects/%d" % oid)
        title = (o.get("title") or "").strip()
        if not title:
            continue
        subj = "artwork “%s” (Met %d)" % (title[:150], oid)
        why = "The Met Open Access record %d (%s)." % (oid, o.get("department") or "collection")
        mk = lambda pred, obj: _item(subj, pred, obj, "met-open-access", "The Metropolitan Museum of Art Open Access", "CC0",
                                     o.get("objectURL") or MET, why)
        for field, pred in (("artistDisplayName", "artist"), ("objectDate", "date"), ("medium", "medium"), ("culture", "culture"),
                            ("department", "museum department")):
            if (o.get(field) or "").strip():
                items.append(mk(pred, o[field].strip()[:300]))
    nxt = cursor + len(ids)
    total = s.get("total", 0)
    return items, (nxt if ids and nxt < total else None), "%d highlighted objects (%d–%d of %d)" % (len(ids), cursor + 1, nxt, total)


EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TAXA = ["Mammalia", "Aves", "Lepidosauria", "Testudines", "Crocodylia", "Amphibia", "Actinopterygii", "Chondrichthyes", "Insecta",
        "Magnoliopsida", "Liliopsida", "Pinopsida", "Fungi"]
TAXA_STEP = 10 ** 7                  # cursor = group index × TAXA_STEP + position in the group


def _ncbi(cursor, budget):
    g, pos = divmod(cursor, TAXA_STEP)
    if g >= len(TAXA):
        return [], None, "finished"
    term = "%s[subtree] AND species[rank] AND specified[prop]" % TAXA[g]
    s = FETCH(EUTILS + "esearch.fcgi?" + urllib.parse.urlencode({"db": "taxonomy", "term": term, "retstart": pos,
                                                                  "retmax": min(int(budget), 200), "retmode": "json"}))["esearchresult"]
    ids, total = s.get("idlist") or [], int(s.get("count") or 0)
    items = []
    if ids:
        r = FETCH(EUTILS + "esummary.fcgi?" + urllib.parse.urlencode({"db": "taxonomy", "id": ",".join(ids), "retmode": "json"}))["result"]
        for uid in r.get("uids", []):
            t = r[uid]
            if not t.get("commonname") or t.get("status") != "active":
                continue                    # the named, everyday species first: what people ask about
            subj = "organism %s" % t["scientificname"]
            url = "https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=%s" % uid
            why = "NCBI Taxonomy %s (%s, %s)." % (uid, TAXA[g], t.get("division") or "")
            mk = lambda pred, obj: _item(subj, pred, obj, "ncbi-taxonomy", "NCBI Taxonomy", "US government work", url, why)
            items += [mk("common name", t["commonname"]), mk("belongs to", TAXA[g])]
            if t.get("division"):
                items.append(mk("group", t["division"]))
    pos += len(ids)
    nxt = g * TAXA_STEP + pos if ids and pos < total else (g + 1) * TAXA_STEP
    return items, (nxt if nxt // TAXA_STEP < len(TAXA) else None), "%d %s species with common names (%d of %d)" % (len(items) // 2 if items else 0, TAXA[g], pos, total)


# ---------------------------------------------------------------------------------------------------- sources needing a free key
# Keys live in <commons folder>/api-keys.json (owner-only), never in the database, its backups, the code or the logs.
KEY_SERVICES = {
    "api.data.gov": {"title": "api.data.gov (Smithsonian Open Access and USDA FoodData Central)", "how": "Fill in the form at "
                     "https://api.data.gov/signup/ (name and email); the key is shown at once. One key serves both sources."},
    "gemini": {"title": "Google Gemini API (paid tier) — exemplar tools and the fact gatherer",
               "how": "Google AI Studio → Get API key (aistudio.google.com/apikey), on a project with billing (the paid tier keeps your prompts out of Google's training). Used only by the exemplar generator and the fact gatherer (separate programs), never by the applications."},
    "perplexity": {"title": "Perplexity API (Sonar) — fact gatherer", "how": "perplexity.ai → Settings → API → add a payment method → "
                   "Generate API key. Paid per request. Used only by the fact gatherer; every fact it finds is checked on the cited page."},
    "anthropic": {"title": "Anthropic Claude API (web search) — fact gatherer", "how": "platform.claude.com → API keys → Create key "
                  "(with billing). Needs the 'anthropic' Python package (pip install anthropic) on the computer that runs the gatherer."},
    "openai": {"title": "OpenAI API (web search) — fact gatherer", "how": "platform.openai.com → API keys → Create new secret key "
               "(with billing). Used only by the fact gatherer."},
    "dpla": {"title": "Digital Public Library of America", "how": "Type your email and press Request: DPLA emails you the key."},
    "nara": {"title": "US National Archives Catalog", "how": "Email Catalog_API@nara.gov with your name and email and ask for a "
             "read-only Catalog API v2 key."},
    "europeana": {"title": "Europeana", "how": "Create a free account at europeana.eu, confirm it, then My Profile → Manage API key → "
                  "tick the terms → Request. Issued at once."},
}
_KEYS = {"folder": None}


def _keys_file(folder):
    return os.path.join(folder, "api-keys.json")


def load_keys(folder):
    try:
        with open(_keys_file(folder), encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if k in KEY_SERVICES and v}
    except (OSError, ValueError):
        return {}


def save_key(folder, service, key):
    if service not in KEY_SERVICES:
        raise ValueError("unknown service")
    keys = load_keys(folder)
    key = "".join((key or "").split())
    if key:
        keys[service] = key
    else:
        keys.pop(service, None)
    path = _keys_file(folder)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(keys, f)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def key_status(folder):
    keys = load_keys(folder)
    return [{"service": k, "title": v["title"], "how": v["how"], "set": k in keys, "hint": ("…" + keys[k][-4:]) if k in keys else ""}
            for k, v in KEY_SERVICES.items()]


def request_dpla_key(email):
    """Ask DPLA to email a key to `email` (run from the admin's own computer, at the admin's request)."""
    email = (email or "").strip()
    if "@" not in email or " " in email or "/" in email:
        raise ValueError("Give a valid email address.")
    req = urllib.request.Request("https://api.dp.la/v2/api_key/" + urllib.parse.quote(email, safe="@."), method="POST",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return {"status": r.status, "message": "DPLA says the key was created and emailed. Check your inbox (and spam folder), "
                                               "then paste the key here."}


def _key(service):
    return load_keys(_KEYS["folder"]).get(service) if _KEYS["folder"] else None


TOPICS = ["history", "architecture", "science", "engineering", "geography", "map", "astronomy", "chemistry", "mathematics", "language",
          "manuscript", "exploration", "invention", "railway", "bridge", "medicine", "music", "war"]


def _first(v):
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = v.get("name") or v.get("displayDate") or v.get("content")
    return " ".join(str(v).split()) if v not in (None, "") else None


SI = "https://api.si.edu/openaccess/api/v1.0/category/%s/search?"


def _smithsonian(category):
    def run(cursor, budget):
        r = FETCH(SI % category + urllib.parse.urlencode({"q": "*", "start": cursor, "rows": min(int(budget), 100), "api_key": _key("api.data.gov")}))
        rows, total = r.get("response", {}).get("rows", []), r.get("response", {}).get("rowCount", 0)
        items, kept = [], 0
        for row in rows:
            c = row.get("content") or {}
            d, ix = c.get("descriptiveNonRepeating") or {}, c.get("indexedStructured") or {}
            if (d.get("metadata_usage") or {}).get("access") != "CC0" or not row.get("title"):
                continue                                   # only records the Smithsonian marks CC0
            kept += 1
            subj = "Smithsonian object “%s” (%s)" % (row["title"][:150], d.get("record_ID") or row.get("id"))
            url = d.get("record_link") or "https://collections.si.edu/"
            why = "Smithsonian Open Access record %s, marked CC0." % (d.get("record_ID") or row.get("id"))
            mk = lambda pred, obj: _item(subj, pred, obj, "smithsonian-open-access", "Smithsonian Open Access", "CC0", url, why)
            if d.get("data_source"):
                items.append(mk("held by", d["data_source"]))
            for field, pred, n in (("date", "date", 1), ("object_type", "object type", 1), ("place", "place", 3), ("topic", "topic", 3)):
                for v in (ix.get(field) or [])[:n]:
                    if isinstance(v, str) and v.strip() and not v.startswith("["):
                        items.append(mk(pred, v.strip()))
        nxt = cursor + len(rows)
        return items, (nxt if rows and nxt < total else None), "%d CC0 records of %d read (%d–%d of %d)" % (kept, len(rows), cursor + 1, nxt, total)
    return run


FDC = "https://api.nal.usda.gov/fdc/v1/foods/list?"
FDC_TYPES = ["Foundation", "SR Legacy"]
NUTRIENTS = {"208": "energy", "203": "protein", "204": "total fat", "205": "carbohydrate", "291": "dietary fibre", "269": "total sugars",
             "301": "calcium", "303": "iron", "307": "sodium", "401": "vitamin C"}


def _fdc(cursor, budget):
    t, page = divmod(cursor, 10 ** 6)
    if t >= len(FDC_TYPES):
        return [], None, "finished"
    size = min(int(budget), 200)
    foods = FETCH(FDC + urllib.parse.urlencode({"dataType": FDC_TYPES[t], "pageSize": size, "pageNumber": page + 1, "api_key": _key("api.data.gov")}))
    items = []
    for f in foods if isinstance(foods, list) else []:
        subj = "food %s" % " ".join(str(f.get("description") or "").split())
        url = "https://fdc.nal.usda.gov/food-details/%s/nutrients" % f.get("fdcId")
        why = "USDA FoodData Central %s food %s." % (FDC_TYPES[t], f.get("fdcId"))
        for n in f.get("foodNutrients") or []:
            name = NUTRIENTS.get(str(n.get("number") or n.get("nutrientNumber") or ""))
            amount = n.get("amount", n.get("value"))
            if name and amount is not None and subj != "food ":
                items.append(_item(subj, "%s per 100 g" % name, "%s %s" % (amount, (n.get("unitName") or "").lower()), "usda-fooddata-central",
                                   "USDA FoodData Central", "CC0 1.0", url, why))
    n = len(foods) if isinstance(foods, list) else 0
    nxt = cursor + 1 if n == size else (t + 1) * 10 ** 6
    return items, (nxt if nxt // 10 ** 6 < len(FDC_TYPES) else None), "%d %s foods (page %d)" % (n, FDC_TYPES[t], page + 1)


NARA = "https://catalog.archives.gov/api/v2/records/search?"


def _nara(cursor, budget):
    size = min(int(budget), 100)
    r = FETCH(NARA + urllib.parse.urlencode({"q": "*", "availableOnline": "true", "limit": size, "page": cursor // size + 1}),
              headers={"x-api-key": _key("nara") or "", "Content-Type": "application/json"})
    hits = ((r.get("body") or {}).get("hits") or {}).get("hits") or []
    items, kept = [], 0
    for h in hits:
        rec = (h.get("_source") or {}).get("record") or {}
        if (rec.get("useRestriction") or {}).get("status") != "Unrestricted" or not rec.get("title"):
            continue                                       # only records NARA marks "Unrestricted"
        kept += 1
        na = rec.get("naId") or h.get("_id")
        subj = "National Archives record “%s” (NAID %s)" % (rec["title"][:150], na)
        url = "https://catalog.archives.gov/id/%s" % na
        why = "National Archives Catalog record %s; use restriction: Unrestricted." % na
        mk = lambda pred, obj: _item(subj, pred, obj, "nara-catalog", "US National Archives Catalog", "US government record", url, why)
        if rec.get("levelOfDescription"):
            items.append(mk("level of description", rec["levelOfDescription"]))
        for d in (rec.get("productionDates") or [])[:1]:
            if d.get("year"):
                items.append(mk("date", "-".join(str(x) for x in (d.get("year"), d.get("month"), d.get("day")) if x)))
        for a in rec.get("ancestors") or []:
            if a.get("levelOfDescription") == "series" and a.get("title"):
                items.append(mk("part of series", a["title"][:300]))
                if a.get("inclusiveStartDate") and a.get("inclusiveEndDate"):
                    items.append(mk("series covers", "%s to %s" % (_first(a["inclusiveStartDate"].get("logicalDate") if isinstance(a["inclusiveStartDate"], dict) else a["inclusiveStartDate"]),
                                                                    _first(a["inclusiveEndDate"].get("logicalDate") if isinstance(a["inclusiveEndDate"], dict) else a["inclusiveEndDate"]))))
                break
    nxt = cursor + len(hits)
    return items, (nxt if hits and nxt < 10000 else None), "%d unrestricted records of %d read" % (kept, len(hits))


DPLA = "https://api.dp.la/v2/items?"


def _dpla(cursor, budget):
    t, page = divmod(cursor, 10 ** 4)
    if t >= len(TOPICS):
        return [], None, "finished"
    size = min(int(budget), 100)
    r = FETCH(DPLA + urllib.parse.urlencode({"q": TOPICS[t], "page_size": size, "page": page + 1, "api_key": _key("dpla")}))
    docs, items = r.get("docs") or [], []
    for d in docs:
        sr = d.get("sourceResource") or {}
        title = _first(sr.get("title"))
        if not title:
            continue
        subj = "DPLA item “%s” (%s)" % (title[:150], d.get("id"))
        url = d.get("isShownAt") or "https://dp.la/item/%s" % d.get("id")
        why = "DPLA record %s (metadata CC0), topic '%s'." % (d.get("id"), TOPICS[t])
        mk = lambda pred, obj: _item(subj, pred, obj, "dpla-metadata", "Digital Public Library of America", "CC0 (metadata)", url, why)
        for field, pred, n in (("date", "date", 1), ("subject", "subject", 3), ("spatial", "place", 2), ("type", "type", 1)):
            vals = sr.get(field)
            for v in (vals if isinstance(vals, list) else [vals])[:n]:
                v = _first(v)
                if v:
                    items.append(mk(pred, v[:300]))
        if _first(d.get("dataProvider")):
            items.append(mk("provided by", _first(d.get("dataProvider"))))
    nxt = cursor + 1 if len(docs) == size and (page + 1) * size < min(int(r.get("count") or 0), 10000) else (t + 1) * 10 ** 4
    return items, (nxt if nxt // 10 ** 4 < len(TOPICS) else None), "%d items on '%s' (page %d)" % (len(docs), TOPICS[t], page + 1)


EUROPEANA = "https://api.europeana.eu/record/v2/search.json?"


def _europeana(cursor, budget):
    t, start = divmod(cursor, 10 ** 4)
    if t >= len(TOPICS):
        return [], None, "finished"
    rows = min(int(budget), 100)
    r = FETCH(EUROPEANA + urllib.parse.urlencode({"wskey": _key("europeana"), "query": TOPICS[t], "rows": rows, "start": start + 1}))
    found, items = r.get("items") or [], []
    for it in found:
        title = _first(it.get("title"))
        if not title:
            continue
        subj = "Europeana record “%s” (%s)" % (title[:150], it.get("id"))
        url = it.get("guid") or "https://www.europeana.eu/item%s" % it.get("id")
        why = "Europeana record %s (metadata CC0), topic '%s'." % (it.get("id"), TOPICS[t])
        mk = lambda pred, obj: _item(subj, pred, obj, "europeana-metadata", "Europeana", "CC0 (metadata)", url.split("?")[0], why)
        for field, pred in (("year", "year"), ("country", "country"), ("dataProvider", "held by"), ("type", "type")):
            v = _first(it.get(field))
            if v:
                items.append(mk(pred, v))
        for c in list(dict.fromkeys(it.get("dcCreator") or []))[:3]:
            if c and not str(c).startswith("http"):
                items.append(mk("creator", str(c)[:200]))
    nxt = start + len(found)
    nxt = t * 10 ** 4 + nxt if found and nxt < min(int(r.get("totalResults") or 0), 1000) else (t + 1) * 10 ** 4
    return items, (nxt if nxt // 10 ** 4 < len(TOPICS) else None), "%d records on '%s'" % (len(found), TOPICS[t])


NEEDS_KEY = {"smithsonian-history": "api.data.gov", "smithsonian-science": "api.data.gov", "usda-foods": "api.data.gov",
             "nara-records": "nara", "dpla-items": "dpla", "europeana-records": "europeana"}


# ---------------------------------------------------------------------------------------------------- the catalogue
# name: (application, registry source key, title, why, budget key, default budget, harvester)
HARVESTERS = {
    "wikidata-countries": ("facts", "wikidata", "Countries: capitals, continents and codes (Wikidata)",
                           "the basic map of the world every history and geography question rests on", "wd_countries", 50,
                           lambda c, b: _wikidata("P31=Q3624078", _countries, c, b)),
    "natural-earth-places": ("facts", "natural-earth", "Cities and towns: country, region and coordinates (Natural Earth)",
                             "where places are — the largest first", "ne_places", 150, _natural_earth),
    "frus-volumes": ("facts", "frus", "Foreign Relations of the United States volumes (Office of the Historian)",
                     "the official documentary record of US diplomacy since 1861: titles and the years each volume covers", "frus", 100, _frus),
    "met-highlights": ("facts", "met-open-access", "The Met's highlighted artworks: artist, date, medium (Met Open Access)",
                       "art history anchored to dated, attributed works — highlights first", "met", 30, _met),
    "wikidata-programming-languages": ("stem", "wikidata", "Programming languages: first release, designers (Wikidata)",
                                       "computer programming: the languages people ask about most, first", "wd_proglang", 50,
                                       lambda c, b: _wikidata("P31=Q9143", _prog_languages, c, b)),
    "wikidata-compounds": ("stem", "wikidata", "Chemical compounds: formula and CAS number (Wikidata)",
                           "chemistry: the most-referenced compounds first", "wd_compounds", 50,
                           lambda c, b: _wikidata("P31=Q11173", _compounds, c, b)),
    "ncbi-taxonomy": ("stem", "ncbi-taxonomy", "Species with common names (NCBI Taxonomy)",
                      "biology: named species of animals, plants and fungi", "ncbi", 200, _ncbi),
    "wikidata-languages": ("language", "wikidata", "The world's languages: ISO codes and writing systems (Wikidata)",
                           "which languages exist, how they are written — the most-documented first", "wd_languages", 50,
                           lambda c, b: _wikidata("P220", _languages, c, b)),
    # (1.47) more open, unrestricted sources: Wikidata (CC0) sets and US government data (public domain)
    "wikidata-battles": ("facts", "wikidata", "Battles: date, place and the war they belong to (Wikidata)",
                         "military history anchored to dates and places — the best-known first", "wd_battles", 50,
                         lambda c, b: _wikidata("P31=Q178561", _battles, c, b)),
    "wikidata-treaties": ("facts", "wikidata", "Treaties: when and where they were signed (Wikidata)",
                          "diplomatic history: the treaties people ask about most", "wd_treaties", 50,
                          lambda c, b: _wikidata("P31=Q131569", _treaties, c, b)),
    "wikidata-rivers": ("facts", "wikidata", "Rivers: length, countries and where they flow (Wikidata)",
                        "physical geography: the great rivers first", "wd_rivers", 50, lambda c, b: _wikidata("P31=Q4022", _rivers, c, b)),
    "wikidata-mountains": ("facts", "wikidata", "Mountains: elevation and country (Wikidata)",
                           "physical geography: the best-known peaks first", "wd_mountains", 50, lambda c, b: _wikidata("P31=Q8502", _mountains, c, b)),
    "wikidata-minerals": ("stem", "wikidata", "Minerals: chemical formula and crystal system (Wikidata)",
                          "earth science and chemistry: common minerals first", "wd_minerals", 50, lambda c, b: _wikidata("P31=Q7946", _minerals, c, b)),
    "wikidata-writing-systems": ("language", "wikidata", "Writing systems: ISO 15924 codes and age (Wikidata)",
                                 "how the world's languages are written", "wd_scripts", 50, lambda c, b: _wikidata("P506", _scripts, c, b)),
    "usgs-earthquakes": ("stem", "usgs-earthquakes", "Major earthquakes since 1900: magnitude, date, place, depth (USGS)",
                         "earth science: every recorded magnitude 6.5+ earthquake, strongest first", "usgs_eq", 200, _usgs_quakes),
    "federal-register-presidential": ("facts", "federal-register", "Executive orders and proclamations since 1994 (Federal Register)",
                                      "US history: what each president ordered and proclaimed, with dates", "fr_pres", 100, _federal_register),
    "pubchem-compounds": ("stem", "pubchem-computed", "Compounds: formula, molecular weight, IUPAC name (PubChem, computed properties only)",
                          "chemistry: NCBI-computed identifiers for the most-studied compounds", "pubchem", 100, _pubchem),
    "smithsonian-history": ("facts", "smithsonian-open-access", "Smithsonian history and culture records (CC0 only)",
                            "dated, placed objects from 19 Smithsonian museums", "si_history", 100, _smithsonian("history_culture")),
    "smithsonian-science": ("stem", "smithsonian-open-access", "Smithsonian science and technology records (CC0 only)",
                            "specimens and instruments with their dates, places and topics", "si_science", 100, _smithsonian("science_technology")),
    "usda-foods": ("stem", "usda-fooddata-central", "Food composition: energy, protein, fat, vitamins per 100 g (USDA)",
                   "nutrition facts measured by the USDA — Foundation foods first", "fdc", 100, _fdc),
    "nara-records": ("facts", "nara-catalog", "National Archives records online (Unrestricted only)",
                     "primary US records with dates and their series", "nara", 100, _nara),
    "dpla-items": ("facts", "dpla-metadata", "Digital Public Library of America records by topic",
                   "US library, archive and museum records on the subjects QueryBook covers", "dpla", 100, _dpla),
    "europeana-records": ("facts", "europeana-metadata", "Europeana records by topic",
                          "European cultural heritage records on the subjects QueryBook covers", "europeana", 100, _europeana),
}


def budgets(app_id):
    return {h[4]: h[5] for h in HARVESTERS.values() if h[0] == app_id}


def plan(ctx, app_id):
    """Tasks for this application's approved online sources (unfinished ones, with their key if one is needed)."""
    if not enabled(ctx):
        return []
    _KEYS["folder"] = ctx.commons.folder
    tasks = []
    for name, (app, key, title, why, bkey, bdef, _) in HARVESTERS.items():
        if app != app_id or ctx.commons.setting("harvester:%s" % name, "on") == "off" or not ctx.source_ok(key):
            continue
        if name in NEEDS_KEY and not _key(NEEDS_KEY[name]):
            continue                                  # waits for its free key (Harvesting page → API keys)
        cur = ctx.cursor("online:" + name)
        if cur < 0:
            continue                                  # source finished
        tasks.append({"action": "online:" + name, "title": "%s — from item %d" % (title, cur + 1), "target": {"cursor": cur},
                      "source": key, "budget_key": bkey, "why": why})
    return tasks


def execute(task, ctx):
    name = task["action"].split(":", 1)[1]
    _KEYS["folder"] = ctx.commons.folder
    app, key, title, why, bkey, bdef, fn = HARVESTERS[name]
    items, nxt, detail = fn(int(task["target"]["cursor"]), ctx.budget(bkey, bdef))
    return {"items": items, "cursor": {"online:" + name: -1 if nxt is None else nxt}, "detail": detail}
