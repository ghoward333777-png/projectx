//! Registered extraction engines (QBF-C020..C024). Engines run only on the
//! ingestion path; the query path never calls one.

pub mod llm;
pub mod rules;

use crate::config::EngineProfile;
use crate::d1::parse::Book;
use crate::d2::Atom;
use crate::d3::Catalog;
use crate::d3::entities::EntityTable;
use std::collections::BTreeMap;

/// A candidate record before calibration and admission.
#[derive(Clone, Debug)]
pub struct Candidate {
    pub type_ref: String,
    pub atom: Atom,
    pub labels: BTreeMap<String, String>,
    pub pos: u64,
    pub chapter: u32,
    pub quote: String,
    pub engine: String,
    pub prompt_hash: Option<String>,
    pub citation_verified: bool,
}

#[derive(Clone, Debug, Default, serde::Serialize)]
pub struct EngineReport {
    pub engine: String,
    pub requests: usize,
    pub failed_requests: usize,
    pub candidates: usize,
    pub refused: usize,
    pub unverified_citations: usize,
    pub input_tokens: u64,
    pub output_tokens: u64,
}

pub trait Extractor: Send + Sync {
    fn id(&self) -> &str;
    fn reliability(&self) -> f64;
    fn extract(
        &self,
        book: &Book,
        entities: &EntityTable,
        catalog: &Catalog,
        progress: &(dyn Fn(&str) + Sync),
    ) -> anyhow::Result<(Vec<Candidate>, EngineReport)>;
}

pub fn build(profile: &EngineProfile) -> anyhow::Result<Box<dyn Extractor>> {
    Ok(match profile.kind.as_str() {
        "rules" => Box::new(rules::RuleEngine { id: profile.id.clone(), reliability: profile.reliability }),
        "claude" | "openai" => Box::new(llm::LlmEngine::new(profile.clone())?),
        k => anyhow::bail!("unknown engine kind {k}"),
    })
}
