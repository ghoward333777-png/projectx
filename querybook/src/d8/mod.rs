//! D8 · Access, Rights & Retention. Executes before retrieval: a Scope is the
//! only way into D4, and its fields are private to this module, so no other
//! domain can widen one. Spoiler protection (QBF-C196) is a scope bound, not a
//! mask over a rendered answer.

use crate::app::QueryBook;
use crate::d0::{Domain, Trace};
use crate::util::{now_secs, random_bytes, sha256_hex};
use argon2::Argon2;
use argon2::password_hash::{PasswordHasher, PasswordVerifier};
use rusqlite::{OptionalExtension, params};
use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
pub struct User {
    pub id: i64,
    pub username: String,
    pub roles: Vec<String>,
    pub tenant: String,
}

impl User {
    pub fn has(&self, role: &str) -> bool {
        self.roles.iter().any(|r| r == role)
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct WorkRow {
    pub id: String,
    pub title: String,
    pub author: String,
    pub rights: String,
    pub positions: u64,
    pub facts: u64,
    pub chapters: serde_json::Value,
    pub engines: String,
    pub genre: String,
    pub ingested_at: i64,
}

pub fn hash_password(pw: &str) -> anyhow::Result<String> {
    let h =
        Argon2::default().hash_password_with_salt(pw.as_bytes(), &random_bytes::<16>()).map_err(|e| anyhow::anyhow!("{e}"))?;
    Ok(h.to_string())
}

pub fn create_user(qb: &QueryBook, username: &str, password: &str, roles: &[&str], tenant: &str) -> anyhow::Result<i64> {
    anyhow::ensure!(username.len() >= 2 && password.len() >= 4, "username >= 2 chars, password >= 4 chars");
    let h = hash_password(password)?;
    qb.store.write(|c| {
        c.execute(
            "INSERT INTO users(username, pass_hash, roles, tenant, created) VALUES(?1,?2,?3,?4,?5)
             ON CONFLICT(username) DO UPDATE SET pass_hash=excluded.pass_hash, roles=excluded.roles, tenant=excluded.tenant",
            params![username, h, roles.join(","), tenant, now_secs()],
        )?;
        Ok(c.query_row("SELECT id FROM users WHERE username=?1", [username], |r| r.get(0))?)
    })
}

fn row_user(r: &rusqlite::Row) -> rusqlite::Result<User> {
    let roles: String = r.get(2)?;
    Ok(User {
        id: r.get(0)?,
        username: r.get(1)?,
        roles: roles.split(',').filter(|s| !s.is_empty()).map(String::from).collect(),
        tenant: r.get(3)?,
    })
}

pub fn login(qb: &QueryBook, username: &str, password: &str, device: &str) -> anyhow::Result<Option<(String, User)>> {
    let row: Option<(User, String)> = qb.store.read(|c| {
        Ok(c.query_row("SELECT id, username, roles, tenant, pass_hash FROM users WHERE username=?1", [username], |r| {
            Ok((row_user(r)?, r.get::<_, String>(4)?))
        })
        .optional()?)
    })?;
    let Some((user, hash)) = row else { return Ok(None) };
    if Argon2::default().verify_password(password.as_bytes(), hash.as_str()).is_err() {
        return Ok(None);
    }
    let token = hex::encode(random_bytes::<32>());
    qb.store.write(|c| {
        c.execute(
            "INSERT INTO sessions(token_hash, user_id, created, device) VALUES(?1,?2,?3,?4)",
            params![sha256_hex(token.as_bytes()), user.id, now_secs(), device],
        )?;
        Ok(())
    })?;
    Ok(Some((token, user)))
}

pub fn user_for_token(qb: &QueryBook, token: &str) -> anyhow::Result<Option<(User, String)>> {
    let th = sha256_hex(token.as_bytes());
    qb.store.read(|c| {
        Ok(c.query_row(
            "SELECT u.id, u.username, u.roles, u.tenant, s.device FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?1",
            [&th],
            |r| Ok((row_user(r)?, r.get::<_, String>(4)?)),
        )
        .optional()?)
    })
}

pub fn logout(qb: &QueryBook, token: &str) -> anyhow::Result<()> {
    qb.store.write(|c| {
        c.execute("DELETE FROM sessions WHERE token_hash=?1", [sha256_hex(token.as_bytes())])?;
        Ok(())
    })
}

/// QBF-C171: access requires both an available seat and the entitlement.
pub fn has_seat(qb: &QueryBook, user: &User) -> anyhow::Result<bool> {
    qb.store.read(|c| {
        let seats: Option<i64> =
            c.query_row("SELECT seats FROM seats WHERE tenant=?1", [&user.tenant], |r| r.get(0)).optional()?;
        let Some(seats) = seats else { return Ok(true) }; // unmetered tenant
        let rank: i64 =
            c.query_row("SELECT COUNT(*) FROM users WHERE tenant=?1 AND id<=?2", params![user.tenant, user.id], |r| r.get(0))?;
        Ok(rank <= seats)
    })
}

pub fn grant(qb: &QueryBook, user_id: i64, work: &str, kind: &str) -> anyhow::Result<()> {
    qb.store.write(|c| {
        c.execute(
            "INSERT OR REPLACE INTO entitlements(user_id, work, grant_kind) VALUES(?1,?2,?3)",
            params![user_id, work, kind],
        )?;
        Ok(())
    })
}

fn row_work(r: &rusqlite::Row) -> rusqlite::Result<WorkRow> {
    let ch: String = r.get(6)?;
    Ok(WorkRow {
        id: r.get(0)?,
        title: r.get(1)?,
        author: r.get(2)?,
        rights: r.get(3)?,
        positions: r.get::<_, i64>(4)? as u64,
        facts: r.get::<_, i64>(5)? as u64,
        chapters: serde_json::from_str(&ch).unwrap_or(serde_json::Value::Null),
        engines: r.get(7)?,
        genre: r.get(8)?,
        ingested_at: r.get(9)?,
    })
}
const WORK_COLS: &str = "id,title,author,rights,positions,facts,chapters,engines,genre,ingested_at";

pub fn all_works(qb: &QueryBook) -> anyhow::Result<Vec<WorkRow>> {
    qb.store.read(|c| {
        let mut st = c.prepare(&format!("SELECT {WORK_COLS} FROM works ORDER BY title"))?;
        let rows = st.query_map([], row_work)?;
        Ok(rows.collect::<Result<_, _>>()?)
    })
}

pub fn work(qb: &QueryBook, id: &str) -> anyhow::Result<Option<WorkRow>> {
    qb.store.read(|c| Ok(c.query_row(&format!("SELECT {WORK_COLS} FROM works WHERE id=?1"), [id], row_work).optional()?))
}

pub fn entitled(qb: &QueryBook, user: &User, work_id: &str) -> anyhow::Result<bool> {
    if !has_seat(qb, user)? {
        return Ok(false);
    }
    if user.has("operator") {
        return Ok(true);
    }
    let Some(w) = work(qb, work_id)? else { return Ok(false) };
    if qb.cfg.library.open_public_domain && w.rights == "public-domain" {
        return Ok(true);
    }
    qb.store.read(|c| {
        Ok(c.query_row("SELECT 1 FROM entitlements WHERE user_id=?1 AND work=?2", params![user.id, work_id], |_| Ok(()))
            .optional()?
            .is_some())
    })
}

pub fn library(qb: &QueryBook, user: &User) -> anyhow::Result<Vec<WorkRow>> {
    let mut out = Vec::new();
    for w in all_works(qb)? {
        if entitled(qb, user, &w.id)? {
            out.push(w);
        }
    }
    Ok(out)
}

#[derive(Clone, Debug, Serialize)]
pub struct Progress {
    pub pos: u64,
    pub spoiler: bool,
}

pub fn progress(qb: &QueryBook, user: &User, work: &str) -> anyhow::Result<Progress> {
    let r: Option<(i64, i64)> = qb.store.read(|c| {
        Ok(c.query_row("SELECT pos, spoiler FROM progress WHERE user_id=?1 AND work=?2", params![user.id, work], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .optional()?)
    })?;
    Ok(match r {
        Some((p, s)) => Progress { pos: p as u64, spoiler: s != 0 },
        None => Progress { pos: 0, spoiler: qb.cfg.library.spoiler_default },
    })
}

pub fn set_progress(
    qb: &QueryBook,
    user: &User,
    work: &str,
    pos: Option<u64>,
    spoiler: Option<bool>,
) -> anyhow::Result<Progress> {
    let cur = progress(qb, user, work)?;
    let p = Progress { pos: pos.unwrap_or(cur.pos), spoiler: spoiler.unwrap_or(cur.spoiler) };
    qb.store.write(|c| {
        c.execute(
            "INSERT OR REPLACE INTO progress(user_id, work, pos, spoiler, updated) VALUES(?1,?2,?3,?4,?5)",
            params![user.id, work, p.pos as i64, p.spoiler as i64, now_secs()],
        )?;
        Ok(())
    })?;
    Ok(p)
}

/// The scope description: bounded by entitlement, reading position and ACL
/// identities before any record is traversed.
#[derive(Clone, Debug, Serialize)]
pub struct Scope {
    user_id: i64,
    acl: Vec<String>,
    /// (work, highest traversable narrative position)
    works: Vec<(String, u64)>,
    /// non-book corpora (e.g. imported UFCS feeds) the reader enabled
    corpora: Vec<String>,
    spoiler_bounded: bool,
    marker: u64,
}

impl Scope {
    pub fn user_id(&self) -> i64 {
        self.user_id
    }
    pub fn acl(&self) -> &[String] {
        &self.acl
    }
    pub fn works(&self) -> &[(String, u64)] {
        &self.works
    }
    pub fn corpora(&self) -> &[String] {
        &self.corpora
    }
    pub fn spoiler_bounded(&self) -> bool {
        self.spoiler_bounded
    }
    pub fn marker(&self) -> u64 {
        self.marker
    }
    pub fn primary_work(&self) -> Option<&str> {
        self.works.first().map(|(w, _)| w.as_str())
    }
    /// Is a record at this position of this work inside the scope?
    pub fn admits(&self, work: Option<&str>, pos: u64) -> bool {
        match work {
            Some(w) => self.works.iter().any(|(sw, max)| sw == w && pos <= *max),
            None => true,
        }
    }
    /// Same scope with the reading bound lifted: used only to *count* whether
    /// an answer exists later in the book, never to traverse it.
    pub fn unbounded_probe(&self) -> Scope {
        let mut s = self.clone();
        for w in s.works.iter_mut() {
            w.1 = u64::MAX;
        }
        s.spoiler_bounded = false;
        s
    }
    /// The same scope restricted to the entitled works (no imported corpora).
    pub fn book_only(&self) -> Scope {
        let mut s = self.clone();
        s.corpora.clear();
        s
    }
    /// The same scope restricted to the enabled corpora (no works).
    pub fn world_only(&self) -> Scope {
        let mut s = self.clone();
        s.works.clear();
        s
    }
    pub fn entitlement_dims(&self) -> Vec<String> {
        let mut v: Vec<String> = self.works.iter().map(|(w, m)| format!("{w}@{m}")).collect();
        v.extend(self.corpora.iter().map(|c| format!("corpus:{c}")));
        v.sort();
        v
    }
}

pub struct ScopeRequest<'a> {
    pub work: &'a str,
    /// include imported world-knowledge corpora (UFCS feeds) beyond the book
    pub include_world: bool,
    /// override the stored reading position (e.g. the page the reader is on)
    pub at_pos: Option<u64>,
}

pub fn scope_for(qb: &QueryBook, user: &User, req: &ScopeRequest, trace: &mut Trace) -> anyhow::Result<Scope> {
    trace.cross(Domain::D9, Domain::D8, "resolve-scope")?;
    anyhow::ensure!(entitled(qb, user, req.work)?, "not entitled to '{}' (or no seat available)", req.work);
    let prog = progress(qb, user, req.work)?;
    let exempt = user.has("instructor") || user.has("researcher") || user.has("author");
    let bounded = prog.spoiler && !exempt;
    // the bound is the furthest point read, whichever page is open now
    let marker = req.at_pos.map(|p| p.max(prog.pos)).unwrap_or(prog.pos);
    let max = if bounded { marker } else { u64::MAX };
    let mut acl = vec![format!("work:{}", req.work), format!("user:{}", user.id), format!("tenant:{}", user.tenant)];
    let mut corpora = Vec::new();
    if req.include_world {
        acl.push("public".into());
        corpora = qb.store.read(|c| {
            let mut st = c.prepare("SELECT feed FROM import_cursors ORDER BY feed")?;
            let r = st.query_map([], |r| r.get::<_, String>(0))?;
            Ok(r.collect::<Result<Vec<_>, _>>()?)
        })?;
    }
    acl.sort();
    trace.cross(Domain::D8, Domain::D4, "scope-description")?;
    Ok(Scope { user_id: user.id, acl, works: vec![(req.work.to_string(), max)], corpora, spoiler_bounded: bounded, marker })
}

/// Scope used by ingestion-time pre-computation: the whole work, no reader.
pub fn precompute_scope(work: &str) -> Scope {
    Scope {
        user_id: 0,
        acl: vec![format!("work:{work}")],
        works: vec![(work.to_string(), u64::MAX)],
        corpora: vec![],
        spoiler_bounded: false,
        marker: u64::MAX,
    }
}

/// Scope over imported corpora only (operator tooling and benchmarks).
pub fn world_scope(corpora: &[String]) -> Scope {
    Scope {
        user_id: 0,
        acl: vec!["public".into()],
        works: vec![],
        corpora: corpora.to_vec(),
        spoiler_bounded: false,
        marker: u64::MAX,
    }
}

// ---- retention (QBF-C173 retain by default, erasure as option) -----------

pub fn record_history(
    qb: &QueryBook,
    user: &User,
    session: &str,
    work: &str,
    mode: &str,
    query: &str,
    answer: &str,
    fuids: &[String],
    key: &str,
) -> anyhow::Result<()> {
    qb.store.write(|c| {
        c.execute(
            "INSERT INTO history(user_id, session, work, ts, mode, query, answer, fuids, context_key) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9)",
            params![user.id, session, work, now_secs(), mode, query, answer, fuids.join(","), key],
        )?;
        Ok(())
    })
}

#[derive(Serialize)]
pub struct HistoryRow {
    pub id: i64,
    pub work: String,
    pub ts: i64,
    pub mode: String,
    pub query: String,
    pub answer: String,
    pub fuids: Vec<String>,
}

pub fn history(qb: &QueryBook, user: &User, limit: usize) -> anyhow::Result<Vec<HistoryRow>> {
    qb.store.read(|c| {
        let mut st = c.prepare(
            "SELECT id, work, ts, mode, query, answer, fuids FROM history WHERE user_id=?1 ORDER BY ts DESC, id DESC LIMIT ?2",
        )?;
        let rows = st.query_map(params![user.id, limit as i64], |r| {
            let f: String = r.get(6)?;
            Ok(HistoryRow {
                id: r.get(0)?,
                work: r.get(1)?,
                ts: r.get(2)?,
                mode: r.get(3)?,
                query: r.get(4)?,
                answer: r.get(5)?,
                fuids: f.split(',').filter(|s| !s.is_empty()).map(String::from).collect(),
            })
        })?;
        Ok(rows.collect::<Result<_, _>>()?)
    })
}

/// Erasure at session, work or account scope; the ledger records that an
/// erasure occurred, never what was erased.
pub fn erase_history(qb: &QueryBook, user: &User, scope: &str, key: &str) -> anyhow::Result<usize> {
    let n = qb.store.write(|c| {
        Ok(match scope {
            "session" => c.execute("DELETE FROM history WHERE user_id=?1 AND session=?2", params![user.id, key])?,
            "work" => c.execute("DELETE FROM history WHERE user_id=?1 AND work=?2", params![user.id, key])?,
            "account" => {
                let n = c.execute("DELETE FROM history WHERE user_id=?1", [user.id])?;
                c.execute("DELETE FROM cards WHERE user_id=?1", [user.id])?;
                n
            }
            _ => anyhow::bail!("scope must be session, work or account"),
        })
    })?;
    qb.store.ledger_append(
        &format!("user:{}", user.id),
        &format!("erasure.{scope}"),
        "D8 retention",
        "content-not-retained",
        "erasure",
    )?;
    Ok(n)
}
