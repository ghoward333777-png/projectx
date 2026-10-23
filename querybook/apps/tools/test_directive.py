#!/usr/bin/env python3
"""The Campaign Manager (qbdirective): reading a directive, designing the campaign, the assistant, compiling the wave plans
and launching a wave — with the directive bundled beside the Control Panel and a throw-away shared folder. No network."""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_core"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import qbcommons as cm  # noqa: E402
import qbdirective as D  # noqa: E402
import qbonline as ol  # noqa: E402

BUNDLED = os.path.join(ROOT, "control", "directives", "QueryBook-Synthetic-Video-Directive.docx")
SMALL = """# Small test directive

Out of scope: weapons employment, targeting, and any real person's likeness without consent. Defense work is logistics only.

### Robotic manipulation (ROB)

Shared profile. Real teleoperation data is costly.

| # | Task | Why it pays | Who pays | Ease | Tier | Rev | WM / AG |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROB-01 | Bin picking of mixed items | Largest use case | Amazon Robotics, FANUC | 4 | T0 | A | H / H |
| ROB-02 | Weapons loading drill | test of the scope guard | nobody | 3 | T0 | B | M / M |
| ROB-03 | Deformable objects | home tasks | 1X | 2 | SM | A | H / H |

| Category | Required angles | Required POVs | Required overlays | Required dialog | Required captions |
| --- | --- | --- | --- | --- | --- |
| Robotic manipulation | Third-person 45°, top-down | Wrist camera; robot head camera | Grasp points | None | Action verb |

| Task | Modeling required | Online by |
| --- | --- | --- |
| ROB-03 Deformable objects | Cloth simulation | Day 60–90 |
"""


class Checks:
    def __init__(self):
        self.n = self.ok = 0

    def check(self, name, cond, detail=""):
        self.n += 1
        self.ok += bool(cond)
        print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else " — %s" % (detail,)))


def main():
    c = Checks()
    # --- reading the bundled directive
    with open(BUNDLED, "rb") as f:
        data = f.read()
    b = D.read(os.path.basename(BUNDLED), data)
    tiers = {t: sum(1 for x in b["tasks"] if x["tier"] == t) for t in D.TIERS}
    c.check("reads all 122 tasks of the bundled directive (72 T0, 42 T30, 8 SM)", len(b["tasks"]) == 122 and tiers == {"T0": 72, "T30": 42, "SM": 8}, tiers)
    c.check("reads the 19 categories and their capture specifications", len(b["categories"]) == 19 and len(b["capture_spec"]) == 19)
    c.check("every task finds its category's cameras", all(D.capture_for(b, t)["category"] in {x["category"] for x in b["capture_spec"]} for t in b["tasks"]))
    c.check("reads the specialized-modeling schedule, metadata record and timeline lists",
            len(b["specialized_modeling"]) == 8 and b["metadata_schema"]["task_id"] == "ROB-09" and b["fastest_revenue"][0] == "DH-01"
            and "DRV-05" in b["largest_revenue"])
    c.check("reads the anchor rule, throughput and scope exclusions", b["anchor_rule"]["max_pct"] == 5 and b["throughput"]["T0"] == 1000
            and "targeting" in b["scope_exclusions"])
    try:
        D.read("x.docx", b"not a zip")
        bad = False
    except ValueError:
        bad = True
    c.check("a broken .docx is refused with a plain message", bad)

    with tempfile.TemporaryDirectory() as tmp:
        st = D.Store(tmp)
        camp = st.create("directive.docx", data)
        c.check("the same document again gives the same campaign", st.create("again.docx", data)["id"] == camp["id"] and len(st.list()) == 1)
        d = D.design(camp, today="2026-10-23")
        w = {x["tier"]: x for x in d["waves"]}
        c.check("waves follow the tiers and never start before the directive allows", w["T0"]["start_day"] == 0 and w["T30"]["start_day"] >= 30
                and w["SM"]["start_day"] >= 60 and w["T30"]["start_day"] >= w["T0"]["end_day"], {k: (v["start_day"], v["end_day"]) for k, v in w.items()})
        c.check("the schedule uses the tool's real daily budget (Veo: 10 a day)", d["requests_per_day"] == 10 and w["T0"]["requests"] == 72 * 2 * 2
                and w["T0"]["end_day"] == 29)
        c.check("fastest-revenue tasks are scheduled first", [j["id"] for j in d["tasks"]][:3] == ["DH-01", "DH-02", "ENT-01"])
        c.check("regulated categories carry the larger anchor set", all(j["anchor_pct"] == (5 if j["category"] in D.REGULATED else 2) for j in d["tasks"]))
        c.check("the design is deterministic", json.dumps(D.design(camp, today="2026-10-23"), sort_keys=True) == json.dumps(d, sort_keys=True))
        # --- the assistant
        ck = D.checklist(camp)
        c.check("a new campaign is not ready: scope, reviewers, consent, anchor source", not ck["ready_to_compile"] and ck["next"]["key"] == "scope")
        for msg in ["I acknowledge the scope", "use the default reviewers", "consent is on file", "anchor source is partner hospital simulation recordings"]:
            reply, ch = D.respond(camp, msg)
            c.check("assistant applies: %s" % msg, ch, reply[:200])
        c.check("after those four answers it is ready to compile, not to launch", D.checklist(camp)["ready_to_compile"] and not D.checklist(camp)["ready_to_launch"])
        reply, ch = D.respond(camp, "use omni, 25 requests a day, 3 takes for T0 and 1 view")
        s = D.settings_of(camp)
        c.check("assistant applies several settings from one sentence", s["tool"] == "omni-speech-video" and s["requests_per_day"] == 25
                and s["takes"]["T0"] == 3 and s["views"] == 1, ch)
        D.respond(camp, "exclude MED-07 and DH")
        d2 = D.design(camp)
        c.check("assistant excludes a task and a whole category", "MED-07" not in {j["id"] for j in d2["tasks"]} and not any(j["category"] == "DH" for j in d2["tasks"]))
        D.respond(camp, "include DH")
        c.check("…and includes them back", any(j["category"] == "DH" for j in D.design(camp)["tasks"]))
        c.check("assistant explains a task with its first prompt", "First request's prompt" in D.respond(camp, "explain ROB-09")[0])
        c.check("assistant never launches from chat", "passphrase" in D.respond(camp, "launch the campaign")[0])
        c.check("anything it changes is audited", len(camp.get("audit", [])) >= 6)
        c.check("without a key the assistant answers rule-based", "help" in D.respond(camp, "tell me a joke")[0])
        asked = []
        reply, _ = D.respond(camp, "which wave earns money fastest?", ai=lambda cp, t: asked.append(t) or "advice")
        c.check("a free question goes to the optional AI (advisory)", reply == "advice" and asked)
        reply, _ = D.respond(camp, "which wave earns money fastest?", ai=lambda cp, t: 1 / 0)
        c.check("an AI failure never breaks the conversation", "could not answer" in reply)
        # --- compiling
        m = D.compile_plans(camp, st.folder)
        plan = json.load(open(m["waves"][0]["path"]))
        c.check("compiling writes one scene plan per wave", [x["tier"] for x in m["waves"]] == ["T0", "T30", "SM"] and plan["scene"] is True
                and plan["kind"] == "video" and plan["model"] == "gemini-omni-1.1-flash")
        c.check("every plan item names its task and carries the whole prompt", all(i["covers"] and "Task:" in i["prompt"] for i in plan["items"]))
        jobs = [json.loads(l) for l in open(m["jobs"], encoding="utf-8")]
        c.check("the jobs manifest has one line per request with the metadata record", len(jobs) == sum(x["items"] for x in m["waves"])
                and jobs[0]["metadata"]["provenance"]["synthetic"] is True and jobs[0]["metadata"]["review"]["reviewer_role"])
        import generate_exemplars as G
        c.check("the exemplar generator builds the scene prompt (no avatar image needed)",
                G.prompt_for(plan, plan["items"][0]).startswith(D.FIXED) and plan["items"][0]["prompt"] in G.prompt_for(plan, plan["items"][0]))
        c.check("compiling twice gives the same plans", json.load(open(D.compile_plans(camp, st.folder)["waves"][0]["path"])) == plan)
        # --- the scope guard and a Markdown directive
        small = st.create("small.md", SMALL.encode("utf-8"))
        ds = D.design(small)
        c.check("a Markdown directive is read (tasks, capture, schedule)", len(small["brief"]["tasks"]) == 3 and small["brief"]["capture_spec"]
                and small["brief"]["specialized_modeling"][0]["online_day"] == 60)
        c.check("the scope guard holds back a weapons task, whatever the directive says", [h["id"] for h in ds["held"]] == ["ROB-02"]
                and "ROB-02" not in {j["id"] for j in ds["tasks"]})
        try:
            D.read("empty.md", b"# Nothing here\n\nNo table.")
            none = False
        except ValueError:
            none = True
        c.check("a document with no task register is refused", none)

        # --- a focus directive refines the campaign
        with open(os.path.join(ROOT, "control", "directives", "Focus-Market-Need-Verifiable-AI-Answers.docx"), "rb") as f:
            fdata = f.read()
        fc = D.Store(os.path.join(tmp, "focus"))
        base = fc.ingest("directive.docx", data)
        focused = fc.ingest("Focus-Market-Need.docx", fdata)
        df = D.design(focused)
        first = {j["id"] for j in df["tasks"] if j["focus"] == 1}
        c.check("a focus directive (no task register) refines the existing campaign", focused["id"] == base["id"] and focused["focus"]["sectors"]
                and len(fc.list()) == 1)
        c.check("its first move (aviation maintenance, energy, pharma) leads: energy, aircraft, LOTO, aseptic fill-finish",
                {"ENG-01", "ENG-04", "INS-01", "MFG-04", "MFG-08"} <= first and not {"HOM-01", "ENT-05", "DLY-03"} & {j["id"] for j in df["tasks"] if j["focus"] < 3}, sorted(first))
        c.check("focus tasks come first in every wave", all([j["focus"] for j in df["tasks"] if j["tier"] == t] ==
                                                            sorted(j["focus"] for j in df["tasks"] if j["tier"] == t) for t in D.TIERS))
        c.check("the same focus document again changes nothing", len(fc.ingest("again.docx", fdata).get("audit", [])) == len(focused.get("audit", [])))
        D.respond(focused, "focus tasks only")
        only = D.design(focused)
        c.check("“focus tasks only” keeps just the focus", only["totals"]["tasks"] == df["totals"]["focus_first_move"] + df["totals"]["focus_sectors"]
                and all(j["focus"] < 3 for j in only["tasks"]))
        c.check("“show the focus” explains the ranking", "first-move tasks" in D.respond(focused, "show the focus")[0])
        empty = D.Store(os.path.join(tmp, "nothing-yet"))
        try:
            empty.ingest("focus.docx", fdata)
            alone = False
        except ValueError:
            alone = True
        c.check("a focus directive with no campaign to refine is refused with the reason", alone)

        # --- launching (admin) on a real shared folder
        com = cm.Commons(os.path.join(tmp, "commons"), "control")
        lst = D.Store(com.folder)
        camp2 = lst.create("directive.docx", data)
        for msg in ["I acknowledge the scope", "use the default reviewers", "consent is on file", "anchor source is partner recordings"]:
            D.respond(camp2, msg)
        lst.save(camp2)
        D.compile_plans(camp2, lst.folder)
        try:
            D.launch(lst, com, camp2["id"], "T0", "no-passphrase-yet")
            refused = False
        except Exception:
            refused = True
        c.check("launching needs the admin passphrase", refused)
        com.approvals.set_admin("campaign-admin-1")
        try:
            D.launch(lst, com, camp2["id"], "T0", "campaign-admin-1")
            refused = ""
        except ValueError as e:
            refused = str(e)
        c.check("launching waits for the Google source and a Gemini key", "Google exemplar source" in refused and "Gemini" in refused, refused)
        com.approvals.admin_source("google-generative-exemplars", "approved", "campaign-admin-1", "test", accept_restriction=True)
        ol.save_key(com.folder, "gemini", "TESTKEY123")
        out = D.launch(lst, com, camp2["id"], "T0", "campaign-admin-1")
        import qbcampaign
        tool = next(t for t in qbcampaign.tools(com) if t["id"] == "veo-speech-video")
        c.check("a launched wave's plan goes to the video tool, switched on", tool["on"] and tool["plan"].endswith("wave-t0.json") and "switched on" in out["summary"], tool)
        c.check("the launch is recorded on the campaign", lst.get(camp2["id"])["launched"]["T0"]["status"] == "launched")
        v = D.view(lst, com, camp2["id"])
        c.check("the page view shows the launch and the readiness", v["checklist"]["ready_to_launch"] and v["design"]["waves"][0]["launch"])
        com.store.conn().close()
    print("\n  %d of %d checks passed" % (c.ok, c.n))
    return c.ok == c.n


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
