//! QBF-C031 Provenance Ledger and QBF-C178 signed verification.
//!
//! Append-only, hash-linked chain. Each node records the operation, the
//! actor, the domains crossed, the safety evaluation that ran, and (for a
//! batch of admitted records) the Merkle root over their FUIDs. Each node
//! carries a keyed checksum (HMAC with the deployment key) so a node whose
//! recorded safety evaluation does not match what ran is detectable, and an
//! Ed25519 signature with the deployment signing key.

use crate::util::{random_bytes, sha256, sha256_hex};
use ed25519_dalek::{Signer, SigningKey, Verifier, VerifyingKey};
use hmac::{Hmac, KeyInit, Mac};
use rusqlite::{Connection, OptionalExtension, params};
use serde::Serialize;
use sha2::Sha256;
use std::path::Path;

pub struct Keys {
    mac: Vec<u8>,
    signing: SigningKey,
}

impl Keys {
    /// Tenant-scoped key custody (QBF-C177): keys live in the deployment's
    /// data directory, generated on first start, never leave it.
    pub fn load_or_create(dir: &Path) -> anyhow::Result<Keys> {
        std::fs::create_dir_all(dir)?;
        let mac_path = dir.join("ledger-mac.key");
        let sig_path = dir.join("ledger-sign.key");
        if !mac_path.exists() {
            write_secret(&mac_path, &random_bytes::<32>())?;
        }
        if !sig_path.exists() {
            write_secret(&sig_path, &random_bytes::<32>())?;
        }
        let mac = std::fs::read(&mac_path)?;
        let sig: [u8; 32] = std::fs::read(&sig_path)?.try_into().map_err(|_| anyhow::anyhow!("signing key must be 32 bytes"))?;
        Ok(Keys { mac, signing: SigningKey::from_bytes(&sig) })
    }

    pub fn verifying_key_hex(&self) -> String {
        hex::encode(self.signing.verifying_key().to_bytes())
    }

    fn mac(&self, msg: &[u8]) -> String {
        let mut m = <Hmac<Sha256> as KeyInit>::new_from_slice(&self.mac).expect("hmac key");
        m.update(msg);
        hex::encode(m.finalize().into_bytes())
    }
}

fn write_secret(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    std::fs::write(path, bytes)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    }
    Ok(())
}

pub const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS ledger(
  seq INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  actor TEXT NOT NULL,
  op TEXT NOT NULL,
  crossing TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  safety TEXT NOT NULL,
  merkle_root TEXT NOT NULL,
  leaves INTEGER NOT NULL,
  substrate INTEGER NOT NULL,
  prev TEXT NOT NULL,
  hash TEXT NOT NULL,
  mac TEXT NOT NULL,
  sig TEXT NOT NULL
);";

#[derive(Clone, Debug, Serialize)]
pub struct Node {
    pub seq: u64,
    pub ts: i64,
    pub actor: String,
    pub op: String,
    pub crossing: String,
    pub payload_hash: String,
    pub safety: String,
    pub merkle_root: String,
    pub leaves: u64,
    /// Did this node mutate the substrate? (drives the store version)
    pub substrate: bool,
    pub prev: String,
    pub hash: String,
    pub mac: String,
    pub sig: String,
}

pub struct Append<'a> {
    pub actor: &'a str,
    pub op: &'a str,
    pub crossing: &'a str,
    pub payload_hash: String,
    pub safety: String,
    pub leaves: &'a [String],
    pub substrate: bool,
    pub ts: i64,
}

fn node_hash(prev: &str, seq: u64, a: &Append, root: &str) -> String {
    sha256_hex(
        format!(
            "ledger-v1|{prev}|{seq}|{}|{}|{}|{}|{}|{}|{root}|{}|{}",
            a.ts,
            a.actor,
            a.op,
            a.crossing,
            a.payload_hash,
            a.safety,
            a.leaves.len(),
            a.substrate as u8
        )
        .as_bytes(),
    )
}

pub fn head(conn: &Connection) -> anyhow::Result<(u64, String)> {
    let r: Option<(i64, String)> = conn
        .query_row("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1", [], |r| Ok((r.get(0)?, r.get(1)?)))
        .optional()?;
    Ok(r.map(|(s, h)| (s as u64, h)).unwrap_or((0, "genesis".into())))
}

/// Head hash of the last substrate-mutating node: the store version that
/// enters every context-lock key.
pub fn substrate_head(conn: &Connection) -> anyhow::Result<String> {
    let r: Option<String> =
        conn.query_row("SELECT hash FROM ledger WHERE substrate=1 ORDER BY seq DESC LIMIT 1", [], |r| r.get(0)).optional()?;
    Ok(r.unwrap_or_else(|| "genesis".into()))
}

pub fn append(conn: &Connection, keys: &Keys, a: Append) -> anyhow::Result<Node> {
    let (last, prev) = head(conn)?;
    let seq = last + 1;
    let root = merkle_root(a.leaves);
    let hash = node_hash(&prev, seq, &a, &root);
    let mac = keys.mac(format!("{hash}|{}", a.safety).as_bytes());
    let sig = hex::encode(keys.signing.sign(hash.as_bytes()).to_bytes());
    conn.execute(
        "INSERT INTO ledger(seq,ts,actor,op,crossing,payload_hash,safety,merkle_root,leaves,substrate,prev,hash,mac,sig)
         VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)",
        params![
            seq as i64,
            a.ts,
            a.actor,
            a.op,
            a.crossing,
            a.payload_hash,
            a.safety,
            root,
            a.leaves.len() as i64,
            a.substrate as i64,
            prev,
            hash,
            mac,
            sig
        ],
    )?;
    Ok(Node {
        seq,
        ts: a.ts,
        actor: a.actor.into(),
        op: a.op.into(),
        crossing: a.crossing.into(),
        payload_hash: a.payload_hash,
        safety: a.safety,
        merkle_root: root,
        leaves: a.leaves.len() as u64,
        substrate: a.substrate,
        prev,
        hash,
        mac,
        sig,
    })
}

fn row_to_node(r: &rusqlite::Row) -> rusqlite::Result<Node> {
    Ok(Node {
        seq: r.get::<_, i64>(0)? as u64,
        ts: r.get(1)?,
        actor: r.get(2)?,
        op: r.get(3)?,
        crossing: r.get(4)?,
        payload_hash: r.get(5)?,
        safety: r.get(6)?,
        merkle_root: r.get(7)?,
        leaves: r.get::<_, i64>(8)? as u64,
        substrate: r.get::<_, i64>(9)? != 0,
        prev: r.get(10)?,
        hash: r.get(11)?,
        mac: r.get(12)?,
        sig: r.get(13)?,
    })
}

const NODE_COLS: &str = "seq,ts,actor,op,crossing,payload_hash,safety,merkle_root,leaves,substrate,prev,hash,mac,sig";

pub fn node(conn: &Connection, seq: u64) -> anyhow::Result<Option<Node>> {
    Ok(conn.query_row(&format!("SELECT {NODE_COLS} FROM ledger WHERE seq=?1"), [seq as i64], row_to_node).optional()?)
}

pub fn recent(conn: &Connection, limit: usize) -> anyhow::Result<Vec<Node>> {
    let mut st = conn.prepare(&format!("SELECT {NODE_COLS} FROM ledger ORDER BY seq DESC LIMIT ?1"))?;
    let rows = st.query_map([limit as i64], row_to_node)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

#[derive(Clone, Debug, Serialize)]
pub struct Verification {
    pub nodes: u64,
    pub verified: u64,
    pub first_failure: Option<String>,
    pub head: String,
    pub verifying_key: String,
}

/// Walk the whole chain: recompute every hash link, the keyed checksum and
/// the signature. A node is admitted to the report only if its signature
/// verifies against the deployment key.
pub fn verify(conn: &Connection, keys: &Keys) -> anyhow::Result<Verification> {
    let vk: VerifyingKey = keys.signing.verifying_key();
    let mut st = conn.prepare(&format!("SELECT {NODE_COLS} FROM ledger ORDER BY seq ASC"))?;
    let rows = st.query_map([], row_to_node)?;
    let mut prev = "genesis".to_string();
    let mut n = 0u64;
    let mut ok = 0u64;
    let mut failure = None;
    for row in rows {
        let node = row?;
        n += 1;
        if failure.is_some() {
            continue;
        }
        let a = Append {
            actor: &node.actor,
            op: &node.op,
            crossing: &node.crossing,
            payload_hash: node.payload_hash.clone(),
            safety: node.safety.clone(),
            leaves: &vec![String::new(); node.leaves as usize],
            substrate: node.substrate,
            ts: node.ts,
        };
        let expect = node_hash(&prev, node.seq, &a, &node.merkle_root);
        let mac_ok = keys.mac(format!("{}|{}", node.hash, node.safety).as_bytes()) == node.mac;
        let sig_ok = hex::decode(&node.sig)
            .ok()
            .and_then(|b| <[u8; 64]>::try_from(b).ok())
            .map(|b| vk.verify(node.hash.as_bytes(), &ed25519_dalek::Signature::from_bytes(&b)).is_ok())
            .unwrap_or(false);
        if node.prev != prev || expect != node.hash {
            failure = Some(format!("node {}: hash link broken", node.seq));
        } else if !mac_ok {
            failure = Some(format!("node {}: keyed checksum mismatch (safety evaluation altered)", node.seq));
        } else if !sig_ok {
            failure = Some(format!("node {}: signature does not verify", node.seq));
        } else {
            ok += 1;
        }
        prev = node.hash.clone();
    }
    Ok(Verification { nodes: n, verified: ok, first_failure: failure, head: prev, verifying_key: keys.verifying_key_hex() })
}

// ---- Merkle tree over a batch's FUIDs ------------------------------------

fn leaf(fuid: &str) -> [u8; 32] {
    sha256(format!("leaf|{fuid}").as_bytes())
}

fn parent(a: &[u8; 32], b: &[u8; 32]) -> [u8; 32] {
    let mut buf = Vec::with_capacity(70);
    buf.extend_from_slice(b"node|");
    buf.extend_from_slice(a);
    buf.extend_from_slice(b);
    sha256(&buf)
}

pub fn merkle_root(fuids: &[String]) -> String {
    if fuids.is_empty() {
        return "empty".into();
    }
    let mut level: Vec<[u8; 32]> = fuids.iter().map(|f| leaf(f)).collect();
    while level.len() > 1 {
        level = level.chunks(2).map(|c| parent(&c[0], c.get(1).unwrap_or(&c[0]))).collect();
    }
    hex::encode(level[0])
}

/// Inclusion proof for leaf `idx`: sibling hashes bottom-up with side flags.
pub fn merkle_proof(fuids: &[String], idx: usize) -> Vec<(bool, String)> {
    let mut proof = Vec::new();
    let mut level: Vec<[u8; 32]> = fuids.iter().map(|f| leaf(f)).collect();
    let mut i = idx;
    while level.len() > 1 {
        let sib = if i % 2 == 0 { level.get(i + 1).unwrap_or(&level[i]) } else { &level[i - 1] };
        proof.push((i % 2 == 0, hex::encode(sib)));
        level = level.chunks(2).map(|c| parent(&c[0], c.get(1).unwrap_or(&c[0]))).collect();
        i /= 2;
    }
    proof
}

pub fn merkle_verify(fuid: &str, proof: &[(bool, String)], root: &str) -> bool {
    let mut h = leaf(fuid);
    for (sib_on_right, sib) in proof {
        let Ok(s) = hex::decode(sib) else { return false };
        let Ok(s): Result<[u8; 32], _> = s.try_into() else { return false };
        h = if *sib_on_right { parent(&h, &s) } else { parent(&s, &h) };
    }
    hex::encode(h) == root
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn merkle_proofs() {
        let f: Vec<String> = (0..7).map(|i| format!("f{i}")).collect();
        let root = merkle_root(&f);
        for i in 0..f.len() {
            assert!(merkle_verify(&f[i], &merkle_proof(&f, i), &root));
        }
        assert!(!merkle_verify("forged", &merkle_proof(&f, 2), &root));
    }

    #[test]
    fn chain_detects_tampering() {
        let dir = std::env::temp_dir().join(format!("qb-ledger-{}", hex::encode(random_bytes::<6>())));
        let keys = Keys::load_or_create(&dir).unwrap();
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(SCHEMA).unwrap();
        for i in 0..3 {
            let leaves = vec![format!("a{i}"), format!("b{i}")];
            append(
                &conn,
                &keys,
                Append {
                    actor: "t",
                    op: "commit",
                    crossing: "D1->D2",
                    payload_hash: "x".into(),
                    safety: "ok".into(),
                    leaves: &leaves,
                    substrate: true,
                    ts: 1,
                },
            )
            .unwrap();
        }
        let v = verify(&conn, &keys).unwrap();
        assert_eq!((v.nodes, v.verified, v.first_failure.is_none()), (3, 3, true));
        conn.execute("UPDATE ledger SET safety='bypassed' WHERE seq=2", []).unwrap();
        let v = verify(&conn, &keys).unwrap();
        assert!(v.first_failure.unwrap().contains("node 2"));
        let _ = std::fs::remove_dir_all(dir);
    }
}
