//! Google Drive connector for backups (the operator's own Drive).
//!
//! Authorisation is the OAuth device flow, made for servers without a
//! browser: `qb drive-auth` shows a short code, the operator enters it at
//! google.com/device on any phone or computer, and the server keeps only a
//! refresh token (in the data directory's `keys/`, mode 0600). The scope is
//! `drive.file`: QueryBook sees only the files it created itself, never the
//! rest of the Drive.
//!
//! Uploads are resumable (32 MiB pieces; an interrupted piece is resumed, not
//! restarted), so a 60–80 GB backup survives network hiccups. Only encrypted
//! `.qbk` files are ever uploaded.

use serde_json::{Value as J, json};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::Duration;

const SCOPE: &str = "https://www.googleapis.com/auth/drive.file";
const FOLDER_MIME: &str = "application/vnd.google-apps.folder";
const PIECE: u64 = 32 << 20; // a multiple of 256 KiB, as the upload protocol requires

fn piece_size() -> u64 {
    // QB_DRIVE_PIECE_KB (a multiple of 256) exists for tests and slow links
    std::env::var("QB_DRIVE_PIECE_KB")
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .filter(|k| *k >= 256 && k % 256 == 0)
        .map(|k| k << 10)
        .unwrap_or(PIECE)
}

pub struct Drive {
    http: reqwest::blocking::Client,
    client_id: String,
    client_secret: String,
    oauth: String,
    api: String,
    keys: PathBuf,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct RemoteFile {
    pub id: String,
    pub name: String,
    pub size: u64,
    pub created: String,
}

fn env(k: &str) -> anyhow::Result<String> {
    std::env::var(k)
        .ok()
        .filter(|v| !v.trim().is_empty())
        .ok_or_else(|| anyhow::anyhow!("{k} is not set (see README: Backups to Google Drive)"))
}

impl Drive {
    /// `keys` is the data directory's keys folder (where the token is kept).
    pub fn new(keys: &Path) -> anyhow::Result<Drive> {
        Ok(Drive {
            http: reqwest::blocking::Client::builder()
                .connect_timeout(Duration::from_secs(30))
                .timeout(Duration::from_secs(600))
                .build()?,
            client_id: env("QB_DRIVE_CLIENT_ID")?,
            client_secret: env("QB_DRIVE_CLIENT_SECRET")?,
            oauth: std::env::var("QB_DRIVE_OAUTH_BASE").unwrap_or_else(|_| "https://oauth2.googleapis.com".into()),
            api: std::env::var("QB_DRIVE_API_BASE").unwrap_or_else(|_| "https://www.googleapis.com".into()),
            keys: keys.to_path_buf(),
        })
    }

    fn token_file(&self) -> PathBuf {
        self.keys.join("drive-token.json")
    }

    /// One-time device-flow authorisation. `show` receives the instructions.
    pub fn authorize(&self, show: &dyn Fn(&str)) -> anyhow::Result<()> {
        let r: J = self
            .http
            .post(format!("{}/device/code", self.oauth))
            .form(&[("client_id", self.client_id.as_str()), ("scope", SCOPE)])
            .send()?
            .error_for_status()?
            .json()?;
        let url = r["verification_url"].as_str().or(r["verification_uri"].as_str()).unwrap_or("https://www.google.com/device");
        let code = r["user_code"].as_str().unwrap_or("?");
        show(&format!(
            "\nOn any phone or computer, open  {url}\nand enter the code  {code}\nthen allow QueryBook to store its own files in your Drive.\n"
        ));
        let device = r["device_code"].as_str().ok_or_else(|| anyhow::anyhow!("no device code in reply"))?.to_string();
        let mut interval = r["interval"].as_u64().unwrap_or(5);
        let deadline = std::time::Instant::now() + Duration::from_secs(r["expires_in"].as_u64().unwrap_or(1800));
        loop {
            std::thread::sleep(Duration::from_secs(interval));
            anyhow::ensure!(std::time::Instant::now() < deadline, "the code expired; run qb drive-auth again");
            let resp = self
                .http
                .post(format!("{}/token", self.oauth))
                .form(&[
                    ("client_id", self.client_id.as_str()),
                    ("client_secret", self.client_secret.as_str()),
                    ("device_code", device.as_str()),
                    ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
                ])
                .send()?;
            let v: J = resp.json()?;
            match v["error"].as_str() {
                None => {
                    let refresh = v["refresh_token"].as_str().ok_or_else(|| anyhow::anyhow!("no refresh token returned"))?;
                    self.save_token(refresh)?;
                    show("Authorised. The server can now upload backups to your Drive.");
                    return Ok(());
                }
                Some("authorization_pending") => {}
                Some("slow_down") => interval += 5,
                Some("access_denied") => anyhow::bail!("access was declined in the browser"),
                Some(e) => anyhow::bail!("authorisation failed: {e}"),
            }
        }
    }

    fn save_token(&self, refresh: &str) -> anyhow::Result<()> {
        std::fs::create_dir_all(&self.keys)?;
        let p = self.token_file();
        std::fs::write(&p, json!({"refresh_token": refresh, "scope": SCOPE}).to_string())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o600))?;
        }
        Ok(())
    }

    fn access_token(&self) -> anyhow::Result<String> {
        let t: J = serde_json::from_str(
            &std::fs::read_to_string(self.token_file())
                .map_err(|_| anyhow::anyhow!("not authorised yet: run  qb drive-auth  once"))?,
        )?;
        let refresh = t["refresh_token"].as_str().unwrap_or("");
        let v: J = self
            .http
            .post(format!("{}/token", self.oauth))
            .form(&[
                ("client_id", self.client_id.as_str()),
                ("client_secret", self.client_secret.as_str()),
                ("refresh_token", refresh),
                ("grant_type", "refresh_token"),
            ])
            .send()?
            .json()?;
        v["access_token"]
            .as_str()
            .map(String::from)
            .ok_or_else(|| anyhow::anyhow!("Drive refused the stored authorisation ({}); run  qb drive-auth  again", v["error"]))
    }

    /// The backup folder, created on first use.
    pub fn folder(&self, name: &str) -> anyhow::Result<String> {
        let tok = self.access_token()?;
        let q = format!("name = '{}' and mimeType = '{FOLDER_MIME}' and trashed = false", name.replace('\'', "\\'"));
        let v: J = self
            .http
            .get(format!("{}/drive/v3/files", self.api))
            .bearer_auth(&tok)
            .query(&[("q", q.as_str()), ("fields", "files(id,name)"), ("spaces", "drive")])
            .send()?
            .error_for_status()?
            .json()?;
        if let Some(id) = v["files"][0]["id"].as_str() {
            return Ok(id.to_string());
        }
        let v: J = self
            .http
            .post(format!("{}/drive/v3/files", self.api))
            .bearer_auth(&tok)
            .json(&json!({"name": name, "mimeType": FOLDER_MIME}))
            .send()?
            .error_for_status()?
            .json()?;
        v["id"].as_str().map(String::from).ok_or_else(|| anyhow::anyhow!("folder was not created"))
    }

    /// Resumable upload of a local file into `folder`.
    pub fn upload(&self, path: &Path, folder: &str, progress: &dyn Fn(&str)) -> anyhow::Result<RemoteFile> {
        let total = std::fs::metadata(path)?.len();
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        let tok = self.access_token()?;
        let resp = self
            .http
            .post(format!("{}/upload/drive/v3/files?uploadType=resumable", self.api))
            .bearer_auth(&tok)
            .header("X-Upload-Content-Type", "application/octet-stream")
            .header("X-Upload-Content-Length", total.to_string())
            .json(&json!({"name": name, "parents": [folder]}))
            .send()?
            .error_for_status()?;
        let session = resp
            .headers()
            .get("location")
            .and_then(|v| v.to_str().ok())
            .ok_or_else(|| anyhow::anyhow!("Drive gave no upload session"))?
            .to_string();
        let mut file = std::fs::File::open(path)?;
        let mut sent = 0u64;
        let mut failures = 0;
        let mut last_report = 0u64;
        loop {
            let len = piece_size().min(total - sent);
            let mut piece = vec![0u8; len as usize];
            use std::io::{Seek, SeekFrom};
            file.seek(SeekFrom::Start(sent))?;
            file.read_exact(&mut piece)?;
            let range = if total == 0 { "bytes */0".to_string() } else { format!("bytes {}-{}/{}", sent, sent + len - 1, total) };
            let r = self.http.put(&session).header("Content-Range", range).body(piece).send();
            match r {
                Ok(resp) if resp.status().is_success() => {
                    let v: J = resp.json()?;
                    progress(&format!("  uploaded {} ({:.1} GB)", name, total as f64 / 1e9));
                    return Ok(RemoteFile {
                        id: v["id"].as_str().unwrap_or("").to_string(),
                        name,
                        size: total,
                        created: String::new(),
                    });
                }
                Ok(resp) if resp.status().as_u16() == 308 => {
                    sent = resp
                        .headers()
                        .get("range")
                        .and_then(|v| v.to_str().ok())
                        .and_then(|r| r.rsplit('-').next())
                        .and_then(|n| n.parse::<u64>().ok())
                        .map(|n| n + 1)
                        .unwrap_or(0);
                    failures = 0;
                    if sent - last_report >= 1 << 30 {
                        progress(&format!("  {:.1} of {:.1} GB", sent as f64 / 1e9, total as f64 / 1e9));
                        last_report = sent;
                    }
                }
                other => {
                    failures += 1;
                    let why = match other {
                        Ok(r) => format!("HTTP {}", r.status()),
                        Err(e) => e.to_string(),
                    };
                    anyhow::ensure!(failures <= 8, "upload failed after retries: {why}");
                    progress(&format!("  upload interrupted ({why}); resuming"));
                    std::thread::sleep(Duration::from_secs(2u64 << failures.min(6)));
                    // ask the session how much it holds, then continue from there
                    if let Ok(st) = self.http.put(&session).header("Content-Range", format!("bytes */{total}")).send() {
                        if st.status().is_success() {
                            let v: J = st.json()?;
                            return Ok(RemoteFile {
                                id: v["id"].as_str().unwrap_or("").into(),
                                name,
                                size: total,
                                created: String::new(),
                            });
                        }
                        sent = st
                            .headers()
                            .get("range")
                            .and_then(|v| v.to_str().ok())
                            .and_then(|r| r.rsplit('-').next())
                            .and_then(|n| n.parse::<u64>().ok())
                            .map(|n| n + 1)
                            .unwrap_or(0);
                    }
                }
            }
        }
    }

    /// Backups in the folder, newest first.
    pub fn list(&self, folder: &str) -> anyhow::Result<Vec<RemoteFile>> {
        let tok = self.access_token()?;
        let q = format!("'{folder}' in parents and trashed = false");
        let v: J = self
            .http
            .get(format!("{}/drive/v3/files", self.api))
            .bearer_auth(&tok)
            .query(&[
                ("q", q.as_str()),
                ("fields", "files(id,name,size,createdTime)"),
                ("orderBy", "createdTime desc"),
                ("pageSize", "1000"),
            ])
            .send()?
            .error_for_status()?
            .json()?;
        let mut out: Vec<RemoteFile> = v["files"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|f| RemoteFile {
                id: f["id"].as_str().unwrap_or("").into(),
                name: f["name"].as_str().unwrap_or("").into(),
                size: f["size"].as_str().and_then(|s| s.parse().ok()).unwrap_or(0),
                created: f["createdTime"].as_str().unwrap_or("").into(),
            })
            .filter(|f| f.name.ends_with(".qbk"))
            .collect();
        // names carry a sortable timestamp; newest first regardless of server order
        out.sort_by(|a, b| b.name.cmp(&a.name));
        Ok(out)
    }

    pub fn delete(&self, id: &str) -> anyhow::Result<()> {
        let tok = self.access_token()?;
        self.http.delete(format!("{}/drive/v3/files/{id}", self.api)).bearer_auth(&tok).send()?.error_for_status()?;
        Ok(())
    }

    /// Stream a file's content.
    pub fn download(&self, id: &str) -> anyhow::Result<impl Read> {
        let tok = self.access_token()?;
        Ok(self
            .http
            .get(format!("{}/drive/v3/files/{id}?alt=media", self.api))
            .bearer_auth(&tok)
            .timeout(Duration::from_secs(24 * 3600))
            .send()?
            .error_for_status()?)
    }
}
