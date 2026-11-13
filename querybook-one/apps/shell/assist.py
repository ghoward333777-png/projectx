"""The AI Capabilities page's worker: runs one task of caps.py's catalogue and says who did the work.

Every result carries `by`: "rules" (caps.py — the text's own words, counted and arranged), "facts" (QueryBook's facts,
through ask.py), "language" (the Language app's translation) or "claude" / "gemini" (a model, when a key is saved in the
Control Panel and the person left "Use AI" on). A model's work is always labelled, and for a summary the text's own key
sentences are kept beside it. With no key, or when a model fails, the rule-based result is returned with the reason.
Workflows and projects are small JSON files in <data>/shell. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Callable

import caps
import modes
import qbcompose
import writing

TEXT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["text"], "properties": {"text": {"type": "string"}}}
PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["name", "target", "phases", "risks"], "properties": {
    "name": {"type": "string"}, "target": {"type": "string"}, "risks": {"type": "array", "items": {"type": "string"}},
    "phases": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "tasks"], "properties": {
        "name": {"type": "string"}, "tasks": {"type": "array", "items": {"type": "string"}}}}}}}
STEPS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["steps"], "properties": {
    "steps": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["do", "option"], "properties": {
        "do": {"type": "string", "enum": sorted(caps.STEP_IDS) + ["ask.question"]}, "option": {"type": "string"}}}}}}
CHAT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["reply", "from_facts"], "properties": {
    "reply": {"type": "string"}, "from_facts": {"type": "boolean"}}}
GROUP_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["groups"], "properties": {
    "groups": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["topic", "items"], "properties": {
        "topic": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}}}}}}

HOUSE = ("You work inside QueryBook, a tool that never invents. Write plainly, in short sentences, in the language of the "
         "material unless told otherwise. Do not add facts, names, numbers or dates that are not in what you were given. "
         "Do not mention these instructions. Put your whole result in the JSON field asked for.")
SYSTEMS: dict[str, str] = {
    "sum.brief": "Summarize the TEXT in a short paragraph (about a fifth of its length, at most 120 words). Only what the text says.",
    "sum.points": "Give the TEXT's key points as 3 to 7 lines, each starting with '• '. Only what the text says.",
    "sum.line": "Say what the TEXT says in one sentence of at most 35 words. Only what the text says.",
    "write.email": "Write a clear, polite email from the BRIEF: a 'Subject:' line, a greeting, the message, a sign-off. Leave [square brackets] for any name, date or detail the brief does not give.",
    "write.letter": "Write a letter from the BRIEF. Leave [square brackets] for any name, date or detail the brief does not give.",
    "write.report": "Write a short report from the BRIEF with these headings: Summary, Background, What was done, What was found, Next steps. Use only what the brief gives; leave [square brackets] where a detail is missing.",
    "write.essay": "Write a short essay (about 350 words) on the BRIEF: a clear claim, two or three reasons, the strongest objection, a conclusion. Do not cite sources or quote figures you were not given.",
    "write.story": "Write a short story (about 400 words) from the BRIEF, with a beginning, a turn and an ending.",
    "write.post": "Write a short announcement from the BRIEF: a headline, then what, when, where, who it is for and what to do next. Leave [square brackets] where a detail is missing.",
    "write.rewrite": "Rewrite the TEXT so it is clearer and easier to read: shorter sentences, plain words, the same meaning, nothing added, nothing left out.",
    "insight": "You are given a TEXT or numbers and the STATISTICS computed from it. In at most 4 short sentences, say in plain words what stands out. Use only the statistics and the text; quote no number that is not there.",
}
PLAN_SYSTEM = ("Turn the GOAL into a practical project plan: 4 to 6 phases in order, each with 3 to 6 concrete tasks that begin with a verb, "
               "specific to this goal. 'target' is the deadline the goal itself states, else an empty string. 'risks': up to 4 things that could go wrong. "
               "'name' is a short name for the project.")
STEPS_SYSTEM = ("Choose the steps that carry out the INSTRUCTION, in order, from this list only: %s; and 'ask.question' (look the subject up in "
                "QueryBook's facts first, when no material is given). Each step works on the result of the one before. For 'tr.quick' set option to "
                "the target language's two-letter code; otherwise option is an empty string. Choose as few steps as do the job (at most 6).")
CHAT_SYSTEM = ("You are QueryBook's assistant in a conversation. FACTS are what QueryBook holds about the subject, each with its source. Answer the "
               "person's last message in a friendly, plain way, in at most 120 words. Base every factual statement on FACTS and set from_facts true. "
               "If FACTS do not cover it, say so first in a few words, then answer from general knowledge if you can do so reliably, and set "
               "from_facts false. Never present general knowledge as coming from QueryBook's facts.")
LABELS = {"rules": "QueryBook's rules — the text's own words, no AI", "facts": "QueryBook's facts", "language": "the Language app",
          "claude": "Claude", "gemini": "Gemini"}


class Store:
    """a small JSON list in <data>/shell/<name>.json"""

    def __init__(self, folder: str, name: str) -> None:
        self.path = os.path.join(folder, "shell", name + ".json")
        self.lock = threading.Lock()

    def load(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                rows = json.load(f)
            return rows if isinstance(rows, list) else []
        except (OSError, ValueError):
            return []

    def save(self, rows: list) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


class Assist:
    def __init__(self, folder: str, keys: Callable[[], dict], urls: Callable[[], dict],
                 ask_fn: Callable[[dict, dict], dict], check_fn: Callable[[str, dict], dict]) -> None:
        self.keys, self.urls, self.ask_fn, self.check_fn = keys, urls, ask_fn, check_fn
        self.workflows = Store(folder, "workflows")
        self.projects = Store(folder, "projects")
        self.user_styles = Store(folder, "styles")          # the user's own styles, measured from their samples (the growing library)
        self.learned = Store(folder, "learned")             # rules learned from sources, once: QueryBook's words, the page's address

    # ---------------------------------------------------------------- what is available
    def status(self) -> dict:
        k = self.keys()
        return {"claude": bool(k.get("anthropic")), "gemini": bool(k.get("gemini")),
                "model": qbcompose.CLAUDE_MODEL if k.get("anthropic") else qbcompose.GEMINI_MODEL if k.get("gemini") else "",
                "language": bool(self.urls().get("language"))}

    def catalogue(self) -> dict:
        lib = self.genres()
        every = self.shipped_learned() + self.learned.load()
        done = {r.get("source"): 0 for r in every}
        pages_of = {r.get("source"): 0 for r in every}
        for r in every:
            done[r.get("source")] += len(r.get("units") or [])
            pages_of[r.get("source")] += 1
        return {"capabilities": caps.CAPABILITIES, "steps": caps.STEPS, "ai": self.status(), "labels": LABELS,
                "genres": [{"id": g["id"], "name": g["name"], "family": g["family"], "learned": len(g.get("learned") or [])} for g in lib["genres"].values()],
                "families": lib["families"], "genres_status": lib["status"],
                "styles": [{"id": x["id"], "name": x["name"], "about": x.get("about", ""), "by": x.get("by", "")} for x in self.styles().values()],
                "fields": list(lib["fields"].values()),
                "sources": [dict(x, rules=done.get(x["id"], 0), pages=pages_of.get(x["id"], 0),
                                 status="learned from: %d rules from %d page%s" % (done[x["id"]], pages_of[x["id"]], "" if pages_of[x["id"]] == 1 else "s")
                                 if x["id"] in done else "not read: " + self._not_read[x["id"]] if x["id"] in self._not_read else x["status"])
                            for x in lib["sources"].values()],
                "learned": {"rules": sum(done.values()), "pages": len(every), "sources": len([k for k in done if k])}}

    def shipped_learned(self) -> list:
        """the rules QueryBook ships with: learned from the register's sources in a build session (tools/build_learned.py)"""
        if getattr(self, "_shipped", None) is None:
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "genres_learned.json"), encoding="utf-8") as f:
                    d = json.load(f)
                self._shipped, self._not_read = list(d.get("pages") or []), {r["source"]: r["why"] for r in d.get("not_read") or []}
            except (OSError, ValueError, KeyError):
                self._shipped, self._not_read = [], {}
        return self._shipped

    def styles(self) -> dict:
        """the style library: QueryBook's templates and the user's own styles"""
        out = dict(self.genres()["styles"])
        for r in self.user_styles.load():
            out[r["id"]] = r
        return out

    def learn_style(self, sample: str, name: str) -> dict:
        prof = writing.style_profile(sample)
        if not prof["enough"]:
            return {"by": "rules", "text": "That sample has %d words. QueryBook needs at least %d words of your own writing to measure a style — a page or more is better."
                    % (prof["words"], writing.STYLE_MIN_WORDS)}
        name = " ".join(name.split())[:40] or "My style %d" % (len(self.user_styles.load()) + 1)
        rec = {"id": "user-" + uuid.uuid4().hex[:8], "name": name, "about": "Measured from %d words of the user's own writing." % prof["words"],
               "by": "you", "profile": {f: prof[f] for f in writing.STYLE_FEATURES}, "made": time.strftime("%Y-%m-%d")}
        rows = [r for r in self.user_styles.load() if r.get("name") != name] + [rec]
        self.user_styles.save(rows)
        near = sorted(((writing.style_distance(rec["profile"], t["profile"])["distance"], t["name"]) for t in self.genres()["styles"].values()))[:2]
        return {"by": "rules", "style": rec, "text": "Saved as “%s”. It is now in the style list.\n\n%s\n\nNearest templates: %s." % (
            name, writing.style_brief(rec), ", ".join("%s (distance %s)" % (n, d) for d, n in near)),
            "note": "A style is kept as numbers measured from your sample — sentence length and variety, word choice, I and you, questions, contractions. None of your sentences is stored."}

    FETCH_MAX = 600000

    def fetch_page(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "QueryBook/1 (writing-skills learner; one page at a time)"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read(self.FETCH_MAX).decode("utf-8", "replace")

    def robots_allow(self, url: str) -> bool:
        import urllib.robotparser
        import urllib.parse
        u = urllib.parse.urlsplit(url)
        rp = urllib.robotparser.RobotFileParser("%s://%s/robots.txt" % (u.scheme, u.netloc))
        try:
            rp.read()
        except (OSError, ValueError):
            return True                                      # no robots file could be read: nothing forbids the page
        return rp.can_fetch("QueryBook", url)

    def learn_source(self, url: str, source_id: str, use_ai: bool) -> dict:
        """one page of one source -> rule units in QueryBook's own words, kept with the page's address; learned once"""
        lib = self.genres()
        url = url.strip()
        if not re.match(r"^https?://[^\s/]+\.[^\s/]+", url):
            return {"by": "rules", "text": "Give the address of one page of the source (https://…)."}
        if any(r.get("url") == url for r in self.shipped_learned() + self.learned.load()):
            return {"by": "rules", "text": "That page has already been learned from. Sources are learned once."}
        if not self.can_ai(use_ai):
            return {"by": "rules", "text": "Learning from a source needs an AI key (Control Panel → Harvesting → API keys): a model reads the page and restates its advice "
                    "as rules in its own words; QueryBook then drops any rule that repeats the page's wording."}
        if not self.robots_allow(url):
            return {"by": "rules", "text": "That site's robots rules do not allow this page to be read by a program, so QueryBook has not read it."}
        try:
            page = writing.page_text(self.fetch_page(url))
        except (OSError, ValueError) as e:
            return {"by": "rules", "text": "The page could not be read (%s)." % e}
        if len(page.split()) < 80:
            return {"by": "rules", "text": "That page has too little text to learn from."}
        ids = sorted(lib["genres"])
        schema = {"type": "object", "additionalProperties": False, "required": ["units"], "properties": {"units": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["genre", "layer", "section", "rule", "reason", "failure"], "properties": {
                "genre": {"type": "string", "enum": ids + ["any"]}, "layer": {"type": "string", "enum": list(writing.LAYERS)}, "section": {"type": "string"},
                "rule": {"type": "string"}, "reason": {"type": "string"}, "failure": {"type": "string"}}}}}}
        system = ("You read a PAGE of writing advice and restate each piece of advice as a rule IN YOUR OWN WORDS. Never copy a phrase of five or more words from "
                  "the page. For each rule give: the kind of document it is about (one of the listed ids, or 'any' for advice on all writing), the skill layer, "
                  "the section of the document it concerns (or an empty string), the rule as an instruction, the reason for it, and the failure it prevents. "
                  "Give at most 25 rules, the most useful first. Give only advice the page actually gives.")
        try:
            j, provider = self.model(system, "PAGE:\n" + page[:30000], schema)
        except (RuntimeError, OSError, ValueError) as e:
            return {"by": "rules", "text": "The AI could not read the page (%s). Nothing was learned." % e}
        res = writing.keep_units([u for u in j.get("units") or [] if isinstance(u, dict)], page, ids)
        if not res["kept"]:
            return {"by": provider, "text": "No usable rule came from that page. Nothing was saved."}
        import hashlib
        rec = {"id": uuid.uuid4().hex[:10], "source": source_id if source_id in lib["sources"] else "", "url": url, "retrieved": time.strftime("%Y-%m-%d"),
               "page_hash": hashlib.sha256(page.encode("utf-8")).hexdigest(), "by": provider, "units": res["kept"]}
        self.learned.save(self.learned.load() + [rec])
        self._genres = None                                  # the records are rebuilt with what was learned
        name = lib["sources"].get(source_id, {}).get("name") or url
        lines = ["%d rules learned from %s." % (len(res["kept"]), name), ""]
        lines += ["• [%s%s] %s" % (lib["genres"][u["genre"]]["name"] if u["genre"] in lib["genres"] else "all writing", " — " + u["section"] if u["section"] else "", u["rule"])
                  for u in res["kept"]]
        if res["dropped"]:
            lines += ["", "%d left out: %s." % (len(res["dropped"]), "; ".join(sorted({w for _r, w in res["dropped"]})))]
        return {"by": provider, "text": "\n".join(lines), "learned": len(res["kept"]),
                "note": "Rules are kept in QueryBook's own words with the page's address and the date. No passage of the page is kept. Record the site's licence terms before relying on it widely."}

    # ---------------------------------------------------------------- writing (writing.py: the grammar, the genre library, the critic)
    def genres(self) -> dict:
        if getattr(self, "_genres", None) is None:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "genres.json"), encoding="utf-8") as f:
                lib = writing.load_genres(f.read())
            for rec in self.shipped_learned() + self.learned.load():   # what was learned from sources joins the genre it is about
                for u in rec.get("units") or []:
                    for gid in ([u["genre"]] if u.get("genre") in lib["genres"] else list(lib["genres"]) if u.get("genre") == "any" and u.get("layer") in writing.LAYERS[:2] else []):
                        g = lib["genres"][gid]
                        g.setdefault("learned", []).append(dict(u, source=rec.get("source") or rec.get("url"), url=rec.get("url")))
                        if rec.get("url") not in g["provenance"]["sources"]:
                            g["provenance"]["sources"].append(rec.get("url"))
            for g in lib["genres"].values():
                if g.get("learned"):
                    g["provenance"]["status"] = "first draft from general knowledge, with %d rules learned from %d source page%s" % (
                        len(g["learned"]), len(g["provenance"]["sources"]), "" if len(g["provenance"]["sources"]) == 1 else "s")
            self._genres = lib
        return self._genres

    def write_document(self, brief: str, genre_id: str, use_ai: bool, body: dict) -> dict:
        """the writing machine, in steps the user reviews: PLAN (brief -> genre -> blueprint) -> DRAFT (facts bound, drafted,
        judged, sent back once) -> REVISE (the user's notes applied, judged again), as many times as the user likes.
        The draft is a model's (labelled); the blueprint and the critic are QueryBook's rules and judge by the same record."""
        stage = str(body.get("stage") or "plan")
        field = self.genres()["fields"].get(str(body.get("field") or ""), {})
        style = self.styles().get(str(body.get("style") or ""), {})
        lib = self.genres()
        pick = {"id": genre_id, "why": "chosen", "blend": ""} if genre_id in lib["genres"] else writing.select_genre(brief, lib)
        if not pick["id"]:
            names = ", ".join(g["name"] for g in lib["genres"].values())
            return {"by": "rules", "text": "What kind of document should this be? Choose one above, or name it in the brief.\n\nQueryBook can plan and check: " + names + ".",
                    "note": "The brief does not name a kind of document, and QueryBook does not guess one."}
        g = lib["genres"][pick["id"]]
        bp = writing.with_field_and_style(writing.blueprint(g, brief), field, style)
        plan = writing.blueprint_text(bp)
        out = {"genre": g["id"], "genre_name": g["name"], "blueprint": bp, "blueprint_text": plan, "blend": pick["blend"],
               "record_status": g["provenance"]["status"], "stage": stage, "field": field.get("id", ""), "style": style.get("id", "")}
        status = "This kind of document's record is a %s." % g["provenance"]["status"]
        if stage == "plan":                                  # the user reviews the plan before a word is drafted
            return dict(out, by="rules", text=plan, can_draft=self.can_ai(use_ai),
                        note=("This is the plan. Read it; change the brief, the kind, the field or the style if it is not what you want; then have it written. "
                              if self.can_ai(use_ai) else "This is the plan to write from. No AI key is saved, so QueryBook cannot draft it: write to the plan, "
                              "then use “Check a draft”. ") + status)
        facts: list[dict] = []
        if not bp["fiction"]:                                # bind facts: what QueryBook holds on the subject, for the draft to stand on
            try:
                r = self.ask_fn({"q": brief[:300], "mode": "qa"}, self.urls())
                facts = modes.facts_of(r.get("sections") or [])[:12]
            except (RuntimeError, OSError, ValueError, KeyError):
                facts = []
        fact_lines = ["%s — %s: %s" % (modes.clean(f.get("subject")), f.get("predicate") or "", modes.fact_value(f)) for f in facts]
        out["facts"] = fact_lines
        if not self.can_ai(use_ai):
            return dict(out, by="rules", text=plan, note="No AI key is saved, so this is the plan to write from: the sections in order, what each must "
                        "do, and the register. Write to it, then use “Check a draft” to have it judged. " + status)
        system = ("You draft documents to a blueprint. Follow the BLUEPRINT exactly. Use only what the BRIEF and the FACTS give: add no fact, name, "
                  "number, date, quotation or source of your own, and leave [square brackets] where a needed detail is missing."
                  + (" This is fiction: invent the story from the brief's premise, and keep its own facts consistent." if bp["fiction"] else ""))
        user = "BLUEPRINT:\n%s\n\nBRIEF:\n%s\n\nFACTS:\n%s" % (writing.writer_brief(bp), brief[:6000], "\n".join(fact_lines) or "(none held)")
        try:
            if stage == "revise":                            # the user's own notes on the draft they have read
                notes, old = str(body.get("notes") or "").strip(), str(body.get("draft") or "").strip()
                if not notes or not old:
                    raise ValueError("say what to change, and keep the draft on the page")
                j, provider = self.model(system + " You are revising the DRAFT to the person's NOTES: do what the notes ask, keep everything else, stay within the blueprint.",
                                         user + "\n\nDRAFT:\n" + old[:30000] + "\n\nNOTES:\n" + notes[:4000], TEXT_SCHEMA)
                draft = str(j.get("text") or "").strip()
                if not draft:
                    raise RuntimeError("empty result")
                crit = writing.critique(draft, bp)
                return dict(out, by=provider, text=draft, critique=crit, critique_text=writing.critique_text(crit), rounds=0, can_draft=True,
                            note="Revised to your notes. " + ("The critic passes it. " if crit["passed"] else "The critic finds %d thing%s to fix (below). "
                                                                 % (len(crit["revise"]), "" if len(crit["revise"]) == 1 else "s")) + status)
            j, provider = self.model(system, user, TEXT_SCHEMA)
            draft = str(j.get("text") or "").strip()
            if not draft:
                raise RuntimeError("empty result")
            crit = writing.critique(draft, bp)
            rounds = 0
            if not crit["passed"]:                           # the critic sends it back once, with what failed — the blueprint stays fixed
                rounds = 1
                j2, _ = self.model(system + " You are revising: change only what the LIST requires and keep everything else.",
                                   user + "\n\nDRAFT:\n" + draft[:20000] + "\n\nLIST (fix each):\n" + "\n".join("- " + x for x in crit["revise"][:12]), TEXT_SCHEMA)
                again = str(j2.get("text") or "").strip()
                if again:
                    c2 = writing.critique(again, bp)
                    if len(c2["revise"]) <= len(crit["revise"]):
                        draft, crit = again, c2
            return dict(out, by=provider, text=draft, critique=crit, critique_text=writing.critique_text(crit), rounds=rounds, can_draft=True,
                        note=("The critic passed it at all five layers. " if crit["passed"] else "The critic still finds %d thing%s to fix (listed below). "
                              % (len(crit["revise"]), "" if len(crit["revise"]) == 1 else "s")) + status
                        + (" Checks left for a person: %d." % len(crit["for_a_person"]) if crit["for_a_person"] else ""))
        except (RuntimeError, OSError, ValueError) as e:
            return dict(out, by="rules", text=plan, note="The AI could not draft this (%s), so this is the plan to write from. %s" % (e, status))

    def check_draft(self, text: str, genre_id: str, body: dict) -> dict:
        lib = self.genres()
        g = lib["genres"].get(genre_id)
        bp = writing.blueprint(g, "") if g else writing.plain_blueprint()
        bp = writing.with_field_and_style(bp, lib["fields"].get(str(body.get("field") or ""), {}), self.styles().get(str(body.get("style") or ""), {}))
        bp["asks"] = []
        crit = writing.critique(text, bp)
        return {"by": "rules", "critique": crit, "text": writing.critique_text(crit), "genre": genre_id,
                "note": ("Judged as %s. " % writing.a_an(g["name"]) if g else "No kind of document chosen, so only the grammar is judged (sentence flow and paragraph "
                         "pattern). Choose a kind above for all five layers. ") + ("This kind of document's record is a %s." % g["provenance"]["status"] if g else "")}

    # ---------------------------------------------------------------- the model
    def model(self, system: str, user: str, schema: dict) -> tuple[dict, str]:
        j, provider, _, _ = qbcompose.ask_model(self.keys(), HOUSE + "\n\n" + system, user, schema)
        return j, provider

    def can_ai(self, use_ai: bool) -> bool:
        k = self.keys()
        return bool(use_ai and (k.get("anthropic") or k.get("gemini")))

    def with_model(self, task: str, label: str, text: str, use_ai: bool, fallback: dict) -> dict:
        """the model's text for a task, or the rule-based fallback with the reason"""
        if not self.can_ai(use_ai):
            return dict(fallback, by="rules")
        try:
            j, provider = self.model(SYSTEMS[task], "%s:\n%s" % (label, text[:60000]), TEXT_SCHEMA)
            out = str(j.get("text") or "").strip()
            if not out:
                raise RuntimeError("empty result")
            return dict(fallback, text=out, by=provider, rules_text=fallback.get("text", ""))
        except (RuntimeError, OSError, ValueError) as e:
            return dict(fallback, by="rules", note="The AI could not do this (%s), so this is the rule-based result." % e)

    # ---------------------------------------------------------------- one task
    def run(self, body: dict) -> dict:
        task = str(body.get("task") or "")
        text = str(body.get("text") or "")[:200000].strip()
        use_ai = body.get("ai") is not False
        option = str(body.get("option") or "")
        if task.startswith("proj."):
            return self.project(task, body)
        if task.startswith("wf."):
            return self.workflow(task, body)
        if task == "chat.talk":
            return self.chat(text, [t for t in body.get("turns") or [] if isinstance(t, dict)], use_ai)
        if task == "agent.run":
            return self.agent(text, use_ai)
        if not caps.task(task) and task not in caps.STEP_IDS:
            raise ValueError("QueryBook does not know that task.")
        if not text:
            raise ValueError("There is nothing to work on yet — type or paste something first.")
        if task == "write.doc":
            r = self.write_document(text, option, use_ai, body)
        elif task == "write.check":
            r = self.check_draft(text, option, body)
        elif task == "write.style":
            r = self.learn_style(text, str(body.get("name") or ""))
        elif task == "write.learn":
            r = self.learn_source(text, option, use_ai)
        elif task == "write.grammar":
            paras = [p for p in writing.paragraphs(text) if len(writing.sentences(p)) >= 2][:12]
            r = {"by": "rules", "text": "\n\n".join("Paragraph %d\n%s" % (i + 1, writing.explain(p)) for i, p in enumerate(paras))
                 or "There is no paragraph of two or more sentences to read.",
                 "note": "Each sentence is split into its topic (what the reader already holds) and its comment (what is new). The tagger works by rules, "
                         "not by parsing: where it finds no verb it says so."}
        else:
            r = self.step(task, text, option, use_ai)
        r["task"] = task
        r["by_label"] = LABELS.get(r.get("by", "rules"), r.get("by", ""))
        return r

    def step(self, task: str, text: str, option: str, use_ai: bool) -> dict:
        if task in ("sum.brief", "sum.points", "sum.line"):
            base = caps.summarize(text, task.split(".")[1])
            if base["of"] <= 1 and task != "sum.line":
                return dict(base, by="rules", note="The text is a single sentence, so there is nothing to shorten.")
            return self.with_model(task, "TEXT", text, use_ai, base)
        if task == "write.rewrite":
            a = caps.analyze_text(text)
            base = {"text": text, "note": "Rewriting needs an AI key (Control Panel → Harvesting → API keys). Without one, here is what to fix: "
                    "the reading level is %s (grade %s); the longest sentence has %d words — split it." % (a["level"], a["grade"], len(caps.words(a["longest_sentence"]))),
                    "longest_sentence": a["longest_sentence"]}
            r = self.with_model(task, "TEXT", text, use_ai, base)
            if r["by"] != "rules":
                r.pop("note", None)
            return r
        if task.startswith("write."):
            kind = task.split(".")[1]
            base = caps.skeleton(kind, text)
            base["note"] = "No AI key is saved, so this is the outline to write from — the parts of the piece with your own words placed in them. Save a Claude or Gemini key in the Control Panel → Harvesting → API keys for a full draft."
            r = self.with_model(task, "BRIEF", text, use_ai, base)
            if r["by"] != "rules":
                r.pop("note", None)
            return r
        if task == "org.group":
            base = caps.group_items(text)
            if self.can_ai(use_ai):
                try:
                    its = caps.items(text)
                    j, provider = self.model("Put these ITEMS into 2 to 7 named topics. Every item must appear exactly once, word for word.",
                                             "ITEMS:\n" + "\n".join(its), GROUP_SCHEMA)
                    got = sorted(caps.fold(x) for g in j.get("groups") or [] for x in g.get("items") or [])
                    if got == sorted(caps.fold(x) for x in its):       # checked: nothing lost, nothing added
                        groups = [{"topic": str(g["topic"]), "items": list(g["items"])} for g in j["groups"] if g.get("items")]
                        return {"groups": groups, "by": provider, "rules_text": base["text"],
                                "text": "\n\n".join(g["topic"] + "\n" + "\n".join("  • " + x for x in g["items"]) for g in groups)}
                    base["note"] = "The AI's grouping lost or changed an item, so the rule-based grouping is shown."
                except (RuntimeError, OSError, ValueError) as e:
                    base["note"] = "The AI could not do this (%s), so this is the rule-based result." % e
            return dict(base, by="rules")
        if task in ("an.claims", "tool.check"):
            r = self.check_fn(text[:20000], self.urls())
            t = r.get("tally") or {}
            lines = ["%s — %s" % ({"VERIFIED": "✔ supported", "CONTRADICTED": "✖ contradicted", "UNKNOWN": "? no facts"}.get(c.get("verdict"), "?"), c.get("claim", ""))
                     for c in r.get("claims") or []]
            return {"claims": r.get("claims") or [], "tally": t, "by": "facts",
                    "text": "%d supported · %d contradicted · %d with no facts\n%s" % (t.get("VERIFIED", 0), t.get("CONTRADICTED", 0), t.get("UNKNOWN", 0), "\n".join(lines))}
        if task == "tr.quick":
            return self.translate(text, option or "es")
        if task == "ask.question":
            r = self.ask_fn({"q": text[:500], "mode": "qa"}, self.urls())
            facts = modes.facts_of(r.get("sections") or [])[:6]
            lines = ["%s — %s: %s" % (modes.clean(f.get("subject")), f.get("predicate") or "", modes.fact_value(f)) for f in facts]
            return {"text": "\n".join([r.get("short") or ""] + lines).strip() or "QueryBook holds no facts about that yet.", "by": "facts", "facts": facts}
        base = caps.run_step(task, text)
        base["by"] = "rules"
        if task in ("an.numbers", "an.text", "an.compare") and self.can_ai(use_ai) and base.get("text") and not base["text"].startswith("No "):
            try:
                j, provider = self.model(SYSTEMS["insight"], "STATISTICS:\n%s\n\nTEXT:\n%s" % (base["text"], text[:20000]), TEXT_SCHEMA)
                if str(j.get("text") or "").strip():
                    base["insight"] = str(j["text"]).strip()
                    base["insight_by"] = LABELS[provider]
            except (RuntimeError, OSError, ValueError):
                pass                                        # the computed result stands on its own
        return base

    # ---------------------------------------------------------------- 11 translate (through the Language app)
    def translate(self, text: str, tgt: str, src: str = "en") -> dict:
        base = (self.urls().get("language") or "").rstrip("/")
        if not base:
            raise ValueError("The Language application is not running, so nothing can be translated yet.")
        try:
            r = _post(base + "/api/lablang/cloudtr", {"text": text[:2000], "src": src, "tgt": tgt}, 60)
            return {"text": r.get("text", ""), "by": "language", "note": "Translated by %s (online), into %s." % (r.get("by", "the online service"), tgt), "lang": tgt}
        except (OSError, ValueError, urllib.error.HTTPError) as e:
            why = _reason(e)
        ws = list(dict.fromkeys(w for w in caps.WORD.findall(text)))[:200]
        try:
            f = _post(base + "/api/lablang/fill", {"src": src, "tgt": tgt, "words": ws}, 30).get("words") or {}
        except (OSError, ValueError, urllib.error.HTTPError):
            f = {}
        known = {w: v["text"] for w, v in f.items() if isinstance(v, dict) and v.get("via")}
        if not known:
            raise ValueError("This could not be translated: %s. Open Translate for the offline dictionaries, or save a Google or Gemini key." % why)
        out = caps.WORD.sub(lambda m: known.get(m.group(0), known.get(m.group(0).lower(), m.group(0))), text)
        return {"text": out, "by": "language", "lang": tgt,
                "note": "Word by word from the offline word lists (%d of %d words found) — word order and endings are not adjusted. Online translation was not available: %s."
                        % (len(known), len(ws), why)}

    # ---------------------------------------------------------------- 6 projects
    def project(self, task: str, body: dict) -> dict:
        with self.projects.lock:
            rows = self.projects.load()
            if task == "proj.list":
                return {"projects": [dict(p, progress=caps.progress(p)) for p in rows]}
            if task == "proj.plan":
                goal = " ".join(str(body.get("text") or "").split())[:1000]
                if not goal:
                    raise ValueError("Say what you want to achieve.")
                plan = caps.project_plan(goal)
                if self.can_ai(body.get("ai") is not False):
                    try:
                        j, provider = self.model(PLAN_SYSTEM, "GOAL:\n" + goal, PLAN_SCHEMA)
                        phases = [{"name": str(p.get("name") or "")[:80], "tasks": [{"text": str(t)[:300], "done": False} for t in (p.get("tasks") or [])[:8] if str(t).strip()]}
                                  for p in (j.get("phases") or [])[:8]]
                        if sum(len(p["tasks"]) for p in phases) >= 4:
                            plan = {"name": str(j.get("name") or plan["name"])[:80], "goal": goal, "target": str(j.get("target") or plan["target"])[:60],
                                    "phases": phases, "risks": [str(r)[:200] for r in (j.get("risks") or [])[:4]], "by": provider}
                    except (RuntimeError, OSError, ValueError) as e:
                        plan["note"] = "The AI could not plan this (%s), so this is QueryBook's standard five-phase plan." % e
                elif plan["by"] == "rules":
                    plan["note"] = "No AI key is saved, so this is QueryBook's standard five-phase plan for any goal. With a Claude or Gemini key the tasks are written for your goal."
                plan.update({"id": uuid.uuid4().hex[:10], "created": time.strftime("%Y-%m-%d %H:%M")})
                rows.insert(0, plan)
                self.projects.save(rows[:100])
                return {"project": dict(plan, progress=caps.progress(plan)), "text": caps.plan_text(plan), "by": plan["by"], "by_label": LABELS[plan["by"]],
                        "note": plan.get("note", "")}
            p = next((x for x in rows if x.get("id") == body.get("id")), None)
            if not p:
                raise ValueError("That project is no longer there.")
            if task == "proj.delete":
                rows.remove(p)
            elif task == "proj.toggle":
                t = p["phases"][int(body.get("phase") or 0)]["tasks"][int(body.get("item") or 0)]
                t["done"] = not t.get("done")
            elif task == "proj.add":
                txt = " ".join(str(body.get("text") or "").split())[:300]
                if txt:
                    p["phases"][int(body.get("phase") or 0)]["tasks"].append({"text": txt, "done": False})
            else:
                raise ValueError("QueryBook does not know that project action.")
            self.projects.save(rows)
            return {"projects": [dict(x, progress=caps.progress(x)) for x in rows], "text": caps.plan_text(p) if task != "proj.delete" else ""}

    # ---------------------------------------------------------------- 8 workflows
    def all_workflows(self) -> list:
        return [dict(w, starter=True) for w in caps.STARTER_WORKFLOWS] + self.workflows.load()

    def workflow(self, task: str, body: dict) -> dict:
        if task == "wf.list":
            return {"workflows": self.all_workflows(), "steps": caps.STEPS}
        if task == "wf.save":
            steps = caps.check_workflow([s for s in body.get("steps") or [] if isinstance(s, dict)])
            name = " ".join(str(body.get("name") or "").split())[:60]
            if not name or not steps:
                raise ValueError("A workflow needs a name and at least one step.")
            with self.workflows.lock:
                rows = [w for w in self.workflows.load() if w.get("name") != name]
                rows.insert(0, {"id": uuid.uuid4().hex[:10], "name": name, "about": " → ".join(caps.step_name(s["do"]) for s in steps), "steps": steps})
                self.workflows.save(rows[:100])
            return {"workflows": self.all_workflows()}
        if task == "wf.delete":
            with self.workflows.lock:
                self.workflows.save([w for w in self.workflows.load() if w.get("id") != body.get("id")])
            return {"workflows": self.all_workflows()}
        if task == "wf.run":
            steps = caps.check_workflow([s for s in body.get("steps") or [] if isinstance(s, dict)])
            if not steps:
                w = next((x for x in self.all_workflows() if x.get("id") == body.get("id")), None)
                steps = caps.check_workflow((w or {}).get("steps") or [])
            text = str(body.get("text") or "").strip()
            if not steps:
                raise ValueError("Choose a workflow, or add at least one step.")
            if not text:
                raise ValueError("Paste the text the workflow should work on.")
            return self.chain(steps, text[:200000], body.get("ai") is not False)
        raise ValueError("QueryBook does not know that workflow action.")

    def chain(self, steps: list, text: str, use_ai: bool) -> dict:
        """each step works on the result of the one before; a step that fails stops the chain and says why"""
        trace: list[dict] = []
        cur = text
        for s in steps:
            row = {"do": s["do"], "name": caps.step_name(s["do"]) + (" → " + s["option"] if s.get("option") else "")}
            try:
                r = self.step(s["do"], cur, s.get("option") or "", use_ai)
                row.update({"text": r.get("text", ""), "by": r.get("by", "rules"), "by_label": LABELS.get(r.get("by", "rules"), ""), "note": r.get("note", "")})
                if s["do"] not in ("an.text", "an.numbers", "an.claims", "org.actions"):   # a report about the text does not replace the text
                    cur = r.get("text") or cur
            except (ValueError, RuntimeError, OSError) as e:
                row.update({"text": "", "error": _reason(e)})
                trace.append(row)
                break
            trace.append(row)
        return {"trace": trace, "text": cur, "done": len([t for t in trace if not t.get("error")]), "of": len(steps)}

    # ---------------------------------------------------------------- 9 agent
    def agent(self, goal: str, use_ai: bool) -> dict:
        """the goal's instruction is turned into steps (by a model when there is a key, else by the instruction's own
        words), the steps are run as a chain, and every step is shown"""
        if not goal:
            raise ValueError("Tell the agent what you want done.")
        g = caps.split_goal(goal)
        steps: list[dict] = []
        planner = "rules"
        if self.can_ai(use_ai):
            try:
                j, planner = self.model(STEPS_SYSTEM % ", ".join("%s (%s)" % (s["id"], s["name"]) for s in caps.STEPS),
                                        "INSTRUCTION:\n%s\n\nMATERIAL GIVEN: %s" % (g["instruction"], "yes, %d words" % len(caps.words(g["material"])) if g["material"] else "none"),
                                        STEPS_SCHEMA)
                steps = [{"do": str(s.get("do")), "option": str(s.get("option") or "")} for s in (j.get("steps") or [])[:6]
                         if str(s.get("do")) in caps.STEP_IDS or s.get("do") == "ask.question"]
            except (RuntimeError, OSError, ValueError):
                planner = "rules"
        if not steps:
            planner = "rules"
            steps = caps.plan_steps(g["instruction"])
        material = g["material"]
        trace: list[dict] = []
        if not material:                                    # nothing to work on: look the subject up in the facts first
            steps = [s for s in steps if s["do"] != "ask.question"]
            subject = _subject(g["instruction"])
            r = self.step("ask.question", subject, "", use_ai)
            trace.append({"do": "ask.question", "name": "Look it up in QueryBook's facts: " + subject, "text": r["text"], "by": "facts", "by_label": LABELS["facts"]})
            material = r["text"] if r.get("facts") or len(r["text"]) > 60 else ""
            if not material:
                return {"trace": trace, "text": r["text"], "planner": planner, "planner_label": LABELS[planner], "done": 1, "of": 1,
                        "note": "QueryBook holds no facts about that, so there was nothing for the next steps to work on. Paste the text after a colon — for example: “Summarize and translate into Spanish: <your text>”."}
        else:
            steps = [s for s in steps if s["do"] != "ask.question"]
        if not steps and len(trace) == 0:
            steps = [{"do": "sum.brief"}]
            note = "The instruction named no step QueryBook knows, so the agent summarized the material."
        else:
            note = ""
        out = self.chain(caps.check_workflow(steps), material, use_ai) if steps else {"trace": [], "text": material, "done": 0, "of": 0}
        out["trace"] = trace + out["trace"]
        out.update({"planner": planner, "planner_label": LABELS[planner], "instruction": g["instruction"], "note": note,
                    "plan": [t["name"] for t in out["trace"]]})
        return out

    # ---------------------------------------------------------------- 10 chatbot
    def chat(self, message: str, turns: list, use_ai: bool) -> dict:
        if not message:
            raise ValueError("Say something first.")
        small = caps.small_talk(message)
        if small:
            return {"reply": small, "by": "rules", "by_label": "QueryBook", "facts": [], "turn": {"question": message, "subject": ""}}
        guided = modes.follow_up(message[:500], [t for t in turns if t.get("subject")][-6:])
        r = self.ask_fn({"q": guided["question"], "mode": "qa"}, self.urls())
        facts = modes.facts_of(r.get("sections") or [])[:8]
        subject = (r.get("understood") or {}).get("subject") or ""
        shown = [{"subject": modes.clean(f.get("subject")), "predicate": f.get("predicate") or "", "value": modes.fact_value(f), "where": f.get("where") or ""} for f in facts]
        short = r.get("short") or ""
        base = short or ("I found these facts:\n" + "\n".join("• %s — %s: %s" % (f["subject"], f["predicate"], f["value"]) for f in shown[:4]) if shown else "")
        out = {"facts": shown, "turn": {"question": guided["question"], "subject": subject}, "asked": guided["question"]}
        if self.can_ai(use_ai):
            try:
                talk = "\n".join("%s: %s" % ("Person" if t.get("role") != "assistant" else "Assistant", str(t.get("text") or "")[:600]) for t in turns[-8:] if t.get("text"))
                fact_lines = "\n".join("- %s — %s: %s (source: %s)" % (f["subject"], f["predicate"], f["value"], f["where"]) for f in shown) or "(none)"
                j, provider = self.model(CHAT_SYSTEM, "CONVERSATION SO FAR:\n%s\n\nFACTS:\n%s%s\n\nTHE PERSON'S LAST MESSAGE:\n%s"
                                         % (talk or "(this is the first message)", fact_lines, ("\nShort answer from the facts: " + short) if short else "", message[:2000]), CHAT_SCHEMA)
                reply = str(j.get("reply") or "").strip()
                if reply:
                    grounded = bool(j.get("from_facts")) and bool(shown or short)
                    return dict(out, reply=reply, by=provider if not grounded else "facts+" + provider,
                                by_label=("QueryBook's facts, worded by %s" % LABELS[provider]) if grounded else
                                         ("%s's general knowledge — not from QueryBook's facts" % LABELS[provider]))
            except (RuntimeError, OSError, ValueError):
                pass
        if base:
            return dict(out, reply=base, by="facts", by_label=LABELS["facts"])
        return dict(out, reply="QueryBook holds no facts about that yet, and no AI key is saved to answer from general knowledge. Try a person, a place, a word, a date or a calculation.",
                    by="rules", by_label="QueryBook")


def _subject(instruction: str) -> str:
    """'Find out about Marie Curie and translate it into Spanish' → 'Marie Curie'"""
    s = re.split(r"\b(?:and then|then|and (?:translate|summar|make|give|turn|list|quiz|check)|,\s*(?:then|translate|summar))\b", instruction, maxsplit=1, flags=re.I)[0]
    s = re.sub(r"^\s*(?:please\s+)?(?:find out|look up|tell me|search for|search|research|what do (?:you|we) know|learn)\s*(?:about|on|for)?\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*(?:summari[sz]e|translate|explain|describe)\s+", "", s, flags=re.I)
    return s.strip(" .?:") or instruction.strip()


def _post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _reason(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            return str(json.loads(e.read().decode("utf-8")).get("error") or e)[:300]
        except Exception:
            return str(e)
    return str(e)[:300]
