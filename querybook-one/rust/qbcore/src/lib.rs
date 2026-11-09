//! QueryBook's formula math, ported from the Python suite.
//!
//! * `formulas` — every solution of the 35 STEM formulas (generated from apps/stem/science.py)
//! * `qbmath`   — network memory and answer routing (apps/_core/qbmath.py)
//! * `pyround`  — Python's `round(x, n)` exactly, so results match the suite bit for bit
//!
//! The same rules are proved in Lean (querybook-one/lean) and checked here against vectors the Python code produced.

pub mod formulas;
pub mod pyround;
pub mod qbmath;
