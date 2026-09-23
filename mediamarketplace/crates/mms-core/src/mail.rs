//! Outgoing email over SMTP (lettre). Every send is logged; a missing SMTP host means
//! "not configured" and callers carry on (receipts and notices stay available in the store).

use crate::db::Db;
use anyhow::{bail, Context, Result};
use lettre::message::{header::ContentType, Attachment, MultiPart, SinglePart};
use lettre::transport::smtp::authentication::Credentials;
use lettre::{AsyncSmtpTransport, AsyncTransport, Message, Tokio1Executor};

#[derive(Debug, Clone, Default)]
pub struct Smtp {
    pub host: String,
    pub port: u16,
    pub username: String,
    pub password: String,
    pub from: String,
    pub tls: String, // "starttls" | "tls" | "none"
}

impl Smtp {
    pub fn configured(&self) -> bool {
        !self.host.trim().is_empty() && !self.from.trim().is_empty()
    }
}

pub struct Outgoing<'a> {
    pub to: &'a str,
    pub subject: &'a str,
    pub text: &'a str,
    pub html: Option<&'a str>,
    pub attachment: Option<(&'a str, &'a [u8], &'a str)>, // filename, bytes, mime
    pub kind: &'a str,
}

#[derive(Clone)]
pub struct Mailer {
    db: Db,
}

impl Mailer {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    /// Builds the message; pure so it can be tested without a server.
    pub fn build(smtp: &Smtp, m: &Outgoing<'_>) -> Result<Message> {
        let from = smtp.from.parse().context("invalid From address")?;
        let to = m.to.parse().context("invalid recipient address")?;
        let builder = Message::builder().from(from).to(to).subject(m.subject);
        let text = SinglePart::builder()
            .header(ContentType::TEXT_PLAIN)
            .body(m.text.to_string());
        let mut body = match m.html {
            Some(h) => MultiPart::alternative().singlepart(text).singlepart(
                SinglePart::builder()
                    .header(ContentType::TEXT_HTML)
                    .body(h.to_string()),
            ),
            None => MultiPart::mixed().singlepart(text),
        };
        if let Some((name, bytes, mime)) = m.attachment {
            let ct = ContentType::parse(mime)
                .unwrap_or(ContentType::parse("application/octet-stream").unwrap());
            body = MultiPart::mixed()
                .multipart(body)
                .singlepart(Attachment::new(name.to_string()).body(bytes.to_vec(), ct));
        }
        Ok(builder.multipart(body)?)
    }

    pub async fn send(&self, smtp: &Smtp, m: Outgoing<'_>) -> Result<bool> {
        if !smtp.configured() {
            return Ok(false);
        }
        let msg = Self::build(smtp, &m)?;
        let creds = (!smtp.username.is_empty())
            .then(|| Credentials::new(smtp.username.clone(), smtp.password.clone()));
        let port = if smtp.port == 0 { 587 } else { smtp.port };
        let mut t = match smtp.tls.as_str() {
            "tls" => AsyncSmtpTransport::<Tokio1Executor>::relay(&smtp.host)?,
            "none" => AsyncSmtpTransport::<Tokio1Executor>::builder_dangerous(&smtp.host),
            _ => AsyncSmtpTransport::<Tokio1Executor>::starttls_relay(&smtp.host)?,
        }
        .port(port);
        if let Some(c) = creds {
            t = t.credentials(c);
        }
        let transport = t.build();
        let result = transport.send(msg).await;
        let now = crate::now();
        match result {
            Ok(_) => {
                sqlx::query("INSERT INTO mail_log (to_addr, subject, kind, status, sent_at) VALUES (?, ?, ?, 'sent', ?)").bind(m.to).bind(m.subject).bind(m.kind).bind(&now).execute(&self.db.pool).await?;
                Ok(true)
            }
            Err(e) => {
                sqlx::query("INSERT INTO mail_log (to_addr, subject, kind, status, error, sent_at) VALUES (?, ?, ?, 'failed', ?, ?)").bind(m.to).bind(m.subject).bind(m.kind).bind(e.to_string()).bind(&now).execute(&self.db.pool).await?;
                bail!("mail failed: {e}")
            }
        }
    }

    pub async fn log(
        &self,
        limit: i64,
    ) -> Result<Vec<(String, String, String, String, String, String)>> {
        Ok(sqlx::query_as("SELECT to_addr, subject, kind, status, error, sent_at FROM mail_log ORDER BY id DESC LIMIT ?").bind(limit).fetch_all(&self.db.pool).await?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_multipart_with_attachment() {
        let smtp = Smtp {
            host: "smtp.example".into(),
            port: 587,
            username: String::new(),
            password: String::new(),
            from: "Demo <store@example.com>".into(),
            tls: "starttls".into(),
        };
        let m = Mailer::build(
            &smtp,
            &Outgoing {
                to: "ada@example.com",
                subject: "Receipt MMS-2026-00001",
                text: "Thanks",
                html: Some("<b>Thanks</b>"),
                attachment: Some(("receipt.pdf", b"%PDF-1.4", "application/pdf")),
                kind: "receipt",
            },
        )
        .unwrap();
        let raw = String::from_utf8_lossy(&m.formatted()).to_string();
        assert!(
            raw.contains("Subject: Receipt MMS-2026-00001")
                && raw.contains("application/pdf")
                && raw.contains("receipt.pdf")
        );
        assert!(!Smtp::default().configured());
        assert!(Mailer::build(
            &smtp,
            &Outgoing {
                to: "not-an-address",
                subject: "x",
                text: "",
                html: None,
                attachment: None,
                kind: "t"
            }
        )
        .is_err());
    }
}
