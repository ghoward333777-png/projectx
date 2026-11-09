//! The Rust port must equal the Python engine on every golden vector (contracts/vectors.tsv, from tools/gen_vectors.py).
use vwcore::{core, router, verdict};

fn unesc(s: &str) -> String {
    let mut out = String::new();
    let mut it = s.chars();
    while let Some(c) = it.next() {
        if c == '\\' {
            match it.next() { Some('t') => out.push('\t'), Some('n') => out.push('\n'), Some(o) => out.push(o), None => {} }
        } else { out.push(c); }
    }
    out
}

#[test]
fn equals_python_on_every_vector() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../contracts/vectors.tsv");
    let text = std::fs::read_to_string(path).expect("contracts/vectors.tsv");
    let mut bad = Vec::new();
    let mut n = 0;
    for line in text.lines() {
        let cols: Vec<&str> = line.split('\t').collect();
        assert_eq!(cols.len(), 3, "bad line {line:?}");
        let (f, inp, exp) = (cols[0], unesc(cols[1]), unesc(cols[2]));
        let got = match f {
            "fnv1a32" => core::fnv1a32(&inp).to_string(),
            "slug" => core::slug(&inp),
            "words" => core::words(&inp).join("|"),
            "xorshift32" => core::xorshift32(inp.parse().unwrap()).to_string(),
            "strip_qids" => verdict::strip_qids(&inp),
            "route" => router::route(&inp).to_string(),
            "screen_for" => router::screen_for(&inp).to_string(),
            "calculate" => verdict::calculate(&inp).unwrap_or_else(|| "∅".to_string()),
            "status_trust" => verdict::status_trust(&inp).to_string(),
            "multi_valued" => verdict::multi_valued(&inp).to_string(),
            "verdict" => {
                let facts: Vec<verdict::Fact> = if inp.is_empty() { vec![] } else {
                    inp.split('|').map(|x| { let p: Vec<&str> = x.split(';').collect();
                        verdict::Fact { subject: p[0].into(), predicate: p[1].into(), object: p[2].into() } }).collect()
                };
                verdict::verdict(&facts).to_string()
            }
            other => panic!("unknown function {other}"),
        };
        n += 1;
        if got != exp { bad.push(format!("{f}({inp:?}) = {got:?}, Python says {exp:?}")); }
    }
    assert!(n > 100, "only {n} vectors");
    assert!(bad.is_empty(), "{} mismatches:\n{}", bad.len(), bad.join("\n"));
}
