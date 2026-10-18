"""The Math, Science & Engineering harvest team (see qbcommons for the four agents).

What it harvests into the Commons: the physical constants (CODATA 2018 / SI 2019), the elements
(IUPAC atomic weights), the unit definitions, molar masses of common compounds and the two derived
constants (recomputed, so they count as verified), and this application's own verified saved answers.

What it answers for the other applications: lifespans, date order and calendar dates (History & News),
arithmetic, unit conversions and whether a name is a chemical element — all by calculation.
"""
import json
from fractions import Fraction as F

import engine
import qbcommons as cm
import science
import units
import verify

LONGEST_LIFE = 122          # years: Jeanne Calment (1875–1997), the longest documented human life
COMPOUNDS = ["H2O", "CO2", "O2", "N2", "H2", "NaCl", "KCl", "CaCO3", "CH4", "C2H6", "C3H8", "C2H5OH", "CH3OH", "C6H12O6", "C12H22O11",
             "NH3", "HCl", "H2SO4", "HNO3", "H3PO4", "NaOH", "KOH", "Ca(OH)2", "NaHCO3", "Na2CO3", "CuSO4", "CuSO4·5H2O", "Fe2O3",
             "Fe3O4", "Al2O3", "SiO2", "MgO", "CaO", "SO2", "NO2", "O3", "H2O2", "CH3COOH", "C8H18", "AgNO3"]
SRC_CODATA = science.CONSTANT_SOURCE
SRC_IUPAC = science.ELEMENT_SOURCE
SRC_UNITS = "SI Brochure 9th edition (2019); NIST SP 811 exact unit definitions"
SRC_APP = "QueryBook Math, Science & Engineering (exact arithmetic)"
LIC_FACTS = "facts and defined values — not subject to copyright"
BUDGET = {"elements": 60, "saved": 200, "recheck": 300}


def _units():
    seen, out = set(), []
    for u in units.unit_table():
        if u["si_factor"] == "affine" or u["description"] in seen:
            continue
        seen.add(u["description"])
        out.append(u)
    return out


def _ymd(d):
    return (int(d["year"]), int(d.get("month") or 0), int(d.get("day") or 0))


def _label(d):
    y, m, dd = _ymd(d)
    ys = "%d BC" % -y if y < 0 else str(y)
    return (d.get("label") or "%s%s%s" % ("%d " % dd if dd else "", (["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m] + " ") if m else "", ys))


def _years_between(a, b):
    """Whole years from date a to date b (year-only dates count whole years). No year 0 between BC and AD."""
    ya, ma, da = _ymd(a)
    yb, mb, db = _ymd(b)
    n = yb - ya - (1 if ya < 0 < yb else 0)
    if ma and mb and (mb, db or 0) < (ma, da or 0):
        n -= 1
    return n


class StemAdapter(cm.Adapter):
    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------ Strategist
    def survey(self, ctx):
        have = {r["predicate"]: r["n"] for r in ctx.commons.store.query(
            "SELECT predicate, count(*) AS n FROM facts WHERE domain = 'stem' AND origin_app = 'stem' GROUP BY predicate")}
        saved = self.app.store.scalar("SELECT count(*) FROM facts WHERE status = 'verified'", default=0)
        return {"constants": len(science.CONSTANTS), "constants_shared": have.get("value", 0),
                "elements": len(science.ELEMENTS), "elements_done": min(ctx.cursor("elements"), len(science.ELEMENTS)),
                "units": len(_units()), "units_shared": have.get("equals in SI units", 0),
                "compounds": len(COMPOUNDS), "compounds_shared": have.get("molar mass", 0),
                "saved_verified": saved, "saved_after_id": ctx.cursor("saved"),
                "stem_facts_in_commons": ctx.commons.store.scalar("SELECT count(*) FROM facts WHERE domain = 'stem'", default=0)}

    def strategy(self, sv, ctx):
        goals = []
        n_open = ctx.commons.store.scalar("SELECT count(*) FROM requests WHERE to_app = 'stem' AND status = 'open'", default=0)
        if n_open:
            goals.append({"goal": "Answer %d checks from the other applications" % n_open, "priority": 1,
                          "why": "lifespans, dates and arithmetic in their facts can be settled by calculation"})
        if sv["constants_shared"] < sv["constants"]:
            goals.append({"goal": "Share the physical constants", "priority": 2, "why": "reference values every domain relies on (CODATA 2018, SI 2019)"})
        if sv["elements_done"] < sv["elements"]:
            goals.append({"goal": "Share the elements (%d of %d done)" % (sv["elements_done"], sv["elements"]), "priority": 3,
                          "why": "atomic numbers and weights; the element names also give the Language Builder words to confirm"})
        if sv["units_shared"] < sv["units"]:
            goals.append({"goal": "Share the unit definitions", "priority": 4, "why": "exact SI factors let every application convert measurements"})
        if sv["compounds_shared"] < sv["compounds"]:
            goals.append({"goal": "Compute molar masses of common compounds", "priority": 5, "why": "calculated from the atomic weights, so they are verified"})
        if sv["saved_verified"]:
            goals.append({"goal": "Share this application's verified saved answers", "priority": 6, "why": "each one is recomputed before it is shared"})
        goals.append({"goal": "Re-check the shared science facts", "priority": 7, "why": "a value that no longer matches its reference is marked contradicted"})
        return {"goals": goals, "budget": BUDGET,
                "sources": [{"name": SRC_CODATA, "licence": LIC_FACTS, "use": "constants"},
                            {"name": SRC_IUPAC, "licence": LIC_FACTS, "use": "elements and molar masses"},
                            {"name": SRC_UNITS, "licence": LIC_FACTS, "use": "unit definitions"},
                            {"name": SRC_APP, "licence": "computed here", "use": "saved answers, derived constants, checks"}]}

    # ------------------------------------------------------------------ Planner
    def plan(self, st, ctx):
        names = {g["goal"].split(" (")[0] for g in st["goals"]}
        tasks = []
        if "Share the physical constants" in names:
            tasks.append({"action": "constants", "title": "Publish %d constants and recompute R and F" % len(science.CONSTANTS)})
        if "Share the elements" in names:
            start = ctx.cursor("elements")
            end = min(start + st["budget"]["elements"], len(science.ELEMENTS))
            tasks.append({"action": "elements", "title": "Publish elements %d–%d" % (start + 1, end), "target": {"from": start, "to": end}})
        if "Share the unit definitions" in names:
            tasks.append({"action": "units", "title": "Publish %d unit definitions" % len(_units())})
        if "Compute molar masses of common compounds" in names:
            tasks.append({"action": "compounds", "title": "Compute %d molar masses" % len(COMPOUNDS)})
        if "Share this application's verified saved answers" in names:
            tasks.append({"action": "saved", "title": "Recompute and publish up to %d saved answers" % st["budget"]["saved"],
                          "target": {"after": ctx.cursor("saved"), "limit": st["budget"]["saved"]}})
        return tasks

    # ------------------------------------------------------------------ Harvester
    def execute(self, task, ctx):
        a, t = task["action"], task.get("target") or {}
        if a == "constants":
            items = [self._constant(c) for c in science.CONSTANTS]
            items += self._derived()
            return {"items": items, "detail": "%d constants, 2 recomputed" % len(science.CONSTANTS)}
        if a == "elements":
            items = []
            for e in science.ELEMENTS[t["from"]:t["to"]]:
                items += self._element(e)
            return {"items": items, "cursor": {"elements": t["to"]}, "detail": "%d elements" % (t["to"] - t["from"])}
        if a == "units":
            return {"items": [self._unit(u) for u in _units()]}
        if a == "compounds":
            return {"items": [self._compound(f) for f in COMPOUNDS]}
        if a == "saved":
            rows = self.app.store.query("SELECT * FROM facts WHERE status = 'verified' AND id > ? ORDER BY id LIMIT ?", (t["after"], t["limit"]))
            items = [i for i in (self._saved(r) for r in rows) if i]
            return {"items": items, "cursor": {"saved": rows[-1]["id"]} if rows else {}, "detail": "%d of %d recomputed" % (len(items), len(rows))}
        raise ValueError("unknown task %s" % a)

    def _constant(self, c, verdict="supports"):
        sym, name, value, unit, exact, note = c
        return {"subject": "constant %s (%s)" % (sym, name), "predicate": "value", "object": ("%s %s" % (value, unit)).strip(),
                "statement": "The %s %s is %s %s%s." % (name, sym, value, unit, " exactly" if exact else ""),
                "evidence": [{"method": "reference", "source": SRC_CODATA, "licence": LIC_FACTS, "verdict": verdict, "detail": note}],
                "reasoning": ["Read from the bundled CODATA 2018 table: %s." % note]}

    def _derived(self):
        na, kb, e = (F(dict((c[0], c[2]) for c in science.CONSTANTS)[k]) for k in ("N_A", "k_B", "e"))
        out = []
        for sym, name, val, unit, how in (("R", "molar gas constant", na * kb, "J/(mol*K)", "N_A × k_B"), ("F", "Faraday constant", na * e, "C/mol", "N_A × e")):
            dec = science._dec(val)
            out.append({"subject": "constant %s (%s)" % (sym, name), "predicate": "value", "object": "%s %s" % (dec, unit),
                        "evidence": [{"method": "recompute", "source": SRC_APP, "licence": "computed here", "detail": "%s, exact rational arithmetic" % how}],
                        "reasoning": ["%s = %s, both exact SI defining constants since 2019." % (sym, how), "Multiplied exactly as fractions: %s." % dec]})
        return out

    def _element(self, e, verdict="supports"):
        subj = "element %s (%s)" % (e["symbol"], e["name"])
        checks = [{"kind": "term", "payload": {"word": e["name"].lower()}}] if e["name"].isalpha() else []
        return [{"subject": subj, "predicate": "atomic number", "object": str(e["z"]),
                 "evidence": [{"method": "reference", "source": SRC_IUPAC, "licence": LIC_FACTS, "verdict": verdict}],
                 "reasoning": ["Position %d in the IUPAC periodic table." % e["z"]], "checks": checks},
                {"subject": subj, "predicate": "standard atomic weight", "object": e["weight"],
                 "evidence": [{"method": "reference", "source": SRC_IUPAC, "licence": LIC_FACTS, "verdict": verdict,
                               "detail": None if e["stable"] else "no stable isotope: [mass number] of a long-lived isotope"}]}]

    def _unit(self, u, verdict="supports"):
        return {"subject": "unit %s (%s)" % (u["description"], u["unit"]), "predicate": "equals in SI units",
                "object": ("%s %s" % (u["si_factor"], u["dimension"])).strip(),
                "evidence": [{"method": "reference", "source": SRC_UNITS, "licence": LIC_FACTS, "verdict": verdict}]}

    def _compound(self, f):
        r = science.molar_mass(f)
        parts = ", ".join("%d × %s (%s)" % (x["count"], x["symbol"], x["weight"]) for x in r["elements"])
        return {"subject": "compound %s" % f, "predicate": "molar mass", "object": "%s g/mol" % r["molar_mass"],
                "evidence": [{"method": "recompute", "source": SRC_APP, "licence": "computed here", "detail": "sum of standard atomic weights"}],
                "reasoning": ["Parsed the formula %s%s." % (f, (" into " + parts) if parts else ""),
                              "Added the IUPAC standard atomic weights of each atom: %s g/mol." % r["molar_mass"]]}

    def _saved(self, row):
        try:
            detail = json.loads(row["detail"] or "{}")
            fresh = verify.recompute(row["kind"], row["question"], detail)
        except Exception:
            return None
        ok = verify.answers_match(row["answer"].split(" ")[0] if row["kind"] != "calc" else row["answer"], fresh)
        return {"subject": row["question"], "predicate": {"calc": "equals", "convert": "converts to", "formula": "solves to", "molar": "molar mass"}.get(row["kind"], "equals"),
                "object": row["answer"],
                "evidence": [{"method": "recompute", "source": SRC_APP, "licence": "computed here", "verdict": "supports" if ok else "contradicts",
                              "detail": "recomputed: %s" % fresh}],
                "reasoning": ["Recomputed from the saved inputs (%s)." % row["kind"], "Result %s %s the saved answer." % (fresh, "matches" if ok else "does NOT match")]}

    # ------------------------------------------------------------------ Curator upkeep: re-check shared reference values
    def curate(self, ctx):
        after = ctx.cursor("recheck")
        rows = ctx.commons.store.query("""SELECT id, subject, predicate, object FROM facts WHERE origin_app = 'stem' AND id > ?
                                          AND predicate IN ('value', 'atomic number', 'standard atomic weight', 'equals in SI units') ORDER BY id LIMIT ?""",
                                       (after, BUDGET["recheck"]))
        consts = {"constant %s (%s)" % (c[0], c[1]): c for c in science.CONSTANTS}
        elems = {"element %s (%s)" % (e["symbol"], e["name"]): e for e in science.ELEMENTS}
        unit_rows = {"unit %s (%s)" % (u["description"], u["unit"]): u for u in _units()}
        out = []
        for r in rows:
            s, p = r["subject"], r["predicate"]
            if p == "value" and s in consts and consts[s][0] not in ("R", "F"):
                fresh = self._constant(consts[s])
            elif s in elems:
                fresh = next(x for x in self._element(elems[s]) if x["predicate"] == p)
            elif s in unit_rows:
                fresh = self._unit(unit_rows[s])
            else:
                continue
            if fresh["object"] != r["object"]:
                # the shared value differs from the reference: say so on the shared fact
                fresh = dict(fresh, object=r["object"], checks=[], reasoning=["Re-checked against the reference table: it gives %s, not %s." % (fresh["object"], r["object"])])
                fresh["evidence"] = [dict(fresh["evidence"][0], verdict="contradicts", detail="reference gives %s" % self._ref_value(s, p, consts, elems, unit_rows))]
            out.append(fresh)
        nxt = rows[-1]["id"] if len(rows) == BUDGET["recheck"] else 0          # wrap around when the end is reached
        ctx.commons.set_setting("cursor:stem:recheck", nxt)
        return out

    def _ref_value(self, s, p, consts, elems, unit_rows):
        if s in consts:
            return self._constant(consts[s])["object"]
        if s in elems:
            return next(x for x in self._element(elems[s]) if x["predicate"] == p)["object"]
        return self._unit(unit_rows[s])["object"]

    # ------------------------------------------------------------------ checks for the other applications
    def verifiers(self, ctx):
        return {"lifespan": self.check_lifespan, "date_order": self.check_order, "calendar_date": self.check_date,
                "arithmetic": self.check_arithmetic, "element": self.check_element, "unit": self.check_unit}

    def check_lifespan(self, p):
        b, d = p["born"], p["died"]
        if _ymd(d) < _ymd(b):
            return {"verdict": "contradicts", "detail": "died (%s) before being born (%s)" % (_label(d), _label(b)),
                    "reasoning": ["Born %s, died %s." % (_label(b), _label(d)), "The death date is earlier than the birth date."]}
        age = _years_between(b, d)
        why = ["Born %s, died %s." % (_label(b), _label(d)), "Calendar arithmetic gives an age at death of %d years%s." %
               (age, "" if b.get("month") and d.get("month") else " (to the year: the dates have no month)")]
        if age > LONGEST_LIFE:
            return {"verdict": "contradicts", "detail": "age at death %d is beyond the longest documented life (%d years)" % (age, LONGEST_LIFE),
                    "reasoning": why + ["No documented human life exceeds %d years (Jeanne Calment, 1875–1997)." % LONGEST_LIFE]}
        return {"verdict": "supports", "detail": "age at death %d years — possible" % age,
                "reasoning": why + ["Between 0 and %d years, so the two dates are consistent." % LONGEST_LIFE]}

    def check_order(self, p):
        a, b = p["earlier"], p["later"]
        ok = _ymd(a) <= _ymd(b)
        return {"verdict": "supports" if ok else "contradicts", "detail": "%s %s %s" % (_label(a), "is not after" if ok else "is after", _label(b)),
                "reasoning": ["Compared year, month and day: %s against %s." % (_label(a), _label(b))]}

    def check_date(self, p):
        y, m, d = _ymd(p)
        if y == 0:
            return {"verdict": "contradicts", "detail": "there is no year 0", "reasoning": ["The calendar goes from 1 BC to AD 1."]}
        days = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if m and not 1 <= m <= 12 or (d and not 1 <= d <= days[m]):
            return {"verdict": "contradicts", "detail": "no such day or month", "reasoning": ["Month %d, day %d is not on the calendar." % (m, d)]}
        leap = verify.is_leap(y) if y >= 1583 else abs(y) % 4 == 0
        if m == 2 and d == 29 and not leap:
            return {"verdict": "contradicts", "detail": "%d was not a leap year" % y,
                    "reasoning": ["29 February exists only in leap years.", "%d is not one (%s calendar)." % (y, "Gregorian" if y >= 1583 else "Julian")]}
        return {"verdict": "supports", "detail": "%s is a real calendar date" % _label(p),
                "reasoning": ["Month and day are within range%s." % (" and %d was a leap year" % y if m == 2 and d == 29 else "")]}

    def check_arithmetic(self, p):
        r = engine.evaluate(p["expression"])
        ok = verify.answers_match(str(p["value"]), r["value"])
        return {"verdict": "supports" if ok else "contradicts", "detail": "%s = %s" % (p["expression"], r["display"]),
                "reasoning": ["Evaluated %s exactly: %s." % (p["expression"], r["display"])]}

    def check_element(self, p):
        e = science.element(p.get("name") or p.get("symbol") or "")
        if not e:
            return {"verdict": "contradicts", "detail": "not one of the 118 known elements", "reasoning": ["Searched the IUPAC table by name and symbol."]}
        return {"verdict": "supports", "detail": "%s (%s), atomic number %d" % (e["name"], e["symbol"], e["z"]),
                "reasoning": ["Found in the IUPAC table: %s, symbol %s, atomic number %d." % (e["name"], e["symbol"], e["z"])]}

    def check_unit(self, p):
        r = units.convert(p["question"])
        ok = verify.answers_match(str(p["value"]).split(" ")[0], r["result"])
        return {"verdict": "supports" if ok else "contradicts", "detail": r["display"], "reasoning": ["Converted with exact unit factors: %s." % r["display"]]}
