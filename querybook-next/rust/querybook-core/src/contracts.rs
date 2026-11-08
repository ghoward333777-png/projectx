//! Boundary types and traits — the Rust side of `querybook/core/model.py` and
//! `querybook/core/interfaces.py`. JSON shapes are specified in /contracts.
//! `Value` stands in for serde_json::Value until that dependency is enabled.

use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Array(Vec<Value>),
    Object(BTreeMap<String, Value>),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Document {
    pub id: String,
    pub coll: String,
    pub ts: i64,
    pub hash: String,
    pub data: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ChangeEvent {
    pub seq: i64,
    pub kind: String, // "add" | "update" | "remove"  (JSON field: "type")
    pub coll: String,
    pub id: String,
    pub ts: i64,
    pub title: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct RawItem {
    pub body: String,
    pub title: String,
    pub source: String,
    pub url: String,
    pub domain: Option<String>,
    pub fields: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct IngestResult {
    pub status: String, // "added" | "duplicate" | "rejected"
    pub domain: String,
    pub coll: String,
    pub id: String,
    pub reason: String,
}

#[derive(Debug)]
pub struct StoreError {
    pub code: String,
    pub message: String,
}

/// Same method set as the Python `DocumentStore` protocol.
pub trait DocumentStore {
    fn create(&self, coll: &str, data: BTreeMap<String, Value>, content_hash: Option<&str>, doc_id: Option<&str>)
        -> Result<(Document, bool), StoreError>;
    fn get(&self, coll: &str, doc_id: &str) -> Result<Option<Document>, StoreError>;
    fn update(&self, coll: &str, doc_id: &str, patch: BTreeMap<String, Value>) -> Result<Option<Document>, StoreError>;
    fn delete(&self, coll: &str, doc_id: &str) -> Result<bool, StoreError>;
    fn scan(&self, coll: &str) -> Box<dyn Iterator<Item = Document> + '_>;
    fn search(&self, coll: Option<&str>, text: &str, limit: usize) -> Result<Vec<Document>, StoreError>;
    fn changes_since(&self, seq: i64, limit: usize, coll: Option<&str>) -> Result<Vec<ChangeEvent>, StoreError>;
    fn latest_seq(&self) -> Result<i64, StoreError>;
    fn collections(&self) -> Result<BTreeMap<String, i64>, StoreError>;
}

/// Same method set as the Python `Source` protocol.
pub trait Source {
    fn name(&self) -> &str;
    fn kind(&self) -> &str;
    fn poll(&mut self) -> Result<Vec<RawItem>, String>;
}

/// A fact in one of the suite's bulk shards (`COMMONS/shards/<dataset>.sqlite`, table `facts`).
#[derive(Debug, Clone, PartialEq)]
pub struct ShardFact {
    pub fp: [u8; 16], // legacy::shard_fp(area, s, p, o)
    pub dataset: String,
    pub subject: String,
    pub predicate: String, // predicates.name for facts.p
    pub object: String,
    pub part: i64,
    pub row: i64,
}

/// A fact in the suite's shared database (`COMMONS/commons.sqlite`, table `facts`).
#[derive(Debug, Clone, PartialEq)]
pub struct CommonsFact {
    pub id: i64,
    pub fingerprint: String, // legacy::fingerprint(&[domain, subject, predicate, object])
    pub domain: String,
    pub subject: String,
    pub predicate: String,
    pub object: String,
    pub statement: Option<String>,
    pub origin_app: String,
    pub status: String,
    pub confidence: f64,
    pub created: String,
    pub updated: String,
}

/// Read-only access to the suite's store; same methods as Python's `LegacyStore`.
pub trait SuiteStore {
    fn facts_by_subject(&self, subject: &str, limit: usize) -> Result<Vec<ShardFact>, StoreError>;
    fn fact_exists(&self, area: &str, s: &str, p: &str, o: &str) -> Result<Vec<String>, StoreError>;
    fn commons_by_subject(&self, subject: &str, limit: usize) -> Result<Vec<CommonsFact>, StoreError>;
    fn commons_count(&self) -> Result<i64, StoreError>;
}
