"""VeriWave Code: describe an application, get its files, a live preview and a download.

Local engine: a deterministic generator that recognises the kind of application asked for and writes a complete,
working, single-file web application (or a Python command-line program), titled and configured from the prompt. Any
prompt it doesn't recognise becomes a record-keeping application whose fields come from the prompt.
Claude engine: the prompt goes to Claude under a strict file contract; the result is checked before it is shown.

Lean:
    inductive Kind where
      | python | landing | todo | calculator | timer | notes | quiz | converter | drawing | game | records
    deriving Repr, BEq, DecidableEq
    def Kind.name : Kind → String
      | .python => "python" | .landing => "landing" | .todo => "todo" | .calculator => "calculator" | .timer => "timer"
      | .notes => "notes" | .quiz => "quiz" | .converter => "converter" | .drawing => "drawing" | .game => "game"
      | .records => "records"
    def pageKey (title : String) : String := "app:" ++ slug title
"""
from __future__ import annotations

import html
import json

from . import core
from .backends import BackendError, Claude, parse_json_reply

KIND_ORDER = ("python", "landing", "todo", "calculator", "timer", "notes", "quiz", "converter", "drawing", "game")
KINDS: dict[str, list[str]] = {
    "python": ["python", "command line", "cli", "script"],
    "landing": ["landing page", "website", "web site", "homepage", "home page", "portfolio", "site for"],
    "todo": ["to do", "todo", "task list", "checklist", "tasks"],
    "calculator": ["calculator", "calc"],
    "timer": ["timer", "stopwatch", "countdown", "pomodoro"],
    "notes": ["notes", "note taking", "notepad", "journal", "diary"],
    "quiz": ["quiz", "flashcard", "flash card", "flashcards", "trivia", "test me"],
    "converter": ["converter", "convert", "conversion", "unit"],
    "drawing": ["drawing", "paint", "sketch", "whiteboard", "canvas"],
    "game": ["game", "guess", "guessing"],
}
BASE_TITLES: dict[str, str] = {
    "todo": "To-Do List", "calculator": "Calculator", "timer": "Timer", "notes": "Notes", "quiz": "Quiz",
    "converter": "Unit Converter", "game": "Number Guessing Game", "drawing": "Sketch Pad", "landing": "Welcome",
    "python": "Command-Line Tool", "records": "Records",
}
STOP = {"a", "an", "the", "app", "application", "make", "build", "create", "code", "write", "me", "please", "simple", "small",
        "web", "page", "that", "which", "with", "for", "to", "and", "my", "program", "tool", "single", "file", "html",
        "javascript", "of", "fields", "columns", "field", "column"}
ENDERS = {"with", "that", "which", "and", "for", "to", "using", "where"}


def detect_kind(prompt: str) -> str:
    """the kind of application a prompt asks for; 'records' when none is recognised

    Lean:
        def kindTable : List (Kind × List String) := [
          (.python, ["python", "command line", "cli", "script"]),
          (.landing, ["landing page", "website", "web site", "homepage", "home page", "portfolio", "site for"]),
          (.todo, ["to do", "todo", "task list", "checklist", "tasks"]), (.calculator, ["calculator", "calc"]),
          (.timer, ["timer", "stopwatch", "countdown", "pomodoro"]),
          (.notes, ["notes", "note taking", "notepad", "journal", "diary"]),
          (.quiz, ["quiz", "flashcard", "flash card", "flashcards", "trivia", "test me"]),
          (.converter, ["converter", "convert", "conversion", "unit"]),
          (.drawing, ["drawing", "paint", "sketch", "whiteboard", "canvas"]), (.game, ["game", "guess", "guessing"])]
        def detectKind (prompt : String) : Kind :=
          match kindTable.find? (fun p => hasAny (words prompt) p.2) with
          | some p => p.1
          | none => .records
        #guard detectKind "Build me a to-do app" == .todo                -- py: detect_kind("Build me a to-do app") == "todo"
        #guard detectKind "a website for my bakery" == .landing          -- py: detect_kind("a website for my bakery") == "landing"
        #guard detectKind "track my books with title, author" == .records   -- py: detect_kind("track my books with title, author") == "records"
    """
    ws = core.words(prompt)
    for kind in KIND_ORDER:
        if core.has_any(ws, KINDS[kind]):
            return kind
    return "records"


def cap(word: str) -> str:
    """a word with its first ASCII letter in upper case

    Lean:
        def cap (w : String) : String := match w.toList with
          | [] => ""
          | c :: cs => String.mk (c.toUpper :: cs)
        #guard cap "bakery" == "Bakery"                                  -- py: cap("bakery") == "Bakery"
    """
    if not word:
        return ""
    c = word[0]
    return (chr(ord(c) - 32) if "a" <= c <= "z" else c) + word[1:]


def phrase_after(ws: list[str], leads: list[str], skip: list[str], most: int) -> list[str]:
    """the words after the first lead word, skipping leading filler, stopping at a joining word or after `most` words

    Lean:
        def enders : List String := ["with", "that", "which", "and", "for", "to", "using", "where"]
        def afterLead (leads : List String) : List String → List String
          | [] => []
          | w :: ws => if leads.contains w then ws else afterLead leads ws
        def phraseAfter (ws leads skip : List String) (most : Nat) : List String :=
          (((afterLead leads ws).dropWhile skip.contains).takeWhile (fun w => !enders.contains w)).take most
        theorem phraseAfter_len (ws leads skip : List String) (most : Nat) : (phraseAfter ws leads skip most).length ≤ most :=
          List.length_take_le _ _
        #guard phraseAfter ["a", "site", "for", "my", "corner", "bakery", "with", "menu"] ["for"] ["my", "a", "an"] 4 == ["corner", "bakery"]   -- py: phrase_after(["a", "site", "for", "my", "corner", "bakery", "with", "menu"], ["for"], ["my", "a", "an"], 4) == ["corner", "bakery"]
    """
    i = 0
    while i < len(ws) and ws[i] not in leads:
        i += 1
    rest = ws[i + 1:] if i < len(ws) else []
    j = 0
    while j < len(rest) and rest[j] in skip:
        j += 1
    out: list[str] = []
    for w in rest[j:]:
        if w in ENDERS:
            break
        out.append(w)
    return out[:most]


def title_from(prompt: str, kind: str) -> str:
    """the application's title: what the prompt calls it, else a subject named in it, else the kind's own name

    Lean:
        def baseTitle (k : Kind) : String := match k with
          | .todo => "To-Do List" | .calculator => "Calculator" | .timer => "Timer" | .notes => "Notes" | .quiz => "Quiz"
          | .converter => "Unit Converter" | .game => "Number Guessing Game" | .drawing => "Sketch Pad"
          | .landing => "Welcome" | .python => "Command-Line Tool" | .records => "Records"
        def titleFrom (prompt : String) (k : Kind) : String :=
          let ws := words prompt
          let named := phraseAfter ws ["called", "named", "titled"] [] 4
          if !named.isEmpty then " ".intercalate (named.map cap)
          else
            let subj := match k with
              | .records => phraseAfter ws ["track", "manage", "log", "catalog", "catalogue"] ["my", "of", "the", "a", "an"] 3
              | .landing => phraseAfter ws ["for"] ["my", "a", "an", "the", "our"] 4
              | _ => []
            if subj.isEmpty then baseTitle k
            else " ".intercalate (subj.map cap) ++ (if k == .records then " Tracker" else "")
        #guard titleFrom "a website for my corner bakery" .landing == "Corner Bakery"   -- py: title_from("a website for my corner bakery", "landing") == "Corner Bakery"
        #guard titleFrom "track my books with title, author" .records == "Books Tracker"   -- py: title_from("track my books with title, author", "records") == "Books Tracker"
        #guard titleFrom "a timer called focus box" .timer == "Focus Box"   -- py: title_from("a timer called focus box", "timer") == "Focus Box"
        #guard titleFrom "a calculator" .calculator == "Calculator"        -- py: title_from("a calculator", "calculator") == "Calculator"
    """
    ws = core.words(prompt)
    named = phrase_after(ws, ["called", "named", "titled"], [], 4)
    if named:
        return " ".join(cap(w) for w in named)
    subj: list[str] = []
    if kind == "records":
        subj = phrase_after(ws, ["track", "manage", "log", "catalog", "catalogue"], ["my", "of", "the", "a", "an"], 3)
    elif kind == "landing":
        subj = phrase_after(ws, ["for"], ["my", "a", "an", "the", "our"], 4)
    if not subj:
        return BASE_TITLES[kind]
    return " ".join(cap(w) for w in subj) + (" Tracker" if kind == "records" else "")


def fields_from(prompt: str) -> list[str]:
    """the record fields a prompt lists after 'with', 'fields' or 'columns' (commas, 'and', ';' or '/' between them)

    Lean:
        def fieldStop : List String := ["a", "an", "the", "app", "application", "make", "build", "create", "code", "write",
          "me", "please", "simple", "small", "web", "page", "that", "which", "with", "for", "to", "and", "my", "program",
          "tool", "single", "file", "html", "javascript", "of", "fields", "columns", "field", "column"]
        def listAfter (low : String) : Option String :=
          [" with ", " fields ", " columns ", " fields: ", " columns: "].findSome? (fun k =>
            match low.splitOn k with
            | _ :: rest@(_ :: _) => some (k.intercalate rest)
            | _ => none)
        def fieldsOf (rest : String) : List String :=
          let parts := (((rest.replace ";" ",").replace "/" ",").replace " and " ",").splitOn ","
          let names := parts.map (fun p => " ".intercalate (((words p).filter (fun w => !fieldStop.contains w)).map cap))
          ((names.filter (· != "")).eraseDups).take 8
        def fieldsFrom (prompt : String) : List String :=
          match listAfter (" " ++ lower prompt ++ " ") with
          | none => ["Name", "Notes"]
          | some rest => match fieldsOf rest with
            | [] => ["Name", "Notes"]
            | fs => fs
        #guard fieldsFrom "track my books with title, author and year read" == ["Title", "Author", "Year Read"]   -- py: fields_from("track my books with title, author and year read") == ["Title", "Author", "Year Read"]
        #guard fieldsFrom "a records app" == ["Name", "Notes"]          -- py: fields_from("a records app") == ["Name", "Notes"]
    """
    low = " " + core.lower(prompt) + " "
    rest = ""
    for k in (" with ", " fields ", " columns ", " fields: ", " columns: "):
        i = low.find(k)
        if i >= 0:
            rest = low[i + len(k):]
            break
    else:
        return ["Name", "Notes"]
    parts = rest.replace(";", ",").replace("/", ",").replace(" and ", ",").split(",")
    out: list[str] = []
    for part in parts:
        name = " ".join(cap(w) for w in core.words(part) if w not in STOP)
        if name and name not in out:
            out.append(name)
    return out[:8] if out else ["Name", "Notes"]


def number_before(ws: list[str], units: list[str], default: int) -> int:
    """the number written just before one of the unit words ('10 minutes'), else the default

    Lean:
        def numberBefore (units : List String) (dflt : Nat) : List String → Nat
          | a :: rest@(b :: _) => if a.all Char.isDigit && !a.isEmpty && units.contains b then a.toNat! else numberBefore units dflt rest
          | _ => dflt
        #guard numberBefore ["minutes", "min"] 5 ["a", "10", "minutes", "timer"] == 10   -- py: number_before(["a", "10", "minutes", "timer"], ["minutes", "min"], 5) == 10
        #guard numberBefore ["minutes"] 5 ["timer"] == 5                  -- py: number_before(["timer"], ["minutes"], 5) == 5
    """
    for i in range(len(ws) - 1):
        if ws[i].isdigit() and ws[i].isascii() and ws[i + 1] in units:
            return int(ws[i])
    return default


def number_after(ws: list[str], leads: list[str], default: int) -> int:
    """the number written just after one of the lead words ('1 to 50' -> 50), else the default

    Lean:
        def numberAfter (leads : List String) (dflt : Nat) : List String → Nat
          | a :: rest@(b :: _) => if leads.contains a && b.all Char.isDigit && !b.isEmpty then b.toNat! else numberAfter leads dflt rest
          | _ => dflt
        #guard numberAfter ["to"] 100 ["from", "1", "to", "50"] == 50     -- py: number_after(["from", "1", "to", "50"], ["to"], 100) == 50
    """
    for i in range(len(ws) - 1):
        if ws[i] in leads and ws[i + 1].isdigit() and ws[i + 1].isascii():
            return int(ws[i + 1])
    return default


def strip_request(prompt: str) -> str:
    """a prompt without its request words ('please make me a …'), for showing as a description

    Lean:
        def requestWords : List String := ["please", "make", "build", "create", "code", "write", "me", "a", "an"]
        def stripRequest (prompt : String) : String := " ".intercalate ((words prompt).dropWhile requestWords.contains)
        #guard stripRequest "Please build me a site for bakers" == "site for bakers"   -- py: strip_request("Please build me a site for bakers") == "site for bakers"
    """
    ws = core.words(prompt)
    i = 0
    while i < len(ws) and ws[i] in ("please", "make", "build", "create", "code", "write", "me", "a", "an"):
        i += 1
    return " ".join(ws[i:])


def _page(title: str, body: str, script: str, extra_css: str) -> str:
    """one complete, self-contained page: the shared look (light and dark), the title, the body and its script

    Lean:
        -- the page's storage key and heading are fixed by its title
        #guard pageKey "To-Do List" == "app:to-do-list"                  -- py: 'const KEY = "app:to-do-list"' in _page("To-Do List", "", "", "")
        #guard pageKey "Q&A" == "app:q-a"                                 -- py: '<h1>Q&amp;A</h1>' in _page("Q&A", "", "", "") and '"app:q-a"' in _page("Q&A", "", "", "")
    """
    t = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t}</title>
<style>
:root {{ --bg:#f6f7f9; --panel:#fff; --ink:#1d2330; --muted:#5b6475; --line:#dde1e8; --accent:#2f5fb3; --accent-ink:#fff; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#12151b; --panel:#1b2029; --ink:#e7eaf0; --muted:#9aa3b5; --line:#2c3340; --accent:#6f9be8; --accent-ink:#0d1320; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:720px; margin:0 auto; padding:24px 16px 60px; }}
h1 {{ font-size:26px; margin:0 0 16px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:14px; }}
input, select, textarea, button {{ font:inherit; color:inherit; }}
input, select, textarea {{ background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:8px 10px; width:100%; }}
button {{ border:0; border-radius:8px; padding:8px 14px; background:var(--accent); color:var(--accent-ink); font-weight:600; cursor:pointer; }}
button.ghost {{ background:transparent; color:var(--accent); border:1px solid var(--line); }}
.row {{ display:flex; gap:8px; align-items:center; }} .row > * {{ flex:1; }} .row > button {{ flex:none; }}
.muted {{ color:var(--muted); }} ul {{ list-style:none; padding:0; margin:0; }}
li {{ display:flex; gap:10px; align-items:center; padding:8px 0; border-bottom:1px solid var(--line); }}
{extra_css}
</style>
</head>
<body>
<main>
<h1>{t}</h1>
{body}
</main>
<script>
"use strict";
const KEY = {json.dumps("app:" + core.slug(title))};
function load(d) {{ try {{ return JSON.parse(localStorage.getItem(KEY)) ?? d; }} catch (e) {{ return d; }} }}
function save(v) {{ try {{ localStorage.setItem(KEY, JSON.stringify(v)); }} catch (e) {{}} }}
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}})[c]);
{script}
</script>
</body>
</html>
"""


def _todo(title: str, prompt: str) -> str:
    """the to-do application: add, tick off, delete and clear tasks; kept in the browser

    Lean:
        #guard pageKey (baseTitle .todo) == "app:to-do-list"   -- py: 'const KEY = "app:to-do-list"' in _todo("To-Do List", "") and 'Clear done' in _todo("To-Do List", "")
    """
    body = """<div class="card"><form id="f" class="row"><input id="t" placeholder="Add a task" required><button>Add</button></form></div>
<div class="card"><div class="row" style="margin-bottom:8px"><span class="muted" id="count"></span>
<button class="ghost" id="clear" type="button">Clear done</button></div><ul id="list"></ul></div>"""
    script = """let items = load([]);
function draw() {
  $("#list").innerHTML = items.map((it, i) => `<li><input type="checkbox" style="width:auto" data-i="${i}" ${it.done ? "checked" : ""}>
  <span style="flex:1;${it.done ? "text-decoration:line-through;opacity:.6" : ""}">${esc(it.text)}</span>
  <button class="ghost" data-del="${i}">Delete</button></li>`).join("") || '<li class="muted">Nothing to do.</li>';
  $("#count").textContent = items.filter(i => !i.done).length + " left";
  save(items);
}
$("#f").onsubmit = e => { e.preventDefault(); items.push({ text: $("#t").value.trim(), done: false }); $("#t").value = ""; draw(); };
$("#list").onclick = e => { const d = e.target.dataset; if (d.del) { items.splice(+d.del, 1); draw(); } else if (d.i) { items[+d.i].done = e.target.checked; draw(); } };
$("#clear").onclick = () => { items = items.filter(i => !i.done); draw(); };
draw();"""
    return _page(title, body, script, "")


def _calculator(title: str, prompt: str) -> str:
    """the calculator: keypad and keyboard, brackets, exact display to 12 significant digits

    Lean:
        #guard pageKey (baseTitle .calculator) == "app:calculator"   -- py: 'const KEY = "app:calculator"' in _calculator("Calculator", "") and 'class="keys"' in _calculator("Calculator", "")
    """
    keys = ["C", "(", ")", "÷", "7", "8", "9", "×", "4", "5", "6", "−", "1", "2", "3", "+", "0", ".", "⌫", "="]
    body = ('<div class="card"><div id="out" style="font-size:34px;text-align:right;min-height:52px;overflow-x:auto">0</div>'
            '<div class="muted" id="hist" style="text-align:right;min-height:24px"></div><div class="keys">'
            + "".join(f'<button type="button" class="{"ghost" if k not in "=" else ""}">{k}</button>' for k in keys) + "</div></div>")
    css = ".keys { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-top:10px; } .keys button { font-size:22px; padding:16px 0; }"
    script = """let expr = "";
function show() { $("#out").textContent = expr || "0"; }
function calc(s) {
  const js = s.replace(/×/g, "*").replace(/÷/g, "/").replace(/−/g, "-");
  if (!/^[0-9+\\-*/(). ]+$/.test(js)) throw new Error("bad");
  const v = Function('"use strict"; return (' + js + ')')();
  if (!isFinite(v)) throw new Error("bad");
  return +v.toPrecision(12) + "";
}
document.querySelector(".keys").onclick = e => {
  const k = e.target.textContent; if (e.target.tagName !== "BUTTON") return;
  if (k === "C") expr = ""; else if (k === "⌫") expr = expr.slice(0, -1);
  else if (k === "=") { try { $("#hist").textContent = expr + " ="; expr = calc(expr); } catch (_) { $("#hist").textContent = "Can't calculate that"; } }
  else expr += k;
  show();
};
document.addEventListener("keydown", e => {
  const map = { "*": "×", "/": "÷", "-": "−", "Enter": "=", "Backspace": "⌫", "Escape": "C" };
  const k = map[e.key] || e.key;
  const b = [...document.querySelectorAll(".keys button")].find(x => x.textContent === k);
  if (b) { e.preventDefault(); b.click(); }
});"""
    return _page(title, body, script, css)


def _timer(title: str, prompt: str) -> str:
    """the timer: stopwatch with laps, or a countdown (minutes from the prompt; 25 for a pomodoro) with a beep

    Lean:
        #guard pageKey (baseTitle .timer) == "app:timer"   -- py: 'const KEY = "app:timer"' in _timer("Timer", "") and 'id="laps"' in _timer("Timer", "")
    """
    ws = core.words(prompt)
    mins = 25 if "pomodoro" in ws else core.clamp(1, 999, number_before(ws, ["min", "mins", "minute", "minutes"], 5))
    body = f"""<div class="card" style="text-align:center"><div id="clock" style="font-size:64px;font-variant-numeric:tabular-nums">00:00.0</div>
<div class="row" style="justify-content:center;margin:10px 0"><label class="muted" style="flex:none">Countdown minutes</label>
<input id="mins" type="number" min="0" value="{mins}" style="max-width:90px"></div>
<div class="row" style="justify-content:center"><button id="go" style="flex:none">Start</button><button id="lap" class="ghost" style="flex:none">Lap</button>
<button id="reset" class="ghost" style="flex:none">Reset</button><label style="flex:none"><input type="checkbox" id="down" style="width:auto"> Count down</label></div></div>
<div class="card"><ul id="laps"></ul></div>"""
    script = """let start = 0, acc = 0, timer = null, laps = [];
const fmt = ms => { ms = Math.max(0, ms); const m = Math.floor(ms / 60000), s = Math.floor(ms / 1000) % 60, t = Math.floor(ms / 100) % 10;
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0") + "." + t; };
const elapsed = () => acc + (timer ? Date.now() - start : 0);
function tick() {
  let v = elapsed();
  if ($("#down").checked) { v = +$("#mins").value * 60000 - v; if (v <= 0 && timer) { stop(); beep(); v = 0; } }
  $("#clock").textContent = fmt(v);
}
function beep() { try { const a = new AudioContext(), o = a.createOscillator(); o.connect(a.destination); o.frequency.value = 880; o.start(); o.stop(a.currentTime + 0.6); } catch (e) {} }
function stop() { acc = elapsed(); clearInterval(timer); timer = null; $("#go").textContent = "Start"; }
$("#go").onclick = () => { if (timer) return stop(); start = Date.now(); timer = setInterval(tick, 100); $("#go").textContent = "Pause"; };
$("#reset").onclick = () => { stop(); acc = 0; laps = []; $("#laps").innerHTML = ""; tick(); };
$("#lap").onclick = () => { laps.unshift(fmt(elapsed())); $("#laps").innerHTML = laps.map((l, i) => `<li>Lap ${laps.length - i}<span style="margin-left:auto">${l}</span></li>`).join(""); };
tick();"""
    return _page(title, body, script, "")


def _notes(title: str, prompt: str) -> str:
    """the notes application: create, search, edit and delete notes; saved as you type

    Lean:
        #guard pageKey (baseTitle .notes) == "app:notes"   -- py: 'const KEY = "app:notes"' in _notes("Notes", "") and 'id="nb"' in _notes("Notes", "")
    """
    body = """<div class="card"><div class="row"><input id="q" placeholder="Search notes"><button id="new" type="button">New note</button></div></div>
<div class="card" id="editor" hidden><input id="nt" placeholder="Title" style="margin-bottom:8px"><textarea id="nb" rows="8" placeholder="Write…"></textarea>
<div class="row" style="margin-top:8px"><span class="muted" id="saved"></span><button class="ghost" id="del" type="button">Delete</button><button id="done" type="button">Done</button></div></div>
<div class="card"><ul id="list"></ul></div>"""
    script = """let notes = load([]), cur = -1;
function draw() {
  const q = $("#q").value.toLowerCase();
  $("#list").innerHTML = notes.map((n, i) => ({ n, i })).filter(x => (x.n.title + " " + x.n.body).toLowerCase().includes(q))
    .map(x => `<li data-i="${x.i}" style="cursor:pointer;display:block"><b>${esc(x.n.title || "Untitled")}</b><div class="muted">${esc(x.n.body.slice(0, 90))}</div></li>`).join("")
    || '<li class="muted">No notes yet.</li>';
}
function open(i) { cur = i; $("#editor").hidden = false; $("#nt").value = notes[i].title; $("#nb").value = notes[i].body; $("#nb").focus(); }
$("#new").onclick = () => { notes.unshift({ title: "", body: "", at: Date.now() }); save(notes); open(0); draw(); };
$("#list").onclick = e => { const li = e.target.closest("li[data-i]"); if (li) open(+li.dataset.i); };
for (const id of ["#nt", "#nb"]) $(id).oninput = () => { notes[cur].title = $("#nt").value; notes[cur].body = $("#nb").value; notes[cur].at = Date.now(); save(notes); $("#saved").textContent = "Saved"; draw(); };
$("#del").onclick = () => { notes.splice(cur, 1); save(notes); $("#editor").hidden = true; draw(); };
$("#done").onclick = () => { $("#editor").hidden = true; };
$("#q").oninput = draw; draw();"""
    return _page(title, body, script, "")


def _quiz(title: str, prompt: str, questions: list[dict] | None) -> str:
    """the quiz: multiple choice, feedback, score; the QUESTIONS list is plain data at the top of the script

    Lean:
        structure QuizQ where
          q : String
          options : List String
          a : Nat
        def quizScore (answers : List Nat) (qs : List QuizQ) : Nat :=
          ((answers.zip qs).filter (fun p => p.1 == p.2.a)).length
        theorem quizScore_le (answers : List Nat) (qs : List QuizQ) : quizScore answers qs ≤ qs.length := by
          unfold quizScore
          exact Nat.le_trans (List.length_filter_le _ _) (by simp only [List.length_zip]; omega)
        #guard pageKey (baseTitle .quiz) == "app:quiz"                   -- py: 'const KEY = "app:quiz"' in _quiz("Quiz", "", None) and "QUESTIONS" in _quiz("Quiz", "", None)
    """
    qs = questions or [
        {"q": "What is 7 × 8?", "options": ["54", "56", "64", "48"], "a": 1},
        {"q": "Which planet is closest to the Sun?", "options": ["Venus", "Earth", "Mercury", "Mars"], "a": 2},
        {"q": "What is H₂O commonly called?", "options": ["Salt", "Water", "Hydrogen", "Oxygen"], "a": 1},
        {"q": "How many sides does a hexagon have?", "options": ["5", "6", "7", "8"], "a": 1},
        {"q": "Which is a prime number?", "options": ["21", "27", "29", "33"], "a": 2},
    ]
    body = """<div class="card"><div class="muted" id="prog"></div><h2 id="q" style="font-size:20px"></h2><div id="opts" style="display:grid;gap:8px"></div>
<p id="fb" style="min-height:24px"></p><div class="row"><span></span><button id="next" type="button" hidden>Next</button></div></div>
<p class="muted">Edit the QUESTIONS list in this file to make it your own.</p>"""
    script = "const QUESTIONS = " + json.dumps(qs, ensure_ascii=False, indent=1) + """;
let i = 0, score = 0, answered = false;
function draw() {
  if (i >= QUESTIONS.length) { $("#q").textContent = `You scored ${score} of ${QUESTIONS.length}.`; $("#opts").innerHTML = '<button id="again">Try again</button>';
    $("#again").onclick = () => { i = 0; score = 0; draw(); }; $("#prog").textContent = ""; $("#fb").textContent = ""; $("#next").hidden = true; return; }
  const q = QUESTIONS[i]; answered = false;
  $("#prog").textContent = `Question ${i + 1} of ${QUESTIONS.length} · score ${score}`;
  $("#q").textContent = q.q; $("#fb").textContent = ""; $("#next").hidden = true;
  $("#opts").innerHTML = q.options.map((o, k) => `<button class="ghost" data-k="${k}" style="text-align:left">${esc(o)}</button>`).join("");
}
$("#opts").onclick = e => { const k = e.target.dataset.k; if (k === undefined || answered) return; answered = true;
  const ok = +k === QUESTIONS[i].a; if (ok) score++;
  $("#fb").textContent = ok ? "Correct!" : "Not quite — the answer is " + QUESTIONS[i].options[QUESTIONS[i].a] + ".";
  e.target.style.borderColor = ok ? "green" : "crimson"; $("#next").hidden = false; };
$("#next").onclick = () => { i++; draw(); };
draw();"""
    return _page(title, body, script, "")


def _converter(title: str, prompt: str) -> str:
    """the unit converter: length, mass, volume, speed and temperature

    Lean:
        #guard pageKey (baseTitle .converter) == "app:unit-converter"   -- py: 'const KEY = "app:unit-converter"' in _converter("Unit Converter", "") and '"Temperature"' in _converter("Unit Converter", "")
    """
    units = {
        "Length": {"metre": 1, "kilometre": 1000, "centimetre": 0.01, "millimetre": 0.001, "mile": 1609.344, "yard": 0.9144, "foot": 0.3048, "inch": 0.0254},
        "Mass": {"kilogram": 1, "gram": 0.001, "pound": 0.45359237, "ounce": 0.028349523125, "tonne": 1000, "stone": 6.35029318},
        "Volume": {"litre": 1, "millilitre": 0.001, "US gallon": 3.785411784, "UK gallon": 4.54609, "US cup": 0.2365882365, "cubic metre": 1000},
        "Speed": {"metre/second": 1, "km/hour": 1 / 3.6, "mile/hour": 0.44704, "knot": 0.514444},
        "Temperature": {"Celsius": "C", "Fahrenheit": "F", "Kelvin": "K"},
    }
    body = """<div class="card"><select id="cat"></select></div>
<div class="card"><div class="row"><input id="v" type="number" value="1"><select id="from"></select></div>
<div style="text-align:center;margin:8px 0" class="muted">equals</div><div class="row"><input id="r" readonly><select id="to"></select></div></div>"""
    script = "const UNITS = " + json.dumps(units) + """;
const toK = { C: v => v + 273.15, F: v => (v - 32) * 5 / 9 + 273.15, K: v => v }, fromK = { C: v => v - 273.15, F: v => (v - 273.15) * 9 / 5 + 32, K: v => v };
$("#cat").innerHTML = Object.keys(UNITS).map(c => `<option>${c}</option>`).join("");
function fill() { const u = Object.keys(UNITS[$("#cat").value]); for (const s of ["#from", "#to"]) $(s).innerHTML = u.map(x => `<option>${x}</option>`).join(""); $("#to").selectedIndex = 1; calc(); }
function calc() {
  const t = UNITS[$("#cat").value], v = +$("#v").value, a = t[$("#from").value], b = t[$("#to").value];
  const r = typeof a === "string" ? fromK[b](toK[a](v)) : v * a / b;
  $("#r").value = isFinite(r) ? +r.toPrecision(10) : "";
}
$("#cat").onchange = fill; for (const s of ["#v", "#from", "#to"]) $(s).oninput = calc; fill();"""
    return _page(title, body, script, "")


def _game(title: str, prompt: str) -> str:
    """the number-guessing game: higher/lower hints, guess count, best score kept

    Lean:
        #guard pageKey (baseTitle .game) == "app:number-guessing-game"   -- py: 'const KEY = "app:number-guessing-game"' in _game("Number Guessing Game", "") and 'Higher' in _game("Number Guessing Game", "")
    """
    top = core.clamp(10, 1000000, number_after(core.words(prompt), ["to"], 100))
    body = f"""<div class="card"><p>I'm thinking of a number from 1 to <b id="max">{top}</b>.</p>
<form id="f" class="row"><input id="g" type="number" min="1" max="{top}" placeholder="Your guess" required><button>Guess</button></form>
<p id="msg" style="font-size:20px;min-height:30px"></p><p class="muted" id="info"></p><button class="ghost" id="again" type="button">New game</button></div>"""
    script = f"""const MAX = {top};
let secret, tries, best = load(null);
function reset() {{ secret = 1 + Math.floor(Math.random() * MAX); tries = 0; $("#msg").textContent = ""; info(); }}
function info() {{ $("#info").textContent = `Guesses: ${{tries}}` + (best ? ` · best: ${{best}}` : ""); }}
$("#f").onsubmit = e => {{ e.preventDefault(); const g = +$("#g").value; tries++;
  if (g === secret) {{ $("#msg").textContent = `Yes! ${{secret}} in ${{tries}} guesses.`; if (!best || tries < best) {{ best = tries; save(best); }} }}
  else $("#msg").textContent = g < secret ? "Higher ↑" : "Lower ↓";
  $("#g").value = ""; info(); }};
$("#again").onclick = reset; reset();"""
    return _page(title, body, script, "")


def _drawing(title: str, prompt: str) -> str:
    """the sketch pad: colour, brush size, undo, clear, download as PNG

    Lean:
        #guard pageKey (baseTitle .drawing) == "app:sketch-pad"   -- py: 'const KEY = "app:sketch-pad"' in _drawing("Sketch Pad", "") and 'id="cv"' in _drawing("Sketch Pad", "")
    """
    body = """<div class="card"><div class="row" style="flex-wrap:wrap"><input type="color" id="c" value="#2f5fb3" style="max-width:60px;padding:2px">
<input type="range" id="w" min="1" max="40" value="6" style="max-width:160px"><button class="ghost" id="undo" type="button">Undo</button>
<button class="ghost" id="clr" type="button">Clear</button><button id="dl" type="button">Download PNG</button></div></div>
<canvas id="cv" style="width:100%;height:60vh;background:#fff;border:1px solid var(--line);border-radius:12px;touch-action:none"></canvas>"""
    script = """const cv = $("#cv"), cx = cv.getContext("2d"); let strokes = [], cur = null;
function size() { const r = cv.getBoundingClientRect(); cv.width = r.width * devicePixelRatio; cv.height = r.height * devicePixelRatio; redraw(); }
function redraw() { cx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0); cx.clearRect(0, 0, cv.width, cv.height); cx.lineCap = cx.lineJoin = "round";
  for (const s of strokes) { cx.strokeStyle = s.c; cx.lineWidth = s.w; cx.beginPath(); s.p.forEach(([x, y], i) => i ? cx.lineTo(x, y) : cx.moveTo(x, y)); cx.stroke(); } }
const pt = e => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
cv.onpointerdown = e => { cv.setPointerCapture(e.pointerId); cur = { c: $("#c").value, w: +$("#w").value, p: [pt(e)] }; strokes.push(cur); };
cv.onpointermove = e => { if (cur) { cur.p.push(pt(e)); redraw(); } };
cv.onpointerup = () => { cur = null; };
$("#undo").onclick = () => { strokes.pop(); redraw(); }; $("#clr").onclick = () => { strokes = []; redraw(); };
$("#dl").onclick = () => { const a = document.createElement("a"); a.download = "drawing.png"; a.href = cv.toDataURL(); a.click(); };
addEventListener("resize", size); size();"""
    return _page(title, body, script, "")


def _landing(title: str, prompt: str) -> str:
    """the landing page: hero with the prompt's description, three sections and a contact form

    Lean:
        #guard pageKey (baseTitle .landing) == "app:welcome"   -- py: 'const KEY = "app:welcome"' in _landing("Welcome", "") and 'id="contact"' in _landing("Welcome", "")
    """
    t = html.escape(title)
    about = html.escape(strip_request(prompt))
    body = f"""<section class="card hero"><h2>{t}</h2><p class="muted">{about[:220]}</p><a class="cta" href="#contact">Get in touch</a></section>
<section class="grid">
<div class="card"><h3>What we do</h3><p>Replace this with what {t} offers and who it is for.</p></div>
<div class="card"><h3>Why it matters</h3><p>Say what changes for the people who use it.</p></div>
<div class="card"><h3>How it works</h3><p>Three short steps from first visit to result.</p></div></section>
<section class="card" id="contact"><h3>Contact</h3><form id="f" style="display:grid;gap:8px"><input placeholder="Your name" required>
<input type="email" placeholder="Email" required><textarea rows="4" placeholder="Message"></textarea><button>Send</button></form><p id="sent" class="muted"></p></section>"""
    css = (".hero { text-align:center; padding:48px 16px; } .hero h2 { font-size:34px; margin:0 0 8px; } "
           ".cta { display:inline-block; margin-top:14px; background:var(--accent); color:var(--accent-ink); padding:10px 20px; border-radius:999px; text-decoration:none; font-weight:600; } "
           ".grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; } h3 { margin:0 0 6px; }")
    script = """$("#f").onsubmit = e => { e.preventDefault(); $("#sent").textContent = "Thanks — this demo form doesn't send anything yet; connect it to your email service."; e.target.reset(); };"""
    return _page(title, body, script, css)


def _records(title: str, prompt: str) -> str:
    """the record keeper: the prompt's fields as a form, a sortable searchable table, CSV export

    Lean:
        #guard pageKey (baseTitle .records) == "app:records"   -- py: 'const KEY = "app:records"' in _records("Records", "") and 'Export CSV' in _records("Records", "")
    """
    fields = fields_from(prompt)
    inputs = "".join(f'<input name="{html.escape(f)}" placeholder="{html.escape(f)}">' for f in fields)
    body = f"""<div class="card"><form id="f" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px">{inputs}<button>Add</button></form></div>
<div class="card"><div class="row" style="margin-bottom:8px"><input id="q" placeholder="Search"><button class="ghost" id="csv" type="button">Export CSV</button></div>
<div style="overflow-x:auto"><table id="t" style="width:100%;border-collapse:collapse"></table></div></div>"""
    css = "th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); } th { cursor:pointer; }"
    script = "const FIELDS = " + json.dumps(fields) + """;
let rows = load([]), sortBy = null, asc = true;
function draw() {
  const q = $("#q").value.toLowerCase();
  let r = rows.map((x, i) => ({ x, i })).filter(o => FIELDS.some(f => String(o.x[f] || "").toLowerCase().includes(q)));
  if (sortBy) r.sort((a, b) => String(a.x[sortBy]).localeCompare(String(b.x[sortBy]), undefined, { numeric: true }) * (asc ? 1 : -1));
  $("#t").innerHTML = "<tr>" + FIELDS.map(f => `<th data-f="${esc(f)}">${esc(f)}${sortBy === f ? (asc ? " ▲" : " ▼") : ""}</th>`).join("") + "<th></th></tr>" +
    (r.map(o => "<tr>" + FIELDS.map(f => `<td>${esc(o.x[f] || "")}</td>`).join("") + `<td><button class="ghost" data-del="${o.i}">Delete</button></td></tr>`).join("")
    || `<tr><td colspan="${FIELDS.length + 1}" class="muted">No records yet.</td></tr>`);
  save(rows);
}
$("#f").onsubmit = e => { e.preventDefault(); const fd = new FormData(e.target); rows.push(Object.fromEntries(FIELDS.map(f => [f, (fd.get(f) || "").trim()]))); e.target.reset(); draw(); };
$("#t").onclick = e => { const d = e.target.dataset; if (d.del) { rows.splice(+d.del, 1); draw(); } else if (d.f) { asc = sortBy === d.f ? !asc : true; sortBy = d.f; draw(); } };
$("#q").oninput = draw;
$("#csv").onclick = () => { const q = v => '"' + String(v ?? "").replace(/"/g, '""') + '"';
  const csv = [FIELDS.map(q).join(","), ...rows.map(r => FIELDS.map(f => q(r[f])).join(","))].join("\\n");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "records.csv"; a.click(); };
draw();"""
    return _page(title, body, script, css)


def _python(title: str, prompt: str) -> str:
    """a Python command-line program (standard library only): summarises text files or standard input

    Lean:
        def pyName (title : String) : String := match (slug title).replace "-" "_" with
          | "" => "tool"
          | n => n
        #guard pyName "Command-Line Tool" == "command_line_tool"         -- py: "python command_line_tool.py" in _python("Command-Line Tool", "x")
    """
    name = core.slug(title).replace("-", "_") or "tool"
    doc = prompt.strip().replace('"""', "'''")
    return f'''#!/usr/bin/env python3
"""{title}

Generated by VeriWave from: {doc}

Usage:
    python {name}.py FILE [FILE ...]          summarise text files (lines, words, characters, top words)
    python {name}.py --top 20 FILE            show more top words
    echo "some text" | python {name}.py -     read standard input
"""
from __future__ import annotations

import argparse
import collections
import re
import sys


def summarise(text: str, top: int) -> dict:
    words = re.findall(r"[A-Za-z']+", text.lower())
    return {{"lines": text.count("\\n") + (1 if text and not text.endswith("\\n") else 0), "words": len(words),
            "characters": len(text), "top": collections.Counter(words).most_common(top)}}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="{title}")
    ap.add_argument("files", nargs="+", help="text files, or - for standard input")
    ap.add_argument("--top", type=int, default=10, help="how many of the most common words to show")
    args = ap.parse_args(argv)
    for path in args.files:
        try:
            text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8", errors="replace").read()
        except OSError as e:
            print(f"{{path}}: {{e.strerror}}", file=sys.stderr)
            return 1
        s = summarise(text, args.top)
        print(f"{{path}}: {{s['lines']}} lines, {{s['words']}} words, {{s['characters']}} characters")
        for w, n in s["top"]:
            print(f"  {{n:6d}}  {{w}}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


def build_page(kind: str, title: str, prompt: str) -> str:
    """the page for a kind of web application

    Lean:
        def hasPage : Kind → Bool
          | .python => false
          | _ => true
        theorem only_python_has_no_page (k : Kind) (h : k ≠ .python) : hasPage k = true := by
          cases k <;> simp_all [hasPage]
        #guard hasPage .records && !hasPage .python                       -- py: build_page("records", "R", "").startswith("<!doctype html>")
    """
    if kind == "todo":
        return _todo(title, prompt)
    if kind == "calculator":
        return _calculator(title, prompt)
    if kind == "timer":
        return _timer(title, prompt)
    if kind == "notes":
        return _notes(title, prompt)
    if kind == "quiz":
        return _quiz(title, prompt, None)
    if kind == "converter":
        return _converter(title, prompt)
    if kind == "game":
        return _game(title, prompt)
    if kind == "drawing":
        return _drawing(title, prompt)
    if kind == "landing":
        return _landing(title, prompt)
    return _records(title, prompt)


def generate_local(prompt: str, kind: str) -> dict:
    """a complete application from a prompt (kind '' = detect it): its files, entry file and whether it previews

    Lean:
        def entryFor (k : Kind) (title : String) : String := if k == .python then pyName title ++ ".py" else "index.html"
        theorem entry_previews (k : Kind) (t : String) (h : k ≠ .python) : entryFor k t = "index.html" := by
          cases k <;> first | exact (h rfl).elim | rfl
        #guard entryFor .todo "To-Do List" == "index.html"                -- py: generate_local("Build me a to-do app", "")["entry"] == "index.html"
        #guard entryFor .python "Command-Line Tool" == "command_line_tool.py"   -- py: generate_local("write a python script", "")["entry"] == "command_line_tool.py"
    """
    if kind not in KINDS and kind != "records":
        kind = detect_kind(prompt)
    title = title_from(prompt, kind)
    files: dict[str, str] = {}
    if kind == "python":
        entry = (core.slug(title).replace("-", "_") or "tool") + ".py"
        files[entry] = _python(title, prompt)
        how = "Run `python " + entry + " --help`.\n"
    else:
        entry = "index.html"
        files[entry] = build_page(kind, title, prompt)
        how = "Open `index.html` in any web browser. Data is kept in the browser's local storage.\n"
    files["README.md"] = "# " + title + "\n\nGenerated by VeriWave (local engine) from the prompt:\n\n> " + prompt.strip() + "\n\n" + how
    return {"kind": kind, "title": title, "files": files, "entry": entry, "engine": "local", "preview": entry.endswith(".html")}


def safe_path(path: str) -> str:
    """a generated file's path made safe: forward slashes, relative, no '..' part; '' when it can't be

    Lean:
        def safePath (p : String) : String :=
          let q := (p.replace "\\" "/").dropWhile (· == '/')
          if q.isEmpty || (q.splitOn "/").contains ".." then "" else q
        #guard safePath "/src/app.js" == "src/app.js"                     -- py: safe_path("/src/app.js") == "src/app.js"
        #guard safePath "../etc/passwd" == ""                             -- py: safe_path("../etc/passwd") == ""
    """
    q = path.replace("\\", "/").lstrip("/")
    if not q or ".." in q.split("/"):
        return ""
    return q


CODE_SYSTEM = """You are VeriWave's coding engine. Build exactly the application the user describes.
Return ONLY a JSON object, no prose, in this format:
{"title": "<short name>", "entry": "<main file path>", "files": {"<path>": "<full file contents>", ...}, "notes": "<one or two sentences on how to run it>"}
Rules: complete, working code with no placeholders or TODOs; for anything with a user interface, prefer ONE self-contained
index.html (inline CSS and JavaScript, no external requests) so it previews in a sandboxed frame; include a README.md;
keep paths relative with no leading slash or '..'; never include secrets or API keys."""


def pick_entry(asked: str, paths: list[str]) -> str:
    """the entry file: the one asked for if it exists, else index.html, else the first file

    Lean:
        def pickEntry (asked : String) (paths : List String) : String :=
          if paths.contains asked then asked else if paths.contains "index.html" then "index.html" else paths.headD ""
        theorem pickEntry_asked (a : String) (ps : List String) (h : ps.contains a = true) : pickEntry a ps = a := by
          unfold pickEntry; rw [if_pos h]
        #guard pickEntry "" ["a.py"] == "a.py"                            -- py: pick_entry("", ["a.py"]) == "a.py"
    """
    if asked in paths:
        return asked
    if "index.html" in paths:
        return "index.html"
    return paths[0] if paths else ""


def generate_claude(prompt: str, claude: Claude, history: list[dict]) -> dict:
    """an application written by Claude under the file contract; every path made safe, an entry file guaranteed

    Lean:
        #guard pickEntry "main.py" ["index.html", "README.md"] == "index.html"   -- py: pick_entry("main.py", ["index.html", "README.md"]) == "index.html"
    """
    msgs = list(history) + [{"role": "user", "content": prompt}]
    reply = claude.complete(CODE_SYSTEM, msgs, max_tokens=32000, effort="high")
    data = parse_json_reply(reply)
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise BackendError("Claude's reply had no files.")
    clean: dict[str, str] = {}
    for path, content in files.items():
        p = safe_path(str(path))
        if p and isinstance(content, str):
            clean[p] = content
    if not clean:
        raise BackendError("Claude's reply had no usable files.")
    entry = pick_entry(str(data.get("entry") or ""), list(clean))
    return {"kind": "custom", "title": str(data.get("title") or "Application")[:80], "files": clean, "entry": entry,
            "engine": "claude", "notes": str(data.get("notes") or ""), "preview": entry.endswith(".html")}
