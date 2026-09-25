//! Sentence segmentation and token scanning shared by extraction stages.

const ABBREV: &[&str] = &[
    "mr", "mrs", "ms", "dr", "st", "sr", "jr", "col", "capt", "gen", "lt", "rev", "prof", "vs", "etc", "no", "mt", "e.g", "i.e",
    "fig", "vol", "ch", "p", "pp", "ed", "cf", "inc", "ltd", "co",
];

/// Split a passage into sentences, keeping closing quotes with their sentence.
pub fn sentences(text: &str) -> Vec<String> {
    let chars: Vec<(usize, char)> = text.char_indices().collect();
    let mut out = Vec::new();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < chars.len() {
        let (bi, c) = chars[i];
        if matches!(c, '.' | '!' | '?' | '…') {
            // absorb runs of terminal punctuation and closing quotes/brackets
            let mut j = i + 1;
            while j < chars.len() && matches!(chars[j].1, '.' | '!' | '?' | '"' | '\'' | '\u{201D}' | '\u{2019}' | ')' | ']') {
                j += 1;
            }
            let end = if j < chars.len() { chars[j].0 } else { text.len() };
            let next_starts_upper = chars[j..]
                .iter()
                .find(|(_, ch)| !ch.is_whitespace())
                .map(|(_, ch)| ch.is_uppercase() || matches!(ch, '"' | '\u{201C}' | '\u{2018}' | '\''))
                .unwrap_or(true);
            let at_space = j >= chars.len() || chars[j].1.is_whitespace();
            let word_before: String = text[start..bi]
                .rsplit(|ch: char| ch.is_whitespace() || ch == '(' || ch == '"' || ch == '\u{201C}')
                .next()
                .unwrap_or("")
                .to_lowercase();
            let is_abbrev = c == '.'
                && (ABBREV.contains(&word_before.as_str())
                    || (word_before.len() == 1 && word_before.chars().all(|x| x.is_alphabetic())));
            if at_space && next_starts_upper && !is_abbrev {
                let s = text[start..end].trim();
                if !s.is_empty() {
                    out.push(s.to_string());
                }
                start = end;
            }
            i = j;
            continue;
        }
        i += 1;
    }
    let rest = text[start..].trim();
    if !rest.is_empty() {
        out.push(rest.to_string());
    }
    out
}

/// A word token with its original surface and byte span.
#[derive(Clone, Debug)]
pub struct Tok<'a> {
    pub text: &'a str,
    pub start: usize,
    pub end: usize,
}

pub fn tokens(s: &str) -> Vec<Tok<'_>> {
    let mut out = Vec::new();
    let mut start: Option<usize> = None;
    for (i, c) in s.char_indices() {
        let wordish = c.is_alphanumeric() || c == '\'' || c == '\u{2019}' || c == '-' || c == '.';
        match (wordish, start) {
            (true, None) => start = Some(i),
            (false, Some(st)) => {
                push_tok(s, st, i, &mut out);
                start = None;
            }
            _ => {}
        }
    }
    if let Some(st) = start {
        push_tok(s, st, s.len(), &mut out);
    }
    out
}

fn push_tok<'a>(s: &'a str, st: usize, en: usize, out: &mut Vec<Tok<'a>>) {
    let raw = &s[st..en];
    // keep "Mr." style abbreviations, drop sentence-final dots and quote marks
    let keep_dot = raw.ends_with('.') && ABBREV.contains(&raw.trim_end_matches('.').to_lowercase().as_str());
    let mut t = raw.trim_start_matches(['\'', '\u{2019}', '-', '.']);
    if !keep_dot {
        t = t.trim_end_matches(['.', '-']);
    }
    t = t.trim_end_matches(['\'', '\u{2019}']);
    if t.is_empty() {
        return;
    }
    let offset = raw.find(t).unwrap_or(0);
    out.push(Tok { text: t, start: st + offset, end: st + offset + t.len() });
}

/// Strip a possessive suffix: "Darcy's" -> "Darcy".
pub fn base_form(t: &str) -> &str {
    for suf in ["'s", "\u{2019}s", "s'", "s\u{2019}"] {
        if let Some(b) = t.strip_suffix(suf) {
            if suf.starts_with('s') {
                return &t[..t.len() - suf.len() + 1];
            }
            return b;
        }
    }
    t
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn splits_sentences_respecting_titles() {
        let s = sentences(
            "Mr. Bennet was among the earliest. He had always intended to visit him! “Is he married?” asked Mrs. Bennet. Yes.",
        );
        assert_eq!(s.len(), 4, "{s:?}");
        assert_eq!(s[0], "Mr. Bennet was among the earliest.");
        assert!(s[2].starts_with('“') && s[2].ends_with("Mrs. Bennet."));
    }
    #[test]
    fn tokens_keep_titles() {
        let t: Vec<&str> = tokens("“Mr. Darcy’s house,” said she.").iter().map(|t| t.text).collect();
        assert_eq!(t, vec!["Mr.", "Darcy’s", "house", "said", "she"]);
        assert_eq!(base_form("Darcy’s"), "Darcy");
    }
}
