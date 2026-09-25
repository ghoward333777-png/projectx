//! D2 · Knowledge Substrate: custody of records and lineage.
pub mod fact;
pub mod index;
pub mod ledger;
pub mod store;

pub use fact::{
    Atom, Certification, Derivation, Edge, EdgeClass, Evidence, FactUnit, Narrative, ProvRef, SourceRef, Temporal, Value,
};
pub use store::Store;
