//! D9 · Interaction Surfaces: presentation only. No authority over content,
//! retrieval or rights: every content request resolves a scope through D8
//! and content through D4; reader-authored records enter the substrate only
//! through the D8->D2 conversion (owner-only ACL).

use crate::app::QueryBook;
use crate::d0::{self, Domain, Trace};
use crate::d1::pipeline::{IngestOptions, ingest_file};
use crate::d2::{Atom, Derivation, Evidence, FactUnit, Narrative, ProvRef, SourceRef, Temporal, Value};
use crate::d4::{self, Request};
use crate::d8::{self, ScopeRequest, User};
use crate::util::{now_secs, sha256_hex};
use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, Multipart, Path, Query, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use rusqlite::params;
use serde::Deserialize;
use serde_json::{Value as J, json};
use std::collections::BTreeMap;
use std::sync::Arc;

type AppState = Arc<QueryBook>;

const INDEX_HTML: &str = include_str!("../../web/index.html");
const APP_JS: &str = include_str!("../../web/app.js");
const DASHBOARD_JS: &str = include_str!("../../web/dashboard.js");
const APP_CSS: &str = include_str!("../../web/app.css");

pub struct ApiError(StatusCode, String);

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"error": self.1}))).into_response()
    }
}

impl<E: std::fmt::Display> From<E> for ApiError {
    fn from(e: E) -> Self {
        ApiError(StatusCode::BAD_REQUEST, e.to_string())
    }
}

type R<T> = Result<T, ApiError>;

fn unauthorized() -> ApiError {
    ApiError(StatusCode::UNAUTHORIZED, "sign in required".into())
}
fn forbidden(msg: &str) -> ApiError {
    ApiError(StatusCode::FORBIDDEN, msg.into())
}

fn token(headers: &HeaderMap) -> Option<String> {
    let cookies = headers.get(header::COOKIE)?.to_str().ok()?;
    cookies.split(';').find_map(|c| c.trim().strip_prefix("qb_session=").map(|v| v.to_string()))
}

/// (user, device, session id)
fn auth(qb: &QueryBook, headers: &HeaderMap) -> R<(User, String, String)> {
    let t = token(headers).ok_or_else(unauthorized)?;
    let (u, device) = d8::user_for_token(qb, &t)?.ok_or_else(unauthorized)?;
    Ok((u, device, sha256_hex(t.as_bytes())[..16].to_string()))
}

async fn blocking<T: Send + 'static>(f: impl FnOnce() -> anyhow::Result<T> + Send + 'static) -> R<T> {
    tokio::task::spawn_blocking(f)
        .await
        .map_err(|e| ApiError(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?
        .map_err(|e| ApiError(StatusCode::BAD_REQUEST, format!("{e:#}")))
}

pub async fn serve(qb: AppState) -> anyhow::Result<()> {
    ensure_demo_users(&qb)?;
    crate::d1::ufcs::ensure_tables(&qb)?;
    let bind = qb.cfg.server.bind.clone();
    let app = Router::new()
        .route(
            "/",
            get(|| async {
                ([(header::CONTENT_TYPE, "text/html; charset=utf-8"), (header::CACHE_CONTROL, "no-cache")], INDEX_HTML)
            }),
        )
        .route(
            "/app.js",
            get(|| async {
                ([(header::CONTENT_TYPE, "application/javascript; charset=utf-8"), (header::CACHE_CONTROL, "no-cache")], APP_JS)
            }),
        )
        .route(
            "/dashboard.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "application/javascript; charset=utf-8"), (header::CACHE_CONTROL, "no-cache")],
                    DASHBOARD_JS,
                )
            }),
        )
        .route(
            "/app.css",
            get(|| async { ([(header::CONTENT_TYPE, "text/css; charset=utf-8"), (header::CACHE_CONTROL, "no-cache")], APP_CSS) }),
        )
        .route("/api/health", get(|| async { Json(json!({"ok": true})) }))
        .route("/api/login", post(login))
        .route("/api/logout", post(logout))
        .route("/api/me", get(me))
        .route("/api/library", get(library))
        .route("/api/works/{id}", get(work))
        .route("/api/works/{id}/chapter/{n}", get(chapter))
        .route("/api/works/{id}/progress", post(progress))
        .route("/api/works/{id}/suggested", get(suggested))
        .route("/api/works/{id}/annotations", get(annotations).post(annotate))
        .route("/api/annotations/{fuid}", delete(unannotate))
        .route("/api/query", post(query))
        .route("/api/facts/{fuid}", get(fact))
        .route("/api/history", get(history).delete(erase_history))
        .route("/api/export", get(export))
        .route("/api/study/review", post(review))
        .route("/api/study/{work}/mastery", get(mastery))
        .route("/api/ledger", get(ledger))
        .route("/api/ledger/verify", get(verify))
        .route("/api/admin/stats", get(admin_stats))
        .route("/api/admin/dashboard", get(dashboard))
        .route("/api/admin/upload", post(upload))
        .route("/api/admin/jobs", get(jobs))
        .route("/api/admin/users", post(add_user))
        .route("/api/admin/grant", post(grant))
        .route("/api/admin/questions/{work}", get(reader_questions))
        .layer(DefaultBodyLimit::max(300 * 1024 * 1024))
        .with_state(qb.clone());
    let listener = tokio::net::TcpListener::bind(&bind).await?;
    eprintln!(
        "QueryBook listening on http://{bind}  (records: {}, store {})",
        qb.store.fact_count()?,
        &qb.store.version()[..12.min(qb.store.version().len())]
    );
    axum::serve(listener, app).await?;
    Ok(())
}

/// First start: create the demo accounts if there are no users at all.
fn ensure_demo_users(qb: &QueryBook) -> anyhow::Result<()> {
    let n: i64 = qb.store.read(|c| Ok(c.query_row("SELECT COUNT(*) FROM users", [], |r| r.get(0))?))?;
    if n == 0 {
        let reader_pw = std::env::var("QB_DEMO_READER_PASSWORD").unwrap_or_else(|_| "reader".into());
        let admin_pw = std::env::var("QB_ADMIN_PASSWORD").unwrap_or_else(|_| "admin".into());
        d8::create_user(qb, "reader", &reader_pw, &["reader"], "default")?;
        d8::create_user(qb, "admin", &admin_pw, &["operator", "author"], "default")?;
        eprintln!(
            "created demo accounts reader/{reader_pw} and admin/<QB_ADMIN_PASSWORD or 'admin'> — change them with `qb user`"
        );
    }
    Ok(())
}

#[derive(Deserialize)]
struct LoginReq {
    username: String,
    password: String,
    #[serde(default)]
    device: String,
}

async fn login(State(qb): State<AppState>, Json(r): Json<LoginReq>) -> R<Response> {
    let res = blocking(move || {
        let device = if r.device.is_empty() { "web".to_string() } else { r.device };
        d8::login(&qb, &r.username, &r.password, &device)
    })
    .await?;
    let Some((token, user)) = res else { return Err(ApiError(StatusCode::UNAUTHORIZED, "wrong username or password".into())) };
    let cookie = format!("qb_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000");
    Ok(([(header::SET_COOKIE, cookie)], Json(json!({"user": user}))).into_response())
}

async fn logout(State(qb): State<AppState>, headers: HeaderMap) -> R<Response> {
    if let Some(t) = token(&headers) {
        blocking(move || d8::logout(&qb, &t)).await?;
    }
    Ok(([(header::SET_COOKIE, "qb_session=; Path=/; Max-Age=0".to_string())], Json(json!({"ok": true}))).into_response())
}

async fn me(State(qb): State<AppState>, headers: HeaderMap) -> R<Json<J>> {
    let (u, device, _) = auth(&qb, &headers)?;
    let corpora = d8::world_feeds(&qb)?;
    Ok(Json(json!({
        "user": u, "device": device, "regime": qb.regime_label(), "corpora": corpora,
        "engines": qb.cfg.engines.iter().map(|e| json!({"id": e.id, "kind": e.kind, "model": e.model})).collect::<Vec<_>>(),
    })))
}

async fn library(State(qb): State<AppState>, headers: HeaderMap) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        let mut out = Vec::new();
        for w in d8::library(&qb, &u)? {
            let p = d8::progress(&qb, &u, &w.id)?;
            out.push(json!({"work": w, "progress": p}));
        }
        Ok(Json(json!({"works": out})))
    })
    .await
}

async fn work(State(qb): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        anyhow::ensure!(d8::entitled(&qb, &u, &id)?, "not entitled to this work");
        let w = d8::work(&qb, &id)?.ok_or_else(|| anyhow::anyhow!("no such work"))?;
        let p = d8::progress(&qb, &u, &id)?;
        let m = crate::d14::mastery(&qb, u.id, &id)?;
        Ok(Json(json!({"work": w, "progress": p, "mastery": m})))
    })
    .await
}

async fn chapter(State(qb): State<AppState>, headers: HeaderMap, Path((id, n)): Path<(String, u32)>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        anyhow::ensure!(d8::entitled(&qb, &u, &id)?, "not entitled to this work");
        let rows: Vec<J> = qb.store.read(|c| {
            let mut st = c.prepare("SELECT pos, kind, text FROM passages WHERE work=?1 AND chapter=?2 ORDER BY pos")?;
            let r = st.query_map(params![id, n], |r| {
                Ok(json!({"pos": r.get::<_, i64>(0)?, "kind": r.get::<_, String>(1)?, "text": r.get::<_, String>(2)?}))
            })?;
            Ok(r.collect::<Result<_, _>>()?)
        })?;
        Ok(Json(json!({"chapter": n, "passages": rows})))
    })
    .await
}

#[derive(Deserialize)]
struct ProgressReq {
    pos: Option<u64>,
    spoiler: Option<bool>,
    #[serde(default)]
    reset: bool,
}

async fn progress(
    State(qb): State<AppState>,
    headers: HeaderMap,
    Path(id): Path<String>,
    Json(r): Json<ProgressReq>,
) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        anyhow::ensure!(d8::entitled(&qb, &u, &id)?, "not entitled to this work");
        let cur = d8::progress(&qb, &u, &id)?;
        // the spoiler bound is the furthest point read; paging back never lowers it
        let pos = r.pos.map(|p| if r.reset { p } else { p.max(cur.pos) });
        let p = d8::set_progress(&qb, &u, &id, pos, r.spoiler)?;
        Ok(Json(json!({"progress": p})))
    })
    .await
}

async fn suggested(State(qb): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        anyhow::ensure!(d8::entitled(&qb, &u, &id)?, "not entitled to this work");
        let p = d8::progress(&qb, &u, &id)?;
        let bound = if p.spoiler { p.pos } else { u64::MAX };
        let qs: Vec<String> = qb.store.read(|c| {
            let mut st = c.prepare("SELECT question FROM answer_units WHERE work=?1 AND stale=0 AND max_pos<=?2 ORDER BY min_conf DESC, question LIMIT 8")?;
            let r = st.query_map(params![id, bound.min(i64::MAX as u64) as i64], |r| r.get(0))?;
            Ok(r.collect::<Result<_, _>>()?)
        })?;
        Ok(Json(json!({"questions": qs})))
    })
    .await
}

#[derive(Deserialize)]
struct QueryReq {
    work: String,
    #[serde(default)]
    mode: String,
    #[serde(default)]
    query: String,
    chapter: Option<u32>,
    focus: Option<String>,
    /// the page the reader is on (spoiler bound = max(this, furthest read))
    at: Option<u64>,
    #[serde(default)]
    world: bool,
}

async fn query(State(qb): State<AppState>, headers: HeaderMap, Json(r): Json<QueryReq>) -> R<Json<d4::Answer>> {
    let (u, device, session) = auth(&qb, &headers)?;
    blocking(move || {
        let mut trace = Trace::default();
        // "world": the imported knowledge alone, no book (D8 resolves it before retrieval)
        let scope = if r.work == "world" {
            let feeds = d8::world_feeds(&qb)?;
            anyhow::ensure!(!feeds.is_empty(), "no imported knowledge on this server yet");
            d8::world_scope(&feeds)
        } else {
            d8::scope_for(&qb, &u, &ScopeRequest { work: &r.work, include_world: r.world, at_pos: r.at }, &mut trace)?
        };
        let req = Request { mode: r.mode.clone(), query: r.query.clone(), chapter: r.chapter, focus: r.focus.clone(), device };
        let a = d4::answer(&qb, &scope, &req, trace)?;
        let text: String = a.lines.iter().map(|l| l.text.clone()).collect::<Vec<_>>().join(" ");
        let fuids: Vec<String> = a.citations.iter().map(|c| c.fuid.clone()).collect();
        let label = if r.query.is_empty() { a.mode.clone() } else { r.query.clone() };
        d8::record_history(&qb, &u, &session, &r.work, &a.mode, &label, &text, &fuids, &a.context_key)?;
        Ok(Json(a))
    })
    .await
}

/// Full record inspection with its Merkle inclusion proof. Only records the
/// requester's scope admits are returned.
async fn fact(State(qb): State<AppState>, headers: HeaderMap, Path(fuid): Path<String>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        let f = qb.store.get(&fuid)?.ok_or_else(|| anyhow::anyhow!("no such record"))?;
        let allowed = match f.work() {
            Some(w) => {
                let p = d8::progress(&qb, &u, w)?;
                let exempt = u.has("instructor") || u.has("researcher") || u.has("author");
                let pos = f.narrative.as_ref().map(|n| n.pos).unwrap_or(0);
                d8::entitled(&qb, &u, w)? && (!p.spoiler || exempt || pos <= p.pos) && (f.acl.iter().any(|a| a == &format!("work:{w}") || a == &format!("user:{}", u.id)))
            }
            None => f.acl.iter().any(|a| a == "public" || a == &format!("user:{}", u.id)),
        };
        anyhow::ensure!(allowed, "that record is outside your scope");
        let node = qb.store.read(|c| crate::d2::ledger::node(c, f.provenance.batch))?;
        // Merkle proof over the admitting batch
        use tantivy::query::RangeQuery;
        use std::ops::Bound;
        let b = f.provenance.batch;
        let q = RangeQuery::new(Bound::Included(tantivy::Term::from_field_u64(qb.store.index.f.batch, b)), Bound::Included(tantivy::Term::from_field_u64(qb.store.index.f.batch, b)));
        let hits = qb.store.index.search(&q, 2_000_000)?;
        let mut leaves: Vec<(u32, String)> = Vec::new();
        for fu in qb.store.get_many(&hits.into_iter().map(|h| h.1).collect::<Vec<_>>())? {
            if fu.provenance.batch == b {
                leaves.push((fu.provenance.leaf, fu.fuid));
            }
        }
        leaves.sort();
        leaves.dedup();
        let fuids: Vec<String> = leaves.iter().map(|l| l.1.clone()).collect();
        let proof = fuids.iter().position(|x| *x == f.fuid).map(|i| crate::d2::ledger::merkle_proof(&fuids, i));
        let proof_ok = match (&proof, &node) {
            (Some(p), Some(n)) => crate::d2::ledger::merkle_verify(&f.fuid, p, &n.merkle_root),
            _ => false,
        };
        let adjustments: Vec<J> = qb.store.read(|c| {
            let mut st = c.prepare("SELECT seq, ts, d_alpha, d_beta, class, reason FROM adjustments WHERE fuid=?1 ORDER BY seq")?;
            let r = st.query_map([&f.fuid], |r| {
                Ok(json!({"seq": r.get::<_, i64>(0)?, "ts": r.get::<_, i64>(1)?, "d_alpha": r.get::<_, f64>(2)?, "d_beta": r.get::<_, f64>(3)?, "class": r.get::<_, String>(4)?, "reason": r.get::<_, String>(5)?}))
            })?;
            Ok(r.collect::<Result<_, _>>()?)
        })?;
        Ok(Json(json!({
            "record": f, "trust": f.trust(), "confidence": f.evidence.confidence(), "lower": f.evidence.lower(),
            "diversity": f.evidence.diversity(), "epistemic": f.evidence.epistemic(), "aleatory": f.evidence.aleatory(),
            "ledger_node": node, "merkle": {"leaves": fuids.len(), "proof_steps": proof.as_ref().map(|p| p.len()), "verified": proof_ok},
            "adjustments": adjustments, "superseded": qb.store.is_superseded(&f.fuid)?,
        })))
    })
    .await
}

// ---- reader-authored records (QBF-C182/C183) ------------------------------

#[derive(Deserialize)]
struct AnnotateReq {
    /// "highlight" | "note"
    kind: String,
    pos: u64,
    #[serde(default)]
    text: String,
    #[serde(default)]
    note: String,
    #[serde(default)]
    color: String,
}

async fn annotate(
    State(qb): State<AppState>,
    headers: HeaderMap,
    Path(id): Path<String>,
    Json(r): Json<AnnotateReq>,
) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        anyhow::ensure!(d8::entitled(&qb, &u, &id)?, "not entitled to this work");
        let chapter: i64 = qb.store.read(|c| {
            Ok(c.query_row("SELECT chapter FROM passages WHERE work=?1 AND pos=?2", params![id, r.pos as i64], |r| r.get(0))?)
        })?;
        let (pred, type_ref) =
            if r.kind == "note" { ("reader_note", "reader.note") } else { ("reader_highlight", "reader.highlight") };
        let body = if r.kind == "note" { r.note.trim().to_string() } else { r.text.trim().to_string() };
        anyhow::ensure!(!body.is_empty() && body.len() < 20_000, "empty or oversized annotation");
        let subject = format!("user:{}/reader", u.id);
        let mut labels = BTreeMap::new();
        labels.insert(subject.clone(), u.username.clone());
        let mut ev = Evidence::prior(0.99);
        ev.support("reader", 1.0);
        let mut f = FactUnit {
            fuid: String::new(),
            fingerprint: String::new(),
            type_ref: type_ref.into(),
            atom: Atom { subject, predicate: pred.into(), object: Value::Text(body), args: BTreeMap::new(), polarity: true },
            group: "reader".into(),
            applicability: if r.color.is_empty() { None } else { Some(format!("color:{}", r.color)) },
            temporal: Temporal { occurred: None, ingested: now_secs(), attested: None },
            spatial: None,
            narrative: Some(Narrative {
                work: id.clone(),
                pos: r.pos,
                chapter: chapter as u32,
                also: vec![],
                cfi: None,
                sentence: None,
            }),
            evidence: ev,
            source: SourceRef { class: "reader".into(), id: format!("user:{}", u.id), authority: 0.99 },
            modality: "text".into(),
            safety: crate::d0::safety::classify(&r.note),
            acl: vec![format!("user:{}", u.id)],
            edges: vec![],
            supersedes: None,
            derivation: Derivation { kind: "reader".into(), engine: None, prompt_hash: None, citation_verified: None },
            provenance: ProvRef { batch: 0, leaf: 0 },
            certification: None,
            quote: if r.text.is_empty() { None } else { Some(r.text.clone()) },
            labels,
            external_id: None,
            embedding: None,
        };
        f.seal();
        qb.catalog.read().unwrap().validate(&f).map_err(|e| anyhow::anyhow!(e))?;
        let permit = d0::commit_permit(Domain::D8, "reader-authored-acl-owner-only")?;
        let mut v = vec![f];
        qb.store.commit(&permit, &mut v, &format!("user:{}", u.id), "reader.annotate", "reader-authored", true)?;
        Ok(Json(json!({"annotation": annotation_json(&v[0])})))
    })
    .await
}

fn annotation_json(f: &FactUnit) -> J {
    let text = match &f.atom.object {
        Value::Text(t) => t.clone(),
        _ => String::new(),
    };
    json!({
        "fuid": f.fuid, "kind": if f.atom.predicate == "reader_note" { "note" } else { "highlight" },
        "pos": f.narrative.as_ref().map(|n| n.pos).unwrap_or(0), "chapter": f.narrative.as_ref().map(|n| n.chapter).unwrap_or(0),
        "text": f.quote.clone().unwrap_or_default(), "note": if f.atom.predicate == "reader_note" { text } else { String::new() },
        "color": f.applicability.clone().unwrap_or_default().trim_start_matches("color:").to_string(), "ts": f.temporal.ingested,
    })
}

async fn annotations(State(qb): State<AppState>, headers: HeaderMap, Path(id): Path<String>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        use tantivy::query::{BooleanQuery, Occur, Query, TermQuery};
        use tantivy::schema::IndexRecordOption;
        let f = &qb.store.index.f;
        let t = |field, v: &str| -> Box<dyn Query> {
            Box::new(TermQuery::new(tantivy::Term::from_field_text(field, v), IndexRecordOption::Basic))
        };
        let q = BooleanQuery::new(vec![
            (Occur::Must, t(f.work, &id)),
            (Occur::Must, t(f.acl, &format!("user:{}", u.id))),
            (Occur::Must, t(f.group, "reader")),
        ]);
        let hits = qb.store.index.search(&q, 5000)?;
        let mut facts = qb.store.get_many(&hits.into_iter().map(|h| h.1).collect::<Vec<_>>())?;
        facts.sort_by_key(|f| (f.narrative.as_ref().map(|n| n.pos).unwrap_or(0), f.temporal.ingested));
        Ok(Json(json!({"annotations": facts.iter().map(annotation_json).collect::<Vec<_>>()})))
    })
    .await
}

async fn unannotate(State(qb): State<AppState>, headers: HeaderMap, Path(fuid): Path<String>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        let f = qb.store.get(&fuid)?.ok_or_else(|| anyhow::anyhow!("no such annotation"))?;
        anyhow::ensure!(
            f.group == "reader" && f.acl == vec![format!("user:{}", u.id)],
            "only the author of an annotation may erase it"
        );
        let permit = d0::commit_permit(Domain::D8, "reader-authored-acl-owner-only")?;
        let ok = qb.store.erase(&permit, &fuid, &format!("user:{}", u.id))?;
        Ok(Json(json!({"erased": ok})))
    })
    .await
}

// ---- retention and portability --------------------------------------------

async fn history(State(qb): State<AppState>, headers: HeaderMap) -> R<Json<J>> {
    let (u, _, session) = auth(&qb, &headers)?;
    blocking(move || Ok(Json(json!({"history": d8::history(&qb, &u, 200)?, "session": session})))).await
}

#[derive(Deserialize)]
struct EraseQ {
    scope: String,
    #[serde(default)]
    key: String,
}

async fn erase_history(State(qb): State<AppState>, headers: HeaderMap, Query(q): Query<EraseQ>) -> R<Json<J>> {
    let (u, _, session) = auth(&qb, &headers)?;
    blocking(move || {
        let key = if q.scope == "session" { session } else { q.key };
        let n = d8::erase_history(&qb, &u, &q.scope, &key)?;
        Ok(Json(json!({"erased": n})))
    })
    .await
}

async fn export(State(qb): State<AppState>, headers: HeaderMap) -> R<Response> {
    let (u, _, _) = auth(&qb, &headers)?;
    let body = blocking(move || {
        use tantivy::query::TermQuery;
        let q = TermQuery::new(
            tantivy::Term::from_field_text(qb.store.index.f.acl, &format!("user:{}", u.id)),
            tantivy::schema::IndexRecordOption::Basic,
        );
        let hits = qb.store.index.search(&q, 100_000)?;
        let records = qb.store.get_many(&hits.into_iter().map(|h| h.1).collect::<Vec<_>>())?;
        let v = json!({
            "format": "querybook-export-v1", "exported_at": now_secs(), "user": u,
            "records": records, "history": d8::history(&qb, &u, 100_000)?,
        });
        Ok(serde_json::to_vec_pretty(&v)?)
    })
    .await?;
    Ok((
        [
            (header::CONTENT_TYPE, "application/json"),
            (header::CONTENT_DISPOSITION, "attachment; filename=\"querybook-export.json\""),
        ],
        body,
    )
        .into_response())
}

// ---- study ------------------------------------------------------------------

#[derive(Deserialize)]
struct ReviewReq {
    work: String,
    fuid: String,
    quality: u8,
}

async fn review(State(qb): State<AppState>, headers: HeaderMap, Json(r): Json<ReviewReq>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || {
        anyhow::ensure!(d8::entitled(&qb, &u, &r.work)?, "not entitled");
        let rv = crate::d14::review(&qb, u.id, &r.work, &r.fuid, r.quality)?;
        Ok(Json(json!({"review": rv, "mastery": crate::d14::mastery(&qb, u.id, &r.work)?})))
    })
    .await
}

async fn mastery(State(qb): State<AppState>, headers: HeaderMap, Path(work): Path<String>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    blocking(move || Ok(Json(json!({"mastery": crate::d14::mastery(&qb, u.id, &work)?})))).await
}

// ---- ledger -------------------------------------------------------------------

async fn ledger(State(qb): State<AppState>, headers: HeaderMap) -> R<Json<J>> {
    let _ = auth(&qb, &headers)?;
    blocking(move || {
        let nodes = qb.store.read(|c| crate::d2::ledger::recent(c, 40))?;
        Ok(Json(json!({"nodes": nodes, "verifying_key": qb.store.keys.verifying_key_hex(), "store_version": qb.store.version()})))
    })
    .await
}

async fn verify(State(qb): State<AppState>, headers: HeaderMap) -> R<Json<J>> {
    let _ = auth(&qb, &headers)?;
    blocking(move || Ok(Json(serde_json::to_value(qb.store.verify_ledger()?)?))).await
}

// ---- administration (operator / author) -----------------------------------

fn require(u: &User, roles: &[&str]) -> R<()> {
    if roles.iter().any(|r| u.has(r)) { Ok(()) } else { Err(forbidden("this needs an operator or author account")) }
}

async fn admin_stats(State(qb): State<AppState>, headers: HeaderMap) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    require(&u, &["operator", "author"])?;
    blocking(move || {
        let users: Vec<J> = qb.store.read(|c| {
            let mut st = c.prepare("SELECT id, username, roles, tenant FROM users ORDER BY id")?;
            let r = st.query_map([], |r| Ok(json!({"id": r.get::<_, i64>(0)?, "username": r.get::<_, String>(1)?, "roles": r.get::<_, String>(2)?, "tenant": r.get::<_, String>(3)?})))?;
            Ok(r.collect::<Result<_, _>>()?)
        })?;
        let feeds: Vec<J> = qb.store.read(|c| {
            let mut st = c.prepare("SELECT feed, cursor, imported, refused, updated FROM import_cursors ORDER BY feed")?;
            let r = st.query_map([], |r| Ok(json!({"feed": r.get::<_, String>(0)?, "cursor": r.get::<_, String>(1)?, "imported": r.get::<_, i64>(2)?, "refused": r.get::<_, i64>(3)?, "updated": r.get::<_, i64>(4)?})))?;
            Ok(r.collect::<Result<_, _>>()?)
        })?;
        Ok(Json(json!({
            "records": qb.store.fact_count()?, "indexed": qb.store.index.num_docs(), "store_version": qb.store.version(),
            "works": d8::all_works(&qb)?, "users": users, "feeds": feeds, "regime": qb.regime_label(),
            "engines": qb.cfg.engines.iter().filter(|e| e.kind != "claude").map(|e| json!({"id": e.id, "kind": e.kind, "model": e.model, "reliability": e.reliability,
                "ready": e.kind == "rules" || e.kind == "language" || e.api_key_env.is_empty() || std::env::var(&e.api_key_env).map(|v| !v.is_empty()).unwrap_or(false)})).collect::<Vec<_>>(),
            "rights": crate::d1::pipeline::RIGHTS,
        })))
    })
    .await
}

/// Operator overview: store, library, world knowledge, lattice, backups,
/// ledger and reader activity. Read-only; every figure comes from the store.
async fn dashboard(State(qb): State<AppState>, headers: HeaderMap) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    require(&u, &["operator", "author"])?;
    blocking(move || {
        let now = crate::util::now_secs();
        // a table that has not been created yet (no lattice, no imports) reads as empty
        let q1 = |sql: &str| -> i64 { qb.store.read(|c| Ok(c.query_row(sql, [], |r| r.get::<_, i64>(0))?)).unwrap_or(0) };
        let rows = |sql: &str, cols: &[&str]| -> Vec<J> {
            qb.store
                .read(|c| {
                    let mut st = c.prepare(sql)?;
                    let n = st.column_count();
                    let r = st
                        .query_map([], |r| {
                            let mut o = serde_json::Map::new();
                            for i in 0..n {
                                let v: rusqlite::types::Value = r.get(i)?;
                                let j = match v {
                                    rusqlite::types::Value::Integer(x) => json!(x),
                                    rusqlite::types::Value::Real(x) => json!(x),
                                    rusqlite::types::Value::Text(t) => json!(t),
                                    _ => J::Null,
                                };
                                o.insert(cols.get(i).copied().unwrap_or("?").to_string(), j);
                            }
                            Ok(J::Object(o))
                        })?
                        .collect::<Result<Vec<_>, _>>()?;
                    Ok(r)
                })
                .unwrap_or_default()
        };
        let works = d8::all_works(&qb)?;
        let book_facts: i64 = works.iter().map(|w| w.facts as i64).sum();
        let mut top: Vec<J> = {
            let mut w: Vec<_> = works.iter().collect();
            w.sort_by(|a, b| b.facts.cmp(&a.facts).then(a.title.cmp(&b.title)));
            w.into_iter().take(12).map(|x| json!({"id": x.id, "title": x.title, "facts": x.facts})).collect()
        };
        top.shrink_to_fit();
        let day = 86_400i64;
        let since = (now / day - 29) * day;
        // trends: per UTC day over the last 30 days
        let per_day = |sql: &str| -> Vec<J> {
            qb.store
                .read(|c| {
                    let mut st = c.prepare(sql)?;
                    let r = st
                        .query_map([since], |r| Ok(json!({"day": r.get::<_, i64>(0)? * 86_400, "n": r.get::<_, i64>(1)?})))?
                        .collect::<Result<Vec<_>, _>>()?;
                    Ok(r)
                })
                .unwrap_or_default()
        };
        let facts_before: i64 = qb
            .store
            .read(|c| Ok(c.query_row("SELECT COALESCE(SUM(leaves),0) FROM ledger WHERE substrate=1 AND ts<?1", [since], |r| r.get::<_, i64>(0))?))
            .unwrap_or(0);
        let facts = qb.store.fact_count()? as i64;
        let disk: u64 = walk_bytes(&qb.store.dir);
        let last = |op: &str| -> Option<i64> {
            qb.store.read(|c| Ok(c.query_row("SELECT MAX(ts) FROM ledger WHERE op=?1", [op], |r| r.get::<_, Option<i64>>(0))?)).ok().flatten()
        };
        let drive_authorised = qb.store.dir.join("keys").join("drive-token.json").exists();
        Ok(Json(json!({
            "generated": now,
            "store": {
                "facts": facts, "indexed": qb.store.index.num_docs(), "book_facts": book_facts,
                "world_facts": (facts - book_facts).max(0), "disk_bytes": disk, "version": qb.store.version(),
                "regime": qb.regime_label(),
            },
            "library": { "works": works.len(), "top": top },
            "trends": {
                "since": since,
                "facts_before": facts_before,
                "facts_added": per_day("SELECT ts/86400, SUM(leaves) FROM ledger WHERE substrate=1 AND ts>=?1 GROUP BY ts/86400 ORDER BY 1"),
                "questions": per_day("SELECT ts/86400, COUNT(*) FROM history WHERE mode='ask' AND ts>=?1 GROUP BY ts/86400 ORDER BY 1"),
            },
            "feeds": rows("SELECT feed, imported, refused, updated FROM import_cursors ORDER BY imported DESC", &["feed", "imported", "refused", "updated"]),
            "lattice": {
                "classes_censused": q1("SELECT COUNT(*) FROM lattice_census WHERE status='ok'"),
                "classes_total": q1("SELECT COALESCE(json_extract(summary, '$.classes'), 0) FROM lattice_structure ORDER BY ts DESC LIMIT 1"),
                "members": q1("SELECT COUNT(*) FROM lattice_members"),
                "cells_filled": q1("SELECT COUNT(*) FROM expectations WHERE value='' AND status='filled'"),
                "cells_absent": q1("SELECT COUNT(*) FROM expectations WHERE value='' AND status='absent'"),
                "cells_open": q1("SELECT COUNT(*) FROM expectations WHERE value='' AND status='open'"),
                "predictions": q1("SELECT COUNT(*) FROM expectations WHERE value!=''"),
                "confirmed": q1("SELECT COUNT(*) FROM expectations WHERE value!='' AND status='confirmed'"),
                "refuted": q1("SELECT COUNT(*) FROM expectations WHERE value!='' AND status='refuted'"),
                "rules": rows("SELECT rule, confirmed, refuted, ROUND(alpha/(alpha+beta), 3) FROM lattice_rules ORDER BY confirmed+refuted DESC LIMIT 12", &["rule", "confirmed", "refuted", "reliability"]),
                "findings": q1("SELECT COUNT(*) FROM lattice_findings"),
            },
            "backups": {
                "last_backup": last("store.backup"), "last_upload": last("store.backup.upload"), "drive_authorised": drive_authorised,
            },
            "ledger": {
                "nodes": q1("SELECT COUNT(*) FROM ledger"), "head": qb.store.read(|c| Ok(crate::d2::ledger::head(c)?.1)).unwrap_or_default(),
            },
            "activity": {
                "users": q1("SELECT COUNT(*) FROM users"),
                "questions_7d": qb.store.read(|c| Ok(c.query_row("SELECT COUNT(*) FROM history WHERE mode='ask' AND ts>=?1", [now - 7 * 86400], |r| r.get::<_, i64>(0))?)).unwrap_or(0),
                "questions_total": q1("SELECT COUNT(*) FROM history WHERE mode='ask'"),
                "unanswered_total": q1("SELECT COUNT(*) FROM history WHERE mode='ask' AND answer=''"),
                "recent": rows("SELECT work, query, CASE WHEN answer='' THEN 0 ELSE 1 END, ts FROM history WHERE mode='ask' ORDER BY ts DESC LIMIT 10", &["work", "question", "answered", "ts"]),
            },
            "jobs": rows("SELECT label, status, detail, started, finished FROM jobs ORDER BY id DESC LIMIT 6", &["label", "status", "detail", "started", "finished"]),
        })))
    })
    .await
}

fn walk_bytes(p: &std::path::Path) -> u64 {
    std::fs::read_dir(p)
        .map(|rd| {
            rd.flatten()
                .map(|e| match e.file_type() {
                    Ok(t) if t.is_dir() => walk_bytes(&e.path()),
                    _ => e.metadata().map(|m| m.len()).unwrap_or(0),
                })
                .sum()
        })
        .unwrap_or(0)
}

async fn upload(State(qb): State<AppState>, headers: HeaderMap, mut mp: Multipart) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    require(&u, &["operator", "author"])?;
    let mut fields: BTreeMap<String, String> = BTreeMap::new();
    let mut file: Option<(String, Bytes)> = None;
    while let Some(field) = mp.next_field().await? {
        let name = field.name().unwrap_or("").to_string();
        if name == "file" {
            let fname = field.file_name().unwrap_or("upload.epub").to_string();
            file = Some((fname, field.bytes().await?));
        } else {
            fields.insert(name, field.text().await?);
        }
    }
    let (fname, bytes) = file.ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "no file".into()))?;
    let rights = fields.get("rights").cloned().unwrap_or_default();
    if !crate::d1::pipeline::RIGHTS.contains(&rights.as_str()) {
        return Err(ApiError(StatusCode::BAD_REQUEST, "declare the rights you hold in this work".into()));
    }
    let safe: String =
        fname.chars().map(|c| if c.is_alphanumeric() || c == '.' || c == '-' || c == '_' { c } else { '_' }).collect();
    let dir = qb.store.dir.join("uploads");
    std::fs::create_dir_all(&dir)?;
    let path = dir.join(format!("{}-{}", &sha256_hex(&bytes)[..10], safe));
    std::fs::write(&path, &bytes)?;
    let engines: Vec<String> = fields
        .get("engines")
        .map(|e| e.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect())
        .unwrap_or_else(|| vec!["language".into()]);
    let opts = IngestOptions {
        id: fields.get("id").filter(|s| !s.is_empty()).cloned(),
        rights,
        rights_note: fields.get("rights_note").cloned().unwrap_or_default(),
        engines,
        replace: fields.get("replace").map(|v| v == "true" || v == "on").unwrap_or(false),
        genre: fields.get("genre").cloned().unwrap_or_default(),
        actor: format!("user:{}", u.id),
    };
    let job: i64 = qb.store.write(|c| {
        c.execute(
            "INSERT INTO jobs(kind, label, status, detail, started) VALUES('ingest', ?1, 'running', '', ?2)",
            params![fname, now_secs()],
        )?;
        Ok(c.last_insert_rowid())
    })?;
    let qb2 = qb.clone();
    std::thread::spawn(move || {
        let set = |status: &str, detail: &str| {
            let _ = qb2.store.write(|c| {
                c.execute(
                    "UPDATE jobs SET status=?2, detail=?3, finished=CASE WHEN ?2='running' THEN NULL ELSE ?4 END WHERE id=?1",
                    params![job, status, detail, now_secs()],
                )?;
                Ok(())
            });
        };
        let progress = |m: &str| {
            let _ = qb2.store.write(|c| {
                c.execute("UPDATE jobs SET detail=?2 WHERE id=?1", params![job, m])?;
                Ok(())
            });
        };
        match ingest_file(&qb2, &path, &opts, &progress) {
            Ok(r) => set("done", &serde_json::to_string(&r).unwrap_or_default()),
            Err(e) => set("failed", &format!("{e:#}")),
        }
    });
    Ok(Json(json!({"job": job})))
}

async fn jobs(State(qb): State<AppState>, headers: HeaderMap) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    require(&u, &["operator", "author"])?;
    blocking(move || {
        let rows: Vec<J> = qb.store.read(|c| {
            let mut st = c.prepare("SELECT id, kind, label, status, detail, started, finished FROM jobs ORDER BY id DESC LIMIT 30")?;
            let r = st.query_map([], |r| {
                Ok(json!({"id": r.get::<_, i64>(0)?, "kind": r.get::<_, String>(1)?, "label": r.get::<_, String>(2)?, "status": r.get::<_, String>(3)?,
                    "detail": r.get::<_, String>(4)?, "started": r.get::<_, i64>(5)?, "finished": r.get::<_, Option<i64>>(6)?}))
            })?;
            Ok(r.collect::<Result<_, _>>()?)
        })?;
        Ok(Json(json!({"jobs": rows})))
    })
    .await
}

#[derive(Deserialize)]
struct UserReq {
    username: String,
    password: String,
    #[serde(default)]
    roles: String,
}

async fn add_user(State(qb): State<AppState>, headers: HeaderMap, Json(r): Json<UserReq>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    require(&u, &["operator"])?;
    blocking(move || {
        let roles: Vec<&str> = if r.roles.is_empty() { vec!["reader"] } else { r.roles.split(',').map(|s| s.trim()).collect() };
        let id = d8::create_user(&qb, &r.username, &r.password, &roles, "default")?;
        Ok(Json(json!({"id": id})))
    })
    .await
}

#[derive(Deserialize)]
struct GrantReq {
    username: String,
    work: String,
}

async fn grant(State(qb): State<AppState>, headers: HeaderMap, Json(r): Json<GrantReq>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    require(&u, &["operator"])?;
    blocking(move || {
        let id: i64 =
            qb.store.read(|c| Ok(c.query_row("SELECT id FROM users WHERE username=?1", [&r.username], |x| x.get(0))?))?;
        d8::grant(&qb, id, &r.work, "grant")?;
        Ok(Json(json!({"ok": true})))
    })
    .await
}

/// Author feedback: what readers ask about a work, aggregated and anonymous.
async fn reader_questions(State(qb): State<AppState>, headers: HeaderMap, Path(work): Path<String>) -> R<Json<J>> {
    let (u, _, _) = auth(&qb, &headers)?;
    require(&u, &["operator", "author"])?;
    blocking(move || {
        let rows: Vec<J> = qb.store.read(|c| {
            let mut st = c.prepare(
                "SELECT lower(query), COUNT(*), COUNT(DISTINCT user_id), SUM(CASE WHEN answer='' THEN 1 ELSE 0 END) FROM history
                 WHERE work=?1 AND mode='ask' GROUP BY lower(query) ORDER BY COUNT(*) DESC LIMIT 50",
            )?;
            let r = st.query_map([&work], |r| {
                Ok(json!({"question": r.get::<_, String>(0)?, "asked": r.get::<_, i64>(1)?, "readers": r.get::<_, i64>(2)?, "unanswered": r.get::<_, i64>(3)?}))
            })?;
            Ok(r.collect::<Result<_, _>>()?)
        })?;
        Ok(Json(json!({"questions": rows})))
    })
    .await
}
