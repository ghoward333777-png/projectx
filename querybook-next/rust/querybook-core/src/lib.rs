//! QueryBook core, Rust edition.
//!
//! Mirrors `querybook/core` module for module. The Python implementation is the
//! reference; `contracts/golden_text.tsv` and the lexer tests pin both sides to
//! the same behaviour so a module can be swapped without changing any output.

pub mod contracts;
pub mod fql_lexer;
pub mod legacy;
pub mod text;
