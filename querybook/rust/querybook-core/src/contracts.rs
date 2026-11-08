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
