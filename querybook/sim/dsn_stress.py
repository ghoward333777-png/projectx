#!/usr/bin/env python3
"""dsn_stress.py — stress test: QueryBook's current design against the Digital Synaptic Network (DSN) design.

The question: can agents that talk to each other the way neurons do (sparse signals along weighted, auditable "digital
synapses", Fact-Unit IDs instead of text, thresholds, excitation and inhibition, connections that learn) answer better,
cheaper or more robustly than QueryBook does today — and how does each hold up under extreme stress?

Six engines answer the same questions over the same facts:
  A0  Current QueryBook, as installed without an AI model: the REAL qb_chat.answer() pipeline (plan -> retrieve ->
      gate -> compose -> check) on a REAL ufcs_store, the plan made from the question's words.
  A1  Current QueryBook with a planned first lookup (what an AI planner gives it): the real retrieve + gate, one hop.
  A2  Control: the current pipeline chained hop by hop (a small change, no agents) — separates "multi-hop" from "agents".
  B   Conventional multi-agent: a coordinator asks EVERY agent each step, agents answer in text.
  C0  DSN without learning: subscriptions (dendrites), synapses, Fact-Unit-ID messages, thresholds, inhibition.
  C   DSN with learning: synapses strengthen on verified help, weaken on lies and silence (auditable records).

Facts come from a synthetic world with known answers (works, authors, people, cities, countries, continents,
currencies, organisations), 1- to 4-step questions. Stress, alone and combined: wrong facts (low and high trust),
missing facts, lying / dead / slow agents, thousands of agents, a million facts, poisoned learning feedback, the faulty
agents changing mid-run, parallel load.

Communication time is MODELLED (per message 0.5 ms + bytes at 100 MB/s; a dead agent costs a 250 ms timeout; a slow one
+50 ms) and reported beside the real compute time. Everything is seeded: the same command gives the same numbers.

  python dsn_stress.py quick                 (a few minutes)
  python dsn_stress.py stress                (about half an hour on a laptop-class machine)
  python dsn_stress.py extreme               (hours; for a strong PC: 1 million facts, 10,560 agents, all stresses)
  python dsn_stress.py self-test
Options: --qb FOLDER (where qb_chat.py and ufcs_store.py are; default: beside this file, then ../QueryBook-v9.64)
         --out FOLDER (reports; default ./dsn-results)   --threads N   --queries N   --seed N
Standard library only. Writes a Markdown report and a JSON file with every number.
"""
import argparse, hashlib, json, math, os, random, shutil, statistics, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor

VERSION = "1.1.0"
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------------------------- the prototype's code
def load_prototype(qb=None):
    for d in [qb] if qb else [HERE, os.path.join(HERE, "..", "QueryBook-v9.64"), os.path.join(HERE, "QueryBook-v9.64")]:
        if d and os.path.isfile(os.path.join(d, "qb_chat.py")) and os.path.isfile(os.path.join(d, "ufcs_store.py")):
            sys.path.insert(0, os.path.abspath(d))
            for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):     # the deterministic path: no AI model is ever called
                os.environ.pop(k, None)
            import qb_chat, ufcs_store
            return qb_chat, ufcs_store, os.path.abspath(d)
    raise SystemExit("qb_chat.py and ufcs_store.py were not found: put this file in the QueryBook prototype folder or pass --qb FOLDER")


# ---------------------------------------------------------------------------------------------- the world
SYL = ["ka", "vo", "ra", "lin", "mo", "te", "sa", "dri", "el", "nu", "por", "vash", "qi", "lu", "ben", "tor", "ia", "zen",
       "ma", "rek", "ost", "fa", "gil", "un", "ho", "pe", "sti", "wa", "ry", "ond", "cal", "ix", "ve", "ta", "nor", "bu"]
PRED_TEXT = {"author": "author", "born_in": "birthplace", "in_country": "country", "on_continent": "continent",
             "uses_currency": "currency", "has_capital": "capital", "headquartered_in": "headquarters city",
             "founded_by": "founder", "published_by": "publisher", "works_as": "occupation", "citizen_of": "citizenship"}
FUNCTIONAL = set(PRED_TEXT)                # every relation here has one true value per subject (none is in the prototype's
                                           # MULTI_VALUED list, so both designs treat two values as a contradiction)
CHAINS = {1: [["author"], ["born_in"], ["in_country"], ["headquartered_in"], ["published_by"], ["on_continent"]],
          2: [["author", "born_in"], ["published_by", "headquartered_in"], ["born_in", "in_country"], ["founded_by", "born_in"]],
          3: [["author", "born_in", "in_country"], ["published_by", "headquartered_in", "in_country"], ["founded_by", "born_in", "in_country"]],
          4: [["author", "born_in", "in_country", "on_continent"], ["published_by", "headquartered_in", "in_country", "uses_currency"],
              ["published_by", "founded_by", "born_in", "in_country"]]}
START = {"author": "work", "published_by": "work", "born_in": "person", "founded_by": "org", "headquartered_in": "org",
         "in_country": "city", "on_continent": "country"}


class World:
    """facts[(s, p)] = [(o, trust, kind, fuid)] — kind: true / noise (wrong, low trust) / adv (wrong, high trust)"""

    def __init__(self, n_facts=200_000, seed=1, noise=0.0, adv=0.0, missing=0.0):
        rnd = random.Random(seed)
        self.seed, self.noise, self.adv, self.missing = seed, noise, adv, missing
        unit = max(10, int(n_facts / 1.9))
        size = {"continent": 7, "currency": 60, "country": 200, "city": max(50, unit // 20), "person": max(50, unit // 4),
                "org": max(20, unit // 20), "work": max(50, unit // 2), "occupation": 300}
        used = set()

        def name(kind, i):
            while True:
                n = " ".join("".join(rnd.choice(SYL) for _ in range(rnd.randint(2, 3))) for _ in range(2 if kind in ("person",) else 1))
                n = "%s %s%d" % (n, kind[:2], i) if kind not in ("continent",) else n + " land"
                if n not in used:
                    used.add(n)
                    return n
        self.ents = {k: [name(k, i) for i in range(v)] for k, v in size.items()}
        E = self.ents
        true = {}
        country_cities = {}
        for c in E["city"]:
            co = rnd.choice(E["country"]); true[(c, "in_country")] = co; country_cities.setdefault(co, []).append(c)
        for co in E["country"]:
            true[(co, "on_continent")] = rnd.choice(E["continent"]); true[(co, "uses_currency")] = rnd.choice(E["currency"])
            true[(co, "has_capital")] = rnd.choice(country_cities.get(co) or E["city"])
        for p in E["person"]:
            true[(p, "born_in")] = rnd.choice(E["city"]); true[(p, "works_as")] = rnd.choice(E["occupation"])
            true[(p, "citizen_of")] = rnd.choice(E["country"])
        for o in E["org"]:
            true[(o, "headquartered_in")] = rnd.choice(E["city"]); true[(o, "founded_by")] = rnd.choice(E["person"])
        for w in E["work"]:
            true[(w, "author")] = rnd.choice(E["person"]); true[(w, "published_by")] = rnd.choice(E["org"])
        self.truth = dict(true)
        self.facts = {}
        objs = {}
        for (s, p), o in true.items():
            objs.setdefault(p, []).append(o)
        for (s, p), o in true.items():
            if rnd.random() < missing:
                continue                                        # the true fact is not in the store
            self.facts.setdefault((s, p), []).append((o, round(rnd.uniform(0.70, 0.99), 3), "true"))
        for (s, p), o in true.items():
            if rnd.random() < noise:                            # a wrong value at LOW trust (below the gate)
                self.facts.setdefault((s, p), []).append((self._other(rnd, objs[p], o), round(rnd.uniform(0.05, 0.45), 3), "noise"))
            if rnd.random() < adv:                              # a wrong value at HIGH trust: a real contradiction
                self.facts.setdefault((s, p), []).append((self._other(rnd, objs[p], o), round(rnd.uniform(0.55, 0.95), 3), "adv"))
        self.fu = {}                                            # Fact-Unit id -> (s, p, o, trust)
        for (s, p), lst in self.facts.items():
            out = []
            for o, t, k in lst:
                fid = hashlib.sha256(("%s|%s|%s" % (s, p, o)).encode()).hexdigest()[:16]
                self.fu[fid] = (s, p, o, t)
                out.append((o, t, k, fid))
            self.facts[(s, p)] = out
        self.n = sum(len(v) for v in self.facts.values())
        self.by_pred = {}
        for (s, p) in self.facts:
            self.by_pred.setdefault(p, []).append(s)
        self.objs = {p: sorted(set(v)) for p, v in objs.items()}

    def truth_of(self, start, chain):
        """the real-world answer, whether or not the store holds it (used by the learning-over-time study)"""
        s = start
        for p in chain:
            s = self.truth[(s, p)]
        return s

    @staticmethod
    def _other(rnd, pool, o):
        for _ in range(10):
            x = rnd.choice(pool)
            if x != o:
                return x
        return o + " (alt)"

    def expected(self, start, chain):
        """what a perfect, honest reader of THIS store must say: (verdict, answer)"""
        s = start
        for p in chain:
            usable = [f for f in self.facts.get((s, p), []) if f[1] >= 0.5]
            if not usable:
                return "UNKNOWN", None
            if len({f[0] for f in usable}) > 1:
                return "CONTRADICTED", None
            s = usable[0][0]
        return "VERIFIED", s

    def questions(self, n, seed, depths=(1, 2, 3, 4)):
        rnd = random.Random(seed)
        out = []
        for i in range(n):
            d = depths[i % len(depths)]
            chain = rnd.choice(CHAINS[d])
            start = rnd.choice(self.ents[START[chain[0]]])
            text = "What is the " + " of the ".join(PRED_TEXT[p] for p in reversed(chain)) + " of " + start + "?"
            v, a = self.expected(start, chain)
            out.append({"id": i, "start": start, "chain": chain, "depth": d, "text": text, "exp": v, "ans": a})
        return out


# ---------------------------------------------------------------------------------------------- engine A: the prototype's own pipeline
class CurrentQueryBook:
    def __init__(self, world, qb_chat, ufcs_store, folder, log=print):
        self.qc, self.us, self.w = qb_chat, ufcs_store, world
        key = "store-%d-%d-%g-%g-%g" % (world.n, world.seed, world.noise, world.adv, world.missing)
        self.path = os.path.join(folder, key)
        t0 = time.time()
        if not os.path.exists(os.path.join(self.path, "ready")):
            shutil.rmtree(self.path, ignore_errors=True)
            st = ufcs_store.UFCSStore(self.path)
            k = 0
            for (s, p), lst in world.facts.items():
                for o, t, kind, fid in lst:
                    st.add(ufcs_store.make_packet(s, p, o, domain="sim", trust=t))
                    k += 1
                    if k % 200_000 == 0:
                        log("    store: %s of %s facts written" % (format(k, ","), format(world.n, ",")))
            st.flush(); st.close()
            open(os.path.join(self.path, "ready"), "w").close()
        self.build_s = time.time() - t0
        self.local = threading.local()

    def st(self):
        if not hasattr(self.local, "st"):
            self.local.st = self.us.UFCSStore(self.path)
        return self.local.st

    def _hop(self, subject, predicate, cost):
        facts, _ = self.qc.retrieve(self.st(), [{"subject": subject, "predicate": predicate, "trust_min": 0.5}], 8)
        cost["lookups"] += 1
        cost["bytes"] += sum(len(json.dumps(f)) for f in facts)          # what the stages hand each other
        verdict, gated = self.qc.gate(facts, 0.5)
        hits = [f for f in gated if f["predicate"] == predicate and f["subject"] == self.us._norm(subject)]
        return verdict, hits

    def answer_planned(self, q, chained):
        cost = {"lookups": 0, "messages": 0, "bytes": 0, "agents": 0, "comm_ms": 0.0}
        s = q["start"]
        chain = q["chain"] if chained else q["chain"][:1]
        for i, p in enumerate(chain):
            verdict, hits = self._hop(s, p, cost)
            if verdict == "CONTRADICTED" and len({h["object"].lower() for h in hits}) > 1:
                return "CONTRADICTED", None, cost
            if not hits:
                return "UNKNOWN", None, cost
            s = hits[0]["object"]
        if not chained and len(q["chain"]) > 1:
            return "NO ANSWER", None, cost                               # it lists facts about the first step only
        return "VERIFIED", s, cost

    def answer_words(self, q):
        """the installed path: qb_chat.answer() from the question's words, deterministic (no AI model)"""
        cost = {"lookups": 1, "messages": 0, "bytes": 0, "agents": 0, "comm_ms": 0.0}
        r = self.qc.answer(self.st(), q["text"], 0.5)
        cites = r.get("citations") or []
        cost["bytes"] += len(json.dumps(cites))
        last = q["chain"][-1]
        subj = self.us._norm(q["start"])
        vals = {c["object"] for c in cites if c["predicate"] == last and (len(q["chain"]) > 1 or c["subject"] == subj)}
        if r["verdict"] == "UNKNOWN":
            return "UNKNOWN", None, cost
        if r["verdict"] == "CONTRADICTED" and len(vals) > 1:
            return "CONTRADICTED", None, cost
        if len(q["chain"]) == 1 and vals:
            return "VERIFIED", sorted(vals)[0], cost
        return "NO ANSWER", None, cost


# ---------------------------------------------------------------------------------------------- the agents (shared by B and C)
LAT_MS, BW, TIMEOUT_MS, SLOW_MS = 0.5, 100e6, 250.0, 50.0


def msg_ms(nbytes):
    return LAT_MS + nbytes / BW * 1000.0


class AgentPool:
    """one agent per (predicate, shard, replica): replicas hold the same facts. Faulty agents: liar / dead / slow."""

    def __init__(self, world, shards=8, replicas=3, liar=0.0, dead=0.0, slow=0.0, seed=7, biased=0.0):
        self.w, self.S, self.R = world, shards, replicas
        self.preds = sorted({p for (_, p) in world.facts})
        self.ids = [(p, s, r) for p in self.preds for s in range(shards) for r in range(replicas)]
        self.seed = seed
        self.moved = {}                       # (predicate, declared shard) -> the shard whose agents really hold those facts
        self.set_faults(liar, dead, slow, seed, biased)

    def set_faults(self, liar, dead, slow, seed, biased=0.0):
        """liar: invents a fact (caught when its FU id is resolved) · dead · slow · biased: reports only the wrong,
        high-trust value when the store holds one (its FU ids resolve correctly, so resolution cannot catch it)"""
        rnd = random.Random(seed)
        self.fault = {}
        for a in self.ids:
            x = rnd.random()
            self.fault[a] = ("liar" if x < liar else "dead" if x < liar + dead else "slow" if x < liar + dead + slow
                             else "biased" if x < liar + dead + slow + biased else "ok")
        self.n_dead = sum(1 for v in self.fault.values() if v == "dead")
        self.n_slow = sum(1 for v in self.fault.values() if v == "slow")

    def shard(self, subject):
        return int(hashlib.md5(subject.encode()).hexdigest()[:8], 16) % self.S

    def holds(self, agent, subject):
        return self.shard(subject) == agent[1]

    def misplace(self, share, seed):
        """re-sharding nobody told the network about: for `share` of the (predicate, shard) areas, the facts now live with
        the agents of another shard, so the subscriptions (dendrites) point at agents that no longer hold them"""
        rnd = random.Random(seed)
        self.moved = {}
        for p in self.preds:
            for k in range(self.S):
                if rnd.random() < share:
                    self.moved[(p, k)] = (k + 1 + rnd.randrange(self.S - 1)) % self.S

    def home(self, predicate, subject):
        k = self.shard(subject)
        return self.moved.get((predicate, k), k)

    def reply(self, agent, subject, predicate, rnd):
        """the facts this agent reports for (subject, predicate): [(o, claimed_trust, fuid)] — None if dead"""
        f = self.fault[agent]
        if f == "dead":
            return None
        facts = [(o, t, fid) for o, t, k, fid in self.w.facts.get((subject, predicate), [])]
        if f == "liar":                       # claims a wrong value, confidently: a real fact of ANOTHER subject
            pool = self.w.by_pred.get(predicate) or []
            other = pool[rnd.randrange(len(pool))] if pool else subject
            lie = self.w.facts.get((other, predicate)) or [("nothing", 0.9, "k", "0" * 16)]
            o, _t, _k, fid = lie[0]
            return [(o, 0.95, fid)]
        if self.moved and agent[1] != self.home(predicate, subject):
            return []                         # an honest agent that does not hold this area (any more)
        if f == "biased":
            adv = [(o, t, fid) for o, t, k, fid in self.w.facts.get((subject, predicate), []) if k == "adv"]
            if adv:
                return adv
        return facts


# ---------------------------------------------------------------------------------------------- engine B: conventional multi-agent (broadcast, text)
class Broadcast:
    def __init__(self, pool):
        self.p = pool

    def answer(self, q, rnd):
        cost = {"lookups": 0, "messages": 0, "bytes": 0, "agents": 0, "comm_ms": 0.0}
        s = q["start"]
        nA = len(self.p.ids)
        for p in q["chain"]:
            ask = "Agent, what do you know about '%s' regarding %s? List every fact with its trust and source." % (s, p)
            claims = []
            hop_ms = msg_ms(len(ask))
            for a in self.p.ids:                                  # only holders of this predicate+subject can say anything
                if a[0] != p or not self.p.holds(a, s):
                    continue
                r = self.p.reply(a, s, p, rnd)
                if r is None:
                    continue
                txt = "I found %d fact(s): " % len(r) + "; ".join("%s %s %s (trust %.2f, source SRC-GEN, fu %s)" % (s, p, o, t, fid) for o, t, fid in r)
                cost["bytes"] += len(txt); hop_ms = max(hop_ms, msg_ms(len(txt)))
                claims += [(o, t) for o, t, fid in r]
            others = nA - sum(1 for a in self.p.ids if a[0] == p and self.p.holds(a, s))
            cost["bytes"] += len(ask) * nA + others * len("I have no facts about that.")
            cost["messages"] += 2 * nA - self.p.n_dead
            cost["agents"] += nA
            if self.p.n_dead:
                hop_ms = max(hop_ms, TIMEOUT_MS)                  # waits for every agent: one dead agent = a timeout
            elif self.p.n_slow:
                hop_ms += SLOW_MS
            cost["comm_ms"] += hop_ms
            usable = [c for c in claims if c[1] >= 0.5]
            if not usable:
                return "UNKNOWN", None, cost
            if len({c[0] for c in usable}) > 1:
                return "CONTRADICTED", None, cost
            s = usable[0][0]
        return "VERIFIED", s, cost


# ---------------------------------------------------------------------------------------------- engine C: the Digital Synaptic Network
class Synapse:
    __slots__ = ("strength", "evidence", "inhibitions", "silences", "last", "purpose")

    def __init__(self, purpose):
        self.strength, self.evidence, self.inhibitions, self.silences, self.last, self.purpose = 0.5, 0, 0, 0, 0, purpose

    def record(self):
        return {"strength": round(self.strength, 3), "evidence": self.evidence, "inhibitions": self.inhibitions,
                "silences": self.silences, "last_reinforced": self.last, "purpose": self.purpose}


class DSN:
    """Sparse, verifiable signalling. A query enters as an event; only agents whose receptive field (dendrites) covers
    (predicate, the subject's shard) can be activated; among those, synapses from the sending assembly decide who fires
    (strongest first, threshold THETA) and the network stops as soon as a verified answer exists. Messages are 12-byte
    Fact-Unit references; the receiver resolves each FU id in the shared UFCS graph — a reference that does not resolve
    to the subject and predicate asked about is inhibitory (it weakens that synapse). Learning: verified help
    strengthens, a lie or silence weakens; weak synapses drift back slowly and are re-tested now and then."""
    THETA, ETA, INHIB, SILENCE, DRIFT, EXPLORE = 0.30, 0.10, 0.50, 0.15, 0.002, 0.02
    EVENT_B, FU_B = 12, 12

    def __init__(self, pool, learn=True, poison=0.0, seed=11):
        self.p, self.learn, self.poison = pool, learn, poison
        self.syn = {}
        self.lock = threading.Lock()
        self.rnd = random.Random(seed)
        self.t = 0

    def _s(self, src, dst):
        k = (src, dst)
        s = self.syn.get(k)
        if s is None:
            with self.lock:
                s = self.syn.setdefault(k, Synapse("%s -> %s" % (src, dst[0])))
        return s

    def _adjust(self, syn, good, kind=None):
        if not self.learn:
            return
        if self.poison and self.rnd.random() < self.poison:
            good = not good                                         # poisoned feedback
        if good:
            syn.strength += self.ETA * (1 - syn.strength); syn.evidence += 1; syn.last = self.t
        elif kind == "silence":
            syn.strength -= self.SILENCE * syn.strength; syn.silences += 1
        else:
            syn.strength -= self.INHIB * syn.strength; syn.inhibitions += 1

    def answer(self, q, rnd):
        cost = {"lookups": 0, "messages": 0, "bytes": 0, "agents": 0, "comm_ms": 0.0}
        self.t += 1
        src, s = "router", q["start"]
        for p in q["chain"]:
            field = [a for a in self.p.ids if a[0] == p and a[1] == self.p.shard(s)]     # dendrites: only these can hear it
            syns = sorted(((self._s(src, a), a) for a in field), key=lambda x: -x[0].strength)
            if self.learn:
                for sy, _ in syns:                                   # weak synapses recover slowly (re-sensitisation)
                    sy.strength += self.DRIFT * (0.5 - sy.strength) if sy.strength < 0.5 else 0
            order = [x for x in syns if x[0].strength >= self.THETA or (self.learn and rnd.random() < self.EXPLORE)]
            order += [x for x in syns if x not in order]             # below threshold: only if all above fail
            got, conflict, used = None, False, None
            for sy, a in order:
                cost["messages"] += 1; cost["bytes"] += self.EVENT_B; cost["agents"] += 1
                r = self.p.reply(a, s, p, rnd)
                if r is None:                                        # silence: a timeout, then the next one
                    cost["comm_ms"] += TIMEOUT_MS
                    self._adjust(sy, False, "silence")
                    continue
                cost["messages"] += 1; cost["bytes"] += self.FU_B * max(1, len(r))
                cost["comm_ms"] += msg_ms(self.EVENT_B) + msg_ms(self.FU_B * max(1, len(r))) + (SLOW_MS if self.p.fault[a] == "slow" else 0)
                resolved, bad = [], False
                for o, claimed, fid in r:                            # resolve every reference in the shared graph
                    cost["lookups"] += 1
                    f = self.p.w.fu.get(fid)
                    if not f or f[0] != s or f[1] != p:
                        bad = True                                   # it does not say what it claims: inhibition
                        continue
                    resolved.append(f)
                if bad and not resolved:
                    self._adjust(sy, False)
                    continue
                usable = [f for f in resolved if f[3] >= 0.5]        # the graph's trust, never the claimed one
                if not usable:
                    got = "UNKNOWN"; used = (sy, a)
                    if sy.strength >= self.THETA:
                        break                                        # a trusted agent says: not known
                    continue
                if len({f[2] for f in usable}) > 1:
                    conflict = True; used = (sy, a); break
                got = usable[0][2]; used = (sy, a)
                break
            if conflict:
                if used:
                    self._adjust(used[0], True)                      # it reported honestly: the conflict is in the facts
                return "CONTRADICTED", None, cost
            if got in (None, "UNKNOWN"):
                return "UNKNOWN", None, cost
            self._adjust(used[0], True)
            src, s = p, got                                          # the answering assembly sends the next event
        return "VERIFIED", s, cost

    def audit(self, top=5):
        rows = sorted(self.syn.values(), key=lambda x: x.strength)
        return {"synapses": len(rows), "weakest": [r.record() for r in rows[:top]], "strongest": [r.record() for r in rows[-top:]]}


# ---------------------------------------------------------------------------------------------- running and scoring
def score(q, verdict, ans):
    exp = q["exp"]
    if verdict == exp and (exp != "VERIFIED" or ans == q["ans"]):
        return "correct"
    if verdict == "VERIFIED":
        return "wrong answer"                     # stated something false, or answered what is not known
    if verdict == "CONTRADICTED":
        return "false alarm"                      # saw a conflict that is not in the store (a lying agent)
    if exp == "CONTRADICTED":
        return "missed conflict"
    return "no answer"                            # declined, or could not get there


def run_engine(name, fn, qs, threads=1, shift_at=None, on_shift=None):
    res = [None] * len(qs)
    t0 = time.perf_counter()

    def one(i):
        rnd = random.Random(1000 + i)
        t = time.perf_counter()
        v, a, c = fn(qs[i], rnd)
        c["wall_ms"] = (time.perf_counter() - t) * 1000
        res[i] = (score(qs[i], v, a), c)
    if shift_at:
        for i in range(shift_at):
            one(i)
        on_shift()
        rest = range(shift_at, len(qs))
    else:
        rest = range(len(qs))
    if threads > 1:
        with ThreadPoolExecutor(threads) as ex:
            list(ex.map(one, rest))
    else:
        for i in rest:
            one(i)
    wall = time.perf_counter() - t0
    return summarise(name, qs, res, wall, shift_at)


def pct(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def summarise(name, qs, res, wall, shift_at=None):
    n = len(res)
    out = {"engine": name, "questions": n}
    for k in ("correct", "wrong answer", "no answer", "missed conflict", "false alarm"):
        out[k] = round(100.0 * sum(1 for r in res if r[0] == k) / n, 1)
    for k in ("messages", "bytes", "agents", "lookups"):
        out[k] = round(sum(r[1][k] for r in res) / n, 1)
    tot = [r[1]["wall_ms"] + r[1]["comm_ms"] for r in res]
    out.update(wall_ms=round(statistics.mean(r[1]["wall_ms"] for r in res), 3), comm_ms=round(statistics.mean(r[1]["comm_ms"] for r in res), 2),
               p50_ms=round(pct(tot, 0.5), 2), p99_ms=round(pct(tot, 0.99), 2), qps_compute=round(n / max(wall, 1e-9), 1))
    out["by_depth"] = {d: round(100.0 * sum(1 for q, r in zip(qs, res) if q["depth"] == d and r[0] == "correct") /
                                max(1, sum(1 for q in qs if q["depth"] == d)), 1) for d in (1, 2, 3, 4)}
    tenth = max(1, n // 10)
    out["curve"] = [round(100.0 * sum(1 for r in res[i:i + tenth] if r[0] == "correct") / len(res[i:i + tenth]), 1) for i in range(0, n, tenth)][:10]
    out["curve_msgs"] = [round(sum(r[1]["messages"] for r in res[i:i + tenth]) / len(res[i:i + tenth]), 1) for i in range(0, n, tenth)][:10]
    if shift_at:
        after = res[shift_at:shift_at + max(1, n // 20)]
        out["just_after_shift"] = round(100.0 * sum(1 for r in after if r[0] == "correct") / len(after), 1)
    return out


SCENARIOS = {
    # name: world, agents, faults, learning stress, load
    "S0 clean":                  dict(),
    "S1 bad knowledge":          dict(noise=0.5, adv=0.10, missing=0.15),
    "S2 faulty agents":          dict(liar=0.20, dead=0.10, slow=0.10),
    "S3 extreme faulty agents":  dict(liar=0.40, dead=0.20, slow=0.10),
    "S4 many agents (x10)":      dict(liar=0.20, dead=0.10, shards_x=10),
    "S5 poisoned learning":      dict(liar=0.20, dead=0.10, poison=0.30),
    "S6 faults change mid-run":  dict(liar=0.20, dead=0.10, shift=True),
    "S7 parallel load":          dict(liar=0.20, dead=0.10, threads=32),
    "S8 EVERYTHING AT ONCE":     dict(noise=0.5, adv=0.10, missing=0.15, liar=0.40, dead=0.20, slow=0.10, shards_x=40,
                                      poison=0.30, shift=True, threads=32),
}
PRESETS = {
    "quick":   dict(facts=20_000, queries=600, shards=8, replicas=3, scenarios=["S0 clean", "S1 bad knowledge", "S2 faulty agents", "S8 EVERYTHING AT ONCE"], scale=[]),
    "stress":  dict(facts=200_000, queries=3000, shards=8, replicas=3, scenarios=list(SCENARIOS), scale=[20_000, 200_000]),
    "extreme": dict(facts=1_000_000, queries=10_000, shards=8, replicas=3, scenarios=list(SCENARIOS), scale=[20_000, 200_000, 1_000_000]),
}


_A_CACHE = {}


def scenario(name, cfg, base, qbmods, folder, log):
    c = SCENARIOS[name]
    log("\n== %s" % name)
    t0 = time.time()
    w = World(cfg.get("facts_override") or base["facts"], seed=base["seed"], noise=c.get("noise", 0), adv=c.get("adv", 0), missing=c.get("missing", 0))
    qs = w.questions(base["queries"], base["seed"] + 1)
    shards = base["shards"] * c.get("shards_x", 1)
    pool = AgentPool(w, shards, base["replicas"], c.get("liar", 0), c.get("dead", 0), c.get("slow", 0), seed=base["seed"] + 2)
    log("   world: %s facts · %s agents · built in %.1f s" % (format(w.n, ","), format(len(pool.ids), ","), time.time() - t0))
    threads = base.get("threads") or c.get("threads", 1)
    shift_at = len(qs) // 2 if c.get("shift") else None
    on_shift = (lambda: pool.set_faults(c.get("liar", 0), c.get("dead", 0), c.get("slow", 0), base["seed"] + 99)) if shift_at else None
    rows = []
    akey = (w.n, w.seed, w.noise, w.adv, w.missing, len(qs), threads)
    if qbmods and akey in _A_CACHE:                       # A0-A2 use no agents: agent faults cannot change their results
        rows += [dict(r, engine=r["engine"] + " (same world: reused)") for r in _A_CACHE[akey]]
    elif qbmods:
        cur = CurrentQueryBook(w, qbmods[0], qbmods[1], folder, log)
        log("   current-QueryBook store ready (%.1f s)" % cur.build_s)
        n_words = min(len(qs), 400 if w.n <= 50_000 else 120 if w.n <= 500_000 else 60)   # the word path scans the whole
                                                                                         # store (LIKE): slow by design
        rows.append(run_engine("A0 current, keywords only", lambda q, r: cur.answer_words(q), qs[:n_words], 1))
        rows.append(run_engine("A1 current, planned first hop", lambda q, r: cur.answer_planned(q, False), qs, threads))
        rows.append(run_engine("A2 current pipeline, chained (control)", lambda q, r: cur.answer_planned(q, True), qs, threads))
        _A_CACHE[akey] = [dict(r) for r in rows]
    nq_b = len(qs) if len(pool.ids) <= 3000 else min(len(qs), 1500)
    b = Broadcast(pool)
    rows.append(run_engine("B multi-agent broadcast (text)", b.answer, qs[:nq_b], threads,
                           shift_at if shift_at and shift_at < nq_b else None, on_shift))
    pool.set_faults(c.get("liar", 0), c.get("dead", 0), c.get("slow", 0), base["seed"] + 2)
    c0 = DSN(pool, learn=False)
    rows.append(run_engine("C0 DSN, no learning", c0.answer, qs, threads, shift_at, on_shift))
    pool.set_faults(c.get("liar", 0), c.get("dead", 0), c.get("slow", 0), base["seed"] + 2)
    dsn = DSN(pool, learn=True, poison=c.get("poison", 0))
    rows.append(run_engine("C DSN, learning", dsn.answer, qs, threads, shift_at, on_shift))
    for r in rows:
        log("   %-40s correct %5.1f%%  wrong %5.1f%%  no-answer %5.1f%%  msgs %8.1f  bytes %10.1f  p99 %7.1f ms" %
            (r["engine"], r["correct"], r["wrong answer"], r["no answer"], r["messages"], r["bytes"], r["p99_ms"]))
    exp = {k: round(100.0 * sum(1 for q in qs if q["exp"] == k) / len(qs), 1) for k in ("VERIFIED", "UNKNOWN", "CONTRADICTED")}
    return {"scenario": name, "stress": c, "facts": w.n, "agents": len(pool.ids), "threads": threads, "expected_mix": exp,
            "results": rows, "dsn_audit": dsn.audit()}


def scale_runs(base, qbmods, folder, log):
    out = []
    for n in base["scale"]:
        log("\n== scale: %s facts" % format(n, ","))
        r = scenario("S2 faulty agents", {"facts_override": n}, dict(base, queries=min(base["queries"], 2000)), qbmods, folder, log)
        r["scenario"] = "Scale %s facts" % format(r["facts"], ",")
        out.append(r)
    return out


# ---------------------------------------------------------------------------------------------- learning over time
VERIFY_MS, VERIFY_B, VERIFY_ACC = 300.0, 200, 0.97


def new_cost():
    return {"lookups": 0, "messages": 0, "bytes": 0, "agents": 0, "comm_ms": 0.0, "verifies": 0}


class Verifier:
    """an outside check: a harvest from the original source, a document, a person. Slow (300 ms) and right 97% of the
    time, so nothing is learned from a single check"""

    def __init__(self, world, seed):
        self.w, self.rnd = world, random.Random(seed)

    def check(self, s, p):
        t = self.w.truth.get((s, p))
        if t is None or self.rnd.random() < VERIFY_ACC:
            return t
        return World._other(self.rnd, self.w.objs[p], t)


class FactLearner:
    """new verified knowledge written back to the shared graph: a fact is learned after two outside checks agree.
    An audit that finds a store Fact Unit wrong marks it, and readers skip it from then on."""
    NEED = 2

    def __init__(self, verifier):
        self.v, self.known, self.pending, self.bad_fu = verifier, {}, {}, set()

    def get(self, s, p):
        return self.known.get((s, p))

    def check(self, s, p, cost):
        """one outside check: (what the check said, the confirmed value or None)"""
        cost["messages"] += 2; cost["bytes"] += 12 + VERIFY_B; cost["comm_ms"] += VERIFY_MS; cost["verifies"] += 1
        raw = self.v.check(s, p)
        if raw is None:
            return None, None
        pv, n = self.pending.get((s, p), (None, 0))
        n = n + 1 if pv == raw else 1
        if n >= self.NEED:
            self.known[(s, p)] = raw
            self.pending.pop((s, p), None)
            return raw, raw
        self.pending[(s, p)] = (raw, n)
        return raw, None


class CentralReader:
    """the chained central pipeline (A2's logic) reading the store directly; optionally with the same fact learning and
    audits the upgraded DSN gets, so the comparison stays fair"""
    AUDIT = 0.05

    def __init__(self, world, learner=None, seed=13):
        self.w, self.L, self.rnd = world, learner, random.Random(seed)

    def answer(self, q, rnd):
        cost = new_cost()
        s = q["start"]
        for p in q["chain"]:
            cost["lookups"] += 1
            if self.L:
                k = self.L.get(s, p)
                if k is not None:
                    s = k
                    continue
            usable = [f for f in self.w.facts.get((s, p), []) if f[1] >= 0.5 and not (self.L and f[3] in self.L.bad_fu)]
            vals = {f[0] for f in usable}
            if len(vals) == 1:
                if self.L and self.rnd.random() < self.AUDIT:
                    raw, conf = self.L.check(s, p, cost)
                    if raw is not None and raw != usable[0][0] and conf is None:
                        raw, conf = self.L.check(s, p, cost)        # never mark a fact on a single check
                    if conf is not None and conf != usable[0][0]:
                        self.L.bad_fu.add(usable[0][3])
                        s = conf
                        continue
                s = usable[0][0]
                continue
            if self.L:
                raw, conf = self.L.check(s, p, cost)
                if conf is not None:
                    s = conf
                    continue
            return ("CONTRADICTED" if vals else "UNKNOWN"), None, cost
        return "VERIFIED", s, cost


class DSNPlus(DSN):
    """the DSN with the three upgrades, each switchable:
    facts  — agents learn: new verified facts written back to the graph, and combined facts (shortcuts) for chains the
             network keeps answering
    paths  — new pathways: when the subscribed agents know nothing, probe the same predicate's other agents once and
             form a lasting pathway to the ones that answer (and drop it when it stops working)
    audit  — feedback on accuracy, not just usefulness: a sample of answers is checked from outside; an agent caught
             withholding the true value is inhibited on every synapse into it, and that signal cannot be poisoned"""
    AUDIT, SHORTCUT_AFTER = 0.05, 3

    def __init__(self, pool, learn=True, poison=0.0, seed=11, facts=False, paths=False, audit=False, verifier=None):
        super().__init__(pool, learn=learn, poison=poison, seed=seed)
        self.facts, self.paths, self.audit_on = facts, paths, audit
        self.L = FactLearner(verifier) if (facts or audit) else None
        self.route, self.probe_fail, self.chains, self.shortcuts, self.by_dst = {}, {}, {}, {}, {}
        self.arnd = random.Random(seed + 5)

    def _s(self, src, dst):
        k = (src, dst)
        s = self.syn.get(k)
        if s is None:
            with self.lock:
                s = self.syn.setdefault(k, Synapse("%s -> %s" % (src, dst[0])))
                self.by_dst.setdefault(dst, []).append(s)
        return s

    def _adjust(self, syn, good, kind=None, trusted=False):
        if not self.learn:
            return
        if self.poison and not trusted and self.rnd.random() < self.poison:
            good = not good
        if good:
            syn.strength += self.ETA * (1 - syn.strength); syn.evidence += 1; syn.last = self.t
        elif kind == "silence":
            syn.strength -= self.SILENCE * syn.strength; syn.silences += 1
        else:
            syn.strength -= self.INHIB * syn.strength; syn.inhibitions += 1

    def _ask(self, a, s, p, rnd, cost):
        cost["messages"] += 1; cost["bytes"] += self.EVENT_B; cost["agents"] += 1
        r = self.p.reply(a, s, p, rnd)
        if r is None:
            return "dead", [], TIMEOUT_MS
        cost["messages"] += 1; cost["bytes"] += self.FU_B * max(1, len(r))
        ms = msg_ms(self.EVENT_B) + msg_ms(self.FU_B * max(1, len(r))) + (SLOW_MS if self.p.fault[a] == "slow" else 0)
        bad_fu = self.L.bad_fu if self.L else ()
        resolved, bad = [], False
        for o, claimed, fid in r:
            cost["lookups"] += 1
            f = self.p.w.fu.get(fid)
            if not f or f[0] != s or f[1] != p:
                bad = True
                continue
            if fid not in bad_fu and f[3] >= 0.5:
                resolved.append((f[2], fid))
        return ("lie" if bad and not resolved else "ok"), resolved, ms

    def _hop(self, src, s, p, rnd, cost):
        """(verdict, value, fid, agent) for one step, from the agents subscribed to this area (or a learned pathway)"""
        k = self.p.shard(s)
        home = self.route.get((p, k), k) if self.paths else k
        field = [a for a in self.p.ids if a[0] == p and a[1] == home]
        syns = sorted(((self._s(src, a), a) for a in field), key=lambda x: -x[0].strength)
        if self.learn:
            for sy, _ in syns:
                sy.strength += self.DRIFT * (0.5 - sy.strength) if sy.strength < 0.5 else 0
        order = [x for x in syns if x[0].strength >= self.THETA or (self.learn and rnd.random() < self.EXPLORE)]
        order += [x for x in syns if x not in order]
        verdict, used = "UNKNOWN", None
        for sy, a in order:
            st, res, ms = self._ask(a, s, p, rnd, cost)
            cost["comm_ms"] += ms
            if st == "dead":
                self._adjust(sy, False, "silence")
                continue
            if st == "lie":
                self._adjust(sy, False)
                continue
            if not res:
                used = (sy, a)
                if sy.strength >= self.THETA:
                    break
                continue
            if len({v for v, _ in res}) > 1:
                self._adjust(sy, True)
                return "CONTRADICTED", None, None, a
            self._adjust(sy, True)
            return "VERIFIED", res[0][0], res[0][1], a
        if self.paths and home != k and used is not None:
            self.route.pop((p, k), None)                                # the learned pathway stopped working
        return verdict, None, None, None

    def _probe(self, src, s, p, rnd, cost):
        """a new pathway: ask one agent of every other shard for this predicate, in parallel; keep the one that knows"""
        k = self.p.shard(s)
        n = self.probe_fail.get((p, k), 0)
        if self.arnd.random() > max(0.1, 1.0 / (1 + n)):
            return None
        home = self.route.get((p, k), k)
        wave, found = 0.0, None
        for k2 in range(self.p.S):
            if k2 == home:
                continue
            a = (p, k2, (self.t + k2) % self.p.R)
            st, res, ms = self._ask(a, s, p, rnd, cost)
            wave = max(wave, ms)
            if st == "ok" and res and len({v for v, _ in res}) == 1 and not found:
                found = (k2, res[0][0], res[0][1], a)
        cost["comm_ms"] += wave
        if found:
            self.route[(p, k)] = found[0]
            self.probe_fail.pop((p, k), None)
            self._adjust(self._s(src, found[3]), True)
            return found
        self.probe_fail[(p, k)] = n + 1
        return None

    def _audit_hop(self, s, p, value, fid, agent, cost):
        """check one answered step from outside: (value to use or None, still trusted)"""
        raw, conf = self.L.check(s, p, cost)
        if raw is not None and raw != value and conf is None:
            raw, conf = self.L.check(s, p, cost)            # one check can be wrong: never mark a fact on a single check
        if raw is None or raw == value or conf is None:
            if agent is not None and raw == value:
                self._adjust(self._s("audit", agent), True, trusted=True)
            return value, True
        if fid and not fid.startswith("L|"):
            self.L.bad_fu.add(fid)
            withheld = agent is not None and any(f[0] == raw and f[1] >= 0.5 for f in self.p.w.facts.get((s, p), []))
            if withheld:                                                # the graph holds the value the agent left out
                for sy in self.by_dst.get(agent, []):
                    self._adjust(sy, False, trusted=True)
        return conf, False

    def answer(self, q, rnd):
        cost = new_cost()
        self.t += 1
        chain = q["chain"]
        key = (q["start"], tuple(chain))
        sc = self.shortcuts.get(key) if self.facts else None
        if sc and self._shortcut_valid(sc, chain):
            cost["messages"] += 2; cost["bytes"] += 24; cost["lookups"] += len(chain); cost["comm_ms"] += 2 * msg_ms(12)
            if not (self.audit_on and self.arnd.random() < self.AUDIT):
                return "VERIFIED", sc["ans"], cost
            i = self.arnd.randrange(len(chain))
            v, ok = self._audit_hop(sc["path"][i], chain[i], sc["path"][i + 1], sc["fids"][i], None, cost)
            if ok:
                return "VERIFIED", sc["ans"], cost
            self.shortcuts.pop(key, None)
        src, s, path, fids = "router", q["start"], [q["start"]], []
        for p in chain:
            if self.facts:
                kv = self.L.get(s, p)
                if kv is not None:                                      # learned knowledge, read from the graph
                    cost["messages"] += 2; cost["bytes"] += 24; cost["lookups"] += 1; cost["comm_ms"] += 2 * msg_ms(12)
                    path.append(kv); fids.append("L|%s|%s" % (s, p)); src, s = p, kv
                    continue
            verdict, value, fid, agent = self._hop(src, s, p, rnd, cost)
            if verdict == "UNKNOWN" and self.paths:
                f = self._probe(src, s, p, rnd, cost)
                if f:
                    verdict, value, fid, agent = "VERIFIED", f[1], f[2], f[3]
            if verdict == "VERIFIED" and self.audit_on and self.arnd.random() < self.AUDIT:
                v, ok = self._audit_hop(s, p, value, fid, agent, cost)
                if not ok:
                    verdict, value, fid = ("VERIFIED", v, "L|%s|%s" % (s, p)) if v is not None else ("UNKNOWN", None, None)
            if verdict != "VERIFIED" and self.facts:
                raw, conf = self.L.check(s, p, cost)
                if conf is not None:
                    verdict, value, fid = "VERIFIED", conf, "L|%s|%s" % (s, p)
            if verdict != "VERIFIED":
                return verdict, None, cost
            path.append(value); fids.append(fid); src, s = p, value
        if self.facts and len(chain) > 1:
            prev = self.chains.get(key)
            n = prev["n"] + 1 if prev and prev["ans"] == s else 1
            self.chains[key] = {"ans": s, "n": n, "path": path, "fids": fids}
            if n >= self.SHORTCUT_AFTER and self.audit_on:       # check every step from outside before caching it
                for i, (pp, fid) in enumerate(zip(chain, fids)):
                    if not fid.startswith("L|"):
                        v, ok = self._audit_hop(path[i], pp, path[i + 1], fid, None, cost)
                        if not ok:
                            self.chains.pop(key, None)
                            return self._redo(q, rnd, cost)
            if n >= self.SHORTCUT_AFTER:
                self.shortcuts[key] = self.chains[key]
        return "VERIFIED", s, cost

    def _redo(self, q, rnd, cost):
        """a step failed its check: answer again now that the wrong Fact Unit is marked (costs add up)"""
        v, ans, c2 = self.answer(q, rnd)
        for k in cost:
            cost[k] += c2.get(k, 0)
        return v, ans, cost

    def _shortcut_valid(self, sc, chain):
        for i, fid in enumerate(sc["fids"]):
            if fid.startswith("L|"):
                if self.L.get(sc["path"][i], chain[i]) != sc["path"][i + 1]:
                    return False
            elif fid in self.L.bad_fu:
                return False
        return True

    def state(self):
        return {"synapses": len(self.syn), "learned_facts": len(self.L.known) if self.L else 0,
                "shortcuts": len(self.shortcuts), "pathways": len(self.route), "facts_marked_wrong": len(self.L.bad_fu) if self.L else 0}


def score_truth(q, verdict, ans):
    """scored against the real world, not against the store: learning can only show up this way"""
    if verdict == "VERIFIED":
        return "correct" if ans == q["truth"] else "wrong answer"
    return "no answer"


STUDY = dict(noise=0.5, adv=0.10, missing=0.15, liar=0.15, dead=0.10, slow=0.10, biased=0.15, misplaced=0.15, poison=0.20)
STUDY_SIZE = {"quick": dict(facts=20_000, queries=3000, distinct=1500), "stress": dict(facts=200_000, queries=10_000, distinct=3000),
              "extreme": dict(facts=1_000_000, queries=20_000, distinct=6000), "learning": dict(facts=200_000, queries=10_000, distinct=3000)}
BLOCK = 500


def study_engines(w, pool, seed):
    V = lambda: Verifier(w, seed + 31)
    kw = dict(poison=STUDY["poison"])
    return [
        ("Central pipeline (A2 logic), no learning", CentralReader(w)),
        ("Central pipeline + learns facts and audits", CentralReader(w, FactLearner(V()))),
        ("C0 DSN, no learning", DSNPlus(pool, learn=False)),
        ("C  DSN, learning synapses (today)", DSNPlus(pool, **kw)),
        ("C+1 + agents learn facts", DSNPlus(pool, facts=True, verifier=V(), **kw)),
        ("C+2 + new pathways", DSNPlus(pool, facts=True, paths=True, verifier=V(), **kw)),
        ("C+3 + accuracy feedback (all three)", DSNPlus(pool, facts=True, paths=True, audit=True, verifier=V(), **kw)),
    ]


def learning_study(size, seed, log, block=BLOCK):
    """one long stream of questions, popular ones recurring (as in real use), reported every `block` questions.
    Half-way the faulty agents change; at three quarters the agents' areas are re-sharded again."""
    log("\n== Learning over time: %s questions in blocks of %d" % (format(size["queries"], ","), block))
    t0 = time.time()
    st = STUDY
    w = World(size["facts"], seed=seed, noise=st["noise"], adv=st["adv"], missing=st["missing"])
    base = w.questions(size["distinct"], seed + 1)
    for q in base:
        q["truth"] = w.truth_of(q["start"], q["chain"])
    rnd = random.Random(seed + 3)
    cum, acc = [], 0.0
    for i in range(len(base)):
        acc += 1.0 / (i + 1)
        cum.append(acc)
    qs = [dict(base[j], id=i) for i, j in enumerate(rnd.choices(range(len(base)), cum_weights=cum, k=size["queries"]))]
    n = len(qs)
    shift_at, reshard_at = n // 2, (3 * n) // 4
    pool = AgentPool(w, 8, 3, seed=seed + 2)
    ceiling = round(100.0 * sum(1 for q in qs if w.expected(q["start"], q["chain"]) == ("VERIFIED", q["truth"])) / n, 1)
    log("   world: %s facts · %s agents · %s distinct questions · built in %.1f s · a perfect reader of the store gets %.1f%% right"
        % (format(w.n, ","), format(len(pool.ids), ","), format(len(base), ","), time.time() - t0, ceiling))
    faults = lambda sd: pool.set_faults(st["liar"], st["dead"], st["slow"], sd, st["biased"])
    rows = []
    for name, eng in study_engines(w, pool, seed):
        faults(seed + 2); pool.misplace(st["misplaced"], seed + 4)
        res = []
        t1 = time.time()
        for i, q in enumerate(qs):
            if i == shift_at:
                faults(seed + 99)
            if i == reshard_at:
                pool.misplace(st["misplaced"], seed + 77)
            r = random.Random(1000 + i)
            t = time.perf_counter()
            v, a, c = eng.answer(q, r)
            c["wall_ms"] = (time.perf_counter() - t) * 1000
            res.append((score_truth(q, v, a), c))
        blocks = []
        for b in range(0, n, block):
            part = res[b:b + block]
            m = len(part)
            tot = [x[1]["wall_ms"] + x[1]["comm_ms"] for x in part]
            blocks.append({"from": b + 1, "to": b + m,
                           "correct": round(100.0 * sum(1 for x in part if x[0] == "correct") / m, 1),
                           "wrong": round(100.0 * sum(1 for x in part if x[0] == "wrong answer") / m, 1),
                           "messages": round(sum(x[1]["messages"] for x in part) / m, 1),
                           "verifies": round(sum(x[1].get("verifies", 0) for x in part) / m, 3),
                           "mean_ms": round(statistics.mean(tot), 2), "p99_ms": round(pct(tot, 0.99), 1)})
        row = {"engine": name, "blocks": blocks, "state": eng.state() if hasattr(eng, "state") else {},
               "correct": round(100.0 * sum(1 for x in res if x[0] == "correct") / n, 1),
               "wrong": round(100.0 * sum(1 for x in res if x[0] == "wrong answer") / n, 1)}
        if isinstance(eng, CentralReader) and eng.L:
            row["state"] = {"learned_facts": len(eng.L.known), "facts_marked_wrong": len(eng.L.bad_fu)}
        rows.append(row)
        f, l = blocks[0], blocks[-1]
        log("   %-42s first block %5.1f%% right, %7.1f ms avg · last block %5.1f%% right, %7.1f ms avg · wrong overall %4.1f%% (%.0f s)"
            % (name, f["correct"], f["mean_ms"], l["correct"], l["mean_ms"], row["wrong"], time.time() - t1))
    return {"questions": n, "block": block, "distinct": len(base), "facts": w.n, "agents": len(pool.ids), "stress": st,
            "ceiling": ceiling, "events": {"faults change": shift_at + 1, "areas re-sharded": reshard_at + 1}, "engines": rows,
            "verify": {"ms": VERIFY_MS, "accuracy": VERIFY_ACC}}


def study_md(S):
    nb = len(S["engines"][0]["blocks"])
    g = max(1, -(-nb // 10))                                   # at most 10 columns: merge neighbouring blocks
    cols = [list(range(i, min(nb, i + g))) for i in range(0, nb, g)]
    ev = S["events"]

    def head():
        h = []
        for c in cols:
            a, b = S["engines"][0]["blocks"][c[0]]["from"], S["engines"][0]["blocks"][c[-1]]["to"]
            mark = ("F" if a <= ev["faults change"] <= b else "") + ("R" if a <= ev["areas re-sharded"] <= b else "")
            h.append("%s–%s%s" % (format(a, ","), format(b, ","), (" " + mark) if mark else ""))
        return "| Engine | " + " | ".join(h) + " |\n|---|" + "---|" * len(cols)

    def table(key, fmt):
        L = [head()]
        for e in S["engines"]:
            vals = []
            for c in cols:
                xs = [e["blocks"][i][key] for i in c]
                vals.append(fmt % (max(xs) if key == "p99_ms" else sum(xs) / len(xs)))
            L.append("| %s | %s |" % (e["engine"], " | ".join(vals)))
        return "\n".join(L)
    E = {e["engine"]: e for e in S["engines"]}
    def last(e, k):
        return e["blocks"][-1][k]
    def first(e, k):
        return e["blocks"][0][k]
    find = lambda pre: next(e for e in S["engines"] if e["engine"].startswith(pre))
    c, c3, c0, cen, cenl = find("C  "), find("C+3"), find("C0"), find("Central pipeline (A2"), find("Central pipeline +")
    L = ["## Learning over time", "",
         "One long stream of %s questions drawn from %s distinct ones, popular questions recurring as in real use, reported every %d "
         "questions. Scored against the **real world**, not the store, so learning new facts can show up. World: %s facts with bad "
         "knowledge (wrong, missing and contradicted facts) · %s agents, of them liars, dead, slow and **biased** agents (they report "
         "only the wrong high-trust value, and pass the Fact-Unit check) · %d%% of agent areas **re-sharded** without telling the "
         "network · %d%% of learning feedback poisoned. **F** = the faulty agents change; **R** = the areas are re-sharded again. "
         "The outside check used for learning and audits takes %d ms and is right %d%% of the time."
         % (format(S["questions"], ","), format(S["distinct"], ","), S["block"], format(S["facts"], ","), format(S["agents"], ","),
            int(S["stress"]["misplaced"] * 100), int(S["stress"]["poison"] * 100), S["verify"]["ms"], int(S["verify"]["accuracy"] * 100)), "",
         "A perfect reader of the store, with no learning, gets **%.1f%%** right: that is the ceiling for anything that only routes better." % S["ceiling"], "",
         "**Read this first**", "",
         "- Today's DSN (C): %.1f%% right in the first block, %.1f%% in the last; average time %.1f → %.1f ms. Learning synapses only "
         "(no learning: C0 %.1f%% → %.1f%%)." % (first(c, "correct"), last(c, "correct"), first(c, "mean_ms"), last(c, "mean_ms"),
                                                 first(c0, "correct"), last(c0, "correct")),
         "- With all three upgrades (C+3): %.1f%% → %.1f%% right, average time %.1f → %.1f ms, wrong answers %.1f%% overall (C: %.1f%%)."
         % (first(c3, "correct"), last(c3, "correct"), first(c3, "mean_ms"), last(c3, "mean_ms"), c3["wrong"], c["wrong"]),
         "- The central pipeline given the same fact learning: %.1f%% → %.1f%% right, average time %.1f → %.1f ms (without it: %.1f%% flat)."
         % (first(cenl, "correct"), last(cenl, "correct"), first(cenl, "mean_ms"), last(cenl, "mean_ms"), cen["correct"]),
         "- Learning without accuracy checks caches mistakes: wrong answers overall C %.1f%% · C+1 %.1f%% · C+2 %.1f%% · C+3 %.1f%%. "
         "A wrong fact turned into a shortcut is repeated every time a popular question comes back."
         % (c["wrong"], find("C+1")["wrong"], find("C+2")["wrong"], c3["wrong"]), "",
         "### Correct answers (% of questions)", "", table("correct", "%.1f"), "",
         "### Wrong answers (% of questions)", "", table("wrong", "%.1f"), "",
         "### Average time per question (ms, compute + modelled communication + outside checks)", "", table("mean_ms", "%.1f"), "",
         "### Worst 1% time per question (ms)", "", table("p99_ms", "%.0f"), "",
         "### Messages per question", "", table("messages", "%.1f"), "",
         "### What each engine had built by the end", "",
         "| Engine | Correct overall | Wrong overall | Learned facts | Shortcuts | Pathways | Fact Units found wrong | Synapses |", "|---|---|---|---|---|---|---|---|"]
    for e in S["engines"]:
        s = e["state"]
        L.append("| %s | %.1f%% | %.1f%% | %s | %s | %s | %s | %s |" % (e["engine"], e["correct"], e["wrong"], s.get("learned_facts", "–"),
                 s.get("shortcuts", "–"), s.get("pathways", "–"), s.get("facts_marked_wrong", "–"), s.get("synapses", "–")))
    L += ["", "Upgrades: **C+1** agents learn — a fact the store lacks or contradicts is checked from outside and learned once two "
          "checks agree; chains answered the same way 3 times become one-step shortcuts. **C+2** adds new pathways — when the "
          "subscribed agents know nothing, one agent per other shard is asked once and a lasting pathway forms to the one that "
          "knows (dropped when it stops working). **C+3** adds feedback on accuracy — 5% of answers are checked from outside, and "
          "every step of a chain is checked before it becomes a shortcut; a wrong Fact Unit is marked, and an agent caught withholding the true value is inhibited on every synapse into it (a signal "
          "poisoned feedback cannot flip).", ""]
    return "\n".join(L)


def report_md(meta, runs):
    L = ["# QueryBook stress test: current design vs Digital Synaptic Network", "",
         "Version %s · preset **%s** · seed %d · %s · prototype code from `%s`" % (VERSION, meta["preset"], meta["seed"], meta["when"], meta["qb"]), "",
         "Engines: **A0** current QueryBook as installed (keywords, no AI model) · **A1** current, planned first hop · **A2** current pipeline "
         "chained (control, no agents) · **B** conventional multi-agent (asks every agent, text) · **C0** DSN without learning · **C** DSN with "
         "learning.", "",
         "Outcomes per question: *correct* · *wrong answer* (stated something false, or answered the unknowable) · *no answer* (declined or "
         "could not get there) · *missed conflict* · *false alarm* (reported a conflict that a lying agent invented). Time = real compute + "
         "modelled communication (0.5 ms + bytes at 100 MB/s per message; 250 ms timeout per dead agent waited for).", ""]
    for r in runs:
        L += ["## %s" % r["scenario"], "", "%s facts · %s agents · %d thread(s) · stress: `%s` · what a perfect reader must say: %s" %
              (format(r["facts"], ","), format(r["agents"], ","), r["threads"], json.dumps(r["stress"]), r["expected_mix"]), "",
              "| Engine | Correct | Wrong answer | No answer | Missed conflict | False alarm | Messages/q | Bytes/q | Agents woken/q | p50 ms | p99 ms | Correct by depth 1/2/3/4 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for e in r["results"]:
            bd = e["by_depth"]
            L.append("| %s | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %s | %s | %s | %.1f | %.1f | %s/%s/%s/%s |" % (
                e["engine"], e["correct"], e["wrong answer"], e["no answer"], e["missed conflict"], e["false alarm"],
                format(e["messages"], ",.1f"), format(e["bytes"], ",.0f"), format(e["agents"], ",.1f"), e["p50_ms"], e["p99_ms"], bd[1], bd[2], bd[3], bd[4]))
        c = next((e for e in r["results"] if e["engine"].startswith("C DSN")), None)
        if c:
            L += ["", "DSN learning curve (correct %% per tenth of the run): %s · messages per question: %s%s" % (
                c["curve"], c["curve_msgs"], (" · just after the faults changed: %.1f%%" % c["just_after_shift"]) if "just_after_shift" in c else "")]
        L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="QueryBook current design vs Digital Synaptic Network — stress test")
    ap.add_argument("preset", choices=["quick", "stress", "extreme", "learning", "self-test"],
                    help="learning = only the learning-over-time study (about 5-15 minutes)")
    ap.add_argument("--qb"); ap.add_argument("--out", default="dsn-results")
    ap.add_argument("--threads", type=int); ap.add_argument("--queries", type=int); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-current", action="store_true", help="skip the prototype engines (A0-A2)")
    ap.add_argument("--no-learning", action="store_true", help="skip the learning-over-time study")
    ap.add_argument("--study-queries", type=int, help="questions in the learning-over-time study")
    a = ap.parse_args(argv)
    if a.preset == "self-test":
        return self_test(a)
    only_study = a.preset == "learning"
    base = dict(PRESETS["quick" if only_study else a.preset], seed=a.seed)
    if only_study:
        base["scenarios"], base["scale"] = [], []
    size = dict(STUDY_SIZE[a.preset])
    if a.study_queries:
        size["queries"] = a.study_queries
    if a.queries:
        base["queries"] = a.queries
    if a.threads:
        base["threads"] = a.threads
    qbmods, qbdir = (None, "skipped")
    if not a.no_current and not only_study:
        qc, us, qbdir = load_prototype(a.qb)
        qbmods = (qc, us)
    os.makedirs(a.out, exist_ok=True)
    folder = os.path.join(a.out, "stores")
    os.makedirs(folder, exist_ok=True)
    logf = open(os.path.join(a.out, "run-log.txt"), "a", encoding="utf-8")

    def log(*x):
        line = " ".join(str(v) for v in x)
        print(line, flush=True); logf.write(line + "\n"); logf.flush()
    when = time.strftime("%Y-%m-%d %H:%M")
    log("QueryBook stress test %s — preset %s, %s CPU cores, prototype: %s" % (VERSION, a.preset, os.cpu_count(), qbdir))
    runs = [scenario(n, {}, base, qbmods, folder, log) for n in base["scenarios"]] + scale_runs(base, qbmods, folder, log)
    study = None if a.no_learning else learning_study(size, a.seed, log)
    meta = {"preset": a.preset, "seed": a.seed, "when": when, "qb": qbdir, "cores": os.cpu_count(), "version": VERSION, "base": base}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(a.out, "dsn-stress-%s-%s.json" % (a.preset, stamp)), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "runs": runs, "learning_over_time": study}, f, indent=1)
    md = os.path.join(a.out, "dsn-stress-%s-%s.md" % (a.preset, stamp))
    with open(md, "w", encoding="utf-8") as f:
        f.write(report_md(meta, runs) + ("\n" + study_md(study) if study else ""))
    log("\nReport: %s" % os.path.abspath(md))
    return 0


def self_test(a):
    """the engines are right where the answer is clear, and each stress does what it says"""
    ok = []

    def check(name, cond, detail=""):
        ok.append(bool(cond)); print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)))
    w = World(3000, seed=3)
    qs = w.questions(200, 4)
    check("a clean world: every question has a verified answer", all(q["exp"] == "VERIFIED" for q in qs))
    pool = AgentPool(w, 4, 3)
    for eng, fn in (("B", Broadcast(pool).answer), ("C", DSN(pool).answer)):
        r = run_engine(eng, fn, qs)
        check("%s answers every question of a clean world correctly" % eng, r["correct"] == 100.0, r)
    w2 = World(3000, seed=3, noise=0.5, adv=0.2, missing=0.2)
    q2 = w2.questions(400, 4)
    check("bad knowledge creates unknown and contradicted questions", any(q["exp"] == "UNKNOWN" for q in q2) and any(q["exp"] == "CONTRADICTED" for q in q2))
    p2 = AgentPool(w2, 4, 3)
    r = run_engine("C", DSN(p2).answer, q2)
    check("with honest agents the DSN reads bad knowledge exactly as a perfect reader would", r["correct"] == 100.0, r)
    p3 = AgentPool(w, 4, 3, liar=0.3, dead=0.1)
    rb, rc0, rc = run_engine("B", Broadcast(p3).answer, qs), run_engine("C0", DSN(p3, learn=False).answer, qs), run_engine("C", DSN(p3).answer, qs)
    check("lying agents: broadcast reports false conflicts, the DSN catches the lies by resolving FU ids", rb["false alarm"] > 0 and rc["correct"] > rb["correct"], (rb["correct"], rc["correct"]))
    check("learning cuts messages compared with no learning", rc["messages"] <= rc0["messages"], (rc0["messages"], rc["messages"]))
    dsn = DSN(p3); run_engine("C", dsn.answer, qs)
    weak = dsn.audit()["weakest"][0]
    check("every synapse is auditable: strength, evidence, inhibitions, silences", weak["inhibitions"] + weak["silences"] > 0 and weak["strength"] < 0.3, weak)
    cw = World(3000, seed=3)
    cq = cw.questions(200, 4)
    for q in cq:
        q["truth"] = cw.truth_of(q["start"], q["chain"])
    cp = AgentPool(cw, 4, 3)
    bad = [n for n, e in study_engines(cw, cp, 3) if any(score_truth(q, *e.answer(q, random.Random(i))[:2]) != "correct" for i, q in enumerate(cq))]
    check("learning study: every engine answers a clean world correctly", not bad, bad)
    S = learning_study(dict(facts=20_000, queries=3000, distinct=1500), 1, lambda *x: None)
    E = {e["engine"][:3]: e for e in S["engines"]}
    check("learning study: agents that learn facts raise accuracy over time (C+1 last block above C)",
          E["C+1"]["blocks"][-1]["correct"] > E["C  "]["blocks"][-1]["correct"] + 10, (E["C+1"]["blocks"][-1], E["C  "]["blocks"][-1]))
    check("learning study: accuracy feedback cuts the wrong answers that learning alone caches (C+3 below C+2)",
          E["C+3"]["wrong"] < E["C+2"]["wrong"], (E["C+3"]["wrong"], E["C+2"]["wrong"]))
    check("learning study: the report renders", "## Learning over time" in study_md(S))
    try:
        qc, us, d = load_prototype(a.qb)
        tmp = tempfile.mkdtemp()
        try:
            cur = CurrentQueryBook(w, qc, us, tmp, log=lambda *x: None)
            r1 = run_engine("A1", lambda q, r: cur.answer_planned(q, False), [q for q in qs if q["depth"] == 1])
            r2 = run_engine("A2", lambda q, r: cur.answer_planned(q, True), qs)
            check("the prototype's own pipeline answers 1-step questions correctly", r1["correct"] == 100.0, r1)
            check("the prototype's pipeline, chained, answers every question of a clean world", r2["correct"] == 100.0, r2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except SystemExit as e:
        print("skip the prototype checks:", e)
    print("%d of %d checks passed" % (sum(ok), len(ok)))
    return 0 if all(ok) else 1


def _console_utf8():
    """a Windows console that cannot show "—" or "·" must never stop the test: unknown characters become "?" """
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


if __name__ == "__main__":
    _console_utf8()
    print("QueryBook stress test %s starting: Python %s on %s, %s CPU cores" % (VERSION, sys.version.split()[0], sys.platform, os.cpu_count()), flush=True)
    if sys.version_info < (3, 8):
        print("Python 3.8 or newer is needed (this is %s). Install it from python.org." % sys.version.split()[0])
        sys.exit(2)
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        err = traceback.format_exc()
        print("\nTHE TEST STOPPED WITH AN ERROR:\n" + err, flush=True)
        try:
            os.makedirs("dsn-results", exist_ok=True)
            with open(os.path.join("dsn-results", "error.txt"), "w", encoding="utf-8") as f:
                f.write(err)
            print("The error is also saved in dsn-results\\error.txt — please send that file.")
        except OSError:
            pass
        sys.exit(1)
