//! Integration test: qb-core reproduces the Python oracle's fingerprints/fuids
//! byte-for-byte on the exported vector set (AC-R1/R2). Part of `cargo test`.
//! Regenerate vectors with `python rust/parity/gen_vectors.py` after changing them.

use std::fs;

fn unhex(s: &str) -> String {
    let bytes: Vec<u8> = (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect();
    String::from_utf8(bytes).unwrap()
}

#[test]
fn parity_against_python_oracle() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../parity/vectors.tsv");
    let text = fs::read_to_string(path)
        .expect("vectors.tsv missing — run `python rust/parity/gen_vectors.py`");
    let mut total = 0;
    for line in text.lines() {
        let line = line.trim_end_matches('\r');
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let f: Vec<&str> = line.split('\t').collect();
        assert_eq!(f.len(), 8, "bad vector line: {}", line);
        let (s, p, o, pol, sid, ing) =
            (unhex(f[0]), unhex(f[1]), unhex(f[2]), unhex(f[3]), unhex(f[4]), unhex(f[5]));
        assert_eq!(qb_core::fingerprint(&s, &p, &o, &pol), f[6], "fingerprint mismatch: {:?}", (&s, &p, &o, &pol));
        assert_eq!(qb_core::fuid(&s, &p, &o, &pol, &sid, &ing), f[7], "fuid mismatch: {:?}", (&s, &p, &o, &pol, &sid, &ing));
        total += 1;
    }
    assert!(total > 0, "no vectors found");
    eprintln!("parity: {} vectors byte-identical to the Python oracle", total);
}
