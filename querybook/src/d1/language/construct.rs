//! Stage 4 — Fact Unit construction: the transition from language to
//! knowledge. For each parsed clause: subject, predicate and object from the
//! dependency structure; a semantic type (event, description, attribute,
//! relation, state, speech, claim); ontology tagging to canonical concepts
//! (world-level linking to harvested concepts happens after commit, in D3).
//!
//! Reference handling is conservative: a relative pronoun resolves to its
//! antecedent; "he"/"she" resolve only when exactly one person was the
//! subject in the preceding sentence and no other person is named in this
//! one — and such candidates carry reduced evidential weight.

use super::lexicon::{KIN, VerbClass};
use super::ner::{self, EntKind, Mention};
use super::parse::{Clause, ClauseKind, ClauseParse};
use super::tag::{Form, Pos, Token};
use crate::d1::engines::Candidate;
use crate::d2::{Atom, Value};
use crate::d3::entities::EntityTable;
use serde::Serialize;
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub enum SemanticType {
    Event,
    Description,
    Attribute,
    Relation,
    State,
    Speech,
    Claim,
}

impl SemanticType {
    pub fn name(self) -> &'static str {
        match self {
            SemanticType::Event => "event",
            SemanticType::Description => "description",
            SemanticType::Attribute => "attribute",
            SemanticType::Relation => "relation",
            SemanticType::State => "state",
            SemanticType::Speech => "speech",
            SemanticType::Claim => "claim",
        }
    }
}

/// Discourse state carried across the sentences of one passage.
#[derive(Default)]
pub struct Discourse {
    pub last_person: Option<(String, String)>, // (concept, label)
    pub persons_last_sentence: usize,
}

pub struct Ctx<'a> {
    pub work: &'a str,
    pub ents: &'a EntityTable,
    pub engine: &'a str,
    pub pos: u64,
    pub chapter: u32,
    pub sentence: u32,
    pub text: &'a str,
    pub salient_terms: &'a BTreeMap<String, u32>,
}

pub struct Built {
    pub candidate: Candidate,
    pub stype: SemanticType,
}

fn span_text(text: &str, tokens: &[Token], idx: &[usize]) -> String {
    if idx.is_empty() {
        return String::new();
    }
    let a = tokens[idx[0]].start;
    let b = tokens[*idx.last().unwrap()].end;
    text[a..b].trim().trim_end_matches([',', ';', ':']).to_string()
}

/// Contiguous words of the clause from token `from` to the clause end,
/// stopping at hard punctuation, at most `max` words.
fn tail_text(text: &str, tokens: &[Token], clause: &[usize], from: usize, max: usize) -> String {
    let mut idx: Vec<usize> = Vec::new();
    let mut words = 0;
    for &k in clause.iter().filter(|&&k| k >= from) {
        let t = &tokens[k];
        if matches!(t.text.as_str(), ";" | ":" | "." | "!" | "?" | "\u{201C}" | "\u{201D}" | "\"") {
            break;
        }
        if t.pos != Pos::Punct {
            words += 1;
        }
        if words > max {
            break;
        }
        idx.push(k);
    }
    while idx.last().map(|&k| tokens[k].pos == Pos::Punct).unwrap_or(false) {
        idx.pop();
    }
    span_text(text, tokens, &idx)
}

/// Cut a predicate phrase at its first clause joint (comma, coordination,
/// comparison, relative), so a description stays one description.
fn cut_at_boundary(text: String) -> String {
    let mut out: Vec<&str> = Vec::new();
    for (i, w) in text.split_whitespace().enumerate() {
        let lw = w.to_lowercase();
        if i > 0 && matches!(lw.as_str(), "and" | "but" | "or" | "than" | "who" | "which" | "whom" | "whose" | "while" | "though")
        {
            break;
        }
        // a comma inside a short opening ("a stout, well-grown girl") joins adjectives
        let comma = w.ends_with(',') || w.ends_with(';');
        if comma && (i >= 2 || w.ends_with(';')) {
            out.push(w.trim_end_matches([',', ';']));
            break;
        }
        out.push(w);
    }
    out.join(" ")
}

pub fn build(
    cx: &Ctx,
    tokens: &[Token],
    clauses: &[Clause],
    parses: &[ClauseParse],
    mentions: &[Mention],
    dis: &mut Discourse,
) -> Vec<Built> {
    let mut out: Vec<Built> = Vec::new();
    let persons_here: Vec<&Mention> = mentions.iter().filter(|m| m.kind == EntKind::Person).collect();
    let mut labels: BTreeMap<String, String> = BTreeMap::new();
    let mut subject_of_clause: Vec<Option<(String, String, f64)>> = vec![None; clauses.len()];

    for (ci, (clause, p)) in clauses.iter().zip(parses).enumerate() {
        if clause.kind == ClauseKind::Speech {
            continue;
        }
        // ---- subject
        let mut weight = 1.0;
        let subj: Option<(String, String, EntKind)> = match p.subject {
            Some(s) if clause.kind == ClauseKind::Relative && matches!(tokens[s].lower.as_str(), "who" | "which" | "that") => {
                clause.antecedent.and_then(|a| ner::mention_at(mentions, a)).map(|m| (m.concept.clone(), m.label.clone(), m.kind))
            }
            Some(s) => match ner::mention_at(mentions, s) {
                Some(m) if !m.concept.is_empty() => Some((m.concept.clone(), m.label.clone(), m.kind)),
                _ if matches!(tokens[s].lower.as_str(), "he" | "she") => {
                    let other_person_before = persons_here.iter().any(|m| m.tokens[0] < s);
                    match (&dis.last_person, dis.persons_last_sentence, other_person_before) {
                        (Some((c, l)), 1, false) => {
                            weight = 0.6;
                            Some((c.clone(), l.clone(), EntKind::Person))
                        }
                        _ => None,
                    }
                }
                _ if tokens[s].pos == Pos::Noun && cx.salient_terms.get(&tokens[s].lemma).copied().unwrap_or(0) >= 4 => {
                    let term = tokens[s].lemma.clone();
                    Some((format!("w:{}/term-{}", cx.work, crate::util::slug(&term)), term, EntKind::Misc))
                }
                _ => None,
            },
            None if clause.kind == ClauseKind::Relative => {
                clause.antecedent.and_then(|a| ner::mention_at(mentions, a)).map(|m| (m.concept.clone(), m.label.clone(), m.kind))
            }
            None => None,
        };
        let Some((sc, sl, skind)) = subj else { continue };
        // "Lydia's letters were frequent": the possessor is not the subject
        if let Some(s) = p.subject {
            let last = ner::mention_at(mentions, s).map(|m| *m.tokens.last().unwrap()).unwrap_or(s);
            if tokens.get(last + 1).map(|t| t.lower == "'s" || t.lower == "'").unwrap_or(false) {
                continue;
            }
            // "between him and Darcy there was ...": a name inside a prepositional phrase is not the subject
            let first = ner::mention_at(mentions, s).map(|m| m.tokens[0]).unwrap_or(s);
            let governed = (first.saturating_sub(4)..first)
                .rev()
                .take_while(|&k| tokens[k].pos != Pos::Punct)
                .any(|k| tokens[k].pos == Pos::Adp && !(k + 1..first).any(|j| matches!(tokens[j].pos, Pos::Verb | Pos::Aux)));
            if governed && clause.kind != ClauseKind::Relative {
                continue;
            }
        }
        subject_of_clause[ci] = Some((sc.clone(), sl.clone(), weight));
        labels.insert(sc.clone(), sl.clone());
        let Some(root) = p.root else { continue };

        // ---- arguments: time and place
        let mut time: Option<String> = None;
        let mut place: Option<(String, String)> = None;
        for m in mentions.iter().filter(|m| m.tokens.iter().any(|t| clause.tokens.contains(t))) {
            match m.kind {
                EntKind::Date if time.is_none() => time = Some(m.label.clone()),
                EntKind::Place if place.is_none() && m.concept != sc => {
                    let prev = m.tokens[0].checked_sub(1).map(|k| tokens[k].lower.as_str()).unwrap_or("");
                    if matches!(prev, "at" | "in" | "to" | "from" | "near") {
                        place = Some((m.concept.clone(), m.label.clone()));
                    }
                }
                _ => {}
            }
        }
        let obj_mention =
            p.object.and_then(|o| ner::mention_at(mentions, o)).filter(|m| !m.concept.is_empty() && m.concept != sc);
        let obl_mention = |preps: &[&str]| -> Option<&Mention> {
            mentions.iter().find(|m| {
                !m.concept.is_empty()
                    && m.concept != sc
                    && m.tokens.iter().any(|t| clause.tokens.contains(t))
                    && m.tokens[0] > root
                    && m.tokens[0].checked_sub(1).map(|k| preps.contains(&tokens[k].lower.as_str())).unwrap_or(false)
            })
        };
        let concept = |m: &Mention, labels: &mut BTreeMap<String, String>| {
            labels.insert(m.concept.clone(), m.label.clone());
            Value::Concept(m.concept.clone())
        };

        // ---- predicate classification (Stage 3) -> governed predicate
        let class = ner::classify(tokens, p);
        let mut args: BTreeMap<String, Value> = BTreeMap::new();
        let (pred, type_ref, object, stype): (&str, &str, Value, SemanticType) = match class {
            Some((_, VerbClass::Copula)) => {
                let pred_chunk = p.chunks.iter().find(|c| c.head == root);
                let Some(pc) = pred_chunk else { continue };
                if tokens[root].pos == Pos::Adj {
                    let first = tokens[pc.tokens[0]].lower.as_str();
                    let after = tokens.get(*pc.tokens.last().unwrap() + 1).map(|t| t.lower.as_str()).unwrap_or("");
                    // comparisons and degree constructions ("as far from", "so ... that", "more ... than") are not traits
                    if matches!(first, "as" | "so" | "too" | "more" | "less" | "most" | "least")
                        || matches!(after, "as" | "than" | "that" | "enough")
                    {
                        continue;
                    }
                    let text = if matches!(after, "of" | "to" | "with" | "in" | "at" | "about") {
                        cut_at_boundary(tail_text(cx.text, tokens, &clause.tokens, pc.tokens[0], 7))
                    } else {
                        span_text(cx.text, tokens, &pc.tokens)
                    };
                    ("has_trait", "assertion.property", Value::Text(text), SemanticType::Attribute)
                } else if tokens[root].pos.nominal() && tokens[root].pos != Pos::Pron {
                    // "the sister of Y" -> relative_of; otherwise a description
                    let head_lemma = tokens[root].lemma.clone();
                    let of_person = mentions.iter().find(|m| {
                        m.kind == EntKind::Person
                            && m.concept != sc
                            && m.tokens[0] > root
                            && m.tokens[0].checked_sub(1).map(|k| tokens[k].lower == "of").unwrap_or(false)
                    });
                    if matches!(
                        head_lemma.as_str(),
                        "week"
                            | "day"
                            | "month"
                            | "year"
                            | "hour"
                            | "minute"
                            | "fortnight"
                            | "night"
                            | "morning"
                            | "evening"
                            | "time"
                    ) {
                        continue; // "Jane was a week in town": a duration, not a description
                    }
                    if KIN.contains(&head_lemma.as_str()) && of_person.is_some() {
                        let op = of_person.unwrap();
                        args.insert("relation".into(), Value::Text(head_lemma));
                        ("relative_of", "assertion.relation", concept(op, &mut labels), SemanticType::Relation)
                    } else if ner::mention_at(mentions, root).is_some() || tokens[root].pos == Pos::Propn {
                        continue; // "X was Mr. Y": identity between names, not a description
                    } else {
                        let text = cut_at_boundary(tail_text(cx.text, tokens, &clause.tokens, pc.tokens[0], 14));
                        if text.split_whitespace().count() < 2 {
                            continue;
                        }
                        ("is_a", "assertion.property", Value::Text(text), SemanticType::Description)
                    }
                } else {
                    continue;
                }
            }
            Some((lemma, class)) => {
                let lemma = lemma.as_str();
                match (lemma, class) {
                    ("marry", _) if obj_mention.map(|m| m.kind == EntKind::Person).unwrap_or(false) => {
                        ("married_to", "assertion.relation", concept(obj_mention.unwrap(), &mut labels), SemanticType::Relation)
                    }
                    ("meet", _) if obj_mention.is_some() => {
                        ("meets", "event.action", concept(obj_mention.unwrap(), &mut labels), SemanticType::Event)
                    }
                    ("love" | "adore", _) if obj_mention.is_some() => {
                        ("loves", "assertion.relation", concept(obj_mention.unwrap(), &mut labels), SemanticType::Relation)
                    }
                    ("hate" | "dislike" | "despise", _) if obj_mention.is_some() => {
                        ("dislikes", "assertion.relation", concept(obj_mention.unwrap(), &mut labels), SemanticType::Relation)
                    }
                    ("live" | "reside" | "dwell", _) if obl_mention(&["at", "in", "near"]).is_some() => (
                        "lives_in",
                        "assertion.relation",
                        concept(obl_mention(&["at", "in", "near"]).unwrap(), &mut labels),
                        SemanticType::Relation,
                    ),
                    (_, VerbClass::Motion)
                        if obj_mention.map(|m| m.kind == EntKind::Place).unwrap_or(false)
                            || obl_mention(&["to", "at", "into"]).is_some() =>
                    {
                        let m = obj_mention
                            .filter(|m| m.kind == EntKind::Place)
                            .or_else(|| obl_mention(&["to", "at", "into"]))
                            .unwrap();
                        ("visits", "event.action", concept(m, &mut labels), SemanticType::Event)
                    }
                    ("own" | "possess", _) if p.object.is_some() => {
                        let text = tail_text(cx.text, tokens, &clause.tokens, root + 1, 10);
                        ("owns", "assertion.relation", Value::Text(text), SemanticType::Relation)
                    }
                    ("believe" | "think" | "suppose" | "suspect", _) => {
                        // the complement clause is the belief
                        let sub = clauses.iter().enumerate().find(|(k, c)| {
                            *k != ci && c.kind == ClauseKind::Subordinate && c.tokens.first().map(|&t| t > root).unwrap_or(false)
                        });
                        let text = match sub {
                            Some((_, c)) => span_text(cx.text, tokens, &c.tokens),
                            None => {
                                tail_text(cx.text, tokens, &clause.tokens, root + 1, 16).trim_start_matches("that ").to_string()
                            }
                        };
                        if text.split_whitespace().count() < 3 {
                            continue;
                        }
                        ("believes", "assertion.claim", Value::Text(text), SemanticType::State)
                    }
                    ("feel", _) => {
                        let text = cut_at_boundary(tail_text(cx.text, tokens, &clause.tokens, root + 1, 8));
                        if text.is_empty() {
                            continue;
                        }
                        ("feels", "assertion.property", Value::Text(text), SemanticType::State)
                    }
                    (_, VerbClass::Communication) if clauses.iter().any(|c| c.kind == ClauseKind::Speech) => continue, // speech handled below
                    _ => {
                        if tokens[root].pos != Pos::Verb || matches!(skind, EntKind::Place | EntKind::Date | EntKind::Quantity) {
                            continue;
                        }
                        let has_aux = p.arcs.iter().any(|a| a.head == Some(root) && a.rel.starts_with("aux"));
                        if tokens[root].form == Form::Ger && !has_aux {
                            continue;
                        }
                        let vp_start = p.chunks.iter().find(|c| c.tokens.contains(&root)).map(|c| c.tokens[0]).unwrap_or(root);
                        let text = tail_text(cx.text, tokens, &clause.tokens, vp_start, 16);
                        if text.split_whitespace().count() < 2 {
                            continue;
                        }
                        if let Some(t) = &time {
                            args.insert("time".into(), Value::Date(t.clone()));
                        }
                        if let Some((pc, pl)) = &place {
                            labels.insert(pc.clone(), pl.clone());
                            args.insert("place".into(), Value::Concept(pc.clone()));
                        }
                        ("performs", "event.action", Value::Text(text), SemanticType::Event)
                    }
                }
            }
            None => continue,
        };
        // a negated trait is the trait with negative polarity, so CCR can see the conflict
        let mut object = object;
        let mut neg_trait = false;
        if let Value::Text(t) = &object {
            if let Some(n) = ["not ", "never ", "no longer "].into_iter().find(|n| pred == "has_trait" && t.starts_with(n)) {
                let rest = t[n.len()..].to_string();
                object = Value::Text(rest);
                neg_trait = true;
            }
        }
        let polarity = !((p.negated && pred != "performs") || neg_trait);
        let _ = skind;
        out.push(Built {
            candidate: Candidate {
                type_ref: type_ref.into(),
                atom: Atom { subject: sc.clone(), predicate: pred.into(), object, args, polarity },
                labels: labels.clone(),
                pos: cx.pos,
                chapter: cx.chapter,
                quote: cx.text.to_string(),
                engine: cx.engine.into(),
                prompt_hash: None,
                citation_verified: true,
                sentence: Some(cx.sentence),
                weight,
            },
            stype,
        });
    }

    // ---- speech: quoted clause attributed to its reporting clause's subject
    for clause in clauses.iter().filter(|c| c.kind == ClauseKind::Speech) {
        let words = span_text(cx.text, tokens, &clause.tokens);
        if words.split_whitespace().count() < 3 {
            continue;
        }
        // speaker: a person named outside the quotes next to a communication verb
        let speaker =
            clauses.iter().zip(parses).enumerate().filter(|(_, (c, _))| c.kind != ClauseKind::Speech).find_map(|(k, (_, p))| {
                let cls = ner::classify(tokens, p)?;
                if cls.1 != VerbClass::Communication {
                    return None;
                }
                subject_of_clause[k].clone().or_else(|| {
                    // "said Elizabeth": subject after the verb
                    let r = p.root?;
                    mentions
                        .iter()
                        .find(|m| m.kind == EntKind::Person && m.tokens[0] > r && m.tokens[0] <= r + 3)
                        .map(|m| (m.concept.clone(), m.label.clone(), 1.0))
                        .or_else(|| {
                            // "returned she": an inverted pronoun speaker, resolved only when
                            // exactly one person was in play in the previous sentence
                            let next = tokens.get(r + 1)?;
                            if !matches!(next.lower.as_str(), "he" | "she") || dis.persons_last_sentence != 1 {
                                return None;
                            }
                            dis.last_person.clone().map(|(c, l)| (c, l, 0.6))
                        })
                })
            });
        if let Some((sc, sl, w)) = speaker {
            let mut l = BTreeMap::new();
            l.insert(sc.clone(), sl);
            out.push(Built {
                candidate: Candidate {
                    type_ref: "event.speech".into(),
                    atom: Atom {
                        subject: sc,
                        predicate: "says".into(),
                        object: Value::Text(words),
                        args: BTreeMap::new(),
                        polarity: true,
                    },
                    labels: l,
                    pos: cx.pos,
                    chapter: cx.chapter,
                    quote: cx.text.to_string(),
                    engine: cx.engine.into(),
                    prompt_hash: None,
                    citation_verified: true,
                    sentence: Some(cx.sentence),
                    weight: w,
                },
                stype: SemanticType::Speech,
            });
        }
    }

    // ---- appositive descriptions: "Mr. Collins, the heir of the estate, ..."
    for p in parses {
        for a in p.arcs.iter().filter(|a| a.rel == "appos") {
            let (Some(h), d) = (a.head, a.dep) else { continue };
            let Some(m) = ner::mention_at(mentions, h) else { continue };
            if m.concept.is_empty() || ner::mention_at(mentions, d).is_some() {
                continue;
            }
            let Some(ch) = p.chunks.iter().find(|c| c.head == d) else { continue };
            if !matches!(tokens[ch.tokens[0]].lower.as_str(), "the" | "a" | "an" | "his" | "her" | "their") {
                continue;
            }
            // include a following of-PP: "the heir of the Longbourn estate"
            let mut idx = ch.tokens.clone();
            if let Some(pp) = p
                .chunks
                .iter()
                .find(|c| c.tokens.first().map(|&t| t == idx.last().unwrap() + 1 && tokens[t].lower == "of").unwrap_or(false))
            {
                idx.extend(pp.tokens.iter().copied());
            }
            let text = span_text(cx.text, tokens, &idx);
            let mut l = BTreeMap::new();
            l.insert(m.concept.clone(), m.label.clone());
            out.push(Built {
                candidate: Candidate {
                    type_ref: "assertion.property".into(),
                    atom: Atom {
                        subject: m.concept.clone(),
                        predicate: "is_a".into(),
                        object: Value::Text(text),
                        args: BTreeMap::new(),
                        polarity: true,
                    },
                    labels: l,
                    pos: cx.pos,
                    chapter: cx.chapter,
                    quote: cx.text.to_string(),
                    engine: cx.engine.into(),
                    prompt_hash: None,
                    citation_verified: true,
                    sentence: Some(cx.sentence),
                    weight: 1.0,
                },
                stype: SemanticType::Description,
            });
        }
    }

    // ---- discourse update: the sentence's person subjects
    let subj_persons: Vec<(String, String)> = clauses
        .iter()
        .zip(parses)
        .filter_map(|(_, p)| {
            p.subject
                .and_then(|s| ner::mention_at(mentions, s))
                .filter(|m| m.kind == EntKind::Person)
                .map(|m| (m.concept.clone(), m.label.clone()))
        })
        .collect();
    let mut distinct = subj_persons.clone();
    distinct.dedup();
    dis.persons_last_sentence = persons_here.iter().map(|m| &m.concept).collect::<std::collections::BTreeSet<_>>().len();
    if let Some(last) = distinct.last() {
        dis.last_person = Some(last.clone());
    } else if dis.persons_last_sentence == 0 && !subject_of_clause.iter().any(|s| s.is_some()) {
        // a sentence about no one keeps the previous referent available
    } else if dis.persons_last_sentence != 1 {
        dis.last_person = None;
    }
    let _ = cx.ents;
    out
}
