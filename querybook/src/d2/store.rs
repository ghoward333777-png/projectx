//! D2 custody. The only code with write authority over the substrate; every
//! write requires a `CommitPermit`, which only a satisfied matrix crossing can
//! mint. The SQLite table holds each record's QBF frame as an opaque blob
//! keyed by FUID (QBF-C289): the host database never parses, indexes or
//! interprets a record.

use super::fact::{FactUnit, decode, encode_compact};
use super::index::FactIndex;
use super::ledger::{self, Append, Keys, Node};
use crate::d0::CommitPermit;
use crate::util::{now_secs, sha256_hex};
use rusqlite::{Connection, OptionalExtension, params};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};

pub const APP_SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, fuid BLOB NOT NULL UNIQUE, frame BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS supersession(prior TEXT PRIMARY KEY, successor TEXT NOT NULL, relation TEXT NOT NULL, ts INTEGER NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS adjustments(fuid TEXT NOT NULL, seq INTEGER NOT NULL, ts INTEGER NOT NULL, d_alpha REAL NOT NULL, d_beta REAL NOT NULL, class TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(fuid, seq)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS contradictions(a TEXT NOT NULL, b TEXT NOT NULL, kind TEXT NOT NULL, ts INTEGER NOT NULL, PRIMARY KEY(a,b));
CREATE TABLE IF NOT EXISTS works(id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL, language TEXT NOT NULL,
  rights TEXT NOT NULL, rights_note TEXT NOT NULL, source_hash TEXT NOT NULL, chapters TEXT NOT NULL, positions INTEGER NOT NULL,
  spoiler_default INTEGER NOT NULL, ingested_at INTEGER NOT NULL, engines TEXT NOT NULL, facts INTEGER NOT NULL, genre TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS passages(work TEXT NOT NULL, pos INTEGER NOT NULL, chapter INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, cfi TEXT, href TEXT, PRIMARY KEY(work,pos)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS aliases(work TEXT NOT NULL, alias TEXT NOT NULL, concept TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL, freq INTEGER NOT NULL, first_pos INTEGER NOT NULL, PRIMARY KEY(work, alias, concept));
CREATE INDEX IF NOT EXISTS aliases_concept ON aliases(concept);
CREATE TABLE IF NOT EXISTS concept_vectors(work TEXT NOT NULL, concept TEXT NOT NULL, vec TEXT NOT NULL, PRIMARY KEY(work,concept));
CREATE TABLE IF NOT EXISTS predicates(id TEXT PRIMARY KEY, spec TEXT NOT NULL, registered_by TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS answer_units(work TEXT NOT NULL, qkey TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, fuids TEXT NOT NULL,
  max_pos INTEGER NOT NULL, min_conf REAL NOT NULL, store_version TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(work,qkey));
CREATE TABLE IF NOT EXISTS answer_deps(fuid TEXT NOT NULL, work TEXT NOT NULL, qkey TEXT NOT NULL, PRIMARY KEY(fuid, work, qkey)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pass_hash TEXT NOT NULL, roles TEXT NOT NULL, tenant TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created INTEGER NOT NULL, device TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entitlements(user_id INTEGER NOT NULL, work TEXT NOT NULL, grant_kind TEXT NOT NULL, PRIMARY KEY(user_id, work));
CREATE TABLE IF NOT EXISTS seats(tenant TEXT PRIMARY KEY, seats INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS progress(user_id INTEGER NOT NULL, work TEXT NOT NULL, pos INTEGER NOT NULL, spoiler INTEGER NOT NULL, updated INTEGER NOT NULL, PRIMARY KEY(user_id, work));
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, session TEXT NOT NULL, work TEXT NOT NULL, ts INTEGER NOT NULL,
  mode TEXT NOT NULL, query TEXT NOT NULL, answer TEXT NOT NULL, fuids TEXT NOT NULL, context_key TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS history_user ON history(user_id, ts);
CREATE TABLE IF NOT EXISTS cards(user_id INTEGER NOT NULL, fuid TEXT NOT NULL, work TEXT NOT NULL, ease REAL NOT NULL, interval_days REAL NOT NULL,
  reps INTEGER NOT NULL, due INTEGER NOT NULL, PRIMARY KEY(user_id, fuid));
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, started INTEGER NOT NULL, finished INTEGER);
CREATE TABLE IF NOT EXISTS import_cursors(feed TEXT PRIMARY KEY, cursor TEXT NOT NULL, imported INTEGER NOT NULL, refused INTEGER NOT NULL, updated INTEGER NOT NULL);
";

pub struct Store {
    pub dir: PathBuf,
    write: Mutex<Connection>,
    reads: Vec<Mutex<Connection>>,
    next: AtomicUsize,
    pub keys: Keys,
    pub index: FactIndex,
}

fn open_conn(path: &Path) -> anyhow::Result<Connection> {
    let c = Connection::open(path)?;
    c.busy_timeout(std::time::Duration::from_secs(30))?;
    c.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=OFF; PRAGMA cache_size=-65536;")?;
    Ok(c)
}

impl Store {
    pub fn open(dir: &Path, heap_mb: usize) -> anyhow::Result<Store> {
        std::fs::create_dir_all(dir)?;
        let db = dir.join("querybook.sqlite");
        let write = open_conn(&db)?;
        // bulk imports touch large random-key B-trees (FUID, fingerprint)
        write.execute_batch("PRAGMA cache_size=-524288;")?;
        write.execute_batch(APP_SCHEMA)?;
        // migrations for stores created by earlier builds (ignore "duplicate column")
        for m in ["ALTER TABLE passages ADD COLUMN cfi TEXT", "ALTER TABLE passages ADD COLUMN href TEXT"] {
            let _ = write.execute(m, []);
        }
        write.execute_batch(ledger::SCHEMA)?;
        let reads = (0..4).map(|_| open_conn(&db).map(Mutex::new)).collect::<Result<Vec<_>, _>>()?;
        let keys = Keys::load_or_create(&dir.join("keys"))?;
        let index = FactIndex::open(&dir.join("index"), heap_mb)?;
        Ok(Store { dir: dir.to_path_buf(), write: Mutex::new(write), reads, next: AtomicUsize::new(0), keys, index })
    }

    pub fn read<T>(&self, f: impl FnOnce(&Connection) -> anyhow::Result<T>) -> anyhow::Result<T> {
        let i = self.next.fetch_add(1, Ordering::Relaxed) % self.reads.len();
        let c = self.reads[i].lock().unwrap();
        f(&c)
    }

    /// Writes to tables other than `facts` (accounts, progress, history...).
    /// The facts table is only ever written through `commit`/`erase`.
    pub fn write<T>(&self, f: impl FnOnce(&Connection) -> anyhow::Result<T>) -> anyhow::Result<T> {
        let c = self.write.lock().unwrap();
        f(&c)
    }

    /// Head of the last substrate-mutating ledger node, read fresh so that
    /// writes made by another process (the `qb` CLI) are seen immediately.
    pub fn version(&self) -> String {
        self.read(|c| ledger::substrate_head(c)).unwrap_or_else(|_| "unknown".into())
    }

    pub fn get(&self, fuid: &str) -> anyhow::Result<Option<FactUnit>> {
        let frame: Option<Vec<u8>> =
            self.read(|c| Ok(c.query_row("SELECT frame FROM facts WHERE fuid=?1", [key(fuid)], |r| r.get(0)).optional()?))?;
        frame.map(|b| decode(&b)).transpose()
    }

    pub fn get_many(&self, fuids: &[String]) -> anyhow::Result<Vec<FactUnit>> {
        self.read(|c| {
            let mut st = c.prepare_cached("SELECT frame FROM facts WHERE fuid=?1")?;
            let mut out = Vec::with_capacity(fuids.len());
            for f in fuids {
                if let Some(b) = st.query_row([key(f)], |r| r.get::<_, Vec<u8>>(0)).optional()? {
                    out.push(decode(&b)?);
                }
            }
            Ok(out)
        })
    }

    pub fn is_superseded(&self, fuid: &str) -> anyhow::Result<bool> {
        self.read(|c| Ok(c.query_row("SELECT 1 FROM supersession WHERE prior=?1", [fuid], |_| Ok(())).optional()?.is_some()))
    }

    /// Admit a batch. Assigns each record its provenance reference (ledger
    /// node + Merkle leaf), writes the opaque frames, indexes them and appends
    /// one signed ledger node whose Merkle root covers every admitted FUID.
    /// Records already present (identical FUID) are skipped: admission is
    /// idempotent. `index_now=false` defers the index commit (bulk import).
    pub fn commit(
        &self,
        permit: &CommitPermit,
        facts: &mut [FactUnit],
        actor: &str,
        op: &str,
        safety_digest: &str,
        index_now: bool,
    ) -> anyhow::Result<(Node, usize)> {
        use rayon::prelude::*;
        let mut conn = self.write.lock().unwrap();
        let (last, _) = ledger::head(&conn)?;
        let seq = last + 1;
        for (i, fact) in facts.iter_mut().enumerate() {
            fact.provenance.batch = seq;
            fact.provenance.leaf = i as u32;
        }
        // encode frames and build index views on every core
        let prepared: Vec<(Vec<u8>, tantivy::TantivyDocument)> =
            facts.par_iter().map(|f| (encode_compact(f), self.index.document(f, &searchable_text(f)))).collect();
        let tx = conn.transaction()?;
        let mut leaves = Vec::with_capacity(facts.len());
        let mut docs = Vec::with_capacity(facts.len());
        {
            let mut ins = tx.prepare_cached("INSERT OR IGNORE INTO facts(fuid, frame) VALUES(?1, ?2)")?;
            for (fact, (frame, doc)) in facts.iter_mut().zip(prepared) {
                if ins.execute(params![key(&fact.fuid), frame])? == 1 {
                    leaves.push(fact.fuid.clone());
                    docs.push(doc);
                } else {
                    // already admitted under an earlier node; that provenance stands
                    fact.provenance.batch = 0;
                }
            }
        }
        let inserted = docs.len();
        self.index.add_many(docs)?;
        let payload_hash = sha256_hex(leaves.join(",").as_bytes());
        let node = ledger::append(
            &tx,
            &self.keys,
            Append {
                actor,
                op,
                crossing: &format!("{}->{} {}", permit.crossing.from, permit.crossing.to, permit.crossing.permission),
                payload_hash,
                safety: safety_digest.to_string(),
                leaves: &leaves,
                substrate: inserted > 0,
                ts: now_secs(),
            },
        )?;
        tx.commit()?;
        drop(conn);
        if index_now {
            self.flush()?;
        }
        Ok((node, inserted))
    }

    /// Record a supersession: the successor must already be committed. The
    /// prior record is untouched (immutable); only the index view changes.
    pub fn supersede(&self, permit: &CommitPermit, prior: &FactUnit, successor: &str, relation: &str) -> anyhow::Result<()> {
        let _ = permit;
        self.write(|c| {
            c.execute(
                "INSERT OR REPLACE INTO supersession(prior, successor, relation, ts) VALUES(?1,?2,?3,?4)",
                params![prior.fuid, successor, relation, now_secs()],
            )?;
            c.execute(
                "UPDATE answer_units SET stale=1 WHERE (work,qkey) IN (SELECT work,qkey FROM answer_deps WHERE fuid=?1)",
                [&prior.fuid],
            )?;
            Ok(())
        })?;
        self.index.delete_fuid(&prior.fuid)?;
        let mut view = self.index.document(prior, &searchable_text(prior));
        view.add_text(self.index.f.status, "superseded");
        self.index.add(view)?;
        Ok(())
    }

    /// Erase a reader-authored record (notes, highlights). The ledger records
    /// that an erasure occurred, not what was erased.
    pub fn erase(&self, permit: &CommitPermit, fuid: &str, actor: &str) -> anyhow::Result<bool> {
        let mut conn = self.write.lock().unwrap();
        let tx = conn.transaction()?;
        let n = tx.execute("DELETE FROM facts WHERE fuid=?1", [key(fuid)])?;
        if n > 0 {
            ledger::append(
                &tx,
                &self.keys,
                Append {
                    actor,
                    op: "erasure",
                    crossing: &format!("{}->{} {}", permit.crossing.from, permit.crossing.to, permit.crossing.permission),
                    payload_hash: "content-not-retained".into(),
                    safety: "erasure".into(),
                    leaves: &[],
                    substrate: false,
                    ts: now_secs(),
                },
            )?;
        }
        tx.commit()?;
        drop(conn);
        if n > 0 {
            self.index.delete_fuid(fuid)?;
            self.index.commit()?;
        }
        Ok(n > 0)
    }

    pub fn flush(&self) -> anyhow::Result<()> {
        self.index.commit()
    }

    /// Bulk-import checkpoint: make work visible without giving up the lock.
    pub fn checkpoint(&self) -> anyhow::Result<()> {
        self.index.checkpoint()
    }

    pub fn ledger_append(&self, actor: &str, op: &str, crossing: &str, payload: &str, safety: &str) -> anyhow::Result<Node> {
        self.write(|c| {
            ledger::append(
                c,
                &self.keys,
                Append {
                    actor,
                    op,
                    crossing,
                    payload_hash: sha256_hex(payload.as_bytes()),
                    safety: safety.into(),
                    leaves: &[],
                    substrate: false,
                    ts: now_secs(),
                },
            )
        })
    }

    pub fn verify_ledger(&self) -> anyhow::Result<ledger::Verification> {
        self.read(|c| ledger::verify(c, &self.keys))
    }

    pub fn fact_count(&self) -> anyhow::Result<u64> {
        self.read(|c| Ok(c.query_row("SELECT COUNT(*) FROM facts", [], |r| r.get::<_, i64>(0))? as u64))
    }
}

/// Storage key: the FUID's 32 raw bytes (half the size of its hex form).
pub fn key(fuid: &str) -> Vec<u8> {
    hex::decode(fuid).unwrap_or_else(|_| fuid.as_bytes().to_vec())
}

/// Text the retrieval index matches against: concept labels, the predicate
/// phrase, literal values and the verbatim source span.
pub fn searchable_text(f: &FactUnit) -> String {
    let mut parts: Vec<String> = Vec::new();
    for c in f.atom.concepts() {
        parts.push(f.label(c));
    }
    parts.push(f.atom.predicate.replace(['_', ':', '.'], " "));
    let mut lit = |v: &super::fact::Value| match v {
        super::fact::Value::Text(t) | super::fact::Value::Date(t) => parts.push(t.clone()),
        super::fact::Value::Number { value, unit } => parts.push(format!("{value} {unit}")),
        _ => {}
    };
    lit(&f.atom.object);
    for v in f.atom.args.values() {
        lit(v);
    }
    if let Some(q) = &f.quote {
        parts.push(q.clone());
    }
    parts.join(" \u{2029} ")
}
