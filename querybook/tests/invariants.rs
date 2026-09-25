//! End-to-end invariants of the QueryBook prototype, each tied to the
//! registry rule it enforces. Every test builds its own store in a temp dir.

use querybook::app::QueryBook;
use querybook::config::Config;
use querybook::d0::{self, Domain, Trace};
use querybook::d1::pipeline::{IngestOptions, ingest_file};
use querybook::d4::{Answer, Request, answer};
use querybook::d8::{self, ScopeRequest, User};
use std::path::PathBuf;
use std::sync::Arc;

const BOOK: &str = "The Clockmaker of Linden

CHAPTER I

Anna Grey was a clockmaker from the town of Linden. Anna Grey lived at Linden. Anna Grey repaired the great tower clock every spring. Tomas Reed was a travelling surveyor. Tomas Reed arrived at Linden in the rain.

Anna Grey was patient and exacting. Tomas Reed was curious and restless. Tomas Reed met Anna Grey at the market.

“The clock has never lost a minute,” said Anna Grey.

CHAPTER II

The Mayor of Linden was a cautious man. The Mayor of Linden disliked Tomas Reed. Anna Grey refused the Mayor of Linden his request to stop the clock.

Tomas Reed measured the valley twice. Tomas Reed drew a new map of the river.

CHAPTER III

Anna Grey married Tomas Reed in the autumn. The Mayor of Linden attended the wedding at the tower.

Tomas Reed built a workshop beside the tower. Anna Grey taught Tomas Reed the escapement.
";

struct Env {
    qb: Arc<QueryBook>,
    dir: PathBuf,
    work: String,
}

impl Drop for Env {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn env(name: &str) -> Env {
    let dir = std::env::temp_dir().join(format!("qb-test-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let mut cfg = Config::default();
    cfg.server.data_dir = dir.join("data");
    let qb = QueryBook::open(cfg).unwrap();
    let book = dir.join("clockmaker.txt");
    std::fs::write(&book, BOOK).unwrap();
    let opts = IngestOptions {
        id: Some("clockmaker".into()),
        rights: "author-owned".into(),
        rights_note: "test".into(),
        engines: vec!["rules".into()],
        replace: false,
        genre: "fiction".into(),
        actor: "test".into(),
    };
    let r = ingest_file(&qb, &book, &opts, &|_: &str| {}).unwrap();
    assert!(r.admitted > 10, "ingest admitted {} records", r.admitted);
    if std::env::var("QB_DEBUG").is_ok() {
        eprintln!(
            "{name}: admitted {} count {} indexed {}",
            r.admitted,
            qb.store.fact_count().unwrap(),
            qb.store.index.num_docs()
        );
    }
    Env { qb, dir, work: "clockmaker".into() }
}

fn reader(e: &Env, name: &str) -> User {
    let id = d8::create_user(&e.qb, name, "pw-1234", &["reader"], "default").unwrap();
    d8::grant(&e.qb, id, &e.work, "grant").unwrap();
    User { id, username: name.into(), roles: vec!["reader".into()], tenant: "default".into() }
}

fn ask(e: &Env, u: &User, q: &str, at: Option<u64>) -> Answer {
    let mut t = Trace::default();
    let scope = d8::scope_for(&e.qb, u, &ScopeRequest { work: &e.work, include_world: false, at_pos: at }, &mut t).unwrap();
    answer(&e.qb, &scope, &Request { mode: "ask".into(), query: q.into(), ..Default::default() }, t).unwrap()
}

/// QBF-C006 / C238: identical context key + identical query => identical bytes.
#[test]
fn determinism_under_the_context_lock() {
    let e = env("det");
    let u = reader(&e, "ann");
    let a1 = ask(&e, &u, "Who is Tomas Reed?", Some(1000));
    let a2 = ask(&e, &u, "Who is Tomas Reed?", Some(1000));
    assert_eq!(a1.status, "answered");
    assert_eq!(a1.context_key, a2.context_key);
    assert_eq!(a1.output_hash, a2.output_hash);
    assert_eq!(serde_json::to_string(&a1.lines).unwrap(), serde_json::to_string(&a2.lines).unwrap());
    // a different reading position is a different key: nothing is claimed across it
    let a3 = ask(&e, &u, "Who is Tomas Reed?", Some(3));
    assert_ne!(a1.context_key, a3.context_key);
}

/// QBF-C196: a record past the reader's position is not traversable.
#[test]
fn spoiler_bound_is_structural() {
    let e = env("spoil");
    let u = reader(&e, "ben");
    let wedding_pos = {
        let a = ask(&e, &u, "Who did Anna Grey marry?", Some(10_000));
        let c = a.citations.iter().find(|c| c.quote.contains("married")).expect("wedding cited with the whole book in scope");
        c.pos
    };
    let early = wedding_pos - 3;
    let a = ask(&e, &u, "Who did Anna Grey marry?", Some(early));
    assert!(a.citations.iter().all(|c| c.pos <= early), "a citation escaped the spoiler bound");
    assert!(!a.lines.iter().any(|l| l.text.contains("married")));
    // a question only the later text answers reports that, without content
    let b = ask(&e, &u, "wedding autumn", Some(early));
    assert_eq!(b.status, "beyond-position", "{:?}", b.lines);
    assert!(b.citations.is_empty());
}

/// QBF-C182: reader-authored records carry an owner-only ACL.
#[test]
fn notes_are_visible_only_to_their_author() {
    let e = env("acl");
    let a = reader(&e, "cara");
    let b = reader(&e, "dev");
    let mut f = querybook::d2::FactUnit {
        fuid: String::new(),
        fingerprint: String::new(),
        type_ref: "reader.note".into(),
        atom: querybook::d2::Atom {
            subject: format!("user:{}/reader", a.id),
            predicate: "reader_note".into(),
            object: querybook::d2::Value::Text("secret clock theory".into()),
            args: Default::default(),
            polarity: true,
        },
        group: "reader".into(),
        applicability: None,
        temporal: querybook::d2::Temporal { occurred: None, ingested: 1, attested: None },
        spatial: None,
        narrative: Some(querybook::d2::Narrative { work: e.work.clone(), pos: 3, chapter: 0, also: vec![] }),
        evidence: querybook::d2::Evidence::prior(0.99),
        source: querybook::d2::SourceRef { class: "reader".into(), id: format!("user:{}", a.id), authority: 0.99 },
        modality: "text".into(),
        safety: Default::default(),
        acl: vec![format!("user:{}", a.id)],
        edges: vec![],
        supersedes: None,
        derivation: querybook::d2::Derivation { kind: "reader".into(), engine: None, prompt_hash: None, citation_verified: None },
        provenance: querybook::d2::ProvRef { batch: 0, leaf: 0 },
        certification: None,
        quote: None,
        labels: Default::default(),
        external_id: None,
    };
    f.seal();
    let permit = d0::commit_permit(Domain::D8, "reader-authored-acl-owner-only").unwrap();
    e.qb.store.commit(&permit, &mut vec![f], "test", "annotate", "reader", true).unwrap();
    // never cited as the book, for anyone
    for u in [&a, &b] {
        let ans = ask(&e, u, "secret clock theory", Some(10_000));
        assert!(ans.citations.iter().all(|c| !c.quote.contains("secret")));
    }
}

/// QBF-C031 / C178: the ledger verifies after ingest; the D7->D2 route does not exist.
#[test]
fn ledger_verifies_and_generation_cannot_write() {
    let e = env("ledger");
    let v = e.qb.store.verify_ledger().unwrap();
    assert!(v.first_failure.is_none(), "{:?}", v.first_failure);
    assert!(v.nodes >= 2);
    assert!(d0::commit_permit(Domain::D7, "anything").is_err());
    assert!(d0::commit_permit(Domain::D9, "anything").is_err());
}

/// QBF-C084: a pre-computed answer is served only while every contributing
/// record is unrevised; revision marks it stale.
#[test]
fn precomputed_answers_invalidate_on_revision() {
    let e = env("pqg");
    let u = reader(&e, "eve");
    let a = ask(&e, &u, "Who is Tomas Reed?", Some(10_000));
    assert_eq!(a.served_from, "precomputed", "Tomas Reed is a central concept; PQG should have answered him");
    let first = a.citations[0].fuid.clone();
    let rec = e.qb.store.get(&first).unwrap().expect("every cited record is retrievable by its FUID");
    let permit = d0::commit_permit(Domain::D1, "safety-evaluation+type-validation+confidence-calibration").unwrap();
    e.qb.store.supersede(&permit, &rec, "test-successor", "correction").unwrap();
    e.qb.store.flush().unwrap();
    let b = ask(&e, &u, "Who is Tomas Reed?", Some(10_000));
    assert_eq!(b.served_from, "live");
    assert!(b.citations.iter().all(|c| c.fuid != first), "a superseded record was cited");
}

/// Every citation resolves to a record whose quote occurs in the book text.
#[test]
fn every_citation_resolves_to_the_source() {
    let e = env("cite");
    let u = reader(&e, "fay");
    for q in ["Who is Anna Grey?", "What did Tomas Reed do?", "Who is the Mayor of Linden?"] {
        let a = ask(&e, &u, q, Some(10_000));
        for c in &a.citations {
            let text: String =
                e.qb.store
                    .read(|db| {
                        Ok(db.query_row(
                            "SELECT text FROM passages WHERE work=?1 AND pos=?2",
                            rusqlite::params![e.work, c.pos as i64],
                            |r| r.get(0),
                        )?)
                    })
                    .unwrap();
            assert!(
                querybook::util::canon_text(&text).contains(&querybook::util::canon_text(&c.quote)),
                "quote not in passage {}: {}",
                c.pos,
                c.quote
            );
        }
    }
}

/// UFCS import: refusal with a reason, corroboration instead of duplication.
#[test]
fn ufcs_import_revalidates_and_corroborates() {
    let e = env("ufcs");
    let feed = e.dir.join("feed.ndjson");
    let rec = r#"{"id":"a","atom":{"subject":"Q1","subject_label":"Linden","predicate":"population","object":1200,"polarity":true},"envelope":{"confidence":{"value":0.9,"weight":4}},"text":"Linden has 1200 inhabitants."}"#;
    std::fs::write(
        &feed,
        format!("{rec}\n{}\n{}\n", rec.replace("\"id\":\"a\"", "\"id\":\"b\""), r#"{"id":"c","atom":{"predicate":"x"}}"#),
    )
    .unwrap();
    let mapping = e.dir.join("m.toml");
    std::fs::write(
        &mapping,
        r#"feed = "test"
[fields]
id = "/id"
subject = "/atom/subject"
subject_label = "/atom/subject_label"
predicate = "/atom/predicate"
object = "/atom/object"
polarity = "/atom/polarity"
confidence = "/envelope/confidence/value"
weight = "/envelope/confidence/weight"
text = "/text"
"#,
    )
    .unwrap();
    let r = querybook::d1::ufcs::import(&e.qb, &mapping, Some(&feed), 0, false, &|_: &str| {}).unwrap();
    assert_eq!((r.read, r.admitted, r.corroborations, r.refused), (3, 1, 1, 1), "{r:?}");
    let v = e.qb.store.verify_ledger().unwrap();
    assert!(v.first_failure.is_none());
}

#[test]
fn store_and_index_agree() {
    let e = env("agree");
    assert_eq!(e.qb.store.fact_count().unwrap(), e.qb.store.index.num_docs());
}
