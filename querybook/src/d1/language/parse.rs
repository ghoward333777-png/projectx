//! Stage 1b — clause decomposition; Stage 2b — constituency chunking and
//! dependency parsing. Deterministic rules over tagged tokens.
//!
//! Clauses: main, coordinate (", and she…"), subordinate ("because …",
//! "when …"), relative ("…, who was proud,") with its antecedent, and quoted
//! speech. A clause is a set of token indices, so an embedded relative clause
//! leaves its host clause contiguous in meaning ("Mr. Darcy … refused").
//!
//! Phrases: NP, VP, PP, ADJP, ADVP. Dependencies use Universal Dependencies
//! relation names (nsubj, nsubj:pass, obj, iobj, obl, nmod, amod, det, case,
//! aux, cop, advmod, neg→advmod with Polarity, mark, cc, conj, poss, compound,
//! flat, nummod, xcomp, ccomp, acl:relcl, punct, root).

use super::tag::{Form, Pos, Token};
use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum ClauseKind {
    Main,
    Coordinate,
    Subordinate,
    Relative,
    Speech,
}

#[derive(Clone, Debug, Serialize)]
pub struct Clause {
    pub kind: ClauseKind,
    /// token indices in order
    pub tokens: Vec<usize>,
    /// subordinator / coordinator word, if any
    pub marker: Option<String>,
    /// token index of the antecedent head (relative clauses)
    pub antecedent: Option<usize>,
    /// index of the clause this one depends on
    pub parent: Option<usize>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum Phrase {
    NP,
    VP,
    PP,
    ADJP,
    ADVP,
    O,
}

#[derive(Clone, Debug, Serialize)]
pub struct Chunk {
    pub kind: Phrase,
    /// token indices (contiguous within the clause)
    pub tokens: Vec<usize>,
    pub head: usize,
}

#[derive(Clone, Debug, Serialize)]
pub struct Arc {
    pub dep: usize,
    /// None = root
    pub head: Option<usize>,
    pub rel: &'static str,
}

#[derive(Clone, Debug, Serialize)]
pub struct ClauseParse {
    pub clause: usize,
    pub chunks: Vec<Chunk>,
    pub root: Option<usize>,
    pub subject: Option<usize>,
    pub object: Option<usize>,
    pub copular: bool,
    pub passive: bool,
    pub negated: bool,
    pub arcs: Vec<Arc>,
}

// ---------------------------------------------------------------- clauses --

fn quote_open(t: &str) -> bool {
    t == "\u{201C}" || t == "\""
}
fn quote_close(t: &str) -> bool {
    t == "\u{201D}" || t == "\""
}

/// Split a tagged sentence into clauses.
pub fn clauses(tokens: &[Token]) -> Vec<Clause> {
    let n = tokens.len();
    // 1. quoted speech spans
    let mut in_quote = vec![false; n];
    let mut quotes: Vec<Vec<usize>> = Vec::new();
    let mut open: Option<usize> = None;
    for i in 0..n {
        let t = tokens[i].text.as_str();
        match open {
            None if quote_open(t) => open = Some(i),
            Some(o) if quote_close(t) || (t == "\"" && i > o) => {
                let span: Vec<usize> = (o + 1..i).filter(|&k| tokens[k].pos != Pos::Punct || tokens[k].text == ",").collect();
                for k in o..=i {
                    in_quote[k] = true;
                }
                if span.len() >= 2 {
                    quotes.push(span);
                }
                open = None;
            }
            _ => {}
        }
    }
    // 2. split the narration into clauses at markers
    let has_verb_after = |from: usize, to: usize| (from..to).any(|k| matches!(tokens[k].pos, Pos::Verb | Pos::Aux) && !in_quote[k]);
    let mut out: Vec<Clause> = Vec::new();
    let mut cur: Vec<usize> = Vec::new();
    let mut cur_kind = ClauseKind::Main;
    let mut cur_marker: Option<String> = None;
    let mut relative: Option<(Clause, usize)> = None; // (clause, host index)
    let flush = |cur: &mut Vec<usize>, kind: ClauseKind, marker: &mut Option<String>, out: &mut Vec<Clause>| {
        if cur.iter().any(|&k| tokens[k].pos != Pos::Punct) {
            out.push(Clause { kind, tokens: std::mem::take(cur), marker: marker.take(), antecedent: None, parent: None });
        } else {
            cur.clear();
            *marker = None;
        }
    };
    let mut i = 0;
    while i < n {
        if in_quote[i] {
            i += 1;
            continue;
        }
        let t = &tokens[i];
        // relative clause: noun/name , who|which … ,   or  noun that/who …
        if let Some((rc, host)) = relative.as_mut() {
            if t.text == "," || t.text == ";" || i + 1 == n || t.text == "." {
                let _ = host;
                if t.text != "," && t.pos != Pos::Punct {
                    rc.tokens.push(i);
                }
                let (rc, _) = relative.take().unwrap();
                out.push(rc);
                i += 1;
                continue;
            }
            rc.tokens.push(i);
            i += 1;
            continue;
        }
        if matches!(t.lower.as_str(), "who" | "which" | "whom") && i > 0 {
            let mut a = i - 1;
            if tokens[a].text == "," && a > 0 {
                a -= 1;
            }
            if matches!(tokens[a].pos, Pos::Noun | Pos::Propn) && has_verb_after(i + 1, n) {
                relative = Some((
                    Clause { kind: ClauseKind::Relative, tokens: vec![i], marker: Some(t.lower.clone()), antecedent: Some(a), parent: None },
                    out.len(),
                ));
                i += 1;
                continue;
            }
        }
        if t.text == ";" || t.text == ":" {
            flush(&mut cur, cur_kind, &mut cur_marker, &mut out);
            cur_kind = ClauseKind::Coordinate;
            i += 1;
            continue;
        }
        // ", and she …" / "but he …": coordinate clause with its own subject and verb
        if t.pos == Pos::Cconj && i + 1 < n && matches!(tokens[i + 1].pos, Pos::Pron | Pos::Propn | Pos::Det) && has_verb_after(i + 2, n)
            && cur.iter().any(|&k| matches!(tokens[k].pos, Pos::Verb | Pos::Aux))
        {
            flush(&mut cur, cur_kind, &mut cur_marker, &mut out);
            cur_kind = ClauseKind::Coordinate;
            cur_marker = Some(t.lower.clone());
            i += 1;
            continue;
        }
        // subordinate clause opens at a subordinator followed by a clause
        let subord = t.pos == Pos::Sconj
            || (matches!(t.lower.as_str(), "before" | "after" | "since" | "until" | "till" | "as" | "once")
                && i + 1 < n
                && matches!(tokens[i + 1].pos, Pos::Pron | Pos::Propn | Pos::Det)
                && has_verb_after(i + 2, n));
        if subord && t.lower != "that" {
            flush(&mut cur, cur_kind, &mut cur_marker, &mut out);
            cur_kind = ClauseKind::Subordinate;
            cur_marker = Some(t.lower.clone());
            i += 1;
            continue;
        }
        // a sentence-initial subordinate clause ends at its comma
        if t.text == "," && cur_kind == ClauseKind::Subordinate && has_verb_after(i + 1, n) && cur.iter().any(|&k| matches!(tokens[k].pos, Pos::Verb | Pos::Aux)) {
            flush(&mut cur, cur_kind, &mut cur_marker, &mut out);
            cur_kind = ClauseKind::Main;
            i += 1;
            continue;
        }
        cur.push(i);
        i += 1;
    }
    if let Some((rc, _)) = relative.take() {
        out.push(rc);
    }
    flush(&mut cur, cur_kind, &mut cur_marker, &mut out);
    for q in quotes {
        out.push(Clause { kind: ClauseKind::Speech, tokens: q, marker: None, antecedent: None, parent: None });
    }
    // parents: subordinate/relative/speech attach to the nearest main or coordinate clause
    let host = out.iter().position(|c| matches!(c.kind, ClauseKind::Main | ClauseKind::Coordinate));
    for (k, c) in out.iter_mut().enumerate() {
        if !matches!(c.kind, ClauseKind::Main) && host != Some(k) {
            c.parent = host;
        }
    }
    out
}

// ----------------------------------------------------------------- chunks --

fn np_word(p: Pos) -> bool {
    matches!(p, Pos::Noun | Pos::Propn | Pos::Adj | Pos::Num)
}

/// Group a clause's tokens into phrases.
pub fn chunk(tokens: &[Token], idx: &[usize]) -> Vec<Chunk> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < idx.len() {
        let t = &tokens[idx[i]];
        let start = i;
        match t.pos {
            Pos::Det | Pos::Noun | Pos::Propn | Pos::Adj | Pos::Num | Pos::Pron => {
                if t.pos == Pos::Pron {
                    out.push(Chunk { kind: Phrase::NP, tokens: vec![idx[i]], head: idx[i] });
                    i += 1;
                    continue;
                }
                let mut j = i + 1;
                if t.pos == Pos::Det {
                    // determiner then optional adverb+adjectives then nouns
                    while j < idx.len() && (np_word(tokens[idx[j]].pos) || (tokens[idx[j]].pos == Pos::Adv && j + 1 < idx.len() && tokens[idx[j + 1]].pos == Pos::Adj)) {
                        j += 1;
                    }
                } else {
                    while j < idx.len() && np_word(tokens[idx[j]].pos) {
                        j += 1;
                    }
                }
                // possessive: X 's Y  => one NP
                while j + 1 < idx.len() && tokens[idx[j]].lower == "'s" && np_word(tokens[idx[j + 1]].pos) {
                    j += 1;
                    while j < idx.len() && np_word(tokens[idx[j]].pos) {
                        j += 1;
                    }
                }
                let span: Vec<usize> = idx[start..j].to_vec();
                // an adjective-only span is an ADJP
                let head_pos = span.iter().rev().find(|&&k| matches!(tokens[k].pos, Pos::Noun | Pos::Propn | Pos::Num));
                match head_pos {
                    Some(&h) => {
                        // head: last noun; for a Propn run the last Propn
                        out.push(Chunk { kind: Phrase::NP, tokens: span, head: h });
                    }
                    None => {
                        let h = *span.iter().rev().find(|&&k| tokens[k].pos == Pos::Adj).unwrap_or(&span[span.len() - 1]);
                        out.push(Chunk { kind: if tokens[h].pos == Pos::Adj { Phrase::ADJP } else { Phrase::O }, tokens: span, head: h });
                    }
                }
                i = j.max(i + 1);
            }
            Pos::Aux | Pos::Verb | Pos::Part if !(t.pos == Pos::Part && t.lower == "'s") => {
                let mut j = i;
                let mut head = idx[i];
                while j < idx.len() && matches!(tokens[idx[j]].pos, Pos::Aux | Pos::Part | Pos::Adv | Pos::Verb) {
                    let p = tokens[idx[j]].pos;
                    if p == Pos::Verb || (p == Pos::Aux && tokens[head].pos != Pos::Verb) {
                        head = idx[j];
                    }
                    // stop after the main verb unless a particle/infinitive continues it
                    if p == Pos::Verb && !(j + 1 < idx.len() && matches!(tokens[idx[j + 1]].pos, Pos::Verb)) {
                        j += 1;
                        break;
                    }
                    j += 1;
                }
                if tokens[head].pos == Pos::Adv {
                    out.push(Chunk { kind: Phrase::ADVP, tokens: idx[start..j].to_vec(), head });
                } else {
                    out.push(Chunk { kind: Phrase::VP, tokens: idx[start..j].to_vec(), head });
                }
                i = j.max(i + 1);
            }
            Pos::Adp => {
                // PP = preposition + following NP (chunked recursively)
                let mut j = i + 1;
                while j < idx.len() && (np_word(tokens[idx[j]].pos) || matches!(tokens[idx[j]].pos, Pos::Det | Pos::Pron) || tokens[idx[j]].lower == "'s") {
                    j += 1;
                    if tokens[idx[j - 1]].pos == Pos::Pron {
                        break;
                    }
                }
                let span = idx[start..j].to_vec();
                let head = *span.iter().skip(1).rev().find(|&&k| tokens[k].pos.nominal()).unwrap_or(&idx[i]);
                out.push(Chunk { kind: Phrase::PP, tokens: span, head });
                i = j.max(i + 1);
            }
            Pos::Adv => {
                out.push(Chunk { kind: Phrase::ADVP, tokens: vec![idx[i]], head: idx[i] });
                i += 1;
            }
            _ => {
                out.push(Chunk { kind: Phrase::O, tokens: vec![idx[i]], head: idx[i] });
                i += 1;
            }
        }
    }
    out
}

// ------------------------------------------------------------ dependencies --

pub fn parse_clause(tokens: &[Token], clause: &Clause, ci: usize) -> ClauseParse {
    let chunks = chunk(tokens, &clause.tokens);
    let mut arcs: Vec<Arc> = Vec::new();
    let vp = chunks.iter().position(|c| c.kind == Phrase::VP);
    let mut root = None;
    let mut subject = None;
    let mut object = None;
    let (mut copular, mut passive, mut negated) = (false, false, false);
    if let Some(v) = vp {
        let vchunk = &chunks[v];
        let head = vchunk.head;
        let is_cop = tokens[head].pos == Pos::Aux && super::lexicon::COPULA.contains(&tokens[head].lemma.as_str());
        negated = vchunk.tokens.iter().any(|&k| matches!(tokens[k].lower.as_str(), "not" | "n't" | "never"));
        passive = tokens[head].pos == Pos::Verb
            && tokens[head].form == Form::Part
            || (tokens[head].form == Form::Past && vchunk.tokens.iter().any(|&k| tokens[k].pos == Pos::Aux && tokens[k].lemma == "be"));
        // subject: nearest NP before the VP
        subject = chunks[..v].iter().rev().find(|c| c.kind == Phrase::NP).map(|c| c.head);
        if is_cop {
            // copula: the predicate (ADJP/NP after the verb) is the root
            copular = true;
            if let Some(pred) = chunks[v + 1..].iter().find(|c| matches!(c.kind, Phrase::ADJP | Phrase::NP)) {
                root = Some(pred.head);
                arcs.push(Arc { dep: head, head: Some(pred.head), rel: "cop" });
            } else {
                root = Some(head);
            }
            passive = false;
        } else {
            root = Some(head);
            // object: first NP directly after the VP; a second NP makes the first iobj
            let after: Vec<&Chunk> = chunks[v + 1..].iter().take_while(|c| c.kind != Phrase::VP).collect();
            let nps: Vec<&&Chunk> = after.iter().take_while(|c| c.kind == Phrase::NP).collect();
            match nps.len() {
                0 => {}
                1 => object = Some(nps[0].head),
                _ => {
                    arcs.push(Arc { dep: nps[0].head, head: Some(head), rel: "iobj" });
                    object = Some(nps[1].head);
                }
            }
        }
        for &k in &vchunk.tokens {
            if k == head {
                continue;
            }
            let rel = match tokens[k].pos {
                Pos::Aux => {
                    if copular {
                        continue;
                    }
                    if passive && tokens[k].lemma == "be" { "aux:pass" } else { "aux" }
                }
                Pos::Part if matches!(tokens[k].lower.as_str(), "not" | "n't") => "advmod",
                Pos::Adv => "advmod",
                Pos::Verb => "xcomp",
                _ => "dep",
            };
            arcs.push(Arc { dep: k, head: Some(root.unwrap_or(head)), rel });
        }
    } else if let Some(c) = chunks.iter().find(|c| c.kind == Phrase::NP) {
        root = Some(c.head); // verbless fragment
    }
    let r = root;
    if let Some(r) = r {
        arcs.push(Arc { dep: r, head: None, rel: "root" });
    }
    if let (Some(s), Some(r)) = (subject, r) {
        arcs.push(Arc { dep: s, head: Some(r), rel: if passive { "nsubj:pass" } else { "nsubj" } });
    }
    if let (Some(o), Some(r)) = (object, r) {
        arcs.push(Arc { dep: o, head: Some(r), rel: "obj" });
    }
    // phrase-internal and attachment relations
    let mut last_np: Option<usize> = None;
    for (k, c) in chunks.iter().enumerate() {
        match c.kind {
            Phrase::NP | Phrase::ADJP => {
                let is_propn_run = c.tokens.iter().all(|&t| tokens[t].pos == Pos::Propn);
                let mut poss_owner: Option<usize> = None;
                for (j, &t) in c.tokens.iter().enumerate() {
                    if t == c.head {
                        continue;
                    }
                    if tokens[t].lower == "'s" {
                        // "X 's Y": X is poss of the head, 's is case
                        if j > 0 {
                            poss_owner = Some(c.tokens[j - 1]);
                        }
                        arcs.push(Arc { dep: t, head: poss_owner, rel: "case" });
                        continue;
                    }
                    let rel = match tokens[t].pos {
                        Pos::Det => "det",
                        Pos::Adj => "amod",
                        Pos::Num => "nummod",
                        Pos::Adv => "advmod",
                        Pos::Propn if is_propn_run => "flat",
                        Pos::Noun | Pos::Propn => {
                            if c.tokens.get(j + 1).map(|&n| tokens[n].lower == "'s").unwrap_or(false) {
                                "nmod:poss"
                            } else {
                                "compound"
                            }
                        }
                        _ => "dep",
                    };
                    let head = if is_propn_run { c.tokens[0] } else { c.head };
                    if t != head {
                        arcs.push(Arc { dep: t, head: Some(head), rel });
                    }
                }
                if c.kind == Phrase::NP {
                    last_np = Some(c.head);
                }
                if Some(c.head) != r && Some(c.head) != subject && Some(c.head) != object && c.kind == Phrase::NP {
                    // an NP right after another NP and a comma is an appositive
                    let prev_comma = k >= 2 && chunks[k - 1].tokens.len() == 1 && tokens[chunks[k - 1].tokens[0]].text == ",";
                    if prev_comma && chunks[k - 2].kind == Phrase::NP {
                        arcs.push(Arc { dep: c.head, head: Some(chunks[k - 2].head), rel: "appos" });
                    } else if let Some(r) = r {
                        if !arcs.iter().any(|a| a.dep == c.head) {
                            arcs.push(Arc { dep: c.head, head: Some(r), rel: "dep" });
                        }
                    }
                } else if c.kind == Phrase::ADJP && Some(c.head) != r {
                    if let Some(r) = r {
                        arcs.push(Arc { dep: c.head, head: Some(r), rel: "xcomp" });
                    }
                }
            }
            Phrase::PP => {
                let prep = c.tokens[0];
                if c.head != prep {
                    arcs.push(Arc { dep: prep, head: Some(c.head), rel: "case" });
                    for &t in &c.tokens[1..] {
                        if t != c.head {
                            let rel = match tokens[t].pos {
                                Pos::Det => "det",
                                Pos::Adj => "amod",
                                Pos::Num => "nummod",
                                _ => "compound",
                            };
                            arcs.push(Arc { dep: t, head: Some(c.head), rel });
                        }
                    }
                    // "of"-PP after a noun modifies the noun; others the verb
                    let attach_noun = tokens[prep].lower == "of" && last_np.is_some();
                    let (h, rel) = if attach_noun { (last_np, "nmod") } else { (r, "obl") };
                    if let Some(h) = h {
                        arcs.push(Arc { dep: c.head, head: Some(h), rel });
                    }
                }
            }
            Phrase::ADVP => {
                if let (Some(r), false) = (r, arcs.iter().any(|a| a.dep == c.head)) {
                    arcs.push(Arc { dep: c.head, head: Some(r), rel: "advmod" });
                }
            }
            Phrase::O => {
                for &t in &c.tokens {
                    let rel = match tokens[t].pos {
                        Pos::Punct => "punct",
                        Pos::Cconj => "cc",
                        Pos::Sconj => "mark",
                        _ => "dep",
                    };
                    if let Some(r) = r {
                        if t != r {
                            arcs.push(Arc { dep: t, head: Some(r), rel });
                        }
                    }
                }
            }
            Phrase::VP => {}
        }
    }
    arcs.sort_by_key(|a| a.dep);
    arcs.dedup_by_key(|a| a.dep);
    ClauseParse { clause: ci, chunks, root, subject, object, copular, passive, negated, arcs }
}

/// Bracketed constituency tree for a clause, e.g. (S (NP Mr. Collins) (VP refused) (NP the offer)).
pub fn tree(tokens: &[Token], p: &ClauseParse) -> String {
    let mut s = String::from("(S");
    for c in &p.chunks {
        let words: Vec<&str> = c.tokens.iter().map(|&k| tokens[k].text.as_str()).collect();
        let label = match c.kind {
            Phrase::NP => "NP",
            Phrase::VP => "VP",
            Phrase::PP => "PP",
            Phrase::ADJP => "ADJP",
            Phrase::ADVP => "ADVP",
            Phrase::O => tokens[c.head].pos.tag(),
        };
        s.push_str(&format!(" ({label} {})", words.join(" ")));
    }
    s.push(')');
    s
}

#[cfg(test)]
mod tests {
    use super::super::tag::{tag, tokenize};
    use super::*;

    fn analyse(s: &str, ents: &[(&str, usize)]) -> (Vec<Token>, Vec<Clause>) {
        let spans: Vec<(usize, usize, usize)> = ents.iter().map(|(n, e)| {
            let a = s.find(n).unwrap();
            (a, a + n.len(), *e)
        }).collect();
        let mut t = tokenize(s);
        tag(&mut t, &spans);
        let c = clauses(&t);
        (t, c)
    }

    #[test]
    fn svo_and_copula() {
        let (t, c) = analyse("Mr. Collins refused the generous offer.", &[("Mr. Collins", 0)]);
        assert_eq!(c.len(), 1);
        let p = parse_clause(&t, &c[0], 0);
        assert_eq!(t[p.root.unwrap()].text, "refused");
        assert_eq!(t[p.subject.unwrap()].text, "Collins");
        assert_eq!(t[p.object.unwrap()].text, "offer");
        assert_eq!(tree(&t, &p), "(S (NP Mr. Collins) (VP refused) (NP the generous offer) (PUNCT .))");
        let (t, c) = analyse("Jane was not happy.", &[("Jane", 1)]);
        let p = parse_clause(&t, &c[0], 0);
        assert!(p.copular && p.negated);
        assert_eq!(t[p.root.unwrap()].text, "happy");
    }

    #[test]
    fn clause_decomposition() {
        let (t, c) = analyse("Mr. Darcy, who was proud, refused to dance, and Elizabeth laughed because she was amused.", &[("Mr. Darcy", 0), ("Elizabeth", 1)]);
        let kinds: Vec<ClauseKind> = c.iter().map(|c| c.kind).collect();
        assert!(kinds.contains(&ClauseKind::Relative), "{kinds:?}");
        assert!(kinds.contains(&ClauseKind::Coordinate), "{kinds:?}");
        assert!(kinds.contains(&ClauseKind::Subordinate), "{kinds:?}");
        let rel = c.iter().find(|c| c.kind == ClauseKind::Relative).unwrap();
        assert_eq!(t[rel.antecedent.unwrap()].text, "Darcy");
        let main = &c[c.iter().position(|c| c.kind == ClauseKind::Main).unwrap()];
        let words: Vec<&str> = main.tokens.iter().map(|&k| t[k].text.as_str()).collect();
        assert!(words.contains(&"refused") && words.contains(&"Darcy"), "{words:?}");
    }
}
