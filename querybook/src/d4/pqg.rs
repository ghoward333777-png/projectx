//! Probable Question Generation and the Pre-Computed Answer Set
//! (QBF-C082..C084). Runs on the ingestion path after commit ("D5
//! pre-computes"): for the work's central concepts it asks the questions
//! readers will ask, answers them through the ordinary query path over the
//! whole work, and stores each answer with the FUIDs it relied on. A stored
//! answer is served only when it matches, every contributing record is
//! unrevised, and every cited record lies inside the reader's scope.

use super::query::{Citation, Line, Request, answer};
use crate::app::QueryBook;
use crate::d0::Trace;
use crate::d8::{Scope, precompute_scope};
use crate::util::{content_words, sha256_hex};
use rusqlite::params;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Serialize, Deserialize)]
pub struct Stored {
    pub lines: Vec<Line>,
    pub citations: Vec<Citation>,
}

pub fn qkey(q: &str) -> String {
    // "who is X" and "what is X" ask for the same identity records
    let qt = match super::query_type(q).as_str() {
        "who" | "what" | "which" | "whom" => "identity".to_string(),
        other => other.to_string(),
    };
    let mut w: Vec<String> = content_words(q);
    w.sort();
    w.dedup();
    format!("{qt}|{}", w.join(" "))
}

fn jaccard(a: &str, b: &str) -> f64 {
    let (ta, wa) = a.split_once('|').unwrap_or(("", a));
    let (tb, wb) = b.split_once('|').unwrap_or(("", b));
    if ta != tb {
        return 0.0;
    }
    let sa: BTreeSet<&str> = wa.split(' ').filter(|s| !s.is_empty()).collect();
    let sb: BTreeSet<&str> = wb.split(' ').filter(|s| !s.is_empty()).collect();
    if sa.is_empty() || sb.is_empty() {
        return 0.0;
    }
    sa.intersection(&sb).count() as f64 / sa.union(&sb).count() as f64
}

pub fn generate(qb: &QueryBook, work: &str, progress: &(dyn Fn(&str) + Sync)) -> anyhow::Result<usize> {
    let concepts: Vec<(String, String, String)> = qb.store.read(|c| {
        let mut st = c.prepare(
            "SELECT concept, MAX(label), MAX(kind) FROM aliases WHERE work=?1 AND freq>=5 GROUP BY concept ORDER BY MAX(freq) DESC, concept LIMIT 60",
        )?;
        let r = st.query_map([work], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?;
        Ok(r.collect::<Result<_, _>>()?)
    })?;
    let scope = precompute_scope(work);
    let floor = 2; // coverage: at least two contributing records
    let mut stored = 0;
    for (_concept, label, kind) in &concepts {
        let question = match kind.as_str() {
            "person" => format!("Who is {label}?"),
            "place" => format!("What is {label}?"),
            _ => format!("What is {label}?"),
        };
        let req = Request { mode: "ask".into(), query: question.clone(), ..Default::default() };
        let a = answer(qb, &scope, &req, Trace::default())?;
        if a.status != "answered" || a.served_from != "live" || a.citations.len() < floor {
            continue;
        }
        let fuids: Vec<String> = a.citations.iter().map(|c| c.fuid.clone()).collect();
        let max_pos = a.citations.iter().map(|c| c.pos).max().unwrap_or(0);
        let min_conf = a.citations.iter().map(|c| c.confidence).fold(1.0, f64::min);
        let body = serde_json::to_string(&Stored { lines: a.lines.clone(), citations: a.citations.clone() })?;
        let key = qkey(&question);
        qb.store.write(|c| {
            c.execute(
                "INSERT OR REPLACE INTO answer_units(work,qkey,question,answer,fuids,max_pos,min_conf,store_version,stale) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,0)",
                params![work, key, question, body, fuids.join(","), max_pos as i64, min_conf, qb.store.version()],
            )?;
            for f in &fuids {
                c.execute("INSERT OR IGNORE INTO answer_deps(fuid, work, qkey) VALUES(?1,?2,?3)", params![f, work, key])?;
            }
            Ok(())
        })?;
        stored += 1;
    }
    progress(&format!(
        "pre-computed {stored} answers (PRECOMPUTED_ANSWER, provenance: {})",
        sha256_hex(work.as_bytes())[..8].to_string()
    ));
    Ok(stored)
}

pub fn lookup(qb: &QueryBook, scope: &Scope, query: &str) -> anyhow::Result<Option<Stored>> {
    let Some((work, bound)) = scope.works().first().cloned() else { return Ok(None) };
    let key = qkey(query);
    let rows: Vec<(String, String, i64, String)> = qb.store.read(|c| {
        let mut st = c.prepare_cached("SELECT qkey, answer, max_pos, fuids FROM answer_units WHERE work=?1 AND stale=0")?;
        let r = st.query_map([&work], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?;
        Ok(r.collect::<Result<_, _>>()?)
    })?;
    let best = rows
        .into_iter()
        .map(|r| (if r.0 == key { 1.0 } else { jaccard(&r.0, &key) }, r))
        .filter(|(s, _)| *s >= qb.cfg.retrieval.question_match)
        .max_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal).then_with(|| b.1.0.cmp(&a.1.0)));
    let Some((_, (_, body, max_pos, fuids))) = best else { return Ok(None) };
    if (max_pos as u64) > bound {
        return Ok(None); // would reach past the reader's position: answer live instead
    }
    for f in fuids.split(',') {
        if qb.store.is_superseded(f)? {
            return Ok(None);
        }
    }
    let s: Stored = serde_json::from_str(&body)?;
    if !s.citations.iter().all(|c| scope.admits(Some(&c.work), c.pos)) {
        return Ok(None);
    }
    Ok(Some(s))
}
