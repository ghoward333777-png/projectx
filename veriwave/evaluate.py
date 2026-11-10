"""VeriWave readiness evaluation, from the command line, against the fact store on D:\\QB.

    python evaluate.py                     300 sampled facts x 3 phrasings, plus D:\\QB\\veriwave\\eval-questions.jsonl
    python evaluate.py --sample 1000       more questions
    python evaluate.py --questions my.jsonl --seed 7
    python evaluate.py --with-apps         also ask QueryBook's applications (starts them, as VeriWave does)

Refuses to run unless D:\\QB (or VERIWAVE_FACTS, set on purpose) holds a connected fact store. The report is saved in
D:\\QB\\veriwave\\evals and shown on VeriWave's Admin > Readiness screen.
"""
from __future__ import annotations

import json
import os
import sys

from vw import evaluate, store
from vw.backends import Claude
from vw.factstore import FactStore
from vw.model import VeriWave
from vw.querybook import Connection
from vw.server import int_param


def main(argv: list[str]) -> int:
    root = evaluate.eval_root()
    sample = int_param(argv[argv.index("--sample") + 1], 300, 10, 5000) if "--sample" in argv and argv.index("--sample") + 1 < len(argv) else 300
    seed = int_param(argv[argv.index("--seed") + 1], 1, 0, 1000000) if "--seed" in argv and argv.index("--seed") + 1 < len(argv) else 1
    conn = Connection("auto" if "--with-apps" in argv else "none", False)
    conn.start()
    if "--with-apps" in argv:
        conn.wait_until_running(90.0)
    facts = FactStore(root)
    st = store.Store(store.data_root())
    model = VeriWave(conn, st, Claude("", None), facts)
    qfile = argv[argv.index("--questions") + 1] if "--questions" in argv and argv.index("--questions") + 1 < len(argv) \
        else os.path.join(st.root, "eval-questions.jsonl")
    curated = evaluate.load_curated(qfile)
    fs = facts.status()
    print("\n  VeriWave readiness evaluation")
    print("  Fact store: %s  (%s facts)" % (root, format(int(fs.get("facts") or 0), ",")))
    why = evaluate.readiness_check(fs, root)
    if why:
        print("  Cannot run: " + why + "\n")
        conn.stop()
        return 2
    print("  Questions: %d sampled facts x %d phrasings + %d of your own (%s)\n" % (sample, len(evaluate.PHRASINGS), len(curated), qfile))

    def progress(done: int, total: int) -> None:
        if done % 25 == 0 or done == total:
            print("  %d / %d" % (done, total), flush=True)

    rep = evaluate.run(model, root, sample, seed, curated, progress)
    folder = os.path.join(st.root, "evals")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, evaluate.report_name(int(rep["at"])))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False)
    s = rep["summary"]
    print("\n  Answer rate      %5.1f%%   (answered when the fact is in the store)" % s["answer_rate"])
    print("  Accuracy         %5.1f%%   (a citation holds the right answer)" % s["accuracy"])
    print("  Top answer       %5.1f%%   (the one-line answer itself is right)" % s["top_answer_accuracy"])
    print("  Wrong refusals   %5.1f%%   (\"I don't know\" although the fact is there)" % s["wrong_refusal_rate"])
    print("  Response time    median %.0f ms, 95th percentile %.0f ms" % (s["median_ms"], s["p95_ms"]))
    for t, ps in rep.get("by_phrasing", {}).items():
        print("    %-26s answer rate %5.1f%%, accuracy %5.1f%%" % (t, ps["answer_rate"], ps["accuracy"]))
    print("\n  Report: " + path + "\n")
    conn.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
