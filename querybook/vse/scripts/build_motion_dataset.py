"""Motion training data from QueryBook's reservoir: per recording, the viseme per frame (labels), neutral prosody
and emotion, a zero speaker vector, and the measured 13 mouth numbers as the motion target (head/eyes zero)."""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vse.common.types import VISEMES  # noqa: E402

db, out = sys.argv[1], sys.argv[2]
con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
n = 0
with open(out, "w", encoding="utf-8") as f:
    for frames, labels in con.execute("SELECT frames, labels FROM ingest_reservoir"):
        fr, lb = json.loads(frames), json.loads(labels or "[]")
        if len(fr) < 10:
            continue
        vis = [VISEMES.index(l[1]) if l and len(l) > 1 and l[1] in VISEMES else 0 for l in lb]
        motion = [r[1:14] + [0.0] * 8 for r in fr]
        f.write(json.dumps({"visemes": vis, "prosody": [[0.5, 0.5, 0.5, 1.0]] * len(fr), "emotion": [0.5, 0.45, 0.5, 0, 0, 0, 0, 0],
                            "speaker": [0.0] * 256, "motion": motion}) + "\n")
        n += 1
print("wrote %d recordings to %s" % (n, out))
