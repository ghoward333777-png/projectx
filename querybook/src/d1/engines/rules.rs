//! Built-in deterministic extractor: no network, no model, runs on the
//! operator's own server. Pattern-based over sentences with resolved entity
//! mentions. Its records are marked with derivation engine "rules".

use super::{Candidate, EngineReport, Extractor};
use crate::d1::parse::Book;
use crate::d1::segment::{sentences, tokens};
use crate::d2::{Atom, Value};
use crate::d3::Catalog;
use crate::d3::entities::EntityTable;
use crate::util::{is_stopword, slug, words};
use std::collections::BTreeMap;

pub struct RuleEngine {
    pub id: String,
    pub reliability: f64,
}

const KIN: &[&str] = &[
    "father",
    "mother",
    "sister",
    "brother",
    "wife",
    "husband",
    "daughter",
    "son",
    "aunt",
    "uncle",
    "cousin",
    "niece",
    "nephew",
    "grandfather",
    "grandmother",
    "friend",
    "sisters",
    "daughters",
    "sons",
    "brothers",
];
const DETERMINERS: &[&str] = &["a", "an", "the", "his", "her", "their", "one", "my", "our", "its"];
const INTENSIFIERS: &[&str] = &[
    "very",
    "so",
    "too",
    "quite",
    "rather",
    "extremely",
    "remarkably",
    "perfectly",
    "most",
    "not",
    "always",
    "never",
    "still",
    "therefore",
    "far",
    "yet",
    "thus",
    "now",
    "then",
    "already",
    "ever",
    "much",
    "also",
    "however",
    "indeed",
    "only",
    "just",
    "soon",
    "almost",
    "equally",
    "really",
    "certainly",
    "surely",
    "probably",
    "perhaps",
    "sometimes",
    "often",
    "once",
    "again",
];
const IRREGULAR_PAST: &[&str] = &[
    "went",
    "came",
    "saw",
    "took",
    "gave",
    "made",
    "found",
    "left",
    "told",
    "thought",
    "felt",
    "knew",
    "brought",
    "sent",
    "began",
    "wrote",
    "ran",
    "sat",
    "stood",
    "spoke",
    "heard",
    "met",
    "kept",
    "lost",
    "held",
    "led",
    "fell",
    "rose",
    "became",
    "bought",
    "caught",
    "fought",
    "sought",
    "taught",
    "won",
    "drew",
    "threw",
    "grew",
    "chose",
    "broke",
    "forgot",
    "forgave",
    "hid",
    "bit",
    "shook",
    "struck",
    "swore",
    "tore",
    "wore",
    "woke",
    "rode",
    "drove",
    "flew",
    "sang",
    "spent",
    "got",
    "put",
    "read",
    "let",
    "set",
    "shut",
    "cut",
    "hurt",
    "paid",
    "laid",
    "meant",
    "slept",
    "wept",
    "swept",
    "understood",
];
const NOT_EVENT_VERBS: &[&str] = &[
    "was",
    "were",
    "is",
    "are",
    "had",
    "has",
    "said",
    "replied",
    "cried",
    "asked",
    "answered",
    "exclaimed",
    "added",
    "continued",
    "observed",
    "returned",
    "need",
    "indeed",
];
const SPEECH: &[&str] = &[
    "said",
    "replied",
    "cried",
    "asked",
    "answered",
    "exclaimed",
    "continued",
    "added",
    "observed",
    "returned",
    "whispered",
    "called",
    "says",
];

fn is_past_verb(w: &str) -> bool {
    let l = w.to_lowercase();
    if NOT_EVENT_VERBS.contains(&l.as_str()) {
        return false;
    }
    IRREGULAR_PAST.contains(&l.as_str()) || (l.len() > 4 && l.ends_with("ed") && !l.ends_with("eed") && !l.ends_with("ness"))
}

/// Cut a phrase at the first clause boundary, keep at most `max` words.
/// Commas inside adjective lists are crossed ("a conceited, pompous, silly
/// man"); a phrase that reaches `max` without a boundary is refused, since a
/// truncated phrase would assert something the text does not.
fn phrase(s: &str, max: usize, stop_at_and: bool) -> Option<String> {
    const BREAK_AFTER_COMMA: &[&str] = &[
        "you", "he", "she", "it", "they", "we", "i", "and", "but", "who", "which", "that", "as", "when", "while", "though",
        "although", "if", "for", "so", "or", "nor", "yet", "said", "says", "replied", "cried", "the", "a", "an", "his", "her",
        "their", "whose", "where", "with", "without", "after", "before", "because", "since", "until", "unless",
    ];
    let ws: Vec<&str> = s.split_whitespace().collect();
    let mut out: Vec<String> = Vec::new();
    for (i, w) in ws.iter().enumerate() {
        let bare = w.trim_matches(|c: char| !c.is_alphanumeric() && c != '\'' && c != '-' && c != '’');
        let lw = bare.to_lowercase();
        if out.len() >= 2
            && (lw == "who" || lw == "which" || lw == "that" || (stop_at_and && lw == "and" && out.len() >= 3) || lw == "but")
        {
            return Some(out.join(" "));
        }
        if !bare.is_empty() {
            out.push(bare.to_string());
        }
        let abbrev = w.ends_with('.') && crate::d3::entities::TITLES.contains(&lw.as_str());
        let hard = !abbrev && w.ends_with([';', ':', '.', '!', '?', '”', '"', ')']);
        if hard {
            return Some(out.join(" "));
        }
        if w.ends_with(',') {
            let next = ws.get(i + 1).map(|n| n.trim_matches(|c: char| !c.is_alphanumeric()).to_lowercase()).unwrap_or_default();
            let verbish = !next.contains('-') && (next.ends_with("ed") || next.ends_with("ing"));
            let continues = !next.is_empty() && !BREAK_AFTER_COMMA.contains(&next.as_str()) && !verbish && out.len() < max;
            if !continues {
                return Some(out.join(" "));
            }
            let last = out.pop().unwrap();
            out.push(format!("{last},"));
        }
        if out.len() >= max {
            return if i + 1 == ws.len() { Some(out.join(" ")) } else { None };
        }
    }
    if out.is_empty() { None } else { Some(out.join(" ")) }
}

/// Remove quotation marks that open or close outside the sentence.
fn balance_quotes(s: &str) -> String {
    let opens = s.matches('\u{201C}').count();
    let closes = s.matches('\u{201D}').count();
    let mut t = s.trim().to_string();
    if closes > opens && t.ends_with('\u{201D}') {
        t.pop();
    }
    if opens > closes && t.starts_with('\u{201C}') {
        t.remove(0);
    }
    t.trim().to_string()
}

struct Ctx<'a> {
    book: &'a Book,
    ents: &'a EntityTable,
    engine: &'a str,
}

impl<'a> Ctx<'a> {
    fn cand(
        &self,
        pred: &str,
        type_ref: &str,
        subj: usize,
        object: Value,
        args: BTreeMap<String, Value>,
        pos: u64,
        chapter: u32,
        quote: &str,
    ) -> Candidate {
        let mut labels = BTreeMap::new();
        let s = &self.ents.entities[subj];
        labels.insert(s.concept.clone(), s.label.clone());
        let mut add = |v: &Value| {
            if let Value::Concept(c) = v {
                if let Some(e) = self.ents.entities.iter().find(|e| &e.concept == c) {
                    labels.insert(c.clone(), e.label.clone());
                }
            }
        };
        add(&object);
        for v in args.values() {
            add(v);
        }
        Candidate {
            type_ref: type_ref.into(),
            atom: Atom { subject: s.concept.clone(), predicate: pred.into(), object, args, polarity: true },
            labels,
            pos,
            chapter,
            quote: quote.to_string(),
            engine: self.engine.into(),
            prompt_hash: None,
            citation_verified: true,
            sentence: None,
            weight: 1.0,
        }
    }
}

impl Extractor for RuleEngine {
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
        let ctx = Ctx { book, ents, engine: &self.id };
        let _ = ctx.book;
        let mut out = Vec::new();
        let fictionish = ents.entities.iter().filter(|e| e.kind == "person").count() >= 5;
        // salient terms for non-fiction subjects
        let mut term_freq: BTreeMap<String, u32> = BTreeMap::new();
        if !fictionish {
            for p in &book.passages {
                for w in words(&p.text) {
                    if w.len() > 3 && !is_stopword(&w) {
                        *term_freq.entry(w).or_insert(0) += 1;
                    }
                }
            }
        }
        let mut term_entities: BTreeMap<String, usize> = BTreeMap::new();
        let mut local = EntityTable { entities: ents.entities.clone(), surface: ents.surface.clone(), max_len: ents.max_len };
        let total = book.passages.len().max(1);
        for (pi, p) in book.passages.iter().enumerate() {
            if pi % 500 == 0 {
                progress(&format!("rules: passage {pi}/{total}"));
            }
            if p.kind != "p" {
                continue;
            }
            for s in sentences(&p.text) {
                let wc = s.split_whitespace().count();
                if wc < 3 {
                    continue;
                }
                let ms = ents.mentions(&s);
                let before = out.len();
                self.patterns(&ctx, &s, &ms, p.pos, p.chapter, &mut out);
                let fired = out.len() > before;
                // fall-back claim record: one declarative sentence about its first-named subject
                if !fired && (6..=48).contains(&wc) && !s.contains('?') {
                    if let Some(&(_, _, e)) = ms.first() {
                        out.push(ctx.cand(
                            "states",
                            "assertion.claim",
                            e,
                            Value::Text(balance_quotes(&s)),
                            BTreeMap::new(),
                            p.pos,
                            p.chapter,
                            &s,
                        ));
                    } else if !fictionish {
                        // non-fiction: subject is the sentence's most salient repeated term
                        let best = words(&s)
                            .into_iter()
                            .filter(|w| w.len() > 3 && !is_stopword(w))
                            .filter_map(|w| term_freq.get(&w).map(|f| (*f, w)))
                            .filter(|(f, _)| *f >= 4)
                            .max_by(|a, b| a.0.cmp(&b.0).then_with(|| b.1.cmp(&a.1)));
                        if let Some((_, term)) = best {
                            let idx = *term_entities.entry(term.clone()).or_insert_with(|| {
                                local.entities.push(crate::d3::entities::Entity {
                                    concept: format!("w:{}/term-{}", book.id, slug(&term)),
                                    label: term.clone(),
                                    kind: "concept".into(),
                                    aliases: [term.clone()].into_iter().collect(),
                                    freq: 0,
                                    first_pos: p.pos,
                                });
                                local.entities.len() - 1
                            });
                            let lctx = Ctx { book, ents: &local, engine: &self.id };
                            out.push(lctx.cand(
                                "states",
                                "assertion.claim",
                                idx,
                                Value::Text(balance_quotes(&s)),
                                BTreeMap::new(),
                                p.pos,
                                p.chapter,
                                &s,
                            ));
                        }
                    }
                }
            }
        }
        let refused = out.iter().filter(|c| catalog.get(&c.atom.predicate).is_none()).count();
        out.retain(|c| catalog.get(&c.atom.predicate).is_some());
        let report = EngineReport { engine: self.id.clone(), candidates: out.len(), refused, ..Default::default() };
        Ok((out, report))
    }
}

impl RuleEngine {
    fn patterns(&self, ctx: &Ctx, s: &str, ms: &[(usize, usize, usize)], pos: u64, ch: u32, out: &mut Vec<Candidate>) {
        let concept = |i: usize| Value::Concept(ctx.ents.entities[i].concept.clone());
        let none = BTreeMap::new;

        // (A) direct speech: “...,” said X  /  X said, “...”
        let mut quotes: Vec<(usize, usize)> = Vec::new();
        let mut open: Option<usize> = None;
        for (i, c) in s.char_indices() {
            match c {
                '\u{201C}' => open = Some(i + c.len_utf8()),
                '\u{201D}' => {
                    if let Some(o) = open.take() {
                        quotes.push((o, i));
                    }
                }
                _ => {}
            }
        }
        if !quotes.is_empty() {
            let joined = quotes
                .iter()
                .map(|&(qs, qe)| s[qs..qe].trim().trim_end_matches(',').trim().to_string())
                .collect::<Vec<_>>()
                .join(" ");
            let (qs, qe) = (quotes[0].0, quotes[0].1);
            let after_q = &s[qe..];
            let inside = |m: &&(usize, usize, usize)| quotes.iter().any(|&(a, b)| m.0 >= a && m.1 <= b);
            let speaker = ms.iter().filter(|m| !inside(m)).find(|m| {
                m.0 >= qe && m.0 - qe < 40 && {
                    let gap = s[qe..m.0].to_lowercase();
                    SPEECH.iter().any(|v| gap.contains(v))
                        || after_q.trim_start_matches(['\u{201D}', ',', ' ']).to_lowercase().starts_with("said")
                }
            });
            let speaker = speaker.or_else(|| {
                ms.iter()
                    .rev()
                    .filter(|m| !inside(m))
                    .find(|m| m.1 <= qs && qs - m.1 < 24 && SPEECH.iter().any(|v| s[m.1..qs].to_lowercase().contains(v)))
            });
            if let (Some(m), true) = (speaker, joined.split_whitespace().count() >= 3) {
                out.push(ctx.cand("says", "event.speech", m.2, Value::Text(joined), none(), pos, ch, s));
            }
        }
        if !quotes.is_empty() {
            return;
        }

        for (mi, &(_, end, e)) in ms.iter().enumerate() {
            let after = s[end..].trim_start();
            let after_l = after.to_lowercase();
            let next_m = ms.get(mi + 1);

            let head = s[..ms[mi].0].trim();
            let hl = head.to_lowercase();
            let clause_initial = head.is_empty()
                || head.ends_with([',', ';', '—', ':', '“', '"'])
                || ["and", "but", "then", "so", "yet", "when", "while", "after", "before", "though", "although", "once"]
                    .contains(&hl.as_str())
                || [", and", ", but", "; and", "; but", ", then", ", when", ", while"].iter().any(|t| hl.ends_with(t));

            // (C) appositive: "X, the heir of the estate,"
            if let (true, Some(rest)) = (clause_initial && !hl.ends_with(" of"), after.strip_prefix(", ")) {
                let first = rest.split_whitespace().next().unwrap_or("").to_lowercase();
                // vocatives ("Lydia, my love,") are address, not description
                if DETERMINERS.contains(&first.as_str()) && !["my", "our", "your"].contains(&first.as_str()) {
                    if let Some(np) = phrase(rest, 9, false) {
                        let words_n = np.split_whitespace().count();
                        let closes = rest.get(np.len()..).map(|r| r.starts_with(',')).unwrap_or(false);
                        if words_n >= 2 && closes && !KIN.iter().any(|k| np.ends_with(k)) {
                            out.push(ctx.cand("is_a", "assertion.property", e, Value::Text(np), none(), pos, ch, s));
                        }
                    }
                }
            }

            // (D) kinship: "X's sister, Y" / "Y, X's sister"
            if let Some(k) = KIN.iter().find(|k| {
                after_l.starts_with(&format!("{k}"))
                    && s[..end].ends_with(['s'])
                    && (s[..end].ends_with("'s") || s[..end].ends_with("’s"))
            }) {
                if let Some(nm) = next_m {
                    if nm.0 - end < k.len() + 6 {
                        let mut args = BTreeMap::new();
                        args.insert("relation".to_string(), Value::Text(k.trim_end_matches('s').to_string()));
                        out.push(ctx.cand("relative_of", "assertion.relation", nm.2, concept(e), args, pos, ch, s));
                    }
                }
            }
            if let Some(nm) = next_m {
                // (D2) binary relations between two named parties
                let rel = s[end..nm.0].trim().to_lowercase();
                let rel = rel.trim_matches(',').trim();
                let pred = match rel {
                    "married" | "marries" | "is married to" | "was married to" | "had married" => {
                        Some(("married_to", "assertion.relation"))
                    }
                    "was engaged to" | "is engaged to" | "became engaged to" => Some(("engaged_to", "assertion.relation")),
                    "loved" | "loves" | "was in love with" | "is in love with" | "fell in love with" => {
                        Some(("loves", "assertion.relation"))
                    }
                    "met" | "meets" | "was introduced to" => Some(("meets", "event.action")),
                    "visited" | "went to" | "returned to" | "arrived at" | "set off for" | "travelled to" | "traveled to"
                    | "came to" => Some(("visits", "event.action")),
                    "lived at" | "lived in" | "lives at" | "lives in" | "resided at" | "resided in" | "of" => {
                        if rel == "of" {
                            if ctx.ents.entities[nm.2].kind == "place" && ctx.ents.entities[e].kind == "person" {
                                Some(("lives_in", "assertion.relation"))
                            } else {
                                None
                            }
                        } else {
                            Some(("lives_in", "assertion.relation"))
                        }
                    }
                    "disliked" | "despised" | "hated" => Some(("dislikes", "assertion.relation")),
                    "is the friend of" | "was the friend of" | "is a friend of" | "was a friend of" => {
                        Some(("friend_of", "assertion.relation"))
                    }
                    _ => None,
                };
                if let Some((p, t)) = pred {
                    out.push(ctx.cand(p, t, e, concept(nm.2), none(), pos, ch, s));
                    continue;
                }
            }

            // only clause-initial subjects for copula and event patterns
            if !clause_initial {
                continue;
            }

            // (B) copula: "X was a ..." / "X was very handsome"
            let tw: Vec<&str> = after.split_whitespace().collect();
            if tw.len() >= 2 && matches!(tw[0], "is" | "was") {
                let rest = &after[tw[0].len()..].trim_start();
                let w1 = tw[1].trim_matches(|c: char| !c.is_alphanumeric()).to_lowercase();
                if DETERMINERS.contains(&w1.as_str()) {
                    if let Some(np) = phrase(rest, 10, true) {
                        if np.split_whitespace().count() >= 2 {
                            out.push(ctx.cand("is_a", "assertion.property", e, Value::Text(np), none(), pos, ch, s));
                            continue;
                        }
                    }
                } else if let Some(ap) = phrase(rest, 6, false) {
                    const PREPS: &[&str] =
                        &["in", "to", "of", "with", "at", "for", "on", "by", "from", "about", "as", "than", "and", "or"];
                    let ap: String = ap
                        .split_whitespace()
                        .take_while(|w| !PREPS.contains(&w.to_lowercase().as_str()))
                        .collect::<Vec<_>>()
                        .join(" ");
                    let ap = ap.trim_end_matches(',').to_string();
                    let aw: Vec<String> = ap.split_whitespace().map(|w| w.to_lowercase()).collect();
                    let head_word = aw.iter().find(|w| !INTENSIFIERS.contains(&w.as_str())).cloned().unwrap_or_default();
                    let starts_with_adverb = aw
                        .first()
                        .map(|w| {
                            INTENSIFIERS.contains(&w.as_str())
                                && ![
                                    "very",
                                    "so",
                                    "too",
                                    "quite",
                                    "rather",
                                    "extremely",
                                    "remarkably",
                                    "perfectly",
                                    "most",
                                    "not",
                                ]
                                .contains(&w.as_str())
                        })
                        .unwrap_or(false);
                    let adjectival = !head_word.is_empty()
                        && !starts_with_adverb
                        && head_word.len() >= 4
                        && !head_word.ends_with("ing")
                        && !(head_word.ends_with("ed") && !head_word.ends_with("ted") && head_word.len() > 6)
                        && !is_stopword(&head_word)
                        && !["gone", "come", "being", "been", "able", "going", "there", "here", "now", "then", "also"]
                            .contains(&head_word.as_str())
                        && !aw.is_empty()
                        && aw.len() <= 3;
                    if adjectival {
                        out.push(ctx.cand("has_trait", "assertion.property", e, Value::Text(ap), none(), pos, ch, s));
                        continue;
                    }
                }
            }

            // (E) event: "X refused him." -> performs(X, "refused him")
            let toks = tokens(after);
            let mut vi = 0;
            while vi < toks.len()
                && [
                    "had",
                    "then",
                    "at",
                    "once",
                    "soon",
                    "now",
                    "immediately",
                    "instantly",
                    "afterwards",
                    "also",
                    "never",
                    "only",
                    "presently",
                ]
                .contains(&toks[vi].text.to_lowercase().as_str())
            {
                vi += 1;
            }
            let direct = after.chars().next().map(|c| c.is_alphabetic()).unwrap_or(false);
            if let (true, Some(v)) = (direct, toks.get(vi)) {
                if is_past_verb(v.text) {
                    let tail = &after[toks[0].start..];
                    if let Some(vp) = phrase(tail, 18, false) {
                        if vp.split_whitespace().count() >= 2 {
                            let vp = vp.trim_end_matches([',', ';', '.']).to_string();
                            out.push(ctx.cand("performs", "event.action", e, Value::Text(vp), none(), pos, ch, s));
                        }
                    }
                }
            }
        }
    }
}
