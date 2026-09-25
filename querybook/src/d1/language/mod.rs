//! The language-learning pipeline of the ingestion subsystem (D1): the
//! deterministic stages QueryBook performs before it "understands" a text.
//!
//!   1. Text segmentation      paragraphs (parse.rs), sentences (segment.rs), clauses (parse::clauses)
//!   2. Linguistic parsing     tokens + POS (tag.rs), constituency chunks + dependencies (parse.rs)
//!   3. Entity & relation      NER, normalization, predicate classification (ner.rs)
//!   4. Fact Unit construction subject/predicate/object, semantic typing, ontology tagging (construct.rs)
//!   5. FU anchoring           EPUB CFI, paragraph, spine item (d1::parse Anchor, carried in Narrative)
//!   6. Semantic embedding     FU, context window, graph alignment (embed.rs)
//!   7. QBE integration        retrieval, ranking with embeddings, scope resolution (d4)
//!
//! Stages 1–4 run inside `LanguageEngine`, a registered extraction engine with
//! no trained component and no network. Stages 5–6 run in the ingestion
//! pipeline over every engine's records; stage 7 is the query path.

pub mod construct;
pub mod embed;
pub mod lexicon;
pub mod ner;
pub mod parse;
pub mod tag;

use super::engines::{Candidate, EngineReport, Extractor};
use super::parse::Book;
use super::segment::sentences;
use crate::d3::Catalog;
use crate::d3::entities::EntityTable;
use serde::Serialize;
use std::collections::BTreeMap;

pub struct LanguageEngine {
    pub id: String,
    pub reliability: f64,
}

#[derive(Debug, Default, Serialize)]
pub struct Stages {
    // stage 1
    pub paragraphs: usize,
    pub sentences: usize,
    pub clauses: BTreeMap<String, usize>,
    // stage 2
    pub tokens: usize,
    pub pos: BTreeMap<String, usize>,
    pub phrases: BTreeMap<String, usize>,
    pub dependencies: BTreeMap<String, usize>,
    // stage 3
    pub mentions: BTreeMap<String, usize>,
    pub predicate_classes: BTreeMap<String, usize>,
    pub resolved_references: usize,
    // stage 4
    pub facts: BTreeMap<String, usize>,
    // stage 5
    pub anchored_paragraphs: usize,
}

/// Full analysis of one sentence (for `qb analyze` and tests).
#[derive(Debug, Serialize)]
pub struct SentenceAnalysis {
    pub text: String,
    pub tokens: Vec<(String, String, String)>, // text, POS, lemma
    pub clauses: Vec<(String, String)>,         // kind, text
    pub trees: Vec<String>,
    pub dependencies: Vec<(String, String, String)>, // dependent, relation, head
    pub mentions: Vec<(String, String, String)>,     // text, kind, concept
    pub predicate: Vec<(String, String)>,            // lemma, class
    pub facts: Vec<(String, String, String, String)>, // semantic type, subject, predicate, object
}

struct Salient(BTreeMap<String, u32>);

fn salient_terms(book: &Book, fiction: bool) -> Salient {
    let mut m = BTreeMap::new();
    if !fiction {
        for p in &book.passages {
            for w in crate::util::words(&p.text) {
                if w.len() > 3 && !crate::util::is_stopword(&w) {
                    *m.entry(w.trim_end_matches('s').to_string()).or_insert(0) += 1;
                }
            }
        }
    }
    Salient(m)
}

/// Run stages 1–4 over one sentence.
pub fn analyze_sentence(
    text: &str,
    ents: &EntityTable,
    work: &str,
    engine: &str,
    pos: u64,
    chapter: u32,
    sentence: u32,
    salient: &BTreeMap<String, u32>,
    dis: &mut construct::Discourse,
    stats: Option<&mut Stages>,
) -> (Vec<construct::Built>, SentenceAnalysis) {
    let spans = ents.mentions(text);
    let mut tokens = tag::tokenize(text);
    tag::tag(&mut tokens, &spans);
    let clauses = parse::clauses(&tokens);
    let parses: Vec<parse::ClauseParse> = clauses.iter().enumerate().map(|(i, c)| parse::parse_clause(&tokens, c, i)).collect();
    let mentions = ner::recognize(&tokens, ents);
    let cx = construct::Ctx { work, ents, engine, pos, chapter, sentence, text, salient_terms: salient };
    let before = dis.last_person.clone();
    let built = construct::build(&cx, &tokens, &clauses, &parses, &mentions, dis);
    let _ = before;
    if let Some(st) = stats {
        st.sentences += 1;
        st.tokens += tokens.len();
        for t in &tokens {
            *st.pos.entry(t.pos.tag().into()).or_insert(0) += 1;
        }
        for c in &clauses {
            *st.clauses.entry(format!("{:?}", c.kind).to_lowercase()).or_insert(0) += 1;
        }
        for p in &parses {
            for c in &p.chunks {
                *st.phrases.entry(format!("{:?}", c.kind)).or_insert(0) += 1;
            }
            for a in &p.arcs {
                *st.dependencies.entry(a.rel.to_string()).or_insert(0) += 1;
            }
            if let Some((_, cls)) = ner::classify(&tokens, p) {
                *st.predicate_classes.entry(format!("{cls:?}").to_lowercase()).or_insert(0) += 1;
            }
        }
        for m in &mentions {
            *st.mentions.entry(format!("{:?}", m.kind).to_lowercase()).or_insert(0) += 1;
        }
        for b in &built {
            *st.facts.entry(b.stype.name().into()).or_insert(0) += 1;
            if b.candidate.weight < 1.0 {
                st.resolved_references += 1;
            }
        }
    }
    let analysis = SentenceAnalysis {
        text: text.to_string(),
        tokens: tokens.iter().map(|t| (t.text.clone(), t.pos.tag().to_string(), t.lemma.clone())).collect(),
        clauses: clauses
            .iter()
            .map(|c| (format!("{:?}", c.kind).to_lowercase(), c.tokens.iter().map(|&k| tokens[k].text.as_str()).collect::<Vec<_>>().join(" ")))
            .collect(),
        trees: parses.iter().map(|p| parse::tree(&tokens, p)).collect(),
        dependencies: parses
            .iter()
            .flat_map(|p| p.arcs.iter())
            .map(|a| (tokens[a.dep].text.clone(), a.rel.to_string(), a.head.map(|h| tokens[h].text.clone()).unwrap_or_else(|| "ROOT".into())))
            .collect(),
        mentions: mentions.iter().map(|m| (m.tokens.iter().map(|&k| tokens[k].text.as_str()).collect::<Vec<_>>().join(" "), format!("{:?}", m.kind), if m.concept.is_empty() { m.normalized.clone() } else { m.concept.clone() })).collect(),
        predicate: parses.iter().filter_map(|p| ner::classify(&tokens, p)).map(|(l, c)| (l, format!("{c:?}"))).collect(),
        facts: built
            .iter()
            .map(|b| {
                let a = &b.candidate.atom;
                let o = match &a.object {
                    crate::d2::Value::Concept(c) => b.candidate.labels.get(c).cloned().unwrap_or(c.clone()),
                    crate::d2::Value::Text(t) => t.clone(),
                    v => v.canonical(),
                };
                let s = b.candidate.labels.get(&a.subject).cloned().unwrap_or(a.subject.clone());
                (b.stype.name().to_string(), s, if a.polarity { a.predicate.clone() } else { format!("NOT {}", a.predicate) }, o)
            })
            .collect(),
    };
    (built, analysis)
}

impl Extractor for LanguageEngine {
    fn id(&self) -> &str {
        &self.id
    }
    fn reliability(&self) -> f64 {
        self.reliability
    }

    fn extract(
        &self,
        book: &Book,
        ents: &EntityTable,
        catalog: &Catalog,
        progress: &(dyn Fn(&str) + Sync),
    ) -> anyhow::Result<(Vec<Candidate>, EngineReport)> {
        let fiction = ents.entities.iter().filter(|e| e.kind == "person").count() >= 5;
        let salient = salient_terms(book, fiction);
        let mut stats = Stages::default();
        let mut out: Vec<Candidate> = Vec::new();
        let total = book.passages.len().max(1);
        for (pi, p) in book.passages.iter().enumerate() {
            if pi % 500 == 0 {
                progress(&format!("{}: passage {pi}/{total}", self.id));
            }
            if p.kind != "p" {
                continue;
            }
            stats.paragraphs += 1;
            if p.anchor.is_some() {
                stats.anchored_paragraphs += 1;
            }
            let mut dis = construct::Discourse::default();
            for (si, s) in sentences(&p.text).iter().enumerate() {
                if s.split_whitespace().count() < 2 {
                    continue;
                }
                let (built, _) = analyze_sentence(s, ents, &book.id, &self.id, p.pos, p.chapter, si as u32, &salient.0, &mut dis, Some(&mut stats));
                let fired = !built.is_empty();
                out.extend(built.into_iter().map(|b| b.candidate));
                // coverage fall-back: a sentence naming someone still yields its claim
                let wc = s.split_whitespace().count();
                if !fired && (6..=48).contains(&wc) && !s.contains('?') {
                    if let Some(&(_, _, e)) = ents.mentions(s).first() {
                        let ent = &ents.entities[e];
                        let mut labels = BTreeMap::new();
                        labels.insert(ent.concept.clone(), ent.label.clone());
                        *stats.facts.entry("claim".into()).or_insert(0) += 1;
                        out.push(Candidate {
                            type_ref: "assertion.claim".into(),
                            atom: crate::d2::Atom {
                                subject: ent.concept.clone(),
                                predicate: "states".into(),
                                object: crate::d2::Value::Text(s.clone()),
                                args: BTreeMap::new(),
                                polarity: true,
                            },
                            labels,
                            pos: p.pos,
                            chapter: p.chapter,
                            quote: s.clone(),
                            engine: self.id.clone(),
                            prompt_hash: None,
                            citation_verified: true,
                            sentence: Some(si as u32),
                            weight: 1.0,
                        });
                    }
                }
            }
        }
        let refused = out.iter().filter(|c| catalog.get(&c.atom.predicate).is_none()).count();
        out.retain(|c| catalog.get(&c.atom.predicate).is_some());
        let report = EngineReport { engine: self.id.clone(), candidates: out.len(), refused, stages: Some(serde_json::to_value(&stats)?), ..Default::default() };
        Ok((out, report))
    }
}
