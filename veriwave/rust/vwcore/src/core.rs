//! vw/core.py
pub const M32: u64 = 4_294_967_296;

/// FNV-1a, 32 bits, over the UTF-8 bytes.
pub fn fnv1a32(text: &str) -> u64 {
    let mut h: u64 = 2_166_136_261;
    for b in text.as_bytes() {
        h = ((h ^ (*b as u64)) * 16_777_619) % M32;
    }
    h
}

/// One step of xorshift32.
pub fn xorshift32(state: u64) -> u64 {
    let mut x = state ^ ((state << 13) % M32);
    x ^= x >> 17;
    (x ^ ((x << 5) % M32)) % M32
}

pub fn seed_of(text: &str) -> u64 {
    let h = fnv1a32(text);
    if h == 0 { 2_463_534_242 } else { h }
}

pub struct Rng { pub state: u64 }

impl Rng {
    pub fn new(seed: u64) -> Rng {
        let s = seed % M32;
        Rng { state: if s == 0 { 2_463_534_242 } else { s } }
    }
    pub fn next(&mut self) -> u64 { self.state = xorshift32(self.state); self.state }
    pub fn below(&mut self, n: u64) -> u64 { self.next() % n }
    pub fn between(&mut self, lo: i64, hi: i64) -> i64 { lo + self.below((hi - lo + 1) as u64) as i64 }
}

fn is_ascii_alnum(c: char) -> bool { c.is_ascii_alphanumeric() }

pub fn lower(text: &str) -> String { text.chars().map(|c| c.to_ascii_lowercase()).collect() }

pub fn slug(text: &str) -> String {
    let mut out = String::new();
    let mut pending = false;
    for c in text.chars() {
        if is_ascii_alnum(c) {
            if pending && !out.is_empty() { out.push('-'); }
            out.push(c.to_ascii_lowercase());
            pending = false;
        } else {
            pending = true;
        }
    }
    out
}

pub fn clamp(lo: i64, hi: i64, x: i64) -> i64 { if x < lo { lo } else if hi < x { hi } else { x } }

pub fn words(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    for c in text.chars() {
        if is_ascii_alnum(c) || c == '\'' {
            cur.push(c.to_ascii_lowercase());
        } else if !cur.is_empty() {
            out.push(std::mem::take(&mut cur));
        }
    }
    if !cur.is_empty() { out.push(cur); }
    out
}

pub fn has_phrase(ws: &[String], phrase: &[String]) -> bool {
    if phrase.is_empty() { return true; }
    if ws.len() < phrase.len() { return false; }
    (0..=ws.len() - phrase.len()).any(|i| ws[i..i + phrase.len()] == *phrase)
}

pub fn has_any(ws: &[String], phrases: &[&str]) -> bool {
    phrases.iter().any(|p| has_phrase(ws, &words(p)))
}
