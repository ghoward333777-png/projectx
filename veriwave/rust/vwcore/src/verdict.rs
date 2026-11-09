//! vw/verdict.py: trust, the verdict rule and exact arithmetic (i128, every value bounded by 2^62 as in Python and Lean).
use crate::core::lower;

pub const MIN_TRUST: i64 = 50;
const BOUND: i128 = 1 << 62;

pub fn status_trust(status: &str) -> i64 {
    match lower(status.trim()).as_str() {
        "proved" => 99, "verified" | "confirmed" => 95, "accepted" => 85, "sourced" => 80, "active" => 75,
        "harvested" | "imported" => 70, "unverified" => 60, "pending" => 55, "stale" => 45, "disputed" | "contested" => 40,
        "retracted" | "rejected" => 5, "deleted" => 0, _ => 65,
    }
}

pub fn strip_qids(text: &str) -> String {
    let cs: Vec<char> = text.chars().collect();
    let mut out = String::new();
    let (mut i, n) = (0usize, cs.len());
    while i < n {
        if i + 3 <= n && cs[i] == ' ' && cs[i + 1] == '(' && cs[i + 2] == 'Q' {
            let mut j = i + 3;
            while j < n && cs[j].is_ascii_digit() { j += 1; }
            if j > i + 3 && j < n && cs[j] == ')' { i = j + 1; continue; }
        }
        out.push(cs[i]);
        i += 1;
    }
    out.trim().to_string()
}

pub fn norm(text: &str) -> String { lower(strip_qids(text).trim()) }

const MULTI_VALUED: &[&str] = &["instance of", "subclass of", "occupation", "award", "child", "sibling", "spouse", "member", "genre",
    "language", "field", "part of", "has part", "notable work", "educated", "employer", "position", "nominated", "citizenship",
    "alias", "also known", "category", "translation", "named after", "influenced", "described by", "different from", "contains",
    "shares border", "religion", "ethnic", "participant", "cast member", "product", "industry", "topic", "subject", "use"];

pub fn multi_valued(predicate: &str) -> bool {
    let p = lower(predicate);
    MULTI_VALUED.iter().any(|m| p.contains(m))
}

pub struct Fact { pub subject: String, pub predicate: String, pub object: String }

pub fn clash(a: &Fact, b: &Fact) -> bool {
    !multi_valued(&a.predicate) && !a.object.is_empty() && !b.object.is_empty() && norm(&a.subject) == norm(&b.subject)
        && lower(&a.predicate) == lower(&b.predicate) && norm(&a.object) != norm(&b.object)
}

pub fn verdict(facts: &[Fact]) -> &'static str {
    if facts.is_empty() { return "UNKNOWN"; }
    if facts.iter().any(|a| facts.iter().any(|b| clash(a, b))) { "CONTRADICTED" } else { "VERIFIED" }
}

// ------------------------------------------------------------------ exact arithmetic
pub type Q = (i128, i128);

fn gcd(mut a: i128, mut b: i128) -> i128 { while b != 0 { let t = a % b; a = b; b = t; } a }

pub fn q_norm(n: i128, d: i128) -> Q {
    let g = gcd(n.abs(), d);
    if g == 0 { (0, 1) } else { (n / g, d / g) }
}

fn in_bound(q: Q) -> bool { q.0.abs() < BOUND && q.1 < BOUND }

fn q_raw(op: char, a: Q, b: Q) -> Option<Q> {
    let (an, ad) = a;
    let (bn, bd) = b;
    match op {
        '+' => Some(q_norm(an.checked_mul(bd)?.checked_add(bn.checked_mul(ad)?)?, ad.checked_mul(bd)?)),
        '-' => Some(q_norm(an.checked_mul(bd)?.checked_sub(bn.checked_mul(ad)?)?, ad.checked_mul(bd)?)),
        '*' => Some(q_norm(an.checked_mul(bn)?, ad.checked_mul(bd)?)),
        '/' => {
            if bn == 0 { return None; }
            let s = if bn < 0 { -1 } else { 1 };
            Some(q_norm(an.checked_mul(bd)?.checked_mul(s)?, ad.checked_mul(bn.abs())?))
        }
        '^' => {
            if bd != 1 || bn.abs() > 64 { return None; }
            let (mut pn, mut pd): Q = (1, 1);
            for _ in 0..bn.abs() {
                let r = q_norm(pn.checked_mul(an)?, pd.checked_mul(ad)?);
                pn = r.0; pd = r.1;
            }
            if bn >= 0 { return Some((pn, pd)); }
            if an == 0 { return None; }
            Some(q_norm(pd * if pn < 0 { -1 } else { 1 }, pn.abs()))
        }
        _ => None,
    }
}

pub fn q_apply(op: char, a: Q, b: Q) -> Option<Q> { q_raw(op, a, b).filter(|q| in_bound(*q)) }

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Tok { Num(Q), Op(char) }

pub fn tokenize(text: &str) -> Option<Vec<Tok>> {
    let mut toks = Vec::new();
    let mut num: Option<i128> = None;
    let mut sc: u32 = 0;
    let mut dot = false;
    let flush = |num: Option<i128>, sc: u32, toks: &mut Vec<Tok>| -> Option<()> {
        if let Some(n) = num { toks.push(Tok::Num(q_norm(n, 10i128.checked_pow(sc)?))); }
        Some(())
    };
    for c in text.chars() {
        if c.is_ascii_digit() {
            num = Some(num.unwrap_or(0).checked_mul(10)?.checked_add(c as i128 - 48)?);
            if dot { sc += 1; }
            continue;
        }
        if c == '.' {
            if dot { return None; }
            num = Some(num.unwrap_or(0));
            dot = true;
            continue;
        }
        flush(num, sc, &mut toks)?;
        num = None; sc = 0; dot = false;
        if c == ' ' { continue; }
        if "+-*/^()".contains(c) { toks.push(Tok::Op(c)); continue; }
        return None;
    }
    flush(num, sc, &mut toks)?;
    if toks.iter().any(|t| matches!(t, Tok::Num(q) if !in_bound(*q))) { return None; }
    Some(toks)
}

fn prec(op: char) -> u8 { match op { '+' | '-' => 1, '*' | '/' => 2, '~' => 3, '^' => 4, _ => 0 } }

pub fn to_rpn(toks: &[Tok]) -> Option<Vec<Tok>> {
    let mut out = Vec::new();
    let mut st: Vec<char> = Vec::new();
    let mut expect = true;
    for t in toks {
        match *t {
            Tok::Num(_) => { if !expect { return None; } out.push(*t); expect = false; }
            Tok::Op('(') => { if !expect { return None; } st.push('('); }
            Tok::Op(')') => {
                if expect { return None; }
                while let Some(&top) = st.last() { if top == '(' { break; } out.push(Tok::Op(st.pop()?)); }
                st.pop()?;
            }
            Tok::Op(k) if expect => { if k == '-' { st.push('~'); } else if k != '+' { return None; } }
            Tok::Op(k) => {
                while let Some(&top) = st.last() {
                    if top != '(' && (prec(top) > prec(k) || (prec(top) == prec(k) && k != '^')) { out.push(Tok::Op(st.pop()?)); } else { break; }
                }
                st.push(k);
                expect = true;
            }
        }
    }
    if expect { return None; }
    while let Some(top) = st.pop() { if top == '(' { return None; } out.push(Tok::Op(top)); }
    Some(out)
}

pub fn eval_rpn(rpn: &[Tok]) -> Option<Q> {
    let mut st: Vec<Q> = Vec::new();
    for t in rpn {
        match *t {
            Tok::Num(q) => st.push(q),
            Tok::Op('~') => { let a = st.pop()?; st.push((-a.0, a.1)); }
            Tok::Op(c) => { let b = st.pop()?; let a = st.pop()?; st.push(q_apply(c, a, b)?); }
        }
    }
    if st.len() == 1 { st.pop() } else { None }
}

pub fn prepare(text: &str) -> String {
    let mut t = lower(text.trim());
    for lead in ["what is ", "what's ", "calculate ", "compute ", "evaluate ", "how much is "] {
        if t.starts_with(lead) { t = t[lead.len()..].to_string(); break; }
    }
    let t = t.trim_end_matches(|c: char| c == '?' || c == '=' || c == '.' || c == ' ');
    t.replace('×', "*").replace('÷', "/").replace("% of ", "/100*").replace('%', "/100").replace(',', "")
}

pub fn decimal_digits(n: i128, d: i128, places: u32) -> String {
    let a = n.abs();
    let whole = a / d;
    let frac = (a % d) * 10i128.pow(places) / d;
    let sign = if n < 0 { "-" } else { "" };
    if places == 0 { format!("{sign}{whole}") } else { format!("{sign}{whole}.{:0>width$}", frac, width = places as usize) }
}

pub fn terminating_places(d: i128) -> i64 {
    let (mut r, mut a, mut b) = (d, 0i64, 0i64);
    for _ in 0..64 {
        if r % 2 == 0 && r > 0 { r /= 2; a += 1; } else if r % 5 == 0 && r > 0 { r /= 5; b += 1; } else { break; }
    }
    if r == 1 { a.max(b) } else { -1 }
}

pub fn fmt_q(q: Q) -> String {
    let (n, d) = q;
    if d == 1 { return n.to_string(); }
    let p = terminating_places(d);
    if (0..=12).contains(&p) { return decimal_digits(n, d, p as u32); }
    format!("{n}/{d} ≈ {}", decimal_digits(n, d, 10))
}

pub fn calculate(text: &str) -> Option<String> {
    let toks = tokenize(&prepare(text))?;
    if toks.is_empty() { return None; }
    Some(fmt_q(eval_rpn(&to_rpn(&toks)?)?))
}
