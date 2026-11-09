"""The VeriWave model: one entry point for every capability, behind the chat and every alternative screen.

chat(message) routes with vw/router.py, then answers (cite-or-refuse), codes, creates text, image, video or audio, or
opens a QueryBook screen. The local engine always works; the Claude engine (when a key is set) does the generative work
where it is better, and VeriWave's own rules (citations, trust gate, safe files, safe SVG) apply to both.

Lean:
    structure Turn where
      route : Route
      engine : String
    deriving Repr
    def engineFor (route : Route) (claude : Bool) (asked : String) : String :=
      if asked == "local" || !claude then "local"
      else if route == .answer || route == .screen then "local+claude"
      else "claude"
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from . import answer, audiogen, codegen, core, imagegen, interfaces, registry, router, textgen, videogen
from .backends import BackendError, Claude, parse_json_reply, strip_fence
from .factstore import FactStore, dedupe
from .querybook import Connection, import_ask
from .store import Store

CHAT_SYSTEM = ("You are VeriWave, the QueryBook AI model: helpful, direct and honest. Keep replies short unless asked for "
               "more. Never state a fact you are unsure of as certain; when the user wants a verified fact, suggest the "
               "Answer screen, which cites QueryBook's sources or says it doesn't know.")


def engine_for(route: str, claude_on: bool, asked: str) -> str:
    """which engine serves a request: 'local', 'claude', or 'local+claude' (QueryBook answers, Claude rewords them)

    Lean:
        theorem local_when_asked (r : Route) (c : Bool) : engineFor r c "local" = "local" := by simp [engineFor]
        theorem local_without_key (r : Route) (a : String) : engineFor r false a = "local" := by simp [engineFor]
        #guard engineFor .answer true "" == "local+claude"                  -- py: engine_for("answer", True, "") == "local+claude"
        #guard engineFor .image true "" == "claude"                          -- py: engine_for("image", True, "") == "claude"
        #guard engineFor .image false "" == "local"                          -- py: engine_for("image", False, "") == "local"
    """
    if asked == "local" or not claude_on:
        return "local"
    if route in ("answer", "open"):
        return "local+claude"
    return "claude"


def chat_reply(route: str) -> str:
    """the short line that introduces a result in the chat

    Lean:
        def chatReply (r : Route) : String := match r with
          | .code => "Here is your application. Preview it, read the files, or download it."
          | .text => "Here is the text."
          | .image => "Here is the picture."
          | .video => "Here is the film and its storyboard."
          | .audio => "Here is the audio."
          | .screen => "Opening it."
          | .answer => ""
          | .chat => ""
        #guard chatReply .image == "Here is the picture."                    -- py: chat_reply("image") == "Here is the picture."
    """
    return {"code": "Here is your application. Preview it, read the files, or download it.", "text": "Here is the text.",
            "image": "Here is the picture.", "video": "Here is the film and its storyboard.", "audio": "Here is the audio.",
            "open": "Opening it."}.get(route, "")


def greeting() -> str:
    """the local engine's reply to hello, thanks and 'what can you do'

    Lean:
        #guard (capabilitiesText 407 82 102 223).startsWith "VeriWave is"    -- py: greeting().startswith("Hello")
    """
    return ("Hello! " + answer.capabilities_text() + " Ask me anything, or say what to make: \"build a to-do app\", "
            "\"draw a lighthouse at sunset\", \"compose a calm melody\", \"make a video about bees\", \"open the Language Lab\".")


def understand_fallback(question: str) -> dict:
    """a question's subject when QueryBook's ask module is not beside VeriWave: its words, lower case

    Lean:
        def fallbackSubject (q : String) : String := " ".intercalate (words q)
        #guard fallbackSubject "" == ""                                      -- py: understand_fallback("")["kind"] == "empty"
    """
    ws = core.words(question)
    subject = " ".join(ws)
    return {"question": question, "kind": "fact" if ws else "empty", "subject": subject, "variants": [subject] if ws else [], "hints": []}


def merge_facts(qb: dict, intent: dict, facts: list[dict]) -> dict:
    """QueryBook's answer with the data drive's facts added to its facts section (each fact once), and 'ufcs' asked

    Lean:
        def mergeCount (fromApps fromDrive : List Hit) : Nat := (dedupeHits (fromApps ++ fromDrive)).length
        #guard mergeCount [] [] == 0                                         -- py: merge_facts({}, {"kind": "fact"}, [])["asked"] == []
    """
    out = dict(qb)
    out["understood"] = dict(qb.get("understood") or intent)
    out["asked"] = list(qb.get("asked") or [])
    out["unavailable"] = list(qb.get("unavailable") or [])
    sections = [dict(sec) for sec in (qb.get("sections") or [])]
    if facts:
        out["asked"].append("ufcs")
        found = False
        for sec in sections:
            if sec.get("kind") == "facts":
                sec["items"] = factstore_dedupe(list(sec.get("items") or []) + facts)
                found = True
        if not found:
            sections.append({"source": "Facts", "app": "ufcs", "kind": "facts", "items": factstore_dedupe(facts)})
    out["sections"] = sections
    return out


def factstore_dedupe(facts: list[dict]) -> list[dict]:
    """vw.factstore.dedupe, kept by name here so the merge reads on its own

    Lean:
        #guard (dedupeHits []).length == 0                                   -- py: factstore_dedupe([]) == []
    """
    return dedupe(facts)


def zip_name(iid: str) -> str:
    """the download name of a code project

    Lean:
        def zipName (id : String) : String := id ++ ".zip"
        #guard zipName "a" == "a.zip"                                         -- py: zip_name("a") == "a.zip"
    """
    return iid + ".zip"


class VeriWave:
    """the model: QueryBook connection, creations store, Claude engine

    Lean:
        structure Model where
          claudeOn : Bool
          appsRunning : Bool
    """

    def __init__(self, conn: Connection, store: Store, claude: Claude, facts: FactStore) -> None:
        """Lean:
            def Model.new (c a : Bool) : Model := ⟨c, a⟩
        """
        self.conn = conn
        self.store = store
        self.claude = claude
        self.facts = facts
        self.ask_mod: object | None = import_ask()

    def understand(self, question: str) -> dict:
        """what a question asks about (QueryBook's own ask.understand: kind, subject, variants, predicate hints)

        Lean:
            #guard fallbackSubject "Marie Curie?" == "marie curie"          -- py: understand_fallback("Marie Curie?")["subject"] == "marie curie"
        """
        if self.ask_mod is not None:
            return dict(self.ask_mod.understand(question))  # type: ignore[attr-defined]
        return understand_fallback(question)

    def direct_facts(self, intent: dict) -> list[dict]:
        """facts about the question's subject read straight from the data drive (UFCS, Commons, bulk shards)

        Lean:
            def wantsFacts (kind : String) : Bool := kind == "fact" || kind == "word"
            #guard wantsFacts "fact" && !wantsFacts "math"                  -- py: VeriWave.wants_facts("fact") and not VeriWave.wants_facts("math")
        """
        if not VeriWave.wants_facts(str(intent.get("kind") or "")):
            return []
        found: list[dict] = []
        for v in [str(x) for x in (intent.get("variants") or [intent.get("subject") or ""])][:3]:
            found += self.facts.lookup(v, 40)
            if len(found) >= 40:
                break
        return found

    @staticmethod
    def wants_facts(kind: str) -> bool:
        """questions that facts can answer (not calculations, not empty)

        Lean:
            #guard !wantsFacts "empty"                                       -- py: not VeriWave.wants_facts("empty")
        """
        return kind in ("fact", "word")

    # ------------------------------------------------------------------ Answer
    def ask(self, question: str, min_trust: int, last_subject: str, engine: str) -> dict:
        """a cite-or-refuse answer; with Claude on, the cited facts reworded into prose (verdict and citations unchanged)

        Lean:
            def keepsVerdict (before after : Verdict) : Bool := before == after
            theorem rewording_keeps (v : Verdict) : keepsVerdict v v = true := by cases v <;> rfl
        """
        urls = self.conn.app_urls()
        resolved = answer.resolve_followup(question, last_subject) or question
        qb: dict = {}
        if self.ask_mod is not None and urls:
            qb = self.ask_mod.answer(resolved, urls)  # type: ignore[attr-defined]
        intent = dict(qb.get("understood") or self.understand(resolved))
        qb = merge_facts(qb, intent, self.direct_facts(intent))
        res = answer.compose(question, qb, min_trust, last_subject, bool(urls) or bool(self.facts.status()["connected"]))
        res["engine"] = "local"
        if res["citations"] and engine_for("answer", self.claude.available, engine) == "local+claude":
            try:
                res["prose"] = self.claude.complete(answer.GROUNDED_SYSTEM, [{"role": "user", "content": answer.grounded_prompt(res)}], 2000, "low")
                res["engine"] = "local+claude"
            except BackendError as e:
                res["engine_note"] = str(e)
        return res

    def facts_about(self, subject: str) -> tuple[list[str], list[str]]:
        """QueryBook's offered facts about a subject (texts and sources), for grounding text

        Lean:
            def takeFacts (n : Nat) (xs : List String) : List String := xs.take n
            theorem takeFacts_le (n : Nat) (xs : List String) : (takeFacts n xs).length ≤ n := List.length_take_le _ _
        """
        urls = self.conn.app_urls()
        if not subject:
            return [], []
        qb: dict = {}
        if self.ask_mod is not None and urls:
            try:
                qb = self.ask_mod.answer(subject, urls)  # type: ignore[attr-defined]
            except Exception:
                qb = {}
        qb = merge_facts(qb, {"kind": "fact", "subject": subject, "variants": [subject], "hints": []}, self.facts.lookup(subject, 12))
        cites, _, _ = answer.citations_from(qb, answer.verdict.MIN_TRUST)
        cites = [c for c in cites if c["kind"] in ("fact", "word")][:8]
        return [str(c["text"]) for c in cites], [str(c["where"]) for c in cites]

    # ------------------------------------------------------------------ Code
    def code(self, prompt: str, kind: str, engine: str) -> dict:
        """an application from a prompt, saved as a creation (files, zip, preview URL)

        Lean:
            #guard zipName "000001-todo" == "000001-todo.zip"                -- py: zip_name("000001-todo") == "000001-todo.zip"
        """
        res: dict = {}
        note = ""
        if engine_for("code", self.claude.available, engine) == "claude":
            try:
                res = codegen.generate_claude(prompt, self.claude, [])
            except BackendError as e:
                note = str(e) + " The local engine made this instead."
        if not res:
            res = codegen.generate_local(prompt, kind)
        files = {k: v.encode("utf-8") for k, v in res["files"].items()}
        saved = self.store.save("code", prompt, files, {"title": res["title"], "entry": res["entry"], "engine": res["engine"]})
        res["id"] = saved["id"]
        res["urls"] = saved["urls"]
        res["zip"] = "/api/vw/zip?id=" + saved["id"] + "&name=" + zip_name(saved["id"])
        res["preview_url"] = saved["urls"].get(res["entry"], "") if res["preview"] else ""
        if note:
            res["engine_note"] = note
        return res

    # ------------------------------------------------------------------ Create
    def text(self, prompt: str, engine: str) -> dict:
        """text from a prompt, grounded in QueryBook facts about its subject when there are any

        Lean:
            #guard bodyKind .poem == "verse"                                  -- py: textgen.generate_local("a poem about rain", [], [])["layout"] == "verse"
        """
        subject = textgen.subject_of(prompt)
        facts, sources = self.facts_about(subject)
        res: dict = {}
        if engine_for("text", self.claude.available, engine) == "claude":
            try:
                body = self.claude.complete(textgen.TEXT_SYSTEM, [{"role": "user", "content": textgen.claude_prompt(prompt, facts, sources)}], 16000, "medium")
                res = {"form": textgen.detect_form(prompt), "subject": subject, "title": textgen.title_case(subject), "text": body,
                       "lines": body.split("\n"), "layout": "prose", "engine": "claude", "grounded": len(facts)}
            except BackendError as e:
                res = textgen.generate_local(prompt, facts, sources)
                res["engine_note"] = str(e) + " The local engine wrote this instead."
        if not res:
            res = textgen.generate_local(prompt, facts, sources)
        res["sources"] = sources
        saved = self.store.save("text", prompt, {"text.md": ("# " + res["title"] + "\n\n" + res["text"] + "\n").encode("utf-8")},
                                {"title": res["title"], "engine": res["engine"]})
        res["id"] = saved["id"]
        res["urls"] = saved["urls"]
        return res

    def image(self, prompt: str, engine: str) -> dict:
        """a picture from a prompt (SVG)

        Lean:
            #guard safeSvg "<svg></svg>" == "<svg></svg>"                     -- py: imagegen.safe_svg("<svg></svg>") == "<svg></svg>"
        """
        res: dict = {}
        if engine_for("image", self.claude.available, engine) == "claude":
            try:
                svg = imagegen.safe_svg(strip_fence(self.claude.complete(imagegen.IMAGE_SYSTEM, [{"role": "user", "content": prompt}], 32000, "medium")))
                if svg:
                    res = {"svg": svg, "engine": "claude", "kind": "scene", "elements": [], "light": ""}
                else:
                    res = imagegen.paint(prompt)
                    res["engine_note"] = "Claude's drawing was not a safe SVG; the local painter made this instead."
            except BackendError as e:
                res = imagegen.paint(prompt)
                res["engine_note"] = str(e) + " The local painter made this instead."
        if not res:
            res = imagegen.paint(prompt)
        saved = self.store.save("image", prompt, {"image.svg": res["svg"].encode("utf-8")}, {"engine": res["engine"]})
        res["id"] = saved["id"]
        res["url"] = saved["urls"]["image.svg"]
        res.pop("svg", None)
        return res

    def video(self, prompt: str, engine: str) -> dict:
        """a short film from a prompt: storyboard and animated SVG

        Lean:
            #guard filmSeconds 4 == 20                                        -- py: videogen.generate_local("a video about bees")["seconds"] == 20
        """
        res: dict = {}
        if engine_for("video", self.claude.available, engine) == "claude":
            try:
                res = videogen.from_claude(prompt, parse_json_reply(self.claude.complete(videogen.VIDEO_SYSTEM, [{"role": "user", "content": prompt}], 4000, "low")))
            except BackendError as e:
                res = videogen.generate_local(prompt)
                res["engine_note"] = str(e) + " The local engine made this instead."
        if not res:
            res = videogen.generate_local(prompt)
        board = "\n".join(str(i + 1) + ". " + s["caption"] for i, s in enumerate(res["scenes"]))
        saved = self.store.save("video", prompt, {"film.svg": res["svg"].encode("utf-8"), "storyboard.txt": (board + "\n").encode("utf-8")},
                                {"engine": res["engine"], "seconds": res["seconds"]})
        res["id"] = saved["id"]
        res["url"] = saved["urls"]["film.svg"]
        res["storyboard_url"] = saved["urls"]["storyboard.txt"]
        res.pop("svg", None)
        return res

    def audio(self, prompt: str, engine: str) -> dict:
        """audio from a prompt: music or an effect (local synthesiser), or speech (espeak-ng); Claude can write the words to say

        Lean:
            #guard planKind "music" == "music"                                -- py: audiogen.plan("a calm melody")["kind"] == "music"
        """
        p = audiogen.plan(prompt)
        if p["kind"] == "speech":
            return self.speech(str(p["text"]), prompt)
        info = audiogen.render(prompt)
        wav = info.pop("wav")
        saved = self.store.save("audio", prompt, {"audio.wav": wav}, {"engine": "local", "seconds": info["seconds"]})
        info["id"] = saved["id"]
        info["url"] = saved["urls"]["audio.wav"]
        return info

    def speech(self, text: str, prompt: str) -> dict:
        """the words spoken by espeak-ng (as QueryBook's Language Builder does), or the reason it can't be done here

        Lean:
            def speechEngine (espeakNg espeak : Bool) : String := if espeakNg then "espeak-ng" else if espeak then "espeak" else ""
            #guard speechEngine false false == ""                             -- py: isinstance(VeriWave.find_espeak(), str)
        """
        exe = VeriWave.find_espeak()
        if not exe:
            return {"kind": "speech", "text": text, "error": "Speech needs espeak-ng (QueryBook's speech engine), which is not installed "
                    "on this computer. Install it, or use the Language Lab's Speech tab.", "engine": "local"}
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "speech.wav")
            subprocess.run([exe, "-w", out, text[:2000]], check=False, capture_output=True, timeout=60)
            if not os.path.isfile(out):
                return {"kind": "speech", "text": text, "error": "espeak-ng did not produce audio.", "engine": "local"}
            with open(out, "rb") as f:
                wav = f.read()
        saved = self.store.save("audio", prompt, {"speech.wav": wav}, {"engine": "espeak-ng"})
        return {"kind": "speech", "text": text, "id": saved["id"], "url": saved["urls"]["speech.wav"], "engine": "espeak-ng"}

    @staticmethod
    def find_espeak() -> str:
        """the espeak-ng (or espeak) program, or ''

        Lean:
            #guard speechEngine true false == "espeak-ng"                     -- py: VeriWave.find_espeak() in ("", shutil.which("espeak-ng") or "", shutil.which("espeak") or "")
        """
        return shutil.which("espeak-ng") or shutil.which("espeak") or ""

    # ------------------------------------------------------------------ Chat
    def chat(self, message: str, history: list[dict], last_subject: str, engine: str) -> dict:
        """one chat turn: route the message, run the capability, return the reply and the result card

        Lean:
            theorem chat_explicit (msg : String) (r : Route) (h : explicitRoute msg = some r) : route msg = r := route_explicit msg r h
        """
        rt = router.route(message)
        body = router.strip_explicit(message)
        out: dict = {"route": rt, "reply": chat_reply(rt), "result": None}
        if rt == "answer":
            res = self.ask(body, answer.verdict.MIN_TRUST, last_subject, engine)
            out["result"] = res
            out["reply"] = res.get("prose") or res["short"]
            out["subject"] = res.get("subject") or last_subject
        elif rt == "code":
            out["result"] = self.code(body, "", engine)
        elif rt == "text":
            out["result"] = self.text(body, engine)
        elif rt == "image":
            out["result"] = self.image(body, engine)
        elif rt == "video":
            out["result"] = self.video(body, engine)
        elif rt == "audio":
            out["result"] = self.audio(body, engine)
            if out["result"].get("error"):
                out["reply"] = out["result"]["error"]
        elif rt == "open":
            iid = router.screen_for(body)
            item = interfaces.by_id(iid) if iid else None
            out["result"] = {"interface": iid, "name": item["name"] if item is not None else ""}
            out["reply"] = ("Opening " + item["name"] + ".") if item is not None else "I don't know that screen. The QueryBook menu lists them all."
        else:
            out["reply"] = self.converse(body, history, engine)
        self.store.log({"message": message, "route": rt, "reply": out["reply"][:500]})
        return out

    def converse(self, message: str, history: list[dict], engine: str) -> str:
        """small talk: Claude when on, else the local greeting

        Lean:
            def converseEngine (claude : Bool) (asked : String) : String := if claude && asked != "local" then "claude" else "local"
            #guard converseEngine false "" == "local"                          -- py: engine_for("chat", False, "") == "local"
        """
        if engine_for("chat", self.claude.available, engine) == "claude":
            msgs = [{"role": str(h.get("role")), "content": str(h.get("content"))} for h in history[-12:]
                    if h.get("role") in ("user", "assistant") and h.get("content")]
            msgs.append({"role": "user", "content": message})
            try:
                return self.claude.complete(CHAT_SYSTEM, msgs, 4000, "low")
            except BackendError as e:
                return greeting() + " (" + str(e) + ")"
        return greeting()

    def status(self) -> dict:
        """everything the window needs at start: engines, QueryBook, the registry in numbers, the interfaces

        Lean:
            #guard catalogSize == 67                                           -- py: len(interfaces.catalog()) == 67
        """
        urls = self.conn.app_urls()
        items = interfaces.catalog()
        for it in items:
            it["url"] = interfaces.url_for(it, urls)
        return {"version": VERSION, "engine": {"claude": self.claude.available, "model": self.claude.model if self.claude.available else ""},
                "querybook": self.conn.status(), "registry": registry.summary(), "interfaces": items,
                "espeak": bool(VeriWave.find_espeak()), "data": self.store.root, "facts": self.facts.status()}


VERSION = "0.1.0"
