//! Standard Q&A (QBF-C046) and the reader modes built on the same path:
//! scope (D8) -> FQL retrieval -> admission threshold -> pre-activation under
//! the traversal budget -> attractor stabilization -> D7 realization, with the
//! context-lock key, convergence disclosure and FQL returned with the answer.

use super::attractor::{Convergence, Network};
use super::fql::{Fql, compile};
use crate::app::QueryBook;
use crate::d0::context_lock::ContextDims;
use crate::d0::{Domain, Trace};
use crate::d2::{EdgeClass, FactUnit};
use crate::d7::{self, Opts, Order};
use crate::d8::Scope;
use crate::util::{canon_text, content_words, sha256_hex, words};
use rusqlite::params;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::time::Instant;

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Request {
    #[serde(default)]
    pub mode: String,
    #[serde(default)]
    pub query: String,
    #[serde(default)]
    pub chapter: Option<u32>,
    /// concept chosen from a clarification, or the subject of explore/timeline
    #[serde(default)]
    pub focus: Option<String>,
    #[serde(default)]
    pub device: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Citation {
    pub n: usize,
    pub fuid: String,
    pub fingerprint: String,
    pub predicate: String,
    pub rendered: String,
    pub quote: String,
    pub pos: u64,
    /// EPUB CFI of the source paragraph (language pipeline stage 5), when known
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cfi: Option<String>,
    pub chapter: u32,
    pub chapter_title: String,
    pub confidence: f64,
    pub lower: f64,
    pub trust: f64,
    pub alpha: f64,
    pub beta: f64,
    pub diversity: f64,
    pub sources: Vec<String>,
    pub engine: String,
    pub verified: bool,
    pub safety: String,
    pub status: String,
    pub restated: usize,
    pub ledger_node: u64,
    pub activation: f64,
    pub work: String,
    /// source class for records from outside the book (e.g. "ufcs:feed")
    pub corpus: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Line {
    pub text: String,
    pub cites: Vec<usize>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Section {
    pub title: String,
    pub lines: Vec<Line>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Option_ {
    pub label: String,
    pub concept: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Clarify {
    pub question: String,
    pub options: Vec<Option_>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Neighbor {
    pub concept: String,
    pub label: String,
    pub strength: u32,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Card {
    pub fuid: String,
    pub front: String,
    pub back: String,
    pub cite: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct QuizItem {
    pub prompt: String,
    pub options: Vec<String>,
    pub answer: usize,
    pub cite: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Answer {
    pub mode: String,
    pub query: String,
    /// "answered" | "not-in-book" | "beyond-position" | "clarify"
    pub status: String,
    pub message: String,
    pub lines: Vec<Line>,
    pub sections: Vec<Section>,
    pub citations: Vec<Citation>,
    pub clarify: Option<Clarify>,
    pub neighbors: Vec<Neighbor>,
    pub cards: Vec<Card>,
    pub quiz: Vec<QuizItem>,
    pub served_from: String,
    pub convergence: Option<Convergence>,
    pub regime: String,
    pub fql: String,
    pub scope: ScopeSummary,
    pub context_key: String,
    pub output_hash: String,
    pub trace: Vec<String>,
    pub candidates: usize,
    pub rejected_propositions: usize,
    pub ms: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct ScopeSummary {
    pub work: String,
    pub marker: u64,
    pub spoiler_bounded: bool,
    pub corpora: Vec<String>,
}

impl Answer {
    fn new(mode: &str, query: &str) -> Answer {
        Answer {
            mode: mode.into(),
            query: query.into(),
            status: "answered".into(),
            message: String::new(),
            lines: vec![],
            sections: vec![],
            citations: vec![],
            clarify: None,
            neighbors: vec![],
            cards: vec![],
            quiz: vec![],
            served_from: "live".into(),
            convergence: None,
            regime: String::new(),
            fql: String::new(),
            scope: ScopeSummary::default(),
            context_key: String::new(),
            output_hash: String::new(),
            trace: vec![],
            candidates: 0,
            rejected_propositions: 0,
            ms: 0.0,
        }
    }

    /// Hash over the deliverable output only (not timing or trace).
    pub fn compute_hash(&self) -> String {
        let v = serde_json::json!({
            "mode": self.mode, "status": self.status, "message": self.message, "lines": self.lines,
            "sections": self.sections, "citations": self.citations.iter().map(|c| (&c.fuid, c.n)).collect::<Vec<_>>(),
            "clarify": self.clarify, "neighbors": self.neighbors, "cards": self.cards, "quiz": self.quiz,
        });
        sha256_hex(v.to_string().as_bytes())
    }
}

// ------------------------------------------------------------ analysis ----

#[derive(Clone, Debug)]
pub struct Focus {
    pub concept: String,
    pub label: String,
    pub freq: i64,
}

#[derive(Debug, Default)]
pub struct Analysis {
    pub qtype: &'static str,
    pub focus: Vec<Focus>,
    pub ambiguous: Option<(String, Vec<Focus>)>,
    pub terms: Vec<String>,
    pub prefer: Vec<&'static str>,
}

fn qtype(q: &str) -> &'static str {
    let w = words(q);
    let first = w.first().map(|s| s.as_str()).unwrap_or("");
    let has = |k: &str| w.iter().any(|x| x == k);
    if has("mean") || has("meaning") || has("define") || has("definition") {
        "define"
    } else if (has("say") || has("said") || has("says")) && !has("book") {
        "quote"
    } else if has("related") || has("relation") || has("relationship") || has("married") || has("marry") {
        "relation"
    } else {
        match first {
            "who" | "whom" | "whose" => "who",
            "where" => "where",
            "when" => "when",
            "why" => "why",
            "how" => "how",
            "what" | "which" => "what",
            "is" | "was" | "did" | "does" | "do" | "are" | "were" | "has" | "had" | "can" => "yesno",
            _ => "other",
        }
    }
}

fn prefer_for(qt: &str, q: &str) -> Vec<&'static str> {
    let w = words(q);
    let has = |k: &[&str]| w.iter().any(|x| k.contains(&x.as_str()));
    let mut p: Vec<&'static str> = match qt {
        "who" => vec!["is_a", "relative_of", "has_trait", "member_of"],
        "where" => vec!["lives_in", "located_in", "visits", "occurs_in"],
        "when" => vec!["occurs_in", "performs", "visits"],
        "why" => vec!["causes", "believes", "feels", "states"],
        "define" => vec!["defined_as", "is_a"],
        "quote" => vec!["says"],
        "relation" => vec!["relative_of", "married_to", "engaged_to", "loves", "friend_of"],
        "how" => vec!["performs", "recommends", "states", "causes"],
        _ => vec!["performs", "is_a", "states"],
    };
    if has(&["marry", "married", "marries", "wife", "husband", "wedding"]) {
        p.extend(["married_to", "engaged_to"]);
    }
    if has(&["love", "loves", "loved", "affection"]) {
        p.push("loves");
    }
    if has(&["sister", "brother", "father", "mother", "aunt", "uncle", "cousin", "daughter", "son", "family"]) {
        p.push("relative_of");
    }
    if has(&["live", "lives", "lived", "home", "house", "estate"]) {
        p.push("lives_in");
    }
    if has(&["feel", "feels", "felt", "think", "thinks", "thought", "opinion"]) {
        p.extend(["feels", "believes"]);
    }
    // measurement and reference cues (the world-knowledge predicates)
    if has(&["long", "length"]) {
        p.push("length");
    }
    if has(&["tall", "high", "height", "elevation"]) {
        p.extend(["height", "elevation"]);
    }
    if has(&["big", "large", "area", "size"]) {
        p.push("area");
    }
    if has(&["population", "people", "inhabitants", "populous"]) {
        p.push("population");
    }
    if has(&["born", "birth"]) {
        p.push(if qt == "where" { "born_in" } else { "born_in_year" });
    }
    if has(&["die", "died", "death"]) {
        p.push(if qt == "where" { "died_in" } else { "died_in_year" });
    }
    if has(&["discovered", "discover", "invented", "invent", "inventor", "discoverer"]) {
        p.extend(["discoverer", "discovered_in", "invented_in"]);
    }
    if has(&["capital"]) {
        p.push("capital");
    }
    if has(&["currency", "money"]) {
        p.push("currency");
    }
    if has(&["language", "speak", "spoken"]) {
        p.push("official_language");
    }
    if has(&["moons", "moon", "satellites"]) {
        p.push("natural_satellite");
    }
    p.sort();
    p.dedup();
    p
}

fn alias_rows(qb: &QueryBook, work: &str, grams: &[String]) -> anyhow::Result<Vec<(String, String, String, i64, u64)>> {
    if grams.is_empty() {
        return Ok(vec![]);
    }
    qb.store.read(|c| {
        let mut out = Vec::new();
        let mut st = c.prepare_cached(
            "SELECT alias, concept, label, freq, first_pos FROM aliases WHERE work=?1 AND alias=?2 ORDER BY freq DESC, concept",
        )?;
        for g in grams {
            let rows =
                st.query_map(params![work, g], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get::<_, i64>(4)? as u64)))?;
            for r in rows {
                out.push(r?);
            }
        }
        Ok(out)
    })
}

/// Concepts whose label contains the token (partial-name matches).
fn partial_matches(qb: &QueryBook, work: &str, token: &str, marker: u64) -> anyhow::Result<Vec<Focus>> {
    qb.store.read(|c| {
        let mut st = c.prepare_cached(
            "SELECT concept, label, MAX(freq) FROM aliases WHERE work=?1 AND (' ' || alias || ' ') LIKE ?2 AND first_pos <= ?3 GROUP BY concept ORDER BY MAX(freq) DESC, concept LIMIT 8",
        )?;
        let rows = st.query_map(params![work, format!("% {token} %"), marker.min(i64::MAX as u64) as i64], |r| {
            Ok(Focus { concept: r.get(0)?, label: r.get(1)?, freq: r.get(2)? })
        })?;
        Ok(rows.collect::<Result<_, _>>()?)
    })
}

pub fn analyze(qb: &QueryBook, scope: &Scope, q: &str, focus_param: Option<&str>) -> anyhow::Result<Analysis> {
    let qt = qtype(q);
    let mut a = Analysis { qtype: qt, prefer: prefer_for(qt, q), ..Default::default() };
    let ws: Vec<String> = words(q).into_iter().map(|w| crate::d1::segment::base_form(&w).to_string()).collect();
    let work = scope.primary_work().unwrap_or("").to_string();
    let marker = if scope.spoiler_bounded() { scope.marker() } else { u64::MAX };
    let mut used = vec![false; ws.len()];
    if let Some(f) = focus_param {
        let label = qb
            .store
            .read(|c| Ok(c.query_row("SELECT label FROM aliases WHERE concept=?1 LIMIT 1", [f], |r| r.get::<_, String>(0)).ok()))?
            .unwrap_or_else(|| crate::d2::fact::humanize_concept(f));
        a.focus.push(Focus { concept: f.to_string(), label, freq: 0 });
    }
    // longest-first n-gram match against the work's alias table
    for len in (1..=4usize).rev() {
        for i in 0..ws.len().saturating_sub(len - 1) {
            if used[i..i + len].iter().any(|u| *u) {
                continue;
            }
            let gram = ws[i..i + len].join(" ");
            if len == 1 && (crate::util::is_stopword(&gram) || gram.len() < 3) {
                continue;
            }
            let rows = alias_rows(qb, &work, &[crate::util::alias_key(&gram)])?;
            let rows: Vec<_> = rows.into_iter().filter(|r| r.4 <= marker).collect();
            if let Some(best) = rows.first() {
                for u in &mut used[i..i + len] {
                    *u = true;
                }
                if !a.focus.iter().any(|f| f.concept == best.1) {
                    a.focus.push(Focus { concept: best.1.clone(), label: best.2.clone(), freq: best.3 });
                }
                // a bare surname also reaches the titled forms of that name
                if len == 1 {
                    for pm in partial_matches(qb, &work, &gram, marker)? {
                        if pm.concept != best.1
                            && pm.freq * 2 >= best.3
                            && !a.focus.iter().any(|f| f.concept == pm.concept)
                            && a.focus.len() < 4
                        {
                            a.focus.push(pm);
                        }
                    }
                }
            } else if len == 1 && focus_param.is_none() && ws[i].chars().count() >= 3 && !crate::util::is_stopword(&ws[i]) {
                // no exact alias: a partial name with no dominant referent asks for clarification
                let pm = partial_matches(qb, &work, &ws[i], marker)?;
                let pm: Vec<Focus> = pm.into_iter().filter(|p| p.freq >= 3).collect();
                if pm.len() >= 2 && pm[0].freq < 3 * pm[1].freq {
                    a.ambiguous = Some((ws[i].clone(), pm.into_iter().take(5).collect()));
                    used[i] = true;
                } else if let Some(p) = pm.into_iter().next() {
                    used[i] = true;
                    a.focus.push(p);
                }
            }
        }
    }
    a.terms = content_words(q).into_iter().filter(|w| w.len() > 2).collect();
    Ok(a)
}

// ----------------------------------------------------------- retrieval ----

pub struct Retrieved {
    pub facts: Vec<(f64, FactUnit)>,
    pub fql: String,
}

/// Execute FQL under a scope and load the records (D4 -> D2 read).
pub fn retrieve(qb: &QueryBook, scope: &Scope, q: &Fql) -> anyhow::Result<Retrieved> {
    let query = compile(&qb.store.index, scope, q);
    let hits = qb.store.index.search(query.as_ref(), q.limit)?;
    let fuids: Vec<String> = hits.iter().map(|h| h.1.clone()).collect();
    let scores: BTreeMap<&str, f32> = hits.iter().map(|(s, f)| (f.as_str(), *s)).collect();
    let mut facts = Vec::with_capacity(fuids.len());
    let mut loaded = qb.store.get_many(&fuids)?;
    qb.store.fold_adjustments(&mut loaded)?;
    for f in loaded {
        // defence in depth: the record's own ACL and position must admit it
        let pos = f.narrative.as_ref().map(|n| n.pos).unwrap_or(0);
        if !scope.admits(f.work(), pos) || !f.acl.iter().any(|a| scope.acl().contains(a)) {
            continue;
        }
        let s = scores.get(f.fuid.as_str()).copied().unwrap_or(0.0) as f64;
        facts.push((s, f));
    }
    facts.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal).then_with(|| a.1.fuid.cmp(&b.1.fuid)));
    Ok(Retrieved { facts, fql: q.render(scope) })
}

fn inconsistent(a: &FactUnit, b: &FactUnit, functional: &BTreeSet<String>) -> bool {
    if a.atom.subject != b.atom.subject || a.atom.predicate != b.atom.predicate {
        return false;
    }
    if a.atom.object == b.atom.object && a.atom.args == b.atom.args {
        return a.atom.polarity != b.atom.polarity;
    }
    functional.contains(&a.atom.predicate) && a.atom.polarity && b.atom.polarity
}

pub struct Stable {
    pub facts: Vec<(f64, FactUnit)>,
    pub convergence: Convergence,
    pub conflict: Option<(usize, usize)>,
}

/// Pre-activation under the edge-class traversal budget, then attractor
/// settling over the admitted set. Returns the stabilized set (activation > 0),
/// best first.
pub fn stabilize(
    qb: &QueryBook,
    scope: &Scope,
    mut cands: Vec<(f64, FactUnit)>,
    focus: &[Focus],
    prefer: &[&str],
    query_text: &str,
) -> anyhow::Result<Stable> {
    let cfg = &qb.cfg;
    // (C067/C068) follow typed edges from the strongest seeds while budget remains
    let t = &cfg.traversal;
    let present: BTreeSet<String> = cands.iter().map(|c| c.1.fuid.clone()).collect();
    let mut extra: Vec<(f64, FactUnit)> = Vec::new();
    for (score, f) in cands.iter().take(12) {
        for e in &f.edges {
            let cost = match e.class {
                EdgeClass::Semantic => t.semantic,
                EdgeClass::Editorial => t.editorial,
                EdgeClass::Temporal => t.temporal,
            };
            if cost > t.budget || present.contains(&e.target) || extra.iter().any(|x| x.1.fuid == e.target) {
                continue;
            }
            if let Some(n) = qb.store.get(&e.target)? {
                let pos = n.narrative.as_ref().map(|n| n.pos).unwrap_or(0);
                if scope.admits(n.work(), pos)
                    && n.trust() >= cfg.retrieval.admission_threshold
                    && !qb.store.is_superseded(&n.fuid)?
                {
                    extra.push((score * 0.5 * (1.0 - cost / (t.budget + 1.0)), n));
                }
            }
        }
    }
    cands.extend(extra);
    cands.truncate(cfg.retrieval.max_units);
    let max = cands.iter().map(|c| c.0).fold(0.0f64, f64::max).max(1e-9);
    let focus_set: BTreeSet<&str> = focus.iter().map(|f| f.concept.as_str()).collect();
    let functional: BTreeSet<String> =
        qb.catalog.read().unwrap().predicates.values().filter(|p| p.functional).map(|p| p.id.clone()).collect();
    // Stage 7 (language pipeline): the query is embedded into the same
    // random-indexing space as the records (its content lemmas and focus
    // concepts); semantic closeness raises a candidate's bias
    let qvec = {
        use crate::d1::language::embed;
        let mut feats = embed::text_features(query_text, 1.0);
        feats.extend(focus.iter().map(|f| (format!("c:{}", f.concept), 2.0f32)));
        embed::from_features(&feats)
    };
    // the question naming a record's predicate ("atomic number", "employees")
    // is evidence for that record over its neighbours ("atomic weight")
    let stem = |w: &str| w.trim_end_matches('s').to_string();
    let qwords: BTreeSet<String> = crate::util::content_words(query_text).iter().map(|w| stem(w)).collect();
    let pred_overlap = |pred: &str| -> f64 {
        let pw: Vec<String> = pred
            .trim_start_matches("ufcs:")
            .split('_')
            .filter(|w| w.len() > 2 && !crate::util::is_stopword(w) && !matches!(*w, "has" | "value"))
            .map(stem)
            .collect();
        if pw.is_empty() {
            return 0.0;
        }
        pw.iter().filter(|w| qwords.contains(*w)).count() as f64 / pw.len() as f64
    };
    let bias: Vec<f64> = cands
        .iter()
        .map(|(s, f)| {
            let mut r = (s / max) * (0.5 + 0.5 * f.trust());
            r *= 1.0 + 0.6 * pred_overlap(&f.atom.predicate);
            // the question naming the record's subject outright ("Argentina",
            // "Frankenstein") decides between otherwise similar records
            let sw: Vec<String> = crate::util::content_words(&f.label(&f.atom.subject)).iter().map(|w| stem(w)).collect();
            if !sw.is_empty() && sw.iter().all(|w| qwords.contains(w)) {
                r *= 1.8;
            }
            if let Some(v) = f.embedding.as_deref().and_then(crate::d1::language::embed::dequantize) {
                r *= 1.0 + 0.5 * crate::d1::language::embed::cosine(&qvec, &v).max(0.0) as f64;
            }
            if prefer.contains(&f.atom.predicate.trim_start_matches("ufcs:")) {
                r *= 1.4;
            }
            if focus_set.contains(f.atom.subject.as_str()) {
                r *= 1.3;
            }
            r
        })
        .collect();
    // threshold relative to the strongest candidate: weak, isolated records
    // start below zero and survive only with support from the cluster
    let rmax = bias.iter().cloned().fold(0.0f64, f64::max);
    let bias: Vec<f64> = bias.into_iter().map(|r| r - 0.45 * rmax).collect();
    let mut net = Network::new(bias);
    let mut interpretations = 1;
    for i in 0..cands.len() {
        for j in i + 1..cands.len() {
            let (a, b) = (&cands[i].1, &cands[j].1);
            if inconsistent(a, b, &functional) {
                net.connect(i, j, -0.8);
                interpretations += 1;
                continue;
            }
            // mild global inhibition: only a mutually supporting cluster survives
            let mut w = -0.08;
            if a.atom.subject == b.atom.subject {
                w += 0.25;
            } else if a.atom.concepts().iter().any(|c| b.atom.concepts().contains(c)) {
                w += 0.12;
            }
            if a.edges.iter().any(|e| e.target == b.fuid) || b.edges.iter().any(|e| e.target == a.fuid) {
                w += 0.2;
            }
            if a.fingerprint == b.fingerprint {
                w += 0.1;
            }
            net.connect(i, j, w);
        }
    }
    net.normalize(0.6);
    let bias_dbg = net.bias.clone();
    let (act, conv) = net.settle(&cfg.convergence.regime, cfg.convergence.spectral_bound, interpretations);
    if std::env::var("QB_DEBUG").is_ok() {
        let mut v: Vec<(f64, f64, &FactUnit)> =
            cands.iter().zip(act.iter()).zip(bias_dbg.iter()).map(|(((_, f), a), b)| (*a, *b, f)).collect();
        v.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
        for (a, b, f) in v.iter().take(12) {
            eprintln!(
                "  act {a:.3} bias {b:.3} trust {:.2} {} {} {}",
                f.trust(),
                f.atom.subject,
                f.atom.predicate,
                crate::util::clip(f.quote.as_deref().unwrap_or(""), 60)
            );
        }
    }
    let mut out: Vec<(f64, FactUnit)> = cands.into_iter().zip(act).filter(|(_, a)| *a > 0.0).map(|((_, f), a)| (a, f)).collect();
    out.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal).then_with(|| a.1.fuid.cmp(&b.1.fuid)));
    // (C074) two inconsistent survivors at comparable activation do not resolve
    let mut conflict = None;
    'outer: for i in 0..out.len().min(6) {
        for j in i + 1..out.len().min(6) {
            if inconsistent(&out[i].1, &out[j].1, &functional) && out[j].0 >= 0.9 * out[i].0 {
                conflict = Some((i, j));
                break 'outer;
            }
        }
    }
    Ok(Stable { facts: out, convergence: conv, conflict })
}

// ------------------------------------------------------------- answers ----

pub fn chapter_titles(qb: &QueryBook, work: &str) -> Vec<(u32, String, u64, u64)> {
    crate::d8::work(qb, work)
        .ok()
        .flatten()
        .and_then(|w| serde_json::from_value::<Vec<crate::d1::parse::Chapter>>(w.chapters).ok())
        .map(|v| v.into_iter().map(|c| (c.index, c.title, c.start, c.end)).collect())
        .unwrap_or_default()
}

struct Builder<'a> {
    qb: &'a QueryBook,
    ans: Answer,
    cited: Vec<String>,
    chapters: Vec<(u32, String, u64, u64)>,
}

impl<'a> Builder<'a> {
    fn cite(&mut self, f: &FactUnit, activation: f64) -> usize {
        if let Some(i) = self.cited.iter().position(|x| *x == f.fuid) {
            return i + 1;
        }
        self.cited.push(f.fuid.clone());
        let n = self.cited.len();
        let catalog = self.qb.catalog.read().unwrap();
        let rendered = d7::realize(&[f], &catalog, Opts { order: Order::AsGiven, aggregate: false, connectives: false })
            .sentences
            .first()
            .map(|s| s.text.clone())
            .unwrap_or_default();
        let (pos, chapter) = f.narrative.as_ref().map(|n| (n.pos, n.chapter)).unwrap_or((0, 0));
        let chapter_title = self.chapters.iter().find(|c| c.0 == chapter).map(|c| c.1.clone()).unwrap_or_default();
        self.ans.citations.push(Citation {
            n,
            fuid: f.fuid.clone(),
            fingerprint: f.fingerprint.clone(),
            predicate: f.atom.predicate.clone(),
            rendered,
            quote: f.quote.clone().unwrap_or_default(),
            pos,
            cfi: f.narrative.as_ref().and_then(|n| n.cfi.clone()),
            chapter,
            chapter_title,
            confidence: round(f.evidence.confidence()),
            lower: round(f.evidence.lower()),
            trust: f.trust(),
            alpha: round(f.evidence.alpha),
            beta: round(f.evidence.beta),
            diversity: round(f.evidence.diversity()),
            sources: f.evidence.by_class.keys().cloned().collect(),
            engine: f.derivation.engine.clone().unwrap_or_else(|| f.derivation.kind.clone()),
            verified: f.derivation.citation_verified.unwrap_or(true),
            safety: f.safety.label().into(),
            status: f.status().into(),
            restated: f.narrative.as_ref().map(|n| n.also.len()).unwrap_or(0),
            ledger_node: f.provenance.batch,
            activation: round(activation),
            work: f.work().unwrap_or("").into(),
            corpus: if f.narrative.is_none() { f.source.class.clone() } else { String::new() },
        });
        n
    }

    fn lines(&mut self, facts: &[(f64, FactUnit)], order: Order) -> Vec<Line> {
        let refs: Vec<&FactUnit> = facts.iter().map(|f| &f.1).collect();
        let catalog = self.qb.catalog.read().unwrap().clone();
        let r = d7::realize(&refs, &catalog, Opts { order, aggregate: true, connectives: true });
        self.ans.rejected_propositions += r.rejected;
        r.sentences
            .into_iter()
            .map(|s| {
                let cites = s.cites.iter().map(|&i| self.cite(&facts[i].1, facts[i].0)).collect();
                Line { text: s.text, cites }
            })
            .collect()
    }
}

fn round(x: f64) -> f64 {
    (x * 1e4).round() / 1e4
}

/// Pick the answer set: best first, no duplicate spans, capped per kind.
fn select(stable: &[(f64, FactUnit)], n: usize) -> Vec<(f64, FactUnit)> {
    let mut out: Vec<(f64, FactUnit)> = Vec::new();
    let mut quotes = BTreeSet::new();
    let mut per: BTreeMap<&str, usize> = BTreeMap::new();
    for (a, f) in stable {
        let q = canon_text(f.quote.as_deref().unwrap_or(""));
        let cap = match f.atom.predicate.as_str() {
            "states" => 3,
            "says" => 2,
            _ => 4,
        };
        let c = per.entry(f.atom.predicate.as_str()).or_insert(0);
        if *c >= cap || (f.atom.predicate == "states" && !quotes.insert(q)) {
            continue;
        }
        *c += 1;
        out.push((*a, f.clone()));
        if out.len() >= n {
            break;
        }
    }
    out
}

pub fn answer(qb: &QueryBook, scope: &Scope, req: &Request, mut trace: Trace) -> anyhow::Result<Answer> {
    let t0 = Instant::now();
    qb.refresh_catalog()?;
    let mode = if req.mode.is_empty() { "ask" } else { req.mode.as_str() };
    let work = scope.primary_work().unwrap_or("").to_string();
    let dims = ContextDims {
        device: if req.device.is_empty() { "web".into() } else { req.device.clone() },
        entitlement: scope.entitlement_dims(),
        locale: "en".into(),
        register: "plain".into(),
        audience: "general".into(),
        posture: "attested-past".into(),
        costs: qb.cost_table(),
        regime: qb.cfg.convergence.regime.clone(),
        store: qb.store.version(),
    };
    let mut b = Builder { qb, ans: Answer::new(mode, &req.query), cited: vec![], chapters: chapter_titles(qb, &work) };
    b.ans.regime = qb.regime_label();
    b.ans.scope = ScopeSummary {
        work: work.clone(),
        marker: scope.marker(),
        spoiler_bounded: scope.spoiler_bounded(),
        corpora: scope.corpora().to_vec(),
    };
    b.ans.context_key = dims.key();

    match mode {
        "ask" => ask(&mut b, scope, req, &mut trace)?,
        "summary" => summary(&mut b, scope, req.chapter, &mut trace)?,
        "recap" | "outline" => recap(&mut b, scope, &mut trace)?,
        "who" => whos_who(&mut b, scope, &mut trace)?,
        "timeline" => timeline(&mut b, scope, req, &mut trace)?,
        "explore" => explore(&mut b, scope, req, &mut trace)?,
        "flashcards" | "quiz" => crate::d14::study(&mut StudyCtx { b: &mut b }, scope, mode, req.chapter, &mut trace)?,
        m => anyhow::bail!("unknown mode '{m}'"),
    }
    if b.ans.status == "answered"
        && b.ans.lines.is_empty()
        && b.ans.sections.is_empty()
        && b.ans.cards.is_empty()
        && b.ans.quiz.is_empty()
        && b.ans.neighbors.is_empty()
    {
        b.ans.status = "not-in-book".into();
    }
    let _ = trace.cross(Domain::D4, Domain::D9, "deliver");
    b.ans.trace = trace.crossings.iter().map(|c| format!("{}→{} {} [{}]", c.from, c.to, c.op, c.permission)).collect();
    b.ans.output_hash = b.ans.compute_hash();
    b.ans.ms = (t0.elapsed().as_secs_f64() * 1000.0 * 10.0).round() / 10.0;
    Ok(b.ans)
}

/// Lets D14 build on the same builder without widening D4's surface.
pub struct StudyCtx<'x, 'a> {
    b: &'x mut Builder<'a>,
}

impl<'x, 'a> StudyCtx<'x, 'a> {
    pub fn qb(&self) -> &'a QueryBook {
        self.b.qb
    }
    pub fn cite(&mut self, f: &FactUnit) -> usize {
        self.b.cite(f, 1.0)
    }
    pub fn render(&self, f: &FactUnit) -> String {
        let catalog = self.b.qb.catalog.read().unwrap();
        d7::realize(&[f], &catalog, Opts { order: Order::AsGiven, aggregate: false, connectives: false })
            .sentences
            .first()
            .map(|s| s.text.clone())
            .unwrap_or_default()
    }
    pub fn push_card(&mut self, c: Card) {
        self.b.ans.cards.push(c);
    }
    pub fn push_quiz(&mut self, q: QuizItem) {
        self.b.ans.quiz.push(q);
    }
    pub fn set_fql(&mut self, s: String) {
        self.b.ans.fql = s;
    }
    pub fn set_status(&mut self, s: &str, msg: &str) {
        self.b.ans.status = s.into();
        self.b.ans.message = msg.into();
    }
    pub fn chapter_bounds(&self, ch: u32) -> Option<(u64, u64)> {
        self.b.chapters.iter().find(|c| c.0 == ch).map(|c| (c.2, c.3))
    }
}

fn ask(b: &mut Builder, scope: &Scope, req: &Request, trace: &mut Trace) -> anyhow::Result<()> {
    let qb = b.qb;
    let a = analyze(qb, scope, &req.query, req.focus.as_deref())?;
    if let Some((token, opts)) = &a.ambiguous {
        if a.focus.is_empty() {
            // (C060) anchored clarification rather than a guess
            b.ans.status = "clarify".into();
            b.ans.clarify = Some(Clarify {
                question: format!("“{}” could mean more than one person or thing in this book. Which one?", token),
                options: opts.iter().map(|o| Option_ { label: o.label.clone(), concept: o.concept.clone() }).collect(),
            });
            return Ok(());
        }
    }
    // (C084) pre-computed answer reuse
    if req.focus.is_none() {
        if let Some(pre) = super::pqg::lookup(qb, scope, &req.query)? {
            b.ans.lines = pre.lines;
            b.ans.citations = pre.citations;
            b.cited = b.ans.citations.iter().map(|c| c.fuid.clone()).collect();
            b.ans.served_from = "precomputed".into();
            b.ans.fql = "served from the Question Index (pre-computed at ingestion; every contributing record verified unrevised and inside your scope)".into();
            return Ok(());
        }
    }
    let q = Fql {
        text: a.terms.clone(),
        concepts: a.focus.iter().map(|f| f.concept.clone()).collect(),
        // with world corpora enabled, book concepts boost rather than filter,
        // since imported records carry their own concept identifiers
        require_concept: !a.focus.is_empty() && scope.corpora().is_empty(),
        prefer_predicates: a.prefer.iter().map(|s| s.to_string()).collect(),
        only_predicates: vec![],
        chapter: None,
        min_trust: qb.cfg.retrieval.admission_threshold,
        limit: qb.cfg.retrieval.candidates,
    };
    let r = if scope.corpora().is_empty() {
        retrieve(qb, scope, &q)?
    } else {
        // book and world corpora are ranked separately and normalized, so a
        // large book cannot crowd imported knowledge out of the candidate set
        let book = retrieve(qb, &scope.book_only(), &q)?;
        let world = retrieve(qb, &scope.world_only(), &Fql { require_concept: false, concepts: vec![], ..q.clone() })?;
        if std::env::var("QB_DEBUG").is_ok() {
            eprintln!("  book candidates {}, world candidates {}", book.facts.len(), world.facts.len());
        }
        let norm = |v: Vec<(f64, FactUnit)>| {
            let m = v.iter().map(|x| x.0).fold(0.0f64, f64::max).max(1e-9);
            v.into_iter().map(move |(s, f)| (s / m, f))
        };
        let mut facts: Vec<(f64, FactUnit)> = norm(book.facts).chain(norm(world.facts)).collect();
        facts.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal).then_with(|| a.1.fuid.cmp(&b.1.fuid)));
        Retrieved { facts, fql: format!("{}\n-- merged with --\n{}", book.fql, world.fql) }
    };
    b.ans.fql = r.fql;
    b.ans.candidates = r.facts.len();
    if r.facts.is_empty() {
        return no_answer(b, scope, &q);
    }
    let _ = trace.cross(Domain::D4, Domain::D5, "stabilize");
    let st = stabilize(qb, scope, r.facts, &a.focus, &a.prefer, &req.query)?;
    b.ans.convergence = Some(st.convergence.clone());
    if let Some((i, j)) = st.conflict {
        b.ans.status = "clarify".into();
        let li = b.cite(&st.facts[i].1, st.facts[i].0);
        let lj = b.cite(&st.facts[j].1, st.facts[j].0);
        b.ans.clarify = Some(Clarify {
            question: "The book supports two answers that cannot both hold, equally well. Which situation do you mean?".into(),
            options: vec![],
        });
        b.ans.lines = vec![
            Line { text: b.ans.citations[li - 1].rendered.clone(), cites: vec![li] },
            Line { text: b.ans.citations[lj - 1].rendered.clone(), cites: vec![lj] },
        ];
        return Ok(());
    }
    if st.facts.is_empty() {
        return no_answer(b, scope, &q);
    }
    let _ = trace.cross(Domain::D5, Domain::D7, "realize");
    let chosen = select(&st.facts, qb.cfg.retrieval.answer_facts);
    b.ans.lines = b.lines(&chosen, Order::AsGiven);
    Ok(())
}

/// Nothing inside scope. Say whether the book addresses it later (without
/// disclosing anything), or that it does not say.
fn no_answer(b: &mut Builder, scope: &Scope, q: &Fql) -> anyhow::Result<()> {
    if scope.spoiler_bounded() {
        let probe = scope.unbounded_probe();
        let n = b.qb.store.index.count(compile(&b.qb.store.index, &probe, q).as_ref())?;
        if n > 0 {
            b.ans.status = "beyond-position".into();
            b.ans.message = "The book takes this up later than where you are reading. Spoiler protection keeps it hidden until you get there; you can switch protection off in the panel.".into();
            return Ok(());
        }
    }
    b.ans.status = "not-in-book".into();
    b.ans.message =
        "The book doesn’t say. QueryBook found no grounded record for this within your scope, and it will not guess.".into();
    Ok(())
}

/// Centrality-ranked facts of a region, realized in narrative order.
fn salient(facts: Vec<(f64, FactUnit)>, n: usize) -> Vec<(f64, FactUnit)> {
    let mut centrality: BTreeMap<String, usize> = BTreeMap::new();
    for (_, f) in &facts {
        for c in f.atom.concepts() {
            *centrality.entry(c.to_string()).or_insert(0) += 1;
        }
    }
    let mut scored: Vec<(f64, FactUnit)> = facts
        .into_iter()
        .map(|(_, f)| {
            let c = *centrality.get(&f.atom.subject).unwrap_or(&1) as f64;
            let kind = match f.type_ref.as_str() {
                t if t.starts_with("event.action") => 1.5,
                "assertion.relation" => 1.4,
                "assertion.property" | "assertion.definition" => 1.2,
                "event.speech" => 0.6,
                _ => 0.8,
            };
            ((c.ln_1p()) * kind * (0.5 + f.trust()), f)
        })
        .collect();
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal).then_with(|| a.1.fuid.cmp(&b.1.fuid)));
    select(&scored, n)
}

fn region(qb: &QueryBook, scope: &Scope, chapter: Option<u64>, only: Vec<String>, limit: usize) -> anyhow::Result<Retrieved> {
    let q = Fql { chapter, only_predicates: only, min_trust: qb.cfg.retrieval.admission_threshold, limit, ..Default::default() };
    retrieve(qb, scope, &q)
}

fn summary(b: &mut Builder, scope: &Scope, chapter: Option<u32>, _trace: &mut Trace) -> anyhow::Result<()> {
    let ch = match chapter {
        Some(c) => c,
        None => b.chapters.iter().filter(|c| c.2 <= scope.marker()).map(|c| c.0).last().unwrap_or(0),
    };
    let Some(&(_, ref title, start, _)) = b.chapters.iter().find(|c| c.0 == ch) else {
        anyhow::bail!("no chapter {ch}");
    };
    let title = title.clone();
    if scope.spoiler_bounded() && start > scope.marker() {
        b.ans.status = "beyond-position".into();
        b.ans.message = format!("“{title}” is ahead of where you are reading. Spoiler protection keeps its contents hidden.");
        return Ok(());
    }
    let r = region(b.qb, scope, Some(ch as u64), vec![], 3000)?;
    b.ans.fql = r.fql;
    b.ans.candidates = r.facts.len();
    let chosen = salient(r.facts, 9);
    let lines = b.lines(&chosen, Order::Narrative);
    b.ans.sections.push(Section { title, lines });
    Ok(())
}

fn recap(b: &mut Builder, scope: &Scope, _trace: &mut Trace) -> anyhow::Result<()> {
    let chapters: Vec<_> = b.chapters.iter().filter(|c| !scope.spoiler_bounded() || c.2 <= scope.marker()).cloned().collect();
    let mut fql = String::new();
    for (idx, title, _, _) in chapters.iter().take(80) {
        let r = region(b.qb, scope, Some(*idx as u64), vec![], 1500)?;
        if fql.is_empty() {
            fql = r.fql;
        }
        let chosen = salient(r.facts, 2);
        if chosen.is_empty() {
            continue;
        }
        let lines = b.lines(&chosen, Order::Narrative);
        b.ans.sections.push(Section { title: title.clone(), lines });
    }
    b.ans.fql = fql;
    Ok(())
}

fn whos_who(b: &mut Builder, scope: &Scope, _trace: &mut Trace) -> anyhow::Result<()> {
    let work = scope.primary_work().unwrap_or("").to_string();
    let marker = if scope.spoiler_bounded() { scope.marker() } else { u64::MAX };
    let people: Vec<(String, String)> = b.qb.store.read(|c| {
        let mut st = c.prepare(
            "SELECT concept, MAX(label) FROM aliases WHERE work=?1 AND kind='person' AND first_pos<=?2 GROUP BY concept ORDER BY MAX(freq) DESC, concept LIMIT 24",
        )?;
        let r = st.query_map(params![work, marker.min(i64::MAX as u64) as i64], |r| Ok((r.get(0)?, r.get(1)?)))?;
        Ok(r.collect::<Result<_, _>>()?)
    })?;
    let mut fql = String::new();
    for (concept, label) in people {
        let q = Fql {
            concepts: vec![concept.clone()],
            require_concept: true,
            only_predicates: ["is_a", "relative_of", "has_trait", "member_of", "lives_in", "married_to", "friend_of", "states"]
                .iter()
                .map(|s| s.to_string())
                .collect(),
            min_trust: b.qb.cfg.retrieval.admission_threshold,
            limit: 60,
            ..Default::default()
        };
        let r = retrieve(b.qb, scope, &q)?;
        if fql.is_empty() {
            fql = r.fql.clone();
        }
        let mut own: Vec<(f64, FactUnit)> = r.facts.into_iter().filter(|(_, f)| f.atom.subject == concept).collect();
        // descriptive records first; the character's own earliest sentence only as a fall-back
        let rank = |f: &FactUnit| match f.atom.predicate.as_str() {
            "is_a" | "relative_of" => 0,
            "married_to" | "member_of" | "lives_in" | "friend_of" => 1,
            "has_trait" => 2,
            _ => 3,
        };
        own.sort_by(|a, b| {
            rank(&a.1)
                .cmp(&rank(&b.1))
                .then_with(|| b.1.trust().partial_cmp(&a.1.trust()).unwrap_or(std::cmp::Ordering::Equal))
                .then_with(|| a.1.narrative.as_ref().map(|n| n.pos).cmp(&b.1.narrative.as_ref().map(|n| n.pos)))
                .then_with(|| a.1.fuid.cmp(&b.1.fuid))
        });
        let described = own.iter().filter(|(_, f)| rank(f) < 3).count();
        let chosen = select(&own, if described > 0 { 2 } else { 1 });
        if chosen.is_empty() {
            continue;
        }
        let lines = b.lines(&chosen, Order::AsGiven);
        b.ans.sections.push(Section { title: label, lines });
    }
    b.ans.fql = fql;
    Ok(())
}

fn timeline(b: &mut Builder, scope: &Scope, req: &Request, _trace: &mut Trace) -> anyhow::Result<()> {
    let focus: Vec<String> = match &req.focus {
        Some(f) => vec![f.clone()],
        None if !req.query.trim().is_empty() => {
            analyze(b.qb, scope, &req.query, None)?.focus.into_iter().map(|f| f.concept).take(1).collect()
        }
        None => vec![],
    };
    let q = Fql {
        concepts: focus.clone(),
        require_concept: !focus.is_empty(),
        only_predicates: ["performs", "visits", "meets", "engaged_to", "married_to", "occurs_in"]
            .iter()
            .map(|s| s.to_string())
            .collect(),
        min_trust: b.qb.cfg.retrieval.admission_threshold,
        limit: 4000,
        ..Default::default()
    };
    let r = retrieve(b.qb, scope, &q)?;
    b.ans.fql = r.fql;
    b.ans.candidates = r.facts.len();
    let mut chosen = salient(r.facts, 16);
    chosen.sort_by_key(|(_, f)| (f.narrative.as_ref().map(|n| n.pos).unwrap_or(0), f.fuid.clone()));
    b.ans.lines = b.lines(&chosen, Order::Narrative);
    Ok(())
}

fn explore(b: &mut Builder, scope: &Scope, req: &Request, _trace: &mut Trace) -> anyhow::Result<()> {
    let concept = match &req.focus {
        Some(f) => f.clone(),
        None => match analyze(b.qb, scope, &req.query, None)?.focus.first() {
            Some(f) => f.concept.clone(),
            None => {
                b.ans.status = "not-in-book".into();
                b.ans.message = "Name a person, place or idea from the book to explore its connections.".into();
                return Ok(());
            }
        },
    };
    let q = Fql {
        concepts: vec![concept.clone()],
        require_concept: true,
        min_trust: b.qb.cfg.retrieval.admission_threshold,
        limit: 600,
        ..Default::default()
    };
    let r = retrieve(b.qb, scope, &q)?;
    b.ans.fql = r.fql;
    let mut strength: BTreeMap<String, (u32, String)> = BTreeMap::new();
    for (_, f) in &r.facts {
        for c in f.atom.concepts() {
            if c != concept {
                let e = strength.entry(c.to_string()).or_insert((0, f.label(c)));
                e.0 += 1;
            }
        }
    }
    let mut n: Vec<Neighbor> = strength
        .into_iter()
        .filter(|(_, (s, _))| *s >= 1)
        .map(|(c, (s, l))| Neighbor { concept: c, label: l, strength: s })
        .collect();
    n.sort_by(|a, b| b.strength.cmp(&a.strength).then_with(|| a.label.cmp(&b.label)));
    n.truncate(16);
    b.ans.neighbors = n;
    let mut own: Vec<(f64, FactUnit)> =
        r.facts.into_iter().filter(|(_, f)| f.atom.subject == concept && f.atom.predicate != "states").collect();
    own.sort_by(|a, b| {
        b.1.trust().partial_cmp(&a.1.trust()).unwrap_or(std::cmp::Ordering::Equal).then_with(|| a.1.fuid.cmp(&b.1.fuid))
    });
    let chosen = select(&own, 5);
    b.ans.lines = b.lines(&chosen, Order::AsGiven);
    Ok(())
}
