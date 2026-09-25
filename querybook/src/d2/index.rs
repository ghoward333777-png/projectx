//! Retrieval index over Fact Units (QBF-C033 storage architecture).
//!
//! The host store (SQLite) holds each record as an opaque blob it never
//! parses (QBF-C289). This index is QueryBook's own: it lets FQL filter on
//! semantic structure and on certification trust, freshness and status in a
//! single query (QBF-C290 edge translation happens in d4::fql).

use super::fact::FactUnit;
use std::path::Path;
use std::sync::Mutex;
use tantivy::collector::{Count, TopDocs};
use tantivy::query::Query;
use tantivy::schema::{
    FAST, Field, INDEXED, IndexRecordOption, NumericOptions, STORED, STRING, Schema, TextFieldIndexing, TextOptions, Value,
};
use tantivy::{DocAddress, Index, IndexReader, IndexWriter, ReloadPolicy, TantivyDocument, Term, doc};

#[derive(Clone, Copy)]
pub struct Fields {
    pub fuid: Field,
    pub text: Field,
    pub concepts: Field,
    pub predicate: Field,
    pub type_ref: Field,
    pub work: Field,
    pub corpus: Field,
    pub acl: Field,
    pub group: Field,
    pub status: Field,
    pub trust: Field,
    pub pos: Field,
    pub chapter: Field,
    pub fresh: Field,
    pub batch: Field,
    pub leaf: Field,
    pub links: Field,
    pub fingerprint: Field,
    pub safety: Field,
}

/// The index writer is held only while writing: the server and the `qb`
/// command line (ingest, UFCS import) can then share one data directory.
/// Readers reload on commits made by any process.
pub struct FactIndex {
    pub index: Index,
    pub reader: IndexReader,
    writer: Mutex<Option<IndexWriter>>,
    heap: usize,
    pub f: Fields,
}

fn schema() -> (Schema, Fields) {
    let mut b = Schema::builder();
    let text_opts = TextOptions::default().set_indexing_options(
        TextFieldIndexing::default().set_tokenizer("en_stem").set_index_option(IndexRecordOption::WithFreqsAndPositions),
    );
    let num = NumericOptions::default().set_indexed().set_fast();
    let f = Fields {
        fuid: b.add_text_field("fuid", STRING | STORED),
        text: b.add_text_field("text", text_opts),
        concepts: b.add_text_field("concepts", STRING),
        predicate: b.add_text_field("predicate", STRING),
        type_ref: b.add_text_field("type_ref", STRING),
        work: b.add_text_field("work", STRING),
        corpus: b.add_text_field("corpus", STRING),
        acl: b.add_text_field("acl", STRING),
        group: b.add_text_field("group", STRING),
        status: b.add_text_field("status", STRING),
        trust: b.add_f64_field("trust", num.clone()),
        pos: b.add_u64_field("pos", num.clone()),
        chapter: b.add_u64_field("chapter", num.clone()),
        fresh: b.add_i64_field("fresh", num.clone()),
        batch: b.add_u64_field("batch", num.clone()),
        leaf: b.add_u64_field("leaf", FAST | INDEXED),
        links: b.add_text_field("links", STRING),
        fingerprint: b.add_text_field("fingerprint", STRING),
        safety: b.add_u64_field("safety", num),
    };
    (b.build(), f)
}

impl FactIndex {
    pub fn open(dir: &Path, heap_mb: usize) -> anyhow::Result<FactIndex> {
        std::fs::create_dir_all(dir)?;
        let (schema, f) = schema();
        let mmap = tantivy::directory::MmapDirectory::open(dir)?;
        let index = Index::open_or_create(mmap, schema)?;
        let reader = index.reader_builder().reload_policy(ReloadPolicy::OnCommitWithDelay).try_into()?;
        Ok(FactIndex { index, reader, writer: Mutex::new(None), heap: heap_mb.max(64) * 1_000_000, f })
    }

    /// Run `f` with the writer, acquiring the directory lock if needed
    /// (waiting up to ten minutes for another process to release it).
    fn with_writer<T>(&self, f: impl FnOnce(&mut IndexWriter) -> anyhow::Result<T>) -> anyhow::Result<T> {
        let mut guard = self.writer.lock().unwrap();
        if guard.is_none() {
            let mut waited = 0;
            loop {
                match self.index.writer(self.heap) {
                    Ok(w) => {
                        *guard = Some(w);
                        break;
                    }
                    Err(tantivy::TantivyError::LockFailure(..)) if waited < 600 => {
                        if waited % 30 == 0 {
                            eprintln!("  index is being written by another process; waiting…");
                        }
                        std::thread::sleep(std::time::Duration::from_secs(1));
                        waited += 1;
                    }
                    Err(e) => return Err(e.into()),
                }
            }
        }
        f(guard.as_mut().unwrap())
    }

    /// Hold the writer lock (no commit from this or any other process) while `f` runs.
    pub fn hold_writer<T>(&self, f: impl FnOnce() -> anyhow::Result<T>) -> anyhow::Result<T> {
        self.with_writer(|_| f())
    }

    /// Everything the index knows about a record, derived from the record.
    pub fn document(&self, fact: &FactUnit, searchable_text: &str) -> TantivyDocument {
        let f = &self.f;
        let mut d = doc!(
            f.fuid => fact.fuid.clone(),
            f.text => searchable_text.to_string(),
            f.predicate => fact.atom.predicate.clone(),
            f.type_ref => fact.type_ref.clone(),
            f.group => fact.group.clone(),
            f.status => fact.status().to_string(),
            f.trust => fact.trust(),
            f.fresh => fact.temporal.ingested,
            f.batch => fact.provenance.batch,
            f.leaf => fact.provenance.leaf as u64,
            f.fingerprint => fact.fingerprint.clone(),
            f.safety => fact.safety.as_u64(),
        );
        for c in fact.atom.concepts() {
            d.add_text(f.concepts, c);
        }
        for a in &fact.acl {
            d.add_text(f.acl, a);
        }
        for e in &fact.edges {
            d.add_text(f.links, &e.target);
        }
        match &fact.narrative {
            Some(n) => {
                d.add_text(f.work, &n.work);
                d.add_text(f.corpus, "book");
                d.add_u64(f.pos, n.pos);
                d.add_u64(f.chapter, n.chapter as u64);
            }
            None => {
                d.add_text(f.corpus, &fact.source.class);
                d.add_u64(f.pos, 0);
                d.add_u64(f.chapter, 0);
            }
        }
        d
    }

    pub fn add(&self, doc: TantivyDocument) -> anyhow::Result<()> {
        self.with_writer(|w| {
            w.add_document(doc)?;
            Ok(())
        })
    }

    pub fn add_many(&self, docs: Vec<TantivyDocument>) -> anyhow::Result<()> {
        if docs.is_empty() {
            return Ok(());
        }
        self.with_writer(|w| {
            for d in docs {
                w.add_document(d)?;
            }
            Ok(())
        })
    }

    pub fn delete_fuid(&self, fuid: &str) -> anyhow::Result<()> {
        let t = Term::from_field_text(self.f.fuid, fuid);
        self.with_writer(|w| {
            w.delete_term(t);
            Ok(())
        })
    }

    /// Commit pending writes and release the directory lock.
    pub fn commit(&self) -> anyhow::Result<()> {
        let taken = self.writer.lock().unwrap().take();
        if let Some(mut w) = taken {
            w.commit()?;
            w.wait_merging_threads()?;
        }
        self.reader.reload()?;
        Ok(())
    }

    /// Commit but keep the lock (bulk import checkpoints).
    pub fn checkpoint(&self) -> anyhow::Result<()> {
        if let Some(w) = self.writer.lock().unwrap().as_mut() {
            w.commit()?;
        }
        self.reader.reload()?;
        Ok(())
    }

    /// Analyze free text with the index's own stemming analyzer.
    pub fn analyze(&self, text: &str) -> Vec<String> {
        let mut out = Vec::new();
        if let Ok(mut an) = self.index.tokenizer_for_field(self.f.text) {
            let mut ts = an.token_stream(text);
            while ts.advance() {
                out.push(ts.token().text.clone());
            }
        }
        out
    }

    /// Execute a composed FQL query; returns (score, fuid) best first with a
    /// deterministic tie-break on FUID.
    pub fn search(&self, q: &dyn Query, limit: usize) -> anyhow::Result<Vec<(f32, String)>> {
        let searcher = self.reader.searcher();
        let top = searcher.search(q, &TopDocs::with_limit(limit).order_by_score())?;
        let mut out = Vec::with_capacity(top.len());
        for (score, addr) in top {
            out.push((score, self.fuid_at(&searcher, addr)?));
        }
        out.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal).then_with(|| a.1.cmp(&b.1)));
        Ok(out)
    }

    pub fn count(&self, q: &dyn Query) -> anyhow::Result<usize> {
        Ok(self.reader.searcher().search(q, &Count)?)
    }

    fn fuid_at(&self, searcher: &tantivy::Searcher, addr: DocAddress) -> anyhow::Result<String> {
        let d: TantivyDocument = searcher.doc(addr)?;
        Ok(d.get_first(self.f.fuid).and_then(|v| v.as_str()).unwrap_or_default().to_string())
    }

    pub fn num_docs(&self) -> u64 {
        self.reader.searcher().num_docs()
    }
}
