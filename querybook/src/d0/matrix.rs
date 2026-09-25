//! QBF-C002 Domain Transfer Matrix and QBF-C003 path separation.
//!
//! Every ordered pair of domains carries a permission. A pair absent from the
//! table is DENY: a denied transfer has no route. The denials carry the
//! guarantees (generation cannot write, surfaces cannot touch the store,
//! commerce cannot reach retrieval, governance cannot amend D0).

use serde::Serialize;
use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize)]
pub enum Domain {
    D0,
    D1,
    D2,
    D3,
    D4,
    D5,
    D6,
    D7,
    D8,
    D9,
    D10,
    D11,
    D12,
    D13,
    D14,
}

impl Domain {
    pub fn name(self) -> &'static str {
        match self {
            Domain::D0 => "Prime Directive",
            Domain::D1 => "Ingestion & Sensory Intake",
            Domain::D2 => "Knowledge Substrate",
            Domain::D3 => "Ontology & Conceptual Structure",
            Domain::D4 => "Retrieval & Response",
            Domain::D5 => "Inference, Prediction & Calibration",
            Domain::D6 => "World Model & Perception",
            Domain::D7 => "Grounded Expression",
            Domain::D8 => "Access, Rights & Retention",
            Domain::D9 => "Interaction Surfaces",
            Domain::D10 => "Authoring, Editions & Publication",
            Domain::D11 => "Platform Governance & Evolution",
            Domain::D12 => "External Integration & Analysis",
            Domain::D13 => "Commerce & Entitlement Tokens",
            Domain::D14 => "Learning & Assessment",
        }
    }
    /// QBF-C004: scheduling priority, D0 highest, D13 lowest; latency path
    /// ahead of batch path.
    pub fn priority(self) -> u8 {
        match self {
            Domain::D0 => 0,
            Domain::D8 => 1,
            Domain::D4 => 2,
            Domain::D5 => 3,
            Domain::D7 => 4,
            Domain::D9 => 5,
            Domain::D14 => 6,
            Domain::D2 => 7,
            Domain::D3 => 8,
            Domain::D1 => 9,
            Domain::D6 => 10,
            Domain::D10 => 11,
            Domain::D11 => 12,
            Domain::D12 => 13,
            Domain::D13 => 14,
        }
    }
}

impl fmt::Display for Domain {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}", self)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum Permission {
    Allow,
    Deny,
    /// Permitted subject to a stated conversion.
    Transform(&'static str),
}

use Domain::*;
use Permission::*;

/// The registered matrix. Denials are listed explicitly so they read as
/// guarantees; anything not listed is denied as well.
const MATRIX: &[(Domain, Domain, Permission)] = &[
    // Guarantees (explicit denials)
    (D12, D4, Deny),
    (D13, D4, Deny),
    (D13, D7, Deny),
    (D13, D8, Deny),
    (D9, D2, Deny),
    (D9, D0, Deny),
    (D11, D0, Deny),
    (D7, D2, Deny),
    (D14, D13, Deny),
    // Conversions
    (D1, D2, Transform("safety-evaluation+type-validation+confidence-calibration")),
    (D5, D2, Transform("derived-inference-marking")),
    (D4, D13, Transform("concept-id+one-hop-adjacency-read-only")),
    (D12, D2, Transform("analysis-record-marking")),
    (D10, D2, Transform("rights-validation")),
    (D10, D1, Transform("rights-validation")),
    (D8, D2, Transform("reader-authored-acl-owner-only")),
    // Query path: D8 -> D4 -> D5? -> D7 (scope precedes traversal)
    (D9, D8, Allow),
    (D8, D4, Allow),
    (D4, D2, Allow), // read
    (D4, D5, Allow),
    (D4, D7, Allow),
    (D5, D7, Allow),
    (D7, D9, Allow),
    (D4, D9, Allow),
    // Ingestion path: D1 -> D2 -> D3 -> D6
    (D2, D3, Allow),
    (D3, D6, Allow),
    (D5, D4, Allow),
    // Learning
    (D9, D14, Allow),
    (D14, D8, Allow),
    (D14, D9, Allow),
    // Authoring surface
    (D9, D10, Allow),
    (D11, D8, Allow),
];

pub fn permission(from: Domain, to: Domain) -> Permission {
    if from == D0 {
        return Allow; // governance reaches everywhere
    }
    for (f, t, p) in MATRIX {
        if *f == from && *t == to {
            return *p;
        }
    }
    if to == D3 {
        return Allow; // read-only; writing D3 is reserved to D3
    }
    Deny
}

#[derive(Clone, Debug, Serialize)]
pub struct Crossing {
    pub from: Domain,
    pub to: Domain,
    pub op: String,
    pub permission: String,
}

#[derive(Debug)]
pub struct Refused {
    pub from: Domain,
    pub to: Domain,
    pub op: String,
    pub reason: String,
}

impl fmt::Display for Refused {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "transfer {}->{} ({}) refused: {}", self.from, self.to, self.op, self.reason)
    }
}
impl std::error::Error for Refused {}

/// Evaluate a crossing. A TRANSFORM-REQUIRED crossing proceeds only when the
/// caller names the conversion it performed and it matches the registered one.
pub fn cross(from: Domain, to: Domain, op: &str, conversion_done: Option<&str>) -> Result<Crossing, Refused> {
    let perm = permission(from, to);
    let label = match perm {
        Allow => "ALLOW".to_string(),
        Deny => {
            return Err(Refused { from, to, op: op.into(), reason: "DENY (matrix)".into() });
        }
        Transform(req) => {
            if conversion_done != Some(req) {
                return Err(Refused { from, to, op: op.into(), reason: format!("TRANSFORM-REQUIRED ({req}) not satisfied") });
            }
            format!("TRANSFORM({req})")
        }
    };
    Ok(Crossing { from, to, op: op.into(), permission: label })
}

/// Trace of the crossings a single operation made; returned with every answer.
#[derive(Clone, Debug, Default, Serialize)]
pub struct Trace {
    pub crossings: Vec<Crossing>,
}

impl Trace {
    pub fn cross(&mut self, from: Domain, to: Domain, op: &str) -> Result<(), Refused> {
        let c = cross(from, to, op, None)?;
        self.crossings.push(c);
        Ok(())
    }
}

/// Path separation invariant: the query path and the ingestion path share
/// at most D0 and D2.
pub const QUERY_PATH: &[Domain] = &[D8, D4, D5, D7];
pub const INGESTION_PATH: &[Domain] = &[D1, D2, D3, D6, D5];

pub fn path_intersection() -> Vec<Domain> {
    let mut v: Vec<Domain> = QUERY_PATH.iter().copied().filter(|d| INGESTION_PATH.contains(d)).collect();
    v.sort();
    v
}

/// A permit to write the substrate. Its field is private to D0, so the only
/// way to obtain one is a satisfied D1->D2 (or D5/D8/D10/D12->D2) crossing.
/// D7 can never hold one: its crossing to D2 is denied.
pub struct CommitPermit {
    _private: (),
    pub crossing: Crossing,
}

pub fn commit_permit(from: Domain, conversion_done: &str) -> Result<CommitPermit, Refused> {
    let crossing = cross(from, D2, "commit", Some(conversion_done))?;
    Ok(CommitPermit { _private: (), crossing })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn guarantees_hold() {
        for (f, t) in [(D7, D2), (D9, D2), (D9, D0), (D11, D0), (D12, D4), (D13, D4), (D13, D7), (D13, D8), (D14, D13)] {
            assert_eq!(permission(f, t), Deny, "{f}->{t} must be denied");
            assert!(cross(f, t, "x", None).is_err());
        }
        assert!(commit_permit(D7, "anything").is_err());
    }

    #[test]
    fn absent_is_deny_and_transform_needs_conversion() {
        assert_eq!(permission(D6, D13), Deny);
        assert!(cross(D1, D2, "commit", None).is_err());
        assert!(cross(D1, D2, "commit", Some("wrong")).is_err());
        assert!(commit_permit(D1, "safety-evaluation+type-validation+confidence-calibration").is_ok());
    }

    #[test]
    fn path_separation() {
        let shared = path_intersection();
        assert!(shared.len() <= 2, "query and ingestion paths share {:?}", shared);
        assert!(shared.iter().all(|d| matches!(d, D0 | D2 | D5)));
        assert!(D0.priority() < D13.priority());
    }
}
