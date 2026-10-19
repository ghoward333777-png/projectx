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
UA = "QueryBook-harvester/%s (personal research tool; one request at a time)" % VERSION
MIN_GAP_S = 1.0                     # pause between requests to the same site
_last = {}


class SourceBusy(Exception):
    """The site asked us to slow down (HTTP 429/503) or is unreachable; try again on a later turn."""


def _fetch(url, kind="json", timeout=60):
    host = urllib.parse.urlsplit(url).netloc
    wait = MIN_GAP_S - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json" if kind == "json" else "*/*"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                raise SourceBusy("%s asked to slow down (HTTP %d)" % (host, e.code))
            raise
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
    refs = sorted({v["id"] for e in ents.values() for p in ("P36", "P30", "P287", "P178", "P282", "P17") for v in _values(e, p)
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
}


def budgets(app_id):
    return {h[4]: h[5] for h in HARVESTERS.values() if h[0] == app_id}


def plan(ctx, app_id):
    """Tasks for this application's approved online sources (unfinished ones only)."""
    if not enabled(ctx):
        return []
    tasks = []
    for name, (app, key, title, why, bkey, bdef, _) in HARVESTERS.items():
        if app != app_id or not ctx.source_ok(key):
            continue
        cur = ctx.cursor("online:" + name)
        if cur < 0:
            continue                                  # source finished
        tasks.append({"action": "online:" + name, "title": "%s — from item %d" % (title, cur + 1), "target": {"cursor": cur},
                      "source": key, "budget_key": bkey, "why": why})
    return tasks


def execute(task, ctx):
    name = task["action"].split(":", 1)[1]
    app, key, title, why, bkey, bdef, fn = HARVESTERS[name]
    items, nxt, detail = fn(int(task["target"]["cursor"]), ctx.budget(bkey, bdef))
    return {"items": items, "cursor": {"online:" + name: -1 if nxt is None else nxt}, "detail": detail}
