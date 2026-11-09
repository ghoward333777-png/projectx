"""qbsynapse — learning connections between agents: digital synapses, assemblies, engrams, networks of networks.

The lesson borrowed from biology: do not only make the agents smarter, make the connections between them able to learn.
Here the relationships between agents are themselves a layer of memory, and every part of it can be inspected.

  synapse        a relationship between two agents (or processing elements). It carries its type, strength,
                 activation threshold, the contexts it formed in, reliability (good and bad outcomes), provenance
                 (the last pieces of evidence), history (the last changes), when it formed and when it was last used.
  plasticity     agents that succeed together get a stronger synapse (potentiation); a joint failure weakens it
                 (depression); an unused synapse fades with time (forgetting) and a faded one is removed (turnover);
                 a synapse with a long record fades much more slowly (consolidation). A new synapse starts weak:
                 one coincidence is not a relationship.
  threshold      a synapse passes activation only above its own threshold, which rises when it has been unreliable.
  engram         for each context (a kind of problem), the population of agents that was active when it was solved.
  assembly       agents bound by strong synapses: a functional group that has repeatedly solved problems together.
  network of     assemblies linked by synapses between their members: networks communicating with networks.
  networks
  spreading      activation flows from the agents that are active along synapses above threshold, weakening with
  activation     each step: who else is likely to matter now.

Caution, as the design note says: this does not create intelligence by itself. It records, adapts and exposes how agents
work together, so routing and review can use it. Deterministic when `at` is given; standard library only; thread-safe.
The same file serves the QueryBook suite (qbsynapse.py) and the prototype (qb_synapse.py).
"""
import hashlib, json, os, threading, time

import qbmath                   # the learning arithmetic: pure, proved in Lean, ported to Rust

VERSION = "1.0.0"
INIT, ETA, DEPRESS, THETA = qbmath.SYN_INIT, qbmath.SYN_ETA, qbmath.SYN_DEPRESS, qbmath.SYN_THETA
ASSEMBLY = 0.50                 # strength that binds two agents into the same assembly (about five joint successes)
DECAY_PER_DAY, CONSOLIDATED_DECAY_PER_DAY, CONSOLIDATE_AFTER = qbmath.SYN_DECAY_PER_DAY, qbmath.SYN_CONSOLIDATED_DECAY_PER_DAY, qbmath.SYN_CONSOLIDATE_AFTER
PRUNE_BELOW, PRUNE_IDLE_DAYS = qbmath.SYN_PRUNE_BELOW, qbmath.SYN_PRUNE_IDLE_DAYS
MAX_EPISODE_NODES, MAX_SYNAPSES, MAX_CONTEXTS, MAX_RECENT = 8, 50_000, 2000, 400
DAY = 86400.0


def _key(a, b, kind, directed):
    x, y = (a, b) if directed else tuple(sorted((a, b)))
    return "%s\x1f%s\x1f%s\x1f%d" % (x, y, kind, 1 if directed else 0)


class Network:
    """one learning network of agent relationships, saved as JSON at `path` (or kept in memory when path is None)"""

    def __init__(self, path=None, name="network", window_s=600.0, save_every_s=5.0):
        self.path, self.name, self.window, self.save_every = path, name, float(window_s), float(save_every_s)
        self.lock = threading.RLock()
        self.syn, self.adj, self.engram, self.recent = {}, {}, {}, []
        self.counters = {"episodes": 0, "formed": 0, "potentiated": 0, "depressed": 0, "pruned": 0, "faded": 0}
        self._saved_at, self._dirty = 0.0, False
        self.load()

    # ------------------------------------------------------------------ persistence
    def load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        with self.lock:
            self.syn = {_key(s["a"], s["b"], s["type"], s["directed"]): s for s in d.get("synapses", [])}
            self.engram = d.get("engrams", {})
            self.recent = [tuple(r) for r in d.get("recent", [])]
            self.counters.update(d.get("counters", {}))
            self._reindex()

    def _reindex(self):
        self.adj = {}
        for k, s in self.syn.items():
            self.adj.setdefault(s["a"], set()).add(k)
            self.adj.setdefault(s["b"], set()).add(k)

    def save(self, force=True):
        if not self.path:
            return
        with self.lock:
            if not force and (not self._dirty or time.time() - self._saved_at < self.save_every):
                return
            d = {"version": VERSION, "name": self.name, "counters": self.counters, "synapses": list(self.syn.values()),
                 "engrams": self.engram, "recent": [list(r) for r in self.recent]}
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, separators=(",", ":"))
            os.replace(tmp, self.path)
            self._saved_at, self._dirty = time.time(), False

    # ------------------------------------------------------------------ plasticity
    def _get(self, a, b, kind, directed, at, form=True):
        k = _key(a, b, kind, directed)
        s = self.syn.get(k)
        if s is None and form:
            if len(self.syn) >= MAX_SYNAPSES:
                self.decay(at)
                if len(self.syn) >= MAX_SYNAPSES:
                    return None
            x, y = (a, b) if directed else tuple(sorted((a, b)))
            s = {"a": x, "b": y, "type": kind, "directed": bool(directed), "strength": INIT, "threshold": THETA,
                 "contexts": {}, "ok": 0, "bad": 0, "provenance": [], "history": [], "created": at, "last": at, "consolidated": False}
            self.syn[k] = s
            self.adj.setdefault(x, set()).add(k)
            self.adj.setdefault(y, set()).add(k)
            self.counters["formed"] += 1
        return s

    def _fade(self, s, at):
        """forgetting since the synapse was last used (lazy: applied whenever it is touched)"""
        days = max(0.0, (at - (s["last"] or at)) / DAY)
        s["strength"] = qbmath.syn_fade(s["strength"], days, s["consolidated"])

    def _change(self, s, good, context, evidence, at):
        self._fade(s, at)
        before = s["strength"]
        if good:
            s["strength"] = qbmath.syn_potentiate(before)
            s["ok"] += 1
            self.counters["potentiated"] += 1
        else:
            s["strength"] = qbmath.syn_depress(before)
            s["bad"] += 1
            self.counters["depressed"] += 1
        s["threshold"] = qbmath.syn_threshold(s["ok"], s["bad"])
        s["consolidated"] = qbmath.syn_consolidated(s["ok"], s["bad"])
        if context:
            s["contexts"][context] = s["contexts"].get(context, 0) + 1
            if len(s["contexts"]) > 12:
                for c, _ in sorted(s["contexts"].items(), key=lambda kv: kv[1])[:len(s["contexts"]) - 12]:
                    del s["contexts"][c]
        if evidence:
            s["provenance"] = (s["provenance"] + [str(evidence)[:160]])[-5:]
        s["history"] = (s["history"] + [[round(at, 1), "+" if good else "-", s["strength"]]])[-12:]
        s["last"] = at
        self._dirty = True

    def experience(self, nodes, context, success=True, evidence=None, at=None, kind="co-activation"):
        """agents active together in one episode (for example the specialists whose facts answered one question):
        each pair's synapse is potentiated on success, depressed on failure; the context's engram records them"""
        at = time.time() if at is None else float(at)
        nodes = sorted(dict.fromkeys(n for n in nodes if n))[:MAX_EPISODE_NODES]
        out = {"formed": 0, "strengthened": 0, "weakened": 0}
        with self.lock:
            self.counters["episodes"] += 1
            if success and context and nodes:
                e = self.engram.setdefault(context, {"episodes": 0, "members": {}, "last": at})
                e["episodes"] += 1
                e["last"] = at
                for n in nodes:
                    e["members"][n] = e["members"].get(n, 0) + 1
                if len(self.engram) > MAX_CONTEXTS:
                    for c, _ in sorted(self.engram.items(), key=lambda kv: kv[1]["last"])[:len(self.engram) - MAX_CONTEXTS]:
                        del self.engram[c]
            for i in range(len(nodes)):
                for j in range(i + 1, len(nodes)):
                    before = self.counters["formed"]
                    s = self._get(nodes[i], nodes[j], kind, False, at, form=bool(success))
                    if s is None:
                        continue
                    out["formed"] += self.counters["formed"] - before
                    self._change(s, success, context, evidence, at)
                    out["strengthened" if success else "weakened"] += 1
            self.save(force=False)
        return out

    def activate(self, node, context, success=True, evidence=None, at=None):
        """one agent active at time `at`: co-activation with the agents that were active (and succeeded) within the
        window. Fire together, wire together; a failure next to a success weakens what links them."""
        at = time.time() if at is None else float(at)
        with self.lock:
            self.recent = [r for r in self.recent if at - r[3] <= self.window][-MAX_RECENT:]
            partners = sorted({r[0] for r in self.recent if r[0] != node and r[2]})
            self.recent.append((node, context, bool(success), at))
            for p in partners:
                s = self._get(node, p, "co-activation", False, at, form=bool(success))
                if s is not None:
                    self._change(s, success, context, evidence, at)
            if success and context:
                e = self.engram.setdefault(context, {"episodes": 0, "members": {}, "last": at})
                e["episodes"] += 1
                e["last"] = at
                e["members"][node] = e["members"].get(node, 0) + 1
            self.counters["episodes"] += 1
            self._dirty = True
            self.save(force=False)
        return partners

    def link(self, src, dst, kind, context=None, good=True, evidence=None, at=None):
        """a directed relationship: src's output was used by dst (and turned out right, or wrong)"""
        at = time.time() if at is None else float(at)
        with self.lock:
            s = self._get(src, dst, kind, True, at, form=bool(good))
            if s is not None:
                self._change(s, good, context, evidence, at)
            self.save(force=False)
        return s

    def decay(self, at=None):
        """turnover: every synapse fades by its idle time; faded, idle ones are removed. Returns what was pruned."""
        at = time.time() if at is None else float(at)
        pruned = 0
        with self.lock:
            for k in list(self.syn):
                s = self.syn[k]
                was = s["strength"]
                self._fade(s, at)
                if s["strength"] < was:
                    s["last"] = at if s["strength"] >= PRUNE_BELOW else s["last"]
                    self.counters["faded"] += 1
                if s["strength"] < PRUNE_BELOW and (at - (s["last"] or at)) / DAY >= 0:
                    idle = (at - max(h[0] for h in s["history"])) / DAY if s["history"] else PRUNE_IDLE_DAYS
                    if idle >= PRUNE_IDLE_DAYS:
                        del self.syn[k]
                        pruned += 1
            if pruned:
                self.counters["pruned"] += pruned
                self._reindex()
            self._dirty = True
            self.save(force=False)
        return pruned

    # ------------------------------------------------------------------ reading the network
    def synapse(self, a, b, kind="co-activation", directed=False):
        s = self.syn.get(_key(a, b, kind, directed))
        return dict(s) if s else None

    def neighbours(self, node, min_strength=0.0):
        with self.lock:
            out = []
            for k in self.adj.get(node, ()):
                s = self.syn[k]
                if s["strength"] >= min_strength:
                    out.append((s["b"] if s["a"] == node else s["a"], s))
            return sorted(out, key=lambda x: (-x[1]["strength"], x[0]))

    def spread(self, seeds, steps=2, falloff=0.5):
        """spreading activation from the active agents along synapses above their own threshold"""
        with self.lock:
            act = {n: 1.0 for n in seeds}
            frontier = dict(act)
            for _ in range(max(0, steps)):
                nxt = {}
                for n, a in frontier.items():
                    for k in self.adj.get(n, ()):
                        s = self.syn[k]
                        if s["strength"] < s["threshold"] or (s["directed"] and s["a"] != n):
                            continue
                        m = s["b"] if s["a"] == n else s["a"]
                        v = a * s["strength"] * falloff
                        if v > act.get(m, 0) and v > nxt.get(m, 0):
                            nxt[m] = v
                for m, v in nxt.items():
                    act[m] = max(act.get(m, 0), v)
                frontier = nxt
            return sorted(((n, round(v, 4)) for n, v in act.items()), key=lambda x: (-x[1], x[0]))

    def assemblies(self, min_strength=ASSEMBLY):
        """agents bound by strong co-activation synapses: functional groups (connected groups of two or more)"""
        with self.lock:
            parent = {}

            def find(x):
                parent.setdefault(x, x)
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x
            strong = [s for s in self.syn.values() if s["type"] == "co-activation" and s["strength"] >= min_strength]
            for s in strong:
                ra, rb = find(s["a"]), find(s["b"])
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            groups = {}
            for n in list(parent):
                groups.setdefault(find(n), []).append(n)
            out = []
            for members in groups.values():
                if len(members) < 2:
                    continue
                members.sort()
                ms = set(members)
                inner = [s for s in strong if s["a"] in ms and s["b"] in ms]
                ctx = {}
                for s in inner:
                    for c, n in s["contexts"].items():
                        ctx[c] = ctx.get(c, 0) + n
                top = [c for c, _ in sorted(ctx.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
                out.append({"id": "A-" + hashlib.sha1("|".join(members).encode()).hexdigest()[:8], "members": members,
                            "size": len(members), "cohesion": round(sum(s["strength"] for s in inner) / len(inner), 3),
                            "joint_successes": sum(s["ok"] for s in inner), "contexts": top, "label": top[0] if top else ""})
            out.sort(key=lambda a: (-a["size"], -a["cohesion"], a["id"]))
            return out

    def assembly_links(self, assemblies=None):
        """networks communicating with networks: synapses (above threshold) between members of different assemblies"""
        with self.lock:
            asm = assemblies if assemblies is not None else self.assemblies()
            where = {m: a["id"] for a in asm for m in a["members"]}
            agg = {}
            for s in self.syn.values():
                x, y = where.get(s["a"]), where.get(s["b"])
                if not x or not y or x == y or s["strength"] < s["threshold"]:
                    continue
                k = tuple(sorted((x, y)))
                g = agg.setdefault(k, {"between": list(k), "synapses": 0, "strength": 0.0, "contexts": {}})
                g["synapses"] += 1
                g["strength"] += s["strength"]
                for c, n in s["contexts"].items():
                    g["contexts"][c] = g["contexts"].get(c, 0) + n
            out = []
            for g in agg.values():
                g["strength"] = round(g["strength"] / g["synapses"], 3)
                g["contexts"] = [c for c, _ in sorted(g["contexts"].items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
                out.append(g)
            return sorted(out, key=lambda g: (-g["strength"], g["between"]))

    def engrams(self, top=8, limit=50):
        """for each context, the population of agents active when it was solved (most frequent first)"""
        with self.lock:
            rows = []
            for c, e in self.engram.items():
                mem = sorted(e["members"].items(), key=lambda kv: (-kv[1], kv[0]))
                rows.append({"context": c, "episodes": e["episodes"], "members": [{"agent": n, "times": k} for n, k in mem[:top]],
                             "population": len(mem), "last": e["last"]})
            rows.sort(key=lambda r: (-r["episodes"], r["context"]))
            return rows[:limit]

    def explain(self, a, b, kind="co-activation", directed=False):
        s = self.synapse(a, b, kind, directed)
        if not s:
            return "No synapse between %s and %s." % (a, b)
        when = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "—"
        return "\n".join([
            "%s %s %s  (%s)" % (s["a"], "→" if s["directed"] else "↔", s["b"], s["type"]),
            "strength %.3f · passes activation above %.3f%s" % (s["strength"], s["threshold"], " · consolidated" if s["consolidated"] else ""),
            "reliability: %d good, %d bad" % (s["ok"], s["bad"]),
            "contexts: " + (", ".join("%s ×%d" % kv for kv in sorted(s["contexts"].items(), key=lambda kv: -kv[1])) or "—"),
            "formed %s · last used %s" % (when(s["created"]), when(s["last"])),
            "evidence: " + ("; ".join(s["provenance"]) or "—"),
            "history: " + " ".join("%s%.2f" % (h[1], h[2]) for h in s["history"])])

    def summary(self, top=10):
        with self.lock:
            asm = self.assemblies()
            links = self.assembly_links(asm)
            strongest = sorted(self.syn.values(), key=lambda s: -s["strength"])[:top]
            return {"name": self.name, "version": VERSION, "agents": len(self.adj), "synapses": len(self.syn),
                    "above_threshold": sum(1 for s in self.syn.values() if s["strength"] >= s["threshold"]),
                    "consolidated": sum(1 for s in self.syn.values() if s["consolidated"]),
                    "assemblies": asm, "assembly_links": links, "engrams": self.engrams(limit=20),
                    "strongest": strongest, "counters": dict(self.counters)}

    def health_line(self):
        s = self.summary(top=0)
        return ("Network memory: %s agents · %s synapses (%s above threshold, %s consolidated) · %d assemblies · %d links between "
                "assemblies · formed %s, pruned %s" % (format(s["agents"], ","), format(s["synapses"], ","), format(s["above_threshold"], ","),
                                                       format(s["consolidated"], ","), len(s["assemblies"]), len(s["assembly_links"]),
                                                       format(s["counters"]["formed"], ","), format(s["counters"]["pruned"], ",")))


# ---------------------------------------------------------------------------------------------- self-test
def self_test():
    import shutil, tempfile
    out = []

    def ok(name, cond, detail=""):
        out.append(bool(cond))
        print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)[:400]))
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "net.json")
        n = Network(path, "test")
        t = 1_000_000.0
        med = ["hematology", "oxygen", "hydration", "pain", "disease"]
        mol = ["hemoglobin", "protein", "gene"]
        r = n.experience(med[:2], "medical", True, "case 1", at=t)
        s = n.synapse("hematology", "oxygen")
        ok("one joint success forms a weak synapse, below its threshold (one coincidence is not a relationship)",
           r["formed"] == 1 and s["strength"] < s["threshold"], s)
        for i in range(6):
            n.experience(med, "medical", True, "case %d" % (i + 2), at=t + i)
            n.experience(mol, "molecular", True, "lab %d" % i, at=t + i)
        asm = n.assemblies()
        ok("agents that repeatedly succeed together become functional assemblies", len(asm) == 2 and asm[0]["members"] == sorted(med)
           and asm[1]["members"] == sorted(mol), asm)
        for i in range(4):
            n.experience(["oxygen", "hemoglobin"], "oxygen transport", True, "joint %d" % i, at=t + 10 + i)
        links = n.assembly_links()
        ok("assemblies linked through their members: networks communicating with networks", len(links) == 1 and links[0]["contexts"] == ["oxygen transport"], links)
        e = n.engrams()
        ok("each context keeps its engram: the population active when it was solved", e[0]["context"] == "medical" and e[0]["population"] == 5, e[0])
        sp = dict(n.spread(["hematology"]))
        ok("spreading activation reaches the assembly, then the linked assembly, weaker at each step",
           sp.get("oxygen", 0) > sp.get("hemoglobin", 0) > 0, sp)
        before = n.synapse("pain", "disease")["strength"]
        n.experience(["pain", "disease"], "medical", False, "wrong together", at=t + 20)
        s = n.synapse("pain", "disease")
        ok("a joint failure weakens the synapse and raises its threshold (less reliable, harder to fire)",
           s["strength"] < before and s["threshold"] > THETA and s["bad"] == 1, s)
        ok("every synapse carries its record: type, strength, threshold, contexts, reliability, provenance, history",
           all(k in s for k in ("type", "strength", "threshold", "contexts", "ok", "bad", "provenance", "history", "created", "last")) and s["provenance"], s)
        x = n.explain("oxygen", "hemoglobin")
        ok("a synapse explains itself in plain lines", "strength" in x and "oxygen transport" in x and "evidence" in x, x)
        n.save()
        m = Network(path, "test")
        ok("the network is saved and read back whole", m.summary()["synapses"] == n.summary()["synapses"] and len(m.assemblies()) == 2)
        for i in range(25):
            m.experience(["gene", "protein"], "molecular", True, "repeat %d" % i, at=t + 30 + i)
        g = m.synapse("gene", "protein")
        ok("a synapse with a long record is consolidated", g["consolidated"], g)
        later = t + 200 * DAY
        pruned = m.decay(at=later)
        ok("unused synapses fade with time and faded ones are removed (turnover); consolidated ones last",
           pruned > 0 and m.synapse("gene", "protein") is not None and m.synapse("pain", "disease") is None, (pruned, m.summary()["synapses"]))
        q = Network(None, "window", window_s=60)
        q.activate("agent-a", "math", True, at=t)
        q.activate("agent-b", "math", True, at=t + 30)
        q.activate("agent-c", "math", True, at=t + 200)
        ok("agents active within the window are linked; those far apart in time are not", q.synapse("agent-a", "agent-b") and not q.synapse("agent-a", "agent-c"))
        d = Network(None, "directed")
        d.link("harvester", "verifier", "feeds", "facts", True, at=t)
        ok("directed relationships (one agent's output used by another) are kept apart from co-activation",
           d.synapse("harvester", "verifier", "feeds", True) and not d.synapse("verifier", "harvester", "feeds", True))
        ok("the health line counts agents, synapses, assemblies and links", "assemblies" in n.health_line())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("%d of %d checks passed" % (sum(out), len(out)))
    return all(out)


if __name__ == "__main__":
    import sys
    sys.exit(0 if self_test() else 1)
