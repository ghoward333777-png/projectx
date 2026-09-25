//! Governed predicate and type catalogue (Ontology Mesh vocabulary, QBF-C035;
//! Fact Unit Language, QBF-C292). A predicate not in the catalogue cannot be
//! asserted; a candidate that does not satisfy its predicate's definition is
//! refused at construction, not admitted and flagged.

use crate::d2::Store;
use crate::d2::{EdgeClass, FactUnit, Value};
use rusqlite::params;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

const BUILTIN: &str = include_str!("../../catalog/predicates.json");

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Predicate {
    pub id: String,
    pub label: String,
    #[serde(rename = "type")]
    pub type_ref: String,
    /// "concept" | "text" | "any"
    pub object: String,
    #[serde(default)]
    pub functional: bool,
    #[serde(default)]
    pub symmetric: bool,
    #[serde(default = "semantic")]
    pub edge: String,
    #[serde(default)]
    pub args: BTreeMap<String, String>,
    pub template: String,
    #[serde(default)]
    pub question: String,
    #[serde(default)]
    pub describe: String,
    #[serde(default)]
    pub inverse: Option<String>,
}

fn semantic() -> String {
    "semantic".into()
}

impl Predicate {
    pub fn edge_class(&self) -> EdgeClass {
        match self.edge.as_str() {
            "temporal" => EdgeClass::Temporal,
            "editorial" => EdgeClass::Editorial,
            _ => EdgeClass::Semantic,
        }
    }
}

#[derive(Deserialize)]
struct CatalogFile {
    types: Vec<String>,
    predicates: Vec<Predicate>,
}

#[derive(Clone, Debug)]
pub struct Catalog {
    pub types: BTreeSet<String>,
    pub predicates: BTreeMap<String, Predicate>,
}

impl Catalog {
    pub fn builtin() -> Catalog {
        let f: CatalogFile = serde_json::from_str(BUILTIN).expect("builtin catalogue parses");
        Catalog {
            types: f.types.into_iter().collect(),
            predicates: f.predicates.into_iter().map(|p| (p.id.clone(), p)).collect(),
        }
    }

    /// Built-in catalogue plus predicates registered by an operator (e.g.
    /// during a UFCS feed import), each recorded in the ledger.
    pub fn load(store: &Store) -> anyhow::Result<Catalog> {
        let mut c = Catalog::builtin();
        let extra: Vec<String> = store.read(|db| {
            let mut st = db.prepare("SELECT spec FROM predicates ORDER BY id")?;
            let rows = st.query_map([], |r| r.get::<_, String>(0))?;
            Ok(rows.collect::<Result<_, _>>()?)
        })?;
        for spec in extra {
            let p: Predicate = serde_json::from_str(&spec)?;
            c.types.insert(p.type_ref.clone());
            c.predicates.insert(p.id.clone(), p);
        }
        Ok(c)
    }

    pub fn get(&self, id: &str) -> Option<&Predicate> {
        self.predicates.get(id)
    }

    /// Operator registration of a new predicate (governed: immutable id,
    /// recorded with the registering identity in the provenance ledger).
    pub fn register(&mut self, store: &Store, p: Predicate, operator: &str) -> anyhow::Result<()> {
        if self.predicates.contains_key(&p.id) {
            return Ok(());
        }
        let spec = serde_json::to_string(&p)?;
        store.write(|db| {
            db.execute(
                "INSERT OR IGNORE INTO predicates(id, spec, registered_by, ts) VALUES(?1,?2,?3,?4)",
                params![p.id, spec, operator, crate::util::now_secs()],
            )?;
            Ok(())
        })?;
        store.ledger_append(operator, "catalogue.register-predicate", "D3->D3 ALLOW", &spec, "catalogue")?;
        self.types.insert(p.type_ref.clone());
        self.predicates.insert(p.id.clone(), p);
        Ok(())
    }

    /// Widen a registered predicate's argument slots (a ledgered catalogue
    /// revision). Existing records stay valid: slots are only ever added.
    pub fn extend_args(&mut self, store: &Store, id: &str, keys: &[String], operator: &str) -> anyhow::Result<bool> {
        let Some(p) = self.predicates.get_mut(id) else { return Ok(false) };
        let before = p.args.len();
        for k in keys {
            p.args.entry(k.clone()).or_insert_with(|| "any".into());
        }
        if p.args.len() == before {
            return Ok(false);
        }
        let spec = serde_json::to_string(&*p)?;
        store.write(|db| {
            db.execute("UPDATE predicates SET spec=?2 WHERE id=?1", params![id, spec])?;
            Ok(())
        })?;
        store.ledger_append(operator, "catalogue.extend-arguments", "D3->D3 ALLOW", &spec, "catalogue")?;
        Ok(true)
    }

    /// Construction-time validation against the machine definition.
    pub fn validate(&self, f: &FactUnit) -> Result<(), String> {
        let p = self.get(&f.atom.predicate).ok_or_else(|| format!("predicate '{}' not in catalogue", f.atom.predicate))?;
        if !self.types.contains(&f.type_ref) {
            return Err(format!("type '{}' not registered", f.type_ref));
        }
        if f.atom.subject.trim().is_empty() {
            return Err("empty subject".into());
        }
        let obj_ok = match (p.object.as_str(), &f.atom.object) {
            ("concept", Value::Concept(c)) => !c.is_empty(),
            ("concept", _) => false,
            ("text", Value::Text(t)) => !t.trim().is_empty(),
            ("text", _) => false,
            (_, Value::Text(t)) => !t.trim().is_empty(),
            _ => true,
        };
        if !obj_ok {
            return Err(format!("object kind does not match predicate '{}' ({})", p.id, p.object));
        }
        for k in f.atom.args.keys() {
            if !p.args.contains_key(k) {
                return Err(format!("argument '{k}' is forbidden for predicate '{}'", p.id));
            }
        }
        if f.fuid.is_empty() || f.fingerprint.is_empty() {
            return Err("record not sealed".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn builtin_catalogue_is_consistent() {
        let c = Catalog::builtin();
        assert!(c.predicates.len() >= 25);
        for p in c.predicates.values() {
            assert!(c.types.contains(&p.type_ref), "{} uses unregistered type {}", p.id, p.type_ref);
            assert!(p.template.contains("{o}") || p.template.contains("{s}"), "{} template", p.id);
        }
    }
}
