use crate::config::Config;
use crate::db::Db;
use serde::Serialize;
use std::path::Path;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Ok,
    Warn,
    Fail,
}

#[derive(Debug, Clone, Serialize)]
pub struct Check {
    pub name: String,
    pub status: Status,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct Report {
    pub version: String,
    pub status: Status,
    pub checks: Vec<Check>,
}

impl Report {
    fn overall(checks: &[Check]) -> Status {
        if checks.iter().any(|c| c.status == Status::Fail) {
            Status::Fail
        } else if checks.iter().any(|c| c.status == Status::Warn) {
            Status::Warn
        } else {
            Status::Ok
        }
    }
}

pub async fn run(config: &Config, db: &Db) -> Report {
    let mut checks = Vec::new();

    checks.push(match db.ping().await {
        Ok(()) => Check {
            name: "database".into(),
            status: Status::Ok,
            detail: format!("SQLite at {}", config.database_path().display()),
        },
        Err(e) => Check {
            name: "database".into(),
            status: Status::Fail,
            detail: e.to_string(),
        },
    });

    checks.push(match db.applied_migrations().await {
        Ok(v) if v.len() == crate::db::MIGRATOR.iter().count() => Check {
            name: "migrations".into(),
            status: Status::Ok,
            detail: format!("{} applied", v.len()),
        },
        Ok(v) => Check {
            name: "migrations".into(),
            status: Status::Fail,
            detail: format!(
                "{} of {} applied; run mms-server migrate",
                v.len(),
                crate::db::MIGRATOR.iter().count()
            ),
        },
        Err(e) => Check {
            name: "migrations".into(),
            status: Status::Fail,
            detail: e.to_string(),
        },
    });

    for (name, dir) in [
        ("media (public)", config.media_public_dir()),
        ("media (private)", config.media_private_dir()),
    ] {
        checks.push(writable(name, &dir));
    }

    checks.push(match binary(&config.media.ffmpeg_path) {
        Some(p) => Check {
            name: "ffmpeg".into(),
            status: Status::Ok,
            detail: p,
        },
        None => Check {
            name: "ffmpeg".into(),
            status: Status::Warn,
            detail:
                "not found: video thumbnails, transcoding and Level 3 watermarking are disabled"
                    .into(),
        },
    });

    checks.push(if config.server.public_url.starts_with("https://") {
        Check {
            name: "public url".into(),
            status: Status::Ok,
            detail: config.server.public_url.clone(),
        }
    } else {
        Check {
            name: "public url".into(),
            status: Status::Warn,
            detail: format!(
                "{} is not HTTPS; put a TLS reverse proxy in front before going live",
                config.server.public_url
            ),
        }
    });

    Report {
        version: crate::version().to_string(),
        status: Report::overall(&checks),
        checks,
    }
}

fn writable(name: &str, dir: &Path) -> Check {
    if let Err(e) = std::fs::create_dir_all(dir) {
        return Check {
            name: name.into(),
            status: Status::Fail,
            detail: format!("cannot create {}: {e}", dir.display()),
        };
    }
    let probe = dir.join(".mms-write-test");
    match std::fs::write(&probe, b"ok").and_then(|_| std::fs::remove_file(&probe)) {
        Ok(()) => Check {
            name: name.into(),
            status: Status::Ok,
            detail: dir.display().to_string(),
        },
        Err(e) => Check {
            name: name.into(),
            status: Status::Fail,
            detail: format!("{} is not writable: {e}", dir.display()),
        },
    }
}

/// Resolves a binary name or path; returns the absolute path when found.
pub fn binary(name_or_path: &str) -> Option<String> {
    let p = Path::new(name_or_path);
    if p.components().count() > 1 {
        return p.is_file().then(|| p.display().to_string());
    }
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|d| d.join(name_or_path))
        .find(|c| c.is_file())
        .map(|c| c.display().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn report_covers_db_dirs_and_binaries() {
        let tmp = std::env::temp_dir().join(format!("mms-health-{}", uuid::Uuid::new_v4()));
        let config = Config::generate(tmp.clone(), "127.0.0.1:0", "http://localhost");
        let db = Db::memory().await.unwrap();
        let report = run(&config, &db).await;
        let names: Vec<&str> = report.checks.iter().map(|c| c.name.as_str()).collect();
        assert_eq!(
            names,
            [
                "database",
                "migrations",
                "media (public)",
                "media (private)",
                "ffmpeg",
                "public url"
            ]
        );
        assert_eq!(report.checks[0].status, Status::Ok);
        assert_eq!(report.checks[1].status, Status::Ok);
        assert_eq!(report.checks[2].status, Status::Ok);
        assert_ne!(report.status, Status::Fail);
        std::fs::remove_dir_all(tmp).ok();
        assert!(binary("definitely-not-a-binary-xyz").is_none());
    }
}
