//! qb-core — the parity heart of the QueryBook Rust production engine.
//!
//! Dependency-free by policy: it carries its own SHA-256 so the content-address
//! (the Fact Unit fingerprint) has no external surface. Every function here is a
//! pure function of its inputs — no clock, no RNG — which is Covenant C3
//! (determinism) by construction.
//!
//! The identity contract must match the Python prototype `ufcs_store` byte-for-byte:
//!   _norm(s)          = " ".join(str(s).strip().lower().split())
//!   fingerprint(...)  = sha256_hex( norm(s)|norm(p)|norm(o)|polarity )
//!   fuid(...)         = sha256_hex( json|source_id|ingested )
//! where `json` is Python `json.dumps({"o","p","pol","s"}, sort_keys=True,
//! ensure_ascii=True)`. qb-parity proves the match against exported vectors.

// ---------------------------------------------------------------------------
// SHA-256 (FIPS 180-4), self-contained.
// ---------------------------------------------------------------------------
const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

/// SHA-256 of `data`, returned as lowercase 64-char hex.
pub fn sha256_hex(data: &[u8]) -> String {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    // pre-processing: append 0x80, pad to 56 mod 64, append 64-bit big-endian bit length
    let bitlen = (data.len() as u64).wrapping_mul(8);
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&bitlen.to_be_bytes());

    let mut w = [0u32; 64];
    for chunk in msg.chunks_exact(64) {
        for i in 0..16 {
            w[i] = u32::from_be_bytes([chunk[i * 4], chunk[i * 4 + 1], chunk[i * 4 + 2], chunk[i * 4 + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh.wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g; g = f; f = e;
            e = d.wrapping_add(t1);
            d = c; c = b; b = a;
            a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a); h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c); h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e); h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g); h[7] = h[7].wrapping_add(hh);
    }
    let mut out = String::with_capacity(64);
    for v in h.iter() {
        out.push_str(&format!("{:08x}", v));
    }
    out
}

// ---------------------------------------------------------------------------
// Normalization + content addressing (mirror of ufcs_store._norm/_h/fingerprint/fuid)
// ---------------------------------------------------------------------------

/// `" ".join(str(s).strip().lower().split())` — trim, lowercase, collapse every
/// whitespace run to a single space. `split_whitespace` also trims, so this is
/// exactly the Python behaviour for the whitespace set both runtimes share
/// (space, \t, \n, \r, \x0b, \x0c, NBSP, …).
pub fn norm(s: &str) -> String {
    s.to_lowercase().split_whitespace().collect::<Vec<_>>().join(" ")
}

/// `hashlib.sha256("|".join(parts))` — join parts with '|' then SHA-256 hex.
fn h(parts: &[&str]) -> String {
    sha256_hex(parts.join("|").as_bytes())
}

/// Content identity (dedup key). Matches `ufcs_store.fingerprint`.
pub fn fingerprint(subject: &str, predicate: &str, obj: &str, polarity: &str) -> String {
    h(&[&norm(subject), &norm(predicate), &norm(obj), polarity])
}

/// Python `json.dumps` string escaping with `ensure_ascii=True`: escape `"` `\`
/// the short control forms, other controls as `\u00XX`, and every non-ASCII code
/// point as `\uXXXX` (surrogate pair above the BMP). Lowercase hex, as Python emits.
fn py_json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c if (c as u32) < 0x7f => out.push(c),
            c => {
                let cp = c as u32;
                if cp <= 0xFFFF {
                    out.push_str(&format!("\\u{:04x}", cp));
                } else {
                    // surrogate pair (Python emits two \u escapes above the BMP)
                    let v = cp - 0x10000;
                    let hi = 0xD800 + (v >> 10);
                    let lo = 0xDC00 + (v & 0x3FF);
                    out.push_str(&format!("\\u{:04x}\\u{:04x}", hi, lo));
                }
            }
        }
    }
    out
}

/// Per-ingest id. Matches `ufcs_store.fuid`: SHA-256 of
/// `json.dumps({"o","p","pol","s"}, sort_keys=True, ensure_ascii=True)` joined
/// with source_id and ingested by '|'. Keys sort to: o, p, pol, s.
pub fn fuid(subject: &str, predicate: &str, obj: &str, polarity: &str, source_id: &str, ingested: &str) -> String {
    let content = format!(
        "{{\"o\": \"{}\", \"p\": \"{}\", \"pol\": \"{}\", \"s\": \"{}\"}}",
        py_json_escape(obj), py_json_escape(predicate), py_json_escape(polarity), py_json_escape(subject)
    );
    h(&[&content, source_id, ingested])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha256_known_vectors() {
        assert_eq!(sha256_hex(b""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
        assert_eq!(sha256_hex(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    }

    #[test]
    fn norm_matches_python() {
        assert_eq!(norm("  FRANCE  "), "france");
        assert_eq!(norm("HAS_CAPITAL"), "has_capital");
        assert_eq!(norm("x    y\t\nz"), "x y z");
    }

    #[test]
    fn fingerprint_normalizes() {
        assert_eq!(
            fingerprint("France", "has_capital", "Paris", "+"),
            fingerprint("  france ", "HAS_CAPITAL", "Paris", "+")
        );
        assert_ne!(
            fingerprint("France", "has_capital", "Paris", "+"),
            fingerprint("France", "has_capital", "Lyon", "+")
        );
        assert_eq!(fingerprint("a", "b", "c", "+").len(), 64);
    }
}
