//! Small shared helpers: hashing, canonical text, tokenizing, time.

use sha2::{Digest, Sha256};
use std::time::{SystemTime, UNIX_EPOCH};
use unicode_normalization::UnicodeNormalization;

pub fn sha256(bytes: &[u8]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(bytes);
    h.finalize().into()
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(sha256(bytes))
}

pub fn now_secs() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

pub fn random_bytes<const N: usize>() -> [u8; N] {
    let mut b = [0u8; N];
    getrandom::fill(&mut b).expect("system randomness unavailable");
    b
}

/// NFC, lowercase, collapse whitespace, strip surrounding punctuation.
/// The canonical form every fingerprint is computed over.
pub fn canon_text(s: &str) -> String {
    let nfc: String = s.nfc().collect();
    let mut out = String::with_capacity(nfc.len());
    let mut space = false;
    for ch in nfc.chars() {
        let c = match ch {
            '\u{2018}' | '\u{2019}' => '\'',
            '\u{201C}' | '\u{201D}' => '"',
            '\u{2013}' | '\u{2014}' => '-',
            c => c,
        };
        if c.is_whitespace() {
            space = true;
            continue;
        }
        if space && !out.is_empty() {
            out.push(' ');
        }
        space = false;
        for l in c.to_lowercase() {
            out.push(l);
        }
    }
    out.trim_matches(|c: char| c.is_ascii_punctuation() && c != '\'' && c != '"').to_string()
}

/// Key under which a name is matched: canonical text without periods, so
/// "Mr. Darcy" and "mr darcy" meet.
pub fn alias_key(s: &str) -> String {
    canon_text(s).replace('.', "").split_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn slug(s: &str) -> String {
    let mut out = String::new();
    let mut dash = false;
    for c in canon_text(s).chars() {
        if c.is_alphanumeric() {
            out.push(c);
            dash = false;
        } else if !dash && !out.is_empty() {
            out.push('-');
            dash = true;
        }
    }
    out.trim_end_matches('-').to_string()
}

/// Word tokens (lowercased, apostrophes kept inside words).
pub fn words(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    for ch in s.chars() {
        let c = if ch == '\u{2019}' { '\'' } else { ch };
        if c.is_alphanumeric() || (c == '\'' && !cur.is_empty()) {
            for l in c.to_lowercase() {
                cur.push(l);
            }
        } else if !cur.is_empty() {
            out.push(std::mem::take(&mut cur).trim_end_matches('\'').to_string());
        }
    }
    if !cur.is_empty() {
        out.push(cur.trim_end_matches('\'').to_string());
    }
    out
}

pub const STOPWORDS: &[&str] = &[
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "just",
    "me",
    "more",
    "most",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "now",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
    "tell",
    "say",
    "says",
    "said",
    "book",
    "happen",
    "happens",
    "happened",
    "does",
    "much",
    "many",
    "whose",
    "also",
    "ever",
    "really",
    "anything",
    "something",
    "explain",
    "describe",
    "please",
    "know",
    "chapter",
    "story",
];

pub fn is_stopword(w: &str) -> bool {
    STOPWORDS.contains(&w)
}

pub fn content_words(s: &str) -> Vec<String> {
    words(s).into_iter().filter(|w| !is_stopword(w) && w.len() > 1).collect()
}

pub fn html_escape(s: &str) -> String {
    let mut o = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => o.push_str("&amp;"),
            '<' => o.push_str("&lt;"),
            '>' => o.push_str("&gt;"),
            '"' => o.push_str("&quot;"),
            _ => o.push(c),
        }
    }
    o
}

/// Truncate at a word boundary to at most `max` chars.
pub fn clip(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_string();
    }
    let cut: String = s.chars().take(max).collect();
    match cut.rfind(' ') {
        Some(i) if i > max / 2 => format!("{}…", &cut[..i]),
        _ => format!("{cut}…"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn canon_is_stable() {
        assert_eq!(canon_text("  Mr.\u{00A0}Darcy’s  HOUSE. "), "mr. darcy's house");
        assert_eq!(slug("Lady Catherine de Bourgh"), "lady-catherine-de-bourgh");
        assert_eq!(words("Darcy’s pride, isn't it?"), vec!["darcy's", "pride", "isn't", "it"]);
    }
}
