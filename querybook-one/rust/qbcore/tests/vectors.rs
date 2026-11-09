//! The Rust port must reproduce the Python suite: exactly for qbmath, to 1e-12 relative for the formulas
//! (the Python evaluator works in exact fractions; f64 differs only in the last bits).

use qbcore::{formulas, qbmath};

fn rows(text: &str) -> impl Iterator<Item = Vec<&str>> {
    text.lines().filter(|l| !l.is_empty() && !l.starts_with('#')).map(|l| l.split('\t').collect())
}

#[test]
fn qbmath_matches_python_exactly() {
    let mut n = 0;
    for r in rows(include_str!("../vectors/qbmath.tsv")) {
        let a: Vec<&str> = r[1].split(',').collect();
        let f = |i: usize| a[i].parse::<f64>().unwrap();
        let u = |i: usize| a[i].parse::<u32>().unwrap();
        let got: f64 = match r[0] {
            "syn_potentiate" => qbmath::syn_potentiate(f(0)),
            "syn_depress" => qbmath::syn_depress(f(0)),
            "dsn_hit" => qbmath::dsn_hit(f(0)),
            "dsn_miss" => qbmath::dsn_miss(f(0)),
            "dsn_recover" => qbmath::dsn_recover(f(0)),
            "syn_fade" => qbmath::syn_fade(f(0), f(1), a[2] == "1"),
            "syn_threshold" => qbmath::syn_threshold(u(0), u(1)),
            "syn_consolidated" => qbmath::syn_consolidated(u(0), u(1)) as u32 as f64,
            other => panic!("unknown function {other}"),
        };
        let want: f64 = r[2].parse().unwrap();
        assert_eq!(got.to_bits(), want.to_bits(), "{}({}) = {} but Python gives {}", r[0], r[1], got, want);
        n += 1;
    }
    assert!(n > 300, "only {n} vectors");
}

#[test]
fn formulas_match_python() {
    let mut n = 0;
    for r in rows(include_str!("../vectors/formulas.tsv")) {
        let args: Vec<f64> = r[1].split(',').map(|x| x.parse().unwrap()).collect();
        let want: f64 = r[2].parse().unwrap();
        let got = formulas::call(r[0], &args).unwrap_or_else(|| panic!("no function {}", r[0]));
        let rel = ((got - want) / want).abs();
        assert!(rel < 1e-12, "{}({:?}) = {} but Python gives {} (relative difference {})", r[0], args, got, want, rel);
        n += 1;
    }
    assert!(n >= 100, "only {n} formula vectors");
}
