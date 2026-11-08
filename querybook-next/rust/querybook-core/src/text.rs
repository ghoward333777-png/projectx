//! Port of `querybook/core/text.py` (normalize_ws, tokenize, fnv1a64,
//! content_hash, classify). NFC normalisation is the one step not yet ported
//! (needs the `unicode-normalization` crate); golden inputs are NFC already.

pub const DOMAINS: [&str; 4] = ["language", "stem", "history", "video"];

const INVISIBLE: [char; 6] = ['\u{200b}', '\u{200c}', '\u{200d}', '\u{2060}', '\u{feff}', '\u{00ad}'];

/// Shared verbatim with Python: one lexicon file, two engines.
const LEXICON_SOURCE: &str = include_str!("../../../querybook/core/lexicons.txt");

pub fn normalize_ws(text: &str) -> String {
    let cleaned: String = text.chars().filter(|c| !INVISIBLE.contains(c)).collect();
    cleaned.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn tokenize(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    for ch in text.to_lowercase().chars() {
        if ch.is_alphanumeric() {
            cur.push(ch);
        } else if !cur.is_empty() {
            out.push(std::mem::take(&mut cur));
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

pub fn fnv1a64(data: &[u8]) -> String {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in data {
        h ^= *b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{:016x}", h)
}

pub fn content_hash(text: &str) -> String {
    fnv1a64(normalize_ws(text).to_lowercase().as_bytes())
}

pub struct Lexicons {
    words: [Vec<String>; 4],
}

impl Lexicons {
    pub fn parse(source: &str) -> Self {
        let mut words: [Vec<String>; 4] = Default::default();
        for line in source.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if let Some((name, list)) = line.split_once(':') {
                if let Some(i) = DOMAINS.iter().position(|d| *d == name.trim()) {
                    words[i] = list.split_whitespace().map(str::to_string).collect();
                }
            }
        }
        Lexicons { words }
    }

    pub fn builtin() -> Self {
        Self::parse(LEXICON_SOURCE)
    }

    fn contains(&self, domain: usize, word: &str) -> bool {
        self.words[domain].iter().any(|w| w == word)
    }
}

/// Same rule as Python: lexicon hits per domain, 4-digit years 1000..=2100
/// add one to history, ties go to the earlier domain, all-zero -> language.
pub fn classify(text: &str, lex: &Lexicons) -> (&'static str, [u32; 4]) {
    let mut scores = [0u32; 4];
    for tok in tokenize(text) {
        for (i, score) in scores.iter_mut().enumerate() {
            if lex.contains(i, &tok) {
                *score += 1;
            }
        }
        if tok.len() == 4 && tok.chars().all(|c| c.is_ascii_digit()) {
            let year: u32 = tok.parse().unwrap_or(0);
            if (1000..=2100).contains(&year) {
                scores[2] += 1;
            }
        }
    }
    let mut best = 0;
    for i in 1..4 {
        if scores[i] > scores[best] {
            best = i;
        }
    }
    (DOMAINS[best], scores)
}

/// Decode the golden-file escapes: \t \n \r \\ \uXXXX.
pub fn unescape(s: &str) -> String {
    let chars: Vec<char> = s.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '\\' && i + 1 < chars.len() {
            match chars[i + 1] {
                'u' if i + 5 < chars.len() => {
                    let hex: String = chars[i + 2..i + 6].iter().collect();
                    if let Some(c) = u32::from_str_radix(&hex, 16).ok().and_then(char::from_u32) {
                        out.push(c);
                    }
                    i += 6;
                    continue;
                }
                't' => out.push('\t'),
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                '\\' => out.push('\\'),
                other => {
                    out.push('\\');
                    out.push(other);
                }
            }
            i += 2;
            continue;
        }
        out.push(chars[i]);
        i += 1;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    const GOLDEN: &str = include_str!("../../../contracts/golden_text.tsv");

    #[test]
    fn matches_python_golden_vectors() {
        let lex = Lexicons::builtin();
        let mut checked = 0;
        for line in GOLDEN.lines() {
            if line.starts_with('#') || line.is_empty() {
                continue;
            }
            let cols: Vec<&str> = line.split('\t').collect();
            assert_eq!(cols.len(), 5, "bad golden row: {line:?}");
            let input = unescape(cols[0]);
            assert_eq!(normalize_ws(&input), cols[1], "normalize {:?}", cols[0]);
            assert_eq!(content_hash(&input), cols[2], "hash {:?}", cols[0]);
            let (domain, scores) = classify(&input, &lex);
            assert_eq!(domain, cols[3], "classify {:?}", cols[0]);
            let joined = scores.iter().map(|s| s.to_string()).collect::<Vec<_>>().join(",");
            assert_eq!(joined, cols[4], "scores {:?}", cols[0]);
            checked += 1;
        }
        assert!(checked >= 10);
    }

    #[test]
    fn tokenize_splits_on_non_alphanumerics() {
        assert_eq!(tokenize("F = m*a, Newton's 2nd!"), vec!["f", "m", "a", "newton", "s", "2nd"]);
    }
}
