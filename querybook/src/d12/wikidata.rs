//! Wikidata harvester. Runs a pack of SPARQL queries against the Wikidata
//! Query Service and writes one NDJSON file of UFCS-shaped Fact Envelopes per
//! query. Resumable: a query whose `.done` marker exists is skipped. Polite:
//! one request at a time, a pause between pages, Retry-After honoured, and the
//! operator's contact string in the User-Agent as Wikimedia requires.
//!
//! Wikidata content is CC0, so harvested records carry no attribution burden;
//! each envelope still records its item URL as provenance.

use serde::{Deserialize, Serialize};
use serde_json::{Value as J, json};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

#[derive(Clone, Debug, Deserialize)]
pub struct Pack {
    #[serde(default = "default_endpoint")]
    pub endpoint: String,
    #[serde(default)]
    pub contact: String,
    #[serde(default = "default_page")]
    pub page_size: usize,
    #[serde(default = "default_pause")]
    pub pause_ms: u64,
    #[serde(default = "default_conf")]
    pub confidence: f64,
    #[serde(default = "default_weight")]
    pub weight: f64,
    pub query: Vec<QueryDef>,
}
fn default_endpoint() -> String {
    "https://query.wikidata.org/sparql".into()
}
fn default_page() -> usize {
    5000
}
fn default_pause() -> u64 {
    1500
}
fn default_conf() -> f64 {
    0.9
}
fn default_weight() -> f64 {
    3.0
}

#[derive(Clone, Debug, Deserialize)]
pub struct QueryDef {
    pub id: String,
    pub domain: String,
    pub predicate: String,
    /// "entity" | "literal" | "number" | "year"
    pub object_kind: String,
    pub text: String,
    pub sparql: String,
    #[serde(default = "one")]
    pub scale: f64,
    #[serde(default)]
    pub decimals: usize,
    #[serde(default)]
    pub unit: String,
    /// added after scaling (e.g. kelvin -> degrees Celsius)
    #[serde(default)]
    pub offset: f64,
    /// render in scientific notation (physical constants, particle masses)
    #[serde(default)]
    pub sci: bool,
}
fn one() -> f64 {
    1.0
}

#[derive(Debug, Default, Serialize)]
pub struct QueryReport {
    pub id: String,
    pub domain: String,
    pub rows: usize,
    pub written: usize,
    pub skipped: usize,
    pub status: String,
    pub seconds: f64,
}

#[derive(Debug, Default, Serialize)]
pub struct HarvestReport {
    pub out: String,
    pub queries: Vec<QueryReport>,
    pub envelopes: usize,
}

pub fn load_pack(path: &Path) -> anyhow::Result<Pack> {
    let p: Pack = toml::from_str(&std::fs::read_to_string(path)?)?;
    for q in &p.query {
        anyhow::ensure!(
            matches!(q.object_kind.as_str(), "entity" | "literal" | "number" | "year"),
            "query {}: object_kind must be entity, literal, number or year",
            q.id
        );
        anyhow::ensure!(!q.sparql.to_uppercase().contains(" LIMIT "), "query {}: the harvester adds LIMIT/OFFSET itself", q.id);
    }
    Ok(p)
}

pub(crate) fn qid(uri: &str) -> Option<&str> {
    uri.rsplit('/').next().filter(|s| s.starts_with('Q') && s[1..].chars().all(|c| c.is_ascii_digit()))
}

/// Label service falls back to the Q-id when no English label exists.
pub(crate) fn usable_label(l: &str) -> bool {
    !l.is_empty() && qid(l).is_none() && !(l.starts_with('Q') && l[1..].chars().all(|c| c.is_ascii_digit()))
}

fn thousands(n: i128) -> String {
    let neg = n < 0;
    let s = n.unsigned_abs().to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(c);
    }
    if neg { format!("-{out}") } else { out }
}

pub fn format_number(v: f64, decimals: usize) -> String {
    if decimals == 0 {
        thousands(v.round() as i128)
    } else {
        let s = format!("{v:.decimals$}");
        let (int, frac) = s.split_once('.').unwrap_or((&s, ""));
        let int: i128 = int.parse().unwrap_or(0);
        let frac = frac.trim_end_matches('0');
        let lead = if v < 0.0 && int == 0 { "-" } else { "" };
        if frac.is_empty() { format!("{lead}{}", thousands(int)) } else { format!("{lead}{}.{frac}", thousands(int)) }
    }
}

/// 6.6743e-11 -> "6.6743 × 10^-11"; ordinary magnitudes print plainly.
pub fn format_sci(v: f64) -> String {
    if v == 0.0 || (1e-3..1e7).contains(&v.abs()) {
        return format_number(v, 6);
    }
    let e = v.abs().log10().floor() as i32;
    let m = v / 10f64.powi(e);
    let m = format!("{m:.6}");
    let m = m.trim_end_matches('0').trim_end_matches('.');
    format!("{m} × 10^{e}")
}

/// "1889-03-31T00:00:00Z" -> "1889"; "-0043-..." -> "44 BC" (astronomical year).
pub fn format_year(t: &str) -> Option<String> {
    let neg = t.starts_with('-');
    let digits: String = t.trim_start_matches(['-', '+']).chars().take_while(|c| c.is_ascii_digit()).collect();
    let y: i64 = digits.parse().ok()?;
    Some(if neg {
        format!("{} BC", y + 1)
    } else if y == 0 {
        "1 BC".into()
    } else {
        y.to_string()
    })
}

/// One SPARQL result row -> a Fact Envelope, or None if it cannot be rendered.
pub fn envelope(pack: &Pack, q: &QueryDef, row: &J, attested: &str) -> Option<J> {
    let s_uri = row["s"]["value"].as_str()?;
    let s = qid(s_uri)?;
    let s_label = row["sLabel"]["value"].as_str().unwrap_or("");
    if !usable_label(s_label) {
        return None;
    }
    let o_raw = row["o"]["value"].as_str()?;
    let (object, object_label, object_type, shown, occurred) = match q.object_kind.as_str() {
        "entity" => {
            let o = qid(o_raw)?;
            let l = row["oLabel"]["value"].as_str().unwrap_or("");
            if !usable_label(l) {
                return None;
            }
            (json!(format!("wd:{o}")), json!(l), "entity", l.to_string(), None)
        }
        "number" => {
            let v: f64 = o_raw.parse().ok()?;
            let v = v * q.scale + q.offset;
            let shown = if q.sci { format_sci(v) } else { format_number(v, q.decimals) };
            let shown = if q.unit.is_empty() { shown } else { format!("{shown} {}", q.unit) };
            // exact value kept numerically; the rendering carries the unit
            (json!(v), J::Null, "literal", shown, None)
        }
        "year" => {
            let y = format_year(o_raw)?;
            (json!(y.clone()), J::Null, "literal", y.clone(), Some(y))
        }
        _ => (json!(o_raw), J::Null, "literal", o_raw.to_string(), None),
    };
    let text = q.text.replace("{s}", s_label).replace("{o}", &shown);
    let key = match &object {
        J::String(v) => v.clone(),
        other => other.to_string(),
    };
    let mut atom = json!({
        "subject": format!("wd:{s}"), "subject_label": s_label, "predicate": q.predicate, "object": object,
        "object_type": object_type, "polarity": true, "group": q.domain,
    });
    if !object_label.is_null() {
        atom["object_label"] = object_label;
    }
    if let Some(y) = occurred {
        atom["time"] = json!(y);
    }
    if !q.unit.is_empty() {
        atom["args"] = json!({"unit": q.unit});
    }
    Some(json!({
        "id": format!("wd:{s}|{}|{key}", q.predicate),
        "atom": atom,
        "envelope": {
            "confidence": {"value": pack.confidence, "weight": pack.weight},
            "certification": {"authority": "wikidata", "status": "uncertified"},
            "provenance": {"source": format!("https://www.wikidata.org/wiki/{s}"), "attested_at": attested, "query": q.id},
        },
        "text": text,
    }))
}

pub(crate) fn fetch(
    http: &reqwest::blocking::Client,
    pack: &Pack,
    sparql: &str,
    progress: &dyn Fn(&str),
) -> anyhow::Result<Vec<J>> {
    let mut attempt = 0u32;
    loop {
        let r = http.post(&pack.endpoint).header("Accept", "application/sparql-results+json").form(&[("query", sparql)]).send();
        match r {
            Ok(resp) if resp.status().is_success() => {
                let v: J = resp.json()?;
                return Ok(v["results"]["bindings"].as_array().cloned().unwrap_or_default());
            }
            Ok(resp) if (resp.status().as_u16() == 429 || resp.status().is_server_error()) && attempt < 6 => {
                let wait = resp
                    .headers()
                    .get("retry-after")
                    .and_then(|v| v.to_str().ok())
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(5u64 << attempt);
                progress(&format!("    endpoint busy (HTTP {}); waiting {wait}s", resp.status()));
                std::thread::sleep(Duration::from_secs(wait.min(300)));
            }
            Ok(resp) => {
                let status = resp.status();
                let body = resp.text().unwrap_or_default();
                anyhow::bail!("HTTP {status}: {}", crate::util::clip(&body, 300));
            }
            Err(e) if attempt < 6 => {
                progress(&format!("    network: {e}; retrying"));
                std::thread::sleep(Duration::from_secs(5u64 << attempt));
            }
            Err(e) => return Err(e.into()),
        }
        attempt += 1;
    }
}

/// Run the pack. `only` filters by domain or query id (empty = all).
pub fn harvest(
    pack_path: &Path,
    out: &Path,
    only: &[String],
    force: bool,
    progress: &dyn Fn(&str),
) -> anyhow::Result<HarvestReport> {
    let pack = load_pack(pack_path)?;
    std::fs::create_dir_all(out)?;
    let ua = format!(
        "QueryBookHarvester/0.1 ({})",
        if pack.contact.trim().is_empty() { "no contact set" } else { pack.contact.trim() }
    );
    let http = reqwest::blocking::Client::builder().user_agent(ua).timeout(Duration::from_secs(120)).build()?;
    let attested = crate::util::now_secs().to_string();
    let mut report = HarvestReport { out: out.display().to_string(), ..Default::default() };
    for q in &pack.query {
        if !only.is_empty() && !only.iter().any(|o| o == &q.domain || o == &q.id) {
            continue;
        }
        let file: PathBuf = out.join(format!("{}.ndjson", q.id));
        let done = out.join(format!("{}.done", q.id));
        let mut qr = QueryReport { id: q.id.clone(), domain: q.domain.clone(), ..Default::default() };
        if done.exists() && !force {
            qr.status = "already harvested".into();
            report.queries.push(qr);
            continue;
        }
        let t0 = Instant::now();
        let mut w = std::io::BufWriter::new(std::fs::File::create(&file)?);
        let mut offset = 0usize;
        let mut seen = std::collections::BTreeSet::new();
        let result: anyhow::Result<()> = (|| {
            loop {
                let sparql = format!("{}\nORDER BY ?s ?o\nLIMIT {}\nOFFSET {}", q.sparql.trim(), pack.page_size, offset);
                let rows = fetch(&http, &pack, &sparql, progress)?;
                let n = rows.len();
                qr.rows += n;
                for row in &rows {
                    match envelope(&pack, q, row, &attested) {
                        Some(env) => {
                            let id = env["id"].as_str().unwrap_or("").to_string();
                            if seen.insert(id) {
                                writeln!(w, "{env}")?;
                                qr.written += 1;
                            }
                        }
                        None => qr.skipped += 1,
                    }
                }
                offset += n;
                if n < pack.page_size {
                    break;
                }
                std::thread::sleep(Duration::from_millis(pack.pause_ms));
            }
            Ok(())
        })();
        w.flush()?;
        qr.seconds = (t0.elapsed().as_secs_f64() * 10.0).round() / 10.0;
        match result {
            Ok(()) => {
                std::fs::write(&done, format!("{}\n", qr.written))?;
                qr.status = "ok".into();
            }
            Err(e) => qr.status = format!("failed: {e}"),
        }
        progress(&format!(
            "  {:<28} {:>6} facts ({} rows, {} skipped) {:.1}s {}",
            q.id,
            qr.written,
            qr.rows,
            qr.skipped,
            qr.seconds,
            if qr.status == "ok" { "" } else { &qr.status }
        ));
        report.envelopes += qr.written;
        report.queries.push(qr);
        std::thread::sleep(Duration::from_millis(pack.pause_ms));
    }
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats() {
        assert_eq!(format_number(67_750_000.4, 0), "67,750,000");
        assert_eq!(format_number(3.14159265, 6), "3.141593");
        assert_eq!(format_number(551_695.0, 0), "551,695");
        assert_eq!(format_year("1889-03-31T00:00:00Z").unwrap(), "1889");
        assert_eq!(format_year("-0043-03-15T00:00:00Z").unwrap(), "44 BC");
        assert_eq!(format_sci(6.6743e-11), "6.6743 × 10^-11");
        assert_eq!(format_sci(299792458.0), "2.997925 × 10^8");
        assert_eq!(format_sci(3.14159265), "3.141593");
    }

    #[test]
    fn envelope_shape() {
        let pack: Pack = toml::from_str("query = []").unwrap();
        let q = QueryDef {
            id: "geo.country.area".into(),
            domain: "geography".into(),
            predicate: "area".into(),
            object_kind: "number".into(),
            text: "{s} has an area of {o}.".into(),
            sparql: String::new(),
            scale: 0.000001,
            decimals: 0,
            unit: "km²".into(),
            offset: 0.0,
            sci: false,
        };
        let row = json!({"s": {"value": "http://www.wikidata.org/entity/Q142"}, "sLabel": {"value": "France"}, "o": {"value": "551695000000"}});
        let e = envelope(&pack, &q, &row, "1").unwrap();
        assert_eq!(e["text"], "France has an area of 551,695 km².");
        assert_eq!(e["atom"]["subject"], "wd:Q142");
        let unlabeled =
            json!({"s": {"value": "http://www.wikidata.org/entity/Q1"}, "sLabel": {"value": "Q1"}, "o": {"value": "5"}});
        assert!(envelope(&pack, &q, &unlabeled, "1").is_none());
    }
}
