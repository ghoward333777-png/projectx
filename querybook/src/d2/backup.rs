//! Backup and restore of a whole data directory (store, index, ledger keys).
//!
//! A backup is one file, `querybook-<time>.qbk`:
//!
//!   header   "QBK1" | salt[16] | nonce base[16] | chunk size u32
//!   chunks   len u32 | XChaCha20-Poly1305(ciphertext), AAD = header | index u64 | final u8
//!   plaintext (inside the chunks): zstd stream of entries
//!            path len u16 | path | size u64 | bytes | sha256[32]   … then a zero-length path
//!
//! The key is derived from the operator's passphrase with Argon2id, so the
//! file can sit in cloud storage: without the passphrase it reveals nothing,
//! and any change, reordering or truncation is detected on restore. The ledger
//! signing keys travel inside the encrypted archive — a restore without them
//! could not verify or extend the ledger.
//!
//! The snapshot is consistent: the index writer lock is held (so no ingest or
//! import can commit) while the database is copied with `VACUUM INTO` and the
//! index's immutable segment files are hard-linked. Readers keep answering.

use super::Store;
use chacha20poly1305::aead::{Aead, KeyInit, Payload};
use chacha20poly1305::{XChaCha20Poly1305, XNonce};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::Instant;

const MAGIC: &[u8; 4] = b"QBK1";
const CHUNK: usize = 4 << 20;
const HEADER_LEN: usize = 4 + 16 + 16 + 4;

fn derive_key(passphrase: &str, salt: &[u8]) -> anyhow::Result<[u8; 32]> {
    anyhow::ensure!(passphrase.chars().count() >= 12, "the backup passphrase must be at least 12 characters");
    let params = argon2::Params::new(64 * 1024, 3, 1, Some(32)).map_err(|e| anyhow::anyhow!("argon2 params: {e}"))?;
    let a = argon2::Argon2::new(argon2::Algorithm::Argon2id, argon2::Version::V0x13, params);
    let mut key = [0u8; 32];
    a.hash_password_into(passphrase.as_bytes(), salt, &mut key).map_err(|e| anyhow::anyhow!("key derivation: {e}"))?;
    Ok(key)
}

fn nonce(base: &[u8; 16], idx: u64) -> XNonce {
    let mut n = [0u8; 24];
    n[..16].copy_from_slice(base);
    n[16..].copy_from_slice(&idx.to_be_bytes());
    XNonce::from(n)
}

fn aad(header: &[u8], idx: u64, last: bool) -> Vec<u8> {
    let mut a = header.to_vec();
    a.extend_from_slice(&idx.to_be_bytes());
    a.push(last as u8);
    a
}

/// Encrypts everything written to it into authenticated chunks.
pub struct EncryptWriter<W: Write> {
    out: W,
    cipher: XChaCha20Poly1305,
    header: Vec<u8>,
    base: [u8; 16],
    buf: Vec<u8>,
    idx: u64,
    pub written: u64,
}

impl<W: Write> EncryptWriter<W> {
    pub fn new(mut out: W, passphrase: &str) -> anyhow::Result<Self> {
        let mut salt = [0u8; 16];
        let mut base = [0u8; 16];
        getrandom::fill(&mut salt).map_err(|e| anyhow::anyhow!("random: {e}"))?;
        getrandom::fill(&mut base).map_err(|e| anyhow::anyhow!("random: {e}"))?;
        let key = derive_key(passphrase, &salt)?;
        let mut header = Vec::with_capacity(HEADER_LEN);
        header.extend_from_slice(MAGIC);
        header.extend_from_slice(&salt);
        header.extend_from_slice(&base);
        header.extend_from_slice(&(CHUNK as u32).to_be_bytes());
        out.write_all(&header)?;
        Ok(EncryptWriter {
            out,
            cipher: XChaCha20Poly1305::new((&key).into()),
            written: header.len() as u64,
            header,
            base,
            buf: Vec::with_capacity(CHUNK),
            idx: 0,
        })
    }

    fn seal(&mut self, last: bool) -> std::io::Result<()> {
        let ct = self
            .cipher
            .encrypt(&nonce(&self.base, self.idx), Payload { msg: &self.buf, aad: &aad(&self.header, self.idx, last) })
            .map_err(|_| std::io::Error::other("encryption failed"))?;
        self.out.write_all(&(ct.len() as u32).to_be_bytes())?;
        self.out.write_all(&ct)?;
        self.written += 4 + ct.len() as u64;
        self.idx += 1;
        self.buf.clear();
        Ok(())
    }

    /// Seal the final chunk (marks the end, so truncation is detectable).
    pub fn finish(mut self) -> std::io::Result<W> {
        self.seal(true)?;
        self.out.flush()?;
        Ok(self.out)
    }
}

impl<W: Write> Write for EncryptWriter<W> {
    fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
        let mut rest = data;
        while !rest.is_empty() {
            let take = (CHUNK - self.buf.len()).min(rest.len());
            self.buf.extend_from_slice(&rest[..take]);
            rest = &rest[take..];
            if self.buf.len() == CHUNK {
                self.seal(false)?;
            }
        }
        Ok(data.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.out.flush()
    }
}

/// Authenticates and decrypts a `.qbk` stream; errors on any tampering,
/// a wrong passphrase, or a missing final chunk.
pub struct DecryptReader<R: Read> {
    inp: R,
    cipher: XChaCha20Poly1305,
    header: Vec<u8>,
    base: [u8; 16],
    buf: Vec<u8>,
    pos: usize,
    idx: u64,
    done: bool,
}

impl<R: Read> DecryptReader<R> {
    pub fn new(mut inp: R, passphrase: &str) -> anyhow::Result<Self> {
        let mut header = vec![0u8; HEADER_LEN];
        inp.read_exact(&mut header).map_err(|_| anyhow::anyhow!("not a QueryBook backup (too short)"))?;
        anyhow::ensure!(&header[..4] == MAGIC, "not a QueryBook backup (bad magic)");
        let key = derive_key(passphrase, &header[4..20])?;
        let mut base = [0u8; 16];
        base.copy_from_slice(&header[20..36]);
        Ok(DecryptReader {
            inp,
            cipher: XChaCha20Poly1305::new((&key).into()),
            header,
            base,
            buf: vec![],
            pos: 0,
            idx: 0,
            done: false,
        })
    }

    fn next_chunk(&mut self) -> std::io::Result<bool> {
        if self.done {
            return Ok(false);
        }
        let mut len = [0u8; 4];
        if let Err(e) = self.inp.read_exact(&mut len) {
            return Err(if e.kind() == std::io::ErrorKind::UnexpectedEof {
                std::io::Error::other("backup is truncated (final chunk missing)")
            } else {
                e
            });
        }
        let n = u32::from_be_bytes(len) as usize;
        if n > CHUNK + 64 {
            return Err(std::io::Error::other("backup is corrupt (chunk length)"));
        }
        let mut ct = vec![0u8; n];
        self.inp.read_exact(&mut ct).map_err(|_| std::io::Error::other("backup is truncated"))?;
        let nn = nonce(&self.base, self.idx);
        let pt = match self.cipher.decrypt(&nn, Payload { msg: &ct, aad: &aad(&self.header, self.idx, false) }) {
            Ok(p) => p,
            Err(_) => match self.cipher.decrypt(&nn, Payload { msg: &ct, aad: &aad(&self.header, self.idx, true) }) {
                Ok(p) => {
                    self.done = true;
                    let mut probe = [0u8; 1];
                    if self.inp.read(&mut probe)? != 0 {
                        return Err(std::io::Error::other("backup is corrupt (data after the final chunk)"));
                    }
                    p
                }
                Err(_) => {
                    return Err(std::io::Error::other(if self.idx == 0 {
                        "wrong passphrase, or the backup was altered"
                    } else {
                        "backup was altered or is corrupt"
                    }));
                }
            },
        };
        self.idx += 1;
        self.buf = pt;
        self.pos = 0;
        Ok(true)
    }
}

impl<R: Read> Read for DecryptReader<R> {
    fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
        while self.pos >= self.buf.len() {
            if !self.next_chunk()? {
                return Ok(0);
            }
        }
        let n = (self.buf.len() - self.pos).min(out.len());
        out[..n].copy_from_slice(&self.buf[self.pos..self.pos + n]);
        self.pos += n;
        Ok(n)
    }
}

// ---------------------------------------------------------------- archive

fn write_entry(w: &mut impl Write, path: &str, mut src: impl Read, size: u64) -> anyhow::Result<()> {
    let p = path.as_bytes();
    w.write_all(&(p.len() as u16).to_be_bytes())?;
    w.write_all(p)?;
    w.write_all(&size.to_be_bytes())?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 1 << 20];
    let mut left = size;
    while left > 0 {
        let want = left.min(buf.len() as u64) as usize;
        let n = src.read(&mut buf[..want])?;
        anyhow::ensure!(n > 0, "{path} shrank while being backed up");
        h.update(&buf[..n]);
        w.write_all(&buf[..n])?;
        left -= n as u64;
    }
    w.write_all(&h.finalize())?;
    Ok(())
}

fn files_under(root: &Path, rel: &Path, out: &mut Vec<PathBuf>) -> std::io::Result<()> {
    let dir = root.join(rel);
    let mut entries: Vec<_> = std::fs::read_dir(&dir)?.flatten().collect();
    entries.sort_by_key(|e| e.file_name());
    for e in entries {
        let r = rel.join(e.file_name());
        if e.file_type()?.is_dir() {
            files_under(root, &r, out)?;
        } else {
            out.push(r);
        }
    }
    Ok(())
}

#[derive(Debug, Serialize)]
pub struct BackupReport {
    pub file: String,
    pub bytes: u64,
    pub files: usize,
    pub facts: u64,
    pub ledger_head: String,
    pub sha256: String,
    pub seconds: f64,
}

/// Write an encrypted snapshot of the store to `dest` (a new file).
pub fn create(store: &Store, dest: &Path, passphrase: &str, actor: &str) -> anyhow::Result<BackupReport> {
    let t0 = Instant::now();
    anyhow::ensure!(!dest.exists(), "{} already exists", dest.display());
    let parent = dest.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
    std::fs::create_dir_all(parent)?;
    let staging = parent.join(format!(".qb-staging-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&staging);
    std::fs::create_dir_all(staging.join("index"))?;
    let cleanup = scopeguard(&staging);

    // consistent snapshot: no commit can land while the writer lock is held
    let src = store.dir.clone();
    store.index.hold_writer(|| {
        let db = staging.join("querybook.sqlite");
        store.write(|c| {
            c.execute("VACUUM INTO ?1", [db.to_string_lossy().as_ref()])?;
            Ok(())
        })?;
        for e in std::fs::read_dir(src.join("index"))?.flatten() {
            let to = staging.join("index").join(e.file_name());
            if e.file_type()?.is_file() && std::fs::hard_link(e.path(), &to).is_err() {
                std::fs::copy(e.path(), &to)?;
            }
        }
        Ok(())
    })?;
    let _ = std::fs::remove_file(staging.join("index").join(".tantivy-writer.lock"));
    let _ = std::fs::remove_file(staging.join("index").join(".tantivy-meta.lock"));
    std::fs::create_dir_all(staging.join("keys"))?;
    for e in std::fs::read_dir(src.join("keys"))?.flatten() {
        if e.file_type()?.is_file() {
            std::fs::copy(e.path(), staging.join("keys").join(e.file_name()))?;
        }
    }
    let (facts, head) = store.read(|c| {
        let n: i64 = c.query_row("SELECT COUNT(*) FROM facts", [], |r| r.get(0))?;
        Ok((n as u64, super::ledger::head(c)?.1))
    })?;

    let mut files = Vec::new();
    files_under(&staging, Path::new(""), &mut files)?;
    let manifest = serde_json::json!({
        "format": "QBK1", "created": crate::util::now_secs(), "facts": facts, "ledger_head": head,
        "files": files.iter().map(|f| f.to_string_lossy().to_string()).collect::<Vec<_>>(),
        "version": env!("CARGO_PKG_VERSION"),
    })
    .to_string();

    let tmp = dest.with_extension("qbk.partial");
    let out = std::io::BufWriter::new(std::fs::File::create(&tmp)?);
    let enc = EncryptWriter::new(out, passphrase)?;
    let mut z = zstd::stream::Encoder::new(enc, 3)?;
    write_entry(&mut z, "MANIFEST.json", manifest.as_bytes(), manifest.len() as u64)?;
    for f in &files {
        let p = staging.join(f);
        let size = std::fs::metadata(&p)?.len();
        write_entry(&mut z, &f.to_string_lossy().replace('\\', "/"), std::fs::File::open(&p)?, size)?;
    }
    z.write_all(&0u16.to_be_bytes())?;
    z.finish()?.finish()?;
    std::fs::rename(&tmp, dest)?;
    let bytes = std::fs::metadata(dest)?.len();
    drop(cleanup);

    let mut h = Sha256::new();
    let mut f = std::fs::File::open(dest)?;
    let mut buf = vec![0u8; 1 << 20];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    let sha = hex::encode(h.finalize());
    let rep = BackupReport {
        file: dest.display().to_string(),
        bytes,
        files: files.len(),
        facts,
        ledger_head: head,
        sha256: sha,
        seconds: (t0.elapsed().as_secs_f64() * 10.0).round() / 10.0,
    };
    store.ledger_append(actor, "store.backup", "D2->D2 ALLOW", &serde_json::to_string(&rep)?, "operations")?;
    Ok(rep)
}

struct Cleanup(PathBuf);
impl Drop for Cleanup {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
fn scopeguard(p: &Path) -> Cleanup {
    Cleanup(p.to_path_buf())
}

#[derive(Debug, Serialize)]
pub struct RestoreReport {
    pub into: String,
    pub files: usize,
    pub bytes: u64,
    pub facts: u64,
    pub ledger_head: String,
}

fn read_u<const N: usize>(r: &mut impl Read) -> anyhow::Result<[u8; N]> {
    let mut b = [0u8; N];
    r.read_exact(&mut b)?;
    Ok(b)
}

/// Restore a backup stream into `into`, which must not exist or be empty.
/// Every file is verified against its checksum before the restore is accepted.
pub fn restore(src: impl Read, into: &Path, passphrase: &str) -> anyhow::Result<RestoreReport> {
    if into.exists() {
        anyhow::ensure!(
            std::fs::read_dir(into)?.next().is_none(),
            "{} is not empty; restore into a new directory",
            into.display()
        );
    }
    let staging = into.with_extension("restoring");
    let _ = std::fs::remove_dir_all(&staging);
    std::fs::create_dir_all(&staging)?;
    let guard = scopeguard(&staging);
    let mut z = zstd::stream::Decoder::new(DecryptReader::new(src, passphrase)?)?;
    let mut manifest: Option<serde_json::Value> = None;
    let (mut files, mut bytes) = (0usize, 0u64);
    loop {
        let plen = u16::from_be_bytes(read_u::<2>(&mut z)?) as usize;
        if plen == 0 {
            break;
        }
        let mut p = vec![0u8; plen];
        z.read_exact(&mut p)?;
        let path = String::from_utf8(p)?;
        let rel = Path::new(&path);
        anyhow::ensure!(rel.components().all(|c| matches!(c, Component::Normal(_))), "backup names an unsafe path: {path}");
        let size = u64::from_be_bytes(read_u::<8>(&mut z)?);
        let mut h = Sha256::new();
        let mut data_to: Box<dyn Write> = if path == "MANIFEST.json" {
            Box::new(Vec::new())
        } else {
            let to = staging.join(rel);
            std::fs::create_dir_all(to.parent().unwrap())?;
            Box::new(std::io::BufWriter::new(std::fs::File::create(&to)?))
        };
        let mut left = size;
        let mut buf = vec![0u8; 1 << 20];
        let mut man = Vec::new();
        while left > 0 {
            let want = left.min(buf.len() as u64) as usize;
            let n = z.read(&mut buf[..want])?;
            anyhow::ensure!(n > 0, "backup ended inside {path}");
            h.update(&buf[..n]);
            if path == "MANIFEST.json" {
                man.extend_from_slice(&buf[..n]);
            } else {
                data_to.write_all(&buf[..n])?;
            }
            left -= n as u64;
        }
        data_to.flush()?;
        drop(data_to);
        let want = read_u::<32>(&mut z)?;
        anyhow::ensure!(h.finalize()[..] == want[..], "checksum mismatch in {path}");
        if path == "MANIFEST.json" {
            manifest = Some(serde_json::from_slice(&man)?);
        } else {
            files += 1;
            bytes += size;
        }
    }
    // the decrypting reader must also have reached its authenticated end
    let mut rest = Vec::new();
    z.read_to_end(&mut rest)?;
    let m = manifest.ok_or_else(|| anyhow::anyhow!("backup has no manifest"))?;
    let listed = m["files"].as_array().map(|a| a.len()).unwrap_or(0);
    anyhow::ensure!(listed == files, "backup lists {listed} files but holds {files}");
    if into.exists() {
        std::fs::remove_dir(into)?;
    }
    std::fs::rename(&staging, into)?;
    std::mem::forget(guard);
    Ok(RestoreReport {
        into: into.display().to_string(),
        files,
        bytes,
        facts: m["facts"].as_u64().unwrap_or(0),
        ledger_head: m["ledger_head"].as_str().unwrap_or("").to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encryption_round_trip_and_tamper_detection() {
        let data: Vec<u8> = (0..(CHUNK * 2 + 777)).map(|i| (i % 251) as u8).collect();
        let mut w = EncryptWriter::new(Vec::new(), "correct horse battery").unwrap();
        w.write_all(&data).unwrap();
        let file = w.finish().unwrap();
        let mut back = Vec::new();
        DecryptReader::new(&file[..], "correct horse battery").unwrap().read_to_end(&mut back).unwrap();
        assert_eq!(back, data);
        // wrong passphrase
        let mut sink = Vec::new();
        assert!(DecryptReader::new(&file[..], "wrong horse battery!").unwrap().read_to_end(&mut sink).is_err());
        // one flipped bit
        let mut bad = file.clone();
        bad[HEADER_LEN + 100] ^= 1;
        assert!(DecryptReader::new(&bad[..], "correct horse battery").unwrap().read_to_end(&mut Vec::new()).is_err());
        // truncation at a chunk boundary (final chunk dropped)
        let first = HEADER_LEN + 4 + u32::from_be_bytes(file[HEADER_LEN..HEADER_LEN + 4].try_into().unwrap()) as usize;
        assert!(DecryptReader::new(&file[..first], "correct horse battery").unwrap().read_to_end(&mut Vec::new()).is_err());
        // short passphrases are refused
        assert!(EncryptWriter::new(Vec::new(), "short").is_err());
    }
}
