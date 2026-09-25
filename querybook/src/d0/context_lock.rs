//! QBF-C006 Context Lock and Key. The dimensions over which determinism is
//! asserted are enumerated here (a member of the excluded set). Identical keys
//! for an identical query mean the outputs must be byte-identical; a difference
//! is a defect. Differing keys mean nothing is claimed.

use crate::util::sha256_hex;
use serde::Serialize;

pub const LOCKED_DIMENSIONS: &[&str] =
    &["device", "entitlement", "locale", "register", "audience", "posture", "costs", "regime", "store"];

#[derive(Clone, Debug, Serialize)]
pub struct ContextDims {
    pub device: String,
    /// Sorted "work@marker" entries plus enabled corpora.
    pub entitlement: Vec<String>,
    pub locale: String,
    pub register: String,
    pub audience: String,
    pub posture: String,
    pub costs: String,
    pub regime: String,
    /// Head of the substrate: every committed write changes it.
    pub store: String,
}

impl ContextDims {
    pub fn key(&self) -> String {
        let canon = serde_json::to_string(self).expect("dims serialize");
        sha256_hex(format!("ctx-lock-v1|{canon}").as_bytes())
    }
}
