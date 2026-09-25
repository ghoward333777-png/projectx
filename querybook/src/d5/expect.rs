//! Expectations over the knowledge lattice (QBF-C102 Predictive Level
//! Registration): every lattice cell — a class member and one of its slots —
//! is predicted before it is harvested, and every prediction is later
//! confirmed or refuted by admitted records.
//!
//! Levels, lowest first:
//!   conceptual  an instance attribute given its concept: the presence of a
//!               slot at the class's census fill rate, and the class-mode
//!               value where a class's observed values concentrate on one
//!   invariant   a regularity of the world model: the lattice rules
//!               (inverse, symmetric, chain, constant)
//!   engine      an extraction engine's recalled value (Claude or a
//!               self-hosted model), always the least trusted
//!
//! Induction may not write (D5): expectations live in their own tables and
//! never enter the fact store. A refutation is attributed to the lowest level
//! that explains it (QBF-C103/C104); one that no level explains is retained
//! as a finding and revises nothing (QBF-C105). Per-band calibration gaps are
//! raised as proposals to a named reviewer, never applied (QBF-C101).

use crate::app::QueryBook;
use crate::d2::Value;
use crate::d3::lattice::{Lattice, Rule, Slot};
use rusqlite::{OptionalExtension, params};
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet, HashMap};

/// QBF-C101: the measurement's own parameters are held fixed — the mechanism
/// cannot adjust the terms on which it is judged.
pub const CALIBRATION_TOLERANCE: f64 = 0.10;
pub const CALIBRATION_MIN_BAND: usize = 20;
/// Weight of a rule's stated confidence as a Beta prior (pseudo-observations).
const PRIOR_WEIGHT: f64 = 10.0;
/// Repeated unattributed refutations of one basis surface as a pattern (C105).
const PATTERN_MIN: usize = 5;

pub fn ensure_tables(qb: &QueryBook) -> anyhow::Result<()> {
    qb.store.write(|c| {
        c.execute_batch(
            "CREATE TABLE IF NOT EXISTS lattice_structure(digest TEXT PRIMARY KEY, summary TEXT NOT NULL, ts INTEGER NOT NULL);
             CREATE TABLE IF NOT EXISTS lattice_members(class TEXT NOT NULL, qid TEXT NOT NULL, label TEXT NOT NULL, sitelinks INTEGER NOT NULL, PRIMARY KEY(class, qid)) WITHOUT ROWID;
             CREATE TABLE IF NOT EXISTS lattice_census(class TEXT PRIMARY KEY, members INTEGER NOT NULL, enumerated INTEGER NOT NULL, status TEXT NOT NULL, ts INTEGER NOT NULL);
             CREATE TABLE IF NOT EXISTS lattice_fill(class TEXT NOT NULL, slot TEXT NOT NULL, filled INTEGER NOT NULL, ts INTEGER NOT NULL, PRIMARY KEY(class, slot)) WITHOUT ROWID;
             CREATE TABLE IF NOT EXISTS lattice_checked(class TEXT NOT NULL, slot TEXT NOT NULL, qid TEXT NOT NULL, n INTEGER NOT NULL, ts INTEGER NOT NULL, PRIMARY KEY(class, slot, qid)) WITHOUT ROWID;
             CREATE TABLE IF NOT EXISTS lattice_rules(rule TEXT PRIMARY KEY, alpha REAL NOT NULL, beta REAL NOT NULL, confirmed INTEGER NOT NULL, refuted INTEGER NOT NULL, ts INTEGER NOT NULL);
             CREATE TABLE IF NOT EXISTS lattice_findings(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, detail TEXT NOT NULL, ts INTEGER NOT NULL, UNIQUE(kind, subject));
             CREATE TABLE IF NOT EXISTS expectations(
                id INTEGER PRIMARY KEY, level TEXT NOT NULL, basis TEXT NOT NULL, class TEXT NOT NULL, slot TEXT NOT NULL,
                subject TEXT NOT NULL, subject_label TEXT NOT NULL, value TEXT NOT NULL, value_label TEXT NOT NULL,
                confidence REAL NOT NULL, premise TEXT NOT NULL DEFAULT 'single', status TEXT NOT NULL DEFAULT 'open',
                observed TEXT NOT NULL DEFAULT '', attributed TEXT NOT NULL DEFAULT '', lattice TEXT NOT NULL, ts INTEGER NOT NULL,
                UNIQUE(basis, class, slot, subject, value));
             CREATE INDEX IF NOT EXISTS expectations_cell ON expectations(class, slot, subject);",
        )?;
        Ok(())
    })
}

// ---------------------------------------------------------------- observations

#[derive(Clone, Debug)]
pub struct Obs {
    /// "Q90" for an item, the canonical literal otherwise
    pub key: String,
    pub label: String,
    pub contested: bool,
}

/// Admitted facts about lattice subjects, keyed by (subject Q-id, predicate).
/// Only records that could ground an answer count: superseded, revoked and
/// unverified records are excluded exactly as retrieval excludes them.
#[derive(Default)]
pub struct Observations {
    map: HashMap<(String, String), Vec<Obs>>,
    pub labels: HashMap<String, String>,
    pub records: usize,
}

fn obs_key(v: &Value) -> Option<String> {
    match v {
        Value::Concept(c) => Some(c.strip_prefix("wd:").unwrap_or(c).to_string()),
        Value::Number { value, .. } => Some(canonical_number(*value)),
        Value::Text(t) | Value::Date(t) => Some(t.trim().to_string()),
        Value::Bool(b) => Some(b.to_string()),
    }
}

fn canonical_number(v: f64) -> String {
    if v.fract() == 0.0 && v.abs() < 1e15 { format!("{}", v as i64) } else { format!("{v}") }
}

impl Observations {
    pub fn load(qb: &QueryBook, predicates: &BTreeSet<String>) -> anyhow::Result<Observations> {
        use tantivy::query::{BooleanQuery, Occur, Query, TermQuery};
        use tantivy::schema::IndexRecordOption;
        let ix = &qb.store.index;
        let mut out = Observations::default();
        for p in predicates {
            let term = |field, v: &str| -> Box<dyn Query> {
                Box::new(TermQuery::new(tantivy::Term::from_field_text(field, v), IndexRecordOption::Basic))
            };
            let mut clauses: Vec<(Occur, Box<dyn Query>)> = vec![(
                Occur::Must,
                Box::new(BooleanQuery::new(vec![
                    (Occur::Should, term(ix.f.predicate, &format!("ufcs:{p}"))),
                    (Occur::Should, term(ix.f.predicate, p)),
                ])),
            )];
            for s in ["superseded", "revoked", "unverified"] {
                clauses.push((Occur::MustNot, term(ix.f.status, s)));
            }
            let hits = ix.search(&BooleanQuery::new(clauses), 50_000_000)?;
            let mut fuids: Vec<String> = hits.into_iter().map(|h| h.1).collect();
            fuids.sort();
            for chunk in fuids.chunks(5000) {
                for f in qb.store.get_many(chunk)? {
                    let Some(subj) = f.atom.subject.strip_prefix("wd:") else { continue };
                    let Some(key) = obs_key(&f.atom.object) else { continue };
                    out.records += 1;
                    out.labels.entry(subj.to_string()).or_insert_with(|| f.label(&f.atom.subject));
                    let label = match &f.atom.object {
                        Value::Concept(c) => {
                            let l = f.label(c);
                            out.labels.entry(key.clone()).or_insert_with(|| l.clone());
                            l
                        }
                        other => other.canonical(),
                    };
                    let e = out.map.entry((subj.to_string(), p.clone())).or_default();
                    if !e.iter().any(|o| o.key == key) {
                        e.push(Obs { key, label, contested: f.status() == "contested" });
                    }
                }
            }
        }
        for v in out.map.values_mut() {
            v.sort_by(|a, b| a.key.cmp(&b.key));
        }
        Ok(out)
    }

    pub fn get(&self, subject: &str, predicate: &str) -> &[Obs] {
        self.map.get(&(subject.to_string(), predicate.to_string())).map(|v| v.as_slice()).unwrap_or(&[])
    }

    /// Every (subject, values) pair observed for a predicate, in a stable order.
    pub fn with_predicate(&self, predicate: &str) -> Vec<(&str, &[Obs])> {
        let mut v: Vec<(&str, &[Obs])> =
            self.map.iter().filter(|((_, p), _)| p == predicate).map(|((s, _), o)| (s.as_str(), o.as_slice())).collect();
        v.sort_by(|a, b| a.0.cmp(b.0));
        v
    }
}

pub fn lattice_predicates(l: &Lattice) -> BTreeSet<String> {
    l.slot.iter().map(|s| s.predicate().to_string()).collect()
}

// ---------------------------------------------------------------- members

pub fn members(qb: &QueryBook, class: &str) -> anyhow::Result<Vec<(String, String)>> {
    qb.store.read(|c| {
        let mut st = c.prepare("SELECT qid, label FROM lattice_members WHERE class=?1 ORDER BY sitelinks DESC, qid")?;
        let r = st.query_map([class], |r| Ok((r.get(0)?, r.get(1)?)))?.collect::<Result<Vec<_>, _>>()?;
        Ok(r)
    })
}

fn member_index(qb: &QueryBook) -> anyhow::Result<HashMap<String, Vec<String>>> {
    qb.store.read(|c| {
        let mut st = c.prepare("SELECT qid, class FROM lattice_members ORDER BY qid, class")?;
        let mut m: HashMap<String, Vec<String>> = HashMap::new();
        for r in st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))? {
            let (q, c) = r?;
            m.entry(q).or_default().push(c);
        }
        Ok(m)
    })
}

pub fn checked(qb: &QueryBook) -> anyhow::Result<HashMap<(String, String, String), i64>> {
    qb.store.read(|c| {
        let mut st = c.prepare("SELECT class, slot, qid, n FROM lattice_checked")?;
        let mut m = HashMap::new();
        for r in st.query_map([], |r| Ok(((r.get(0)?, r.get(1)?, r.get(2)?), r.get(3)?)))? {
            let (k, n) = r?;
            m.insert(k, n);
        }
        Ok(m)
    })
}

fn rule_posterior(qb: &QueryBook, r: &Rule) -> anyhow::Result<f64> {
    let prior = r.confidence.clamp(0.01, 0.99);
    let row: Option<(f64, f64)> = qb.store.read(|c| {
        Ok(c.query_row("SELECT alpha, beta FROM lattice_rules WHERE rule=?1", [&r.id], |x| Ok((x.get(0)?, x.get(1)?)))
            .optional()?)
    })?;
    Ok(match row {
        Some((a, b)) if a + b > 0.0 => a / (a + b),
        _ => prior,
    })
}

// ---------------------------------------------------------------- expect

#[derive(Debug, Default, Serialize)]
pub struct ExpectReport {
    pub lattice: String,
    pub classes_with_members: usize,
    pub members: usize,
    pub presence_cells: usize,
    pub value_predictions: usize,
    /// predictions for cells nothing has been observed for yet (true forecasts)
    pub forward: usize,
    /// predictions for cells already observed (measured immediately)
    pub retrospective: usize,
    pub by_basis: BTreeMap<String, usize>,
    pub observations: usize,
}

struct Row {
    level: &'static str,
    basis: String,
    class: String,
    slot: String,
    subject: String,
    subject_label: String,
    value: String,
    value_label: String,
    confidence: f64,
    premise: &'static str,
}

/// Regenerate the conceptual and invariant expectations (engine predictions
/// are kept: they cost money and are only ever added). Deterministic in the
/// lattice, the members, the census and the admitted facts.
pub fn expect(qb: &QueryBook, l: &Lattice, digest: &str) -> anyhow::Result<ExpectReport> {
    let obs = Observations::load(qb, &lattice_predicates(l))?;
    let member_of = member_index(qb)?;
    let fill: HashMap<(String, String), i64> = qb.store.read(|c| {
        let mut st = c.prepare("SELECT class, slot, filled FROM lattice_fill")?;
        let r = st.query_map([], |r| Ok(((r.get(0)?, r.get(1)?), r.get(2)?)))?.collect::<Result<HashMap<_, _>, _>>()?;
        Ok(r)
    })?;
    let census: HashMap<String, i64> = qb.store.read(|c| {
        let mut st = c.prepare("SELECT class, members FROM lattice_census")?;
        let r = st.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?.collect::<Result<HashMap<_, _>, _>>()?;
        Ok(r)
    })?;
    let mut rep = ExpectReport { lattice: digest.to_string(), observations: obs.records, ..Default::default() };
    let mut rows: Vec<Row> = Vec::new();
    let mut labels: HashMap<String, String> = HashMap::new();

    for class in &l.class {
        let mem = members(qb, &class.id)?;
        if mem.is_empty() {
            continue;
        }
        rep.classes_with_members += 1;
        rep.members += mem.len();
        for (q, lab) in &mem {
            labels.insert(q.clone(), lab.clone());
        }
        // fill counts are taken over the enumerated members
        let _ = census.get(&class.id);
        let total = mem.len().max(1) as f64;
        for sid in &class.slots {
            let slot = l.slot(sid).unwrap();
            // conceptual: presence at the class's census fill rate
            let rate = fill.get(&(class.id.clone(), sid.clone())).map(|&n| (n as f64 / total).min(1.0));
            if let Some(rate) = rate {
                for (q, lab) in &mem {
                    rows.push(Row {
                        level: "conceptual",
                        basis: "census".into(),
                        class: class.id.clone(),
                        slot: sid.clone(),
                        subject: q.clone(),
                        subject_label: lab.clone(),
                        value: String::new(),
                        value_label: String::new(),
                        confidence: (rate * 1000.0).round() / 1000.0,
                        premise: "single",
                    });
                }
            }
            let _ = slot;
        }
    }
    let label_of = |q: &str| labels.get(q).cloned().or_else(|| obs.labels.get(q).cloned()).unwrap_or_else(|| q.to_string());

    for rule in &l.rule {
        let classes = l.classes_matching(&rule.class);
        let conf = (rule_posterior(qb, rule)? * 1000.0).round() / 1000.0;
        let before = rows.len();
        match rule.kind.as_str() {
            "inverse" => {
                let slot = l.slot(rule.slot.as_deref().unwrap()).unwrap();
                let from = l.slot(rule.from_slot.as_deref().unwrap()).unwrap();
                let targets: BTreeSet<&str> = classes.iter().map(|c| c.id.as_str()).collect();
                let sources: Option<BTreeSet<&str>> =
                    rule.from_class.as_deref().map(|fc| l.classes_matching(fc).iter().map(|c| c.id.as_str()).collect());
                for (x, ys) in obs.with_predicate(from.predicate()) {
                    if let Some(src) = &sources {
                        if !member_of.get(x).map(|cs| cs.iter().any(|c| src.contains(c.as_str()))).unwrap_or(false) {
                            continue;
                        }
                    }
                    for y in ys {
                        for c in member_of.get(&y.key).into_iter().flatten().filter(|c| targets.contains(c.as_str())) {
                            rows.push(Row {
                                level: "invariant",
                                basis: rule.id.clone(),
                                class: c.clone(),
                                slot: slot.id.clone(),
                                subject: y.key.clone(),
                                subject_label: label_of(&y.key),
                                value: x.to_string(),
                                value_label: label_of(x),
                                confidence: conf,
                                premise: if ys.len() > 1 && from.one { "ambiguous" } else { "single" },
                            });
                        }
                    }
                }
            }
            "symmetric" => {
                let slot = l.slot(rule.slot.as_deref().unwrap()).unwrap();
                let targets: BTreeSet<&str> = classes.iter().map(|c| c.id.as_str()).collect();
                for (x, ys) in obs.with_predicate(slot.predicate()) {
                    if !member_of.get(x).map(|cs| cs.iter().any(|c| targets.contains(c.as_str()))).unwrap_or(false) {
                        continue;
                    }
                    for y in ys {
                        for c in member_of.get(&y.key).into_iter().flatten().filter(|c| targets.contains(c.as_str())) {
                            rows.push(Row {
                                level: "invariant",
                                basis: rule.id.clone(),
                                class: c.clone(),
                                slot: slot.id.clone(),
                                subject: y.key.clone(),
                                subject_label: label_of(&y.key),
                                value: x.to_string(),
                                value_label: label_of(x),
                                confidence: conf,
                                premise: "single",
                            });
                        }
                    }
                }
            }
            "chain" => {
                let slot = l.slot(rule.slot.as_deref().unwrap()).unwrap();
                let (a, b) = (l.slot(&rule.path[0]).unwrap(), l.slot(&rule.path[1]).unwrap());
                for class in &classes {
                    if !class.slots.contains(&slot.id) {
                        continue;
                    }
                    for (x, xl) in members(qb, &class.id)? {
                        let ys = obs.get(&x, a.predicate());
                        let mut seen = BTreeSet::new();
                        for y in ys {
                            let zs = obs.get(&y.key, b.predicate());
                            for z in zs {
                                if !seen.insert(z.key.clone()) {
                                    continue;
                                }
                                rows.push(Row {
                                    level: "invariant",
                                    basis: rule.id.clone(),
                                    class: class.id.clone(),
                                    slot: slot.id.clone(),
                                    subject: x.clone(),
                                    subject_label: xl.clone(),
                                    value: z.key.clone(),
                                    value_label: z.label.clone(),
                                    confidence: conf,
                                    premise: if ys.len() > 1 || zs.len() > 1 { "ambiguous" } else { "single" },
                                });
                            }
                        }
                    }
                }
            }
            "constant" => {
                let slot = l.slot(rule.slot.as_deref().unwrap()).unwrap();
                let v = rule.value.clone().unwrap();
                let vl = rule.value_label.clone().unwrap_or_else(|| v.clone());
                for class in &classes {
                    for (x, xl) in members(qb, &class.id)? {
                        rows.push(Row {
                            level: "invariant",
                            basis: rule.id.clone(),
                            class: class.id.clone(),
                            slot: slot.id.clone(),
                            subject: x,
                            subject_label: xl,
                            value: v.clone(),
                            value_label: vl.clone(),
                            confidence: conf,
                            premise: "single",
                        });
                    }
                }
            }
            "mode" => {
                // conceptual level: a class whose observed values concentrate
                // on one value predicts it for the members not yet observed
                for class in &classes {
                    let mem = members(qb, &class.id)?;
                    for sid in &class.slots {
                        let slot = l.slot(sid).unwrap();
                        if slot.kind == "number" {
                            continue;
                        }
                        let mut counts: BTreeMap<&str, (usize, &str)> = BTreeMap::new();
                        let mut support = 0usize;
                        let mut unobserved = Vec::new();
                        for (x, xl) in &mem {
                            let o = obs.get(x, slot.predicate());
                            if o.is_empty() {
                                unobserved.push((x, xl));
                                continue;
                            }
                            support += 1;
                            for v in o {
                                let e = counts.entry(v.key.as_str()).or_insert((0, v.label.as_str()));
                                e.0 += 1;
                            }
                        }
                        let Some((&top, &(n, top_label))) = counts.iter().max_by(|a, b| a.1.0.cmp(&b.1.0).then(b.0.cmp(a.0)))
                        else {
                            continue;
                        };
                        let share = n as f64 / support.max(1) as f64;
                        if support < rule.min_support || share < rule.min_share {
                            continue;
                        }
                        // Laplace-smoothed share is the stated confidence
                        let c = ((n as f64 + 1.0) / (support as f64 + 2.0) * 1000.0).round() / 1000.0;
                        for (x, xl) in unobserved {
                            rows.push(Row {
                                level: "conceptual",
                                basis: format!("{}:{}", rule.id, class.id),
                                class: class.id.clone(),
                                slot: sid.clone(),
                                subject: x.clone(),
                                subject_label: xl.clone(),
                                value: top.to_string(),
                                value_label: top_label.to_string(),
                                confidence: c,
                                premise: "single",
                            });
                        }
                    }
                }
            }
            _ => {}
        }
        *rep.by_basis.entry(rule.id.clone()).or_insert(0) += rows.len() - before;
    }

    // a prediction for a cell already observed is measured at once; the
    // rest are forecasts the harvest will confirm or refute
    for r in rows.iter().filter(|r| !r.value.is_empty()) {
        rep.value_predictions += 1;
        let pred = l.slot(&r.slot).map(|s| s.predicate().to_string()).unwrap_or_default();
        if obs.get(&r.subject, &pred).is_empty() {
            rep.forward += 1;
        } else {
            rep.retrospective += 1;
        }
    }
    rep.presence_cells = rows.iter().filter(|r| r.value.is_empty()).count();

    let ts = crate::util::now_secs();
    qb.store.write(|c| {
        let tx = c.unchecked_transaction()?;
        tx.execute("DELETE FROM expectations WHERE level IN ('conceptual','invariant')", [])?;
        {
            let mut st = tx.prepare(
                "INSERT OR IGNORE INTO expectations(level,basis,class,slot,subject,subject_label,value,value_label,confidence,premise,lattice,ts)
                 VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)",
            )?;
            for r in &rows {
                st.execute(params![
                    r.level,
                    r.basis,
                    r.class,
                    r.slot,
                    r.subject,
                    r.subject_label,
                    r.value,
                    r.value_label,
                    r.confidence,
                    r.premise,
                    digest,
                    ts
                ])?;
            }
        }
        tx.commit()?;
        Ok(())
    })?;
    Ok(rep)
}

// ---------------------------------------------------------------- confirm

#[derive(Debug, Default, Serialize)]
pub struct ConfirmReport {
    pub evaluated: usize,
    pub status: BTreeMap<String, usize>,
    pub attributed: BTreeMap<String, usize>,
    pub rules: Vec<RuleStat>,
    pub calibration: Vec<Band>,
    pub findings: Vec<String>,
}

#[derive(Debug, Default, Serialize, Clone)]
pub struct RuleStat {
    pub basis: String,
    pub level: String,
    pub predictions: usize,
    pub confirmed: usize,
    pub refuted: usize,
    pub open: usize,
    pub precision: Option<f64>,
    pub reliability: f64,
}

#[derive(Debug, Default, Serialize, Clone)]
pub struct Band {
    pub band: String,
    pub decided: usize,
    pub mean_confidence: f64,
    pub realized: f64,
    pub gap: f64,
    pub finding: bool,
}

fn matches(slot: &Slot, predicted: &str, obs: &Obs) -> bool {
    if let Some(label) = predicted.strip_prefix('~') {
        // an engine recalled a name, not an identifier: compare normalized names
        return crate::util::alias_key(label) == crate::util::alias_key(&obs.label);
    }
    match slot.kind.as_str() {
        "number" => match (predicted.parse::<f64>(), obs.key.parse::<f64>()) {
            (Ok(a), Ok(b)) => (a - b).abs() <= 0.01 * b.abs().max(1e-12),
            _ => false,
        },
        "text" | "year" => predicted.trim().eq_ignore_ascii_case(obs.key.trim()),
        _ => predicted == obs.key,
    }
}

/// Evaluate every expectation against the admitted facts, attribute each
/// refutation, re-derive rule reliabilities and the calibration bands.
pub fn confirm(qb: &QueryBook, l: &Lattice) -> anyhow::Result<ConfirmReport> {
    let obs = Observations::load(qb, &lattice_predicates(l))?;
    let chk = checked(qb)?;
    let rows: Vec<(i64, String, String, String, String, String, String, f64, String)> = qb.store.read(|c| {
        let mut st =
            c.prepare("SELECT id, level, basis, class, slot, subject, value, confidence, premise FROM expectations ORDER BY id")?;
        let r = st
            .query_map([], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?, r.get(6)?, r.get(7)?, r.get(8)?))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(r)
    })?;
    let mut rep = ConfirmReport::default();
    let mut updates: Vec<(i64, &'static str, String, String)> = Vec::with_capacity(rows.len());
    let mut stats: BTreeMap<String, RuleStat> = BTreeMap::new();
    let mut decided: Vec<(f64, bool)> = Vec::new();
    let mut unattributed: BTreeMap<String, usize> = BTreeMap::new();
    for (id, level, basis, class, sid, subject, value, conf, premise) in &rows {
        let Some(slot) = l.slot(sid) else { continue };
        let o = obs.get(subject, slot.predicate());
        let was_checked = chk.get(&(class.clone(), sid.clone(), subject.clone())).copied();
        let observed = o.iter().map(|x| x.label.clone()).collect::<Vec<_>>().join(" | ");
        rep.evaluated += 1;
        let (status, attributed): (&'static str, String) = if value.is_empty() {
            match (o.is_empty(), was_checked) {
                (false, _) => ("filled", String::new()),
                (true, Some(0)) => ("absent", String::new()),
                _ => ("open", String::new()),
            }
        } else if o.is_empty() {
            (if was_checked == Some(0) { "unverifiable" } else { "open" }, String::new())
        } else if o.iter().any(|x| matches(slot, value, x)) {
            ("confirmed", String::new())
        } else {
            // QBF-C103/C104: the lowest level that accounts for the error takes it
            let a = if o.iter().any(|x| x.contested) {
                "unattributed" // the observation itself is in dispute: revise nothing (C105)
            } else if premise == "ambiguous" {
                "conceptual" // a multi-valued premise cell, not the regularity
            } else {
                level_name(level)
            };
            ("refuted", a.to_string())
        };
        if !value.is_empty() {
            let key = if level == "conceptual" && basis != "census" {
                basis.split(':').next().unwrap_or(basis).to_string()
            } else {
                basis.clone()
            };
            let s =
                stats.entry(key.clone()).or_insert_with(|| RuleStat { basis: key, level: level.clone(), ..Default::default() });
            s.predictions += 1;
            match status {
                "confirmed" => {
                    s.confirmed += 1;
                    decided.push((*conf, true));
                }
                "refuted" => {
                    if attributed == *level {
                        s.refuted += 1;
                    }
                    if attributed == "unattributed" {
                        *unattributed.entry(basis.clone()).or_insert(0) += 1;
                    }
                    decided.push((*conf, false));
                }
                _ => s.open += 1,
            }
        }
        *rep.status.entry(status.to_string()).or_insert(0) += 1;
        if !attributed.is_empty() {
            *rep.attributed.entry(attributed.clone()).or_insert(0) += 1;
        }
        updates.push((*id, status, observed, attributed));
    }

    // rule reliability: Beta(prior) + attributed outcomes (recomputed from scratch)
    let ts = crate::util::now_secs();
    for s in stats.values_mut() {
        let prior = l.rule.iter().find(|r| r.id == s.basis).map(|r| r.confidence).filter(|c| *c > 0.0).unwrap_or(0.5);
        let a = prior * PRIOR_WEIGHT + s.confirmed as f64;
        let b = (1.0 - prior) * PRIOR_WEIGHT + s.refuted as f64;
        s.reliability = (a / (a + b) * 1000.0).round() / 1000.0;
        let d = s.confirmed + s.refuted;
        s.precision = (d > 0).then(|| (s.confirmed as f64 / d as f64 * 1000.0).round() / 1000.0);
    }

    // QBF-C101 calibration bands over decided value predictions
    let mut bands: BTreeMap<usize, (usize, f64, usize)> = BTreeMap::new();
    for (c, ok) in &decided {
        let b = ((c * 10.0).floor() as usize).min(9);
        let e = bands.entry(b).or_insert((0, 0.0, 0));
        e.0 += 1;
        e.1 += c;
        e.2 += *ok as usize;
    }
    let reviewer = qb.cfg.operator.name.clone();
    let mut findings: Vec<(String, String, String)> = Vec::new();
    for (b, (n, sum, ok)) in bands {
        let mean = sum / n as f64;
        let realized = ok as f64 / n as f64;
        let gap = realized - mean;
        let finding = n >= CALIBRATION_MIN_BAND && gap.abs() >= CALIBRATION_TOLERANCE;
        let band = format!("{:.1}-{:.1}", b as f64 / 10.0, (b + 1) as f64 / 10.0);
        if finding {
            findings.push((
                "calibration".into(),
                band.clone(),
                format!(
                    "proposal for {reviewer}: predictions stated at {:.0}% came true {:.0}% of the time over {n} outcomes ({}{:.0} points); review the priors of the rules in this band — not applied automatically",
                    mean * 100.0,
                    realized * 100.0,
                    if gap > 0.0 { "+" } else { "" },
                    gap * 100.0
                ),
            ));
        }
        rep.calibration.push(Band {
            band,
            decided: n,
            mean_confidence: (mean * 1000.0).round() / 1000.0,
            realized: (realized * 1000.0).round() / 1000.0,
            gap: (gap * 1000.0).round() / 1000.0,
            finding,
        });
    }
    for (basis, n) in &unattributed {
        if *n >= PATTERN_MIN {
            findings.push((
                "pattern".into(),
                basis.clone(),
                format!("{n} refutations of {basis} were explained by no level (contested observations); repeated unattributed errors against one expectation suggest a missing level"),
            ));
        }
    }

    qb.store.write(|c| {
        let tx = c.unchecked_transaction()?;
        {
            let mut st = tx.prepare("UPDATE expectations SET status=?2, observed=?3, attributed=?4 WHERE id=?1")?;
            for (id, s, o, a) in &updates {
                st.execute(params![id, s, o, a])?;
            }
            let mut st = tx.prepare(
                "INSERT INTO lattice_rules(rule,alpha,beta,confirmed,refuted,ts) VALUES(?1,?2,?3,?4,?5,?6)
                 ON CONFLICT(rule) DO UPDATE SET alpha=?2, beta=?3, confirmed=?4, refuted=?5, ts=?6",
            )?;
            for s in stats.values() {
                let prior = l.rule.iter().find(|r| r.id == s.basis).map(|r| r.confidence).filter(|c| *c > 0.0).unwrap_or(0.5);
                st.execute(params![
                    s.basis,
                    prior * PRIOR_WEIGHT + s.confirmed as f64,
                    (1.0 - prior) * PRIOR_WEIGHT + s.refuted as f64,
                    s.confirmed as i64,
                    s.refuted as i64,
                    ts
                ])?;
            }
            let mut st = tx.prepare(
                "INSERT INTO lattice_findings(kind,subject,detail,ts) VALUES(?1,?2,?3,?4)
                 ON CONFLICT(kind,subject) DO UPDATE SET detail=?3, ts=?4",
            )?;
            for (k, s, d) in &findings {
                st.execute(params![k, s, d, ts])?;
            }
        }
        tx.commit()?;
        Ok(())
    })?;
    rep.findings = findings.into_iter().map(|(k, s, d)| format!("[{k}] {s}: {d}")).collect();
    rep.rules = stats.into_values().collect();
    Ok(rep)
}

fn level_name(level: &str) -> &'static str {
    match level {
        "conceptual" => "conceptual",
        "invariant" => "invariant",
        "engine" => "engine",
        _ => "unattributed",
    }
}

// ---------------------------------------------------------------- report

#[derive(Debug, Default, Serialize)]
pub struct ClassCoverage {
    pub domain: String,
    pub class: String,
    pub label: String,
    pub members: i64,
    pub enumerated: i64,
    pub slots: usize,
    pub cells: i64,
    pub filled: i64,
    pub absent: i64,
    pub open: i64,
    pub predicted_open: i64,
    pub confirmed: i64,
    pub refuted: i64,
}

#[derive(Debug, Default, Serialize)]
pub struct Report {
    pub lattice: String,
    pub domains: usize,
    pub classes: usize,
    pub slots: usize,
    pub rules: usize,
    pub classes_censused: usize,
    pub members: i64,
    pub cells: i64,
    pub filled: i64,
    pub absent: i64,
    pub open: i64,
    pub value_predictions: i64,
    pub confirmed: i64,
    pub refuted: i64,
    pub precision: Option<f64>,
    pub remaining_fill_queries: i64,
    pub coverage: Vec<ClassCoverage>,
    pub rule_stats: Vec<RuleStat>,
    pub findings: Vec<String>,
}

pub fn report(qb: &QueryBook, l: &Lattice, digest: &str) -> anyhow::Result<Report> {
    let mut rep = Report {
        lattice: digest.to_string(),
        domains: l.domain.len(),
        classes: l.class.len(),
        slots: l.slot.len(),
        rules: l.rule.len(),
        ..Default::default()
    };
    let batch = l.source.batch.max(1) as i64;
    qb.store.read(|c| {
        let mut per: HashMap<String, BTreeMap<String, i64>> = HashMap::new();
        let mut st = c.prepare(
            "SELECT class, CASE WHEN value='' THEN 'p:'||status ELSE 'v:'||status END, COUNT(*) FROM expectations GROUP BY 1, 2",
        )?;
        for r in st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, i64>(2)?)))? {
            let (cl, k, n) = r?;
            per.entry(cl).or_default().insert(k, n);
        }
        let census: HashMap<String, (i64, i64)> = {
            let mut st = c.prepare("SELECT class, members, enumerated FROM lattice_census")?;
            let r = st.query_map([], |r| Ok((r.get(0)?, (r.get(1)?, r.get(2)?))))?.collect::<Result<HashMap<_, _>, _>>()?;
            r
        };
        for class in &l.class {
            let Some(&(members, enumerated)) = census.get(&class.id) else { continue };
            rep.classes_censused += 1;
            let m = per.get(&class.id).cloned().unwrap_or_default();
            let g = |k: &str| m.get(k).copied().unwrap_or(0);
            let cc = ClassCoverage {
                domain: l.domain_of(class).to_string(),
                class: class.id.clone(),
                label: class.label.clone(),
                members,
                enumerated,
                slots: class.slots.len(),
                cells: enumerated * class.slots.len() as i64,
                filled: g("p:filled"),
                absent: g("p:absent"),
                open: g("p:open"),
                predicted_open: g("v:open"),
                confirmed: g("v:confirmed"),
                refuted: g("v:refuted"),
            };
            rep.members += enumerated;
            rep.cells += cc.cells;
            rep.filled += cc.filled;
            rep.absent += cc.absent;
            rep.open += cc.open;
            rep.value_predictions += m.iter().filter(|(k, _)| k.starts_with("v:")).map(|(_, n)| n).sum::<i64>();
            rep.confirmed += cc.confirmed;
            rep.refuted += cc.refuted;
            // one targeted query fills `batch` open cells of one column
            rep.remaining_fill_queries += (cc.open + batch - 1) / batch;
            rep.coverage.push(cc);
        }
        let mut st = c.prepare("SELECT kind, subject, detail FROM lattice_findings ORDER BY kind, subject")?;
        rep.findings = st
            .query_map([], |r| {
                Ok(format!("[{}] {}: {}", r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        let mut st = c.prepare("SELECT rule, alpha, beta, confirmed, refuted FROM lattice_rules ORDER BY rule")?;
        rep.rule_stats = st
            .query_map([], |r| {
                let (a, b, cf, rf): (f64, f64, i64, i64) = (r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?);
                Ok(RuleStat {
                    basis: r.get(0)?,
                    confirmed: cf as usize,
                    refuted: rf as usize,
                    precision: (cf + rf > 0).then(|| (cf as f64 / (cf + rf) as f64 * 1000.0).round() / 1000.0),
                    reliability: (a / (a + b) * 1000.0).round() / 1000.0,
                    ..Default::default()
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(())
    })?;
    let d = rep.confirmed + rep.refuted;
    rep.precision = (d > 0).then(|| (rep.confirmed as f64 / d as f64 * 1000.0).round() / 1000.0);
    Ok(rep)
}
