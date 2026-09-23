//! Copyright protection: scan services (link mode and API mode), violations,
//! evidence, DMCA notices and takedown tracking.

use crate::db::Db;
use anyhow::{bail, Result};
use serde::Serialize;
use sha2::{Digest, Sha256};

/// A service the store can use. `api` services take a key under settings;
/// link-mode services open a prepared search for a media file's public URL.
#[derive(Debug, Clone, Serialize)]
pub struct Service {
    pub slug: &'static str,
    pub name: &'static str,
    pub mode: &'static str,
    pub setting: &'static str,
    pub description: &'static str,
}

pub const SERVICES: &[Service] = &[
    Service {
        slug: "google_images",
        name: "Google reverse image search",
        mode: "link",
        setting: "",
        description: "Opens Google Lens for the image's public URL.",
    },
    Service {
        slug: "bing_visual",
        name: "Bing visual search",
        mode: "link",
        setting: "",
        description: "Opens Bing visual search for the image's public URL.",
    },
    Service {
        slug: "yandex_images",
        name: "Yandex images",
        mode: "link",
        setting: "",
        description: "Opens Yandex reverse image search.",
    },
    Service {
        slug: "tineye",
        name: "TinEye",
        mode: "link",
        setting: "",
        description: "Opens TinEye for the image's public URL.",
    },
    Service {
        slug: "lenso",
        name: "Lenso.ai",
        mode: "link",
        setting: "",
        description: "Opens Lenso.ai reverse image search.",
    },
    Service {
        slug: "videntifier",
        name: "Videntifier",
        mode: "api",
        setting: "copyright.videntifier_key",
        description: "Fingerprint matching for video and images (API key).",
    },
    Service {
        slug: "scoredetect",
        name: "ScoreDetect",
        mode: "api",
        setting: "copyright.scoredetect_key",
        description: "Timestamped ownership certificates (API key).",
    },
    Service {
        slug: "copysentry",
        name: "Copysentry",
        mode: "api",
        setting: "copyright.copysentry_key",
        description: "Continuous monitoring of pages that copy your media (API key).",
    },
    Service {
        slug: "dmca_com",
        name: "DMCA.com",
        mode: "api",
        setting: "copyright.dmca_key",
        description: "Managed takedowns (API key).",
    },
    Service {
        slug: "bolster",
        name: "Bolster.ai",
        mode: "api",
        setting: "copyright.bolster_key",
        description: "Brand and content abuse detection (API key).",
    },
    Service {
        slug: "oxylabs",
        name: "Oxylabs",
        mode: "api",
        setting: "copyright.oxylabs_key",
        description: "Web scraping for scheduled scans (API key).",
    },
    Service {
        slug: "urlbox",
        name: "Urlbox",
        mode: "api",
        setting: "copyright.urlbox_key",
        description: "Screenshots of infringing pages as evidence (API key).",
    },
];

pub fn service(slug: &str) -> Option<&'static Service> {
    SERVICES.iter().find(|s| s.slug == slug)
}

/// The URL a link-mode service opens for a public image address.
pub fn search_link(slug: &str, image_url: &str) -> Option<String> {
    let u = urlencode(image_url);
    Some(match slug {
        "google_images" => format!("https://lens.google.com/uploadbyurl?url={u}"),
        "bing_visual" => {
            format!("https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{u}")
        }
        "yandex_images" => format!("https://yandex.com/images/search?rpt=imageview&url={u}"),
        "tineye" => format!("https://tineye.com/search?url={u}"),
        "lenso" => format!("https://lenso.ai/en?url={u}"),
        _ => return None,
    })
}

fn urlencode(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

pub fn evidence_hash(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Scan {
    pub id: i64,
    pub media_id: i64,
    pub service: String,
    pub mode: String,
    pub status: String,
    pub result: Option<String>,
    pub matches: i64,
    pub created_at: String,
    pub finished_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct Violation {
    pub id: i64,
    pub uuid: String,
    pub media_id: Option<i64>,
    pub product_id: Option<i64>,
    pub url: String,
    pub host: String,
    pub source: String,
    pub evidence_note: String,
    pub evidence_hash: String,
    pub mark_session: Option<i64>,
    pub status: String,
    pub notice_sent_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, sqlx::FromRow)]
pub struct ViolationEvent {
    pub id: i64,
    pub violation_id: i64,
    pub kind: String,
    pub note: String,
    pub at: String,
}

/// Who signs the notice; from settings.
#[derive(Debug, Clone, Default)]
pub struct Owner {
    pub name: String,
    pub company: String,
    pub email: String,
    pub address: String,
    pub site_name: String,
    pub store_url: String,
}

const V_SELECT: &str = "SELECT id, uuid, media_id, product_id, url, host, source, evidence_note, evidence_hash, mark_session, status, notice_sent_at, created_at, updated_at FROM violations";

#[derive(Clone)]
pub struct Copyright {
    db: Db,
}

impl Copyright {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub async fn record_scan(
        &self,
        media_id: i64,
        service: &str,
        mode: &str,
        status: &str,
        result: Option<&str>,
        matches: i64,
    ) -> Result<i64> {
        let now = crate::now();
        let id = sqlx::query("INSERT INTO copyright_scans (media_id, service, mode, status, result, matches, created_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
            .bind(media_id).bind(service).bind(mode).bind(status).bind(result).bind(matches).bind(&now).bind(if status == "queued" { None } else { Some(&now) })
            .execute(&self.db.pool).await?.last_insert_rowid();
        Ok(id)
    }

    pub async fn finish_scan(
        &self,
        id: i64,
        status: &str,
        result: Option<&str>,
        matches: i64,
    ) -> Result<()> {
        sqlx::query("UPDATE copyright_scans SET status = ?, result = ?, matches = ?, finished_at = ? WHERE id = ?")
            .bind(status).bind(result).bind(matches).bind(crate::now()).bind(id).execute(&self.db.pool).await?;
        Ok(())
    }

    pub async fn scans(&self, media_id: Option<i64>, limit: i64) -> Result<Vec<Scan>> {
        Ok(sqlx::query_as::<_, Scan>("SELECT id, media_id, service, mode, status, result, matches, created_at, finished_at FROM copyright_scans WHERE (? IS NULL OR media_id = ?) ORDER BY id DESC LIMIT ?")
            .bind(media_id).bind(media_id).bind(limit).fetch_all(&self.db.pool).await?)
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn report(
        &self,
        url: &str,
        media_id: Option<i64>,
        product_id: Option<i64>,
        source: &str,
        note: &str,
        evidence: Option<&[u8]>,
        mark_session: Option<i64>,
    ) -> Result<Violation> {
        let url = url.trim();
        if !url.starts_with("http://") && !url.starts_with("https://") {
            bail!("Enter the full address of the infringing page, starting with https://");
        }
        let host = url
            .split("//")
            .nth(1)
            .unwrap_or("")
            .split('/')
            .next()
            .unwrap_or("")
            .to_string();
        let now = crate::now();
        let uuid = uuid::Uuid::new_v4().to_string();
        let id = sqlx::query("INSERT INTO violations (uuid, media_id, product_id, url, host, source, evidence_note, evidence_hash, mark_session, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
            .bind(&uuid).bind(media_id).bind(product_id).bind(url).bind(&host).bind(source).bind(note.trim()).bind(evidence.map(evidence_hash).unwrap_or_default()).bind(mark_session).bind(&now).bind(&now)
            .execute(&self.db.pool).await?.last_insert_rowid();
        self.event(id, "reported", note).await?;
        Ok(self.by_id(id).await?.expect("just created"))
    }

    pub async fn event(&self, violation_id: i64, kind: &str, note: &str) -> Result<()> {
        sqlx::query(
            "INSERT INTO violation_events (violation_id, kind, note, at) VALUES (?, ?, ?, ?)",
        )
        .bind(violation_id)
        .bind(kind)
        .bind(note)
        .bind(crate::now())
        .execute(&self.db.pool)
        .await?;
        Ok(())
    }

    pub async fn events(&self, violation_id: i64) -> Result<Vec<ViolationEvent>> {
        Ok(sqlx::query_as::<_, ViolationEvent>("SELECT id, violation_id, kind, note, at FROM violation_events WHERE violation_id = ? ORDER BY id").bind(violation_id).fetch_all(&self.db.pool).await?)
    }

    pub async fn set_status(&self, id: i64, status: &str, note: &str) -> Result<()> {
        if !matches!(
            status,
            "open" | "notice_sent" | "removed" | "disputed" | "ignored"
        ) {
            bail!("unknown status");
        }
        sqlx::query("UPDATE violations SET status = ?, updated_at = ? WHERE id = ?")
            .bind(status)
            .bind(crate::now())
            .bind(id)
            .execute(&self.db.pool)
            .await?;
        self.event(id, status, note).await
    }

    pub async fn by_id(&self, id: i64) -> Result<Option<Violation>> {
        Ok(
            sqlx::query_as::<_, Violation>(&format!("{V_SELECT} WHERE id = ?"))
                .bind(id)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn by_uuid(&self, uuid: &str) -> Result<Option<Violation>> {
        Ok(
            sqlx::query_as::<_, Violation>(&format!("{V_SELECT} WHERE uuid = ?"))
                .bind(uuid)
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn list(&self, status: &str) -> Result<Vec<Violation>> {
        Ok(sqlx::query_as::<_, Violation>(&format!(
            "{V_SELECT} WHERE (? = '' OR status = ?) ORDER BY id DESC LIMIT 500"
        ))
        .bind(status)
        .bind(status)
        .fetch_all(&self.db.pool)
        .await?)
    }

    pub async fn counts(&self) -> Result<serde_json::Value> {
        let rows: Vec<(String, i64)> =
            sqlx::query_as("SELECT status, COUNT(*) FROM violations GROUP BY status")
                .fetch_all(&self.db.pool)
                .await?;
        let mut v = serde_json::json!({ "open": 0, "notice_sent": 0, "removed": 0, "disputed": 0, "ignored": 0 });
        for (s, n) in rows {
            v[s] = serde_json::json!(n);
        }
        let (scans,): (i64,) = sqlx::query_as("SELECT COUNT(*) FROM copyright_scans")
            .fetch_one(&self.db.pool)
            .await?;
        v["scans"] = serde_json::json!(scans);
        Ok(v)
    }

    /// Generates the DMCA notice (PDF and plain text), stores the PDF and marks the
    /// violation as notice sent.
    pub async fn generate_notice(
        &self,
        id: i64,
        owner: &Owner,
        work_title: &str,
        original_url: &str,
    ) -> Result<(Vec<u8>, String)> {
        let Some(v) = self.by_id(id).await? else {
            bail!("violation missing")
        };
        let text = notice_text(&v, owner, work_title, original_url);
        let pdf = notice_pdf(&v, owner, work_title, original_url, &text);
        let now = crate::now();
        sqlx::query("UPDATE violations SET notice_pdf = ?, notice_sent_at = ?, status = 'notice_sent', updated_at = ? WHERE id = ?")
            .bind(&pdf).bind(&now).bind(&now).bind(id).execute(&self.db.pool).await?;
        self.event(id, "notice_generated", "DMCA notice generated")
            .await?;
        Ok((pdf, text))
    }

    pub async fn notice_pdf(&self, id: i64) -> Result<Option<Vec<u8>>> {
        Ok(sqlx::query_scalar::<_, Option<Vec<u8>>>(
            "SELECT notice_pdf FROM violations WHERE id = ?",
        )
        .bind(id)
        .fetch_optional(&self.db.pool)
        .await?
        .flatten())
    }
}

pub fn notice_text(v: &Violation, o: &Owner, work_title: &str, original_url: &str) -> String {
    let who = if o.company.is_empty() {
        o.name.clone()
    } else {
        format!("{} on behalf of {}", o.name, o.company)
    };
    format!(
"NOTICE OF COPYRIGHT INFRINGEMENT (17 U.S.C. 512(c))

To the designated agent for {host}:

I am {who}, the owner (or authorised agent of the owner) of the copyrighted work described below.

1. Identification of the copyrighted work
   \"{title}\", published at {original}.

2. Identification of the infringing material
   {url}
   Please remove or disable access to this material.

3. Contact information
   {name}{company}
   {email}
   {address}

4. Statements
   I have a good faith belief that use of the material in the manner complained of is not authorised by the copyright owner, its agent, or the law.
   The information in this notification is accurate, and under penalty of perjury, I am the owner, or authorised to act on behalf of the owner, of an exclusive right that is allegedly infringed.

5. Evidence
   Reported {reported}. Evidence hash (SHA-256): {hash}{session}

Signed: {name}
Date: {date}
",
        host = v.host, who = who, title = work_title, original = original_url, url = v.url,
        name = o.name, company = if o.company.is_empty() { String::new() } else { format!(", {}", o.company) },
        email = o.email, address = o.address, reported = &v.created_at[..10],
        hash = if v.evidence_hash.is_empty() { "none recorded".to_string() } else { v.evidence_hash.clone() },
        session = v.mark_session.map(|s| format!("\n   The copy carries forensic watermark session #{s}, which identifies the account it was issued to.")).unwrap_or_default(),
        date = &crate::now()[..10]
    )
}

fn notice_pdf(
    v: &Violation,
    o: &Owner,
    work_title: &str,
    _original_url: &str,
    text: &str,
) -> Vec<u8> {
    let mut d = crate::pdf::Document::new(&format!("DMCA notice - {}", v.host));
    d.text(
        14.0,
        true,
        &format!(
            "{} - Notice of copyright infringement",
            if o.site_name.is_empty() {
                "MediaMarketplace"
            } else {
                &o.site_name
            }
        ),
    );
    d.text(10.0, false, &format!("Work: {work_title}"));
    d.space(6.0);
    d.rule();
    d.paragraph(10.0, text);
    d.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn links_and_hashes() {
        assert_eq!(
            search_link("tineye", "https://s.io/a b.jpg").unwrap(),
            "https://tineye.com/search?url=https%3A%2F%2Fs.io%2Fa%20b.jpg"
        );
        assert!(
            search_link("videntifier", "x").is_none(),
            "api services have no link"
        );
        assert_eq!(evidence_hash(b"abc").len(), 64);
        assert_eq!(SERVICES.len(), 12);
    }

    #[tokio::test]
    async fn violations_and_notices() {
        let db = Db::memory().await.unwrap();
        let c = Copyright::new(db);
        assert!(c
            .report("ftp://x", None, None, "manual", "", None, None)
            .await
            .is_err());
        let v = c
            .report(
                "https://pirate.example/watch/123",
                None,
                None,
                "manual",
                "Found via TinEye",
                Some(b"screenshot"),
                None,
            )
            .await
            .unwrap();
        assert_eq!(
            (v.host.as_str(), v.status.as_str()),
            ("pirate.example", "open")
        );
        assert_eq!(v.evidence_hash, evidence_hash(b"screenshot"));
        let owner = Owner {
            name: "Ada Owner".into(),
            company: "Demo Studio Ltd".into(),
            email: "legal@demo.io".into(),
            address: "1 Studio Lane".into(),
            site_name: "Demo Studio".into(),
            store_url: "https://demo.io/mms".into(),
        };
        let (pdf, text) = c
            .generate_notice(
                v.id,
                &owner,
                "Lighting Masterclass",
                "https://demo.io/mms/embed/product/lighting",
            )
            .await
            .unwrap();
        assert!(
            pdf.starts_with(b"%PDF")
                && text.contains("512(c)")
                && text.contains("pirate.example")
                && text.contains("Ada Owner on behalf of Demo Studio Ltd")
        );
        assert_eq!(c.by_id(v.id).await.unwrap().unwrap().status, "notice_sent");
        c.set_status(v.id, "removed", "Host confirmed removal")
            .await
            .unwrap();
        assert_eq!(c.events(v.id).await.unwrap().len(), 3);
        assert!(c.set_status(v.id, "bogus", "").await.is_err());
        let counts = c.counts().await.unwrap();
        assert_eq!(counts["removed"], 1);
        let now = crate::now();
        sqlx::query("INSERT INTO media (uuid, type, original_path, mime, hash_sha256, created_at, updated_at) VALUES ('m1','image','x.jpg','image/jpeg','h',?,?)").bind(&now).bind(&now).execute(&c.db.pool).await.unwrap();
        let id = c
            .record_scan(
                1,
                "tineye",
                "link",
                "manual",
                Some("https://tineye.com/..."),
                0,
            )
            .await
            .unwrap();
        assert_eq!(c.scans(Some(1), 10).await.unwrap()[0].id, id);
    }
}
