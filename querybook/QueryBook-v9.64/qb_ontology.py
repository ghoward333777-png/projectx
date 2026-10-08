"""Ontology / concept graph  [deterministic]  — Registry features 8.5.x (068–080)

Builds a concept graph from Fact-Unit triples: concept NODES (subjects/objects) and typed
EDGES derived from predicates — hierarchical (is_a / subclass / instance), prerequisite
(requires / prerequisite), equivalence (equals / means / translation), else related. Provides
a concept-path generator (BFS), ancestors, and neighbours. Deterministic and reproducible; it
organizes existing verified facts, it does not assert new ones.
"""

from collections import defaultdict, deque

_HIER = ("is_a", "subclass_of", "instance_of", "in_century", "in_decade", "type_of")
_PREREQ = ("requires", "prerequisite", "depends_on", "built_on")
_EQUIV = ("equals", "means", "translation", "same_as", "alias_of")


def _edge_type(pred):
    p = (pred or "").lower()
    if p in _HIER: return "hierarchical"
    if p in _PREREQ: return "prerequisite"
    if p in _EQUIV: return "equivalence"
    return "related"


def build(triples):
    """triples: iterable of (subject, predicate, object). Returns a concept graph dict."""
    nodes = set()
    edges = []
    adj = defaultdict(list)
    for s, p, o in triples:
        s = str(s); o = str(o)
        nodes.add(s); nodes.add(o)
        et = _edge_type(p)
        edges.append({"from": s, "to": o, "predicate": p, "type": et})
        adj[s].append((o, et, p))
        # equivalence + hierarchical are navigable both ways for pathing
        if et in ("equivalence",):
            adj[o].append((s, et, p))
    return {"nodes": sorted(nodes), "edges": edges, "_adj": adj,
            "counts": {"nodes": len(nodes), "edges": len(edges)}}


def neighbors(graph, node):
    return [{"to": o, "type": et, "predicate": p} for (o, et, p) in graph["_adj"].get(node, [])]


def ancestors(graph, node, limit=50):
    """Follow hierarchical edges upward (node is_a X is_a Y …)."""
    out, seen, cur, steps = [], {node}, node, 0
    while steps < limit:
        nxt = next(((o) for (o, et, p) in graph["_adj"].get(cur, []) if et == "hierarchical"), None)
        if not nxt or nxt in seen: break
        out.append(nxt); seen.add(nxt); cur = nxt; steps += 1
    return out


def concept_path(graph, a, b, max_depth=8):
    """Shortest edge path between two concepts (BFS). Returns a list of hops or []."""
    a, b = str(a), str(b)
    if a not in graph["_adj"] and a not in graph["nodes"]:
        return []
    q = deque([(a, [])])
    seen = {a}
    while q:
        cur, path = q.popleft()
        if cur == b:
            return path
        if len(path) >= max_depth:
            continue
        for (o, et, p) in graph["_adj"].get(cur, []):
            if o not in seen:
                seen.add(o)
                q.append((o, path + [{"from": cur, "to": o, "type": et, "predicate": p}]))
    return []


def from_store(store_dir, limit=5000):
    """Build the graph from Fact Units in the store (best-effort, bounded)."""
    try:
        import ufcs_store
        st = ufcs_store.UFCSStore(store_dir)
        tris = []
        for i, rec in enumerate(st.iter_all()):
            if i >= limit: break
            s = rec.get("subject"); p = rec.get("predicate"); o = rec.get("object")
            if s is not None and p is not None and o is not None:
                tris.append((s, p, o))
        st.close()
        return build(tris)
    except Exception as ex:
        return {"nodes": [], "edges": [], "_adj": {}, "counts": {"nodes": 0, "edges": 0},
                "error": str(ex)}


def public(graph):
    """Graph without the internal adjacency index (safe to JSON-serialize)."""
    return {k: v for k, v in graph.items() if k != "_adj"}


def qc():
    g = build([("Hamlet", "is_a", "play"), ("play", "is_a", "literary work"),
               ("Hamlet", "author", "Shakespeare"), ("finna", "means", "going to"),
               ("calculus", "requires", "algebra")])
    checks = []
    checks.append(("nodes built", g["counts"]["nodes"] >= 5))
    checks.append(("hierarchical ancestor", "literary work" in ancestors(g, "Hamlet")))
    checks.append(("prerequisite edge typed", any(e["type"] == "prerequisite" for e in g["edges"])))
    path = concept_path(g, "Hamlet", "literary work")
    checks.append(("concept path found", len(path) == 2))
    passed = sum(1 for _, c in checks if c)
    return {"passed": passed, "total": len(checks), "ok": passed == len(checks),
            "rows": [{"check": n, "pass": c} for n, c in checks]}


if __name__ == "__main__":
    import json
    print(json.dumps(qc(), indent=2))
