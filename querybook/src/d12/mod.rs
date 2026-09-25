//! D12 · External Integration: source connectors (QBF-C249 Source Connector
//! Registry). A connector only reaches outside and writes Fact Envelopes to
//! files; nothing it fetches enters the substrate except through the ordinary
//! D1 import (re-validation, safety gate, governed predicates, ledger).
pub mod drive;
pub mod lattice;
pub mod wikidata;
