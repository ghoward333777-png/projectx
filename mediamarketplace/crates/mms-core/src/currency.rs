//! Multi-currency: ECB reference rates (base EUR) cached daily, conversion between
//! any two listed currencies, and rounding per currency.

use crate::db::Db;
use anyhow::{bail, Context, Result};

pub const ECB_URL: &str = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml";

/// Currencies whose minor unit is not 1/100.
pub fn minor_units(code: &str) -> u32 {
    match code {
        "JPY" | "KRW" | "HUF" | "ISK" | "CLP" | "VND" => 0,
        "BHD" | "KWD" | "OMR" | "JOD" => 3,
        _ => 2,
    }
}

/// Parses the ECB daily XML into (code, rate-per-EUR) pairs; EUR itself is 1.
pub fn parse_ecb(xml: &str) -> Vec<(String, f64)> {
    let mut out = vec![("EUR".to_string(), 1.0)];
    for chunk in xml.split("<Cube ").skip(1) {
        let attr = |name: &str| {
            chunk
                .split(&format!("{name}='"))
                .nth(1)
                .and_then(|s| s.split('\'').next())
                .or_else(|| {
                    chunk
                        .split(&format!("{name}=\""))
                        .nth(1)
                        .and_then(|s| s.split('"').next())
                })
        };
        if let (Some(c), Some(r)) = (attr("currency"), attr("rate")) {
            if let Ok(rate) = r.parse::<f64>() {
                if c.len() == 3 && rate > 0.0 {
                    out.push((c.to_string(), rate));
                }
            }
        }
    }
    out
}

#[derive(Clone)]
pub struct Currency {
    db: Db,
}

impl Currency {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub async fn store_rates(&self, rates: &[(String, f64)]) -> Result<usize> {
        let now = crate::now();
        for (code, rate) in rates {
            sqlx::query("INSERT INTO currency_rates (code, rate, fetched_at) VALUES (?, ?, ?) ON CONFLICT(code) DO UPDATE SET rate = excluded.rate, fetched_at = excluded.fetched_at")
                .bind(code).bind(rate).bind(&now).execute(&self.db.pool).await?;
        }
        Ok(rates.len())
    }

    /// Fetches the ECB file and stores it. Needs outbound HTTPS.
    pub async fn refresh(&self) -> Result<usize> {
        let xml = reqwest::Client::new()
            .get(ECB_URL)
            .send()
            .await
            .context("ECB request")?
            .text()
            .await?;
        let rates = parse_ecb(&xml);
        if rates.len() < 2 {
            bail!("ECB file had no rates");
        }
        self.store_rates(&rates).await
    }

    pub async fn rate(&self, code: &str) -> Result<Option<f64>> {
        Ok(
            sqlx::query_scalar("SELECT rate FROM currency_rates WHERE code = ?")
                .bind(code.to_ascii_uppercase())
                .fetch_optional(&self.db.pool)
                .await?,
        )
    }

    pub async fn fetched_at(&self) -> Result<Option<String>> {
        Ok(
            sqlx::query_scalar("SELECT MAX(fetched_at) FROM currency_rates")
                .fetch_optional(&self.db.pool)
                .await?
                .flatten(),
        )
    }

    /// Converts minor units between currencies through EUR; `None` when a rate is missing.
    pub async fn convert(&self, amount_minor: i64, from: &str, to: &str) -> Result<Option<i64>> {
        let (from, to) = (from.to_ascii_uppercase(), to.to_ascii_uppercase());
        if from == to {
            return Ok(Some(amount_minor));
        }
        let (Some(rf), Some(rt)) = (self.rate(&from).await?, self.rate(&to).await?) else {
            return Ok(None);
        };
        let major = amount_minor as f64 / 10f64.powi(minor_units(&from) as i32);
        let eur = major / rf;
        let target = eur * rt;
        let minor = (target * 10f64.powi(minor_units(&to) as i32)).round() as i64;
        Ok(Some(minor))
    }

    /// The factor applied to a base amount when charging in `to`.
    pub async fn factor(&self, from: &str, to: &str) -> Result<Option<f64>> {
        let (from, to) = (from.to_ascii_uppercase(), to.to_ascii_uppercase());
        if from == to {
            return Ok(Some(1.0));
        }
        let (Some(rf), Some(rt)) = (self.rate(&from).await?, self.rate(&to).await?) else {
            return Ok(None);
        };
        Ok(Some(rt / rf))
    }
}

/// Formats minor units with the currency's own number of decimals.
pub fn format(amount_minor: i64, code: &str) -> String {
    let units = minor_units(code);
    if units == 0 {
        return format!("{code} {amount_minor}");
    }
    let div = 10i64.pow(units);
    let sign = if amount_minor < 0 { "-" } else { "" };
    let a = amount_minor.abs();
    format!(
        "{sign}{code} {}.{:0width$}",
        a / div,
        a % div,
        width = units as usize
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"<gesmes:Envelope><Cube><Cube time='2026-09-22'><Cube currency='USD' rate='1.1750'/><Cube currency='JPY' rate='170.15'/><Cube currency='GBP' rate='0.8650'/></Cube></Cube></gesmes:Envelope>"#;

    #[tokio::test]
    async fn rates_convert_and_round() {
        let db = Db::memory().await.unwrap();
        let c = Currency::new(db);
        let rates = parse_ecb(SAMPLE);
        assert_eq!(rates.len(), 4);
        c.store_rates(&rates).await.unwrap();
        assert_eq!(c.convert(10000, "USD", "USD").await.unwrap(), Some(10000));
        // 100 USD → 85.11 EUR → 73.62 GBP
        assert_eq!(c.convert(10000, "USD", "GBP").await.unwrap(), Some(7362));
        assert_eq!(
            c.convert(10000, "USD", "JPY").await.unwrap(),
            Some(14481),
            "no decimals for yen"
        );
        assert_eq!(c.convert(10000, "USD", "XXX").await.unwrap(), None);
        assert_eq!(format(14481, "JPY"), "JPY 14481");
        assert_eq!(format(7362, "GBP"), "GBP 73.62");
        assert!((c.factor("USD", "GBP").await.unwrap().unwrap() - 0.7362).abs() < 0.001);
    }
}
