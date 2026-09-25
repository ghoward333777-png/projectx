//! Shared application context for the CLI and the server.

use crate::config::Config;
use crate::d2::Store;
use crate::d3::Catalog;
use crate::util::sha256_hex;
use std::sync::{Arc, RwLock};

pub struct QueryBook {
    pub cfg: Config,
    pub store: Store,
    pub catalog: RwLock<Catalog>,
    catalog_count: std::sync::atomic::AtomicUsize,
}

impl QueryBook {
    pub fn open(cfg: Config) -> anyhow::Result<Arc<QueryBook>> {
        let store = Store::open(&cfg.server.data_dir, cfg.server.index_heap_mb)?;
        let catalog = Catalog::load(&store)?;
        let n = catalog.predicates.len();
        let qb = QueryBook { cfg, store, catalog: RwLock::new(catalog), catalog_count: std::sync::atomic::AtomicUsize::new(n) };
        qb.record_operator_election()?;
        Ok(Arc::new(qb))
    }

    /// The excluded-set parameters (convergence regime, traversal costs,
    /// context-lock dimensions) are recorded with the operator's identity
    /// whenever they change.
    fn record_operator_election(&self) -> anyhow::Result<()> {
        let election = serde_json::json!({
            "convergence": self.cfg.convergence,
            "traversal": self.cfg.traversal,
            "context_lock": crate::d0::context_lock::LOCKED_DIMENSIONS,
            "admission_threshold": self.cfg.retrieval.admission_threshold,
        })
        .to_string();
        let h = sha256_hex(election.as_bytes());
        let last: Option<String> = self.store.read(|c| {
            Ok(c.query_row("SELECT payload_hash FROM ledger WHERE op='operator.election' ORDER BY seq DESC LIMIT 1", [], |r| {
                r.get(0)
            })
            .ok())
        })?;
        if last.as_deref() != Some(h.as_str()) {
            self.store.ledger_append(&self.cfg.operator.name, "operator.election", "D0 operator", &election, "excluded-set")?;
        }
        Ok(())
    }

    /// Pick up predicates registered by another process (e.g. a UFCS import).
    pub fn refresh_catalog(&self) -> anyhow::Result<()> {
        let n: i64 = self.store.read(|c| Ok(c.query_row("SELECT COUNT(*) FROM predicates", [], |r| r.get(0))?))?;
        static BUILTIN: std::sync::OnceLock<usize> = std::sync::OnceLock::new();
        let builtin = *BUILTIN.get_or_init(|| Catalog::builtin().predicates.len());
        let expect = builtin + n as usize;
        if expect != self.catalog_count.load(std::sync::atomic::Ordering::Relaxed) {
            let c = Catalog::load(&self.store)?;
            self.catalog_count.store(c.predicates.len(), std::sync::atomic::Ordering::Relaxed);
            *self.catalog.write().unwrap() = c;
        }
        Ok(())
    }

    pub fn regime_label(&self) -> String {
        match self.cfg.convergence.regime.as_str() {
            "unique-equilibrium" => {
                format!("unique-equilibrium (spectral contraction, ‖W‖ ≤ {})", self.cfg.convergence.spectral_bound)
            }
            _ => format!("capacity-bound (α = P/N ≤ {})", self.cfg.convergence.load_ceiling),
        }
    }

    pub fn cost_table(&self) -> String {
        let t = &self.cfg.traversal;
        format!("budget={};semantic={};editorial={};temporal={}", t.budget, t.semantic, t.editorial, t.temporal)
    }
}
