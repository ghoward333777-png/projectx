//! D7 · Grounded Expression. Renders a stabilized set of Fact Units as text
//! under the vocabulary constraint. D7 holds no store handle and no retrieval
//! authority (its crossing to D2 is denied by the matrix): it can only speak
//! about the records it is handed.
//!
//! * Narrative Graph (QBF-C147): every rendered proposition references at
//!   least one record; an edge without a record is never constructed.
//! * Structural groundedness (QBF-C149): each sentence's content words must be
//!   derivable from the cited records' labels, values and source spans, plus
//!   the closed-class words of the catalogue templates. A proposition that is
//!   not derivable is rejected before output.
//! * Sentence aggregation (C159), referring expressions (C160), connective
//!   emission only where a typed edge joins two propositions (C161),
//!   given-before-new ordering (C162).

use crate::d2::{EdgeClass, FactUnit, Value};
use crate::d3::Catalog;
use crate::util::words;
use serde::Serialize;
use std::collections::BTreeSet;

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Sentence {
    pub text: String,
    /// indices into the facts slice handed to `realize`
    pub cites: Vec<usize>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Realized {
    pub sentences: Vec<Sentence>,
    pub rejected: usize,
}

#[derive(Clone, Copy, PartialEq)]
pub enum Order {
    /// keep the order given (already ranked by activation)
    AsGiven,
    /// narrative order (summaries, timelines)
    Narrative,
    /// group by subject, focus subject first, subjects already realized first
    GivenBeforeNew,
}

pub struct Opts {
    pub order: Order,
    pub aggregate: bool,
    pub connectives: bool,
}

const CLOSED_CLASS: &[&str] = &[
    "is",
    "the",
    "of",
    "a",
    "an",
    "and",
    "to",
    "at",
    "in",
    "by",
    "for",
    "that",
    "with",
    "as",
    "on",
    "part",
    "has",
    "means",
    "says",
    "believes",
    "feels",
    "leads",
    "lives",
    "belongs",
    "works",
    "owns",
    "visits",
    "meets",
    "loves",
    "dislikes",
    "married",
    "becomes",
    "engaged",
    "friend",
    "recommends",
    "takes",
    "place",
    "after",
    "result",
    "your",
    "note",
    "you",
    "highlighted",
    "was",
    "are",
    "also",
];

fn short_form(label: &str) -> String {
    let parts: Vec<&str> = label.split_whitespace().collect();
    let titled = parts
        .first()
        .map(|p| crate::d3::entities::TITLES.contains(&p.trim_end_matches('.').to_lowercase().as_str()))
        .unwrap_or(false);
    if parts.len() >= 2 && !titled { parts[0].to_string() } else { label.to_string() }
}

fn capitalize(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) if f.is_lowercase() => f.to_uppercase().collect::<String>() + c.as_str(),
        Some(f) => f.to_string() + c.as_str(),
        None => String::new(),
    }
}

fn terminate(s: &str) -> String {
    let t = s.trim_end();
    if t.ends_with(['.', '!', '?', '”', '"', '’', ')']) { t.to_string() } else { format!("{t}.") }
}

fn value_text(f: &FactUnit, v: &Value) -> String {
    match v {
        Value::Concept(c) => f.label(c),
        Value::Text(t) => t.trim().trim_end_matches([',', ';', ':']).to_string(),
        Value::Number { value, unit } => format!("{value} {unit}").trim().to_string(),
        Value::Date(d) => d.clone(),
        Value::Bool(b) => {
            if *b {
                "true".into()
            } else {
                "false".into()
            }
        }
    }
}

struct Refs {
    last_full: std::collections::BTreeMap<String, usize>,
    mentions: Vec<String>,
}

impl Refs {
    /// Full label on first mention; short form only if no other concept has
    /// been mentioned since this one's last mention.
    fn refer(&mut self, f: &FactUnit, concept: &str) -> String {
        let label = f.label(concept);
        let idx = self.mentions.len();
        let reduced = match self.last_full.get(concept) {
            Some(&k) => self.mentions[k..].iter().all(|m| m == concept),
            None => false,
        };
        self.mentions.push(concept.to_string());
        if !reduced {
            self.last_full.insert(concept.to_string(), idx);
            label
        } else {
            short_form(&label)
        }
    }
}

fn proposition(f: &FactUnit, catalog: &Catalog, refs: &mut Refs) -> String {
    // an imported envelope's own rendering is its wording-operative span
    if f.type_ref == "ufcs.fact" {
        if let Some(q) = f.quote.as_deref().filter(|q| !q.trim().is_empty()) {
            refs.refer(f, &f.atom.subject);
            return terminate(&capitalize(q.trim()));
        }
    }
    let p = catalog.get(&f.atom.predicate);
    let template = p.map(|p| p.template.as_str()).unwrap_or("{s} {p} {o}.");
    let subj = refs.refer(f, &f.atom.subject);
    let obj = match &f.atom.object {
        Value::Concept(c) => refs.refer(f, c),
        v => value_text(f, v),
    };
    let mut out = template.replace("{s}", &subj).replace("{p}", &f.atom.predicate.replace('_', " "));
    for (k, v) in &f.atom.args {
        out = out.replace(&format!("{{{k}}}"), &value_text(f, v));
    }
    // unfilled optional argument slots are dropped
    while let (Some(a), Some(b)) = (out.find('{'), out.find('}')) {
        if b > a && &out[a + 1..b] != "o" {
            out.replace_range(a..=b, "");
        } else {
            break;
        }
    }
    out = out.replace("{o}", &obj);
    if !f.atom.polarity {
        // a copular template negates in place ("Jane is not happy"); others by the frame
        out = match out.find(" is ") {
            Some(k) if matches!(f.atom.predicate.as_str(), "is_a" | "has_trait") => {
                format!("{} is not {}", &out[..k], &out[k + 4..])
            }
            _ => format!("It is not the case that {}", out.trim_end_matches('.')),
        };
    }
    terminate(&capitalize(out.trim()))
}

/// Vocabulary derivable from the records (labels, values, spans) plus the
/// catalogue's closed-class template words.
fn vocabulary(facts: &[&FactUnit]) -> BTreeSet<String> {
    let mut v: BTreeSet<String> = CLOSED_CLASS.iter().map(|s| s.to_string()).collect();
    v.insert("it".into());
    v.insert("not".into());
    v.insert("case".into());
    for f in facts {
        for l in f.labels.values() {
            v.extend(words(l));
        }
        for c in f.atom.concepts() {
            v.extend(words(&f.label(c)));
        }
        let mut add = |x: &Value| {
            if let Value::Text(t) | Value::Date(t) = x {
                v.extend(words(t));
            }
            if let Value::Number { value, unit } = x {
                v.extend(words(&format!("{value} {unit}")));
            }
        };
        add(&f.atom.object);
        for a in f.atom.args.values() {
            add(a);
        }
        if let Some(q) = &f.quote {
            v.extend(words(q));
        }
    }
    v
}

pub fn realize(facts: &[&FactUnit], catalog: &Catalog, opts: Opts) -> Realized {
    let mut idx: Vec<usize> = (0..facts.len()).collect();
    match opts.order {
        Order::AsGiven => {}
        Order::Narrative => {
            idx.sort_by_key(|&i| (facts[i].narrative.as_ref().map(|n| n.pos).unwrap_or(0), facts[i].fuid.clone()))
        }
        Order::GivenBeforeNew => {
            // stable grouping: subjects in order of first appearance
            let mut subjects: Vec<&str> = Vec::new();
            for &i in &idx {
                if !subjects.contains(&facts[i].atom.subject.as_str()) {
                    subjects.push(&facts[i].atom.subject);
                }
            }
            idx.sort_by_key(|&i| subjects.iter().position(|s| *s == facts[i].atom.subject).unwrap_or(0));
        }
    }
    let vocab = vocabulary(facts);
    let mut refs = Refs { last_full: Default::default(), mentions: vec![] };
    let mut out: Vec<Sentence> = Vec::new();
    let mut rejected = 0;
    let mut k = 0;
    while k < idx.len() {
        let i = idx[k];
        let f = facts[i];
        // (C159) aggregate consecutive properties of one subject
        if opts.aggregate && matches!(f.atom.predicate.as_str(), "is_a" | "has_trait") {
            let mut group = vec![i];
            while k + group.len() < idx.len() && group.len() < 3 {
                let j = idx[k + group.len()];
                let g = facts[j];
                if g.atom.subject == f.atom.subject
                    && g.atom.predicate == f.atom.predicate
                    && g.atom.polarity
                    && f.atom.polarity
                    && (g.evidence.confidence() - f.evidence.confidence()).abs() <= 0.15
                {
                    group.push(j);
                } else {
                    break;
                }
            }
            if group.len() > 1 {
                let subj = refs.refer(f, &f.atom.subject);
                let objs: Vec<String> = group.iter().map(|&j| value_text(facts[j], &facts[j].atom.object)).collect();
                let joined = match objs.len() {
                    2 => format!("{} and {}", objs[0], objs[1]),
                    _ => format!("{}, {} and {}", objs[0], objs[1], objs[2]),
                };
                let text = terminate(&capitalize(&format!("{subj} is {joined}")));
                if grounded(&text, &vocab) {
                    out.push(Sentence { text, cites: group.clone() });
                } else {
                    rejected += 1;
                }
                k += group.len();
                continue;
            }
        }
        let mut text = proposition(f, catalog, &mut refs);
        // (C161) connective only where a typed edge joins the two records
        if opts.connectives && k > 0 {
            let prev = facts[idx[k - 1]];
            if let Some(e) = prev.edges.iter().find(|e| e.target == f.fuid) {
                let conn = match (e.class, e.predicate.as_str()) {
                    (_, "causes") => Some("As a result, "),
                    (EdgeClass::Temporal, _) => Some("After that, "),
                    _ => None,
                };
                if let Some(c) = conn {
                    let mut chars = text.chars();
                    let first = chars.next().unwrap_or(' ');
                    let lowered = if text.split_whitespace().next().map(|w| w == "It").unwrap_or(false) {
                        format!("{}{}", first.to_lowercase(), chars.as_str())
                    } else {
                        text.clone()
                    };
                    text = format!("{c}{lowered}");
                }
            }
        }
        if grounded(&text, &vocab) {
            out.push(Sentence { text, cites: vec![i] });
        } else {
            rejected += 1;
        }
        k += 1;
    }
    Realized { sentences: out, rejected }
}

/// (C149) every content word must be derivable from the records.
pub fn grounded(text: &str, vocab: &BTreeSet<String>) -> bool {
    words(text).iter().all(|w| vocab.contains(w) || w.chars().all(|c| c.is_numeric()) || w.len() <= 1)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::d2::fact::tests::sample;

    #[test]
    fn renders_and_aggregates_under_the_vocabulary_constraint() {
        let cat = Catalog::builtin();
        let mut a = sample("w:w1/mr-darcy", "a proud man");
        a.labels.insert("w:w1/mr-darcy".into(), "Mr. Darcy".into());
        let mut b = sample("w:w1/mr-darcy", "the owner of Pemberley");
        b.labels = a.labels.clone();
        b.quote = Some("Mr. Darcy, the owner of Pemberley, arrived.".into());
        let r = realize(&[&a, &b], &cat, Opts { order: Order::AsGiven, aggregate: true, connectives: true });
        assert_eq!(r.sentences.len(), 1);
        assert_eq!(r.sentences[0].text, "Mr. Darcy is a proud man and the owner of Pemberley.");
        assert_eq!(r.sentences[0].cites, vec![0, 1]);
    }

    #[test]
    fn rejects_underivable_propositions() {
        let vocab: BTreeSet<String> = ["darcy", "is", "proud"].iter().map(|s| s.to_string()).collect();
        assert!(grounded("Darcy is proud.", &vocab));
        assert!(!grounded("Darcy is secretly kind.", &vocab));
    }
}
