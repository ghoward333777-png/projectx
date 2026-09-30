//! qb-core parity harness (Gate 5).
//!
//! Reads a vector set exported from the Python prototype (`ufcs_store`) and proves
//! the Rust `qb_core::fingerprint` / `fuid` reproduce it byte-for-byte (AC-R1/R2).
//!
//! Vector file (TSV, one vector per line), all input fields hex-encoded UTF-8 to
//! avoid any delimiter/escaping ambiguity:
//!   hex(subject)\thex(predicate)\thex(object)\thex(polarity)\thex(source_id)\thex(ingested)\tfingerprint\tfuid
//!
//! Usage: parity <vectors.tsv>   (exit 0 iff every vector matches)

use std::env;
use std::fs;
use std::process::exit;

fn unhex(s: &str) -> String {
    let bytes: Vec<u8> = (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("bad hex"))
        .collect();
    String::from_utf8(bytes).expect("bad utf8")
}

fn main() {
    let path = env::args().nth(1).unwrap_or_else(|| {
        eprintln!("usage: parity <vectors.tsv>");
        exit(2);
    });
    let text = fs::read_to_string(&path).unwrap_or_else(|e| {
        eprintln!("cannot read {}: {}", path, e);
        exit(2);
    });

    let mut total = 0usize;
    let mut fp_ok = 0usize;
    let mut fu_ok = 0usize;
    let mut failures: Vec<String> = Vec::new();

    for (lineno, line) in text.lines().enumerate() {
        let line = line.trim_end_matches('\r');
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let f: Vec<&str> = line.split('\t').collect();
        if f.len() != 8 {
            failures.push(format!("line {}: expected 8 fields, got {}", lineno + 1, f.len()));
            continue;
        }
        let (subject, predicate, obj, polarity, source_id, ingested) =
            (unhex(f[0]), unhex(f[1]), unhex(f[2]), unhex(f[3]), unhex(f[4]), unhex(f[5]));
        let exp_fp = f[6];
        let exp_fu = f[7];

        total += 1;
        let got_fp = qb_core::fingerprint(&subject, &predicate, &obj, &polarity);
        let got_fu = qb_core::fuid(&subject, &predicate, &obj, &polarity, &source_id, &ingested);

        if got_fp == exp_fp {
            fp_ok += 1;
        } else {
            failures.push(format!(
                "line {}: fingerprint mismatch for ({:?},{:?},{:?},{:?})\n    py:  {}\n    rs:  {}",
                lineno + 1, subject, predicate, obj, polarity, exp_fp, got_fp
            ));
        }
        if got_fu == exp_fu {
            fu_ok += 1;
        } else {
            failures.push(format!(
                "line {}: fuid mismatch for ({:?},{:?},{:?},{:?},{:?},{:?})\n    py:  {}\n    rs:  {}",
                lineno + 1, subject, predicate, obj, polarity, source_id, ingested, exp_fu, got_fu
            ));
        }
    }

    println!("======================================================================");
    println!("qb-core parity vs Python oracle (ufcs_store)");
    println!("vectors: {}   fingerprint {}/{}   fuid {}/{}", total, fp_ok, total, fu_ok, total);
    for msg in &failures {
        println!("  FAIL {}", msg);
    }
    let ok = failures.is_empty() && total > 0;
    println!("PARITY RESULT: {}", if ok { "GREEN ✓ (byte-identical)" } else { "RED ✗" });
    println!("======================================================================");
    exit(if ok { 0 } else { 1 });
}
