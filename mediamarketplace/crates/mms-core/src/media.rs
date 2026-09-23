//! Media library: files on disk, rows in `media`, thumbnails and derived variants.

use crate::config::Config;
use crate::db::Db;
use anyhow::{anyhow, Context, Result};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Media {
    pub id: i64,
    pub uuid: String,
    pub r#type: String,
    pub original_path: String,
    pub private: i64,
    pub mime: String,
    pub bytes: i64,
    pub width: Option<i64>,
    pub height: Option<i64>,
    pub duration_ms: Option<i64>,
    pub hash_sha256: String,
    pub title: Option<String>,
    pub alt: Option<String>,
    pub caption: Option<String>,
    pub tags: Option<String>,
    pub thumbnail_path: Option<String>,
    pub folder_id: Option<i64>,
    pub status: String,
    pub created_at: String,
}

#[derive(Debug, Default, Clone)]
pub struct MediaQuery {
    pub q: String,
    pub r#type: String,
    pub folder_id: Option<i64>,
    pub page: i64,
    pub per_page: i64,
}

pub const THUMB_SIZES: [u32; 3] = [320, 640, 1280];

/// Allowed upload types by extension, with the library type each maps to.
pub fn kind_for_extension(ext: &str) -> Option<&'static str> {
    match ext.to_ascii_lowercase().as_str() {
        "jpg" | "jpeg" | "png" | "gif" | "webp" | "avif" | "svg" => Some("image"),
        "mp4" | "webm" | "mov" | "m4v" => Some("video"),
        "mp3" | "wav" | "m4a" | "ogg" | "flac" | "aac" => Some("audio"),
        "pdf" => Some("pdf"),
        _ => None,
    }
}

#[derive(Clone)]
pub struct MediaStore {
    db: Db,
    public_root: PathBuf,
    private_root: PathBuf,
    ffmpeg: String,
    max_bytes: u64,
}

impl MediaStore {
    pub fn new(db: Db, config: &Config) -> Self {
        Self {
            db,
            public_root: config.media_public_dir(),
            private_root: config.media_private_dir(),
            ffmpeg: config.media.ffmpeg_path.clone(),
            max_bytes: config.media.max_upload_mb * 1024 * 1024,
        }
    }

    pub fn max_bytes(&self) -> u64 {
        self.max_bytes
    }

    pub fn public_root(&self) -> &Path {
        &self.public_root
    }

    /// Absolute path of a stored original.
    pub fn original_path(&self, m: &Media) -> PathBuf {
        let root = if m.private == 1 {
            &self.private_root
        } else {
            &self.public_root
        };
        root.join(&m.original_path)
    }

    /// Stores an uploaded file: validates type and size, writes it under
    /// `<root>/originals/<uuid>.<ext>`, extracts what it can and inserts the row.
    /// Thumbnails are produced by `generate_thumbnails` (usually from a job).
    pub async fn store_upload(
        &self,
        filename: &str,
        data: &[u8],
        private: bool,
        uploader_id: Option<i64>,
    ) -> Result<Media> {
        anyhow::ensure!(!data.is_empty(), "the file is empty");
        anyhow::ensure!(
            data.len() as u64 <= self.max_bytes,
            "the file is larger than the {} MB limit",
            self.max_bytes / 1024 / 1024
        );
        let ext = Path::new(filename)
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let kind =
            kind_for_extension(&ext).ok_or_else(|| anyhow!("file type .{ext} is not allowed"))?;
        let sniffed = infer::get(data).map(|t| t.mime_type().to_string());
        let mime = sniffed.clone().unwrap_or_else(|| {
            mime_guess::from_ext(&ext)
                .first_or_octet_stream()
                .to_string()
        });
        // Content must agree with the extension for binary formats (svg has no magic number).
        if let Some(s) = &sniffed {
            let expected = match kind {
                "image" => "image/",
                "video" => "video/",
                "audio" => "audio/",
                _ => "application/pdf",
            };
            anyhow::ensure!(
                s.starts_with(expected)
                    || (kind == "video" && s.starts_with("audio/"))
                    || (kind == "audio" && s.starts_with("video/")),
                "the file content does not match its .{ext} extension"
            );
        }
        if ext != "svg" {
            anyhow::ensure!(
                sniffed.is_some(),
                "the file content is not a recognised {kind} format"
            );
        }
        if ext == "svg" {
            let text = std::str::from_utf8(data).context("svg must be UTF-8")?;
            let lower = text.to_ascii_lowercase();
            anyhow::ensure!(
                !lower.contains("<script")
                    && !lower.contains("javascript:")
                    && !lower.contains("onload="),
                "svg contains scripting and was refused"
            );
        }
        let uuid = uuid::Uuid::new_v4().to_string();
        let rel = format!("originals/{uuid}.{ext}");
        let root = if private {
            &self.private_root
        } else {
            &self.public_root
        };
        let abs = root.join(&rel);
        tokio::fs::create_dir_all(abs.parent().unwrap()).await?;
        tokio::fs::write(&abs, data)
            .await
            .with_context(|| format!("writing {}", abs.display()))?;
        let hash = hex(&Sha256::digest(data));
        let (w, h) = if kind == "image" && ext != "svg" {
            image_size(data)
        } else {
            (None, None)
        };
        let title = Path::new(filename)
            .file_stem()
            .and_then(|s| s.to_str())
            .map(|s| s.replace(['_', '-'], " "));
        let now = crate::now();
        let id = sqlx::query(
            "INSERT INTO media (uuid, type, original_path, private, mime, bytes, width, height, hash_sha256, title, status, uploader_id, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processing', ?, ?, ?)",
        )
        .bind(&uuid).bind(kind).bind(&rel).bind(private as i64).bind(&mime).bind(data.len() as i64).bind(w).bind(h).bind(&hash).bind(title).bind(uploader_id).bind(&now).bind(&now)
        .execute(&self.db.pool).await?.last_insert_rowid();
        self.by_id(id)
            .await?
            .ok_or_else(|| anyhow!("media row vanished"))
    }

    /// Produces thumbnails under `public/thumbs/<uuid>/<size>.jpg` and marks the item ready.
    /// Images are resized natively; videos use ffmpeg when present; audio and PDF get no
    /// thumbnail (the UI shows a type icon). Never fails the item for a missing ffmpeg.
    pub async fn generate_thumbnails(&self, id: i64) -> Result<()> {
        let m = self
            .by_id(id)
            .await?
            .ok_or_else(|| anyhow!("media {id} not found"))?;
        let thumb_dir = self.public_root.join("thumbs").join(&m.uuid);
        tokio::fs::create_dir_all(&thumb_dir).await?;
        let mut thumb: Option<String> = None;
        let mut duration: Option<i64> = m.duration_ms;
        match m.r#type.as_str() {
            "image" if !m.original_path.ends_with(".svg") => {
                let data = tokio::fs::read(self.original_path(&m)).await?;
                let dir = thumb_dir.clone();
                let uuid = m.uuid.clone();
                let made = tokio::task::spawn_blocking(move || -> Result<Option<String>> {
                    let img = image::load_from_memory(&data).context("decoding image")?;
                    let mut first = None;
                    for size in THUMB_SIZES {
                        let resized = img.thumbnail(size, size);
                        let path = dir.join(format!("{size}.jpg"));
                        resized
                            .to_rgb8()
                            .save_with_format(&path, image::ImageFormat::Jpeg)
                            .context("writing thumbnail")?;
                        first.get_or_insert(format!("thumbs/{uuid}/{size}.jpg"));
                    }
                    Ok(first)
                })
                .await??;
                thumb = made;
            }
            "video" => {
                if let Some(ffmpeg) = crate::health::binary(&self.ffmpeg) {
                    // One PNG frame from ffmpeg (every build can encode PNG), then the same JPEG sizes as images.
                    let src = self.original_path(&m);
                    let frame = thumb_dir.join("frame.png");
                    let status = tokio::process::Command::new(&ffmpeg)
                        .args(["-y", "-loglevel", "error", "-ss", "00:00:03", "-i"])
                        .arg(&src)
                        .args(["-frames:v", "1", "-vf", "scale=1280:-2"])
                        .arg(&frame)
                        .status()
                        .await;
                    let mut ok = matches!(status, Ok(s) if s.success()) && frame.exists();
                    if !ok {
                        // Very short clips have no frame at 3 s; take the first one instead.
                        let status = tokio::process::Command::new(&ffmpeg)
                            .args(["-y", "-loglevel", "error", "-i"])
                            .arg(&src)
                            .args(["-frames:v", "1", "-vf", "scale=1280:-2"])
                            .arg(&frame)
                            .status()
                            .await;
                        ok = matches!(status, Ok(s) if s.success()) && frame.exists();
                    }
                    if ok {
                        let data = tokio::fs::read(&frame).await?;
                        let dir = thumb_dir.clone();
                        let uuid = m.uuid.clone();
                        thumb = tokio::task::spawn_blocking(move || -> Result<Option<String>> {
                            let img =
                                image::load_from_memory(&data).context("decoding video frame")?;
                            let mut first = None;
                            for size in THUMB_SIZES {
                                let path = dir.join(format!("{size}.jpg"));
                                img.thumbnail(size, size)
                                    .to_rgb8()
                                    .save_with_format(&path, image::ImageFormat::Jpeg)?;
                                first.get_or_insert(format!("thumbs/{uuid}/{size}.jpg"));
                            }
                            Ok(first)
                        })
                        .await??;
                        let _ = tokio::fs::remove_file(&frame).await;
                    }
                    if duration.is_none() {
                        duration = probe_duration_ms(&ffmpeg, &src).await;
                    }
                }
            }
            _ => {}
        }
        sqlx::query("UPDATE media SET thumbnail_path = COALESCE(?, thumbnail_path), duration_ms = COALESCE(?, duration_ms), status = 'ready', updated_at = ? WHERE id = ?")
            .bind(thumb).bind(duration).bind(crate::now()).bind(id)
            .execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn by_id(&self, id: i64) -> Result<Option<Media>> {
        Ok(
            sqlx::query_as::<_, Media>(&format!("{SELECT} WHERE id = ?"))
                .bind(id)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn by_uuid(&self, uuid: &str) -> Result<Option<Media>> {
        Ok(
            sqlx::query_as::<_, Media>(&format!("{SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn list(&self, q: &MediaQuery) -> Result<(Vec<Media>, i64)> {
        let per = q.per_page.clamp(1, 200);
        let page = q.page.max(1);
        let like = format!("%{}%", q.q.trim());
        let type_filter = if q.r#type.is_empty() {
            "%".to_string()
        } else {
            q.r#type.clone()
        };
        let total: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM media WHERE type LIKE ? AND (? = '' OR title LIKE ? OR alt LIKE ? OR caption LIKE ? OR tags LIKE ?) AND (? IS NULL OR folder_id = ?)")
            .bind(&type_filter).bind(q.q.trim()).bind(&like).bind(&like).bind(&like).bind(&like).bind(q.folder_id).bind(q.folder_id)
            .fetch_one(&self.db.pool).await?;
        let rows = sqlx::query_as::<_, Media>(&format!("{SELECT} WHERE type LIKE ? AND (? = '' OR title LIKE ? OR alt LIKE ? OR caption LIKE ? OR tags LIKE ?) AND (? IS NULL OR folder_id = ?) ORDER BY id DESC LIMIT ? OFFSET ?"))
            .bind(&type_filter).bind(q.q.trim()).bind(&like).bind(&like).bind(&like).bind(&like).bind(q.folder_id).bind(q.folder_id).bind(per).bind((page - 1) * per)
            .fetch_all(&self.db.pool).await?;
        Ok((rows, total))
    }

    pub async fn update_meta(
        &self,
        id: i64,
        title: &str,
        alt: &str,
        caption: &str,
        tags: &str,
    ) -> Result<()> {
        sqlx::query("UPDATE media SET title = ?, alt = ?, caption = ?, tags = ?, updated_at = ? WHERE id = ?")
            .bind(title.trim()).bind(alt.trim()).bind(caption.trim()).bind(tags.trim()).bind(crate::now()).bind(id)
            .execute(&self.db.pool).await?;
        Ok(())
    }

    /// Deletes the row and every file that belongs to it.
    pub async fn delete(&self, id: i64) -> Result<()> {
        let Some(m) = self.by_id(id).await? else {
            return Ok(());
        };
        let _ = tokio::fs::remove_file(self.original_path(&m)).await;
        let _ = tokio::fs::remove_dir_all(self.public_root.join("thumbs").join(&m.uuid)).await;
        sqlx::query("DELETE FROM media WHERE id = ?")
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        Ok(())
    }

    pub async fn counts_by_type(&self) -> Result<Vec<(String, i64)>> {
        Ok(sqlx::query_as::<_, (String, i64)>(
            "SELECT type, COUNT(*) FROM media GROUP BY type ORDER BY type",
        )
        .fetch_all(&self.db.pool)
        .await?)
    }
}

const SELECT: &str = "SELECT id, uuid, type, original_path, private, mime, bytes, width, height, duration_ms, hash_sha256, title, alt, caption, tags, thumbnail_path, folder_id, status, created_at FROM media";

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn image_size(data: &[u8]) -> (Option<i64>, Option<i64>) {
    match image::load_from_memory(data) {
        Ok(img) => (Some(img.width() as i64), Some(img.height() as i64)),
        Err(_) => (None, None),
    }
}

async fn probe_duration_ms(ffmpeg: &str, src: &Path) -> Option<i64> {
    // ffprobe usually sits next to ffmpeg; fall back to parsing ffmpeg's own banner.
    let ffprobe = Path::new(ffmpeg).with_file_name("ffprobe");
    if ffprobe.exists() {
        let out = tokio::process::Command::new(ffprobe)
            .args([
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
            ])
            .arg(src)
            .output()
            .await
            .ok()?;
        let s = String::from_utf8_lossy(&out.stdout);
        return s.trim().parse::<f64>().ok().map(|d| (d * 1000.0) as i64);
    }
    let out = tokio::process::Command::new(ffmpeg)
        .arg("-i")
        .arg(src)
        .output()
        .await
        .ok()?;
    let text = String::from_utf8_lossy(&out.stderr);
    let idx = text.find("Duration: ")?;
    let stamp = &text[idx + 10..idx + 21];
    let parts: Vec<f64> = stamp.split(':').filter_map(|p| p.parse().ok()).collect();
    if parts.len() == 3 {
        Some(((parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]) * 1000.0) as i64)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn png(w: u32, h: u32) -> Vec<u8> {
        let img = image::RgbImage::from_fn(w, h, |x, _| image::Rgb([(x % 255) as u8, 80, 120]));
        let mut buf = std::io::Cursor::new(Vec::new());
        image::DynamicImage::ImageRgb8(img)
            .write_to(&mut buf, image::ImageFormat::Png)
            .unwrap();
        buf.into_inner()
    }

    async fn store() -> (MediaStore, PathBuf) {
        let tmp = std::env::temp_dir().join(format!("mms-media-{}", uuid::Uuid::new_v4()));
        let config = Config::generate(tmp.clone(), "127.0.0.1:0", "http://localhost/mms");
        let db = Db::memory().await.unwrap();
        (MediaStore::new(db, &config), tmp)
    }

    #[tokio::test]
    async fn upload_validate_thumbnail_search_delete() {
        let (store, tmp) = store().await;
        let m = store
            .store_upload("Studio_Lighting-01.png", &png(1600, 900), false, None)
            .await
            .unwrap();
        assert_eq!(m.r#type, "image");
        assert_eq!(m.mime, "image/png");
        assert_eq!((m.width, m.height), (Some(1600), Some(900)));
        assert_eq!(m.title.as_deref(), Some("Studio Lighting 01"));
        assert_eq!(m.status, "processing");
        assert!(store.original_path(&m).exists());

        store.generate_thumbnails(m.id).await.unwrap();
        let m = store.by_id(m.id).await.unwrap().unwrap();
        assert_eq!(m.status, "ready");
        assert_eq!(
            m.thumbnail_path.as_deref(),
            Some(format!("thumbs/{}/320.jpg", m.uuid).as_str())
        );
        for size in THUMB_SIZES {
            assert!(store
                .public_root()
                .join("thumbs")
                .join(&m.uuid)
                .join(format!("{size}.jpg"))
                .exists());
        }

        assert!(
            store
                .store_upload("evil.exe", b"MZ....", false, None)
                .await
                .is_err(),
            "extension allowlist"
        );
        assert!(
            store
                .store_upload("fake.jpg", b"not really a jpeg at all", false, None)
                .await
                .is_err(),
            "content sniffing"
        );
        assert!(
            store
                .store_upload("logo.svg", b"<svg onload=\"alert(1)\"></svg>", false, None)
                .await
                .is_err(),
            "svg scripting"
        );
        assert!(store
            .store_upload("empty.png", b"", false, None)
            .await
            .is_err());

        let private = store
            .store_upload("secret.png", &png(10, 10), true, None)
            .await
            .unwrap();
        assert!(store
            .original_path(&private)
            .starts_with(tmp.join("media").join("private")));

        let (rows, total) = store
            .list(&MediaQuery {
                q: "lighting".into(),
                per_page: 20,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!((rows.len(), total), (1, 1));
        let (_, total) = store
            .list(&MediaQuery {
                r#type: "video".into(),
                per_page: 20,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!(total, 0);

        store
            .update_meta(m.id, "Lighting", "A lamp", "", "studio, light")
            .await
            .unwrap();
        let (rows, _) = store
            .list(&MediaQuery {
                q: "lamp".into(),
                per_page: 20,
                page: 1,
                ..Default::default()
            })
            .await
            .unwrap();
        assert_eq!(rows.len(), 1);

        store.delete(m.id).await.unwrap();
        assert!(store.by_id(m.id).await.unwrap().is_none());
        assert!(!store.public_root().join("thumbs").join(&m.uuid).exists());
        std::fs::remove_dir_all(tmp).ok();
    }
}
