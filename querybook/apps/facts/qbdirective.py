"""qbdirective — the Campaign Manager: strategic directives in, executable harvest campaigns out.

A directive is a document (Word .docx, Markdown or plain text) that names the learn-by-example tasks QueryBook should collect
examples of — for instance the "QueryBook Synthetic-Video Directive": 122 tasks in 19 categories, each with its readiness tier
(T0 now, T30 within 30 days, SM after specialized modeling), revenue band, world-model value, the cameras, points of view,
overlays, dialog and captions each category needs, and the metadata every clip must carry.

  Reader      reads the document into a brief: the task register (every row whose first cell is an id like MED-01), the
              category profiles, the capture specification, the specialized-modeling schedule, the metadata record, the
              fastest/largest-revenue lists, the anchor-set rule, the scope exclusions and the standing orders.
  Designer    turns the brief into a campaign: waves (T0 → T30 → SM, never earlier than the directive allows), every task's
              takes and camera views as generation requests with their prompts, the real anchor set each task family needs,
              the expert who reviews it, and a day-by-day schedule at the Google tool's real daily budget.
  Checklist   what must be settled before a wave may run (scope acknowledged, reviewers, likeness consent, anchor sources,
              the Google source approved, a Gemini key, the admin passphrase) — the assistant asks for each in turn.
  Compiler    writes each wave as an exemplar plan (tools/plans format, "scene" kind) that tools/generate_exemplars.py runs.
  Launcher    (admin passphrase) gives a wave's plan to the chosen Google video tool and switches it on; the exemplar
              generator — a separate program, never the applications — makes the clips into the exemplar library, where
              QueryBook measures them and the admin approves them. Generated video is an example, never a Fact Unit.
  Assistant   a chat helper for setting a campaign up. It is rule-based (no model, no network) for everything it changes;
              when an Anthropic key is configured it may also answer free questions with Claude, advisory only.

Standard library only. Deterministic: the same directive and settings give the same campaign and the same plans.
"""
import base64, datetime, io, json, math, os, re, time, urllib.error, urllib.request, zipfile
import xml.etree.ElementTree as ET

VERSION = "1.0.0"
TASK_ID = re.compile(r"\b([A-Z]{2,4})-(\d{2,3})\b")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TIERS = ("T0", "T30", "SM")
WAVE_NAMES = {"T0": "Wave 1 — generate now (T0)", "T30": "Wave 2 — within 30 days (T30)", "SM": "Wave 3 — specialized modeling (SM)"}
VIDEO_TOOLS = {"veo-speech-video": ("veo-3.0-fast-generate-001", 10), "omni-speech-video": ("gemini-omni-1.1-flash", 100)}
REGULATED = {"MED", "MIL", "DRV", "ENG", "INS"}            # buyers who require the larger real anchor set (FDA, DoD, NHTSA, FAA …)
REVIEWERS = {"MED": "licensed clinician (RN or MD)", "ROB": "robotics engineer", "DRV": "autonomous-vehicle safety engineer",
             "MFG": "manufacturing engineer", "EMR": "paramedic or fire officer", "MIL": "military logistics or maintenance specialist",
             "SEC": "security operations lead", "DIS": "emergency management specialist", "ENG": "licensed lineworker or plant operator",
             "INS": "certified inspector (A&P, bridge or API)", "ENT": "instructional designer", "DH": "digital-human lead with the consent officer",
             "CON": "UX researcher", "CUL": "cultural advisor from the depicted culture", "DLY": "occupational therapist or home-robotics engineer",
             "SPT": "sports biomechanist or physiotherapist", "HOM": "licensed tradesperson", "AGR": "agronomist or veterinarian",
             "CST": "construction safety manager"}
FAILURE_BRANCH = {"ROB", "DRV", "MFG", "DLY", "INS", "HOM", "CST", "AGR", "SPT", "EMR"}     # categories whose world model needs the mistake too
# never generated, whatever a directive asks: kept for a person to decide
SCOPE_GUARD = re.compile(r"\b(weapons?|munitions?|ordnance|targeting\b|kill chain|lethal|explosives? (?:making|assembly)|facial recognition|"
                         r"face identification|identify (?:real )?(?:people|individuals)|track(?:ing)? (?:real )?individuals|deepfake of)\b", re.I)
LIGHT = ["soft daylight", "overcast daylight", "warm indoor light", "cool fluorescent light", "late-afternoon light", "night-time work lights"]
PLACE = ["well-kept", "busy", "cramped", "modern", "older", "rural"]
PERSON = ["a woman in her thirties", "a man in his fifties", "a young adult", "a person in their sixties", "a man in his twenties",
          "a woman in her forties"]
DEFAULTS = {"tool": "veo-speech-video", "requests_per_day": None, "clip_seconds": 10, "views": 2,
            "takes": {"T0": 2, "T30": 1, "SM": 1}, "anchor_pct": None, "start": None, "scope_ack": False, "reviewers": {},
            "reviewers_confirmed": False, "consent_confirmed": False, "anchor_source": "", "exclude": [], "waves": list(TIERS),
            "focus_only": False}


# ================================================================================================ reader
def _tidy(t):
    return re.sub(r"\s+", " ", (t or "").replace(" ", " ").replace(" ", " ").replace(" ", " ")).strip()


def _para_text(p):
    out = []
    for el in p.iter():
        if el.tag == W + "t":
            out.append(el.text or "")
        elif el.tag in (W + "tab", W + "br"):
            out.append(" ")
    return "".join(out)


def docx_blocks(data):
    """the document body in reading order: heading / paragraph / table / code blocks"""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        doc = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise ValueError("This is not a readable Word document (.docx).")
    levels = {}
    try:
        for st in ET.fromstring(z.read("word/styles.xml")).iter(W + "style"):
            sid, name = st.get(W + "styleId"), st.find(W + "name")
            n = name.get(W + "val") if name is not None else ""
            m = re.match(r"heading\s*(\d)$", n or "", re.I)
            if m:
                levels[sid] = int(m.group(1))
            elif (n or "").lower() == "title":
                levels[sid] = 1
    except (KeyError, ET.ParseError):
        pass
    body = ET.fromstring(doc).find(W + "body")
    blocks, code = [], []

    def flush():
        if code:
            blocks.append({"type": "code", "text": "\n".join(code)}); code.clear()
    for node in list(body if body is not None else []):
        if node.tag == W + "p":
            ps = node.find(W + "pPr")
            style = ""
            if ps is not None and ps.find(W + "pStyle") is not None:
                style = ps.find(W + "pStyle").get(W + "val") or ""
            text = _para_text(node)
            if re.match(r"(Preformatted|Code|HTMLPreformatted|SourceText)", style, re.I):
                code.append(text); continue
            flush()
            if not text.strip():
                continue
            lvl = levels.get(style)
            if lvl is None:
                m = re.match(r"(?:Heading|Title)\s*(\d)?$", style, re.I)
                lvl = int(m.group(1) or 1) if m else None
            blocks.append({"type": "heading", "level": lvl, "text": _tidy(text)} if lvl else {"type": "paragraph", "text": _tidy(text)})
        elif node.tag == W + "tbl":
            flush()
            rows = [[_tidy(" ".join(_para_text(p) for p in tc.iter(W + "p"))) for tc in tr.findall(W + "tc")] for tr in node.findall(W + "tr")]
            if rows:
                blocks.append({"type": "table", "header": rows[0], "rows": rows[1:]})
    flush()
    return blocks


def text_blocks(text):
    """Markdown or plain text: # headings, | tables |, ``` code, everything else a paragraph"""
    lines = (text or "").replace("﻿", "").splitlines()
    blocks, i = [], 0
    strip = lambda s: _tidy(re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s).replace("**", "").replace("__", "").replace("`", ""))
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1; continue
        if line.strip().startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            blocks.append({"type": "code", "text": "\n".join(lines[i + 1:j])}); i = j + 1; continue
        m = re.match(r"(#{1,6})\s+(.+)$", line)
        if m:
            blocks.append({"type": "heading", "level": len(m.group(1)), "text": strip(m.group(2))}); i += 1; continue
        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                row = lines[i].strip().strip("|")
                if not re.fullmatch(r"[\s:|-]+", row):
                    rows.append([strip(c) for c in row.split("|")])
                i += 1
            if rows:
                blocks.append({"type": "table", "header": rows[0], "rows": rows[1:]})
            continue
        blocks.append({"type": "paragraph", "text": strip(re.sub(r"^\s*(?:[-*>]|\d+\.)\s+", "", line))}); i += 1
    return blocks


def blocks_of(name, data):
    ext = os.path.splitext(name or "")[1].lower()
    if ext == ".docx":
        return docx_blocks(data)
    if ext in (".md", ".markdown", ".txt", ""):
        return text_blocks(data.decode("utf-8", "replace"))
    raise ValueError("Upload the directive as a Word (.docx), Markdown (.md) or text (.txt) file.")


def read(name, data):
    """a directive file (bytes) → its brief"""
    brief = interpret(blocks_of(name, data), name or "directive")
    if not brief["tasks"]:
        raise ValueError("No task register found: the directive needs a table whose first column holds task ids like MED-01, "
                         "with columns for the task and its tier (T0 / T30 / SM).")
    return brief


# ------------------------------------------------------------------------------------------------ focus directives
# A focus directive has no task register: it names the sectors that need the work most and a recommended first move, and
# re-ranks an existing campaign. Each rule: (sector words in the directive, whole categories, words in a task that match).
SECTOR_RULES = [
    ("Defense and intelligence", r"defen[cs]e|military|intelligence", {"MIL"},
     r"sustainment|logistics|depot receiving|casualty|convoy|refuel|airlift|cargo|ammunition|readiness"),
    ("Government", r"government|regulator|procurement|benefits?", set(), r"checkpoint|screening|compliance|federal|bridge|tunnel|rail track"),
    ("Legal and compliance", r"legal|compliance", set(), r"compliance|lockout|tagout|\baml\b|privacy|harassment|\bgmp\b"),
    ("Pharma, medical and science", r"pharma|medical|science|clinical", {"MED"}, r"pharma|aseptic|medication|\bgmp\b|clinical|fill-finish"),
    ("Finance and insurance", r"financ|insurance|bank", set(), r"insur|claims|damage assessment|crash|\baml\b|near-miss"),
    ("Engineering and industry", r"engineering|industry|industrial|energy|aviation|manufactur", {"ENG", "INS", "MFG"},
     r"maintenance|inspection|torque|lockout|substation|aircraft|well-site|borescope|assembly|cleanroom|welding|changeover"),
]
FIRST_MOVE_RULES = [  # (words in the recommended first move, categories, task words) — the first wave's spearhead
    (r"aviation|aircraft", set(), r"aircraft walkaround|borescope|aviation maintenance|rotor component|flight line"),
    (r"energy|utilit|power", {"ENG"}, r"substation|turbine|solar|well-site|rig floor|nuclear|pole replacement|storm restoration"),
    (r"pharma", set(), r"pharmaceutical|aseptic|fill-finish|\bgmp\b"),
    (r"compliance", set(), r"lockout|tagout|aseptic|\bgmp\b"),
]


def read_focus(name, data):
    """a focus directive → {title, sectors, first_move, notes}; None when the document is not one"""
    blocks = blocks_of(name, data)
    title, sectors, first, notes, sub = "", [], [], [], ""
    for b in blocks:
        if b["type"] == "heading":
            if not title and b["level"] == 1:
                title = b["text"]
            else:
                sub = b["text"].lower()
        elif b["type"] == "paragraph" and not title and not sectors:
            title = title or b["text"]                     # a pasted document may start without a heading
        elif b["type"] == "paragraph" and sub.startswith("recommended first move"):
            first.append(b["text"])
        elif b["type"] == "paragraph" and sub.startswith(("what it is missing", "what it's missing", "the catch")):
            notes.append(b["text"])
        elif b["type"] == "table":
            i = _col(b["header"], "sector")
            if i is not None:
                for r in b["rows"]:
                    sectors.append({"sector": _cell(r, i), "need": _cell(r, _col(b["header"], "what hurts")),
                                    "buy": _cell(r, _col(b["header"], "what they would buy", "what they'd buy", "what they buy"))})
    text = " ".join(x["text"] for x in blocks if x["type"] in ("paragraph", "heading"))
    if not first:                                          # pasted as plain text: the heading is a paragraph
        m = re.search(r"Recommended first move\s*(.+)$", text, re.I)
        first = [m.group(1).strip()] if m else []
    if not sectors and not first:
        return None
    return {"source": name, "title": title or os.path.splitext(name)[0], "sectors": sectors, "first_move": " ".join(first)[:1000],
            "notes": notes[:12]}


def focus_rank(focus, task):
    """1 = the recommended first move, 2 = a named sector's work, 3 = everything else; with the reasons"""
    if not focus:
        return 3, []
    hay = " ".join([task["task"], task.get("value", "")]).lower()      # the work itself (buyers' names would add noise: "Home Depot")
    fm = (focus.get("first_move") or "").lower()
    why1 = [w for w, cats, kw in FIRST_MOVE_RULES if re.search(w, fm) and (task["category"] in cats or re.search(kw, hay))]
    if why1:
        return 1, ["first move: " + focus["first_move"].split("(")[0].strip()[:80]]
    why2 = []
    for label, sector_re, cats, kw in SECTOR_RULES:
        if any(re.search(sector_re, x["sector"], re.I) for x in focus.get("sectors") or []) and (task["category"] in cats or re.search(kw, hay)):
            why2.append(label)
    return (2, why2) if why2 else (3, [])


def _col(header, *names):
    h = [x.lower().strip() for x in header]
    for i, x in enumerate(h):
        if any(x == n or x.startswith(n) for n in names):
            return i
    return None


def _cell(row, i):
    return row[i].strip() if i is not None and i < len(row) else ""


def interpret(blocks, source):
    title = subtitle = ""
    sections, cats, tasks, capture, industries, companies, special = [], {}, {}, [], [], [], {}
    schema, lists, paras = None, {}, []
    section = sub = ""
    cur = None
    for k, b in enumerate(blocks):
        t = b["type"]
        if t == "heading":
            if not title and b["level"] == 1:
                title = b["text"]
                nxt = blocks[k + 1] if k + 1 < len(blocks) else None
                subtitle = nxt["text"] if nxt and nxt["type"] == "paragraph" else ""
                continue
            if b["level"] <= 2:
                section, sub, cur = b["text"], "", None
                sections.append(section)
            else:
                sub, cur = b["text"], None
                m = re.match(r"(.+?)\s*\(([A-Z]{2,4})\)\s*$", sub)
                if m:
                    cur = m.group(2)
                    cats[cur] = {"code": cur, "name": m.group(1).strip(), "profile": "", "section": section}
            continue
        if t == "paragraph":
            paras.append(b["text"])
            if cur and not cats[cur]["profile"] and b["text"].lower().startswith("shared profile"):
                cats[cur]["profile"] = re.sub(r"^shared profile\.?\s*", "", b["text"], flags=re.I)
            if sub:
                lists.setdefault(sub, []).append(b["text"])
            continue
        if t == "code":
            try:
                d = json.loads(b["text"])
                if schema is None and isinstance(d, dict) and "task_id" in d:
                    schema = d
            except ValueError:
                pass
            continue
        hd, rows = b["header"], b["rows"]
        if _col(hd, "#", "id") is not None and _col(hd, "task") is not None and _col(hd, "tier") is not None:
            for r in rows:
                m = TASK_ID.search(_cell(r, _col(hd, "#", "id")))
                if not m:
                    continue
                wm, _, ag = _cell(r, _col(hd, "wm")).partition("/")
                code = cur or m.group(1)
                tier = _cell(r, _col(hd, "tier")).upper().replace(" ", "")
                ease = re.search(r"\d", _cell(r, _col(hd, "ease")))
                tasks[m.group(0)] = {"id": m.group(0), "category": code, "category_name": cats.get(code, {}).get("name", code),
                                     "task": _cell(r, _col(hd, "task")), "value": _cell(r, _col(hd, "why it pays", "value")),
                                     "payers": [x.strip() for x in _cell(r, _col(hd, "who pays", "payers")).split(",") if x.strip()],
                                     "ease": max(1, min(5, int(ease.group(0)))) if ease else 3, "tier": tier if tier in TIERS else "T30",
                                     "revenue_band": (_cell(r, _col(hd, "rev"))[:1] or "C").upper(),
                                     "world_model": wm.strip().upper() or "M", "agent_reasoning": ag.strip().upper() or "M"}
        elif _col(hd, "category") is not None and _col(hd, "required angles") is not None:
            for r in rows:
                capture.append({"category": _cell(r, _col(hd, "category")), "angles": _cell(r, _col(hd, "required angles")),
                                "povs": _cell(r, _col(hd, "required pov")), "overlays": _cell(r, _col(hd, "required overlays")),
                                "dialog": _cell(r, _col(hd, "required dialog")), "captions": _cell(r, _col(hd, "required captions"))})
        elif _col(hd, "industry") is not None and _col(hd, "composite") is not None:
            for r in rows:
                try:
                    industries.append({"rank": int(_cell(r, _col(hd, "rank")) or 0), "industry": _cell(r, _col(hd, "industry")),
                                       "composite": float(_cell(r, _col(hd, "composite")) or 0)})
                except ValueError:
                    pass
        elif _col(hd, "segment") is not None and _col(hd, "priority targets") is not None:
            for r in rows:
                companies.append({"segment": _cell(r, _col(hd, "segment")), "entry_offer": _cell(r, _col(hd, "entry offer")),
                                  "targets": [x.strip() for x in _cell(r, _col(hd, "priority targets")).split(",") if x.strip()],
                                  "first_ticket": _cell(r, _col(hd, "first ticket")), "sales_cycle": _cell(r, _col(hd, "sales cycle"))})
        elif _col(hd, "modeling required") is not None:
            for r in rows:
                m = TASK_ID.search(_cell(r, _col(hd, "task")))
                if m:
                    days = [int(x) for x in re.findall(r"\d+", _cell(r, _col(hd, "online")))]
                    special[m.group(0)] = {"task": m.group(0), "modeling": _cell(r, _col(hd, "modeling required")),
                                           "online_by": _cell(r, _col(hd, "online")), "online_day": days[0] if days else None}
    full = "\n".join(paras)
    return {"source": source, "title": title or os.path.splitext(os.path.basename(source))[0], "subtitle": subtitle, "sections": sections,
            "categories": list(cats.values()), "tasks": list(tasks.values()), "capture_spec": capture, "industries": industries,
            "companies": companies, "specialized_modeling": list(special.values()), "metadata_schema": schema,
            "throughput": _throughput(full), "anchor_rule": _anchor(full), "scope_exclusions": _exclusions(full),
            "fastest_revenue": _ids_under(lists, "fastest revenue"), "largest_revenue": _ids_under(lists, "largest revenue"),
            "standing_orders": _under(lists, "standing orders"), "submission_question": (_under(lists, "submission question") or [""])[0]}


def _throughput(t):
    out = {"pod_gpus": 64, "T0": 1000, "T30": 300, "SM": 75, "clip_seconds": 10, "from_directive": False}
    m = re.search(r"per\s+(\d+)-GPU", t, re.I)
    if m:
        out["pod_gpus"] = int(m.group(1))
    m = re.search(r"([\d,]+)\s+labell?ed\s+(\d+)-second clips a day at T0", t, re.I)
    if m:
        out.update(T0=int(m.group(1).replace(",", "")), clip_seconds=int(m.group(2)), from_directive=True)
    m = re.search(r"about\s+([\d,]+)\s+at T30", t, re.I)
    if m:
        out["T30"] = int(m.group(1).replace(",", ""))
    m = re.search(r"(\d+)\s*[–-]\s*(\d+)\s+at SM", t)
    if m:
        out["SM"] = (int(m.group(1)) + int(m.group(2))) // 2
    return out


def _anchor(t):
    m = re.search(r"anchor set of\s+(\d+)\s*[–-]\s*(\d+)\s*%", t)
    return {"min_pct": int(m.group(1)), "max_pct": int(m.group(2)), "from_directive": True} if m else {"min_pct": 2, "max_pct": 5, "from_directive": False}


def _exclusions(t):
    m = re.search(r"Out of scope:\s*([^\n]+)", t, re.I)
    if not m:
        return []
    first = re.split(r"\.\s", m.group(1))[0].replace(", and ", ", ")
    return [x.strip(" .;") for x in first.split(",") if x.strip(" .;")]


def _under(lists, start):
    for h, entries in lists.items():
        if h.lower().startswith(start):
            return entries
    return []


def _ids_under(lists, start):
    ids = []
    for e in _under(lists, start):
        found = [m.group(0) for m in TASK_ID.finditer(e)]
        ids += found
        if found:                                   # "DRV-01, 02 and 05" → DRV-02, DRV-05 too
            pre = found[0].split("-")[0]
            m = re.search(pre + r"-\d{2,3}((?:\s*(?:,|and)\s*\d{2,3})+)", e)
            if m:
                ids += ["%s-%s" % (pre, n) for n in re.findall(r"\d{2,3}", m.group(1))]
    return list(dict.fromkeys(ids))


# ================================================================================================ designer
def settings_of(camp):
    s = json.loads(json.dumps(DEFAULTS))
    for k, v in (camp.get("settings") or {}).items():
        if k == "takes" and isinstance(v, dict):
            s["takes"].update({t: max(1, min(20, int(n))) for t, n in v.items() if t in TIERS})
        elif k in s:
            s[k] = v
    tool = s["tool"] if s["tool"] in VIDEO_TOOLS else DEFAULTS["tool"]
    s["tool"] = tool
    s["requests_per_day"] = max(1, int(s["requests_per_day"] or VIDEO_TOOLS[tool][1]))
    s["views"] = max(1, min(4, int(s["views"] or 2)))
    s["clip_seconds"] = max(4, min(60, int(s["clip_seconds"] or 10)))
    return s


def _split(text):
    return [x.strip() for x in re.split(r"[;,]|\band\b", text or "") if x.strip()] or ["a steady wide shot"]


def capture_for(brief, task):
    name = task["category_name"].lower()
    for c in brief["capture_spec"]:
        if name.startswith(c["category"].lower()) or c["category"].lower().startswith(name.split()[0]):
            return c
    return {"category": task["category_name"], "angles": "wide shot, close-up on the hands", "povs": "performer first-person; observer",
            "overlays": "step labels", "dialog": "", "captions": "step text"}


def held(task):
    hit = SCOPE_GUARD.search(" ".join([task["task"], task.get("value", "")]))
    return hit.group(0) if hit else None


def _priority(brief, focus=None):
    fast = {t: i for i, t in enumerate(brief.get("fastest_revenue") or [])}
    band = {"A": 0, "B": 1, "C": 2}
    return lambda t: (focus_rank(focus, t)[0], 0 if t["id"] in fast else 1, fast.get(t["id"], 0), band.get(t["revenue_band"], 3), -t["ease"], t["id"])


def prompts_for(task, cap, s):
    """one generation request per take and camera view: deterministic variety (place, light, performer), failure branches"""
    angles, povs = _split(cap["angles"]), _split(cap["povs"])
    tier = task["tier"]
    out = []
    n = int(task["id"].split("-")[1])
    for take in range(1, s["takes"][tier] + 1):
        k = n + take
        fail = task["category"] in FAILURE_BRANCH and take % 3 == 0
        for v in range(s["views"]):
            view, pov = angles[v % len(angles)], povs[v % len(povs)]
            speech = ("Audio: natural ambient sound and the speech this work involves (%s); no music." % cap["dialog"]) if cap.get("dialog") and \
                cap["dialog"].lower() not in ("none", "optional narration") else "Audio: natural ambient sound only; no music, no narration."
            out.append({"item": "%s-t%02d-v%d" % (task["id"], take, v + 1), "covers": task["id"], "take": take, "view": v + 1, "script": "", "style": "",
                        "camera": view, "pov": pov, "failure_branch": fail,
                        "prompt": ("A %d-second clip. Task: %s (%s). Camera: %s. Point of view: %s. Setting: a %s place suited to the task, %s. "
                                   "Performer: %s. %s %s" % (s["clip_seconds"], task["task"], task["category_name"].lower(), view, pov,
                                                             PLACE[k % len(PLACE)], LIGHT[k % len(LIGHT)], PERSON[k % len(PERSON)],
                                                             "In this take a realistic mistake happens partway through and is noticed and "
                                                             "corrected before the task is finished." if fail else
                                                             "Performed correctly, following standard safe practice from start to finish.", speech))})
    return out


FIXED = ("Photorealistic synthetic training video for QueryBook's procedure library. Fictional people and places only: no real person's "
         "likeness, no brand names or logos, no on-screen text, captions, subtitles or watermarks (overlays and captions are added "
         "afterwards from the clip's metadata). Show the complete action in one continuous shot: the starting state, every step, and the "
         "finished result, at a natural pace.")


def design(camp, today=None):
    """the campaign: waves, per-task requests and schedule, reviewers, anchor sets, and the readiness checklist"""
    brief, s = camp["brief"], settings_of(camp)
    rule = brief["anchor_rule"]
    start = s["start"] or today or camp.get("created", "")[:10] or datetime.date.today().isoformat()
    day0 = datetime.date.fromisoformat(start)
    special = {x["task"]: x for x in brief["specialized_modeling"]}
    model, budget = VIDEO_TOOLS[s["tool"]][0], s["requests_per_day"]
    focus = camp.get("focus")
    order = _priority(brief, focus)
    waves, tasks_out, held_out, cursor = [], [], [], 0
    for tier in TIERS:
        tier_tasks = sorted([t for t in brief["tasks"] if t["tier"] == tier], key=order)
        jobs = []
        for t in tier_tasks:
            why = held(t)
            if why:
                held_out.append({"id": t["id"], "task": t["task"], "why": "matched the scope guard (“%s”): kept for a person to decide" % why}); continue
            if t["id"] in s["exclude"] or t["category"] in s["exclude"]:
                continue
            rank, why_focus = focus_rank(focus, t)
            if s["focus_only"] and focus and rank == 3:
                continue
            cap = capture_for(brief, t)
            pct = s["anchor_pct"] or (rule["max_pct"] if t["category"] in REGULATED else rule["min_pct"])
            req = s["takes"][tier] * s["views"]
            jobs.append({"id": t["id"], "task": t["task"], "category": t["category"], "category_name": t["category_name"], "tier": tier,
                         "revenue_band": t["revenue_band"], "ease": t["ease"], "requests": req, "takes": s["takes"][tier], "views": s["views"],
                         "clips_seconds": req * s["clip_seconds"], "anchor_pct": pct, "anchor_clips": max(1, math.ceil(s["takes"][tier] * pct / 100.0)),
                         "reviewer": (s["reviewers"] or {}).get(t["category"]) or REVIEWERS.get(t["category"], "domain expert"),
                         "capture": cap, "prerequisite": (special.get(t["id"], {}).get("modeling") if tier == "SM" else
                                                          "a scene kit, rigged asset or expert-approved procedure script" if tier == "T30" else "none"),
                         "world_model": t["world_model"], "agent_reasoning": t["agent_reasoning"], "focus": rank, "focus_why": why_focus})
        if tier not in s["waves"] or not jobs:
            if jobs:
                waves.append({"tier": tier, "name": WAVE_NAMES[tier], "included": False, "tasks": len(jobs), "requests": 0})
            continue
        earliest = 0 if tier == "T0" else 30 if tier == "T30" else min([special[j["id"]]["online_day"] for j in jobs
                                                                          if j["id"] in special and special[j["id"]]["online_day"]] or [90])
        first = max(earliest, cursor)
        day = first * budget
        for j in jobs:
            j["start_day"], j["end_day"] = day // budget, (day + j["requests"] - 1) // budget
            j["start_date"] = (day0 + datetime.timedelta(days=j["start_day"])).isoformat()
            day += j["requests"]
        total = sum(j["requests"] for j in jobs)
        end = first + max(1, math.ceil(total / float(budget)))
        cursor = end
        waves.append({"tier": tier, "name": WAVE_NAMES[tier], "included": True, "tasks": len(jobs), "requests": total,
                      "clip_minutes": round(total * s["clip_seconds"] / 60.0, 1), "earliest_day": earliest, "start_day": first, "end_day": end,
                      "start_date": (day0 + datetime.timedelta(days=first)).isoformat(), "end_date": (day0 + datetime.timedelta(days=end)).isoformat(),
                      "categories": sorted({j["category"] for j in jobs}), "anchor_clips": sum(j["anchor_clips"] for j in jobs),
                      "status": (camp.get("launched") or {}).get(tier, {}).get("status", "ready to compile")})
        tasks_out += jobs
    return {"settings": s, "model": model, "requests_per_day": budget, "waves": waves, "tasks": tasks_out, "held": held_out,
            "totals": {"tasks": len(tasks_out), "requests": sum(j["requests"] for j in tasks_out),
                       "clip_minutes": round(sum(j["clips_seconds"] for j in tasks_out) / 60.0, 1),
                       "days": max([w.get("end_day", 0) for w in waves] + [0]), "categories": len({j["category"] for j in tasks_out}),
                       "directive_tasks": len(brief["tasks"]), "focus_first_move": sum(1 for j in tasks_out if j["focus"] == 1),
                       "focus_sectors": sum(1 for j in tasks_out if j["focus"] == 2)},
            "focus": focus,
            "throughput_note": ("The directive plans %d clips a day per %d-GPU pod at T0; this account's %s budget is %d requests a day, so the "
                                "schedule below uses %d a day. Raise the tool's daily budget (Harvesting → Google tools) or add a second video "
                                "tool to go faster." % (brief["throughput"]["T0"], brief["throughput"]["pod_gpus"], model, VIDEO_TOOLS[s["tool"]][1], budget))}


# ================================================================================================ readiness
def checklist(camp, env=None):
    """what must be settled before a wave runs; env = facts about the installation (source approved, keys, passphrase)"""
    env = env or {}
    d = design(camp)
    s, cats = d["settings"], {j["category"] for j in d["tasks"]}
    items = [
        ("directive", "Directive read", True, "%d tasks in %d categories from %s" % (len(camp["brief"]["tasks"]), len(camp["brief"]["categories"]) or len(cats),
                                                                                   camp["brief"]["source"]), "all"),
        ("scope", "Scope exclusions acknowledged", bool(s["scope_ack"]),
         "Out of scope: %s." % "; ".join(camp["brief"]["scope_exclusions"] or ["weapons employment, targeting, identifying real people"]) +
         ("" if s["scope_ack"] else " Say “I acknowledge the scope”."), "all"),
        ("tool", "Video tool and daily budget", True, "%s — %d requests a day" % (d["model"], d["requests_per_day"]), "all"),
        ("reviewers", "Expert reviewers confirmed", bool(s["reviewers_confirmed"]),
         "%d categories need a reviewer (defaults proposed). Say “use the default reviewers” or “reviewer for MED is …”." % len(cats), "all"),
        ("consent", "Likeness consent records", bool(s["consent_confirmed"]) or "DH" not in cats,
         "Digital-human tasks need a consent record for every likeness." if "DH" in cats else "No digital-human tasks selected.", "DH"),
        ("anchor", "Real anchor-set source", bool(s["anchor_source"]) or not (cats & REGULATED),
         ("Regulated categories (%s) need a real-data anchor set of %d%%: say “anchor source is …”." % (", ".join(sorted(cats & REGULATED)),
                                                                                                      camp["brief"]["anchor_rule"]["max_pct"]))
         if cats & REGULATED and not s["anchor_source"] else (s["anchor_source"] or "No regulated categories selected."), "regulated"),
        ("source", "Google exemplar source approved", bool(env.get("source_approved")),
         "Policy registry → “Google Gemini API — generated exemplars” (terms-of-service class: needs your explicit acceptance).", "launch"),
        ("key", "Gemini API key saved", bool(env.get("gemini_key")), "Harvesting → API keys → Gemini.", "launch"),
        ("admin", "Admin passphrase set", bool(env.get("admin_set")), "Harvesting → Admin.", "launch"),
    ]
    out = [{"key": k, "title": t, "ok": bool(ok), "detail": det, "needed_for": need} for k, t, ok, det, need in items]
    return {"items": out, "ready_to_compile": all(i["ok"] for i in out if i["needed_for"] not in ("launch",)),
            "ready_to_launch": all(i["ok"] for i in out), "next": next((i for i in out if not i["ok"]), None)}


# ================================================================================================ compiler
def compile_plans(camp, folder):
    """each included wave as an exemplar plan (scene kind) + a jobs manifest (JSON lines) — what the generator runs"""
    d = design(camp)
    s, brief = d["settings"], camp["brief"]
    out_dir = os.path.join(folder, camp["id"], "plans")
    os.makedirs(out_dir, exist_ok=True)
    tasks = {t["id"]: t for t in brief["tasks"]}
    files = []
    jobs_path = os.path.join(out_dir, "jobs.jsonl")
    with open(jobs_path, "w", encoding="utf-8") as jf:
        for w in d["waves"]:
            if not w["included"]:
                continue
            items = []
            for j in [x for x in d["tasks"] if x["tier"] == w["tier"]]:
                for it in prompts_for(tasks[j["id"]], j["capture"], s):
                    items.append({k: it[k] for k in ("item", "script", "prompt", "style", "covers")})
                    meta = metadata_for(brief, j, it, d["model"])
                    jf.write(json.dumps({"wave": w["tier"], "task": j["id"], "item": it["item"], "model": d["model"], "day": j["start_day"],
                                         "prompt": FIXED + "\n\n" + it["prompt"], "metadata": meta}, ensure_ascii=False, sort_keys=True) + "\n")
            plan = {"skill": "directive:%s:%s" % (camp["id"], w["tier"].lower()), "model": d["model"], "kind": "video", "scene": True,
                    "image": None, "subject": None, "consent": None, "voice": None, "fixed": FIXED, "items": items,
                    "campaign": {"id": camp["id"], "title": brief["title"], "wave": w["name"], "tasks": w["tasks"], "requests": w["requests"]}}
            p = os.path.join(out_dir, "wave-%s.json" % w["tier"].lower())
            with open(p, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=1, ensure_ascii=False, sort_keys=True)
            files.append({"tier": w["tier"], "path": p, "items": len(items)})
    manifest = {"campaign": camp["id"], "title": brief["title"], "compiled": _now(), "version": VERSION, "model": d["model"],
                "waves": files, "jobs": jobs_path, "totals": d["totals"]}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return manifest


def metadata_for(brief, job, it, model):
    """the directive's metadata record for one clip, filled in as far as it can be before generation"""
    cap = job["capture"]
    rec = {"task_id": job["id"], "variant_id": job["id"] + "-" + it["item"].split("-", 2)[-1], "tier": job["tier"],
           "generator": {"model": model, "seed": None, "prompt_hash": None},
           "environment": {"take": it["take"], "camera": it["camera"], "pov": it["pov"]},
           "views": [{"id": "v%d" % it["view"], "angle": it["camera"], "pov": it["pov"]}],
           "steps": [], "recovery_of": job["id"] if it["failure_branch"] else None, "captions": [], "dialog": [],
           "overlays": _split(cap.get("overlays")), "caption_spec": cap.get("captions"),
           "provenance": {"synthetic": True, "c2pa_manifest": True, "real_anchor_link": None},
           "review": {"domain_expert": "required", "status": "pending", "reviewer_role": job["reviewer"]},
           "rights": {"likeness_consent": "required" if job["category"] == "DH" else "n/a", "client_ip": False}, "ufcs_units": None}
    schema = brief.get("metadata_schema") or {}
    return {k: rec.get(k, schema.get(k)) for k in list(dict.fromkeys(list(schema) + list(rec)))}


# ================================================================================================ store
def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    """one JSON file per campaign under <commons>/directives/ (with its compiled plans beside it)"""

    def __init__(self, folder):
        self.folder = os.path.join(folder, "directives")
        os.makedirs(self.folder, exist_ok=True)

    def _path(self, cid):
        if not re.fullmatch(r"[a-z0-9-]{1,80}", cid or ""):
            raise ValueError("No such campaign.")
        return os.path.join(self.folder, cid + ".json")

    def list(self):
        out = []
        for n in sorted(os.listdir(self.folder)):
            if n.endswith(".json"):
                try:
                    c = self.get(n[:-5])
                except (ValueError, OSError):
                    continue
                out.append({"id": c["id"], "title": c["brief"]["title"], "created": c["created"], "tasks": len(c["brief"]["tasks"]),
                            "source": c["brief"]["source"], "status": c.get("status", "draft")})
        return out

    def get(self, cid):
        try:
            with open(self._path(cid), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise ValueError("No such campaign.")

    def save(self, camp):
        p = self._path(camp["id"])
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(camp, f, indent=1, ensure_ascii=False)
        for n in range(10):
            try:
                os.replace(tmp, p); break
            except PermissionError:
                if n == 9:
                    raise
                time.sleep(0.05 * (n + 1))
        return camp

    def create(self, name, data, sha=None):
        brief = read(name, data)
        import hashlib
        sha = sha or hashlib.sha256(data).hexdigest()
        for c in self.list():
            full = self.get(c["id"])
            if full.get("sha256") == sha:
                return full                                    # the same document again: the campaign already exists
        base = re.sub(r"[^a-z0-9]+", "-", brief["title"].lower()).strip("-")[:50] or "directive"
        cid, n = base, 2
        while os.path.exists(self._path(cid)):
            cid, n = "%s-%d" % (base, n), n + 1
        camp = {"id": cid, "created": _now(), "sha256": sha, "status": "draft", "brief": brief, "settings": {}, "chat": [], "launched": {}}
        camp["chat"].append({"role": "assistant", "at": _now(), "text": welcome(camp)})
        return self.save(camp)

    def apply_focus(self, cid, name, data, focus=None):
        """a focus directive re-ranks an existing campaign (the same document twice changes nothing)"""
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
        camp = self.get(cid)
        if (camp.get("focus") or {}).get("sha256") == sha:
            return camp
        focus = focus or read_focus(name, data)
        if not focus:
            raise ValueError("This document has neither a task register nor a focus (a Sector table or a recommended first move).")
        focus.update(sha256=sha, applied=_now())
        camp["focus"] = focus
        camp.setdefault("audit", []).append({"at": _now(), "by": "admin (focus directive)", "changes": ["focus: %s" % focus["title"]]})
        camp.setdefault("chat", []).append({"role": "assistant", "at": _now(), "text": focus_text(camp), "changes": ["focus: " + focus["title"]]})
        return self.save(camp)

    def ingest(self, name, data, target=None):
        """a directive with a task register becomes a campaign; a focus directive refines the target campaign (or the only/newest one)"""
        try:
            return self.create(name, data)
        except ValueError:
            focus = read_focus(name, data)
            if not focus:
                raise
            camps = sorted(self.list(), key=lambda c: c["created"])
            if not camps:
                raise ValueError("This is a focus directive: add the campaign's task directive first, then this one refines it.")
            return self.apply_focus(target or camps[-1]["id"], name, data, focus)


# ================================================================================================ assistant
def welcome(camp):
    d = design(camp)
    b = camp["brief"]
    w = "; ".join("%s: %d tasks, %d requests (%s → %s)" % (x["name"], x["tasks"], x["requests"], x["start_date"], x["end_date"])
                  for x in d["waves"] if x["included"])
    return ("I read “%s”: %d tasks in %d categories, %d specialized-modeling schedules, and its metadata record%s. I've designed the "
            "campaign as three waves — %s — at %d %s requests a day (%d views per take). %s\n\nBefore anything runs I need a few "
            "things from you; type “what's missing” at any time. First: %s"
            % (b["title"], len(b["tasks"]), len(b["categories"]) or len({t["category"] for t in b["tasks"]}), len(b["specialized_modeling"]),
               "" if b["metadata_schema"] else " (no metadata record found: the default one is used)", w, d["requests_per_day"], d["model"],
               d["settings"]["views"], ("%d task(s) are held back by the scope guard." % len(d["held"])) if d["held"] else
               "No task tripped the scope guard.", "please confirm the scope exclusions — say “I acknowledge the scope”."))


def focus_text(camp):
    d = design(camp)
    f = camp.get("focus") or {}
    if not f:
        return "No focus directive applied. Add one (a document with a Sector table and a recommended first move) to re-rank the campaign."
    first = [j for j in d["tasks"] if j["focus"] == 1]
    sect = [j for j in d["tasks"] if j["focus"] == 2]
    by_sector = {}
    for j in sect:
        for w in j["focus_why"]:
            by_sector.setdefault(w, []).append(j["id"])
    lines = ["Focus applied: “%s”." % f.get("title", ""),
             "Recommended first move: %s" % (f.get("first_move") or "—"),
             "→ %d first-move tasks now lead every wave: %s." % (len(first), ", ".join(j["id"] for j in first) or "none"),
             "→ %d more tasks serve the named sectors:" % len(sect)]
    lines += ["   • %s: %s" % (k, ", ".join(v)) for k, v in by_sector.items()]
    lines.append("→ %d other tasks stay in the campaign after them%s." % (len([j for j in d["tasks"] if j["focus"] == 3]),
                 "" if not d["settings"]["focus_only"] else " — but “focus tasks only” is on, so they are left out"))
    if f.get("notes"):
        lines.append("Not harvest tasks, kept as notes: " + " | ".join(n[:140] for n in f["notes"][:4]))
    lines.append("Say “focus tasks only” to run just the focus, or “all tasks” to keep everything (focus first).")
    return "\n".join(lines)


HELP = ("I can set this campaign up with you. Try:\n"
        "• what's missing / status / show the waves\n"
        "• I acknowledge the scope\n"
        "• use veo  ·  use omni  ·  15 requests a day  ·  3 takes for T0  ·  2 views\n"
        "• start on 2026-11-02\n"
        "• use the default reviewers  ·  reviewer for MED is Dr. Lee (RN)\n"
        "• consent is on file  ·  anchor source is our hospital simulation lab recordings  ·  anchor 4%\n"
        "• exclude MED-07  ·  include MED-07  ·  only wave 1\n"
        "• explain ROB-09  ·  compile the plans\n"
        "• show the focus  ·  focus tasks only  ·  all tasks\n"
        "Launching a wave needs your admin passphrase: use the Launch button (I never take passphrases in chat).")


def _set(camp, key, value):
    camp.setdefault("settings", {})[key] = value


def respond(camp, text, env=None, ai=None):
    """one chat turn: apply what the sentence asks (rule-based), then answer; returns (reply, changes)"""
    t = (text or "").strip()
    low = t.lower()
    ch = []
    s = settings_of(camp)
    tasks = {x["id"]: x for x in camp["brief"]["tasks"]}
    if re.search(r"^(help|\?|what can you do|commands)\b", low):
        return HELP, ch
    if re.search(r"\b(acknowledge|accept|agree)\b.*\b(scope|exclusions?)\b|^i acknowledge\b", low):
        _set(camp, "scope_ack", True); ch.append("scope exclusions acknowledged")
    m = re.search(r"\buse (veo|omni)\b", low)
    if m:
        _set(camp, "tool", "veo-speech-video" if m.group(1) == "veo" else "omni-speech-video"); _set(camp, "requests_per_day", None)
        ch.append("video tool: %s" % VIDEO_TOOLS[settings_of(camp)["tool"]][0])
    m = re.search(r"(\d+)\s*(?:requests?|clips?|videos?|generations?)?\s*(?:a|per|/)\s*day\b", low)
    if m:
        _set(camp, "requests_per_day", int(m.group(1))); ch.append("budget: %s requests a day" % m.group(1))
    for m in re.finditer(r"(\d+)\s*takes?(?:\s*(?:for|in|at)\s*(t0|t30|sm|wave\s*[123]))?", low):
        tier = {"wave 1": "T0", "wave1": "T0", "wave 2": "T30", "wave2": "T30", "wave 3": "SM", "wave3": "SM"}.get(
            (m.group(2) or "").replace("  ", " "), (m.group(2) or "").upper())
        takes = dict(s["takes"])
        for tr in ([tier] if tier in TIERS else TIERS):
            takes[tr] = int(m.group(1))
        _set(camp, "takes", takes); ch.append("takes per task: %s" % ", ".join("%s %d" % kv for kv in takes.items()))
    m = re.search(r"(\d)\s*(?:camera\s*)?(?:views?|angles?)\b", low)
    if m:
        _set(camp, "views", int(m.group(1))); ch.append("views per take: %s" % m.group(1))
    m = re.search(r"(\d+)\s*-?\s*seconds?\b", low)
    if m and re.search(r"\b(clip|clips|long|length)\b", low):
        _set(camp, "clip_seconds", int(m.group(1))); ch.append("clip length: %s s" % m.group(1))
    m = re.search(r"\bstart(?:ing|s)?\s+(?:on\s+)?(\d{4}-\d{2}-\d{2})\b", low)
    if m:
        try:
            datetime.date.fromisoformat(m.group(1)); _set(camp, "start", m.group(1)); ch.append("start date: %s" % m.group(1))
        except ValueError:
            return "That date isn't valid — write it as YYYY-MM-DD.", ch
    if re.search(r"\b(default|proposed|suggested) reviewers\b|\breviewers? (?:are )?(?:confirmed|ok|fine|approved)\b", low):
        _set(camp, "reviewers_confirmed", True); ch.append("reviewers confirmed")
    m = re.search(r"\breviewer\s+for\s+([A-Za-z]{2,4})\s+(?:is|=|:)\s+(.+)$", t, re.I)
    if m:
        r = dict(s["reviewers"]); r[m.group(1).upper()] = m.group(2).strip()[:120]
        _set(camp, "reviewers", r); ch.append("reviewer for %s: %s" % (m.group(1).upper(), m.group(2).strip()[:120]))
    if re.search(r"\bconsent\b.*\b(on file|recorded|confirmed|have|signed|yes)\b|\b(confirm|have)\b.*\bconsent\b", low) and "no consent" not in low:
        _set(camp, "consent_confirmed", True); ch.append("likeness consent confirmed")
    m = re.search(r"\banchor\w*\s+(?:source|set|data)\s*(?:is|are|:|=|from|will be)\s+(.+)$", t, re.I)
    if m:
        _set(camp, "anchor_source", m.group(1).strip()[:300]); ch.append("anchor source: %s" % m.group(1).strip()[:300])
    m = re.search(r"\banchor\w*\s*(?:of\s*|at\s*|=\s*)?(\d{1,2})\s*%", low)
    if m:
        _set(camp, "anchor_pct", max(1, min(50, int(m.group(1))))); ch.append("anchor set: %s%% of every task family" % m.group(1))
    m = re.search(r"\bonly wave\s*([123])\b", low)
    if m:
        _set(camp, "waves", [TIERS[int(m.group(1)) - 1]]); ch.append("waves: only %s" % WAVE_NAMES[TIERS[int(m.group(1)) - 1]])
    if re.search(r"\b(?:focus(?:ed)? (?:tasks )?only|only (?:the )?focus(?:ed)?(?: tasks)?)\b", low):
        _set(camp, "focus_only", True); ch.append("only the focus tasks")
    if re.search(r"\ball (?:the )?tasks\b|\bfocus first\b", low):
        _set(camp, "focus_only", False); ch.append("all tasks, focus first")
    if re.search(r"\ball (?:the )?waves\b", low):
        _set(camp, "waves", list(TIERS)); ch.append("waves: all three")
    for verb, ids in re.findall(r"\b(exclude|skip|drop|include|restore|add back)\s+((?:[A-Za-z]{2,4}(?:-\d{2,3})?(?:\s*,\s*|\s+and\s+|\s+)?)+)", t, re.I):
        found = [x.upper() for x in re.findall(r"\b[A-Za-z]{2,4}(?:-\d{2,3})?\b", ids)
                 if x.upper() in tasks or x.upper() in {c["code"] for c in camp["brief"]["categories"]} or x.upper() in {v["category"] for v in tasks.values()}]
        if not found:
            continue
        ex = set(s["exclude"])
        ex = ex | set(found) if verb.lower() in ("exclude", "skip", "drop") else ex - set(found)
        _set(camp, "exclude", sorted(ex)); ch.append("%s %s" % ("excluded" if verb.lower() in ("exclude", "skip", "drop") else "included", ", ".join(found)))
    if ch:
        camp.setdefault("audit", []).append({"at": _now(), "by": "assistant (from the admin's words)", "changes": ch, "text": t[:300]})
        nxt = checklist(camp, env)["next"]
        d = design(camp)
        return ("Done: %s.\n\nThe campaign now has %d tasks, %d requests, %s days at %d a day. %s"
                % ("; ".join(ch), d["totals"]["tasks"], d["totals"]["requests"], d["totals"]["days"], d["requests_per_day"],
                   ("Next: %s — %s" % (nxt["title"], nxt["detail"])) if nxt else "Everything is settled: compile the plans, then launch a wave.")), ch
    m = TASK_ID.search(t.upper())
    if m and m.group(0) in tasks and re.search(r"\b(explain|show|what is|what's|tell me about|details?)\b", low) or (m and low.strip() == m.group(0).lower()):
        return explain(camp, m.group(0)), ch
    open_question = t.endswith("?") or re.match(r"(which|why|how|should|could|would|can|is|are|does|do)\b", low)
    if ai and open_question and not re.search(r"\b(missing|status|checklist|ready|need from me|left to do)\b", low):
        try:
            return ai(camp, t), ch
        except Exception as e:                       # the AI is optional: never let it break the conversation
            return "(Claude could not answer: %s.)\n\n%s" % (str(e)[:200], status_text(camp, env)), ch
    if m and m.group(0) in tasks:
        return explain(camp, m.group(0)), ch
    if re.search(r"\b(the )?focus\b", low) and re.search(r"\b(show|what|which|explain|describe)\b", low):
        return focus_text(camp), ch
    if re.search(r"\b(missing|status|ready|what next|next step|checklist|left to do|need from me)\b", low):
        return status_text(camp, env), ch
    if re.search(r"\b(waves?|schedule|plan|timeline|how long)\b", low) and "compile" not in low:
        return waves_text(camp), ch
    if re.search(r"\bcompile\b", low):
        return "Press “Compile the plans” (or say nothing — I'll wait): compiling writes one exemplar plan per wave and a jobs manifest; it starts nothing.", ch
    if re.search(r"\b(launch|run it|go live|start (?:the )?(?:wave|campaign|generation))\b", low):
        ck = checklist(camp, env)
        return ("Launching needs your admin passphrase, so use the Launch button on a compiled wave. " +
                ("Everything it needs is ready." if ck["ready_to_launch"] else "Still missing: " +
                 "; ".join(i["title"] for i in ck["items"] if not i["ok"]) + ".")), ch
    if ai:
        try:
            return ai(camp, t), ch
        except Exception as e:                       # the AI is optional: never let it break the conversation
            return "(Claude could not answer: %s.)\n\n%s" % (str(e)[:200], status_text(camp, env)), ch
    return "I didn't recognise that as a change. " + status_text(camp, env) + "\n\nType “help” for what I understand.", ch


def status_text(camp, env=None):
    ck = checklist(camp, env)
    lines = ["%s %s — %s" % ("✓" if i["ok"] else "✗", i["title"], i["detail"]) for i in ck["items"]]
    head = ("Ready to launch." if ck["ready_to_launch"] else "Ready to compile; launching still needs the items marked ✗." if ck["ready_to_compile"]
            else "Not ready yet.")
    return head + "\n" + "\n".join(lines)


def waves_text(camp):
    d = design(camp)
    out = [d["throughput_note"], ""]
    for w in d["waves"]:
        if w["included"]:
            out.append("%s: %d tasks, %d requests (%.1f clip-minutes), days %d–%d (%s → %s), %d anchor clips; categories %s."
                       % (w["name"], w["tasks"], w["requests"], w["clip_minutes"], w["start_day"], w["end_day"], w["start_date"], w["end_date"],
                          w["anchor_clips"], ", ".join(w["categories"])))
        else:
            out.append("%s: not included (%d tasks)." % (w["name"], w["tasks"]))
    if d["held"]:
        out.append("Held back by the scope guard: " + "; ".join("%s (%s)" % (h["id"], h["why"]) for h in d["held"]))
    return "\n".join(out)


def explain(camp, tid):
    d = design(camp)
    t = next(x for x in camp["brief"]["tasks"] if x["id"] == tid)
    j = next((x for x in d["tasks"] if x["id"] == tid), None)
    head = "%s — %s (%s, tier %s, band %s, ease %d/5, world model %s / agent %s)\n%s Paid for by: %s." % (
        tid, t["task"], t["category_name"], t["tier"], t["revenue_band"], t["ease"], t["world_model"], t["agent_reasoning"],
        t["value"] + "." if t["value"] else "", ", ".join(t["payers"]) or "—")
    if not j:
        why = next((h["why"] for h in d["held"] if h["id"] == tid), "excluded from this campaign (say “include %s”)" % tid)
        return head + "\n\nNot in the campaign: " + why + "."
    first = prompts_for(t, j["capture"], d["settings"])[0]
    if j.get("focus", 3) < 3:
        head += "\nFocus: %s." % "; ".join(j["focus_why"])
    return (head + "\n\nIn the campaign: %d takes × %d views = %d requests, days %d–%d (from %s); anchor set %d%% (%d real clips); reviewer: %s; "
            "prerequisite: %s.\nCameras: %s. Points of view: %s. Overlays added afterwards: %s.\n\nFirst request's prompt:\n%s"
            % (j["takes"], j["views"], j["requests"], j["start_day"], j["end_day"], j["start_date"], j["anchor_pct"], j["anchor_clips"], j["reviewer"],
               j["prerequisite"], j["capture"]["angles"], j["capture"]["povs"], j["capture"]["overlays"], first["prompt"]))


# -------------------------------------------------------------------------------- the optional AI (Claude), advisory only
CLAUDE_MODEL = "claude-opus-5-5"
SYSTEM = ("You are the Campaign Manager assistant inside QueryBook's Control Panel. You help the admin prepare a directive-driven harvest "
          "campaign of synthetic training videos. You only advise: you cannot change settings, compile or launch anything — the admin does "
          "that with exact phrases the panel understands (\"I acknowledge the scope\", \"use veo\", \"15 requests a day\", \"3 takes for T0\", "
          "\"2 views\", \"start on YYYY-MM-DD\", \"use the default reviewers\", \"reviewer for MED is …\", \"consent is on file\", "
          "\"anchor source is …\", \"anchor 4%\", \"exclude MED-07\", \"only wave 1\") and the Compile and Launch buttons. Suggest the exact "
          "phrase when a change would help. Answer from the campaign summary you are given; say plainly when it does not contain the answer. "
          "Never ask for or repeat passphrases or API keys. Generated video is an example for QueryBook's exemplar library, never a fact. "
          "Keep answers short: a few sentences or a short list.")


def claude_ai(key):
    """an AI answerer for respond(): one Messages API call (standard library HTTP; the applications ship no SDK)"""
    def ask(camp, text):
        d = design(camp)
        summary = {"title": camp["brief"]["title"], "totals": d["totals"], "waves": d["waves"], "throughput_note": d["throughput_note"],
                   "held": d["held"], "checklist": checklist(camp)["items"], "settings": d["settings"],
                   "categories": camp["brief"]["categories"], "fastest_revenue": camp["brief"]["fastest_revenue"],
                   "largest_revenue": camp["brief"]["largest_revenue"],
                   "tasks": [{k: x[k] for k in ("id", "task", "category", "tier", "revenue_band", "ease")} for x in camp["brief"]["tasks"]]}
        history = [{"role": "user" if m["role"] == "you" else "assistant", "content": m["text"]} for m in (camp.get("chat") or [])[-8:]
                   if m["role"] in ("you", "assistant") and m.get("text")]
        while history and history[0]["role"] != "user":
            history.pop(0)
        msgs = history + [{"role": "user", "content": "Campaign summary (JSON):\n" + json.dumps(summary, ensure_ascii=False) +
                           "\n\nThe admin asks: " + text}]
        body = {"model": CLAUDE_MODEL, "max_tokens": 4000, "system": SYSTEM, "messages": msgs, "output_config": {"effort": "low"},
                "fallbacks": "default"}
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2026-10-21",
                                              "anthropic-beta": "server-side-fallback-2026-07-01"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError("Anthropic API answered HTTP %d" % e.code)
        if resp.get("stop_reason") == "refusal":
            return "Claude declined to answer that. " + status_text(camp)
        text_out = "\n".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()
        return (text_out or "Claude gave no answer.") + "\n\n— Claude (advisory; nothing was changed)"
    return ask


def anthropic_key(folder):
    """ANTHROPIC_API_KEY, else the key saved in the shared folder's api-keys.json (never logged or shown)"""
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if k:
        return k
    try:
        import qbonline as ol
        return (ol.load_keys(folder).get("anthropic") or "").strip()
    except Exception:
        return ""


# ================================================================================================ the Control Panel's routes
def environment(c):
    """installation facts the checklist needs"""
    out = {"source_approved": False, "gemini_key": False, "admin_set": False}
    try:
        import qbcampaign
        out["source_approved"] = qbcampaign.source_approved(c)
    except Exception:
        pass
    try:
        import qbonline as ol
        out["gemini_key"] = bool(ol.load_keys(c.folder).get("gemini"))
    except Exception:
        pass
    try:
        out["admin_set"] = c.approvals.admin_set()
    except Exception:
        pass
    return out


def view(store, c, cid):
    camp = store.get(cid)
    env = environment(c)
    d = design(camp)
    lib = {}
    try:
        import qbexemplar
        L = qbexemplar.Library(os.path.join(c.folder, "exemplars"))
        for x in L.list():
            if str(x.get("skill", "")).startswith("directive:%s:" % cid):
                tier = x["skill"].rsplit(":", 1)[1].upper()
                lib[tier] = lib.get(tier, 0) + 1
    except Exception:
        pass
    plans = os.path.join(store.folder, cid, "plans", "manifest.json")
    compiled = None
    if os.path.isfile(plans):
        with open(plans, encoding="utf-8") as f:
            compiled = json.load(f)
    done = {x["tier"] for x in (compiled or {}).get("waves", [])}
    for w in d["waves"]:
        w["made"] = lib.get(w["tier"], 0)
        w["launch"] = (camp.get("launched") or {}).get(w["tier"])
        if w["included"] and not w["launch"]:
            w["status"] = "compiled — ready to launch" if w["tier"] in done else "ready to compile"
    return {"campaign": {k: camp[k] for k in ("id", "created", "status", "settings", "launched") if k in camp}, "brief": camp["brief"],
            "design": d, "checklist": checklist(camp, env), "chat": camp.get("chat", [])[-80:], "compiled": compiled,
            "ai": bool(anthropic_key(c.folder)), "env": env, "audit": camp.get("audit", [])[-40:]}


def launch(store, c, cid, tier, passphrase, start_generator=False, program_dir=None):
    """(admin) give a compiled wave's plan to the campaign's video tool and switch it on; optionally start the exemplar generator"""
    import qbcampaign
    c.approvals._require(passphrase or "")
    camp = store.get(cid)
    ck = checklist(camp, environment(c))
    if not ck["ready_to_launch"]:
        raise ValueError("Not ready to launch: " + "; ".join(i["title"] for i in ck["items"] if not i["ok"]) + ".")
    p = os.path.join(store.folder, cid, "plans", "wave-%s.json" % (tier or "").lower())
    if tier not in TIERS or not os.path.isfile(p):
        raise ValueError("Compile the plans first (no compiled plan for %s)." % tier)
    tool = settings_of(camp)["tool"]
    qbcampaign.set_tool(c, tool, True, passphrase, plan=p)
    camp.setdefault("launched", {})[tier] = {"status": "launched", "at": _now(), "tool": tool, "plan": p}
    camp["status"] = "running"
    camp.setdefault("audit", []).append({"at": _now(), "by": "admin", "changes": ["launched %s on %s" % (WAVE_NAMES[tier], tool)]})
    store.save(camp)
    with c.store.write() as db:
        c.agent_log(db, "engine", "Campaign Manager: %s — %s launched on %s" % (camp["brief"]["title"], WAVE_NAMES[tier], tool))
    out = {"summary": "%s handed to %s and switched on." % (WAVE_NAMES[tier], tool)}
    if start_generator:
        out["generator"] = qbcampaign.runner(c, "start", passphrase, program_dir)["summary"]
    return out


def seed(store, folder):
    """directives shipped beside the application (directives/*.docx|md) are set up once, ready in the Campaign Manager"""
    made = []
    if not os.path.isdir(folder):
        return made
    names = [n for n in sorted(os.listdir(folder)) if n.lower().endswith((".docx", ".md", ".txt"))]
    for focus_pass in (False, True):                    # task directives first, then the focus directives that refine them
        for n in names:
            if n.lower().startswith("focus") != focus_pass:
                continue
            try:
                with open(os.path.join(folder, n), "rb") as f:
                    made.append(store.ingest(n, f.read())["id"])
            except (ValueError, OSError):
                continue
    return made


def add_routes(api, c, program_dir=None):
    store = Store(c.folder)
    try:
        seed(store, os.path.join(program_dir or "", "directives"))
    except Exception:
        pass
    g, p = api.get, api.post

    def guard(fn):
        def run(q):
            try:
                return fn(q)
            except ValueError as e:
                import qbcore as core
                raise core.UserError(str(e))
        return run

    def upload(q):
        name = os.path.basename(str(q.get("name") or "directive.md"))
        if q.get("data"):
            data = base64.b64decode(q["data"])
        elif q.get("text"):
            data = str(q["text"]).encode("utf-8"); name = os.path.splitext(name)[0] + ".md"
        else:
            raise ValueError("Choose a directive file, or paste its text.")
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("The directive is larger than 20 MB.")
        camp = store.ingest(name, data, q.get("target") or None)
        with c.store.write() as db:
            c.agent_log(db, "engine", "Campaign Manager: directive “%s” read (%d tasks)" % (camp["brief"]["title"], len(camp["brief"]["tasks"])))
        return view(store, c, camp["id"])

    def chat(q):
        camp = store.get(q.get("id"))
        text = str(q.get("message") or "").strip()[:2000]
        if not text:
            raise ValueError("Type a message.")
        key = anthropic_key(c.folder)
        reply, changes = respond(camp, text, environment(c), claude_ai(key) if key and q.get("ai", True) else None)
        camp.setdefault("chat", []).extend([{"role": "you", "at": _now(), "text": text},
                                            {"role": "assistant", "at": _now(), "text": reply, "changes": changes}])
        camp["chat"] = camp["chat"][-200:]
        store.save(camp)
        return dict(view(store, c, camp["id"]), reply=reply, changes=changes)

    def settings(q):
        camp = store.get(q.get("id"))
        for k, v in (q.get("settings") or {}).items():
            if k in DEFAULTS:
                _set(camp, k, v)
        camp.setdefault("audit", []).append({"at": _now(), "by": "admin (form)", "changes": sorted((q.get("settings") or {}).keys())})
        store.save(camp)
        return view(store, c, camp["id"])

    def compile_(q):
        camp = store.get(q.get("id"))
        if not checklist(camp, environment(c))["ready_to_compile"]:
            raise ValueError("Not ready to compile: " + "; ".join(i["title"] for i in checklist(camp)["items"]
                                                                   if not i["ok"] and i["needed_for"] != "launch") + ".")
        m = compile_plans(camp, store.folder)
        camp["status"] = "compiled" if camp.get("status") in (None, "draft", "compiled") else camp["status"]
        camp.setdefault("audit", []).append({"at": _now(), "by": "admin", "changes": ["compiled %d wave plan(s)" % len(m["waves"])]})
        store.save(camp)
        return dict(view(store, c, camp["id"]), summary="%d wave plan(s) and %d jobs written to %s" % (
            len(m["waves"]), sum(w["items"] for w in m["waves"]), os.path.dirname(m["jobs"])))

    def delete(q):
        cid = q.get("id")
        os.remove(store._path(cid))
        return {"campaigns": store.list()}

    g("/api/directives")(lambda q: {"campaigns": store.list(), "version": VERSION})
    p("/api/directives/upload")(guard(upload))
    p("/api/directives/get")(guard(lambda q: view(store, c, q.get("id"))))
    p("/api/directives/chat")(guard(chat))
    p("/api/directives/settings")(guard(settings))
    p("/api/directives/compile")(guard(compile_))
    p("/api/directives/launch")(guard(lambda q: dict(launch(store, c, q.get("id"), q.get("tier"), q.get("passphrase"),
                                                           bool(q.get("start_generator")), program_dir), **view(store, c, q.get("id")))))
    p("/api/directives/delete")(guard(delete))
    return store


def attach(app, program_dir=None):
    c = getattr(app, "commons", None)
    if c is None:
        return None
    try:
        return add_routes(app.api, c, program_dir)
    except Exception as e:
        log = getattr(app, "log", None)
        if log:
            log("campaign manager unavailable:", repr(e))
        return None
