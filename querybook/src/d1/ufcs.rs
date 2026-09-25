//! UFCS feed import: Fact Envelopes arriving from an external substrate cross
//! the federation boundary and are re-validated on the receiving side
//! (schema, governed predicate, safety, identity) before admission through
//! the ordinary D1->D2 conversion. A canonically identical assertion merges
//! as corroboration, not a duplicate (recorded in the immutable adjustment
//! history, QBF-C285).
//!
//! The exact wire format is described by a mapping file (JSON pointers), so a
//! new feed is connected by configuration rather than code.

use crate::app::QueryBook;
use crate::d0::{self, Domain, safety};
use crate::d2::{Atom, Certification, Derivation, Edge, EdgeClass, Evidence, FactUnit, ProvRef, SourceRef, Temporal, Value};
use crate::d3::Predicate;
use crate::util::{now_secs, sha256, slug};
use rayon::prelude::*;
use rusqlite::{OptionalExtension, params};
use serde::{Deserialize, Serialize};
use serde_json::Value as J;
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::time::Instant;

#[derive(Clone, Debug, Deserialize)]
pub struct Mapping {
    /// Feed name; becomes the corpus / source class "ufcs:<feed>".
    pub feed: String,
    /// Registered reliability of the feed as a source class.
    #[serde(default = "default_authority")]
    pub authority: f64,
    #[serde(default)]
    pub source: SourceCfg,
    pub fields: Fields,
    #[serde(default)]
    pub predicates: PredicateCfg,
    /// ACL placed on imported records ("public" = any reader who enables the corpus).
    #[serde(default = "default_acl")]
    pub acl: String,
    /// "none" | "fingerprint" (the envelope's id must equal our fingerprint)
    #[serde(default = "default_verify")]
    pub verify_id: String,
    #[serde(default = "default_batch")]
    pub batch: usize,
}
fn default_authority() -> f64 {
    0.85
}
fn default_acl() -> String {
    "public".into()
}
fn default_verify() -> String {
    "none".into()
}
fn default_batch() -> usize {
    50_000
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct SourceCfg {
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub auth_header: String,
    #[serde(default)]
    pub auth_env: String,
    #[serde(default)]
    pub auth_prefix: String,
    /// "json" (a page object holding an array) or "ndjson" (one record per line)
    #[serde(default = "default_format")]
    pub format: String,
    #[serde(default)]
    pub records_path: String,
    #[serde(default)]
    pub cursor_param: String,
    #[serde(default)]
    pub next_cursor_path: String,
    /// Alternative to cursors: offset pagination
    #[serde(default)]
    pub offset_param: String,
    #[serde(default)]
    pub page_size_param: String,
    #[serde(default = "default_page")]
    pub page_size: u64,
    #[serde(default)]
    pub query: BTreeMap<String, String>,
}
fn default_format() -> String {
    "json".into()
}
fn default_page() -> u64 {
    5000
}

#[derive(Clone, Debug, Default, Deserialize)]
pub struct Fields {
    #[serde(default)]
    pub id: String,
    pub subject: String,
    #[serde(default)]
    pub subject_label: String,
    pub predicate: String,
    pub object: String,
    #[serde(default)]
    pub object_label: String,
    /// value "entity" / "concept" / "node" marks a concept reference
    #[serde(default)]
    pub object_kind: String,
    #[serde(default)]
    pub polarity: String,
    #[serde(default)]
    pub group: String,
    #[serde(default)]
    pub args: String,
    #[serde(default)]
    pub alpha: String,
    #[serde(default)]
    pub beta: String,
    #[serde(default)]
    pub confidence: String,
    #[serde(default)]
    pub weight: String,
    #[serde(default)]
    pub authority: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub certified_at: String,
    #[serde(default)]
    pub signature: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub attested: String,
    #[serde(default)]
    pub occurred: String,
    #[serde(default)]
    pub links: String,
    #[serde(default)]
    pub link_target: String,
    #[serde(default)]
    pub link_type: String,
    #[serde(default)]
    pub text: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct PredicateCfg {
    #[serde(default = "yes")]
    pub auto_register: bool,
    #[serde(default)]
    pub map: BTreeMap<String, String>,
}

impl Default for PredicateCfg {
    fn default() -> Self {
        PredicateCfg { auto_register: true, map: BTreeMap::new() }
    }
}
fn yes() -> bool {
    true
}

#[derive(Debug, Default, Serialize)]
pub struct ImportReport {
    pub feed: String,
    pub read: u64,
    pub admitted: u64,
    pub corroborations: u64,
    /// already imported with identical content (skipped)
    pub unchanged: u64,
    /// same envelope id, changed content: prior record superseded
    pub revised: u64,
    pub refused: u64,
    pub refusals: BTreeMap<String, u64>,
    pub sample_errors: Vec<String>,
    pub predicates_registered: u64,
    pub ledger_nodes: u64,
    pub seconds: f64,
    pub per_second: f64,
    pub cursor: String,
}

fn ptr<'a>(v: &'a J, p: &str) -> Option<&'a J> {
    if p.is_empty() {
        return None;
    }
    v.pointer(p).filter(|x| !x.is_null())
}

fn s(v: &J, p: &str) -> Option<String> {
    ptr(v, p).map(|x| match x {
        J::String(s) => s.clone(),
        other => other.to_string(),
    })
}

fn f(v: &J, p: &str) -> Option<f64> {
    ptr(v, p).and_then(|x| x.as_f64().or_else(|| x.as_str().and_then(|s| s.parse().ok())))
}

fn concept_id(feed: &str, raw: &str) -> String {
    if raw.contains(':') && !raw.contains(' ') { raw.to_string() } else { format!("u:{feed}/{}", slug(raw)) }
}

pub struct Converter<'a> {
    pub m: &'a Mapping,
    pub ingested: i64,
}

impl<'a> Converter<'a> {
    fn predicate_for(&self, raw: &str) -> String {
        if let Some(p) = self.m.predicates.map.get(raw) {
            return p.clone();
        }
        format!("ufcs:{}", slug(raw).replace('-', "_"))
    }

    /// Envelope -> Fact Unit, or the reason it is refused.
    pub fn convert(&self, rec: &J) -> Result<FactUnit, String> {
        let fl = &self.m.fields;
        let feed = &self.m.feed;
        let subj_raw = s(rec, &fl.subject).ok_or("missing subject")?;
        let pred_raw = s(rec, &fl.predicate).ok_or("missing predicate")?;
        let obj = ptr(rec, &fl.object).ok_or("missing object")?;
        let subject = concept_id(feed, &subj_raw);
        let mut labels = BTreeMap::new();
        labels.insert(subject.clone(), s(rec, &fl.subject_label).unwrap_or_else(|| subj_raw.clone()));
        let kind = s(rec, &fl.object_kind).unwrap_or_default().to_lowercase();
        let object = match obj {
            J::Number(n) => Value::Number { value: n.as_f64().unwrap_or(0.0), unit: String::new() },
            J::Bool(b) => Value::Bool(*b),
            J::String(t) if matches!(kind.as_str(), "entity" | "concept" | "node" | "iri" | "uri") => {
                let c = concept_id(feed, t);
                labels.insert(c.clone(), s(rec, &fl.object_label).unwrap_or_else(|| t.clone()));
                Value::Concept(c)
            }
            J::String(t) => Value::Text(t.clone()),
            other => Value::Text(other.to_string()),
        };
        let mut args = BTreeMap::new();
        if let Some(J::Object(a)) = ptr(rec, &fl.args) {
            for (k, v) in a {
                let val = match v {
                    J::Number(n) => Value::Number { value: n.as_f64().unwrap_or(0.0), unit: String::new() },
                    J::String(t) => Value::Text(t.clone()),
                    other => Value::Text(other.to_string()),
                };
                args.insert(slug(k).replace('-', "_"), val);
            }
        }
        let polarity = ptr(rec, &fl.polarity)
            .map(|p| p.as_bool().unwrap_or(p.as_str() != Some("negative") && p.as_str() != Some("false")))
            .unwrap_or(true);
        let class = format!("ufcs:{feed}");
        let (alpha, beta) = match (f(rec, &fl.alpha), f(rec, &fl.beta)) {
            (Some(a), Some(b)) if a >= 0.0 && b >= 0.0 && a + b > 0.0 => (a, b),
            _ => {
                let c = f(rec, &fl.confidence).unwrap_or(self.m.authority).clamp(0.0, 1.0);
                let w = f(rec, &fl.weight).unwrap_or(2.0).max(0.1);
                (c * w, (1.0 - c) * w)
            }
        };
        let mut by_class = BTreeMap::new();
        by_class.insert(class.clone(), alpha);
        let certification = s(rec, &fl.status).map(|st| Certification {
            authority: s(rec, &fl.authority).unwrap_or_else(|| feed.clone()),
            status: st.to_lowercase(),
            certified_at: s(rec, &fl.certified_at),
            signature: s(rec, &fl.signature),
        });
        let mut edges = Vec::new();
        if let Some(J::Array(ls)) = ptr(rec, &fl.links) {
            for l in ls.iter().take(64) {
                let (target, ty) = match l {
                    J::String(t) => (t.clone(), String::from("related")),
                    J::Object(_) => {
                        (s(l, &fl.link_target).unwrap_or_default(), s(l, &fl.link_type).unwrap_or_else(|| "related".into()))
                    }
                    _ => continue,
                };
                if target.is_empty() {
                    continue;
                }
                let class = match ty.to_lowercase().as_str() {
                    t if t.contains("time") || t.contains("follow") || t.contains("precede") => EdgeClass::Temporal,
                    t if t.contains("edit") || t.contains("version") || t.contains("supersed") => EdgeClass::Editorial,
                    _ => EdgeClass::Semantic,
                };
                edges.push(Edge { class, predicate: ty, target, weight: 1.0 });
            }
        }
        let text = s(rec, &fl.text);
        let obj_text = match &object {
            Value::Text(t) => t.clone(),
            _ => String::new(),
        };
        let mut fact = FactUnit {
            fuid: String::new(),
            fingerprint: String::new(),
            type_ref: "ufcs.fact".into(),
            atom: Atom { subject, predicate: self.predicate_for(&pred_raw), object, args, polarity },
            group: s(rec, &fl.group).unwrap_or_else(|| "world".into()),
            applicability: None,
            temporal: Temporal { occurred: s(rec, &fl.occurred), ingested: self.ingested, attested: s(rec, &fl.attested) },
            spatial: None,
            narrative: None,
            evidence: Evidence { alpha, beta, by_class },
            source: SourceRef { class, id: s(rec, &fl.source).unwrap_or_else(|| feed.clone()), authority: self.m.authority },
            modality: "structured".into(),
            safety: safety::classify(&format!("{} {}", text.as_deref().unwrap_or(""), obj_text)),
            acl: vec![self.m.acl.clone()],
            edges,
            supersedes: None,
            derivation: Derivation { kind: "imported".into(), engine: None, prompt_hash: None, citation_verified: None },
            provenance: ProvRef { batch: 0, leaf: 0 },
            certification,
            quote: text,
            labels,
            external_id: s(rec, &fl.id),
            embedding: None,
        };
        fact.seal();
        if self.m.verify_id == "fingerprint" {
            if let Some(ext) = &fact.external_id {
                if *ext != fact.fingerprint {
                    return Err("content-derived identifier does not re-validate".into());
                }
            }
        }
        Ok(fact)
    }
}

pub fn load_mapping(path: &Path) -> anyhow::Result<Mapping> {
    let m: Mapping = toml::from_str(&std::fs::read_to_string(path)?)?;
    anyhow::ensure!(!m.feed.is_empty(), "mapping needs a feed name");
    anyhow::ensure!(m.authority > 0.0 && m.authority < 1.0, "authority must be in (0,1)");
    Ok(m)
}

struct Admitter<'a> {
    qb: &'a QueryBook,
    m: &'a Mapping,
    report: ImportReport,
    pending: Vec<FactUnit>,
    since_flush: usize,
    dry_run: bool,
}

impl<'a> Admitter<'a> {
    fn refuse(&mut self, why: String) {
        self.report.refused += 1;
        let key = why.split(':').next().unwrap_or(&why).to_string();
        *self.report.refusals.entry(key).or_insert(0) += 1;
        if self.report.sample_errors.len() < 8 {
            self.report.sample_errors.push(why);
        }
    }

    fn ensure_predicates(&mut self, facts: &[FactUnit]) -> anyhow::Result<()> {
        // argument slots each predicate is used with in this page
        let mut used: BTreeMap<String, std::collections::BTreeSet<String>> = BTreeMap::new();
        for f in facts {
            used.entry(f.atom.predicate.clone()).or_default().extend(f.atom.args.keys().cloned());
        }
        let (missing, widen): (Vec<String>, Vec<(String, Vec<String>)>) = {
            let cat = self.qb.catalog.read().unwrap();
            let missing = used.keys().filter(|p| cat.get(p).is_none()).cloned().collect();
            // only predicates this importer registers are widened; governed ones stay as defined
            let widen = used
                .iter()
                .filter_map(|(p, keys)| {
                    let spec = cat.get(p)?;
                    let new: Vec<String> = keys.iter().filter(|k| !spec.args.contains_key(*k)).cloned().collect();
                    (spec.type_ref == "ufcs.fact" && !new.is_empty()).then(|| (p.clone(), new))
                })
                .collect();
            (missing, widen)
        };
        if (missing.is_empty() && widen.is_empty()) || !self.m.predicates.auto_register || self.dry_run {
            return Ok(());
        }
        let mut cat = self.qb.catalog.write().unwrap();
        for (p, keys) in widen {
            cat.extend_args(&self.qb.store, &p, &keys, &self.qb.cfg.operator.name)?;
        }
        for p in missing {
            let args: BTreeMap<String, String> = used[&p].iter().map(|k| (k.clone(), "any".to_string())).collect();
            let label = p.trim_start_matches("ufcs:").replace('_', " ");
            cat.register(
                &self.qb.store,
                Predicate {
                    id: p.clone(),
                    label: label.clone(),
                    type_ref: "ufcs.fact".into(),
                    object: "any".into(),
                    functional: false,
                    symmetric: false,
                    edge: "semantic".into(),
                    args,
                    template: format!("{{s}} {label} {{o}}."),
                    question: String::new(),
                    describe: format!("Imported from UFCS feed {}", self.m.feed),
                    inverse: None,
                },
                &self.qb.cfg.operator.name,
            )?;
            self.report.predicates_registered += 1;
        }
        Ok(())
    }

    fn push_page(&mut self, conv: &Converter, records: &[J]) -> anyhow::Result<()> {
        self.report.read += records.len() as u64;
        let t_conv = Instant::now();
        let results: Vec<Result<FactUnit, String>> = records.par_iter().map(|r| conv.convert(r)).collect();
        let mut ok = Vec::with_capacity(results.len());
        for r in results {
            match r {
                Ok(f) => ok.push(f),
                Err(e) => self.refuse(e),
            }
        }
        if std::env::var("QB_DEBUG").is_ok() {
            eprintln!("  page: convert {} ms for {}", t_conv.elapsed().as_millis(), records.len());
        }
        self.ensure_predicates(&ok)?;
        let cat = self.qb.catalog.read().unwrap().clone();
        for f in ok {
            if f.safety == crate::d0::SafetyClass::Prohibited {
                self.refuse("safety: prohibited".into());
                continue;
            }
            if let Err(e) = cat.validate(&f) {
                self.refuse(format!("validation: {e}"));
                continue;
            }
            self.pending.push(f);
        }
        if self.pending.len() >= self.m.batch {
            self.commit()?;
        }
        Ok(())
    }

    fn commit(&mut self) -> anyhow::Result<()> {
        if self.pending.is_empty() {
            return Ok(());
        }
        let mut batch = std::mem::take(&mut self.pending);
        // an envelope already imported unchanged is skipped; one whose content
        // changed under the same id supersedes its prior record (correction)
        let mut revised: Vec<(String, String)> = Vec::new(); // (new fuid, prior fuid)
        if !self.dry_run {
            let feed = self.m.feed.clone();
            let (keep, rev, unchanged) = self.qb.store.write(|c| {
                let tx = c.unchecked_transaction()?;
                let mut keep = Vec::with_capacity(batch.len());
                let mut rev = Vec::new();
                let mut unchanged = 0u64;
                {
                    let mut get = tx.prepare_cached("SELECT fp, fuid FROM ext_index WHERE k=?1")?;
                    let mut put = tx.prepare_cached("INSERT OR REPLACE INTO ext_index(k, fp, fuid) VALUES(?1, ?2, ?3)")?;
                    for f in std::mem::take(&mut batch) {
                        let Some(ext) = f.external_id.as_deref() else {
                            keep.push(f);
                            continue;
                        };
                        let k = sha256(format!("{feed}|{ext}").as_bytes())[..16].to_vec();
                        let fp = sha256(f.fingerprint.as_bytes())[..16].to_vec();
                        let prior: Option<(Vec<u8>, String)> = get.query_row([&k], |r| Ok((r.get(0)?, r.get(1)?))).optional()?;
                        match prior {
                            Some((pfp, _)) if pfp == fp => unchanged += 1,
                            Some((_, pfuid)) => {
                                put.execute(params![k, fp, f.fuid])?;
                                rev.push((f.fuid.clone(), pfuid));
                                keep.push(f);
                            }
                            None => {
                                put.execute(params![k, fp, f.fuid])?;
                                keep.push(f);
                            }
                        }
                    }
                }
                tx.commit()?;
                Ok((keep, rev, unchanged))
            })?;
            batch = keep;
            revised = rev;
            self.report.unchanged += unchanged;
        }
        // merge canonically identical assertions: within the batch, then against the store
        batch.sort_by(|a, b| a.fingerprint.cmp(&b.fingerprint).then_with(|| a.fuid.cmp(&b.fuid)));
        let mut uniq: Vec<FactUnit> = Vec::with_capacity(batch.len());
        let mut corroborate: Vec<(String, f64, String)> = Vec::new(); // (fingerprint, weight, class)
        for f in batch {
            if let Some(last) = uniq.last() {
                if last.fingerprint == f.fingerprint {
                    corroborate.push((f.fingerprint.clone(), f.evidence.alpha, f.source.class.clone()));
                    continue;
                }
            }
            uniq.push(f);
        }
        if self.dry_run {
            self.report.admitted += uniq.len() as u64;
            self.report.corroborations += corroborate.len() as u64;
            return Ok(());
        }
        let qb = self.qb;
        let now = now_secs();
        let t_fp = Instant::now();
        let existing: BTreeMap<String, String> = qb.store.write(|c| {
            let tx = c.unchecked_transaction()?;
            let mut out = BTreeMap::new();
            {
                let mut ins = tx.prepare_cached("INSERT OR IGNORE INTO fp_index(fp, fuid) VALUES(?1, ?2)")?;
                let mut get = tx.prepare_cached("SELECT fuid FROM fp_index WHERE fp=?1")?;
                for f in &uniq {
                    let fp = &sha256(f.fingerprint.as_bytes())[..16];
                    if ins.execute(params![fp, f.fuid])? == 0 {
                        let prior: String = get.query_row([fp], |r| r.get(0))?;
                        out.insert(f.fingerprint.clone(), prior);
                    }
                }
            }
            tx.commit()?;
            Ok(out)
        })?;
        let mut fresh = Vec::with_capacity(uniq.len());
        for f in uniq {
            if existing.contains_key(&f.fingerprint) {
                corroborate.push((f.fingerprint.clone(), f.evidence.alpha, f.source.class.clone()));
            } else {
                fresh.push(f);
            }
        }
        let mut eval = safety::Evaluation::new("federation re-validation");
        for f in &fresh {
            eval.record(f.safety);
        }
        let fp_ms = t_fp.elapsed().as_millis();
        let permit = d0::commit_permit(Domain::D1, "safety-evaluation+type-validation+confidence-calibration")?;
        let t_c = Instant::now();
        let (_, inserted) = qb.store.commit(
            &permit,
            &mut fresh,
            &qb.cfg.operator.name,
            &format!("ufcs-import:{}", self.m.feed),
            &eval.digest(),
            false,
        )?;
        if std::env::var("QB_DEBUG").is_ok() {
            eprintln!("  batch: fingerprint index {fp_ms} ms, store+index {} ms for {inserted}", t_c.elapsed().as_millis());
        }
        self.report.ledger_nodes += 1;
        self.report.admitted += inserted as u64;
        if !revised.is_empty() {
            for (new_fuid, prior) in &revised {
                if let Some(old) = qb.store.get(prior)? {
                    qb.store.supersede(&permit, &old, new_fuid, "correction")?;
                    self.report.revised += 1;
                }
            }
        }
        // corroboration is recorded in the immutable adjustment history
        if !corroborate.is_empty() {
            let fps: BTreeMap<String, String> = qb.store.read(|c| {
                let mut get = c.prepare_cached("SELECT fuid FROM fp_index WHERE fp=?1")?;
                let mut m = BTreeMap::new();
                for (fp, _, _) in &corroborate {
                    if let Ok(fu) = get.query_row([&sha256(fp.as_bytes())[..16]], |r| r.get::<_, String>(0)) {
                        m.insert(fp.clone(), fu);
                    }
                }
                Ok(m)
            })?;
            qb.store.write(|c| {
                let tx = c.unchecked_transaction()?;
                {
                    let mut ins = tx.prepare_cached(
                        "INSERT INTO adjustments(fuid, seq, ts, d_alpha, d_beta, class, reason)
                         VALUES(?1, COALESCE((SELECT MAX(seq)+1 FROM adjustments WHERE fuid=?1), 1), ?2, ?3, 0, ?4, 'corroboration')",
                    )?;
                    for (fp, w, class) in &corroborate {
                        if let Some(fu) = fps.get(fp) {
                            ins.execute(params![fu, now, w, class])?;
                        }
                    }
                }
                tx.commit()?;
                Ok(())
            })?;
            self.report.corroborations += corroborate.len() as u64;
        }
        self.since_flush += inserted;
        if self.since_flush >= 1_000_000 {
            qb.store.checkpoint()?;
            self.since_flush = 0;
        }
        Ok(())
    }
}

pub fn ensure_tables(qb: &QueryBook) -> anyhow::Result<()> {
    qb.store.write(|c| {
        c.execute_batch(
            "CREATE TABLE IF NOT EXISTS fp_index(fp BLOB PRIMARY KEY, fuid TEXT NOT NULL) WITHOUT ROWID;
             CREATE TABLE IF NOT EXISTS ext_index(k BLOB PRIMARY KEY, fp BLOB NOT NULL, fuid TEXT NOT NULL) WITHOUT ROWID;",
        )?;
        Ok(())
    })
}

fn save_cursor(qb: &QueryBook, feed: &str, cursor: &str, r: &ImportReport) -> anyhow::Result<()> {
    qb.store.write(|c| {
        c.execute(
            "INSERT INTO import_cursors(feed, cursor, imported, refused, updated) VALUES(?1,?2,?3,?4,?5)
             ON CONFLICT(feed) DO UPDATE SET cursor=excluded.cursor, imported=import_cursors.imported+excluded.imported, refused=import_cursors.refused+excluded.refused, updated=excluded.updated",
            params![feed, cursor, r.admitted as i64, r.refused as i64, now_secs()],
        )?;
        Ok(())
    })
}

pub fn import(
    qb: &QueryBook,
    mapping: &Path,
    file: Option<&Path>,
    limit: u64,
    dry_run: bool,
    progress: &dyn Fn(&str),
) -> anyhow::Result<ImportReport> {
    ensure_tables(qb)?;
    let m = load_mapping(mapping)?;
    let feed_key = format!("ufcs:{}", m.feed);
    let t0 = Instant::now();
    let conv = Converter { m: &m, ingested: now_secs() };
    let mut ad = Admitter {
        qb,
        m: &m,
        report: ImportReport { feed: feed_key.clone(), ..Default::default() },
        pending: vec![],
        since_flush: 0,
        dry_run,
    };
    let tick = |ad: &Admitter| {
        let secs = t0.elapsed().as_secs_f64().max(1e-3);
        progress(&format!(
            "read {} admitted {} corroborations {} refused {} ({:.0}/s)",
            ad.report.read,
            ad.report.admitted,
            ad.report.corroborations,
            ad.report.refused,
            ad.report.read as f64 / secs
        ))
    };
    if let Some(root) = file {
        // a directory imports every .ndjson/.json file in it, in name order
        let files: Vec<std::path::PathBuf> = if root.is_dir() {
            let mut v: Vec<_> = std::fs::read_dir(root)?
                .flatten()
                .map(|e| e.path())
                .filter(|p| matches!(p.extension().and_then(|e| e.to_str()), Some("ndjson" | "json" | "jsonl")))
                .collect();
            v.sort();
            v
        } else {
            vec![root.to_path_buf()]
        };
        for path in &files {
            let path = path.as_path();
            if files.len() > 1 {
                progress(&format!("{}", path.display()));
            }
            let rdr = BufReader::with_capacity(1 << 20, std::fs::File::open(path)?);
            let is_array = path.extension().and_then(|e| e.to_str()) == Some("json");
            if is_array {
                let v: J = serde_json::from_reader(rdr)?;
                let arr = if m.source.records_path.is_empty() {
                    v.as_array().cloned()
                } else {
                    v.pointer(&m.source.records_path).and_then(|x| x.as_array()).cloned()
                };
                let arr = arr.ok_or_else(|| anyhow::anyhow!("no record array found (set source.records_path)"))?;
                for chunk in arr.chunks(10_000) {
                    ad.push_page(&conv, chunk)?;
                    tick(&ad);
                    if limit > 0 && ad.report.read >= limit {
                        break;
                    }
                }
            } else {
                let mut page = Vec::with_capacity(10_000);
                for line in rdr.lines() {
                    let line = line?;
                    if line.trim().is_empty() {
                        continue;
                    }
                    match serde_json::from_str::<J>(&line) {
                        Ok(v) => page.push(v),
                        Err(e) => ad.refuse(format!("malformed: {e}")),
                    }
                    if page.len() >= 10_000 {
                        ad.push_page(&conv, &page)?;
                        page.clear();
                        tick(&ad);
                    }
                    if limit > 0 && ad.report.read + page.len() as u64 >= limit {
                        break;
                    }
                }
                ad.push_page(&conv, &page)?;
            }
            if limit > 0 && ad.report.read >= limit {
                break;
            }
        }
        ad.commit()?;
    } else {
        anyhow::ensure!(!m.source.url.is_empty(), "mapping has no source.url; pass --file for a local dump");
        let http = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(300)).build()?;
        let mut cursor: String = qb
            .store
            .read(|c| Ok(c.query_row("SELECT cursor FROM import_cursors WHERE feed=?1", [&feed_key], |r| r.get(0)).ok()))?
            .unwrap_or_default();
        let mut offset: u64 = cursor.parse().unwrap_or(0);
        if !cursor.is_empty() {
            progress(&format!("resuming {feed_key} from cursor {cursor}"));
        }
        loop {
            let mut req = http.get(&m.source.url);
            let mut q: Vec<(String, String)> = m.source.query.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
            if !m.source.page_size_param.is_empty() {
                q.push((m.source.page_size_param.clone(), m.source.page_size.to_string()));
            }
            if !m.source.cursor_param.is_empty() && !cursor.is_empty() {
                q.push((m.source.cursor_param.clone(), cursor.clone()));
            }
            if !m.source.offset_param.is_empty() {
                q.push((m.source.offset_param.clone(), offset.to_string()));
            }
            req = req.query(&q);
            if !m.source.auth_header.is_empty() {
                let token = std::env::var(&m.source.auth_env)
                    .map_err(|_| anyhow::anyhow!("set {} for the UFCS API", m.source.auth_env))?;
                req = req.header(&m.source.auth_header, format!("{}{}", m.source.auth_prefix, token));
            }
            let mut attempt = 0;
            let body = loop {
                match req.try_clone().expect("clonable").send() {
                    Ok(r) if r.status().is_success() => break r.text()?,
                    Ok(r) if (r.status().as_u16() == 429 || r.status().is_server_error()) && attempt < 6 => {}
                    Ok(r) => {
                        anyhow::bail!("UFCS API HTTP {}: {}", r.status(), crate::util::clip(&r.text().unwrap_or_default(), 300))
                    }
                    Err(e) if attempt < 6 => progress(&format!("network: {e}")),
                    Err(e) => return Err(e.into()),
                }
                attempt += 1;
                std::thread::sleep(std::time::Duration::from_secs(2u64.pow(attempt)));
            };
            let records: Vec<J> = if m.source.format == "ndjson" {
                body.lines().filter(|l| !l.trim().is_empty()).filter_map(|l| serde_json::from_str(l).ok()).collect()
            } else {
                let v: J = serde_json::from_str(&body)?;
                let arr = if m.source.records_path.is_empty() {
                    v.as_array().cloned()
                } else {
                    v.pointer(&m.source.records_path).and_then(|x| x.as_array()).cloned()
                };
                let next = s(&v, &m.source.next_cursor_path).unwrap_or_default();
                cursor = next;
                arr.unwrap_or_default()
            };
            let n = records.len() as u64;
            let (a0, r0) = (ad.report.admitted, ad.report.refused);
            ad.push_page(&conv, &records)?;
            ad.commit()?;
            offset += n;
            if !m.source.offset_param.is_empty() {
                cursor = offset.to_string();
            }
            if !dry_run {
                // the cursor advances only after the page is committed: a crash resumes here
                let inc =
                    ImportReport { admitted: ad.report.admitted - a0, refused: ad.report.refused - r0, ..Default::default() };
                save_cursor(qb, &feed_key, &cursor, &inc)?;
            }
            tick(&ad);
            if n == 0 || (cursor.is_empty() && m.source.offset_param.is_empty()) || (limit > 0 && ad.report.read >= limit) {
                break;
            }
        }
    }
    if !dry_run {
        qb.store.flush()?;
        if file.is_some() {
            save_cursor(qb, &feed_key, "file", &ad.report)?;
        }
    }
    ad.report.seconds = t0.elapsed().as_secs_f64();
    ad.report.per_second = ad.report.read as f64 / ad.report.seconds.max(1e-3);
    ad.report.cursor = if dry_run {
        String::new()
    } else {
        qb.store.read(|c| {
            Ok(c.query_row("SELECT cursor FROM import_cursors WHERE feed=?1", [&feed_key], |r| r.get(0)).unwrap_or_default())
        })?
    };
    Ok(ad.report)
}

// ---- scale benchmark -----------------------------------------------------

const SYL: &[&str] = &["ka", "lo", "mi", "ne", "ru", "sa", "to", "vi", "ze", "po", "an", "el", "or", "ti", "ba", "de"];
const PREDS: &[&str] = &[
    "born_in",
    "located_in",
    "capital_of",
    "member_of",
    "founded_by",
    "author_of",
    "part_of",
    "population",
    "area",
    "discovered_by",
    "occupation",
    "citizen_of",
    "spouse_of",
    "child_of",
    "employer",
    "genre",
    "language",
    "currency",
    "elevation",
    "field_of_work",
];

fn name(mut k: u64) -> String {
    let mut s = String::new();
    for _ in 0..3 {
        s.push_str(SYL[(k % 16) as usize]);
        k /= 16;
    }
    let mut c = s.chars();
    let first = c.next().unwrap().to_uppercase().collect::<String>();
    format!("{first}{} {}", c.as_str(), (k % 997))
}

/// Generate `n` synthetic UFCS envelopes and admit them through the real
/// import path, then time representative FQL queries.
pub fn bench_synthetic(qb: &QueryBook, n: u64, batch: usize) -> anyhow::Result<()> {
    ensure_tables(qb)?;
    let m = Mapping {
        feed: "synthetic".into(),
        authority: 0.8,
        source: SourceCfg::default(),
        fields: Fields {
            id: "/id".into(),
            subject: "/s".into(),
            subject_label: "/sl".into(),
            predicate: "/p".into(),
            object: "/o".into(),
            object_label: "/ol".into(),
            object_kind: "/ok".into(),
            confidence: "/c".into(),
            weight: "/w".into(),
            status: "/st".into(),
            text: "/t".into(),
            ..Default::default()
        },
        predicates: PredicateCfg { auto_register: true, map: BTreeMap::new() },
        acl: "public".into(),
        verify_id: "none".into(),
        batch,
    };
    let conv = Converter { m: &m, ingested: now_secs() };
    let mut ad = Admitter { qb, m: &m, report: ImportReport::default(), pending: vec![], since_flush: 0, dry_run: false };
    let entities = (n / 8).max(1000);
    let t0 = Instant::now();
    let mut i = 0u64;
    while i < n {
        let page: Vec<J> = (i..(i + 10_000).min(n))
            .into_par_iter()
            .map(|k| {
                let h = u64::from_le_bytes(sha256(&k.to_le_bytes())[..8].try_into().unwrap());
                let s = h % entities;
                let p = PREDS[((h >> 20) % PREDS.len() as u64) as usize];
                let concept_obj = (h >> 30) % 3 != 0;
                let o = (h >> 34) % entities;
                let (ov, ok, ol) = if concept_obj {
                    (J::String(format!("e{o}")), "entity", name(o))
                } else {
                    (J::from(((h >> 40) % 100_000) as f64), "literal", String::new())
                };
                serde_json::json!({
                    "id": format!("syn-{k}"), "s": format!("e{s}"), "sl": name(s), "p": p, "o": ov, "ok": ok, "ol": ol,
                    "c": 0.6 + ((h >> 50) % 40) as f64 / 100.0, "w": 3.0, "st": if h % 5 == 0 { "certified" } else { "uncertified" },
                    "t": format!("{} {} {}", name(s), p.replace('_', " "), if concept_obj { name(o) } else { ((h >> 40) % 100_000).to_string() })
                })
            })
            .collect();
        ad.push_page(&conv, &page)?;
        i += page.len() as u64;
        if i % 200_000 == 0 || i == n {
            let secs = t0.elapsed().as_secs_f64();
            eprintln!("  {i}/{n} records, {:.0}/s", i as f64 / secs);
        }
    }
    ad.commit()?;
    qb.store.flush()?;
    let secs = t0.elapsed().as_secs_f64();
    save_cursor(qb, "ufcs:synthetic", "bench", &ad.report)?;
    println!(
        "ingest: {} admitted, {} corroborations, {:.1}s, {:.0} records/s",
        ad.report.admitted,
        ad.report.corroborations,
        secs,
        n as f64 / secs
    );
    // query latency: joint structure + trust filter
    use crate::d4::fql::{Fql, compile};
    let mut lat = Vec::new();
    for k in 0..200u64 {
        let h = u64::from_le_bytes(sha256(&(k + 7_777_777).to_le_bytes())[..8].try_into().unwrap());
        let who = name(h % entities);
        let q =
            Fql { text: vec![who.split(' ').next().unwrap().to_lowercase()], min_trust: 0.2, limit: 160, ..Default::default() };
        let scope = world_scope();
        let t = Instant::now();
        let query = compile(&qb.store.index, &scope, &q);
        let hits = qb.store.index.search(query.as_ref(), q.limit)?;
        let fuids: Vec<String> = hits.iter().map(|h| h.1.clone()).collect();
        let _facts = qb.store.get_many(&fuids)?;
        lat.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    lat.sort_by(|a, b| a.partial_cmp(b).unwrap());
    println!(
        "FQL retrieve+load (160 candidates, trust>=0.2, corpus+acl filters): p50 {:.1} ms, p95 {:.1} ms, max {:.1} ms over {} records",
        lat[lat.len() / 2],
        lat[lat.len() * 95 / 100],
        lat[lat.len() - 1],
        qb.store.index.num_docs()
    );
    let db = std::fs::metadata(qb.store.dir.join("querybook.sqlite")).map(|m| m.len()).unwrap_or(0);
    let ix: u64 = walk_size(&qb.store.dir.join("index"));
    println!(
        "disk: store {:.2} GB, index {:.2} GB ({:.0} bytes/record)",
        db as f64 / 1e9,
        ix as f64 / 1e9,
        (db + ix) as f64 / qb.store.index.num_docs().max(1) as f64
    );
    Ok(())
}

fn world_scope() -> crate::d8::Scope {
    crate::d8::world_scope(&["ufcs:synthetic".to_string()])
}

fn walk_size(p: &Path) -> u64 {
    std::fs::read_dir(p).map(|rd| rd.flatten().map(|e| e.metadata().map(|m| m.len()).unwrap_or(0)).sum()).unwrap_or(0)
}

/// Write a work's records as a concatenated QBF frame stream.
pub fn export_qbf(qb: &QueryBook, work: &str, out: &Path) -> anyhow::Result<usize> {
    use tantivy::query::TermQuery;
    let q =
        TermQuery::new(tantivy::Term::from_field_text(qb.store.index.f.work, work), tantivy::schema::IndexRecordOption::Basic);
    let hits = qb.store.index.search(&q, 50_000_000)?;
    let fuids: Vec<String> = hits.into_iter().map(|h| h.1).collect();
    let mut w = std::io::BufWriter::new(std::fs::File::create(out)?);
    let mut n = 0;
    for chunk in fuids.chunks(5000) {
        for f in qb.store.get_many(chunk)? {
            use std::io::Write;
            w.write_all(&crate::d2::fact::encode(&f))?;
            n += 1;
        }
    }
    Ok(n)
}
