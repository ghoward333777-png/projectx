//! Stage 2a — tokenization and part-of-speech tagging.
//!
//! Tokens keep punctuation (clause decomposition needs it), split possessive
//! 's, keep title abbreviations ("Mr.") and numbers ("1,200", "3.14") whole.
//! Tagging is lexical lookup, then morphology, then contextual correction
//! rules applied left to right (a Brill-style transformation pass), all
//! deterministic. Tag set: Universal Dependencies UPOS.

use super::lexicon::*;
use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum Pos {
    Noun,
    Propn,
    Verb,
    Aux,
    Adj,
    Adv,
    Adp,
    Det,
    Pron,
    Cconj,
    Sconj,
    Num,
    Part,
    Punct,
    X,
}

impl Pos {
    pub fn tag(self) -> &'static str {
        match self {
            Pos::Noun => "NOUN",
            Pos::Propn => "PROPN",
            Pos::Verb => "VERB",
            Pos::Aux => "AUX",
            Pos::Adj => "ADJ",
            Pos::Adv => "ADV",
            Pos::Adp => "ADP",
            Pos::Det => "DET",
            Pos::Pron => "PRON",
            Pos::Cconj => "CCONJ",
            Pos::Sconj => "SCONJ",
            Pos::Num => "NUM",
            Pos::Part => "PART",
            Pos::Punct => "PUNCT",
            Pos::X => "X",
        }
    }
    pub fn nominal(self) -> bool {
        matches!(self, Pos::Noun | Pos::Propn | Pos::Pron | Pos::Num)
    }
}

/// Verb form feature.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum Form {
    None,
    Base,
    Pres3,
    Past,
    Part,
    Ger,
}

#[derive(Clone, Debug, Serialize)]
pub struct Token {
    pub text: String,
    pub lower: String,
    pub start: usize,
    pub end: usize,
    pub pos: Pos,
    pub form: Form,
    pub lemma: String,
    /// entity index (EntityTable) when the token is part of a named mention
    pub ent: Option<usize>,
    /// true for the first token of a sentence
    pub initial: bool,
}

const TITLE_ABBR: &[&str] = &["mr.", "mrs.", "ms.", "dr.", "st.", "col.", "capt.", "gen.", "lt.", "rev.", "prof.", "mt.", "jr.", "sr."];
const ING_NOUNS: &[&str] = &[
    "thing", "nothing", "something", "anything", "everything", "morning", "evening", "king", "ring", "wedding", "building",
    "feeling", "spring", "string", "ceiling", "meaning", "beginning", "being", "painting", "writing", "reading", "wing", "sing",
    "sibling", "darling", "lodging", "clothing", "meeting", "gathering", "blessing",
];
const LY_NOT_ADV: &[&str] = &[
    "family", "early", "lovely", "likely", "friendly", "lonely", "ugly", "holy", "silly", "daily", "reply", "supply", "fly",
    "ally", "rely", "apply", "only", "lily", "italy", "july", "belly", "jolly", "melancholy", "comely", "manly", "elderly",
];
const NOUN_SUFFIX: &[&str] = &["tion", "sion", "ment", "ness", "ity", "ism", "ance", "ence", "ship", "hood", "dom", "ist", "er", "or", "age", "ure"];
const ADJ_SUFFIX: &[&str] = &["ous", "ful", "ive", "able", "ible", "al", "ic", "less", "ish", "ent", "ant", "ary", "y"];

fn is_word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '\'' || c == '\u{2019}' || c == '-'
}

/// Split a sentence into tokens with byte spans.
pub fn tokenize(s: &str) -> Vec<Token> {
    let mut out = Vec::new();
    let chars: Vec<(usize, char)> = s.char_indices().collect();
    let mut i = 0;
    let mk = |t: &str, a: usize, b: usize| Token {
        text: t.to_string(),
        lower: t.to_lowercase().replace('\u{2019}', "'"),
        start: a,
        end: b,
        pos: Pos::X,
        form: Form::None,
        lemma: String::new(),
        ent: None,
        initial: false,
    };
    while i < chars.len() {
        let (bi, c) = chars[i];
        if c.is_whitespace() {
            i += 1;
            continue;
        }
        // numbers: 1,200  3.14  1889
        if c.is_ascii_digit() {
            let mut j = i;
            while j < chars.len()
                && (chars[j].1.is_ascii_digit()
                    || ((chars[j].1 == ',' || chars[j].1 == '.') && j + 1 < chars.len() && chars[j + 1].1.is_ascii_digit()))
            {
                j += 1;
            }
            let end = if j < chars.len() { chars[j].0 } else { s.len() };
            out.push(mk(&s[bi..end], bi, end));
            i = j;
            continue;
        }
        if is_word_char(c) && c != '\'' && c != '\u{2019}' && c != '-' {
            let mut j = i;
            while j < chars.len() && is_word_char(chars[j].1) {
                j += 1;
            }
            let mut end = if j < chars.len() { chars[j].0 } else { s.len() };
            let mut word = &s[bi..end];
            // trailing hyphens/apostrophes are punctuation
            while word.ends_with(['-', '\'', '\u{2019}']) {
                let l = word.chars().last().unwrap().len_utf8();
                end -= l;
                word = &s[bi..end];
                j -= 1;
            }
            // title abbreviation keeps its dot
            if j < chars.len() && chars[j].1 == '.' && TITLE_ABBR.contains(&format!("{}.", word.to_lowercase()).as_str()) {
                end += 1;
                j += 1;
                word = &s[bi..end];
            }
            // possessive 's -> separate PART token
            let lw = word.to_lowercase().replace('\u{2019}', "'");
            if lw.len() > 2 && lw.ends_with("'s") {
                let cut = end - (word.len() - word.rfind(['\'', '\u{2019}']).unwrap());
                out.push(mk(&s[bi..cut], bi, cut));
                out.push(mk(&s[cut..end], cut, end));
            } else if lw.ends_with("n't") && lw.len() > 3 {
                let cut = end - 3;
                out.push(mk(&s[bi..cut], bi, cut));
                out.push(mk(&s[cut..end], cut, end));
            } else {
                out.push(mk(word, bi, end));
            }
            i = j;
            continue;
        }
        let end = bi + c.len_utf8();
        out.push(mk(&s[bi..end], bi, end));
        i += 1;
    }
    if let Some(t) = out.iter_mut().find(|t| t.text.chars().any(|c| c.is_alphanumeric())) {
        t.initial = true;
    }
    out
}

fn is_cap(t: &str) -> bool {
    t.chars().next().map(|c| c.is_uppercase()).unwrap_or(false)
}

fn lexical(t: &mut Token) {
    let w = t.lower.as_str();
    if !t.text.chars().any(|c| c.is_alphanumeric()) {
        t.pos = Pos::Punct;
        return;
    }
    if t.text.chars().next().map(|c| c.is_ascii_digit()).unwrap_or(false) {
        t.pos = Pos::Num;
        return;
    }
    if t.ent.is_some() || TITLE_ABBR.contains(&w) {
        t.pos = Pos::Propn;
        return;
    }
    if w == "'s" || w == "'" {
        t.pos = Pos::Part;
        return;
    }
    if w == "n't" || w == "not" {
        t.pos = Pos::Part;
        return;
    }
    if is_in(AUX, w) {
        t.pos = Pos::Aux;
        t.lemma = verb_lemma(w);
        t.form = match w {
            "was" | "were" | "had" | "did" | "would" | "should" | "could" | "might" => Form::Past,
            "been" | "done" => Form::Part,
            "being" | "having" => Form::Ger,
            "is" | "has" | "does" => Form::Pres3,
            _ => Form::Base,
        };
        return;
    }
    if is_in(PRONOUNS, w) && w != "her" && w != "that" {
        t.pos = Pos::Pron;
        return;
    }
    if is_in(DETERMINERS, w) {
        t.pos = Pos::Det;
        return;
    }
    if is_in(COORD, w) {
        t.pos = Pos::Cconj;
        return;
    }
    if matches!(w, "because" | "although" | "though" | "whereas" | "unless" | "whether" | "if" | "when" | "whenever" | "while" | "lest") {
        t.pos = Pos::Sconj;
        return;
    }
    if is_in(PREPOSITIONS, w) {
        t.pos = Pos::Adp;
        return;
    }
    if is_in(ADVERBS, w) || (w.ends_with("ly") && w.len() > 4 && !LY_NOT_ADV.contains(&w)) {
        t.pos = Pos::Adv;
        return;
    }
    if is_in(MONTHS, w) && is_cap(&t.text) && w != "may" {
        t.pos = Pos::Propn;
        return;
    }
    if is_cap(&t.text) && !t.initial {
        t.pos = Pos::Propn;
        return;
    }
    // verbs: irregular forms, known regular verbs, morphology
    for (base, past, part) in IRREGULAR {
        if w == *past && w != *base {
            t.pos = Pos::Verb;
            t.form = if past == part { Form::Past } else { Form::Past };
            t.lemma = base.to_string();
            return;
        }
        if w == *part && w != *base && w != *past {
            t.pos = Pos::Verb;
            t.form = Form::Part;
            t.lemma = base.to_string();
            return;
        }
    }
    if w.ends_with("ing") && w.len() > 4 && !ING_NOUNS.contains(&w) {
        t.pos = Pos::Verb;
        t.form = Form::Ger;
        t.lemma = verb_lemma(w);
        return;
    }
    if w.ends_with("ed") && w.len() > 3 && !w.ends_with("eed") {
        t.pos = Pos::Verb;
        t.form = Form::Past;
        t.lemma = verb_lemma(w);
        return;
    }
    if COMMON_VERBS.contains(&w) || IRREGULAR.iter().any(|(b, _, _)| b == &w) {
        t.pos = Pos::Verb;
        t.form = Form::Base;
        t.lemma = w.to_string();
        return;
    }
    if w.ends_with('s') && w.len() > 3 && COMMON_VERBS.contains(&verb_lemma(w).as_str()) {
        t.pos = Pos::Verb;
        t.form = Form::Pres3;
        t.lemma = verb_lemma(w);
        return;
    }
    if NOUN_SUFFIX.iter().any(|s| w.ends_with(s) && w.len() > s.len() + 2) {
        t.pos = Pos::Noun;
        return;
    }
    if ADJ_SUFFIX.iter().any(|s| w.ends_with(s) && w.len() > s.len() + 2) {
        t.pos = Pos::Adj;
        return;
    }
    t.pos = Pos::Noun;
}

/// Tag tokens in place. `entity_spans` are (byte start, byte end, entity idx).
pub fn tag(tokens: &mut [Token], entity_spans: &[(usize, usize, usize)]) {
    for t in tokens.iter_mut() {
        t.ent = entity_spans.iter().find(|(a, b, _)| t.start >= *a && t.end <= *b).map(|x| x.2);
        lexical(t);
    }
    // sentence-initial capitalized word: a name only if it is a known entity
    let n = tokens.len();
    // contextual transformations, left to right
    for i in 0..n {
        // determiner governing this position, looking back across adjectives/numbers
        let det_before = {
            let mut k = i;
            let mut found = false;
            while k > 0 {
                k -= 1;
                match tokens[k].pos {
                    Pos::Adj | Pos::Num => continue,
                    Pos::Det => {
                        found = true;
                        break;
                    }
                    _ => break,
                }
            }
            found
        };
        let prev = if i > 0 { Some(tokens[i - 1].pos) } else { None };
        let prev_lower = if i > 0 { tokens[i - 1].lower.clone() } else { String::new() };
        let next = tokens.get(i + 1).map(|t| t.pos);
        let t = &mut tokens[i];
        match t.pos {
            // "the visit", "her love", "a promise": verb form after a determiner is a noun
            Pos::Verb if det_before && matches!(t.form, Form::Base | Form::Pres3) => {
                t.pos = Pos::Noun;
                t.form = Form::None;
            }
            // "the married couple": participle between determiner and noun is an adjective
            Pos::Verb if matches!(prev, Some(Pos::Det | Pos::Adj)) && matches!(t.form, Form::Past | Form::Part | Form::Ger)
                && matches!(next, Some(Pos::Noun | Pos::Propn)) =>
            {
                t.pos = Pos::Adj;
            }
            // "to" + verb base = infinitive marker
            Pos::Noun | Pos::Verb if prev_lower == "to" && (COMMON_VERBS.contains(&t.lower.as_str()) || IRREGULAR.iter().any(|(b, _, _)| *b == t.lower)) => {
                t.pos = Pos::Verb;
                t.form = Form::Base;
                t.lemma = t.lower.clone();
            }
            // after a modal/auxiliary a known verb base is a verb
            Pos::Noun if matches!(prev, Some(Pos::Aux | Pos::Part)) && (COMMON_VERBS.contains(&t.lower.as_str()) || IRREGULAR.iter().any(|(b, _, _)| *b == t.lower)) => {
                t.pos = Pos::Verb;
                t.form = Form::Base;
                t.lemma = t.lower.clone();
            }
            _ => {}
        }
    }
    for i in 0..n {
        let next_pos = tokens.get(i + 1).map(|t| t.pos);
        let t = &mut tokens[i];
        // "her": determiner before a noun phrase, else pronoun
        if t.lower == "her" {
            t.pos = if matches!(next_pos, Some(Pos::Noun | Pos::Adj | Pos::Num)) { Pos::Det } else { Pos::Pron };
        }
    }
    for i in 0..n {
        let next_pos = tokens.get(i + 1).map(|t| t.pos);
        let prev_pos = if i > 0 { Some(tokens[i - 1].pos) } else { None };
        let t = &mut tokens[i];
        if t.lower == "that" {
            // relative/complementizer before a clause, determiner before a noun, else pronoun
            t.pos = match next_pos {
                Some(Pos::Noun | Pos::Adj) => Pos::Det,
                Some(Pos::Pron | Pos::Propn | Pos::Det | Pos::Verb | Pos::Aux) => Pos::Sconj,
                _ => Pos::Pron,
            };
        }
        // "have/had/has" with a nominal complement is a main verb
        if t.pos == Pos::Aux && t.lemma == "have" && matches!(next_pos, Some(Pos::Det | Pos::Noun | Pos::Propn | Pos::Num | Pos::Adj)) {
            t.pos = Pos::Verb;
        }
        // temporal/causal words that open a clause are subordinators
        if t.pos == Pos::Adp && matches!(t.lower.as_str(), "before" | "after" | "since" | "until" | "till" | "as" | "once")
            && matches!(next_pos, Some(Pos::Pron | Pos::Propn | Pos::Det))
            && (prev_pos.is_none() || matches!(prev_pos, Some(Pos::Punct | Pos::Cconj)))
        {
            // could be a clause: decided by the clause splitter using the verb that follows
        }
        if t.initial && t.pos == Pos::Propn && t.ent.is_none() {
            // capitalized only because it starts the sentence
            let mut probe = t.clone();
            probe.initial = false;
            probe.text = probe.lower.clone();
            lexical(&mut probe);
            if probe.pos != Pos::Noun || COMMON_VERBS.contains(&t.lower.as_str()) {
                t.pos = probe.pos;
                t.form = probe.form;
                t.lemma = probe.lemma;
            }
        }
    }
    for t in tokens.iter_mut() {
        if t.lemma.is_empty() {
            t.lemma = match t.pos {
                Pos::Verb | Pos::Aux => verb_lemma(&t.lower),
                Pos::Noun if t.lower.ends_with("ies") => format!("{}y", t.lower.trim_end_matches("ies")),
                Pos::Noun if t.lower.ends_with('s') && !t.lower.ends_with("ss") && t.lower.len() > 3 => t.lower.trim_end_matches('s').to_string(),
                _ => t.lower.clone(),
            };
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tags(s: &str) -> Vec<(String, &'static str)> {
        let mut t = tokenize(s);
        tag(&mut t, &[]);
        t.into_iter().map(|t| (t.text.clone(), t.pos.tag())).collect()
    }

    #[test]
    fn tokenizes_and_tags() {
        let t = tags("Mr. Collins refused the offer of 1,200 pounds.");
        let got: Vec<&str> = t.iter().map(|x| x.1).collect();
        assert_eq!(t[0].0, "Mr.");
        assert_eq!(got, vec!["PROPN", "PROPN", "VERB", "DET", "NOUN", "ADP", "NUM", "NOUN", "PUNCT"]);
        let t = tags("Elizabeth's sister was not happy.");
        assert_eq!(t.iter().map(|x| x.1).collect::<Vec<_>>(), vec!["NOUN", "PART", "NOUN", "AUX", "PART", "ADJ", "PUNCT"]);
        let t = tags("She wanted to visit her aunt.");
        assert_eq!(t.iter().map(|x| x.1).collect::<Vec<_>>(), vec!["PRON", "VERB", "ADP", "VERB", "DET", "NOUN", "PUNCT"]);
    }
}
