"""The Control Panel's assistant: answers questions about the three applications and works the panel from plain
sentences ("stop all harvesting", "focus on volcanoes in history", "exclude football", "find Marie Curie").

It is rule-based — a fixed set of requests recognised by their words, no language model and no network — so it
never invents an answer: it reports what the panel measures, says exactly what it changed (every change also goes
to the audit trail), asks before stopping anything, and asks for the admin passphrase when a global rule needs it.
"""
import re

APP_WORDS = [("language", r"language(?: builder)?|lang\b|words?|vocabulary|speech"),
             ("stem", r"stem|math(?:s|ematics)?|science|engineering"),
             ("facts", r"history(?: (?:and|&) news)?|news|facts? app")]
NAMES = {"language": "Language Builder", "stem": "Math, Science & Engineering", "facts": "History & News"}
SECTIONS = {"app": "apps", "application": "apps", "harvest": "harvest", "target": "target", "filter": "filter", "assistant": "assistant",
            "panel": "panel"}

RULES = [  # (intent, pattern) — the first match wins; order matters
    ("yes", r"^(?:yes|y|ok(?:ay)?|sure|confirm|go ahead|do it)\b[.!]*$"),
    ("no", r"^(?:no|n|cancel|don'?t|stop that|never mind)\b[.!]*$"),
    ("help", r"^(?:help|\?|what can you do|commands)\b"),
    # questions about QueryBook itself go to the Self-Knowledge Layer (qbselfknow): labelled, sourced answers only
    ("self", r"\b(?:who are you|what are you|what is querybook|how do you (?:work|think|reason|answer)|your (?:design|architecture)|"
             r"(?:section|sec\.?)\s*\d|§\s*\d|neuro\w*morphic|neomorphic|world[- ]?(?:view|model)|predictive|hypothes\w*|simulat\w*|recursive|\brsi\b|"
             r"self[- ]?(?:improv\w*|knowledge)|determinis\w*|fact units?|atomic|what can'?t you|your limit\w*|deduc\w*|abduc\w*|feedback loops?)"),
    ("alerts_clear", r"\b(?:clear|dismiss)\b.*\balerts?\b"),
    ("alerts", r"\b(?:alerts?|problems?|issues?|anything wrong|warnings?)\b"),
    ("diagnose", r"\b(?:diagnos\w*|health ?check|run (?:the )?checks?|self[- ]?check)\b"),
    ("target_clear", r"\b(?:clear|remove|reset|drop)\b.*\btarget\w*|\bstop targeting\b|\bno target\b"),
    ("filter_clear", r"\b(?:clear|remove|reset|drop)\b.*\bfilters?\b|\bno filters?\b"),
    ("harvest_now", r"\bharvest\b.*\bnow\b|\brun (?:a )?harvest\b|\bharvest (?:it|them) now\b"),
    ("harvest_stop", r"\b(?:stop|pause|halt|suspend)\b.*\bharvest\w*"),
    ("harvest_start", r"\b(?:start|resume|begin|restart|turn on)\b.*\bharvest\w*|\bmass harvest\w*"),
    ("filter_years", r"\b(?:1[0-9]{3}|20[0-9]{2})\b\s*(?:-|–|to|and|until)\s*\b(?:1[0-9]{3}|20[0-9]{2})\b"),
    ("filter_require", r"\b(?:only (?:keep|allow|accept|facts?)|keep only|require|must (?:mention|contain))\b"),
    ("filter_exclude", r"\b(?:exclude|leave out|filter out|block|ignore|skip|no more)\b"),
    ("target_set", r"\b(?:focus|target|concentrate|prioriti[sz]e)\b"),
    ("search", r"^(?:find|search(?: for)?|look ?up|what do (?:we|you) know about|show (?:me )?facts? (?:about|on))\b"),
    ("app_stop", r"\b(?:stop|close|shut ?down|quit|exit)\b"),
    ("app_start", r"\b(?:start|launch|open|run)\b"),
    ("status", r"\b(?:status|how (?:is|are)|what'?s running|overview|summary|facts? (?:are there|do we have)|how many)\b"),
]
SELF_TEST = [("stop all harvesting", "harvest_stop"), ("start harvesting for stem", "harvest_start"), ("harvest now", "harvest_now"),
             ("focus on volcanoes in history", "target_set"), ("exclude football", "filter_exclude"), ("only keep facts about Rome", "filter_require"),
             ("years 1800 to 1950", "filter_years"), ("clear the filter", "filter_clear"), ("find Marie Curie", "search"),
             ("start the language builder", "app_start"), ("stop stem", "app_stop"), ("any alerts?", "alerts"), ("how is everything?", "status"),
             ("run diagnostics", "diagnose"), ("yes", "yes"),
             ("are you neuromorphic?", "self"), ("what is section 21?", "self"), ("can you improve yourself recursively?", "self")]


def apps_in(text):
    t = text.lower()
    found = [a for a, pat in APP_WORDS if re.search(r"\b(?:%s)" % pat, t)]
    if re.search(r"\b(?:all|every|everything|the three|all three)\b", t):
        return []
    return found


def _strip_apps(text):
    t = re.sub(r"\b(?:in|for|on|from|within)\s+(?:the\s+)?(?:%s)\b(?:\s+app(?:lication)?)?" % "|".join(p for _, p in APP_WORDS), "", text, flags=re.I)
    return t


def _items(text):
    t = re.sub(r"[\"'“”‘’.!?]", "", text)
    parts = re.split(r",|;|\band\b|\bor\b|&", t)
    return [" ".join(p.split()) for p in parts if p.strip()]


def parse(text):
    t = " ".join(text.strip().split())
    low = t.lower()
    for intent, pat in RULES:
        if re.search(pat, low):
            break
    else:
        intent = "unknown"
    args = {"apps": apps_in(low), "text": t}
    if intent == "target_set":
        m = re.search(r"\b(?:focus|target|concentrate|prioriti[sz]e)\w*\s+(?:only\s+)?(?:on|upon)?\s*(.*)$", t, re.I)
        rest = _strip_apps(m.group(1) if m else "")
        rest = re.sub(r"^(?:only\s+)?(?:facts?\s+)?(?:about|on)\s+", "", rest.strip(), flags=re.I)
        args["topics"] = [x for x in _items(rest) if x.lower() not in ("only", "it", "them")]
        args["only"] = bool(re.search(r"\bonly\b|\bnothing else\b", low))
    elif intent in ("filter_exclude", "filter_require"):
        m = re.search(r"\b(?:exclude|leave out|filter out|block|ignore|skip|no more|only keep|keep only|only allow|only accept|only facts?|require|"
                      r"must mention|must contain)\b\s*(.*)$", t, re.I)
        rest = re.sub(r"^(?:facts?\s+)?(?:about|on|with|mentioning|containing|that mention)\s+", "", (m.group(1) if m else "").strip(), flags=re.I)
        args["words"] = _items(_strip_apps(rest))
    elif intent == "filter_years":
        ys = [int(y) for y in re.findall(r"\b(1[0-9]{3}|20[0-9]{2})\b", t)][:2]
        args["years"] = sorted(ys)
    elif intent == "search":
        m = re.search(r"^(?:find|search(?: for)?|look ?up|what do (?:we|you) know about|show (?:me )?facts? (?:about|on))\s*(.*)$", t, re.I)
        args["q"] = re.sub(r"[?.!]+$", "", (m.group(1) if m else "")).strip()
    elif intent == "diagnose":
        args["section"] = next((v for k, v in SECTIONS.items() if k in low), "all")
    return {"intent": intent, "args": args}


HELP = ("I can:\n"
        "• tell you how everything is — \u201cstatus\u201d, \u201cany alerts?\u201d, \u201chow many facts?\u201d\n"
        "• start or stop an application — \u201cstart the language builder\u201d, \u201cstop stem\u201d\n"
        "• start or stop harvesting — \u201cstop all harvesting\u201d, \u201cstart harvesting for history\u201d, \u201charvest now\u201d\n"
        "• target — \u201cfocus on volcanoes and earthquakes in history\u201d, \u201cfocus only on Rome\u201d, \u201cclear the target\u201d\n"
        "• filter — \u201cexclude football\u201d, \u201conly keep facts about science\u201d, \u201cyears 1800 to 1950\u201d, \u201cclear the filter\u201d\n"
        "• search the shared facts — \u201cfind Marie Curie\u201d\n"
        "• diagnose — \u201crun diagnostics\u201d, \u201cdiagnose the filter\u201d; \u201cclear alerts\u201d\n"
        "• talk about QueryBook itself, with sources — \u201care you neuromorphic?\u201d, \u201csection 21\u201d, \u201cwhat can\u2019t you do?\u201d, \u201chow do you work?\u201d\n"
        "I work by fixed rules (no AI model), so I only do what I recognise, and I say exactly what I changed.")
CONFIRM = {"harvest_stop", "app_stop", "target_clear", "filter_clear", "alerts_clear"}
NEEDS_ADMIN = {"target_set", "target_clear", "filter_exclude", "filter_require", "filter_years", "filter_clear"}


def respond(panel, text, passphrase="", pending=None):
    p = parse(text)
    if p["intent"] in ("yes", "no"):
        if not pending:
            return {"reply": "There is nothing waiting for a yes or no. " + ("Say \u201chelp\u201d to see what I can do." if p["intent"] == "yes" else "")}
        if p["intent"] == "no":
            return {"reply": "Cancelled — nothing was changed."}
        p = pending
        confirmed = True
    else:
        confirmed = False
    intent, a = p["intent"], p["args"]
    if intent in NEEDS_ADMIN and panel.commons.approvals.admin_set() and not passphrase:
        return {"reply": "Global rules change what all three applications harvest, so this needs the admin passphrase. Type it in the "
                         "passphrase box under the chat and send again.", "needs": "passphrase", "pending": p}
    if intent in CONFIRM and not confirmed:
        what = {"harvest_stop": "stop " + ("all harvesting" if not a["apps"] else "harvesting for " + ", ".join(NAMES[x] for x in a["apps"])),
                "app_stop": "stop " + (", ".join(NAMES[x] for x in a["apps"]) or "every application"),
                "target_clear": "clear the target (harvest everything evenly again)", "filter_clear": "clear the filter (let every fact in again)",
                "alerts_clear": "dismiss all open alerts"}[intent]
        return {"reply": "Shall I %s? Say yes to go ahead, or no." % what, "needs": "confirm", "pending": p}
    try:
        return _do(panel, intent, a, passphrase)
    except Exception as e:
        return {"reply": "That did not work: %s" % e}


def _do(panel, intent, a, pw):
    act = lambda what, detail, fn: panel.act("assistant", what, detail, fn)
    if intent == "help":
        return {"reply": HELP}
    if intent == "self":
        import qbselfknow
        r = qbselfknow.answer(a.get("text", ""), "user")
        src = (" Sources: " + r["source_text"] + ".") if r["source_text"] else ""
        secs = (" Design: " + ", ".join(r["sections"]) + ".") if r["sections"] else ""
        return {"reply": r["answer"] + src + secs, "label": r["label"]}
    if intent == "status":
        apps = panel.apps()
        lines = []
        for x in apps:
            if x["running"]:
                lines.append("• %s: running (version %s), harvesting %s, %d facts" % (x["name"], x["version"] or "?", "on" if x["harvest_on"] else "off", x["facts"]))
            else:
                lines.append("• %s: not running%s, %d facts" % (x["name"], "" if x["installed"] else " (not installed here)", x["facts"]))
        ctl_ = panel.control()
        r = panel.rules()
        al = panel.alerts()
        ov = panel.overview()
        lines.append("Harvesting is %s. %d shared facts in all (%d confirmed by more than one application)." % (ctl_["master"], ov["facts"], ov["shared"]))
        lines.append("Target: %s. Filter: %s." % (r["target_text"], r["filter_text"]))
        lines.append("%d open alert(s)%s" % (len(al), (": " + "; ".join(x["text"] for x in al[:3])) if al else "."))
        return {"reply": "\n".join(lines)}
    if intent == "alerts":
        al = panel.alerts()
        if not al:
            return {"reply": "No open alerts. The panel checks everything every 20 seconds (last check %s)." % (panel.last_check or "not yet")}
        return {"reply": "\n".join("• [%s] %s" % (x["level"], x["text"]) for x in al)}
    if intent == "alerts_clear":
        panel.api.routes[("POST", "/api/panel/alerts_clear")]({})
        return {"reply": "Dismissed every open alert (they come back if the problem is still there at the next check).", "did": "alerts cleared"}
    if intent == "diagnose":
        d = panel.diagnose(a.get("section") or "all")
        bad = [x for x in d["checks"] if x["status"] != "ok"]
        panel.audit("assistant", "diagnose %s" % d["section"], "", d["overall"], d["overall"] != "fail")
        return {"reply": "Diagnostics (%s): %s — %d checks.%s" % (d["section"], d["overall"].upper(), len(d["checks"]),
                                                                 ("\n" + "\n".join("• %s: %s — %s" % (x["status"], x["name"], x["detail"]) for x in bad)) if bad else " All good."),
                "did": "diagnostics"}
    if intent in ("app_start", "app_stop"):
        if not a["apps"]:
            if intent == "app_start":
                return {"reply": "Which application? Say \u201cstart language\u201d, \u201cstart stem\u201d or \u201cstart history\u201d."}
            a["apps"] = list(NAMES)
        out = []
        for x in a["apps"]:
            fn = panel.start_app if intent == "app_start" else panel.stop_app
            out.append(act("%s %s" % ("start" if intent == "app_start" else "stop", x), "", lambda x=x: fn(x))["summary"])
        return {"reply": "Done: " + "; ".join(out) + ".", "did": intent}
    if intent == "harvest_now":
        apps = a["apps"] or [x["app"] for x in panel.apps() if x["running"]]
        if not apps:
            return {"reply": "No application is running, so nothing can harvest. Say \u201cstart history\u201d (for example) first."}
        out = []
        for x in apps:
            try:
                out.append(act("harvest %s" % x, "", lambda x=x: panel.harvest_now(x))["summary"])
            except Exception as e:
                out.append("%s: %s" % (NAMES[x], e))
        return {"reply": "; ".join(out) + ".", "did": "harvest now"}
    if intent in ("harvest_start", "harvest_stop"):
        action = "start" if intent == "harvest_start" else "stop"
        r = act("harvest %s" % action, ", ".join(a["apps"]) or "all", lambda: panel.harvest(action, a["apps"], [], action == "start"))
        return {"reply": "Done: %s." % r["summary"], "did": intent}
    if intent == "target_set":
        if not a.get("topics") and not a["apps"]:
            return {"reply": "Focus on what? For example \u201cfocus on volcanoes and earthquakes in history\u201d."}
        cur = panel.rules()["target"]
        new = dict(cur, topics=a.get("topics") or cur["topics"], apps=a["apps"] or ([] if a.get("topics") else cur["apps"]), only=a.get("only", False))
        r = act("set target", str(new), lambda: panel.set_rules("target", new, pw))
        return {"reply": "Target set — %s. Harvest tasks that match go first%s." % (r["summary"].split(": ", 1)[1],
                                                                                   " and nothing else is harvested" if new["only"] else ""), "did": "target"}
    if intent == "target_clear":
        act("clear target", "", lambda: panel.set_rules("target", {}, pw))
        return {"reply": "Target cleared — all sources are harvested evenly again.", "did": "target cleared"}
    if intent in ("filter_exclude", "filter_require"):
        if not a.get("words"):
            return {"reply": "Which words? For example \u201cexclude football\u201d or \u201conly keep facts about Rome\u201d."}
        cur = panel.rules()["filter"]
        key = "exclude_words" if intent == "filter_exclude" else "require_words"
        new = dict(cur, **{key: cur[key] + [w for w in a["words"] if w.lower() not in cur[key]]})
        r = act("set filter", str(new), lambda: panel.set_rules("filter", new, pw))
        pv = panel.api.routes[("POST", "/api/panel/preview")]({"rules": new})
        return {"reply": "Filter set — %s. On the latest %d shared facts it would keep %d." % (r["summary"].split(": ", 1)[1], pv["checked"], pv["kept"]),
                "did": "filter"}
    if intent == "filter_years":
        if len(a.get("years") or []) < 2:
            return {"reply": "Give two years, e.g. \u201cyears 1800 to 1950\u201d."}
        new = dict(panel.rules()["filter"], years=a["years"])
        r = act("set filter", str(new), lambda: panel.set_rules("filter", new, pw))
        return {"reply": "Filter set — %s. Facts with no year in them still pass." % r["summary"].split(": ", 1)[1], "did": "filter"}
    if intent == "filter_clear":
        act("clear filter", "", lambda: panel.set_rules("filter", {}, pw))
        return {"reply": "Filter cleared — every fact that passes the licence policy is let in again.", "did": "filter cleared"}
    if intent == "search":
        if not a.get("q"):
            return {"reply": "Find what? For example \u201cfind Marie Curie\u201d."}
        facts = panel.commons.search(a["q"], None, None, 8)
        if not facts:
            return {"reply": "No shared fact mentions \u201c%s\u201d yet. You could target it: \u201cfocus on %s\u201d." % (a["q"], a["q"]), "facts": []}
        return {"reply": "%d shared fact(s) about \u201c%s\u201d:\n" % (len(facts), a["q"]) + "\n".join(
            "• %s — %s — %s (%s, %s)" % (f["subject"], f["predicate"], str(f["object"])[:80], f["domain"], f["status"]) for f in facts),
            "facts": [{"id": f["id"], "subject": f["subject"], "predicate": f["predicate"], "object": f["object"]} for f in facts]}
    return {"reply": "I did not recognise that. " + HELP}
