//! Book ingestion: D10 rights validation -> D1 extraction -> calibration ->
//! D0 safety gate -> D3 validation -> D1->D2 commit -> D5 pre-computation.

use super::engines::{self, Candidate, EngineReport};
use super::parse::{Book, parse_file};
use crate::app::QueryBook;
use crate::d0::{self, Domain, safety};
use crate::d2::{Derivation, Edge, EdgeClass, Evidence, FactUnit, Narrative, ProvRef, SourceRef, Temporal, Value};
use crate::d3::entities::{self, EntityTable};
use crate::util::now_secs;
use rusqlite::params;
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::time::Instant;

pub const RIGHTS: &[&str] = &["public-domain", "author-owned", "licensed", "publisher-licensed"];

#[derive(Clone, Debug)]
pub struct IngestOptions {
    pub id: Option<String>,
    pub rights: String,
    pub rights_note: String,
    pub engines: Vec<String>,
    pub replace: bool,
    pub genre: String,
    pub actor: String,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct IngestReport {
    pub work: String,
    pub title: String,
    pub author: String,
    pub chapters: usize,
    pub passages: usize,
    pub words: usize,
    pub entities: usize,
    pub candidates: usize,
    pub admitted: usize,
    pub refused_validation: usize,
    pub refused_safety: usize,
    pub contradictions: usize,
    pub ledger_node: u64,
    pub questions: usize,
    pub engines: Vec<EngineReport>,
    pub seconds: f64,
}

/// Authority of the work text as a source class, from its rights declaration.
fn authority(rights: &str) -> f64 {
    match rights {
        "author-owned" => 0.95,
        "publisher-licensed" | "licensed" => 0.92,
        _ => 0.9,
    }
}

pub fn ingest_file(
    qb: &QueryBook,
    path: &Path,
    opts: &IngestOptions,
    progress: &(dyn Fn(&str) + Sync),
) -> anyhow::Result<IngestReport> {
    // D10 -> D1: rights validation before ingestion begins.
    anyhow::ensure!(
        RIGHTS.contains(&opts.rights.as_str()),
        "rights declaration required: one of {} (got '{}')",
        RIGHTS.join(", "),
        opts.rights
    );
    d0::cross(Domain::D10, Domain::D1, "admit-work", Some("rights-validation"))?;
    let book = parse_file(path, opts.id.as_deref())?;
    anyhow::ensure!(book.passages.len() >= 3, "{} produced no readable text", path.display());
    ingest_book(qb, book, opts, progress)
}

pub fn ingest_book(
    qb: &QueryBook,
    book: Book,
    opts: &IngestOptions,
    progress: &(dyn Fn(&str) + Sync),
) -> anyhow::Result<IngestReport> {
    let t0 = Instant::now();
    let exists: bool = qb.store.read(|c| Ok(c.query_row("SELECT 1 FROM works WHERE id=?1", [&book.id], |_| Ok(())).is_ok()))?;
    if exists {
        anyhow::ensure!(opts.replace, "work '{}' is already ingested (use --replace to supersede it)", book.id);
        retire_work(qb, &book.id)?;
    }
    progress(&format!("{}: {} passages, {} words", book.title, book.passages.len(), book.words()));
    let ents = entities::detect(&book);
    progress(&format!("{} named concepts", ents.entities.len()));

    // D1: every registered engine requested runs independently; one failing
    // does not stop the others.
    let catalog = qb.catalog.read().unwrap().clone();
    let mut cands: Vec<Candidate> = Vec::new();
    let mut reports = Vec::new();
    let mut reliability: BTreeMap<String, f64> = BTreeMap::new();
    for eid in &opts.engines {
        let profile = qb.cfg.engine(eid).ok_or_else(|| anyhow::anyhow!("engine '{eid}' is not registered in the config"))?;
        let engine = engines::build(profile)?;
        reliability.insert(eid.clone(), engine.reliability());
        match engine.extract(&book, &ents, &catalog, progress) {
            Ok((c, r)) => {
                progress(&format!("{eid}: {} candidates", c.len()));
                cands.extend(c);
                reports.push(r);
            }
            Err(e) => {
                progress(&format!("{eid} failed: {e}"));
                reports.push(EngineReport { engine: eid.clone(), failed_requests: 1, ..Default::default() });
            }
        }
    }
    let n_cands = cands.len();
    let ingested = now_secs();
    let (mut facts, contra_pairs) = merge(&book, cands, &reliability, ingested, authority(&opts.rights));

    // D0 safety gate + D3 construction-time validation.
    let mut eval = safety::Evaluation::new("D1->D2 admission");
    let mut refused_validation = 0;
    facts.retain(|f| {
        if !eval.record(f.safety) {
            return false;
        }
        match catalog.validate(f) {
            Ok(()) => true,
            Err(_) => {
                refused_validation += 1;
                false
            }
        }
    });
    let permit = d0::commit_permit(Domain::D1, "safety-evaluation+type-validation+confidence-calibration")?;
    let (node, admitted) =
        qb.store.commit(&permit, &mut facts, &opts.actor, &format!("ingest:{}", book.id), &eval.digest(), true)?;
    progress(&format!("admitted {admitted} records under ledger node {}", node.seq));

    let fp_to_fuid: BTreeMap<&str, &str> = facts.iter().map(|f| (f.fingerprint.as_str(), f.fuid.as_str())).collect();
    let mut contradictions = 0;
    qb.store.write(|c| {
        let tx = c.unchecked_transaction()?;
        for (a, b) in &contra_pairs {
            if let (Some(fa), Some(fb)) = (fp_to_fuid.get(a.as_str()), fp_to_fuid.get(b.as_str())) {
                tx.execute(
                    "INSERT OR IGNORE INTO contradictions(a,b,kind,ts) VALUES(?1,?2,'polarity',?3)",
                    params![fa, fb, ingested],
                )?;
                contradictions += 1;
            }
        }
        save_work(&tx, &book, opts, &reports, &ents, &facts, ingested)?;
        tx.commit()?;
        Ok(())
    })?;

    let questions = crate::d4::pqg::generate(qb, &book.id, progress).unwrap_or_else(|e| {
        progress(&format!("question pre-computation failed: {e}"));
        0
    });

    Ok(IngestReport {
        work: book.id.clone(),
        title: book.title.clone(),
        author: book.author.clone(),
        chapters: book.chapters.len(),
        passages: book.passages.len(),
        words: book.words(),
        entities: ents.entities.len(),
        candidates: n_cands,
        admitted,
        refused_validation,
        refused_safety: eval.refused,
        contradictions,
        ledger_node: node.seq,
        questions,
        engines: reports,
        seconds: t0.elapsed().as_secs_f64(),
    })
}

/// Group candidates by semantic fingerprint: a restated assertion converges
/// on one record with several provenance branches, its evidence accumulated
/// per source class (engines), diversity-weighted.
pub fn merge(
    book: &Book,
    mut cands: Vec<Candidate>,
    reliability: &BTreeMap<String, f64>,
    ingested: i64,
    authority: f64,
) -> (Vec<FactUnit>, Vec<(String, String)>) {
    cands.sort_by(|a, b| {
        a.pos
            .cmp(&b.pos)
            .then_with(|| a.engine.cmp(&b.engine))
            .then_with(|| a.atom.canonical().cmp(&b.atom.canonical()))
            .then_with(|| a.quote.cmp(&b.quote))
    });
    let mut groups: BTreeMap<String, Vec<Candidate>> = BTreeMap::new();
    let mut order: Vec<String> = Vec::new();
    for c in cands {
        let fp = c.atom.fingerprint();
        let g = groups.entry(fp.clone()).or_default();
        if g.is_empty() {
            order.push(fp);
        }
        g.push(c);
    }
    let anchors: BTreeMap<u64, String> = book.passages.iter().filter_map(|p| p.anchor.as_ref().map(|a| (p.pos, a.cfi()))).collect();
    let mut facts = Vec::with_capacity(order.len());
    for fp in &order {
        let g = &groups[fp];
        let first = &g[0];
        let engines: BTreeSet<&str> = g.iter().map(|c| c.engine.as_str()).collect();
        let max_rel = engines.iter().map(|e| reliability.get(*e).copied().unwrap_or(0.6)).fold(0.0, f64::max);
        let mut ev = Evidence::prior(max_rel);
        let mut seen = BTreeSet::new();
        for c in g {
            if seen.insert((c.engine.clone(), c.pos)) {
                ev.support(&format!("engine:{}", c.engine), reliability.get(&c.engine).copied().unwrap_or(0.6) * c.weight);
            }
        }
        let verified = g.iter().any(|c| c.citation_verified);
        let quote_src = g.iter().find(|c| c.citation_verified).unwrap_or(first);
        let also: Vec<u64> =
            g.iter().map(|c| c.pos).filter(|p| *p != first.pos).collect::<BTreeSet<_>>().into_iter().take(16).collect();
        let mut labels = BTreeMap::new();
        for c in g {
            for (k, v) in &c.labels {
                labels.entry(k.clone()).or_insert_with(|| v.clone());
            }
        }
        let obj_text = match &first.atom.object {
            Value::Text(t) => t.clone(),
            _ => String::new(),
        };
        let mut f = FactUnit {
            fuid: String::new(),
            fingerprint: String::new(),
            type_ref: first.type_ref.clone(),
            atom: first.atom.clone(),
            group: "book".into(),
            applicability: None,
            temporal: Temporal { occurred: None, ingested, attested: None },
            spatial: None,
            narrative: Some(Narrative {
                work: book.id.clone(),
                pos: first.pos,
                chapter: first.chapter,
                also,
                cfi: anchors.get(&first.pos).cloned(),
                sentence: first.sentence,
            }),
            evidence: ev,
            source: SourceRef { class: "work-text".into(), id: book.id.clone(), authority },
            modality: "text".into(),
            safety: safety::classify(&format!("{} {}", quote_src.quote, obj_text)),
            acl: vec![format!("work:{}", book.id)],
            edges: vec![],
            supersedes: None,
            derivation: Derivation {
                kind: "engine".into(),
                engine: Some(engines.iter().copied().collect::<Vec<_>>().join("+")),
                prompt_hash: g.iter().find_map(|c| c.prompt_hash.clone()),
                citation_verified: Some(verified),
            },
            provenance: ProvRef { batch: 0, leaf: 0 },
            certification: None,
            quote: Some(quote_src.quote.clone()),
            labels,
            external_id: None,
            embedding: None,
        };
        f.seal();
        facts.push(f);
    }

    // Structural contradiction: the same assertion with both polarities.
    let mut by_claim: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    for (i, f) in facts.iter().enumerate() {
        let mut a = f.atom.clone();
        a.polarity = true;
        by_claim.entry(a.canonical()).or_default().push(i);
    }
    let mut pairs = Vec::new();
    for idxs in by_claim.values() {
        let pos: Vec<usize> = idxs.iter().copied().filter(|&i| facts[i].atom.polarity).collect();
        let neg: Vec<usize> = idxs.iter().copied().filter(|&i| !facts[i].atom.polarity).collect();
        for &p in &pos {
            for &n in &neg {
                let (wp, wn) = (facts[p].evidence.alpha, facts[n].evidence.alpha);
                facts[p].evidence.contradict(wn * 0.5);
                facts[n].evidence.contradict(wp * 0.5);
                pairs.push((facts[p].fingerprint.clone(), facts[n].fingerprint.clone()));
            }
        }
    }

    // Typed edges only where records actually connect (QBF-C035): an event
    // is followed by the same subject's next event in narrative order.
    let mut events: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    for (i, f) in facts.iter().enumerate() {
        if f.type_ref.starts_with("event.") {
            events.entry(f.atom.subject.clone()).or_default().push(i);
        }
    }
    for idxs in events.values() {
        let mut v = idxs.clone();
        v.sort_by_key(|&i| (facts[i].narrative.as_ref().unwrap().pos, facts[i].fuid.clone()));
        for w in v.windows(2) {
            let (a, b) = (w[0], w[1]);
            let (pa, pb) = (facts[a].narrative.as_ref().unwrap().pos, facts[b].narrative.as_ref().unwrap().pos);
            if pb > pa && pb - pa <= 60 {
                let target = facts[b].fuid.clone();
                facts[a].edges.push(Edge { class: EdgeClass::Temporal, predicate: "followed_by".into(), target, weight: 1.0 });
            }
        }
    }
    (facts, pairs)
}

fn save_work(
    tx: &rusqlite::Transaction,
    book: &Book,
    opts: &IngestOptions,
    reports: &[EngineReport],
    ents: &EntityTable,
    facts: &[FactUnit],
    ingested: i64,
) -> anyhow::Result<()> {
    let engines = reports.iter().map(|r| r.engine.clone()).collect::<Vec<_>>().join("+");
    tx.execute(
        "INSERT OR REPLACE INTO works(id,title,author,language,rights,rights_note,source_hash,chapters,positions,spoiler_default,ingested_at,engines,facts,genre)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)",
        params![
            book.id,
            book.title,
            book.author,
            book.language,
            opts.rights,
            opts.rights_note,
            book.source_hash,
            serde_json::to_string(&book.chapters)?,
            book.passages.len() as i64,
            1,
            ingested,
            engines,
            facts.len() as i64,
            opts.genre
        ],
    )?;
    {
        let mut st = tx.prepare_cached("INSERT OR REPLACE INTO passages(work,pos,chapter,kind,text,cfi,href) VALUES(?1,?2,?3,?4,?5,?6,?7)")?;
        for p in &book.passages {
            let (cfi, href) = match &p.anchor {
                Some(a) => (Some(a.cfi()), Some(a.href.clone())),
                None => (None, None),
            };
            st.execute(params![book.id, p.pos as i64, p.chapter as i64, p.kind, p.text, cfi, href])?;
        }
    }
    let mut st = tx.prepare_cached(
        "INSERT OR REPLACE INTO aliases(work,alias,concept,label,kind,freq,first_pos) VALUES(?1,?2,?3,?4,?5,?6,?7)",
    )?;
    let mut known: BTreeSet<&str> = BTreeSet::new();
    for e in &ents.entities {
        known.insert(&e.concept);
        for a in &e.aliases {
            st.execute(params![
                book.id,
                crate::util::alias_key(a),
                e.concept,
                e.label,
                e.kind,
                e.freq as i64,
                e.first_pos as i64
            ])?;
        }
    }
    // concepts introduced by extraction engines become matchable too
    let mut extra: BTreeMap<&str, (&str, u64, u64)> = BTreeMap::new();
    for f in facts {
        for (c, l) in &f.labels {
            if !known.contains(c.as_str()) {
                let pos = f.narrative.as_ref().map(|n| n.pos).unwrap_or(0);
                let e = extra.entry(c).or_insert((l.as_str(), 0, pos));
                e.1 += 1;
                e.2 = e.2.min(pos);
            }
        }
    }
    for (c, (l, n, pos)) in extra {
        let kind = if c.contains("/term-") { "concept" } else { "entity" };
        st.execute(params![book.id, crate::util::alias_key(l), c, l, kind, n as i64, pos as i64])?;
    }
    Ok(())
}

/// Supersede every record of a work before re-ingesting it.
fn retire_work(qb: &QueryBook, work: &str) -> anyhow::Result<()> {
    use tantivy::query::TermQuery;
    use tantivy::schema::IndexRecordOption;
    let q = TermQuery::new(tantivy::Term::from_field_text(qb.store.index.f.work, work), IndexRecordOption::Basic);
    let hits = qb.store.index.search(&q, 10_000_000)?;
    let permit = d0::commit_permit(Domain::D10, "rights-validation")?;
    for (_, fuid) in hits {
        if let Some(f) = qb.store.get(&fuid)? {
            qb.store.supersede(&permit, &f, "retired-by-reingest", "restatement")?;
        }
    }
    qb.store.index.commit()?;
    qb.store.write(|c| {
        c.execute("DELETE FROM passages WHERE work=?1", [work])?;
        c.execute("DELETE FROM aliases WHERE work=?1", [work])?;
        c.execute("DELETE FROM answer_units WHERE work=?1", [work])?;
        c.execute("DELETE FROM answer_deps WHERE work=?1", [work])?;
        Ok(())
    })
}
