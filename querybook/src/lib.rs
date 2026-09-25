//! QueryBook prototype engine. Modules are organized by the fifteen-domain
//! partition of the QueryBook Feature Registry (v65); cross-domain calls go
//! through the D0 transfer matrix.

pub mod app;
pub mod config;
pub mod d0;
pub mod d1;
pub mod d14;
pub mod d2;
pub mod d3;
pub mod d4;
pub mod d7;
pub mod d8;
pub mod d9;
pub mod util;
