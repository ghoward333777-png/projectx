//! Backups: a consistent SQLite snapshot plus the media directory and config, as
//! one gzip-compressed tar archive. Restoring is unpacking into a data directory.

use anyhow::{Context, Result};
use std::path::Path;

/// Writes `mms-backup-<timestamp>.tar.gz` into `out_dir` and returns its path.
pub async fn create(
    pool: &sqlx::SqlitePool,
    data_dir: &Path,
    out_dir: &Path,
) -> Result<std::path::PathBuf> {
    tokio::fs::create_dir_all(out_dir).await?;
    let stamp = crate::now()
        .replace([':', '-'], "")
        .replace('T', "-")
        .trim_end_matches('Z')
        .to_string();
    let snapshot = out_dir.join(format!(".mms-snapshot-{stamp}.sqlite"));
    let snap_str = snapshot.to_string_lossy().replace('\'', "''");
    // A consistent copy: VACUUM INTO for file databases; in-memory databases (tests)
    // produce no snapshot and the archive simply carries no database.
    let _ = sqlx::query(&format!("VACUUM INTO '{snap_str}'"))
        .execute(pool)
        .await;
    if !snapshot.exists() {
        let db_file = data_dir.join("mms.sqlite");
        if db_file.is_file() {
            let _ = sqlx::query("PRAGMA wal_checkpoint(TRUNCATE)")
                .execute(pool)
                .await;
            tokio::fs::copy(&db_file, &snapshot)
                .await
                .context("database copy")?;
        }
    }
    let archive = out_dir.join(format!("mms-backup-{stamp}.tar.gz"));
    let data = data_dir.to_path_buf();
    let snap = snapshot.clone();
    let out = archive.clone();
    tokio::task::spawn_blocking(move || -> Result<()> {
        let f = std::fs::File::create(&out)?;
        let enc = flate2::write::GzEncoder::new(f, flate2::Compression::default());
        let mut tar = tar::Builder::new(enc);
        if snap.is_file() {
            tar.append_path_with_name(&snap, "mms.sqlite")?;
        }
        for name in ["mms.toml", "runtime.json"] {
            let p = data.join(name);
            if p.is_file() {
                tar.append_path_with_name(&p, name)?;
            }
        }
        let media = data.join("media");
        if media.is_dir() {
            tar.append_dir_all("media", &media)?;
        }
        for extra in ["evidence", "backups-notes"] {
            let p = data.join(extra);
            if p.is_dir() {
                tar.append_dir_all(extra, &p)?;
            }
        }
        tar.into_inner()?.finish()?;
        Ok(())
    })
    .await??;
    let _ = tokio::fs::remove_file(&snapshot).await;
    Ok(archive)
}

/// Lists archives in `out_dir`, newest first: (file name, bytes).
pub async fn list(out_dir: &Path) -> Result<Vec<(String, u64)>> {
    let mut out = Vec::new();
    if let Ok(mut rd) = tokio::fs::read_dir(out_dir).await {
        while let Some(e) = rd.next_entry().await? {
            let name = e.file_name().to_string_lossy().to_string();
            if name.starts_with("mms-backup-") && name.ends_with(".tar.gz") {
                out.push((name, e.metadata().await?.len()));
            }
        }
    }
    out.sort_by(|a, b| b.0.cmp(&a.0));
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn archive_contains_database_and_media() {
        let dir = std::env::temp_dir().join(format!("mms-bk-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(dir.join("media/public")).unwrap();
        std::fs::write(dir.join("media/public/a.txt"), b"hello").unwrap();
        std::fs::write(dir.join("mms.toml"), b"[server]\n").unwrap();
        let db = crate::db::Db::connect(&format!(
            "sqlite://{}?mode=rwc",
            dir.join("mms.sqlite").display()
        ))
        .await
        .unwrap();
        db.migrate().await.unwrap();
        let archive = create(&db.pool, &dir, &dir.join("backups")).await.unwrap();
        assert!(archive.exists());
        let f = std::fs::File::open(&archive).unwrap();
        let mut ar = tar::Archive::new(flate2::read::GzDecoder::new(f));
        let names: Vec<String> = ar
            .entries()
            .unwrap()
            .map(|e| e.unwrap().path().unwrap().to_string_lossy().to_string())
            .collect();
        assert!(
            names.contains(&"mms.sqlite".to_string())
                && names.contains(&"mms.toml".to_string())
                && names.iter().any(|n| n.ends_with("a.txt")),
            "{names:?}"
        );
        assert_eq!(list(&dir.join("backups")).await.unwrap().len(), 1);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
