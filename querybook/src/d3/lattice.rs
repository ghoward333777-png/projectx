//! The knowledge lattice: QueryBook's own upper structure of general
//! knowledge (QBF-C113 World-View Model, ontological part) — domains,
//! subdomains and classes with poly-hierarchical placement (QBF-C042), and
//! for each class the slots its members are expected to carry.
//!
//! The lattice is structure, never fact. It is read by D5 (which predicts
//! what the cells hold) and by D12 (which harvests only the cells in
//! question); it is written only here, and every registration is ledgered.

use crate::d2::Store;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Source {
    #[serde(default = "endpoint")]
    pub endpoint: String,
    #[serde(default = "api")]
    pub api: String,
    #[serde(default)]
    pub contact: String,
    #[serde(default = "page")]
    pub page_size: usize,
    /// members per targeted fill query (VALUES batch)
    #[serde(default = "batch")]
    pub batch: usize,
    #[serde(default = "pause")]
    pub pause_ms: u64,
    #[serde(default = "conf")]
    pub confidence: f64,
    #[serde(default = "weight")]
    pub weight: f64,
}
fn endpoint() -> String {
    "https://query.wikidata.org/sparql".into()
}
fn api() -> String {
    "https://www.wikidata.org/w/api.php".into()
}
fn page() -> usize {
    5000
}
fn batch() -> usize {
    250
}
fn pause() -> u64 {
    1200
}
fn conf() -> f64 {
    0.9
}
fn weight() -> f64 {
    3.0
}
fn one() -> f64 {
    1.0
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Domain {
    pub id: String,
    pub label: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Sub {
    pub id: String,
    pub domain: String,
    pub label: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Slot {
    pub id: String,
    #[serde(default)]
    pub predicate: Option<String>,
    pub pid: String,
    /// entity | number | year | text
    pub kind: String,
    pub text: String,
    #[serde(default)]
    pub one: bool,
    #[serde(default)]
    pub normalize: bool,
    #[serde(default = "one")]
    pub scale: f64,
    #[serde(default)]
    pub offset: f64,
    #[serde(default)]
    pub decimals: usize,
    #[serde(default)]
    pub unit: String,
    #[serde(default)]
    pub sci: bool,
}

impl Slot {
    /// The governed predicate harvested facts carry.
    pub fn predicate(&self) -> &str {
        self.predicate.as_deref().unwrap_or(&self.id)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Class {
    pub id: String,
    pub sub: String,
    pub label: String,
    #[serde(default)]
    pub qid: Option<String>,
    #[serde(default)]
    pub pattern: Option<String>,
    #[serde(default, rename = "where")]
    pub where_: Option<String>,
    #[serde(default)]
    pub deep: bool,
    #[serde(default)]
    pub min_sitelinks: u32,
    pub slots: Vec<String>,
    #[serde(default)]
    pub texts: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Rule {
    pub id: String,
    /// inverse | symmetric | chain | constant | mode
    pub kind: String,
    /// class id, "prefix.*", or "*"
    pub class: String,
    #[serde(default)]
    pub slot: Option<String>,
    #[serde(default)]
    pub from_slot: Option<String>,
    /// inverse: only premises whose subject is a member of this class (id or prefix.*)
    #[serde(default)]
    pub from_class: Option<String>,
    #[serde(default)]
    pub path: Vec<String>,
    #[serde(default)]
    pub value: Option<String>,
    #[serde(default)]
    pub value_label: Option<String>,
    #[serde(default)]
    pub confidence: f64,
    #[serde(default)]
    pub min_share: f64,
    #[serde(default)]
    pub min_support: usize,
}

#[derive(Debug, Deserialize)]
struct SlotFile {
    slot: Vec<Slot>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Lattice {
    pub version: u32,
    pub title: String,
    #[serde(default)]
    pub slots_file: Option<String>,
    pub source: Source,
    pub domain: Vec<Domain>,
    pub sub: Vec<Sub>,
    pub class: Vec<Class>,
    #[serde(default)]
    pub rule: Vec<Rule>,
    #[serde(default)]
    pub slot: Vec<Slot>,
    #[serde(skip)]
    pub path: PathBuf,
}

impl Lattice {
    pub fn load(path: &Path) -> anyhow::Result<Lattice> {
        let text = std::fs::read_to_string(path).map_err(|e| anyhow::anyhow!("reading lattice {}: {e}", path.display()))?;
        let mut l: Lattice = toml::from_str(&text)?;
        if let Some(f) = &l.slots_file {
            let p = path.parent().unwrap_or(Path::new(".")).join(f);
            let t = std::fs::read_to_string(&p).map_err(|e| anyhow::anyhow!("reading slot library {}: {e}", p.display()))?;
            let sf: SlotFile = toml::from_str(&t)?;
            l.slot.extend(sf.slot);
        }
        l.path = path.to_path_buf();
        Ok(l)
    }

    pub fn slot(&self, id: &str) -> Option<&Slot> {
        self.slot.iter().find(|s| s.id == id)
    }

    pub fn class(&self, id: &str) -> Option<&Class> {
        self.class.iter().find(|c| c.id == id)
    }

    pub fn domain_of(&self, class: &Class) -> &str {
        self.sub.iter().find(|s| s.id == class.sub).map(|s| s.domain.as_str()).unwrap_or("")
    }

    /// Classes a rule (or a command-line filter) addresses: an id, "prefix.*", "*".
    pub fn classes_matching(&self, sel: &str) -> Vec<&Class> {
        self.class
            .iter()
            .filter(|c| match sel {
                "*" | "" => true,
                s if s.ends_with(".*") => c.id.starts_with(&s[..s.len() - 1]),
                s => c.id == s,
            })
            .collect()
    }

    /// `only` filters by domain, subdomain, class id or prefix (empty = all).
    pub fn selected(&self, only: &[String]) -> Vec<&Class> {
        self.class
            .iter()
            .filter(|c| {
                only.is_empty()
                    || only.iter().any(|o| {
                        o == &c.id
                            || o == &c.sub
                            || o == self.domain_of(c)
                            || (o.ends_with('*') && c.id.starts_with(o.trim_end_matches('*')))
                    })
            })
            .collect()
    }

    /// Rendering for a cell: the class override, else the slot's own text.
    pub fn text_for<'a>(&'a self, class: &'a Class, slot: &'a Slot) -> &'a str {
        class.texts.get(&slot.id).map(|s| s.as_str()).unwrap_or(&slot.text)
    }

    /// Every Wikidata item and property the lattice names (for live validation).
    pub fn referenced_ids(&self) -> (BTreeSet<String>, BTreeSet<String>) {
        let mut q = BTreeSet::new();
        let mut p = BTreeSet::new();
        let scan = |s: &str, q: &mut BTreeSet<String>, p: &mut BTreeSet<String>| {
            for tok in s.split(|c: char| !c.is_ascii_alphanumeric() && c != ':') {
                if let Some(id) = tok.strip_prefix("wd:") {
                    q.insert(id.to_string());
                } else if let Some(id) = tok.strip_prefix("wdt:") {
                    p.insert(id.to_string());
                }
            }
        };
        for c in &self.class {
            if let Some(x) = &c.qid {
                q.insert(x.clone());
            }
            for s in [&c.pattern, &c.where_].into_iter().flatten() {
                scan(s, &mut q, &mut p);
            }
        }
        for s in &self.slot {
            p.insert(s.pid.clone());
        }
        for r in &self.rule {
            if let Some(v) = &r.value {
                q.insert(v.clone());
            }
        }
        (q, p)
    }

    /// Structural validation: every reference resolves, ids are unique,
    /// every class says how its members are found.
    pub fn check(&self) -> Vec<String> {
        let mut errs = Vec::new();
        let mut dup = |kind: &str, ids: Vec<&str>| {
            let mut seen = BTreeSet::new();
            for id in ids {
                if !seen.insert(id) {
                    errs.push(format!("duplicate {kind} id '{id}'"));
                }
            }
        };
        dup("domain", self.domain.iter().map(|d| d.id.as_str()).collect());
        dup("subdomain", self.sub.iter().map(|d| d.id.as_str()).collect());
        dup("class", self.class.iter().map(|d| d.id.as_str()).collect());
        dup("slot", self.slot.iter().map(|d| d.id.as_str()).collect());
        dup("rule", self.rule.iter().map(|d| d.id.as_str()).collect());
        let domains: BTreeSet<&str> = self.domain.iter().map(|d| d.id.as_str()).collect();
        let subs: BTreeSet<&str> = self.sub.iter().map(|d| d.id.as_str()).collect();
        for s in &self.sub {
            if !domains.contains(s.domain.as_str()) {
                errs.push(format!("subdomain {} names unknown domain {}", s.id, s.domain));
            }
        }
        for s in &self.slot {
            if !matches!(s.kind.as_str(), "entity" | "number" | "year" | "text") {
                errs.push(format!("slot {} has unknown kind {}", s.id, s.kind));
            }
            if !s.pid.starts_with('P') || !s.pid[1..].chars().all(|c| c.is_ascii_digit()) {
                errs.push(format!("slot {} has malformed property id {}", s.id, s.pid));
            }
        }
        for c in &self.class {
            if !subs.contains(c.sub.as_str()) {
                errs.push(format!("class {} names unknown subdomain {}", c.id, c.sub));
            }
            if c.qid.is_none() && c.pattern.is_none() {
                errs.push(format!("class {} needs a qid or a membership pattern", c.id));
            }
            if let Some(p) = &c.pattern {
                if !p.contains("?s") {
                    errs.push(format!("class {} pattern does not bind ?s", c.id));
                }
            }
            for s in c.slots.iter().chain(c.texts.keys()) {
                if self.slot(s).is_none() {
                    errs.push(format!("class {} names unknown slot {s}", c.id));
                }
            }
        }
        for r in &self.rule {
            if let Some(fc) = &r.from_class {
                if self.classes_matching(fc).is_empty() {
                    errs.push(format!("rule {} from_class addresses no class ({fc})", r.id));
                }
            }
            if self.classes_matching(&r.class).is_empty() {
                errs.push(format!("rule {} addresses no class ({})", r.id, r.class));
            }
            let needs_slot = r.kind != "mode";
            for s in r.slot.iter().chain(r.from_slot.iter()).chain(r.path.iter()) {
                if self.slot(s).is_none() {
                    errs.push(format!("rule {} names unknown slot {s}", r.id));
                }
            }
            match r.kind.as_str() {
                "inverse" if r.from_slot.is_none() || r.from_class.is_none() => {
                    errs.push(format!("rule {} (inverse) needs from_slot and from_class", r.id))
                }
                "chain" if r.path.len() != 2 => errs.push(format!("rule {} (chain) needs a two-step path", r.id)),
                "constant" if r.value.is_none() => errs.push(format!("rule {} (constant) needs a value", r.id)),
                "mode" if r.min_share <= 0.5 || r.min_support == 0 => {
                    errs.push(format!("rule {} (mode) needs min_share > 0.5 and min_support", r.id))
                }
                "inverse" | "symmetric" | "chain" | "constant" | "mode" => {}
                k => errs.push(format!("rule {} has unknown kind {k}", r.id)),
            }
            if needs_slot && r.slot.is_none() {
                errs.push(format!("rule {} needs a slot", r.id));
            }
        }
        errs
    }

    /// Content digest of the structure (what a ledger node commits to).
    pub fn digest(&self) -> String {
        let j = serde_json::to_vec(self).unwrap_or_default();
        crate::util::sha256_hex(&j)
    }

    pub fn cells_per_member(&self) -> usize {
        self.class.iter().map(|c| c.slots.len()).sum()
    }
}

/// Register the structure (D3 writes only itself): the digest is ledgered so
/// every later expectation can name the exact lattice it came from.
pub fn register(store: &Store, l: &Lattice, operator: &str) -> anyhow::Result<String> {
    let digest = l.digest();
    let known: bool = store.read(|c| {
        Ok(c.query_row("SELECT 1 FROM lattice_structure WHERE digest=?1", [&digest], |_| Ok(()))
            .map(|_| true)
            .or_else(|e| if matches!(e, rusqlite::Error::QueryReturnedNoRows) { Ok(false) } else { Err(e) })?)
    })?;
    if !known {
        let summary = serde_json::json!({
            "title": l.title, "version": l.version, "digest": digest,
            "domains": l.domain.len(), "subdomains": l.sub.len(), "classes": l.class.len(),
            "slots": l.slot.len(), "rules": l.rule.len(),
        });
        store.write(|c| {
            c.execute(
                "INSERT OR IGNORE INTO lattice_structure(digest, summary, ts) VALUES(?1,?2,?3)",
                rusqlite::params![digest, summary.to_string(), crate::util::now_secs()],
            )?;
            Ok(())
        })?;
        store.ledger_append(operator, "lattice.register", "D3->D3 ALLOW", &summary.to_string(), "structure")?;
    }
    Ok(digest)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shipped_lattice_is_well_formed() {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("config/lattice/knowledge-lattice.toml");
        let l = Lattice::load(&p).unwrap();
        let errs = l.check();
        assert!(errs.is_empty(), "{errs:#?}");
        assert!(l.domain.len() >= 20 && l.class.len() >= 100, "{} domains {} classes", l.domain.len(), l.class.len());
        assert_eq!(l.digest(), Lattice::load(&p).unwrap().digest(), "digest is deterministic");
        assert_eq!(l.selected(&["geo".into()]).len(), l.class.iter().filter(|c| c.id.starts_with("geo.")).count());
    }
}
