//! D14 · Learning & Assessment: assessment from grounding records only.
//! A flashcard derives from exactly one Fact Unit (QBF-C053); review
//! scheduling is spaced repetition (QBF-C277); a comprehension check scores a
//! choice against the record it was generated from (QBF-C275). A learner's
//! assessment record never reaches commerce (D14->D13 denied).

use crate::app::QueryBook;
use crate::d0::{Domain, Trace};
use crate::d2::{FactUnit, Value};
use crate::d4::fql::Fql;
use crate::d4::query::{Card, QuizItem, StudyCtx, retrieve};
use crate::d8::Scope;
use crate::util::{now_secs, sha256};
use rusqlite::{OptionalExtension, params};
use serde::Serialize;
use std::collections::BTreeMap;

const CARD_PREDICATES: &[&str] = &[
    "is_a",
    "relative_of",
    "married_to",
    "engaged_to",
    "lives_in",
    "defined_as",
    "member_of",
    "has_trait",
    "works_for",
    "located_in",
];

fn front(f: &FactUnit, catalog: &crate::d3::Catalog) -> Option<String> {
    let p = catalog.get(&f.atom.predicate)?;
    if p.question.is_empty() {
        return None;
    }
    Some(p.question.replace("{s}", &f.label(&f.atom.subject)))
}

/// Deterministic pseudo-random order keyed by record identity.
fn stable_key(seed: &str, s: &str) -> [u8; 32] {
    sha256(format!("{seed}|{s}").as_bytes())
}

pub fn study(ctx: &mut StudyCtx, scope: &Scope, mode: &str, chapter: Option<u32>, trace: &mut Trace) -> anyhow::Result<()> {
    let _ = trace.cross(Domain::D9, Domain::D14, mode);
    let qb = ctx.qb();
    if let (Some(ch), true) = (chapter, scope.spoiler_bounded()) {
        if let Some((start, _)) = ctx.chapter_bounds(ch) {
            if start > scope.marker() {
                ctx.set_status("beyond-position", "That chapter is ahead of where you are reading.");
                return Ok(());
            }
        }
    }
    let q = Fql {
        chapter: chapter.map(|c| c as u64),
        only_predicates: CARD_PREDICATES.iter().map(|s| s.to_string()).collect(),
        min_trust: qb.cfg.retrieval.admission_threshold,
        limit: 2000,
        ..Default::default()
    };
    let r = retrieve(qb, scope, &q)?;
    ctx.set_fql(r.fql.clone());
    let catalog = qb.catalog.read().unwrap().clone();
    let mut facts: Vec<FactUnit> =
        r.facts.into_iter().map(|(_, f)| f).filter(|f| f.atom.polarity && front(f, &catalog).is_some()).collect();
    facts
        .sort_by(|a, b| b.trust().partial_cmp(&a.trust()).unwrap_or(std::cmp::Ordering::Equal).then_with(|| a.fuid.cmp(&b.fuid)));
    // one card per subject+predicate, strongest record first
    let mut seen = std::collections::BTreeSet::new();
    facts.retain(|f| seen.insert((f.atom.subject.clone(), f.atom.predicate.clone())));
    facts.truncate(if mode == "quiz" { 60 } else { 24 });
    facts.sort_by_key(|f| stable_key("order", &f.fuid));

    if mode == "flashcards" {
        for f in facts.iter().take(12) {
            let Some(fr) = front(f, &catalog) else { continue };
            let back = ctx.render(f);
            let cite = ctx.cite(f);
            ctx.push_card(Card { fuid: f.fuid.clone(), front: fr, back, cite });
        }
        return Ok(());
    }

    // quiz: complete the statement; distractors are other records' objects
    // of the same predicate (so every option is itself grounded in the book)
    let mut pool: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for f in &facts {
        let o = match &f.atom.object {
            Value::Concept(c) => f.label(c),
            Value::Text(t) => t.clone(),
            _ => continue,
        };
        pool.entry(f.atom.predicate.clone()).or_default().push(o);
    }
    let mut asked = 0;
    for f in facts.iter() {
        let correct = match &f.atom.object {
            Value::Concept(c) => f.label(c),
            Value::Text(t) => t.clone(),
            _ => continue,
        };
        let mut distractors: Vec<String> = pool
            .get(&f.atom.predicate)
            .map(|v| v.iter().filter(|o| crate::util::canon_text(o) != crate::util::canon_text(&correct)).cloned().collect())
            .unwrap_or_default();
        distractors.sort_by_key(|d| stable_key(&f.fuid, d));
        distractors.dedup();
        if distractors.len() < 2 {
            continue;
        }
        let mut options: Vec<String> = distractors.into_iter().take(3).collect();
        options.push(correct.clone());
        options.sort_by_key(|o| stable_key(&f.fuid, o));
        let answer = options.iter().position(|o| *o == correct).unwrap_or(0);
        let rendered = ctx.render(f);
        let prompt = rendered.replacen(correct.trim_end_matches('.'), "_____", 1);
        if !prompt.contains("_____") {
            continue;
        }
        let cite = ctx.cite(f);
        ctx.push_quiz(QuizItem { prompt, options, answer, cite });
        asked += 1;
        if asked >= 8 {
            break;
        }
    }
    Ok(())
}

// ---- spaced repetition (SM-2 family) --------------------------------------

#[derive(Serialize)]
pub struct Review {
    pub fuid: String,
    pub ease: f64,
    pub interval_days: f64,
    pub reps: i64,
    pub due: i64,
}

/// QBF-C277: next interval = prior interval scaled by the ease factor where
/// recall quality clears the floor (3), else reset to one day.
pub fn schedule(ease: f64, interval: f64, reps: i64, quality: u8) -> (f64, f64, i64) {
    let q = quality.min(5) as f64;
    let ease = (ease + (0.1 - (5.0 - q) * (0.08 + (5.0 - q) * 0.02))).max(1.3);
    if quality < 3 {
        return (ease, 1.0, 0);
    }
    let interval = match reps {
        0 => 1.0,
        1 => 6.0,
        _ => (interval * ease).round(),
    };
    (ease, interval, reps + 1)
}

pub fn review(qb: &QueryBook, user_id: i64, work: &str, fuid: &str, quality: u8) -> anyhow::Result<Review> {
    let cur: Option<(f64, f64, i64)> = qb.store.read(|c| {
        Ok(c.query_row("SELECT ease, interval_days, reps FROM cards WHERE user_id=?1 AND fuid=?2", params![user_id, fuid], |r| {
            Ok((r.get(0)?, r.get(1)?, r.get(2)?))
        })
        .optional()?)
    })?;
    let (ease, interval, reps) = cur.unwrap_or((2.5, 0.0, 0));
    let (e, i, r) = schedule(ease, interval, reps, quality);
    let due = now_secs() + (i * 86400.0) as i64;
    qb.store.write(|c| {
        c.execute(
            "INSERT OR REPLACE INTO cards(user_id,fuid,work,ease,interval_days,reps,due) VALUES(?1,?2,?3,?4,?5,?6,?7)",
            params![user_id, fuid, work, e, i, r, due],
        )?;
        Ok(())
    })?;
    Ok(Review { fuid: fuid.into(), ease: e, interval_days: i, reps: r, due })
}

/// QBF-C278 learner progress: mastery = recalled / attempted per work.
#[derive(Serialize)]
pub struct Mastery {
    pub cards: i64,
    pub mastered: i64,
    pub due_now: i64,
}

pub fn mastery(qb: &QueryBook, user_id: i64, work: &str) -> anyhow::Result<Mastery> {
    qb.store.read(|c| {
        Ok(c.query_row(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN reps>=2 THEN 1 ELSE 0 END),0), COALESCE(SUM(CASE WHEN due<=?3 THEN 1 ELSE 0 END),0) FROM cards WHERE user_id=?1 AND work=?2",
            params![user_id, work, now_secs()],
            |r| Ok(Mastery { cards: r.get(0)?, mastered: r.get(1)?, due_now: r.get(2)? }),
        )?)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn spaced_repetition_rule() {
        let (e, i, r) = schedule(2.5, 0.0, 0, 5);
        assert_eq!((i, r), (1.0, 1));
        let (e2, i2, r2) = schedule(e, i, r, 4);
        assert_eq!((i2, r2), (6.0, 2));
        let (_, i3, _) = schedule(e2, i2, r2, 4);
        assert!(i3 > 6.0);
        let (_, reset, reps) = schedule(e2, i2, r2, 1);
        assert_eq!((reset, reps), (1.0, 0));
    }
}
