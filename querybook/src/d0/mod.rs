//! D0 · Prime Directive: the vertical governance domain.
pub mod context_lock;
pub mod matrix;
pub mod safety;

pub use matrix::{CommitPermit, Crossing, Domain, Permission, Trace, commit_permit, cross, permission};
pub use safety::SafetyClass;
