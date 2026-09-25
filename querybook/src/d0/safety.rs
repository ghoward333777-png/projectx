//! QBF-C001 Safety Substrate: every record carries a safety classification
//! within itself, and every operation passes every applicable gate.

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, Default)]
pub enum SafetyClass {
    #[default]
    General,
    /// Mature or distressing material; traversable, flagged in citations.
    Sensitive,
    /// Operationally hazardous detail; not traversable by reader scopes.
    Restricted,
    /// Refused at admission; never stored.
    Prohibited,
}

impl SafetyClass {
    pub fn as_u64(self) -> u64 {
        self as u64
    }
    pub fn label(self) -> &'static str {
        match self {
            SafetyClass::General => "general",
            SafetyClass::Sensitive => "sensitive",
            SafetyClass::Restricted => "restricted",
            SafetyClass::Prohibited => "prohibited",
        }
    }
}

const RESTRICTED: &[&str] = &[
    "synthesize nerve agent",
    "weaponize",
    "build a bomb",
    "detonator circuit",
    "enrich uranium",
    "culture the pathogen",
    "increase transmissibility",
    "ricin extraction",
];
const SENSITIVE: &[&str] = &["suicide", "self-harm", "overdose", "sexual assault", "torture"];

/// Deterministic rule-based classification over the assertion's text.
pub fn classify(text: &str) -> SafetyClass {
    let t = text.to_lowercase();
    if RESTRICTED.iter().any(|k| t.contains(k)) {
        return SafetyClass::Restricted;
    }
    if SENSITIVE.iter().any(|k| t.contains(k)) {
        return SafetyClass::Sensitive;
    }
    SafetyClass::General
}

/// Evaluation recorded into the ledger node so a bypass is detectable.
#[derive(Clone, Debug, Serialize)]
pub struct Evaluation {
    pub gate: &'static str,
    pub admitted: usize,
    pub refused: usize,
    pub by_class: [usize; 4],
}

impl Evaluation {
    pub fn new(gate: &'static str) -> Self {
        Evaluation { gate, admitted: 0, refused: 0, by_class: [0; 4] }
    }
    pub fn record(&mut self, c: SafetyClass) -> bool {
        self.by_class[c as usize] += 1;
        if c == SafetyClass::Prohibited {
            self.refused += 1;
            false
        } else {
            self.admitted += 1;
            true
        }
    }
    pub fn digest(&self) -> String {
        format!("{}:admitted={};refused={};classes={:?}", self.gate, self.admitted, self.refused, self.by_class)
    }
}
