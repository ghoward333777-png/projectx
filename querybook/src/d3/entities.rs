//! Concept identity for a work: proper-name detection, alias grouping and
//! canonical concept identifiers ("w:<work>/<slug>"). Deterministic.

use crate::d1::parse::Book;
use crate::d1::segment::{base_form, sentences, tokens};
use crate::util::{canon_text, slug};
use std::collections::{BTreeMap, BTreeSet};

pub const TITLES: &[&str] = &[
    "mr",
    "mrs",
    "miss",
    "ms",
    "dr",
    "lady",
    "lord",
    "sir",
    "colonel",
    "col",
    "captain",
    "capt",
    "aunt",
    "uncle",
    "king",
    "queen",
    "prince",
    "princess",
    "duke",
    "duchess",
    "rev",
    "reverend",
    "professor",
    "prof",
    "saint",
    "st",
    "general",
    "major",
    "lieutenant",
    "mister",
    "madame",
    "monsieur",
    "count",
    "countess",
    "master",
    "mistress",
    "father",
    "mother",
    "brother",
    "sister",
    "judge",
    "president",
    "senator",
    "governor",
    "doctor",
];
const CONNECTORS: &[&str] = &["de", "of", "van", "von", "la", "du", "da", "del", "le", "bin", "al"];
const NOT_NAMES: &[&str] = &[
    "i",
    "i'm",
    "i'll",
    "i've",
    "i'd",
    "o",
    "oh",
    "ah",
    "yes",
    "no",
    "chapter",
    "volume",
    "book",
    "part",
    "the",
    "a",
    "an",
    "and",
    "but",
    "or",
    "nor",
    "if",
    "then",
    "when",
    "where",
    "what",
    "why",
    "how",
    "who",
    "which",
    "whose",
    "whom",
    "this",
    "that",
    "these",
    "those",
    "he",
    "she",
    "it",
    "they",
    "we",
    "you",
    "his",
    "her",
    "its",
    "their",
    "our",
    "your",
    "my",
    "mine",
    "well",
    "now",
    "here",
    "there",
    "so",
    "as",
    "at",
    "in",
    "on",
    "to",
    "for",
    "with",
    "by",
    "from",
    "of",
    "upon",
    "after",
    "before",
    "sir",
    "madam",
    "ma'am",
    "dear",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "god",
    "heaven",
    "lord",
    "mr",
    "mrs",
    "miss",
    "english",
    "french",
    "christmas",
    "project",
    "gutenberg",
    "ebook",
    "illustration",
    "contents",
    "preface",
    "letter",
    "note",
    "end",
    "finis",
    "not",
    "do",
    "don't",
    "did",
    "is",
    "was",
    "be",
    "let",
    "pray",
    "indeed",
    "perhaps",
    "nothing",
    "every",
    "all",
    "one",
];
const SPEECH: &[&str] =
    &["said", "replied", "cried", "asked", "answered", "exclaimed", "continued", "added", "observed", "returned"];
const PLACE_PREPS: &[&str] = &["at", "in", "to", "from", "near", "into", "towards", "toward", "through"];

#[derive(Clone, Debug)]
pub struct Entity {
    pub concept: String,
    pub label: String,
    /// "person" | "place" | "entity"
    pub kind: String,
    pub aliases: BTreeSet<String>,
    pub freq: u32,
    pub first_pos: u64,
}

#[derive(Clone, Debug, Default)]
pub struct EntityTable {
    pub entities: Vec<Entity>,
    /// surface form (canonical text) -> entity index
    pub surface: BTreeMap<String, usize>,
    pub max_len: usize,
}

#[derive(Default, Clone)]
struct Stat {
    freq: u32,
    first_pos: u64,
    titled: bool,
    speech: u32,
    place: u32,
    display: BTreeMap<String, u32>,
}

fn is_cap(t: &str) -> bool {
    t.chars().next().map(|c| c.is_uppercase()).unwrap_or(false)
}

fn norm_title(t: &str) -> String {
    t.trim_end_matches('.').to_lowercase()
}

/// The single candidate, or one that out-mentions every rival three to one.
fn dominant(cands: &[&String], stats: &BTreeMap<String, Stat>) -> Option<String> {
    match cands.len() {
        0 => None,
        1 => Some(cands[0].clone()),
        _ => {
            let mut v: Vec<(u32, &String)> = cands.iter().map(|c| (stats[*c].freq, *c)).collect();
            v.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(b.1)));
            (v[0].0 >= 3 * v[1].0).then(|| v[0].1.clone())
        }
    }
}

pub fn detect(book: &Book) -> EntityTable {
    // lowercase usage of every word, to reject capitalized common words
    let mut lower_freq: BTreeMap<String, u32> = BTreeMap::new();
    let mut sents: Vec<(u64, String)> = Vec::new();
    for p in &book.passages {
        if p.kind != "p" {
            continue;
        }
        for s in sentences(&p.text) {
            for t in tokens(&s) {
                if !is_cap(t.text) {
                    *lower_freq.entry(t.text.to_lowercase()).or_insert(0) += 1;
                }
            }
            sents.push((p.pos, s));
        }
    }
    let mut stats: BTreeMap<String, Stat> = BTreeMap::new();
    for (pos, s) in &sents {
        let toks = tokens(s);
        let mut i = 0;
        while i < toks.len() {
            let t = toks[i].text;
            if !is_cap(t) {
                i += 1;
                continue;
            }
            let mut j = i;
            let mut parts: Vec<&str> = Vec::new();
            let titled = TITLES.contains(&norm_title(t).as_str()) && i + 1 < toks.len() && is_cap(toks[i + 1].text);
            while j < toks.len() {
                let w = toks[j].text;
                // a run of name tokens never crosses punctuation
                if j > i && s[toks[j - 1].end..toks[j].start].chars().any(|c| !c.is_whitespace()) {
                    break;
                }
                if w == "I" && j > i {
                    break;
                }
                if is_cap(w) {
                    parts.push(w);
                    j += 1;
                    if w.ends_with("'s") || w.ends_with("\u{2019}s") {
                        break;
                    }
                } else if CONNECTORS.contains(&w) && j + 1 < toks.len() && is_cap(toks[j + 1].text) && !parts.is_empty() {
                    parts.push(w);
                    j += 1;
                } else {
                    break;
                }
                if parts.len() >= 5 {
                    break;
                }
            }
            // trim leading non-name words ("But Elizabeth" -> "Elizabeth")
            while parts.len() > 1
                && NOT_NAMES.contains(&parts[0].to_lowercase().as_str())
                && !TITLES.contains(&norm_title(parts[0]).as_str())
            {
                parts.remove(0);
            }
            let last = parts.len().saturating_sub(1);
            let cleaned: Vec<String> =
                parts.iter().enumerate().map(|(k, w)| if k == last { base_form(w).to_string() } else { w.to_string() }).collect();
            let surface = cleaned.join(" ");
            let key = canon_text(&surface);
            let first_word = key.split(' ').next().unwrap_or("").to_string();
            let single = cleaned.len() == 1;
            let common = single && {
                let lf = lower_freq.get(&key).copied().unwrap_or(0);
                lf >= 2
            };
            let title_only = cleaned.iter().all(|w| TITLES.contains(&norm_title(w).as_str()));
            if !surface.is_empty()
                && !common
                && !title_only
                && !(single && NOT_NAMES.contains(&first_word.as_str()))
                && key.len() > 1
            {
                let st = stats.entry(key).or_insert_with(|| Stat { first_pos: *pos, ..Default::default() });
                st.freq += 1;
                st.titled |= titled;
                *st.display.entry(surface).or_insert(0) += 1;
                let prev = if i > 0 { toks[i - 1].text.to_lowercase() } else { String::new() };
                let next = toks.get(j).map(|t| t.text.to_lowercase()).unwrap_or_default();
                if SPEECH.contains(&prev.as_str()) || SPEECH.contains(&next.as_str()) {
                    st.speech += 1;
                }
                if PLACE_PREPS.contains(&prev.as_str()) {
                    st.place += 1;
                }
            }
            i = j.max(i + 1);
        }
    }
    stats.retain(|k, s| s.freq >= 2 && !k.chars().all(|c| c.is_numeric() || c == ' '));

    // Group surface forms into concepts.
    let names: Vec<String> = stats.keys().cloned().collect();
    let name_tokens = |k: &str| -> Vec<String> {
        k.split(' ').filter(|w| !TITLES.contains(&norm_title(w).as_str())).map(|w| w.to_string()).collect()
    };
    let multi: Vec<&String> = names.iter().filter(|k| name_tokens(k).len() >= 2).collect();
    let mut owner: BTreeMap<String, String> = BTreeMap::new(); // surface -> canonical surface
    for k in &names {
        let toks = name_tokens(k);
        if toks.len() == 1 && !k.contains(' ') {
            let tok = &toks[0];
            let firsts: Vec<&String> = multi.iter().copied().filter(|m| name_tokens(m).first() == Some(tok)).collect();
            if let Some(o) = dominant(&firsts, &stats) {
                owner.insert(k.clone(), o);
                continue;
            }
            let lasts: Vec<&String> =
                names.iter().filter(|m| *m != k && m.contains(' ') && name_tokens(m).last() == Some(tok)).collect();
            if let Some(o) = dominant(&lasts, &stats) {
                owner.insert(k.clone(), o);
                continue;
            }
        }
        owner.insert(k.clone(), k.clone());
    }
    // resolve chains (a -> b -> c)
    let keys: Vec<String> = owner.keys().cloned().collect();
    for k in keys {
        let mut c = owner[&k].clone();
        for _ in 0..4 {
            match owner.get(&c) {
                Some(n) if *n != c => c = n.clone(),
                _ => break,
            }
        }
        owner.insert(k, c);
    }

    let mut groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for (surface, canon) in &owner {
        groups.entry(canon.clone()).or_default().push(surface.clone());
    }
    let mut table = EntityTable::default();
    for (canon, members) in groups {
        let mut freq = 0;
        let mut first = u64::MAX;
        let (mut titled, mut speech, mut place) = (false, 0, 0);
        for m in &members {
            let s = &stats[m];
            freq += s.freq;
            first = first.min(s.first_pos);
            titled |= s.titled;
            speech += s.speech;
            place += s.place;
        }
        let mut displays: BTreeMap<&String, u32> = BTreeMap::new();
        for m in &members {
            for (d, n) in &stats[m].display {
                *displays.entry(d).or_insert(0) += n;
            }
        }
        let label = displays.iter().max_by_key(|(d, n)| (**n, d.len())).map(|(d, _)| (*d).clone()).unwrap_or(canon.clone());
        let kind = if titled {
            "person"
        } else if place >= 2 && place * 4 >= freq && place >= speech {
            "place"
        } else if speech >= 1 {
            "person"
        } else {
            "entity"
        };
        let idx = table.entities.len();
        let aliases: BTreeSet<String> = members.iter().cloned().collect();
        for a in &aliases {
            table.surface.insert(a.clone(), idx);
            table.max_len = table.max_len.max(a.split(' ').count());
        }
        table.entities.push(Entity {
            concept: format!("w:{}/{}", book.id, slug(&label)),
            label,
            kind: kind.into(),
            aliases,
            freq,
            first_pos: first,
        });
    }
    table
}

impl EntityTable {
    /// Longest-match entity mentions in a sentence: (byte start, byte end, entity index).
    pub fn mentions(&self, sentence: &str) -> Vec<(usize, usize, usize)> {
        let toks = tokens(sentence);
        let mut out = Vec::new();
        let mut i = 0;
        while i < toks.len() {
            let mut hit = None;
            for len in (1..=self.max_len.min(toks.len() - i)).rev() {
                let span = &toks[i..i + len];
                if !is_cap(span[0].text) {
                    break;
                }
                let words: Vec<&str> =
                    span.iter().enumerate().map(|(k, t)| if k == len - 1 { base_form(t.text) } else { t.text }).collect();
                let key = canon_text(&words.join(" "));
                if let Some(&e) = self.surface.get(&key) {
                    hit = Some((span[0].start, span[len - 1].end, e, len));
                    break;
                }
            }
            match hit {
                Some((s, e, idx, len)) => {
                    out.push((s, e, idx));
                    i += len;
                }
                None => i += 1,
            }
        }
        out
    }
}
