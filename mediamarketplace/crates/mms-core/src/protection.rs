//! Forensic watermarking without external dependencies.
//!
//! * A 5x7 bitmap font stamps visible text (the viewer's email) into image derivatives.
//! * A 32-bit session code is hidden in the least significant bits of the blue channel,
//!   repeated across the image with a checksum, and recovered by `decode_lsb`.
//! * The same code is drawn as a low-contrast box grid for video (through ffmpeg) and
//!   recovered from a full-frame screenshot by `decode_grid`.

use crate::db::Db;
use anyhow::{bail, Context, Result};
use image::{DynamicImage, GenericImage, GenericImageView, Rgba};
use serde::Serialize;

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct MarkSession {
    pub id: i64,
    pub code: i64,
    pub uuid: String,
    pub user_id: Option<i64>,
    pub media_id: Option<i64>,
    pub product_id: Option<i64>,
    pub level: i64,
    pub kind: String,
    pub ip: String,
    pub user_agent: String,
    pub created_at: String,
}

// ----- 5x7 font: uppercase letters, digits and a few symbols -----

fn glyph(c: char) -> [u8; 7] {
    match c.to_ascii_uppercase() {
        'A' => [0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
        'B' => [0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E],
        'C' => [0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E],
        'D' => [0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E],
        'E' => [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F],
        'F' => [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10],
        'G' => [0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F],
        'H' => [0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
        'I' => [0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E],
        'J' => [0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C],
        'K' => [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11],
        'L' => [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F],
        'M' => [0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11],
        'N' => [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
        'O' => [0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
        'P' => [0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10],
        'Q' => [0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D],
        'R' => [0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11],
        'S' => [0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E],
        'T' => [0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
        'U' => [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E],
        'V' => [0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04],
        'W' => [0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A],
        'X' => [0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11],
        'Y' => [0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04],
        'Z' => [0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F],
        '0' => [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E],
        '1' => [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
        '2' => [0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F],
        '3' => [0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E],
        '4' => [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02],
        '5' => [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
        '6' => [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E],
        '7' => [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
        '8' => [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E],
        '9' => [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
        '@' => [0x0E, 0x11, 0x17, 0x15, 0x17, 0x10, 0x0E],
        '.' => [0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C],
        '-' => [0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00],
        '_' => [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x1F],
        ':' => [0x00, 0x0C, 0x0C, 0x00, 0x0C, 0x0C, 0x00],
        '/' => [0x01, 0x01, 0x02, 0x04, 0x08, 0x10, 0x10],
        '+' => [0x00, 0x04, 0x04, 0x1F, 0x04, 0x04, 0x00],
        ' ' => [0; 7],
        _ => [0x00, 0x00, 0x0A, 0x00, 0x00, 0x0A, 0x00],
    }
}

/// Position of the visible stamp.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Corner {
    TopLeft,
    TopRight,
    BottomLeft,
    BottomRight,
    Center,
}

impl Corner {
    pub fn parse(s: &str) -> Self {
        match s {
            "top_left" => Corner::TopLeft,
            "top_right" => Corner::TopRight,
            "bottom_left" => Corner::BottomLeft,
            "center" => Corner::Center,
            _ => Corner::BottomRight,
        }
    }
}

/// Burns `text` into the image with a translucent light glyph over a dark shadow so it
/// reads on any background. Scale grows with the image so it stays legible.
pub fn stamp_text(img: &mut DynamicImage, text: &str, corner: Corner, opacity: f32) {
    let (w, h) = img.dimensions();
    let scale = (w / 320).clamp(1, 6);
    let text: String = text.chars().take(48).collect();
    let tw = text.len() as u32 * 6 * scale;
    let th = 7 * scale;
    let pad = 8 * scale;
    let (x0, y0) = match corner {
        Corner::TopLeft => (pad, pad),
        Corner::TopRight => (w.saturating_sub(tw + pad), pad),
        Corner::BottomLeft => (pad, h.saturating_sub(th + pad)),
        Corner::BottomRight => (w.saturating_sub(tw + pad), h.saturating_sub(th + pad)),
        Corner::Center => (w.saturating_sub(tw) / 2, h.saturating_sub(th) / 2),
    };
    let a = opacity.clamp(0.05, 1.0);
    let blend = |img: &mut DynamicImage, x: u32, y: u32, light: bool| {
        if x >= w || y >= h {
            return;
        }
        let p = img.get_pixel(x, y);
        let target: f32 = if light { 255.0 } else { 0.0 };
        let mix = |c: u8| ((c as f32) * (1.0 - a) + target * a).round() as u8;
        img.put_pixel(x, y, Rgba([mix(p[0]), mix(p[1]), mix(p[2]), p[3]]));
    };
    for (i, c) in text.chars().enumerate() {
        let g = glyph(c);
        for (row, bits) in g.iter().enumerate() {
            for col in 0..5u32 {
                if bits & (0x10 >> col) == 0 {
                    continue;
                }
                let gx = x0 + (i as u32 * 6 + col) * scale;
                let gy = y0 + row as u32 * scale;
                for dy in 0..scale {
                    for dx in 0..scale {
                        blend(img, gx + dx + scale.max(1), gy + dy + scale.max(1), false);
                    }
                }
                for dy in 0..scale {
                    for dx in 0..scale {
                        blend(img, gx + dx, gy + dy, true);
                    }
                }
            }
        }
    }
}

// ----- invisible LSB mark -----

/// 32-bit payload plus an 8-bit checksum, repeated for the whole image.
fn frame(code: u32) -> [u8; 40] {
    let mut bits = [0u8; 40];
    let check = code
        .to_be_bytes()
        .iter()
        .fold(0x5Au8, |a, b| a.wrapping_mul(31).wrapping_add(*b));
    let v = ((code as u64) << 8) | check as u64;
    for (i, b) in bits.iter_mut().enumerate() {
        *b = ((v >> (39 - i)) & 1) as u8;
    }
    bits
}

/// Hides the code in the blue channel's least significant bit, row-major, repeated.
/// Save the result losslessly (PNG); JPEG re-encoding destroys least significant bits.
pub fn embed_lsb(img: &mut DynamicImage, code: u32) {
    let (w, h) = img.dimensions();
    let bits = frame(code);
    let mut i = 0usize;
    for y in 0..h {
        for x in 0..w {
            let mut p = img.get_pixel(x, y);
            p[2] = (p[2] & 0xFE) | bits[i % 40];
            img.put_pixel(x, y, p);
            i += 1;
        }
    }
}

/// Recovers the code by majority vote over every repetition; `None` when the checksum
/// disagrees (no mark, or the image was re-encoded).
pub fn decode_lsb(img: &DynamicImage) -> Option<u32> {
    let (w, h) = img.dimensions();
    if (w as u64) * (h as u64) < 40 {
        return None;
    }
    let mut votes = [0i64; 40];
    let mut i = 0usize;
    for y in 0..h {
        for x in 0..w {
            let b = img.get_pixel(x, y)[2] & 1;
            votes[i % 40] += if b == 1 { 1 } else { -1 };
            i += 1;
        }
    }
    let mut v: u64 = 0;
    for vote in votes {
        v = (v << 1) | (vote > 0) as u64;
    }
    let code = (v >> 8) as u32;
    let check = (v & 0xFF) as u8;
    let expect = code
        .to_be_bytes()
        .iter()
        .fold(0x5Au8, |a, b| a.wrapping_mul(31).wrapping_add(*b));
    (check == expect && code != 0).then_some(code)
}

// ----- low-contrast grid for video frames -----

/// Geometry of the 8x5 grid (32-bit code plus an 8-bit checksum) in the bottom-right
/// corner, relative to the frame width so it survives scaling: cell = width/64.
pub fn grid_cells(w: u32, h: u32) -> Vec<(u32, u32, u32)> {
    let cell = (w / 64).max(4);
    let margin = cell;
    let x0 = w.saturating_sub(margin + 8 * cell);
    let y0 = h.saturating_sub(margin + 5 * cell);
    (0..40u32)
        .map(|i| (x0 + (i % 8) * cell, y0 + (i / 8) * cell, cell))
        .collect()
}

/// The marked square inside a cell: the inner half, leaving an unmarked ring around
/// it that the decoder uses as the local background reference.
fn inner(x: u32, y: u32, c: u32) -> (u32, u32, u32) {
    let q = (c / 4).max(1);
    (x + q, y + q, (c - 2 * q).max(1))
}

/// ffmpeg `drawbox` filter chain that paints the set bits of the code as dark boxes.
pub fn ffmpeg_grid_filter(w: u32, h: u32, code: u32, opacity: f32) -> String {
    let a = opacity.clamp(0.05, 0.6);
    let bits = frame(code);
    let mut parts = Vec::new();
    for (i, (x, y, c)) in grid_cells(w, h).into_iter().enumerate() {
        if bits[i] == 1 {
            let (ix, iy, ic) = inner(x, y, c);
            parts.push(format!(
                "drawbox=x={ix}:y={iy}:w={ic}:h={ic}:color=black@{a:.2}:t=fill"
            ));
        }
    }
    if parts.is_empty() {
        "null".to_string()
    } else {
        parts.join(",")
    }
}

/// Paints the same grid onto a still image (posters, screenshots for tests).
pub fn stamp_grid(img: &mut DynamicImage, code: u32, opacity: f32) {
    let (w, h) = img.dimensions();
    let a = opacity.clamp(0.05, 0.6);
    let bits = frame(code);
    for (i, (x, y, c)) in grid_cells(w, h).into_iter().enumerate() {
        if bits[i] == 0 {
            continue;
        }
        let (ix, iy, ic) = inner(x, y, c);
        for yy in iy..(iy + ic).min(h) {
            for xx in ix..(ix + ic).min(w) {
                let p = img.get_pixel(xx, yy);
                let mix = |v: u8| ((v as f32) * (1.0 - a)).round() as u8;
                img.put_pixel(xx, yy, Rgba([mix(p[0]), mix(p[1]), mix(p[2]), p[3]]));
            }
        }
    }
}

/// Reads the grid from a full-frame screenshot: the inner square of each cell is
/// compared with the unmarked ring around it; a clearly darker centre is a set bit.
/// Returns `None` unless the checksum agrees, so clean frames never identify anyone.
pub fn decode_grid(img: &DynamicImage) -> Option<u32> {
    let (w, h) = img.dimensions();
    let luma = |x: u32, y: u32| -> f32 {
        let p = img.get_pixel(x.min(w - 1), y.min(h - 1));
        0.299 * p[0] as f32 + 0.587 * p[1] as f32 + 0.114 * p[2] as f32
    };
    let mut v: u64 = 0;
    for (x, y, c) in grid_cells(w, h) {
        v <<= 1;
        let (ix, iy, ic) = inner(x, y, c);
        let (mut si, mut ni, mut sr, mut nr) = (0.0f32, 0.0f32, 0.0f32, 0.0f32);
        for yy in y..(y + c).min(h) {
            for xx in x..(x + c).min(w) {
                let in_inner = xx > ix && xx + 1 < ix + ic && yy > iy && yy + 1 < iy + ic;
                let in_ring =
                    xx < ix.saturating_sub(0) || xx >= ix + ic || yy < iy || yy >= iy + ic;
                if in_inner {
                    si += luma(xx, yy);
                    ni += 1.0;
                } else if in_ring {
                    sr += luma(xx, yy);
                    nr += 1.0;
                }
            }
        }
        if ni == 0.0 || nr == 0.0 {
            continue;
        }
        let (mi, mr) = (si / ni, sr / nr);
        if mi < mr * 0.86 - 1.0 {
            v |= 1;
        }
    }
    let code = (v >> 8) as u32;
    let check = (v & 0xFF) as u8;
    let expect = code
        .to_be_bytes()
        .iter()
        .fold(0x5Au8, |a, b| a.wrapping_mul(31).wrapping_add(*b));
    (check == expect && code != 0).then_some(code)
}

// ----- sessions -----

#[derive(Clone)]
pub struct Protection {
    db: Db,
}

impl Protection {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    /// Opens a mark session and returns it with a fresh 32-bit code (never zero).
    #[allow(clippy::too_many_arguments)]
    pub async fn open_session(
        &self,
        user_id: Option<i64>,
        media_id: Option<i64>,
        product_id: Option<i64>,
        level: i64,
        kind: &str,
        ip: &str,
        ua: &str,
    ) -> Result<MarkSession> {
        use rand::Rng;
        let uuid = uuid::Uuid::new_v4().to_string();
        for _ in 0..8 {
            let code: u32 = rand::thread_rng().gen_range(1..=u32::MAX);
            let r = sqlx::query("INSERT OR IGNORE INTO mark_sessions (code, uuid, user_id, media_id, product_id, level, kind, ip, user_agent, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
                .bind(code as i64).bind(&uuid).bind(user_id).bind(media_id).bind(product_id).bind(level).bind(kind).bind(ip).bind(ua).bind(crate::now())
                .execute(&self.db.pool).await?;
            if r.rows_affected() == 1 {
                return self.by_uuid(&uuid).await?.context("session just created");
            }
        }
        bail!("could not allocate a session code")
    }

    /// Reuses the session a user already has for a media item so repeat views share one code.
    #[allow(clippy::too_many_arguments)]
    pub async fn session_for(
        &self,
        user_id: i64,
        media_id: i64,
        product_id: Option<i64>,
        level: i64,
        kind: &str,
        ip: &str,
        ua: &str,
    ) -> Result<MarkSession> {
        if let Some(s) = sqlx::query_as::<_, MarkSession>("SELECT id, code, uuid, user_id, media_id, product_id, level, kind, ip, user_agent, created_at FROM mark_sessions WHERE user_id = ? AND media_id = ? AND kind = ? ORDER BY id DESC LIMIT 1")
            .bind(user_id).bind(media_id).bind(kind).fetch_optional(&self.db.pool).await? {
            return Ok(s);
        }
        self.open_session(
            Some(user_id),
            Some(media_id),
            product_id,
            level,
            kind,
            ip,
            ua,
        )
        .await
    }

    pub async fn by_uuid(&self, uuid: &str) -> Result<Option<MarkSession>> {
        Ok(sqlx::query_as::<_, MarkSession>("SELECT id, code, uuid, user_id, media_id, product_id, level, kind, ip, user_agent, created_at FROM mark_sessions WHERE uuid = ?").bind(uuid).fetch_optional(&self.db.pool).await?)
    }

    pub async fn by_code(&self, code: u32) -> Result<Option<MarkSession>> {
        Ok(sqlx::query_as::<_, MarkSession>("SELECT id, code, uuid, user_id, media_id, product_id, level, kind, ip, user_agent, created_at FROM mark_sessions WHERE code = ?").bind(code as i64).fetch_optional(&self.db.pool).await?)
    }

    pub async fn recent(&self, limit: i64) -> Result<Vec<MarkSession>> {
        Ok(sqlx::query_as::<_, MarkSession>("SELECT id, code, uuid, user_id, media_id, product_id, level, kind, ip, user_agent, created_at FROM mark_sessions ORDER BY id DESC LIMIT ?").bind(limit).fetch_all(&self.db.pool).await?)
    }

    /// Identifies a leaked file: LSB first (lossless copies), then the grid (screenshots).
    pub async fn identify(&self, bytes: &[u8]) -> Result<Option<(MarkSession, &'static str)>> {
        let img = image::load_from_memory(bytes).context("not an image")?;
        if let Some(code) = decode_lsb(&img) {
            if let Some(s) = self.by_code(code).await? {
                return Ok(Some((s, "invisible mark")));
            }
        }
        if let Some(code) = decode_grid(&img) {
            if let Some(s) = self.by_code(code).await? {
                return Ok(Some((s, "frame grid")));
            }
        }
        Ok(None)
    }

    /// Deletes sessions older than the retention period. Returns the number removed.
    pub async fn prune(&self, months: i64) -> Result<u64> {
        let cutoff = crate::commerce::add_days(&crate::now(), -(months.max(1) * 30));
        Ok(
            sqlx::query("DELETE FROM mark_sessions WHERE created_at < ?")
                .bind(cutoff)
                .execute(&self.db.pool)
                .await?
                .rows_affected(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn photo(w: u32, h: u32) -> DynamicImage {
        let mut img = image::RgbaImage::new(w, h);
        for (x, y, p) in img.enumerate_pixels_mut() {
            // Smooth gradients with a soft diagonal band, like a real frame.
            let band = (((x + y) as f32 / 40.0).sin() * 30.0) as i32;
            let r = (x * 200 / w) as i32 + 30 + band;
            let g = (y * 200 / h) as i32 + 30;
            let b = 120 + band;
            *p = Rgba([
                r.clamp(0, 255) as u8,
                g.clamp(0, 255) as u8,
                b.clamp(0, 255) as u8,
                255,
            ]);
        }
        DynamicImage::ImageRgba8(img)
    }

    #[test]
    fn lsb_round_trip_survives_png_and_is_deterministic() {
        let mut img = photo(300, 200);
        embed_lsb(&mut img, 0xDEADBEEF);
        assert_eq!(decode_lsb(&img), Some(0xDEADBEEF));
        let mut buf = std::io::Cursor::new(Vec::new());
        img.write_to(&mut buf, image::ImageFormat::Png).unwrap();
        let back = image::load_from_memory(buf.get_ref()).unwrap();
        assert_eq!(decode_lsb(&back), Some(0xDEADBEEF));
        assert_eq!(
            decode_lsb(&photo(300, 200)),
            None,
            "unmarked images decode to nothing"
        );
        let mut a = photo(64, 64);
        let mut b = photo(64, 64);
        embed_lsb(&mut a, 42);
        embed_lsb(&mut b, 42);
        assert_eq!(a.as_bytes(), b.as_bytes());
    }

    #[test]
    fn visible_stamp_changes_pixels_only_where_text_is() {
        let mut img = photo(640, 360);
        let before = img.clone();
        stamp_text(&mut img, "ada@example.com", Corner::BottomRight, 0.5);
        let changed = img
            .as_bytes()
            .iter()
            .zip(before.as_bytes())
            .filter(|(a, b)| a != b)
            .count();
        assert!(changed > 500 && changed < 640 * 360 * 4 / 4, "{changed}");
        // Nothing touched the top-left corner.
        assert_eq!(img.get_pixel(10, 10), before.get_pixel(10, 10));
    }

    #[test]
    fn grid_survives_scaling_and_jpeg() {
        let mut img = photo(1280, 720);
        let code = 0xA5C3_0F71;
        stamp_grid(&mut img, code, 0.35);
        assert_eq!(decode_grid(&img), Some(code));
        let small = img.resize_exact(640, 360, image::imageops::FilterType::Triangle);
        assert_eq!(decode_grid(&small), Some(code), "scaled screenshot");
        let mut buf = std::io::Cursor::new(Vec::new());
        image::DynamicImage::ImageRgb8(small.to_rgb8())
            .write_to(&mut buf, image::ImageFormat::Jpeg)
            .unwrap();
        let jpg = image::load_from_memory(buf.get_ref()).unwrap();
        assert_eq!(decode_grid(&jpg), Some(code), "jpeg screenshot");
        assert_eq!(decode_grid(&photo(1280, 720)), None, "clean frame");
        let f = ffmpeg_grid_filter(1280, 720, 0x8000_0001, 0.3);
        let expected = frame(0x8000_0001).iter().filter(|b| **b == 1).count();
        assert!(f.starts_with("drawbox=x=") && f.matches("drawbox").count() == expected);
    }

    #[tokio::test]
    async fn sessions_identify_leaks() {
        let db = Db::memory().await.unwrap();
        let p = Protection::new(db);
        let s = p
            .open_session(None, None, None, 2, "image", "1.2.3.4", "UA")
            .await
            .unwrap();
        assert!(s.code > 0);
        let mut img = photo(400, 300);
        embed_lsb(&mut img, s.code as u32);
        let mut buf = std::io::Cursor::new(Vec::new());
        img.write_to(&mut buf, image::ImageFormat::Png).unwrap();
        let (found, how) = p.identify(buf.get_ref()).await.unwrap().unwrap();
        assert_eq!((found.uuid, how), (s.uuid.clone(), "invisible mark"));
        let mut frame = photo(1280, 720);
        stamp_grid(&mut frame, s.code as u32, 0.35);
        let mut buf = std::io::Cursor::new(Vec::new());
        image::DynamicImage::ImageRgb8(frame.to_rgb8())
            .write_to(&mut buf, image::ImageFormat::Jpeg)
            .unwrap();
        let (found, how) = p.identify(buf.get_ref()).await.unwrap().unwrap();
        assert_eq!((found.uuid, how), (s.uuid, "frame grid"));
        let mut clean = std::io::Cursor::new(Vec::new());
        photo(50, 50)
            .write_to(&mut clean, image::ImageFormat::Png)
            .unwrap();
        assert!(p.identify(clean.get_ref()).await.unwrap().is_none());
    }
}
