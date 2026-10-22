"""Lip-reading curriculum test (Language 1.47): the lip reader examined the way a speechreading course examines a learner.

Five stages, each from real exemplar clips of a person saying the standard speech test script (P01-P50):

  1. Single mouth shapes     P01-P15  one vowel per word, words said apart      — told which words may come
  2. Look-alike consonants   P16-P26  p/b/m, f/v, t/d/n … before ee, ah, oo     — told which words may come
  3. Words in context        P39-P43  everyday sentences                        — told the topic's words
  4. Sentences, natural pace P27-P38  dense sentences                           — told nothing
  5. Harder conditions       P44-P49  counting, questions, smiling, serious, slow, fast — told nothing

Words that look the same on the lips (pat / bat / mat) cannot be told apart by sight, so each stage is scored twice: strict
(the exact word) and look-alike (the right word is in the set the reader returns as looking the same). The reader is also
scored on whether it says so: the share of its words that come with their look-alike set when there is one. Results are
per stage, so a weak stage shows where to work. Deterministic, standard library only, no AI model; the clips are measured
by QueryBook (the face tracker), the reader never sees the sound.
"""
import json, os, re

import lipread
import vse

VERSION = "1.0.0"
STAGES = [
    {"id": 1, "name": "Single mouth shapes", "items": ["P%02d" % i for i in range(1, 16)], "hint": "stage", "about": "one vowel per word, words said apart"},
    {"id": 2, "name": "Look-alike consonants", "items": ["P%02d" % i for i in range(16, 27)], "hint": "stage", "about": "p/b/m, f/v, t/d/n, s/z, sh/ch before ee, ah, oo"},
    {"id": 3, "name": "Words in context", "items": ["P%02d" % i for i in range(39, 44)], "hint": "item", "about": "everyday sentences, the topic's words known"},
    {"id": 4, "name": "Sentences at natural pace", "items": ["P%02d" % i for i in range(27, 39)], "hint": None, "about": "dense sentences, nothing known"},
    {"id": 5, "name": "Harder conditions", "items": ["P%02d" % i for i in range(44, 50)], "hint": None, "about": "counting, questions, smiling, serious, slow, fast"},
]
STAGE_OF = {it: st["id"] for st in STAGES for it in st["items"]}


def words(text):
    return re.findall(r"[a-z']+", (text or "").lower().replace("’", "'"))


def compact(frames):
    """browser frames → [t, 13 features] rows (what the reader uses; small enough to keep and ship)"""
    out = []
    for f in frames or []:
        if isinstance(f, dict) and f.get("face"):
            out.append([round(float(f.get("t") or 0), 3)] + lipread.features(f))
    return out


def match(expected, read):
    """expected words vs the reader's words ({word, same_on_lips}) in order (LCS): strict and look-alike matches"""
    def score(same):
        a, b = expected, read
        L = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
        for i in range(len(a)):
            for j in range(len(b)):
                L[i + 1][j + 1] = L[i][j] + 1 if same(a[i], b[j]) else max(L[i][j + 1], L[i + 1][j])
        return L[-1][-1]
    strict = score(lambda e, r: e == r["word"])
    alike = score(lambda e, r: e == r["word"] or e in (r.get("same_on_lips") or []) or e in (r.get("group") or []))
    return strict, alike


class Curriculum:
    def __init__(self, folder, bundled=None):
        self.folder = os.path.join(folder, "lipread-curriculum")
        os.makedirs(self.folder, exist_ok=True)
        self.bundled = bundled

    def add(self, exemplar, item, script, frames, skill=""):
        if item not in STAGE_OF:
            return {"stored": False, "why": "not a curriculum item (P01-P49 of the speech test script)"}
        rows = compact(frames)
        if len(rows) < 12:
            raise ValueError("too few frames with a face")
        name = "%s-%s.json" % (re.sub(r"[^A-Za-z0-9]", "", item), re.sub(r"[^A-Za-z0-9]", "", str(exemplar))[:20])
        with open(os.path.join(self.folder, name), "w", encoding="utf-8") as f:
            json.dump({"exemplar": exemplar, "item": item, "skill": skill, "script": script, "fps": 24, "frames": rows}, f, separators=(",", ":"))
        return {"stored": True, "item": item, "stage": STAGE_OF[item], "frames": len(rows)}

    def clips(self):
        """the clips of this computer; where an item has none, the bundled clips (so the test runs out of the box)"""
        out = {}
        if self.bundled and os.path.isfile(self.bundled):
            with open(self.bundled, encoding="utf-8") as f:
                for c in json.load(f)["clips"]:
                    out[c["item"]] = dict(c, source="bundled")
        for fn in sorted(os.listdir(self.folder)):
            if fn.endswith(".json"):
                with open(os.path.join(self.folder, fn), encoding="utf-8") as f:
                    c = json.load(f)
                out[c["item"]] = dict(c, source="this computer")
        return [out[k] for k in sorted(out)]

    def export(self, path, person):
        clips = [c for c in self.clips() if c.get("source") == "this computer"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"kind": "lipread-curriculum", "version": VERSION, "person": person, "clips": [{k: c[k] for k in ("exemplar", "item", "script", "fps", "frames")} for c in clips]},
                      f, separators=(",", ":"))
        return len(clips)

    def run(self, lab=None, learned=None, targets=None, progress=None):
        clips = self.clips()
        stage_words = {st["id"]: sorted({w for c in clips if STAGE_OF.get(c["item"]) == st["id"] for w in words(c["script"])}) for st in STAGES}
        per = []
        for n, c in enumerate(clips):
            st = STAGE_OF.get(c["item"])
            if not st:
                continue
            hint = next(s["hint"] for s in STAGES if s["id"] == st)
            hw = stage_words[st] if hint == "stage" else words(c["script"]) if hint == "item" else []
            # told the words beforehand = a closed set (as a course tells the learner which words may come); told nothing = open vocabulary
            r = vse.lip_read(c["frames"], "en", tuple(hw), "", lab, learned, targets, vocab_size=0 if hw else 1500)
            read = [w for s in (r.get("lipread") or {}).get("segments", []) for w in s["words"]]
            exp = words(c["script"])
            strict, alike = match(exp, read)
            amb = [w for w in read if w.get("same_on_lips")]
            per.append({"item": c["item"], "stage": st, "source": c.get("source"), "expected": len(exp), "read": len(read),
                        "strict": round(strict / max(1, len(exp)), 3), "look_alike": round(alike / max(1, len(exp)), 3),
                        "alternatives_shown": round(len(amb) / max(1, len(read)), 3) if read else None,
                        "text": " ".join(w["word"] for w in read)[:200], "script": c["script"]})
            if progress:
                progress(n + 1, len(clips), c["item"])
        stages = []
        for s in STAGES:
            rows = [p for p in per if p["stage"] == s["id"]]
            m = lambda k: round(sum(p[k] for p in rows) / len(rows), 3) if rows else None
            alt = [p["alternatives_shown"] for p in rows if p["alternatives_shown"] is not None]
            stages.append({"stage": s["id"], "name": s["name"], "about": s["about"], "clips": len(rows), "strict": m("strict"),
                           "look_alike": m("look_alike"), "alternatives_shown": round(sum(alt) / len(alt), 3) if alt else None,
                           "told": {"stage": "the stage's words", "item": "the topic's words", None: "nothing"}[s["hint"]]})
        done = [s for s in stages if s["clips"]]
        weakest = min(done, key=lambda s: (s["look_alike"], s["stage"])) if done else None
        return {"version": VERSION, "clips": len(per), "stages": stages, "items": per,
                "weakest_stage": weakest and {"stage": weakest["stage"], "name": weakest["name"], "look_alike": weakest["look_alike"]},
                "engine": "VSE lip reader (%s)" % vse.VERSION, "deterministic": True}


def self_test():
    out = []
    ok = lambda n, c: out.append((n, bool(c)))
    s, a = match(["pat", "the", "cat"], [{"word": "bat", "same_on_lips": ["pat", "mat"]}, {"word": "the"}, {"word": "hat"}])
    ok("look-alike words get credit only as look-alikes", (s, a) == (1, 2))
    ok("every curriculum item has one stage", len(STAGE_OF) == 49 and sorted(STAGE_OF.values()).count(1) == 15)
    ok("frames are kept as the reader's 13 measures", len(compact([{"t": 0, "face": True, "gap": 0.2, "bs": {"jawOpen": 0.3}}])[0]) == 14)
    return out
