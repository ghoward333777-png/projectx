//! Wikidata connector for the knowledge lattice.
//!
//!   validate_live  every Q-id and P-id the lattice names is fetched from the
//!                  Wikidata API: items must exist, properties must carry the
//!                  datatype the slot expects, labels are reported for review
//!   census         members of each class (above its notability floor) and,
//!                  per slot, how many members Wikidata fills it for — the
//!                  conceptual-level expectation of every cell
//!   fill           targeted harvest: for one class x slot column, only the
//!                  cells still open, in bounded VALUES batches; results are
//!                  written as ordinary Fact Envelopes for the D1 import
//!   predict        (optional) an engine recalls values for open cells; the
//!                  predictions are D5 expectations, never facts
//!   propose        (optional) an engine proposes new classes/slots for a
//!                  domain; ids are live-validated and written for review
//!
//! A connector only reaches outside and writes files or expectation rows;
//! nothing it fetches enters the substrate except through the D1 import.

use super::wikidata::{self, Pack, QueryDef};
use crate::app::QueryBook;
use crate::d3::lattice::{Class, Lattice, Slot};
use rusqlite::params;
use serde::Serialize;
use serde_json::{Value as J, json};
use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

fn pack(l: &Lattice) -> Pack {
    Pack {
        endpoint: l.source.endpoint.clone(),
        contact: l.source.contact.clone(),
        page_size: l.source.page_size,
        pause_ms: l.source.pause_ms,
        confidence: l.source.confidence,
        weight: l.source.weight,
        query: vec![],
    }
}

fn client(l: &Lattice) -> anyhow::Result<reqwest::blocking::Client> {
    let ua = format!(
        "QueryBookLattice/0.1 ({})",
        if l.source.contact.trim().is_empty() { "no contact set" } else { l.source.contact.trim() }
    );
    Ok(reqwest::blocking::Client::builder().user_agent(ua).timeout(Duration::from_secs(120)).build()?)
}

/// The membership graph pattern of a class, binding ?s.
pub fn membership(c: &Class) -> String {
    let base = match (&c.pattern, &c.qid) {
        (Some(p), _) => p.clone(),
        (None, Some(q)) if c.deep => format!("?s wdt:P31/wdt:P279* wd:{q} ."),
        (None, Some(q)) => format!("?s wdt:P31 wd:{q} ."),
        (None, None) => String::new(),
    };
    let extra = c.where_.clone().unwrap_or_default();
    format!("{base} {extra} ?s wikibase:sitelinks ?n . FILTER(?n >= {})", c.min_sitelinks)
}

fn value_triple(slot: &Slot) -> String {
    if slot.kind == "number" && slot.normalize {
        format!("?s p:{p}/psn:{p}/wikibase:quantityAmount ?o .", p = slot.pid)
    } else {
        format!("?s wdt:{} ?o .", slot.pid)
    }
}

fn query_def(l: &Lattice, c: &Class, s: &Slot) -> QueryDef {
    QueryDef {
        id: format!("lattice:{}/{}", c.id, s.id),
        domain: l.domain_of(c).to_string(),
        predicate: s.predicate().to_string(),
        object_kind: if s.kind == "text" { "literal".into() } else { s.kind.clone() },
        text: l.text_for(c, s).to_string(),
        sparql: String::new(),
        scale: s.scale,
        decimals: s.decimals,
        unit: s.unit.clone(),
        offset: s.offset,
        sci: s.sci,
    }
}

// ---------------------------------------------------------------- validate

#[derive(Debug, Default, Serialize)]
pub struct LiveCheck {
    pub items: usize,
    pub properties: usize,
    pub errors: Vec<String>,
    /// id -> Wikidata English label, for human review of intent
    pub labels: BTreeMap<String, String>,
    /// class ids whose lattice label differs from the item's label (review, not error)
    pub label_differs: Vec<String>,
}

fn expected_datatype(kind: &str) -> &'static [&'static str] {
    match kind {
        "entity" => &["wikibase-item"],
        "number" => &["quantity"],
        "year" => &["time"],
        _ => &["string", "external-id", "monolingualtext"],
    }
}

pub fn validate_live(l: &Lattice, progress: &dyn Fn(&str)) -> anyhow::Result<LiveCheck> {
    let http = client(l)?;
    let (qs, ps) = l.referenced_ids();
    let ids: Vec<String> = qs.iter().chain(ps.iter()).cloned().collect();
    let mut rep = LiveCheck { items: qs.len(), properties: ps.len(), ..Default::default() };
    let mut entities: BTreeMap<String, J> = BTreeMap::new();
    for chunk in ids.chunks(50) {
        let url = format!(
            "{}?action=wbgetentities&ids={}&props=labels%7Cdatatype&languages=en&format=json",
            l.source.api,
            chunk.join("%7C")
        );
        let mut attempt = 0;
        let v: J = loop {
            match http.get(&url).send() {
                Ok(r) if r.status().is_success() => break r.json()?,
                Ok(r) if attempt < 5 => {
                    progress(&format!("  api busy (HTTP {}); retrying", r.status()));
                }
                Ok(r) => anyhow::bail!("wbgetentities: HTTP {}", r.status()),
                Err(e) if attempt < 5 => progress(&format!("  network: {e}; retrying")),
                Err(e) => return Err(e.into()),
            }
            attempt += 1;
            std::thread::sleep(Duration::from_secs(2u64 << attempt));
        };
        if let Some(err) = v.get("error") {
            // one malformed id fails the whole request: report and fall back to one-by-one
            progress(&format!("  batch rejected ({}); checking ids one by one", err["info"]));
            for id in chunk {
                let url =
                    format!("{}?action=wbgetentities&ids={id}&props=labels%7Cdatatype&languages=en&format=json", l.source.api);
                let one: J = http.get(&url).send()?.json()?;
                match one["entities"].get(id) {
                    Some(e) => {
                        entities.insert(id.clone(), e.clone());
                    }
                    None => rep.errors.push(format!("{id}: rejected by the API ({})", one["error"]["info"])),
                }
            }
        } else if let Some(obj) = v["entities"].as_object() {
            for (k, e) in obj {
                entities.insert(k.clone(), e.clone());
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    for id in &ids {
        let Some(e) = entities.get(id) else { continue };
        if e.get("missing").is_some() {
            rep.errors.push(format!("{id}: does not exist on Wikidata"));
            continue;
        }
        let label = e["labels"]["en"]["value"].as_str().unwrap_or("").to_string();
        rep.labels.insert(id.clone(), label);
    }
    for s in &l.slot {
        match entities.get(&s.pid) {
            Some(e) if e.get("missing").is_none() => {
                let dt = e["datatype"].as_str().unwrap_or("");
                if !expected_datatype(&s.kind).contains(&dt) {
                    rep.errors.push(format!(
                        "slot {} ({} “{}”): datatype {dt} does not fit kind {}",
                        s.id,
                        s.pid,
                        rep.labels.get(&s.pid).cloned().unwrap_or_default(),
                        s.kind
                    ));
                }
            }
            _ => {}
        }
    }
    let norm = |x: &str| crate::util::alias_key(x).replace(['-', ' '], "");
    for c in &l.class {
        if let Some(q) = &c.qid {
            if let Some(lab) = rep.labels.get(q) {
                let (a, b) = (norm(lab), norm(&c.label));
                if !(a.contains(&b) || b.contains(&a)) {
                    rep.label_differs.push(format!("{} {q}: lattice “{}” vs Wikidata “{lab}”", c.id, c.label));
                }
            }
        }
    }
    Ok(rep)
}

// ---------------------------------------------------------------- census

#[derive(Debug, Default, Serialize)]
pub struct CensusRow {
    pub class: String,
    pub members: usize,
    pub enumerated: usize,
    pub fill: BTreeMap<String, usize>,
    pub status: String,
    pub seconds: f64,
}

/// Enumerate each selected class's members (up to `max_members`, most
/// notable first) and count, per slot, how many notable members carry it.
pub fn census(
    qb: &QueryBook,
    l: &Lattice,
    only: &[String],
    max_members: usize,
    force: bool,
    out: Option<&Path>,
    progress: &dyn Fn(&str),
) -> anyhow::Result<Vec<CensusRow>> {
    crate::d5::expect::ensure_tables(qb)?;
    let http = client(l)?;
    let pk = pack(l);
    let done: BTreeSet<String> = qb.store.read(|c| {
        let mut st = c.prepare("SELECT class FROM lattice_census WHERE status='ok'")?;
        let r = st.query_map([], |r| r.get(0))?.collect::<Result<BTreeSet<String>, _>>()?;
        Ok(r)
    })?;
    let mut rows = Vec::new();
    let attested = crate::util::now_secs().to_string();
    for c in l.selected(only) {
        if done.contains(&c.id) && !force {
            continue;
        }
        let t0 = Instant::now();
        let mut row = CensusRow { class: c.id.clone(), ..Default::default() };
        let result: anyhow::Result<()> = (|| {
            // members, most notable first
            let mut members: Vec<(String, String, i64)> = Vec::new();
            let mut offset = 0usize;
            let page = l.source.page_size.min(max_members.max(1));
            while members.len() < max_members {
                let sparql = format!(
                    "SELECT ?s ?sLabel ?n WHERE {{ {{ SELECT DISTINCT ?s ?n WHERE {{ {} }} ORDER BY DESC(?n) ?s LIMIT {page} OFFSET {offset} }}\n  SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }} }}",
                    membership(c)
                );
                let got = wikidata::fetch(&http, &pk, &sparql, progress)?;
                let n = got.len();
                for r in &got {
                    let Some(q) = r["s"]["value"].as_str().and_then(wikidata::qid) else { continue };
                    let label = r["sLabel"]["value"].as_str().unwrap_or("");
                    if !wikidata::usable_label(label) {
                        continue;
                    }
                    let sl: i64 = r["n"]["value"].as_str().and_then(|x| x.parse().ok()).unwrap_or(0);
                    if !members.iter().any(|m| m.0 == q) {
                        members.push((q.to_string(), label.to_string(), sl));
                    }
                }
                offset += n;
                if n < page {
                    break;
                }
                std::thread::sleep(Duration::from_millis(l.source.pause_ms));
            }
            members.truncate(max_members);
            row.enumerated = members.len();
            // slot fill counts over the enumerated members, in bounded VALUES
            // batches (an unbounded join lets the planner scan every use of a
            // property before it meets the class, which times out)
            let props: String = c
                .slots
                .iter()
                .map(|sid| {
                    let s = l.slot(sid).unwrap();
                    format!("(\"{}\" wdt:{})", s.id, s.pid)
                })
                .collect::<Vec<_>>()
                .join(" ");
            for chunk in members.chunks(l.source.batch.max(1)) {
                let values: String = chunk.iter().map(|m| format!("wd:{}", m.0)).collect::<Vec<_>>().join(" ");
                let sparql = format!(
                    "SELECT ?slot (COUNT(DISTINCT ?s) AS ?c) WHERE {{ VALUES ?s {{ {values} }} VALUES (?slot ?p) {{ {props} }} ?s ?p [] . }} GROUP BY ?slot"
                );
                for r in wikidata::fetch(&http, &pk, &sparql, progress)? {
                    let slot = r["slot"]["value"].as_str().unwrap_or("").to_string();
                    let n: usize = r["c"]["value"].as_str().and_then(|x| x.parse().ok()).unwrap_or(0);
                    *row.fill.entry(slot).or_insert(0) += n;
                }
                std::thread::sleep(Duration::from_millis(l.source.pause_ms / 2));
            }
            row.members = if members.len() < max_members {
                members.len()
            } else {
                let sparql = format!("SELECT (COUNT(DISTINCT ?s) AS ?c) WHERE {{ {} }}", membership(c));
                wikidata::fetch(&http, &pk, &sparql, progress)?
                    .first()
                    .and_then(|r| r["c"]["value"].as_str())
                    .and_then(|x| x.parse().ok())
                    .unwrap_or(members.len())
            };
            // the fill rate is over enumerated members when the census covers them all
            let ts = crate::util::now_secs();
            qb.store.write(|db| {
                let tx = db.unchecked_transaction()?;
                tx.execute("DELETE FROM lattice_members WHERE class=?1", [&c.id])?;
                {
                    let mut st =
                        tx.prepare("INSERT OR IGNORE INTO lattice_members(class,qid,label,sitelinks) VALUES(?1,?2,?3,?4)")?;
                    for (q, lab, n) in &members {
                        st.execute(params![c.id, q, lab, n])?;
                    }
                    let mut st = tx.prepare(
                        "INSERT INTO lattice_fill(class,slot,filled,ts) VALUES(?1,?2,?3,?4)
                         ON CONFLICT(class,slot) DO UPDATE SET filled=?3, ts=?4",
                    )?;
                    for sid in &c.slots {
                        st.execute(params![c.id, sid, row.fill.get(sid).copied().unwrap_or(0) as i64, ts])?;
                    }
                }
                tx.execute(
                    "INSERT INTO lattice_census(class,members,enumerated,status,ts) VALUES(?1,?2,?3,'ok',?4)
                     ON CONFLICT(class) DO UPDATE SET members=?2, enumerated=?3, status='ok', ts=?4",
                    params![c.id, row.members as i64, members.len() as i64, ts],
                )?;
                tx.commit()?;
                Ok(())
            })?;
            // membership is itself harvestable knowledge: "X is a <class>"
            if let Some(dir) = out {
                let dir = dir.join(&c.id);
                std::fs::create_dir_all(&dir)?;
                let mut w = std::io::BufWriter::new(std::fs::File::create(dir.join("_members.ndjson"))?);
                let article = if c.label.starts_with(['a', 'e', 'i', 'o', 'u', 'A', 'E', 'I', 'O', 'U']) { "an" } else { "a" };
                let q = QueryDef {
                    id: format!("lattice:{}/is_a", c.id),
                    domain: l.domain_of(c).to_string(),
                    predicate: "is_a".into(),
                    object_kind: "literal".into(),
                    text: format!("{{s}} is {article} {{o}}."),
                    sparql: String::new(),
                    scale: 1.0,
                    decimals: 0,
                    unit: String::new(),
                    offset: 0.0,
                    sci: false,
                };
                for (qid, label, _) in &members {
                    let r = json!({"s": {"value": format!("http://www.wikidata.org/entity/{qid}")}, "sLabel": {"value": label}, "o": {"value": c.label}});
                    if let Some(env) = wikidata::envelope(&pk, &q, &r, &attested) {
                        writeln!(w, "{env}")?;
                    }
                }
                w.flush()?;
            }
            Ok(())
        })();
        row.seconds = (t0.elapsed().as_secs_f64() * 10.0).round() / 10.0;
        row.status = match result {
            Ok(()) => "ok".into(),
            Err(e) => {
                let msg = format!("failed: {}", crate::util::clip(&e.to_string(), 200));
                qb.store.write(|db| {
                    db.execute(
                        "INSERT INTO lattice_census(class,members,enumerated,status,ts) VALUES(?1,0,0,?2,?3)
                         ON CONFLICT(class) DO UPDATE SET status=?2, ts=?3",
                        params![c.id, msg, crate::util::now_secs()],
                    )?;
                    Ok(())
                })?;
                msg
            }
        };
        let fills: String = c
            .slots
            .iter()
            .map(|s| format!("{s} {:.0}%", 100.0 * row.fill.get(s).copied().unwrap_or(0) as f64 / row.enumerated.max(1) as f64))
            .collect::<Vec<_>>()
            .join(", ");
        progress(&format!(
            "  {:<22} {:>6} members ({} enumerated) {:>5.1}s  {}{}",
            c.id,
            row.members,
            row.enumerated,
            row.seconds,
            if row.status == "ok" { "" } else { &row.status },
            if row.status == "ok" { fills } else { String::new() }
        ));
        rows.push(row);
        std::thread::sleep(Duration::from_millis(l.source.pause_ms));
    }
    Ok(rows)
}

// ---------------------------------------------------------------- fill

#[derive(Debug, Default, Serialize)]
pub struct FillReport {
    pub queries: usize,
    pub cells_checked: usize,
    pub cells_filled: usize,
    pub envelopes: usize,
    /// forecasts whose cells this run fetched (confirmed or refuted by `confirm`)
    pub predictions_tested: usize,
    pub columns: Vec<ColumnFill>,
    pub seconds: f64,
    pub out: String,
}

#[derive(Debug, Default, Serialize)]
pub struct ColumnFill {
    pub class: String,
    pub slot: String,
    pub open_before: usize,
    pub checked: usize,
    pub filled: usize,
    pub envelopes: usize,
    pub queries: usize,
    pub priority: f64,
}

/// Targeted harvest of open cells. Columns are taken in priority order:
/// first those whose open cells carry forecasts from rules whose reliability
/// is still uncertain (each outcome there most changes what the lattice
/// believes — the registry's discriminating-selection principle, QBF-C094),
/// then by expected yield (fill rate x open cells). `budget` bounds queries.
pub fn fill(
    qb: &QueryBook,
    l: &Lattice,
    only: &[String],
    budget: usize,
    out: &Path,
    progress: &dyn Fn(&str),
) -> anyhow::Result<FillReport> {
    crate::d5::expect::ensure_tables(qb)?;
    let t0 = Instant::now();
    let http = client(l)?;
    let pk = pack(l);
    let mut subjects: BTreeSet<String> = BTreeSet::new();
    for c in l.selected(only) {
        subjects.extend(crate::d5::expect::members(qb, &c.id)?.into_iter().map(|m| m.0));
    }
    let obs = crate::d5::expect::Observations::for_subjects(
        qb,
        subjects.iter().map(|s| s.as_str()),
        &crate::d5::expect::lattice_predicates(l),
    )?;
    let chk = crate::d5::expect::checked(qb)?;
    // open forecasts per column, weighted by how uncertain their basis still is
    let forecasts: BTreeMap<(String, String), (usize, f64, BTreeSet<String>)> = qb.store.read(|c| {
        let mut st = c.prepare(
            "SELECT e.class, e.slot, e.subject, COALESCE(r.alpha, 5.0), COALESCE(r.beta, 5.0)
             FROM expectations e LEFT JOIN lattice_rules r ON r.rule = e.basis
             WHERE e.value != '' AND e.status = 'open'",
        )?;
        let mut m: BTreeMap<(String, String), (usize, f64, BTreeSet<String>)> = BTreeMap::new();
        for r in st.query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, f64>(3)?, r.get::<_, f64>(4)?))
        })? {
            let (cl, sl, subj, a, b) = r?;
            // Beta variance: largest while few outcomes have been seen
            let var = a * b / ((a + b).powi(2) * (a + b + 1.0));
            let e = m.entry((cl, sl)).or_default();
            e.0 += 1;
            e.1 += var;
            e.2.insert(subj);
        }
        Ok(m)
    })?;
    let fill_rate: BTreeMap<(String, String), f64> = qb.store.read(|c| {
        let mut st = c.prepare("SELECT f.class, f.slot, CAST(f.filled AS REAL) / MAX(1, n.enumerated) FROM lattice_fill f JOIN lattice_census n ON n.class = f.class")?;
        let r = st.query_map([], |r| Ok(((r.get(0)?, r.get(1)?), r.get(2)?)))?.collect::<Result<BTreeMap<_, _>, _>>()?;
        Ok(r)
    })?;

    struct Col<'a> {
        class: &'a Class,
        slot: &'a Slot,
        open: Vec<(String, String)>,
        priority: f64,
        forecasts: usize,
    }
    let mut cols: Vec<Col> = Vec::new();
    for c in l.selected(only) {
        let mem = crate::d5::expect::members(qb, &c.id)?;
        if mem.is_empty() {
            continue;
        }
        for sid in &c.slots {
            let s = l.slot(sid).unwrap();
            let open: Vec<(String, String)> = mem
                .iter()
                .filter(|(q, _)| {
                    obs.get(q, s.predicate()).is_empty() && !chk.contains_key(&(c.id.clone(), sid.clone(), q.clone()))
                })
                .cloned()
                .collect();
            if open.is_empty() {
                continue;
            }
            let (nf, var, _) = forecasts.get(&(c.id.clone(), sid.clone())).cloned().unwrap_or_default();
            let rate = fill_rate.get(&(c.id.clone(), sid.clone())).copied().unwrap_or(0.5);
            // discrimination first (uncertain forecasts), then expected facts per query
            let priority = 1000.0 * var + rate * open.len().min(l.source.batch) as f64;
            cols.push(Col { class: c, slot: s, open, priority, forecasts: nf });
        }
    }
    cols.sort_by(|a, b| {
        b.priority.partial_cmp(&a.priority).unwrap().then_with(|| (&a.class.id, &a.slot.id).cmp(&(&b.class.id, &b.slot.id)))
    });

    let attested = crate::util::now_secs().to_string();
    let mut rep = FillReport { out: out.display().to_string(), ..Default::default() };
    'cols: for col in &cols {
        let q = query_def(l, col.class, col.slot);
        let dir = out.join(&col.class.id);
        std::fs::create_dir_all(&dir)?;
        let file: PathBuf = dir.join(format!("{}.ndjson", col.slot.id));
        let mut w = std::io::BufWriter::new(std::fs::OpenOptions::new().create(true).append(true).open(&file)?);
        let mut cf = ColumnFill {
            class: col.class.id.clone(),
            slot: col.slot.id.clone(),
            open_before: col.open.len(),
            priority: (col.priority * 100.0).round() / 100.0,
            ..Default::default()
        };
        let tested: BTreeSet<String> =
            forecasts.get(&(col.class.id.clone(), col.slot.id.clone())).map(|f| f.2.clone()).unwrap_or_default();
        for batch in col.open.chunks(l.source.batch.max(1)) {
            if rep.queries >= budget {
                w.flush()?;
                rep.columns.push(cf);
                break 'cols;
            }
            let values: String = batch.iter().map(|(q, _)| format!("wd:{q}")).collect::<Vec<_>>().join(" ");
            let sparql = format!(
                "SELECT ?s ?sLabel ?o ?oLabel WHERE {{ VALUES ?s {{ {values} }} {}\n  SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }} }}",
                value_triple(col.slot)
            );
            let got = match wikidata::fetch(&http, &pk, &sparql, progress) {
                Ok(g) => g,
                Err(e) => {
                    progress(&format!("    {} / {}: {e}", col.class.id, col.slot.id));
                    rep.queries += 1;
                    continue;
                }
            };
            rep.queries += 1;
            cf.queries += 1;
            let mut per: BTreeMap<String, i64> = batch.iter().map(|(q, _)| (q.clone(), 0)).collect();
            let mut seen = BTreeSet::new();
            for r in &got {
                if let Some(env) = wikidata::envelope(&pk, &q, r, &attested) {
                    let id = env["id"].as_str().unwrap_or("").to_string();
                    if !seen.insert(id) {
                        continue;
                    }
                    if let Some(s) = r["s"]["value"].as_str().and_then(wikidata::qid) {
                        *per.entry(s.to_string()).or_insert(0) += 1;
                    }
                    writeln!(w, "{env}")?;
                    cf.envelopes += 1;
                }
            }
            let ts = crate::util::now_secs();
            qb.store.write(|db| {
                let tx = db.unchecked_transaction()?;
                {
                    let mut st = tx.prepare(
                        "INSERT INTO lattice_checked(class,slot,qid,n,ts) VALUES(?1,?2,?3,?4,?5)
                         ON CONFLICT(class,slot,qid) DO UPDATE SET n=?4, ts=?5",
                    )?;
                    for (qid, n) in &per {
                        st.execute(params![col.class.id, col.slot.id, qid, n, ts])?;
                    }
                }
                tx.commit()?;
                Ok(())
            })?;
            cf.checked += per.len();
            cf.filled += per.values().filter(|&&n| n > 0).count();
            rep.predictions_tested += per.keys().filter(|q| tested.contains(*q)).count();
            std::thread::sleep(Duration::from_millis(l.source.pause_ms));
        }
        w.flush()?;
        progress(&format!(
            "  {:<22} {:<20} {:>5} open -> {:>5} filled in {} quer{}{}",
            col.class.id,
            col.slot.id,
            cf.open_before,
            cf.filled,
            cf.queries,
            if cf.queries == 1 { "y" } else { "ies" },
            if col.forecasts > 0 { format!("  ({} forecasts under test)", col.forecasts) } else { String::new() }
        ));
        rep.columns.push(cf);
    }
    rep.cells_checked = rep.columns.iter().map(|c| c.checked).sum();
    rep.cells_filled = rep.columns.iter().map(|c| c.filled).sum();
    rep.envelopes = rep.columns.iter().map(|c| c.envelopes).sum();
    rep.seconds = (t0.elapsed().as_secs_f64() * 10.0).round() / 10.0;
    Ok(rep)
}

// ---------------------------------------------------------------- engine

fn prediction_schema() -> J {
    json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["predictions"],
        "properties": {"predictions": {"type": "array", "items": {
            "type": "object", "additionalProperties": false,
            "required": ["qid", "value", "confidence"],
            "properties": {
                "qid": {"type": "string"},
                "value": {"type": ["string", "null"]},
                "confidence": {"type": "number"}
            }
        }}}
    })
}

const PREDICT_SYSTEM: &str = "You fill cells of a knowledge base before they are checked against Wikidata. \
For each listed item you give your best recollection of one attribute. Rules: answer only from knowledge you are confident of; \
return null when you do not know — a null costs nothing, a wrong value is counted against you; \
for an item-valued attribute give the English name of the value as Wikidata labels it; for a year give the year only \
(negative for BC); for a number give the number alone in the stated unit, no separators. \
confidence is your calibrated probability that the value is exactly right. Every prediction will be verified; none is stored as fact.";

#[derive(Debug, Default, Serialize)]
pub struct PredictReport {
    pub engine: String,
    pub requests: usize,
    pub cells: usize,
    pub predictions: usize,
    pub nulls: usize,
    pub input_tokens: u64,
    pub output_tokens: u64,
}

/// Ask an extraction engine to recall values for open cells. Predictions are
/// stored as engine-level expectations (value "~name" for items, compared by
/// normalized name), never as facts.
pub fn predict(
    qb: &QueryBook,
    l: &Lattice,
    engine_id: &str,
    only: &[String],
    limit: usize,
    digest: &str,
    progress: &dyn Fn(&str),
) -> anyhow::Result<PredictReport> {
    crate::d5::expect::ensure_tables(qb)?;
    let profile = qb.cfg.engine(engine_id).ok_or_else(|| anyhow::anyhow!("engine '{engine_id}' is not registered"))?.clone();
    anyhow::ensure!(matches!(profile.kind.as_str(), "claude" | "openai"), "engine '{engine_id}' is not a model engine");
    let engine = crate::d1::engines::llm::LlmEngine::new(profile)?;
    let mut subjects: BTreeSet<String> = BTreeSet::new();
    for c in l.selected(only) {
        subjects.extend(crate::d5::expect::members(qb, &c.id)?.into_iter().map(|m| m.0));
    }
    let obs = crate::d5::expect::Observations::for_subjects(
        qb,
        subjects.iter().map(|s| s.as_str()),
        &crate::d5::expect::lattice_predicates(l),
    )?;
    let chk = crate::d5::expect::checked(qb)?;
    let basis = format!("engine:{engine_id}");
    let asked: BTreeSet<(String, String, String)> = qb.store.read(|c| {
        let mut st = c.prepare("SELECT class, slot, subject FROM expectations WHERE basis=?1")?;
        let r = st.query_map([&basis], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?.collect::<Result<BTreeSet<_>, _>>()?;
        Ok(r)
    })?;
    let mut rep = PredictReport { engine: engine_id.into(), ..Default::default() };
    'outer: for c in l.selected(only) {
        let mem = crate::d5::expect::members(qb, &c.id)?;
        for sid in &c.slots {
            let s = l.slot(sid).unwrap();
            let open: Vec<&(String, String)> = mem
                .iter()
                .filter(|(q, _)| {
                    obs.get(q, s.predicate()).is_empty()
                        && !chk.contains_key(&(c.id.clone(), sid.clone(), q.clone()))
                        && !asked.contains(&(c.id.clone(), sid.clone(), q.clone()))
                })
                .collect();
            for batch in open.chunks(40) {
                if rep.cells >= limit {
                    break 'outer;
                }
                let unit = if s.unit.is_empty() { String::new() } else { format!(" (unit: {})", s.unit) };
                let items: String = batch.iter().map(|(q, lab)| format!("{q}\t{lab}")).collect::<Vec<_>>().join("\n");
                let user = format!(
                    "Class: {} ({})\nAttribute: {} — Wikidata property {}, value kind {}{unit}\nRendering: {}\n\nItems (Q-id, label):\n{items}",
                    c.label,
                    c.id,
                    s.id.replace('_', " "),
                    s.pid,
                    s.kind,
                    l.text_for(c, s)
                );
                let (text, it, ot) = engine.call_json(PREDICT_SYSTEM, &user, &prediction_schema())?;
                rep.requests += 1;
                rep.cells += batch.len();
                rep.input_tokens += it;
                rep.output_tokens += ot;
                let v: J = serde_json::from_str(&text).map_err(|e| anyhow::anyhow!("engine reply is not JSON: {e}"))?;
                let known: BTreeMap<&str, &str> = batch.iter().map(|(q, lab)| (q.as_str(), lab.as_str())).collect();
                let ts = crate::util::now_secs();
                let rows: Vec<(String, String, String, f64)> = v["predictions"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|p| {
                        let q = p["qid"].as_str()?;
                        let lab = known.get(q)?;
                        let conf = p["confidence"].as_f64().unwrap_or(0.0).clamp(0.0, 1.0);
                        let val = p["value"].as_str()?.trim().to_string();
                        if val.is_empty() {
                            return None;
                        }
                        let stored = if s.kind == "entity" { format!("~{val}") } else { val.clone() };
                        Some((q.to_string(), lab.to_string(), stored, conf))
                    })
                    .map(|(q, lab, stored, conf)| (q, lab, stored, conf))
                    .collect();
                rep.predictions += rows.len();
                rep.nulls += batch.len() - rows.len();
                qb.store.write(|db| {
                    let tx = db.unchecked_transaction()?;
                    {
                        let mut st = tx.prepare(
                            "INSERT OR IGNORE INTO expectations(level,basis,class,slot,subject,subject_label,value,value_label,confidence,premise,lattice,ts)
                             VALUES('engine',?1,?2,?3,?4,?5,?6,?7,?8,'single',?9,?10)",
                        )?;
                        for (q, lab, stored, conf) in &rows {
                            let shown = stored.trim_start_matches('~');
                            st.execute(params![basis, c.id, sid, q, lab, stored, shown, (conf * 1000.0).round() / 1000.0, digest, ts])?;
                        }
                        // a null answer is recorded too, so the cell is not asked again
                        let mut st = tx.prepare(
                            "INSERT OR IGNORE INTO expectations(level,basis,class,slot,subject,subject_label,value,value_label,confidence,premise,status,lattice,ts)
                             VALUES('engine',?1,?2,?3,?4,?5,'','',0,'single','declined',?6,?7)",
                        )?;
                        for (q, lab) in batch.iter().filter(|(q, _)| !rows.iter().any(|r| &r.0 == q)) {
                            st.execute(params![basis, c.id, sid, q, lab, digest, ts])?;
                        }
                    }
                    tx.commit()?;
                    Ok(())
                })?;
                progress(&format!("  {} / {}: {} predicted, {} declined", c.id, sid, rows.len(), batch.len() - rows.len()));
            }
        }
    }
    Ok(rep)
}

fn proposal_schema() -> J {
    json!({
        "type": "object", "additionalProperties": false, "required": ["classes", "slots"],
        "properties": {
            "classes": {"type": "array", "items": {"type": "object", "additionalProperties": false,
                "required": ["id", "sub", "label", "qid", "min_sitelinks", "slots"],
                "properties": {
                    "id": {"type": "string"}, "sub": {"type": "string"}, "label": {"type": "string"},
                    "qid": {"type": "string"}, "min_sitelinks": {"type": "integer"},
                    "slots": {"type": "array", "items": {"type": "string"}}
                }}},
            "slots": {"type": "array", "items": {"type": "object", "additionalProperties": false,
                "required": ["id", "pid", "kind", "text"],
                "properties": {
                    "id": {"type": "string"}, "pid": {"type": "string"},
                    "kind": {"type": "string", "enum": ["entity", "number", "year", "text"]}, "text": {"type": "string"}
                }}}
        }
    })
}

/// Ask an engine to extend one domain of the lattice. The reply is validated
/// structurally and live, then written as a TOML proposal for human review —
/// the lattice itself is changed only by editing it.
pub fn propose(
    qb: &QueryBook,
    l: &Lattice,
    engine_id: &str,
    domain: &str,
    out: &Path,
    progress: &dyn Fn(&str),
) -> anyhow::Result<usize> {
    let profile = qb.cfg.engine(engine_id).ok_or_else(|| anyhow::anyhow!("engine '{engine_id}' is not registered"))?.clone();
    let engine = crate::d1::engines::llm::LlmEngine::new(profile)?;
    let subs: Vec<&str> = l.sub.iter().filter(|s| s.domain == domain).map(|s| s.id.as_str()).collect();
    anyhow::ensure!(!subs.is_empty(), "no domain '{domain}' in the lattice");
    let existing: Vec<String> = l
        .class
        .iter()
        .filter(|c| l.domain_of(c) == domain)
        .map(|c| format!("{} = {} ({})", c.id, c.label, c.qid.as_deref().unwrap_or("pattern")))
        .collect();
    let slots: Vec<String> = l.slot.iter().map(|s| format!("{} {} {}", s.id, s.pid, s.kind)).collect();
    let user = format!(
        "Domain: {domain}\nSubdomains: {}\nExisting classes:\n{}\n\nSlot library (id pid kind):\n{}\n\n\
         Propose up to 15 further classes of real-world things in this domain that general readers ask about, each a Wikidata class \
         (its Q-id) whose members are found by `?s wdt:P31 wd:Q…`, with a notability floor (min_sitelinks) keeping it to the well-known \
         members, and the slots its members are expected to carry. Reuse slot ids from the library; define a new slot only when none fits. \
         Class ids are '{domain}.<name>'; sub must be one of the subdomains.",
        subs.join(", "),
        existing.join("\n"),
        slots.join("\n")
    );
    let system = "You extend the upper structure of a general knowledge lattice. Only name Wikidata ids you are sure of; \
                  every id you give is checked against Wikidata before a human reviews it.";
    let (text, it, ot) = engine.call_json(system, &user, &proposal_schema())?;
    progress(&format!("  {engine_id}: {it} input / {ot} output tokens"));
    let v: J = serde_json::from_str(&text)?;
    // build a candidate lattice with the proposal merged, then check it
    let mut cand = l.clone();
    let mut new_slots = Vec::new();
    for s in v["slots"].as_array().into_iter().flatten() {
        let slot: crate::d3::lattice::Slot = serde_json::from_value(s.clone())?;
        if cand.slot(&slot.id).is_none() {
            new_slots.push(slot.clone());
            cand.slot.push(slot);
        }
    }
    let mut new_classes = Vec::new();
    for c in v["classes"].as_array().into_iter().flatten() {
        let mut c = c.clone();
        c["texts"] = json!({});
        let class: Class = serde_json::from_value(c)?;
        if cand.class(&class.id).is_none() && !cand.class.iter().any(|x| x.qid == class.qid) {
            new_classes.push(class.clone());
            cand.class.push(class);
        }
    }
    let mut notes = cand.check();
    let mini = Lattice { class: new_classes.clone(), slot: new_slots.clone(), rule: vec![], ..cand.clone() };
    let live = validate_live(&mini, progress)?;
    notes.extend(live.errors.iter().cloned());
    notes.extend(live.label_differs.iter().map(|d| format!("review label: {d}")));
    let mut toml = format!(
        "# Proposal for domain '{domain}' from engine {engine_id} — NOT part of the lattice until a human merges it.\n\
         # Validation ({} new classes, {} new slots):\n",
        new_classes.len(),
        new_slots.len()
    );
    for n in &notes {
        toml.push_str(&format!("#   ! {n}\n"));
    }
    if notes.is_empty() {
        toml.push_str("#   all ids resolved; datatypes fit\n");
    }
    for c in &new_classes {
        toml.push_str(&format!(
            "\n[[class]]\nid = \"{}\"\nsub = \"{}\"\nlabel = \"{}\"   # Wikidata: {}\nqid = \"{}\"\nmin_sitelinks = {}\nslots = [{}]\n",
            c.id,
            c.sub,
            c.label,
            c.qid.as_ref().and_then(|q| live.labels.get(q)).cloned().unwrap_or_else(|| "?".into()),
            c.qid.clone().unwrap_or_default(),
            c.min_sitelinks,
            c.slots.iter().map(|s| format!("\"{s}\"")).collect::<Vec<_>>().join(", ")
        ));
    }
    if !new_slots.is_empty() {
        toml.push_str("\n# new slots for slots.toml\n");
        for s in &new_slots {
            toml.push_str(&format!(
                "#  {{ id = \"{}\", pid = \"{}\", kind = \"{}\", text = \"{}\" }},   # Wikidata: {}\n",
                s.id,
                s.pid,
                s.kind,
                s.text,
                live.labels.get(&s.pid).cloned().unwrap_or_else(|| "?".into())
            ));
        }
    }
    std::fs::write(out, toml)?;
    Ok(new_classes.len())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn membership_and_value_patterns() {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("config/lattice/knowledge-lattice.toml");
        let l = Lattice::load(&p).unwrap();
        let c = l.class("geo.country").unwrap();
        let m = membership(c);
        assert!(m.starts_with("?s wdt:P31 wd:Q3624078 .") && m.contains("FILTER NOT EXISTS") && m.contains("sitelinks"), "{m}");
        let moon = membership(l.class("astro.moon").unwrap());
        assert!(moon.contains("wdt:P31/wdt:P279* wd:Q2537"), "{moon}");
        assert_eq!(value_triple(l.slot("area").unwrap()), "?s p:P2046/psn:P2046/wikibase:quantityAmount ?o .");
        assert_eq!(value_triple(l.slot("capital").unwrap()), "?s wdt:P36 ?o .");
        let q = query_def(&l, l.class("chem.element").unwrap(), l.slot("melting_point").unwrap());
        let row = json!({"s": {"value": "http://www.wikidata.org/entity/Q1090"}, "sLabel": {"value": "silver"}, "o": {"value": "1234.93"}});
        let e = wikidata::envelope(&pack(&l), &q, &row, "1").unwrap();
        assert_eq!(e["text"], "silver melts at 961.8 °C.");
    }
}
