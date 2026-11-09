"""qbmath — the suite's learning arithmetic as pure functions (network memory and answer routing).

Plain numbers in, plain numbers out: no I/O, no globals changed, fully annotated. Each function has
  * a Lean 4 proof of its bounds in querybook-one/lean/QueryBookOne/Synapse.lean and Routing.lean, and
  * a line-for-line Rust port in querybook-one/rust/qbcore/src/qbmath.rs, checked against shared test vectors.
qbsynapse.py and qbdsn.py call these, so the suite, the proofs and the Rust port share one definition.
"""
from __future__ import annotations

# network memory (qbsynapse)
SYN_INIT, SYN_ETA, SYN_DEPRESS, SYN_THETA = 0.20, 0.10, 0.25, 0.30
SYN_DECAY_PER_DAY, SYN_CONSOLIDATED_DECAY_PER_DAY, SYN_CONSOLIDATE_AFTER = 0.05, 0.01, 20
SYN_PRUNE_BELOW, SYN_PRUNE_IDLE_DAYS = 0.05, 30
# answer routing (qbdsn)
DSN_START, DSN_THETA, DSN_ETA, DSN_SILENCE, DSN_DRIFT, DSN_EXPLORE_EVERY = 0.5, 0.30, 0.10, 0.15, 0.002, 25


def syn_potentiate(s: float) -> float:
    """a joint success strengthens: s + ETA·(1 − s)"""
    return round(s + SYN_ETA * (1 - s), 4)


def syn_depress(s: float) -> float:
    """a joint failure weakens: s − DEPRESS·s"""
    return round(s - SYN_DEPRESS * s, 4)


def syn_fade(s: float, days: float, consolidated: bool) -> float:
    """forgetting over idle days: s·(1 − rate)^days, rate 1%/day when consolidated, else 5%/day"""
    if days <= 0:
        return s
    rate = SYN_CONSOLIDATED_DECAY_PER_DAY if consolidated else SYN_DECAY_PER_DAY
    return round(s * (1 - rate) ** days, 4)


def syn_threshold(good: int, bad: int) -> float:
    """the activation threshold rises with unreliability: THETA + 0.4·bad/(good + bad)"""
    tot = good + bad
    return round(SYN_THETA + 0.4 * bad / tot, 3) if tot else SYN_THETA


def syn_consolidated(good: int, bad: int) -> bool:
    """at least 20 good outcomes and four good for every bad one"""
    return good >= SYN_CONSOLIDATE_AFTER and good >= 4 * bad


def syn_prunable(s: float, idle_days: float) -> bool:
    """a faded synapse that has been idle long enough is removed"""
    return s < SYN_PRUNE_BELOW and idle_days >= SYN_PRUNE_IDLE_DAYS


def dsn_recover(s: float) -> float:
    """before a lookup, a weak pathway recovers slowly toward 0.5 (re-sensitisation); no rounding, as in qbdsn"""
    return s + DSN_DRIFT * (DSN_START - s) if s < DSN_START else s


def dsn_hit(s: float) -> float:
    """the dataset answered: s + ETA·(1 − s)"""
    return round(s + DSN_ETA * (1 - s), 4)


def dsn_miss(s: float) -> float:
    """the dataset had nothing: s − SILENCE·s"""
    return round(s - DSN_SILENCE * s, 4)


def dsn_strong(s: float) -> bool:
    """a pathway is asked first when it is at least THETA"""
    return s >= DSN_THETA


def self_test() -> list[tuple[str, bool]]:
    checks = [
        ("potentiate 0.2 -> 0.28", syn_potentiate(0.2) == 0.28),
        ("depress 0.4 -> 0.3", syn_depress(0.4) == 0.3),
        ("fade 10 idle days at 5%", syn_fade(1.0, 10, False) == round(0.95 ** 10, 4)),
        ("consolidated fades slower", syn_fade(1.0, 10, True) > syn_fade(1.0, 10, False)),
        ("threshold 0.30..0.70", syn_threshold(0, 0) == 0.3 and syn_threshold(0, 5) == 0.7 and syn_threshold(3, 1) == 0.4),
        ("consolidation needs 20 good and 4:1", syn_consolidated(20, 5) and not syn_consolidated(19, 0) and not syn_consolidated(20, 6)),
        ("routing stays in [0, 1]", all(0 <= f(x) <= 1 for f in (dsn_hit, dsn_miss, dsn_recover) for x in (0.0, 0.3, 0.5, 1.0))),
        ("recovery never passes 0.5", dsn_recover(0.1) < 0.5 and dsn_recover(0.7) == 0.7),
    ]
    return checks


if __name__ == "__main__":
    results = self_test()
    for name, ok in results:
        print(("  [OK]   " if ok else "  [FAIL] ") + name)
    print("%d of %d checks passed" % (sum(ok for _, ok in results), len(results)))
    raise SystemExit(0 if all(ok for _, ok in results) else 1)
