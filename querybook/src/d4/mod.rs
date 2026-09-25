//! D4 · Retrieval & Response: answering a bounded query. The latency-critical
//! path; it performs no ingestion work and never calls an extraction engine.
pub mod attractor;
pub mod fql;
pub mod pqg;
pub mod query;

pub use query::{Answer, Request, answer};

pub(crate) fn query_type(q: &str) -> String {
    let w = crate::util::words(q);
    w.first().cloned().unwrap_or_default()
}
