//! Stage 6 — semantic embedding: the "geometry" of meaning, deterministic.
//!
//! Random indexing (Kanerva; Sahlgren): every feature (content lemma, concept
//! identifier, predicate) owns a sparse ternary index vector derived from a
//! hash of the feature, and a Fact Unit's vector is the weighted sum of its
//! features' index vectors. No training, no model, identical on every run.
//!
//! * FU embedding: lemmas of the assertion and its source span, its concepts
//!   (weighted up), its predicate.
//! * Context-window embedding: the same over the neighbouring passages,
//!   blended in so a fact carries the meaning around it.
//! * Graph alignment: each concept's vector is the mean of the facts it takes
//!   part in; every fact is pulled toward its concepts' vectors, so facts in
//!   the same region of the graph sit close in the space.
//!
//! Vectors are stored quantized (i8 per dimension, base64) in the record.

use crate::d2::{FactUnit, Value};
use crate::util::{is_stopword, sha256, words};
use base64::Engine;
use std::collections::BTreeMap;

pub const DIM: usize = 128;
const NONZERO: usize = 8;

pub type Vector = [f32; DIM];

fn index_vector(feature: &str) -> [(usize, f32); NONZERO] {
    let h = sha256(feature.as_bytes());
    let mut out = [(0usize, 0f32); NONZERO];
    for i in 0..NONZERO {
        let d = u16::from_le_bytes([h[2 * i], h[2 * i + 1]]) as usize % DIM;
        let sign = if h[16 + i] & 1 == 0 { 1.0 } else { -1.0 };
        out[i] = (d, sign);
    }
    out
}

pub fn from_features(features: &[(String, f32)]) -> Vector {
    let mut v = [0f32; DIM];
    for (f, w) in features {
        for (d, s) in index_vector(f) {
            v[d] += s * w;
        }
    }
    normalize(v)
}

pub fn normalize(mut v: Vector) -> Vector {
    let n = v.iter().map(|x| x * x).sum::<f32>().sqrt();
    if n > 0.0 {
        for x in v.iter_mut() {
            *x /= n;
        }
    }
    v
}

pub fn add(a: &Vector, b: &Vector, wb: f32) -> Vector {
    let mut v = *a;
    for i in 0..DIM {
        v[i] += wb * b[i];
    }
    v
}

pub fn cosine(a: &Vector, b: &Vector) -> f32 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

/// Content lemmas of free text (crude stemming keeps it deterministic).
pub fn text_features(text: &str, weight: f32) -> Vec<(String, f32)> {
    words(text)
        .into_iter()
        .filter(|w| w.len() > 2 && !is_stopword(w))
        .map(|w| {
            let stem = w.trim_end_matches("'s").trim_end_matches('s').trim_end_matches("ed").trim_end_matches("ing").to_string();
            (format!("w:{stem}"), weight)
        })
        .collect()
}

pub fn fact_features(f: &FactUnit) -> Vec<(String, f32)> {
    let mut v = Vec::new();
    for c in f.atom.concepts() {
        v.push((format!("c:{c}"), 2.0));
        v.extend(text_features(&f.label(c), 1.0));
    }
    v.push((format!("p:{}", f.atom.predicate), 1.5));
    if let Value::Text(t) = &f.atom.object {
        v.extend(text_features(t, 1.0));
    }
    if let Some(q) = &f.quote {
        v.extend(text_features(q, 0.5));
    }
    v
}

pub fn quantize(v: &Vector) -> String {
    let bytes: Vec<u8> = v.iter().map(|x| ((x * 127.0).round().clamp(-127.0, 127.0) as i8) as u8).collect();
    base64::engine::general_purpose::STANDARD_NO_PAD.encode(bytes)
}

pub fn dequantize(s: &str) -> Option<Vector> {
    let b = base64::engine::general_purpose::STANDARD_NO_PAD.decode(s).ok()?;
    if b.len() != DIM {
        return None;
    }
    let mut v = [0f32; DIM];
    for i in 0..DIM {
        v[i] = (b[i] as i8) as f32 / 127.0;
    }
    Some(normalize(v))
}

/// Embed a work's facts: FU vector + context window + graph alignment.
/// `passage_text(pos)` returns the text at a narrative position.
/// Returns concept vectors for the D3 concept table.
pub fn embed_work(facts: &mut [FactUnit], passage_text: &dyn Fn(u64) -> Option<String>) -> BTreeMap<String, Vector> {
    // FU + context window (±1 passage, half weight)
    let mut vecs: Vec<Vector> = Vec::with_capacity(facts.len());
    let mut ctx_cache: BTreeMap<u64, Vector> = BTreeMap::new();
    for f in facts.iter() {
        let fu = from_features(&fact_features(f));
        let v = match f.narrative.as_ref().map(|n| n.pos) {
            Some(pos) => {
                let ctx = *ctx_cache.entry(pos).or_insert_with(|| {
                    let mut feats = Vec::new();
                    for (p, w) in [(pos.saturating_sub(1), 0.5f32), (pos, 1.0), (pos + 1, 0.5)] {
                        if let Some(t) = passage_text(p) {
                            feats.extend(text_features(&t, w));
                        }
                    }
                    from_features(&feats)
                });
                normalize(add(&fu, &ctx, 0.35))
            }
            None => fu,
        };
        vecs.push(v);
    }
    // graph alignment: concept vectors, then pull each fact toward its concepts
    let mut sums: BTreeMap<String, (Vector, f32)> = BTreeMap::new();
    for (f, v) in facts.iter().zip(&vecs) {
        for c in f.atom.concepts() {
            let e = sums.entry(c.to_string()).or_insert(([0f32; DIM], 0.0));
            e.0 = add(&e.0, v, 1.0);
            e.1 += 1.0;
        }
    }
    let concepts: BTreeMap<String, Vector> = sums.into_iter().map(|(c, (v, _))| (c, normalize(v))).collect();
    for (f, v) in facts.iter_mut().zip(vecs) {
        let mut g = [0f32; DIM];
        for c in f.atom.concepts() {
            if let Some(cv) = concepts.get(c) {
                g = add(&g, cv, 1.0);
            }
        }
        let aligned = normalize(add(&v, &normalize(g), 0.25));
        f.embedding = Some(quantize(&aligned));
    }
    concepts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deterministic_and_meaningful() {
        let a = from_features(&text_features("the clockmaker repaired the tower clock", 1.0));
        let b = from_features(&text_features("the clockmaker repaired the tower clock", 1.0));
        let c = from_features(&text_features("a clockmaker fixed the clock in the tower", 1.0));
        let d = from_features(&text_features("the regiment marched to the coast at dawn", 1.0));
        assert_eq!(a, b);
        assert!(cosine(&a, &c) > cosine(&a, &d), "{} vs {}", cosine(&a, &c), cosine(&a, &d));
        let q = dequantize(&quantize(&a)).unwrap();
        assert!(cosine(&a, &q) > 0.99);
    }
}
