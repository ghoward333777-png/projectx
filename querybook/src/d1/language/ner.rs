//! Stage 3 — entity & relation extraction.
//!
//! * Named-entity recognition: people, places, organisations (from the work's
//!   concept table, typed by D3 evidence), plus dates, years and quantities
//!   recognized from token patterns.
//! * Entity normalization: every mention resolves to one canonical concept;
//!   variants ("Mr. Darcy", "Darcy", "DARCY'S") and acronyms ("NYC" -> the
//!   one entity whose initials match) meet on the same identifier.
//! * Predicate classification: the clause's main verb is classed (motion,
//!   communication, social, possession, cognition, emotion, creation, change,
//!   copula, action) and mapped to the governed predicate catalogue.

use super::lexicon::{self, VerbClass};
use super::parse::ClauseParse;
use super::tag::{Pos, Token};
use crate::d3::entities::EntityTable;
use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum EntKind {
    Person,
    Place,
    Org,
    Date,
    Quantity,
    Misc,
}

#[derive(Clone, Debug, Serialize)]
pub struct Mention {
    pub tokens: Vec<usize>,
    pub kind: EntKind,
    /// canonical concept id (named entities) or normalized literal (dates, quantities)
    pub concept: String,
    pub label: String,
    pub normalized: String,
}

const UNITS: &[&str] = &[
    "pounds", "pound", "guineas", "shillings", "pence", "dollars", "miles", "mile", "feet", "foot", "yards", "acres", "years",
    "year", "days", "weeks", "months", "hours", "minutes", "km", "kilometres", "kilometers", "metres", "meters", "kg", "tons",
    "percent", "per", "cent", "people", "men", "women", "soldiers", "ships",
];
const SEASONS: &[&str] = &["spring", "summer", "autumn", "fall", "winter"];

fn kind_of(ents: &EntityTable, e: usize) -> EntKind {
    let ent = &ents.entities[e];
    let label = ent.label.to_lowercase();
    if lexicon::ORG_WORDS.iter().any(|w| label.split(' ').any(|t| t == *w)) {
        return EntKind::Org;
    }
    match ent.kind.as_str() {
        "person" => EntKind::Person,
        "place" => EntKind::Place,
        _ => EntKind::Misc,
    }
}

/// Initials of a multi-word label: "New York City" -> "nyc".
fn initials(label: &str) -> String {
    label
        .split_whitespace()
        .filter(|w| w.chars().next().map(|c| c.is_uppercase()).unwrap_or(false))
        .filter_map(|w| w.chars().next())
        .collect::<String>()
        .to_lowercase()
}

pub fn recognize(tokens: &[Token], ents: &EntityTable) -> Vec<Mention> {
    let mut out: Vec<Mention> = Vec::new();
    let n = tokens.len();
    let mut i = 0;
    while i < n {
        let t = &tokens[i];
        // named entities from the concept table (a run of tokens with one entity id)
        if let Some(e) = t.ent {
            let mut j = i + 1;
            while j < n && tokens[j].ent == Some(e) {
                j += 1;
            }
            let ent = &ents.entities[e];
            out.push(Mention {
                tokens: (i..j).collect(),
                kind: kind_of(ents, e),
                concept: ent.concept.clone(),
                label: ent.label.clone(),
                normalized: crate::util::alias_key(&ent.label),
            });
            i = j;
            continue;
        }
        // acronym normalization: an all-caps token matching exactly one entity's initials
        if t.text.len() >= 2 && t.text.len() <= 6 && t.text.chars().all(|c| c.is_ascii_uppercase()) {
            let hits: Vec<usize> = (0..ents.entities.len()).filter(|&k| ents.entities[k].label.split_whitespace().count() >= 2 && initials(&ents.entities[k].label) == t.lower).collect();
            if hits.len() == 1 {
                let ent = &ents.entities[hits[0]];
                out.push(Mention { tokens: vec![i], kind: kind_of(ents, hits[0]), concept: ent.concept.clone(), label: ent.label.clone(), normalized: crate::util::alias_key(&ent.label) });
                i += 1;
                continue;
            }
        }
        // dates: [month] [day,] year | year | the 1880s | season of year
        if t.pos == Pos::Num {
            let digits: String = t.text.chars().filter(|c| c.is_ascii_digit()).collect();
            let year = digits.len() == 4 && !t.text.contains(',') && (1000..=2100).contains(&digits.parse::<u32>().unwrap_or(0));
            let next = tokens.get(i + 1).map(|x| x.lower.as_str()).unwrap_or("");
            if year {
                let mut s = i;
                if i >= 1 && lexicon::MONTHS.contains(&tokens[i - 1].lower.as_str()) {
                    s = i - 1;
                } else if i >= 3 && tokens[i - 1].text == "," && tokens[i - 2].pos == Pos::Num && lexicon::MONTHS.contains(&tokens[i - 3].lower.as_str()) {
                    s = i - 3;
                } else if i >= 2 && tokens[i - 1].lower == "of" && SEASONS.contains(&tokens[i - 2].lower.as_str()) {
                    s = i - 2;
                }
                out.push(Mention {
                    tokens: (s..=i).collect(),
                    kind: EntKind::Date,
                    concept: String::new(),
                    label: tokens[s..=i].iter().map(|x| x.text.as_str()).collect::<Vec<_>>().join(" ").replace(" ,", ","),
                    normalized: digits,
                });
                i += 1;
                continue;
            }
            if UNITS.contains(&next) {
                let value: String = t.text.replace(',', "");
                out.push(Mention {
                    tokens: vec![i, i + 1],
                    kind: EntKind::Quantity,
                    concept: String::new(),
                    label: format!("{} {}", t.text, tokens[i + 1].text),
                    normalized: format!("{value} {next}"),
                });
                i += 2;
                continue;
            }
        }
        i += 1;
    }
    out
}

/// A mention covering token `k`, if any.
pub fn mention_at(ms: &[Mention], k: usize) -> Option<&Mention> {
    ms.iter().find(|m| m.tokens.contains(&k))
}

/// Predicate classification for a parsed clause: (verb lemma, class).
pub fn classify(tokens: &[Token], p: &ClauseParse) -> Option<(String, VerbClass)> {
    let r = p.root?;
    if p.copular {
        return Some(("be".into(), VerbClass::Copula));
    }
    let t = &tokens[r];
    if !matches!(t.pos, Pos::Verb | Pos::Aux) {
        return None;
    }
    let lemma = if t.lemma.is_empty() { lexicon::verb_lemma(&t.lower) } else { t.lemma.clone() };
    let class = lexicon::verb_class(&lemma);
    Some((lemma, class))
}

#[cfg(test)]
mod tests {
    use super::super::tag::{tag, tokenize};
    use super::*;

    #[test]
    fn dates_quantities_acronyms() {
        let mut table = EntityTable::default();
        table.entities.push(crate::d3::entities::Entity {
            concept: "w:x/new-york-city".into(),
            label: "New York City".into(),
            kind: "place".into(),
            aliases: Default::default(),
            freq: 5,
            first_pos: 0,
        });
        let s = "In March 1889 the NYC office paid 1,200 pounds.";
        let mut t = tokenize(s);
        tag(&mut t, &[]);
        let ms = recognize(&t, &table);
        let kinds: Vec<(EntKind, String)> = ms.iter().map(|m| (m.kind, m.normalized.clone())).collect();
        assert!(kinds.contains(&(EntKind::Date, "1889".into())), "{kinds:?}");
        assert!(kinds.contains(&(EntKind::Place, "new york city".into())), "{kinds:?}");
        assert!(kinds.contains(&(EntKind::Quantity, "1200 pounds".into())), "{kinds:?}");
    }
}
