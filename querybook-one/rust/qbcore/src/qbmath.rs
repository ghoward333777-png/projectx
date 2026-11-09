//! Port of apps/_core/qbmath.py: network memory (qbsynapse) and answer routing (qbdsn). Same constants, same order of
//! operations, same rounding, so every result equals the Python one exactly (tests/vectors.rs).

use crate::pyround::round;

pub const SYN_INIT: f64 = 0.20;
pub const SYN_ETA: f64 = 0.10;
pub const SYN_DEPRESS: f64 = 0.25;
pub const SYN_THETA: f64 = 0.30;
pub const SYN_DECAY_PER_DAY: f64 = 0.05;
pub const SYN_CONSOLIDATED_DECAY_PER_DAY: f64 = 0.01;
pub const SYN_CONSOLIDATE_AFTER: u32 = 20;
pub const SYN_PRUNE_BELOW: f64 = 0.05;
pub const SYN_PRUNE_IDLE_DAYS: f64 = 30.0;
pub const DSN_START: f64 = 0.5;
pub const DSN_THETA: f64 = 0.30;
pub const DSN_ETA: f64 = 0.10;
pub const DSN_SILENCE: f64 = 0.15;
pub const DSN_DRIFT: f64 = 0.002;
pub const DSN_EXPLORE_EVERY: u32 = 25;

pub fn syn_potentiate(s: f64) -> f64 { round(s + SYN_ETA * (1.0 - s), 4) }
pub fn syn_depress(s: f64) -> f64 { round(s - SYN_DEPRESS * s, 4) }

pub fn syn_fade(s: f64, days: f64, consolidated: bool) -> f64 {
    if days <= 0.0 {
        return s;
    }
    let rate = if consolidated { SYN_CONSOLIDATED_DECAY_PER_DAY } else { SYN_DECAY_PER_DAY };
    round(s * (1.0 - rate).powf(days), 4)
}

pub fn syn_threshold(good: u32, bad: u32) -> f64 {
    let tot = good + bad;
    if tot == 0 { SYN_THETA } else { round(SYN_THETA + 0.4 * bad as f64 / tot as f64, 3) }
}

pub fn syn_consolidated(good: u32, bad: u32) -> bool { good >= SYN_CONSOLIDATE_AFTER && good >= 4 * bad }
pub fn syn_prunable(s: f64, idle_days: f64) -> bool { s < SYN_PRUNE_BELOW && idle_days >= SYN_PRUNE_IDLE_DAYS }

pub fn dsn_recover(s: f64) -> f64 { if s < DSN_START { s + DSN_DRIFT * (DSN_START - s) } else { s } }
pub fn dsn_hit(s: f64) -> f64 { round(s + DSN_ETA * (1.0 - s), 4) }
pub fn dsn_miss(s: f64) -> f64 { round(s - DSN_SILENCE * s, 4) }
pub fn dsn_strong(s: f64) -> bool { s >= DSN_THETA }
