//! Operator configuration. Loaded once at start-up and never modified by the
//! running system: the convergence regime, the context-lock dimension set and
//! the traversal cost table are members of the permanently-excluded set, so
//! they change only when an operator edits this file (the election is recorded
//! in the provenance ledger with the operator's identity at start-up).

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    pub server: Server,
    pub operator: Operator,
    pub engines: Vec<EngineProfile>,
    pub retrieval: Retrieval,
    pub convergence: Convergence,
    pub traversal: Traversal,
    pub library: Library,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Server {
    pub bind: String,
    pub data_dir: PathBuf,
    /// Tantivy writer heap in MB (raise for bulk UFCS import).
    pub index_heap_mb: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Operator {
    pub name: String,
}

/// A registered extraction engine (QBF-C020/C021): the only place a trained
/// component may run, and only on the ingestion path.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EngineProfile {
    pub id: String,
    /// "rules" (built in, runs on this server), "claude" (Anthropic API),
    /// or "openai" (any OpenAI-compatible server you host: vLLM, Ollama, llama.cpp).
    pub kind: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub base_url: String,
    /// Environment variable holding the API key (never the key itself).
    #[serde(default)]
    pub api_key_env: String,
    /// Registered reliability: seeds the Beta prior for records it produces.
    #[serde(default = "default_reliability")]
    pub reliability: f64,
    #[serde(default)]
    pub effort: String,
    /// Words per extraction request.
    #[serde(default = "default_chunk_words")]
    pub chunk_words: usize,
    /// Parallel requests in flight.
    #[serde(default = "default_concurrency")]
    pub concurrency: usize,
    /// USD per million tokens, for `qb estimate`.
    #[serde(default)]
    pub input_price: f64,
    #[serde(default)]
    pub output_price: f64,
    /// Ask an OpenAI-compatible server for JSON mode.
    #[serde(default = "default_true")]
    pub json_mode: bool,
}

fn default_reliability() -> f64 {
    0.6
}
fn default_chunk_words() -> usize {
    2200
}
fn default_concurrency() -> usize {
    4
}
fn default_true() -> bool {
    true
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Retrieval {
    /// Minimum trust for a record to be admitted as grounding (QBF-C046 rule).
    pub admission_threshold: f64,
    pub candidates: usize,
    pub max_units: usize,
    pub answer_facts: usize,
    /// Pre-computed answer match threshold (QBF-C084).
    pub question_match: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Convergence {
    /// "unique-equilibrium" (spectral contraction) or "capacity-bound".
    pub regime: String,
    /// Spectral-norm bound for the contraction regime (< 1).
    pub spectral_bound: f64,
    /// Operating ceiling for alpha = P/N under the capacity regime (< 0.138).
    pub load_ceiling: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Traversal {
    pub budget: f64,
    pub semantic: f64,
    pub editorial: f64,
    pub temporal: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Library {
    /// Every signed-in reader is entitled to works declared public-domain.
    pub open_public_domain: bool,
    /// Spoiler protection default for new works (author-configurable per work).
    pub spoiler_default: bool,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            server: Server::default(),
            operator: Operator::default(),
            engines: vec![EngineProfile {
                id: "rules".into(),
                kind: "rules".into(),
                model: String::new(),
                base_url: String::new(),
                api_key_env: String::new(),
                reliability: 0.6,
                effort: String::new(),
                chunk_words: 2200,
                concurrency: 4,
                input_price: 0.0,
                output_price: 0.0,
                json_mode: true,
            }],
            retrieval: Retrieval::default(),
            convergence: Convergence::default(),
            traversal: Traversal::default(),
            library: Library::default(),
        }
    }
}
impl Default for Server {
    fn default() -> Self {
        Server { bind: "127.0.0.1:8090".into(), data_dir: PathBuf::from("./data"), index_heap_mb: 256 }
    }
}
impl Default for Operator {
    fn default() -> Self {
        Operator { name: "operator".into() }
    }
}
impl Default for Retrieval {
    fn default() -> Self {
        Retrieval { admission_threshold: 0.2, candidates: 160, max_units: 96, answer_facts: 6, question_match: 0.8 }
    }
}
impl Default for Convergence {
    fn default() -> Self {
        Convergence { regime: "unique-equilibrium".into(), spectral_bound: 0.9, load_ceiling: 0.12 }
    }
}
impl Default for Traversal {
    fn default() -> Self {
        Traversal { budget: 6.0, semantic: 1.0, editorial: 3.0, temporal: 5.0 }
    }
}
impl Default for Library {
    fn default() -> Self {
        Library { open_public_domain: true, spoiler_default: true }
    }
}

impl Config {
    pub fn load(path: Option<&Path>) -> anyhow::Result<Config> {
        let mut cfg = match path {
            Some(p) => {
                let text = std::fs::read_to_string(p).map_err(|e| anyhow::anyhow!("reading config {}: {e}", p.display()))?;
                toml::from_str::<Config>(&text)?
            }
            None => Config::default(),
        };
        if cfg.engines.is_empty() {
            cfg.engines = Config::default().engines;
        }
        cfg.validate()?;
        Ok(cfg)
    }

    pub fn validate(&self) -> anyhow::Result<()> {
        match self.convergence.regime.as_str() {
            "unique-equilibrium" => {
                anyhow::ensure!(
                    self.convergence.spectral_bound > 0.0 && self.convergence.spectral_bound < 1.0,
                    "spectral_bound must be in (0,1) for the unique-equilibrium regime"
                )
            }
            "capacity-bound" => anyhow::ensure!(
                self.convergence.load_ceiling < 0.138,
                "load_ceiling must stay below the retrieval-phase boundary 0.138"
            ),
            other => anyhow::bail!("unknown convergence regime {other}"),
        }
        for e in &self.engines {
            anyhow::ensure!(
                matches!(e.kind.as_str(), "rules" | "language" | "claude" | "openai"),
                "engine {} has unknown kind {}",
                e.id,
                e.kind
            );
            anyhow::ensure!(e.reliability > 0.0 && e.reliability < 1.0, "engine {} reliability must be in (0,1)", e.id);
        }
        Ok(())
    }

    pub fn engine(&self, id: &str) -> Option<&EngineProfile> {
        self.engines.iter().find(|e| e.id == id)
    }
}
