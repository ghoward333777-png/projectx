//! The Fact Unit (QBF-C030, v65 schema) carried in a UFCS Fact Envelope.
//!
//! Atom (nucleus): subject, predicate, object, n-ary args (C283), polarity
//! (C282). Envelope: content-derived identity, evidence pair with source-class
//! attribution, provenance, certification, safety classification and ACL held
//! inside the record. A Fact Unit is immutable: a revision is a new record
//! linked by a hash-chained supersession (C286).

use crate::d0::SafetyClass;
use crate::util::{canon_text, sha256_hex};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "t", content = "v")]
pub enum Value {
    /// A canonical concept identifier.
    Concept(String),
    Text(String),
    Number {
        value: f64,
        unit: String,
    },
    Date(String),
    Bool(bool),
}

impl Value {
    pub fn canonical(&self) -> String {
        match self {
            Value::Concept(c) => format!("c:{c}"),
            Value::Text(t) => format!("t:{}", canon_text(t)),
            Value::Number { value, unit } => format!("n:{value}:{}", canon_text(unit)),
            Value::Date(d) => format!("d:{}", d.trim()),
            Value::Bool(b) => format!("b:{b}"),
        }
    }
    pub fn concept(&self) -> Option<&str> {
        match self {
            Value::Concept(c) => Some(c),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Atom {
    pub subject: String,
    pub predicate: String,
    pub object: Value,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub args: BTreeMap<String, Value>,
    /// true = asserted, false = the negation is asserted.
    pub polarity: bool,
}

impl Atom {
    /// Canonical form the semantic fingerprint is computed over. Language and
    /// surface independent for concept references; normalized for text.
    pub fn canonical(&self) -> String {
        let mut s =
            format!("{}|{}|{}|{}", self.subject, self.predicate, self.object.canonical(), if self.polarity { "+" } else { "-" });
        for (k, v) in &self.args {
            s.push('|');
            s.push_str(k);
            s.push('=');
            s.push_str(&v.canonical());
        }
        s
    }
    pub fn fingerprint(&self) -> String {
        sha256_hex(format!("fp-v1|{}", self.canonical()).as_bytes())
    }
    pub fn concepts(&self) -> Vec<&str> {
        let mut v = vec![self.subject.as_str()];
        if let Some(c) = self.object.concept() {
            v.push(c);
        }
        for a in self.args.values() {
            if let Some(c) = a.concept() {
                v.push(c);
            }
        }
        v
    }
}

/// Tri-temporal anchoring: when the assertion held, when it was ingested, when
/// its source was created (attestation).
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct Temporal {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub occurred: Option<String>,
    pub ingested: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub attested: Option<String>,
}

/// Where in a work the assertion is disclosed (spoiler protection, citation).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Narrative {
    pub work: String,
    /// Position of first disclosure (passage index).
    pub pos: u64,
    pub chapter: u32,
    /// Further positions that restate it (provenance branches).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub also: Vec<u64>,
}

/// Diversity-weighted Bayesian evidence pair (QBF-C089, C023, C281, C285).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    pub alpha: f64,
    pub beta: f64,
    /// Contributed weight per registered source class.
    pub by_class: BTreeMap<String, f64>,
}

impl Evidence {
    /// Three-tier prior from the source class's registered reliability.
    pub fn prior(reliability: f64) -> Evidence {
        let k = 2.0;
        Evidence { alpha: reliability * k, beta: (1.0 - reliability) * k, by_class: BTreeMap::new() }
    }
    pub fn support(&mut self, class: &str, weight: f64) {
        self.alpha += weight;
        *self.by_class.entry(class.to_string()).or_insert(0.0) += weight;
    }
    pub fn contradict(&mut self, weight: f64) {
        self.beta += weight;
    }
    pub fn confidence(&self) -> f64 {
        self.alpha / (self.alpha + self.beta)
    }
    pub fn weight(&self) -> f64 {
        self.alpha + self.beta
    }
    /// Epistemic (reducible) component: posterior variance of the Beta.
    pub fn epistemic(&self) -> f64 {
        let n = self.weight();
        self.alpha * self.beta / (n * n * (n + 1.0))
    }
    /// Aleatory (irreducible) component.
    pub fn aleatory(&self) -> f64 {
        let p = self.confidence();
        p * (1.0 - p)
    }
    /// Lower edge of the ~90% credible interval.
    pub fn lower(&self) -> f64 {
        (self.confidence() - 1.645 * self.epistemic().sqrt()).max(0.0)
    }
    /// Effective number of source classes, exp(Shannon entropy). Repeated
    /// elicitation from one engine stays at 1.0 (QBF-C023).
    pub fn diversity(&self) -> f64 {
        let total: f64 = self.by_class.values().sum();
        if total <= 0.0 {
            return 0.0;
        }
        let h: f64 = self
            .by_class
            .values()
            .filter(|w| **w > 0.0)
            .map(|w| {
                let p = w / total;
                -p * p.ln()
            })
            .sum();
        h.exp()
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SourceRef {
    /// Registered source class, e.g. "work-text", "engine:claude", "ufcs:feed".
    pub class: String,
    pub id: String,
    /// Registered authority/reliability of the class.
    pub authority: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum EdgeClass {
    Semantic,
    Editorial,
    Temporal,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Edge {
    pub class: EdgeClass,
    pub predicate: String,
    pub target: String,
    pub weight: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Supersession {
    pub prior: String,
    /// "correction" or "restatement".
    pub relation: String,
    /// Hash link: sha256(prior fuid | prior frame hash).
    pub link: String,
}

/// QBF-C022: unmodifiable derivation marking.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Derivation {
    /// "reported" | "derived" | "reconstructed" | "engine" | "reader" | "imported"
    pub kind: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub engine: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prompt_hash: Option<String>,
    /// QBF-C024: did every citation in the engine's reply resolve?
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub citation_verified: Option<bool>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ProvRef {
    /// Ledger node (batch) that admitted the record.
    pub batch: u64,
    /// Leaf index within the batch's Merkle tree.
    pub leaf: u32,
}

/// UFCS certification carried in the envelope.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Certification {
    pub authority: String,
    /// "certified" | "uncertified" | "contested" | "revoked"
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub certified_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub signature: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FactUnit {
    pub fuid: String,
    pub fingerprint: String,
    pub type_ref: String,
    pub atom: Atom,
    /// UFCS group classification.
    pub group: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub applicability: Option<String>,
    pub temporal: Temporal,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spatial: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub narrative: Option<Narrative>,
    pub evidence: Evidence,
    pub source: SourceRef,
    pub modality: String,
    pub safety: SafetyClass,
    /// Access control carried in the record: "public", "work:<id>",
    /// "user:<id>", "tenant:<id>".
    pub acl: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub edges: Vec<Edge>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub supersedes: Option<Supersession>,
    pub derivation: Derivation,
    pub provenance: ProvRef,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub certification: Option<Certification>,
    /// Wording-operative source span, reproduced verbatim, never regenerated.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quote: Option<String>,
    /// Display labels for the concepts this record references.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub labels: BTreeMap<String, String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub external_id: Option<String>,
}

impl FactUnit {
    /// FUID: deterministic in (content, source, ingestion time).
    pub fn compute_fuid(&self) -> String {
        let content = format!(
            "{}|{}|{}|{}",
            self.type_ref,
            self.atom.canonical(),
            self.narrative.as_ref().map(|n| format!("{}@{}", n.work, n.pos)).unwrap_or_default(),
            self.quote.as_deref().map(canon_text).unwrap_or_default()
        );
        sha256_hex(format!("fuid-v1|{content}|{}:{}|{}", self.source.class, self.source.id, self.temporal.ingested).as_bytes())
    }

    pub fn seal(&mut self) {
        self.fingerprint = self.atom.fingerprint();
        self.fuid = self.compute_fuid();
    }

    pub fn status(&self) -> &str {
        if let Some(c) = &self.certification {
            return &c.status;
        }
        // QBF-C024: a model-derived record whose cited span does not resolve
        // in the source is kept and disclosed, but never grounds an answer
        if self.derivation.citation_verified == Some(false) {
            return "unverified";
        }
        if self.evidence.beta > self.evidence.alpha { "contested" } else { "uncertified" }
    }

    /// Trust-native score: calibrated lower confidence bound, weighted by the
    /// source authority, raised by corroboration diversity and lowered by
    /// contradiction state. Deterministic in the record's own fields.
    pub fn trust(&self) -> f64 {
        let e = &self.evidence;
        // diversity bonus in [0.5, 1): one source class 0.5, two 0.75, three 0.875
        let diversity_bonus = 1.0 - 0.5f64.powf(e.diversity().max(1.0));
        let mut t = e.lower() * (0.5 + 0.5 * self.source.authority) * (0.8 + 0.2 * diversity_bonus);
        match self.status() {
            "certified" => t = (t * 1.15).min(1.0),
            "contested" => t *= 0.5,
            "revoked" => t = 0.0,
            _ => {}
        }
        if self.derivation.citation_verified == Some(false) {
            t *= 0.4;
        }
        (t.clamp(0.0, 1.0) * 1e6).round() / 1e6
    }

    pub fn work(&self) -> Option<&str> {
        self.narrative.as_ref().map(|n| n.work.as_str())
    }

    pub fn label(&self, concept: &str) -> String {
        self.labels.get(concept).cloned().unwrap_or_else(|| humanize_concept(concept))
    }
}

/// Fall-back display for a concept id like "w:pg1342/mr-darcy".
pub fn humanize_concept(id: &str) -> String {
    let tail = id.rsplit(['/', ':']).next().unwrap_or(id);
    tail.split('-')
        .filter(|w| !w.is_empty())
        .map(|w| {
            let mut c = w.chars();
            match c.next() {
                Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

// ---- QBF frame format (C032, C287, C288) ----------------------------------
//
// frame   := "QBF1" | u32 LE payload length | payload | u32 LE crc32(payload)
// payload := '{' canonical JSON                     (plain form)
//          | 0x01 zstd(canonical JSON)              (compact form)
// The compact form yields the same FUID and fingerprint as the full form
// because both are computed over the record's content, not its encoding. A
// corrupt frame costs one frame: a reader scans to the next "QBF1" magic.

pub const MAGIC: &[u8; 4] = b"QBF1";
const CODEC_ZSTD: u8 = 0x01;

fn frame(payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(payload.len() + 12);
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&(payload.len() as u32).to_le_bytes());
    out.extend_from_slice(payload);
    out.extend_from_slice(&crc32fast::hash(payload).to_le_bytes());
    out
}

/// Plain (JSON) frame, used for exports meant to be read anywhere.
pub fn encode(f: &FactUnit) -> Vec<u8> {
    frame(&serde_json::to_vec(f).expect("fact serializes"))
}

/// Compact frame (the at-rest form in the store).
pub fn encode_compact(f: &FactUnit) -> Vec<u8> {
    let json = serde_json::to_vec(f).expect("fact serializes");
    let mut payload = Vec::with_capacity(json.len() / 2 + 8);
    payload.push(CODEC_ZSTD);
    payload.extend(zstd::bulk::compress(&json, 3).expect("zstd compresses"));
    frame(&payload)
}

pub fn decode(frame: &[u8]) -> anyhow::Result<FactUnit> {
    anyhow::ensure!(frame.len() >= 12 && &frame[..4] == MAGIC, "not a QBF1 frame");
    let len = u32::from_le_bytes(frame[4..8].try_into().unwrap()) as usize;
    anyhow::ensure!(frame.len() == len + 12, "frame length mismatch");
    let payload = &frame[8..8 + len];
    let crc = u32::from_le_bytes(frame[8 + len..].try_into().unwrap());
    anyhow::ensure!(crc32fast::hash(payload) == crc, "frame checksum mismatch");
    match payload.first() {
        Some(&CODEC_ZSTD) => Ok(serde_json::from_slice(&zstd::bulk::decompress(&payload[1..], 16 * 1024 * 1024)?)?),
        _ => Ok(serde_json::from_slice(payload)?),
    }
}

/// Decode a concatenated stream, skipping corrupt frames by resynchronising
/// on the next magic. Returns (records, frames skipped).
pub fn decode_stream(bytes: &[u8]) -> (Vec<FactUnit>, usize) {
    let mut out = Vec::new();
    let mut skipped = 0;
    let mut i = 0;
    while i + 12 <= bytes.len() {
        if &bytes[i..i + 4] != MAGIC {
            i += 1;
            continue;
        }
        let len = u32::from_le_bytes(bytes[i + 4..i + 8].try_into().unwrap()) as usize;
        let end = i + 12 + len;
        if end <= bytes.len() {
            if let Ok(f) = decode(&bytes[i..end]) {
                out.push(f);
                i = end;
                continue;
            }
        }
        skipped += 1;
        i += 4;
    }
    (out, skipped)
}

#[cfg(test)]
pub mod tests {
    use super::*;

    pub fn sample(subject: &str, obj: &str) -> FactUnit {
        let mut f = FactUnit {
            fuid: String::new(),
            fingerprint: String::new(),
            type_ref: "assertion.property".into(),
            atom: Atom {
                subject: subject.into(),
                predicate: "is_a".into(),
                object: Value::Text(obj.into()),
                args: BTreeMap::new(),
                polarity: true,
            },
            group: "book".into(),
            applicability: None,
            temporal: Temporal { occurred: None, ingested: 1_700_000_000, attested: None },
            spatial: None,
            narrative: Some(Narrative { work: "w1".into(), pos: 10, chapter: 1, also: vec![] }),
            evidence: Evidence::prior(0.6),
            source: SourceRef { class: "engine:rules".into(), id: "w1".into(), authority: 0.6 },
            modality: "text".into(),
            safety: SafetyClass::General,
            acl: vec!["work:w1".into()],
            edges: vec![],
            supersedes: None,
            derivation: Derivation {
                kind: "engine".into(),
                engine: Some("rules".into()),
                prompt_hash: None,
                citation_verified: Some(true),
            },
            provenance: ProvRef { batch: 0, leaf: 0 },
            certification: None,
            quote: Some("Darcy was a proud man.".into()),
            labels: BTreeMap::new(),
            external_id: None,
        };
        f.evidence.support("engine:rules", 0.6);
        f.seal();
        f
    }

    #[test]
    fn fuid_and_fingerprint_are_deterministic() {
        let a = sample("w:w1/mr-darcy", "a proud man");
        let b = sample("w:w1/mr-darcy", "A  Proud man");
        assert_eq!(a.fingerprint, b.fingerprint, "fingerprint normalizes surface form");
        assert_eq!(a.fuid, sample("w:w1/mr-darcy", "a proud man").fuid);
        let mut neg = a.clone();
        neg.atom.polarity = false;
        assert_ne!(neg.atom.fingerprint(), a.fingerprint, "polarity participates");
    }

    #[test]
    fn frames_roundtrip_and_resync() {
        let a = sample("w:w1/a", "x");
        let b = sample("w:w1/b", "y");
        let fa = encode(&a);
        assert_eq!(decode(&fa).unwrap(), a);
        let fc = encode_compact(&a);
        assert_eq!(decode(&fc).unwrap(), a, "compact form decodes to the same record");
        assert_eq!(decode(&fc).unwrap().compute_fuid(), a.fuid);
        let mut stream = fa.clone();
        stream[20] ^= 0xFF; // corrupt first frame
        stream.extend(encode(&b));
        let (recs, skipped) = decode_stream(&stream);
        assert_eq!(recs, vec![b]);
        assert_eq!(skipped, 1);
    }

    #[test]
    fn self_corroboration_bar() {
        let mut one = Evidence::prior(0.6);
        for _ in 0..3 {
            one.support("engine:claude", 1.0);
        }
        let mut three = Evidence::prior(0.6);
        for c in ["engine:claude", "engine:rules", "work-text"] {
            three.support(c, 1.0);
        }
        assert!((one.diversity() - 1.0).abs() < 1e-9);
        assert!((three.diversity() - 3.0).abs() < 1e-9);
        assert_eq!(one.confidence(), three.confidence());
    }
}
