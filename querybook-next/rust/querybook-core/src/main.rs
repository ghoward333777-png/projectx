//! `querybook-core kernel` — reads one text per stdin line and prints
//! `normalized<TAB>hash<TAB>domain<TAB>scores`, for parity checks from Python.
//! `querybook-core lex` — prints the FQL token stream of each stdin line.

use std::io::{self, BufRead, Write};

use querybook_core::{fql_lexer, legacy, text};

fn main() {
    let cmd = std::env::args().nth(1).unwrap_or_else(|| "kernel".into());
    let lex = text::Lexicons::builtin();
    let stdin = io::stdin();
    let mut out = io::BufWriter::new(io::stdout());
    for line in stdin.lock().lines() {
        let line = line.expect("stdin");
        match cmd.as_str() {
            "kernel" => {
                let input = text::unescape(&line);
                let (domain, scores) = text::classify(&input, &lex);
                let joined = scores.iter().map(|s| s.to_string()).collect::<Vec<_>>().join(",");
                writeln!(out, "{}\t{}\t{}\t{}", text::normalize_ws(&input), text::content_hash(&input), domain, joined).unwrap();
            }
            "fingerprint" => {
                let parts: Vec<String> = line.split('\t').map(text::unescape).collect();
                let refs: Vec<&str> = parts.iter().map(String::as_str).collect();
                writeln!(out, "{}", legacy::fingerprint(&refs)).unwrap();
            }
            "lex" => match fql_lexer::tokenize(&line) {
                Ok(toks) => writeln!(out, "{:?}", toks.iter().map(|t| (&t.tok, t.pos)).collect::<Vec<_>>()).unwrap(),
                Err(e) => writeln!(out, "error {} at {}: {}", e.code, e.pos, e.message).unwrap(),
            },
            other => {
                eprintln!("unknown command {other}; use kernel | fingerprint | lex");
                std::process::exit(2);
            }
        }
    }
}
