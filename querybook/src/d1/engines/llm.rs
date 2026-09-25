//! Model-backed extraction: the Claude API ("claude") or any OpenAI-compatible
//! server the operator hosts ("openai": vLLM, Ollama, llama.cpp, TGI...).
//!
//! QBF-C020: the prompt is composed per engine from its registered profile,
//! naming the concepts to address, the return form and the target schema.
//! QBF-C021: a malformed or over-bound reply terminates that request without
//! producing a partial record. QBF-C022: every record carries the engine and
//! prompt hash. QBF-C024: every quoted span is verified against the passage
//! it cites; an unverified record is admitted carrying that marking.

use super::{Candidate, EngineReport, Extractor};
use crate::config::EngineProfile;
use crate::d1::parse::Book;
use crate::d2::{Atom, Value};
use crate::d3::Catalog;
use crate::d3::entities::EntityTable;
use crate::util::{canon_text, sha256_hex, slug};
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::json;
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::time::Duration;

pub struct LlmEngine {
    p: EngineProfile,
    http: reqwest::blocking::Client,
}

#[derive(Deserialize, Debug)]
struct Reply {
    facts: Vec<RawFact>,
}

#[derive(Deserialize, Debug)]
struct RawFact {
    subject: String,
    #[serde(default)]
    subject_kind: String,
    predicate: String,
    object: String,
    #[serde(default)]
    object_is_entity: bool,
    #[serde(default)]
    relation: String,
    #[serde(default = "yes")]
    polarity: bool,
    pos: u64,
    quote: String,
}
fn yes() -> bool {
    true
}

pub struct Chunk {
    pub first: u64,
    pub last: u64,
    pub text: String,
    pub words: usize,
}

/// Split a book into request-sized chunks on passage boundaries.
pub fn chunks(book: &Book, chunk_words: usize) -> Vec<Chunk> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let (mut first, mut words) = (None, 0usize);
    let mut last = 0;
    for p in &book.passages {
        let w = p.text.split_whitespace().count();
        if words > 0 && words + w > chunk_words {
            out.push(Chunk { first: first.unwrap_or(0), last, text: std::mem::take(&mut cur), words });
            first = None;
            words = 0;
        }
        first.get_or_insert(p.pos);
        last = p.pos;
        cur.push_str(&format!("[p{}]{} {}\n", p.pos, if p.kind == "h" { " (heading)" } else { "" }, p.text));
        words += w;
    }
    if words > 0 {
        out.push(Chunk { first: first.unwrap_or(0), last, text: cur, words });
    }
    out
}

pub fn system_prompt(catalog: &Catalog) -> String {
    let mut preds = String::new();
    for p in catalog.predicates.values() {
        if p.type_ref.starts_with("reader.") || p.type_ref == "ufcs.fact" {
            continue;
        }
        preds.push_str(&format!("- {}: {}\n", p.id, p.describe));
    }
    format!(
        "You convert passages of a book into atomic knowledge records for a grounded reading assistant.\n\
         Rules:\n\
         1. One record = one assertion. A sentence stating three things becomes three records.\n\
         2. Use only the predicates listed below. If nothing fits, use `states` with a short self-contained sentence in the text's own words.\n\
         3. Every record must be supported by the passage it cites: `pos` is the number in the passage marker [pN], and `quote` is an exact, contiguous span copied character-for-character from that passage (12-240 characters) that supports the record.\n\
         4. Name people, places and things exactly as the text names them; prefer the fullest name the text uses. Resolve pronouns only when the passage makes the referent unambiguous.\n\
         5. Record only what the text asserts. No outside knowledge, no guesses, no summaries of your own. Negated statements get polarity false.\n\
         6. For `performs`, the object is the verb phrase in past tense (e.g. \"refused Mr. Collins's proposal\"). For `says`, the object is the exact spoken words. For `relative_of`, put the subject's role in `relation`.\n\
         7. Set object_is_entity true when the object is a named person, place, organisation or thing; otherwise false.\n\
         8. Prefer the facts a reader would ask about: who people are, how they are related, what they do, what happens, where, when, why, and what terms mean.\n\n\
         Predicates:\n{preds}"
    )
}

pub fn reply_schema() -> serde_json::Value {
    json!({
        "type": "object",
        "additionalProperties": false,
        "required": ["facts"],
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": false,
                    "required": ["subject", "subject_kind", "predicate", "object", "object_is_entity", "relation", "polarity", "pos", "quote"],
                    "properties": {
                        "subject": {"type": "string"},
                        "subject_kind": {"type": "string", "enum": ["person", "place", "organization", "thing", "concept", "event"]},
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                        "object_is_entity": {"type": "boolean"},
                        "relation": {"type": "string"},
                        "polarity": {"type": "boolean"},
                        "pos": {"type": "integer"},
                        "quote": {"type": "string"}
                    }
                }
            }
        }
    })
}

fn user_prompt(book: &Book, ents: &EntityTable, chunk: &Chunk) -> String {
    let mut known: Vec<String> = ents
        .entities
        .iter()
        .filter(|e| e.aliases.iter().any(|a| chunk.text.to_lowercase().contains(a.as_str())))
        .map(|e| format!("{} ({})", e.label, e.kind))
        .collect();
    known.sort();
    known.truncate(80);
    format!(
        "Book: {} by {}\nKnown names in this section: {}\n\nPassages:\n{}\n\nReturn JSON: {{\"facts\": [...]}} following the schema.",
        book.title,
        if book.author.is_empty() { "unknown author" } else { &book.author },
        if known.is_empty() { "none".to_string() } else { known.join("; ") },
        chunk.text
    )
}

impl LlmEngine {
    pub fn new(p: EngineProfile) -> anyhow::Result<LlmEngine> {
        let http = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(900))
            .connect_timeout(Duration::from_secs(30))
            .build()?;
        Ok(LlmEngine { p, http })
    }

    fn api_key(&self) -> Option<String> {
        if self.p.api_key_env.is_empty() {
            return None;
        }
        std::env::var(&self.p.api_key_env).ok().filter(|k| !k.is_empty())
    }

    /// One request with retries on rate limits and server errors.
    /// Returns (reply text, input tokens, output tokens).
    fn call(&self, system: &str, user: &str) -> anyhow::Result<(String, u64, u64)> {
        let mut delay = 2u64;
        for attempt in 0..6 {
            let res = if self.p.kind == "claude" { self.call_claude(system, user) } else { self.call_openai(system, user) };
            match res {
                Ok(r) => return Ok(r),
                Err(CallError::Retry(msg, after)) if attempt < 5 => {
                    let wait = after.unwrap_or(delay);
                    eprintln!("  {}: {msg}; retrying in {wait}s", self.p.id);
                    std::thread::sleep(Duration::from_secs(wait));
                    delay = (delay * 2).min(120);
                }
                Err(CallError::Retry(msg, _)) | Err(CallError::Fatal(msg)) => anyhow::bail!("{}: {msg}", self.p.id),
            }
        }
        anyhow::bail!("{}: retries exhausted", self.p.id)
    }

    fn call_claude(&self, system: &str, user: &str) -> Result<(String, u64, u64), CallError> {
        let key =
            self.api_key().ok_or_else(|| CallError::Fatal(format!("set {} to your Anthropic API key", self.p.api_key_env)))?;
        let base = if !self.p.base_url.is_empty() {
            self.p.base_url.clone()
        } else {
            std::env::var("ANTHROPIC_BASE_URL").unwrap_or_else(|_| "https://api.anthropic.com".into())
        };
        let model = if self.p.model.is_empty() { "claude-opus-5" } else { &self.p.model };
        let mut output_config = json!({"format": {"type": "json_schema", "schema": reply_schema()}});
        if !self.p.effort.is_empty() {
            output_config["effort"] = json!(self.p.effort);
        }
        let body = json!({
            "model": model,
            "max_tokens": 16000,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
            "fallbacks": "default"
        });
        let resp = self
            .http
            .post(format!("{}/v1/messages", base.trim_end_matches('/')))
            .header("x-api-key", key)
            .header("anthropic-version", "2023-06-01")
            .header("anthropic-beta", "server-side-fallback-2026-07-01")
            .json(&body)
            .send()
            .map_err(|e| CallError::Retry(format!("network: {e}"), None))?;
        let status = resp.status();
        let retry_after = resp.headers().get("retry-after").and_then(|v| v.to_str().ok()).and_then(|v| v.parse::<u64>().ok());
        let text = resp.text().map_err(|e| CallError::Retry(format!("read: {e}"), None))?;
        if status.as_u16() == 429 || status.as_u16() == 529 || status.is_server_error() {
            return Err(CallError::Retry(format!("HTTP {status}"), retry_after));
        }
        if !status.is_success() {
            return Err(CallError::Fatal(format!("HTTP {status}: {}", crate::util::clip(&text, 400))));
        }
        let v: serde_json::Value =
            serde_json::from_str(&text).map_err(|e| CallError::Fatal(format!("bad JSON envelope: {e}")))?;
        let stop = v["stop_reason"].as_str().unwrap_or("");
        if stop == "refusal" {
            return Err(CallError::Fatal(format!("declined ({})", v["stop_details"]["category"])));
        }
        if stop == "max_tokens" {
            return Err(CallError::Fatal("reply exceeded max_tokens (over-bound); no partial records produced".into()));
        }
        let out: String = v["content"]
            .as_array()
            .map(|a| a.iter().filter(|b| b["type"] == "text").filter_map(|b| b["text"].as_str()).collect())
            .unwrap_or_default();
        let it = v["usage"]["input_tokens"].as_u64().unwrap_or(0)
            + v["usage"]["cache_read_input_tokens"].as_u64().unwrap_or(0)
            + v["usage"]["cache_creation_input_tokens"].as_u64().unwrap_or(0);
        Ok((out, it, v["usage"]["output_tokens"].as_u64().unwrap_or(0)))
    }

    fn call_openai(&self, system: &str, user: &str) -> Result<(String, u64, u64), CallError> {
        anyhow_to_fatal(|| {
            anyhow::ensure!(!self.p.base_url.is_empty(), "engine {} needs base_url (e.g. http://127.0.0.1:8000/v1)", self.p.id);
            Ok(())
        })?;
        let mut body = json!({
            "model": self.p.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": format!("{system}\nReply with a single JSON object only. Schema: {}", reply_schema())},
                {"role": "user", "content": user}
            ]
        });
        if self.p.json_mode {
            body["response_format"] = json!({"type": "json_object"});
        }
        let mut req = self.http.post(format!("{}/chat/completions", self.p.base_url.trim_end_matches('/'))).json(&body);
        if let Some(k) = self.api_key() {
            req = req.bearer_auth(k);
        }
        let resp = req.send().map_err(|e| CallError::Retry(format!("network: {e}"), None))?;
        let status = resp.status();
        let text = resp.text().map_err(|e| CallError::Retry(format!("read: {e}"), None))?;
        if status.as_u16() == 429 || status.is_server_error() {
            return Err(CallError::Retry(format!("HTTP {status}"), None));
        }
        if !status.is_success() {
            return Err(CallError::Fatal(format!("HTTP {status}: {}", crate::util::clip(&text, 400))));
        }
        let v: serde_json::Value =
            serde_json::from_str(&text).map_err(|e| CallError::Fatal(format!("bad JSON envelope: {e}")))?;
        if v["choices"][0]["finish_reason"] == "length" {
            return Err(CallError::Fatal("reply truncated (over-bound); no partial records produced".into()));
        }
        let out = v["choices"][0]["message"]["content"].as_str().unwrap_or("").to_string();
        Ok((out, v["usage"]["prompt_tokens"].as_u64().unwrap_or(0), v["usage"]["completion_tokens"].as_u64().unwrap_or(0)))
    }
}

enum CallError {
    Retry(String, Option<u64>),
    Fatal(String),
}

fn anyhow_to_fatal(f: impl FnOnce() -> anyhow::Result<()>) -> Result<(), CallError> {
    f().map_err(|e| CallError::Fatal(e.to_string()))
}

/// Pull the JSON object out of a reply (tolerates code fences from self-hosted models).
fn parse_reply(text: &str) -> anyhow::Result<Reply> {
    let t = text.trim();
    let t = t.strip_prefix("```json").or_else(|| t.strip_prefix("```")).unwrap_or(t);
    let t = t.strip_suffix("```").unwrap_or(t).trim();
    let start = t.find('{').ok_or_else(|| anyhow::anyhow!("no JSON object in reply"))?;
    let end = t.rfind('}').ok_or_else(|| anyhow::anyhow!("unterminated JSON"))?;
    Ok(serde_json::from_str(&t[start..=end])?)
}

impl Extractor for LlmEngine {
    fn id(&self) -> &str {
        &self.p.id
    }
    fn reliability(&self) -> f64 {
        self.p.reliability
    }

    fn extract(
        &self,
        book: &Book,
        ents: &EntityTable,
        catalog: &Catalog,
        progress: &(dyn Fn(&str) + Sync),
    ) -> anyhow::Result<(Vec<Candidate>, EngineReport)> {
        let system = system_prompt(catalog);
        let cs = chunks(book, self.p.chunk_words.max(300));
        let passages: BTreeMap<u64, (&str, u32)> = book.passages.iter().map(|p| (p.pos, (p.text.as_str(), p.chapter))).collect();
        let done = AtomicUsize::new(0);
        let failed = AtomicUsize::new(0);
        let (tin, tout) = (AtomicU64::new(0), AtomicU64::new(0));
        let pool = rayon::ThreadPoolBuilder::new().num_threads(self.p.concurrency.max(1)).build()?;
        let n = cs.len();
        let results: Vec<Vec<Candidate>> = pool.install(|| {
            cs.par_iter()
                .map(|chunk| {
                    let user = user_prompt(book, ents, chunk);
                    let prompt_hash = sha256_hex(format!("{}|{}|{}", self.p.id, system, user).as_bytes());
                    let reply = self.call(&system, &user).and_then(|(text, i, o)| {
                        tin.fetch_add(i, Ordering::Relaxed);
                        tout.fetch_add(o, Ordering::Relaxed);
                        parse_reply(&text)
                    });
                    let k = done.fetch_add(1, Ordering::Relaxed) + 1;
                    progress(&format!("{}: request {k}/{n}", self.p.id));
                    match reply {
                        Ok(r) => self.convert(book, ents, &passages, chunk, r, &prompt_hash),
                        Err(e) => {
                            eprintln!("  {} chunk p{}-p{} failed: {e}", self.p.id, chunk.first, chunk.last);
                            failed.fetch_add(1, Ordering::Relaxed);
                            Vec::new()
                        }
                    }
                })
                .collect()
        });
        let mut all: Vec<Candidate> = results.into_iter().flatten().collect();
        let before = all.len();
        all.retain(|c| catalog.get(&c.atom.predicate).is_some());
        let unverified = all.iter().filter(|c| !c.citation_verified).count();
        let report = EngineReport {
            engine: self.p.id.clone(),
            requests: n,
            failed_requests: failed.load(Ordering::Relaxed),
            candidates: all.len(),
            refused: before - all.len(),
            unverified_citations: unverified,
            input_tokens: tin.load(Ordering::Relaxed),
            output_tokens: tout.load(Ordering::Relaxed),
            stages: None,
        };
        Ok((all, report))
    }
}

impl LlmEngine {
    /// QBF-C021 reply conversion to candidate records.
    fn convert(
        &self,
        book: &Book,
        ents: &EntityTable,
        passages: &BTreeMap<u64, (&str, u32)>,
        chunk: &Chunk,
        reply: Reply,
        prompt_hash: &str,
    ) -> Vec<Candidate> {
        let resolve = |label: &str, kind: &str| -> (String, String) {
            let key = canon_text(crate::d1::segment::base_form(label.trim()));
            if let Some(&i) = ents.surface.get(&key) {
                return (ents.entities[i].concept.clone(), ents.entities[i].label.clone());
            }
            // try the name without a leading title
            let bare: Vec<&str> = key.split(' ').collect();
            if bare.len() > 1 {
                if let Some(&i) = ents.surface.get(&bare[1..].join(" ")) {
                    return (ents.entities[i].concept.clone(), ents.entities[i].label.clone());
                }
            }
            let prefix = if kind == "concept" || kind == "thing" { "term-" } else { "" };
            (format!("w:{}/{}{}", book.id, prefix, slug(label)), label.trim().to_string())
        };
        let mut out = Vec::new();
        for f in reply.facts {
            if f.subject.trim().is_empty() || f.predicate.trim().is_empty() || f.object.trim().is_empty() {
                continue;
            }
            let pos = if (chunk.first..=chunk.last).contains(&f.pos) { f.pos } else { chunk.first };
            let Some((text, chapter)) = passages.get(&pos) else { continue };
            // QBF-C024: the quoted span must resolve inside the cited passage.
            let verified = f.quote.trim().len() >= 8 && canon_text(text).contains(&canon_text(&f.quote));
            let (sc, sl) = resolve(&f.subject, &f.subject_kind);
            let mut labels = BTreeMap::new();
            labels.insert(sc.clone(), sl);
            let object = if f.object_is_entity {
                let (oc, ol) = resolve(&f.object, "thing");
                labels.insert(oc.clone(), ol);
                Value::Concept(oc)
            } else {
                Value::Text(f.object.trim().to_string())
            };
            let mut args = BTreeMap::new();
            if f.predicate == "relative_of" && !f.relation.trim().is_empty() {
                args.insert("relation".into(), Value::Text(f.relation.trim().to_lowercase()));
            }
            let type_ref = match f.predicate.as_str() {
                "says" => "event.speech",
                "performs" | "visits" | "meets" | "occurs_in" => "event.action",
                "defined_as" => "assertion.definition",
                "is_a" | "has_trait" | "feels" | "has_quantity" => "assertion.property",
                "states" | "believes" | "recommends" => "assertion.claim",
                _ => "assertion.relation",
            };
            out.push(Candidate {
                type_ref: type_ref.into(),
                atom: Atom { subject: sc, predicate: f.predicate.trim().to_string(), object, args, polarity: f.polarity },
                labels,
                pos,
                chapter: *chapter,
                quote: if verified { f.quote.trim().to_string() } else { f.quote.trim().chars().take(240).collect() },
                engine: self.p.id.clone(),
                prompt_hash: Some(prompt_hash.to_string()),
                citation_verified: verified, sentence: None, weight: 1.0,
            });
        }
        out
    }
}

/// Token/cost estimate for a library before spending anything (`qb estimate`).
pub fn estimate(book: &Book, catalog: &Catalog, p: &EngineProfile) -> (usize, u64, u64) {
    let cs = chunks(book, p.chunk_words.max(300));
    let sys_tokens = (system_prompt(catalog).len() as f64 / 3.6) as u64;
    let mut input = 0u64;
    let mut output = 0u64;
    for c in &cs {
        let t = (c.text.len() as f64 / 3.8) as u64;
        input += sys_tokens + t + 150;
        output += (c.words as f64 * 0.9) as u64; // records + quotes run close to the source length
    }
    (cs.len(), input, output)
}
