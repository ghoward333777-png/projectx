"""Unit posteriors → words: CTC prefix beam search constrained to a pronunciation lexicon (a trie of unit sequences),
with a unigram word prior and an insertion bonus. Words that look identical share a lexicon path, so every
hypothesis keeps its look-alike alternatives."""
from __future__ import annotations

import math
from collections import defaultdict


class Trie:
    def __init__(self):
        self.kids, self.words = {}, []


def build_trie(lexicon):
    """lexicon: {word: [unit, ...]} → root Trie."""
    root = Trie()
    for w, units in lexicon.items():
        node = root
        for u in units:
            node = node.kids.setdefault(u, Trie())
        node.words.append(w)
    return root


def _lse(*xs):
    m = max(xs)
    return m if m == -math.inf else m + math.log(sum(math.exp(x - m) for x in xs))


def lexicon_beam_search(log_probs, vocab, lexicon, word_logp=None, beam=16, lm_weight=0.5, insertion=0.5):
    """log_probs: [T][V] (list or tensor rows), vocab[0] = blank. Returns [(words, score)] best first."""
    root = build_trie(lexicon)
    word_logp = word_logp or {}
    idx = {u: i for i, u in enumerate(vocab)}
    # state: (words tuple, trie node id, last unit) → (p_blank, p_nonblank)
    nodes = {id(root): root}
    beams = {((), id(root), None): (0.0, -math.inf)}
    for row in log_probs:
        row = list(map(float, row))
        nxt = defaultdict(lambda: [-math.inf, -math.inf])
        for (words, nid, last), (pb, pnb) in beams.items():
            node = nodes[nid]
            tot = _lse(pb, pnb)
            e = nxt[(words, nid, last)]
            e[0] = _lse(e[0], tot + row[0])                         # blank
            if last is not None:
                e[1] = _lse(e[1], pnb + row[idx[last]])             # repeat of the same unit (no new symbol)
            for u, child in node.kids.items():
                p = row[idx[u]] + (pb if u == last else tot)        # a new symbol (after a blank if repeated)
                nodes[id(child)] = child
                e2 = nxt[(words, id(child), u)]
                e2[1] = _lse(e2[1], p)
                for w in child.words:                               # the word may end here
                    bonus = lm_weight * word_logp.get(w, -10.0) + insertion
                    e3 = nxt[(words + (w,), id(root), u)]
                    e3[1] = _lse(e3[1], p + bonus)
        beams = dict(sorted(((k, tuple(v)) for k, v in nxt.items()), key=lambda kv: -_lse(*kv[1]))[:beam])
    finals = defaultdict(lambda: -math.inf)
    for (words, nid, _), (pb, pnb) in beams.items():
        if nid == id(root):
            finals[words] = _lse(finals[words], pb, pnb)
    return sorted(finals.items(), key=lambda kv: -kv[1])
