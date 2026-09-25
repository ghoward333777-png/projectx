//! Text-modality extraction stage: turns a book file into ordered passages,
//! each with a narrative position (the basis of spoiler protection and of
//! every citation). EPUB 2/3, DOCX, HTML, Markdown and plain text.

use crate::util::{sha256_hex, slug};
use std::io::Read;
use std::path::Path;

#[derive(Clone, Debug)]
pub struct Passage {
    pub pos: u64,
    pub chapter: u32,
    /// "h" heading, "p" paragraph
    pub kind: &'static str,
    pub text: String,
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct Chapter {
    pub index: u32,
    pub title: String,
    pub start: u64,
    pub end: u64,
}

#[derive(Clone, Debug)]
pub struct Book {
    pub id: String,
    pub title: String,
    pub author: String,
    pub language: String,
    pub source_hash: String,
    pub chapters: Vec<Chapter>,
    pub passages: Vec<Passage>,
}

impl Book {
    pub fn words(&self) -> usize {
        self.passages.iter().map(|p| p.text.split_whitespace().count()).sum()
    }
}

pub fn parse_file(path: &Path, id_override: Option<&str>) -> anyhow::Result<Book> {
    let bytes = std::fs::read(path)?;
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("book").to_string();
    // uploads are stored as "<10 hex>-<original name>"
    let stem = match stem.split_once('-') {
        Some((h, rest)) if h.len() == 10 && h.chars().all(|c| c.is_ascii_hexdigit()) => rest.to_string(),
        _ => stem,
    };
    let (meta, blocks) = match ext.as_str() {
        "epub" => parse_epub(&bytes)?,
        "docx" => parse_docx(&bytes)?,
        "html" | "htm" | "xhtml" => (Meta::default(), html_blocks(&String::from_utf8_lossy(&bytes))),
        "md" | "markdown" => text_with_title(&String::from_utf8_lossy(&bytes), true),
        "txt" | "text" => text_with_title(&String::from_utf8_lossy(&bytes), false),
        "pdf" => anyhow::bail!(
            "PDF is not parsed directly; convert it first (e.g. `ebook-convert book.pdf book.epub` from Calibre) \
             so paragraph and chapter structure survive"
        ),
        "azw" | "azw3" | "mobi" | "kfx" => {
            anyhow::bail!("Kindle formats are DRM-protected; supply a DRM-free EPUB of a work you hold the rights to")
        }
        other => anyhow::bail!("unsupported file type .{other}"),
    };
    let source_hash = sha256_hex(&bytes);
    let title = if meta.title.trim().is_empty() { stem.replace(['_', '-'], " ") } else { meta.title.trim().to_string() };
    let id = match id_override {
        Some(i) => i.to_string(),
        None => {
            let s: String = slug(&title).chars().take(40).collect();
            format!("{}-{}", s.trim_end_matches('-'), &source_hash[..6])
        }
    };
    Ok(assemble(id, title, meta.author, meta.language, source_hash, blocks))
}

#[derive(Default)]
struct Meta {
    title: String,
    author: String,
    language: String,
}

/// Cut Project Gutenberg boilerplate, number passages, and derive chapters
/// from headings.
fn assemble(
    id: String,
    title: String,
    author: String,
    language: String,
    source_hash: String,
    blocks: Vec<(bool, String)>,
) -> Book {
    let mut blocks = blocks;
    if let Some(i) = blocks.iter().position(|(_, t)| t.contains("*** START OF")) {
        blocks.drain(..=i);
    }
    if let Some(i) = blocks.iter().position(|(_, t)| t.contains("*** END OF")) {
        blocks.truncate(i);
    }
    let mut passages = Vec::new();
    let mut chapters: Vec<Chapter> = Vec::new();
    let mut pos = 0u64;
    // a new chapter starts at a heading only once the current one has body text
    let mut has_body = false;
    for (heading, text) in blocks {
        let text = text.trim().to_string();
        if text.is_empty() {
            continue;
        }
        let is_heading = heading && text.chars().count() <= 160;
        // illustrated editions put a caption and the chapter marker in one heading
        let title = chapter_marker(&text).unwrap_or_else(|| text.clone());
        if is_heading && (chapters.is_empty() || has_body) {
            chapters.push(Chapter { index: chapters.len() as u32, title: title.clone(), start: pos, end: pos });
            has_body = false;
        } else if is_heading {
            // consecutive headings ("CHAPTER I." then "The Arrival") merge into
            // one title; a caption that precedes the chapter marker yields to it
            if let Some(c) = chapters.last_mut() {
                if chapterish(&title) && !chapterish(&c.title) {
                    c.title = title.clone();
                } else if c.title.len() < 100 && !chapterish(&title) {
                    c.title = format!("{} {}", c.title, title);
                }
            }
        } else if chapters.is_empty() {
            chapters.push(Chapter { index: 0, title: "Opening".into(), start: pos, end: pos });
        }
        if !is_heading {
            has_body = true;
        }
        let chapter = chapters.last().map(|c| c.index).unwrap_or(0);
        passages.push(Passage { pos, chapter, kind: if is_heading { "h" } else { "p" }, text });
        pos += 1;
    }
    let n = chapters.len();
    for i in 0..n {
        let end = if i + 1 < n { chapters[i + 1].start } else { pos };
        chapters[i].end = end;
    }
    chapters.retain(|c| c.end > c.start);
    for (i, c) in chapters.iter_mut().enumerate() {
        c.index = i as u32;
    }
    // re-link passage chapter numbers after pruning empty chapters
    let mut ci = 0usize;
    for p in passages.iter_mut() {
        while ci + 1 < chapters.len() && p.pos >= chapters[ci + 1].start {
            ci += 1;
        }
        p.chapter = ci as u32;
    }
    Book {
        id,
        title,
        author,
        language: if language.is_empty() { "en".into() } else { language },
        source_hash,
        chapters,
        passages,
    }
}

/// "“a caption.” CHAPTER XIX." -> "CHAPTER XIX."
fn chapter_marker(t: &str) -> Option<String> {
    for m in ["CHAPTER", "Chapter", "BOOK ", "PART ", "STAVE", "Stave"] {
        if let Some(i) = t.find(m) {
            if i > 0 {
                return Some(t[i..].trim().to_string());
            }
        }
    }
    None
}

fn chapterish(t: &str) -> bool {
    let l = t.trim().to_lowercase();
    ["chapter", "book ", "part ", "stave", "letter", "act ", "section", "prologue", "epilogue", "introduction", "preface"]
        .iter()
        .any(|p| l.starts_with(p))
        || l.trim_end_matches('.').chars().all(|c| "ivxlcdm0123456789".contains(c)) && !l.is_empty()
}

// ---------------------------------------------------------------- EPUB ----

fn zip_text(zip: &mut zip::ZipArchive<std::io::Cursor<&[u8]>>, name: &str) -> anyhow::Result<String> {
    let mut f = zip.by_name(name).map_err(|e| anyhow::anyhow!("{name}: {e}"))?;
    let mut s = String::new();
    f.read_to_string(&mut s)?;
    Ok(s)
}

fn parse_epub(bytes: &[u8]) -> anyhow::Result<(Meta, Vec<(bool, String)>)> {
    let mut zip = zip::ZipArchive::new(std::io::Cursor::new(bytes))?;
    let container = zip_text(&mut zip, "META-INF/container.xml")?;
    let opf_path = tags(&container, "rootfile")
        .into_iter()
        .find_map(|a| attr(&a, "full-path"))
        .ok_or_else(|| anyhow::anyhow!("container.xml has no rootfile"))?;
    let opf = zip_text(&mut zip, &opf_path)?;
    let base = match opf_path.rfind('/') {
        Some(i) => opf_path[..=i].to_string(),
        None => String::new(),
    };
    let meta = Meta {
        title: element_text(&opf, "dc:title").unwrap_or_default(),
        author: element_text(&opf, "dc:creator").unwrap_or_default(),
        language: element_text(&opf, "dc:language").unwrap_or_default(),
    };
    let mut manifest = std::collections::HashMap::new();
    for a in tags(&opf, "item") {
        if let (Some(id), Some(href)) = (attr(&a, "id"), attr(&a, "href")) {
            let props = attr(&a, "properties").unwrap_or_default();
            manifest.insert(id, (href, props));
        }
    }
    let mut blocks = Vec::new();
    for a in tags(&opf, "itemref") {
        let Some(idref) = attr(&a, "idref") else { continue };
        let Some((href, props)) = manifest.get(&idref) else { continue };
        if props.contains("nav") || attr(&a, "linear").as_deref() == Some("no") {
            continue;
        }
        let path = resolve(&base, &percent_decode(href.split('#').next().unwrap_or(href)));
        if let Ok(doc) = zip_text(&mut zip, &path) {
            blocks.extend(html_blocks(&doc));
        }
    }
    Ok((meta, blocks))
}

fn resolve(base: &str, href: &str) -> String {
    let mut parts: Vec<&str> = base.split('/').filter(|s| !s.is_empty()).collect();
    for seg in href.split('/') {
        match seg {
            "." | "" => {}
            ".." => {
                parts.pop();
            }
            s => parts.push(s),
        }
    }
    parts.join("/")
}

fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let Ok(v) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// All start tags named `name` (namespace prefix tolerated), as raw attribute text.
fn tags(xml: &str, name: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut i = 0;
    while let Some(off) = xml[i..].find('<') {
        let start = i + off + 1;
        let Some(end_off) = xml[start..].find('>') else { break };
        let inner = &xml[start..start + end_off];
        let tag_name = inner.split(|c: char| c.is_whitespace() || c == '/').next().unwrap_or("");
        let local = tag_name.rsplit(':').next().unwrap_or(tag_name);
        if local.eq_ignore_ascii_case(name) && !inner.starts_with('/') {
            out.push(inner.to_string());
        }
        i = start + end_off + 1;
    }
    out
}

fn attr(tag: &str, name: &str) -> Option<String> {
    let mut i = 0;
    while let Some(off) = tag[i..].find(name) {
        let at = i + off;
        let before_ok = at == 0 || tag.as_bytes()[at - 1].is_ascii_whitespace();
        let rest = tag[at + name.len()..].trim_start();
        if before_ok && rest.starts_with('=') {
            let rest = rest[1..].trim_start();
            let q = rest.chars().next()?;
            if q == '"' || q == '\'' {
                let body = &rest[1..];
                let end = body.find(q)?;
                return Some(decode_entities(&body[..end]));
            }
        }
        i = at + name.len();
    }
    None
}

fn element_text(xml: &str, name: &str) -> Option<String> {
    let open = xml.find(&format!("<{name}"))?;
    let gt = xml[open..].find('>')? + open + 1;
    let close = xml[gt..].find(&format!("</{name}>"))? + gt;
    Some(decode_entities(&strip_tags(&xml[gt..close])).trim().to_string())
}

fn strip_tags(s: &str) -> String {
    let mut out = String::new();
    let mut in_tag = false;
    for c in s.chars() {
        match c {
            '<' => in_tag = true,
            '>' => in_tag = false,
            c if !in_tag => out.push(c),
            _ => {}
        }
    }
    out
}

// ---------------------------------------------------------------- HTML ----

const BLOCK_TAGS: &[&str] = &[
    "p",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "blockquote",
    "section",
    "article",
    "pre",
    "tr",
    "dt",
    "dd",
    "figcaption",
    "header",
    "footer",
    "aside",
    "table",
    "ul",
    "ol",
    "body",
    "hr",
];

/// Tolerant XHTML/HTML block extractor: (is_heading, text) in document order.
pub fn html_blocks(html: &str) -> Vec<(bool, String)> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut heading_depth = 0usize;
    let mut skip_until: Option<&'static str> = None;
    let bytes = html.as_bytes();
    let mut i = 0;
    let flush = |cur: &mut String, out: &mut Vec<(bool, String)>, heading: bool| {
        let t = collapse(&decode_entities(cur));
        if !t.is_empty() {
            out.push((heading, t));
        }
        cur.clear();
    };
    while i < bytes.len() {
        if bytes[i] == b'<' {
            if html[i..].starts_with("<!--") {
                i = html[i..].find("-->").map(|e| i + e + 3).unwrap_or(bytes.len());
                continue;
            }
            let Some(end) = html[i..].find('>') else { break };
            let inner = &html[i + 1..i + end];
            i += end + 1;
            let closing = inner.starts_with('/');
            let name = inner
                .trim_start_matches('/')
                .split(|c: char| c.is_whitespace() || c == '/')
                .next()
                .unwrap_or("")
                .to_ascii_lowercase();
            let name = name.rsplit(':').next().unwrap_or("").to_string();
            if let Some(stop) = skip_until {
                if closing && name == stop {
                    skip_until = None;
                }
                continue;
            }
            match name.as_str() {
                "script" | "style" | "head" | "nav" if !closing && !inner.ends_with('/') => {
                    skip_until = Some(match name.as_str() {
                        "script" => "script",
                        "style" => "style",
                        "head" => "head",
                        _ => "nav",
                    });
                    continue;
                }
                "br" => cur.push(' '),
                n if BLOCK_TAGS.contains(&n) => {
                    let is_h = n.len() == 2 && n.starts_with('h') && n.as_bytes()[1].is_ascii_digit();
                    flush(&mut cur, &mut out, heading_depth > 0);
                    if is_h {
                        if closing {
                            heading_depth = heading_depth.saturating_sub(1);
                        } else {
                            heading_depth += 1;
                        }
                    }
                }
                "img" => {
                    if let Some(alt) = attr(inner, "alt") {
                        let alt = alt.trim();
                        if alt.len() > 3 && !alt.eq_ignore_ascii_case("cover") {
                            // alternative text survives as its own passage
                            flush(&mut cur, &mut out, heading_depth > 0);
                        }
                    }
                }
                _ => {}
            }
        } else {
            let next = html[i..].find('<').map(|n| i + n).unwrap_or(bytes.len());
            if skip_until.is_none() {
                cur.push_str(&html[i..next]);
            }
            i = next;
        }
    }
    flush(&mut cur, &mut out, heading_depth > 0);
    out
}

fn collapse(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn decode_entities(s: &str) -> String {
    if !s.contains('&') {
        return s.to_string();
    }
    let mut out = String::with_capacity(s.len());
    let mut i = 0;
    while i < s.len() {
        let c = s[i..].chars().next().unwrap();
        if c == '&' {
            if let Some(semi) = s[i..].find(';').filter(|&n| n <= 10) {
                let ent = &s[i + 1..i + semi];
                let rep = match ent {
                    "amp" => Some('&'),
                    "lt" => Some('<'),
                    "gt" => Some('>'),
                    "quot" => Some('"'),
                    "apos" => Some('\''),
                    "nbsp" => Some(' '),
                    "mdash" => Some('—'),
                    "ndash" => Some('–'),
                    "lsquo" => Some('‘'),
                    "rsquo" => Some('’'),
                    "ldquo" => Some('“'),
                    "rdquo" => Some('”'),
                    "hellip" => Some('…'),
                    "eacute" => Some('é'),
                    "egrave" => Some('è'),
                    "copy" => Some('©'),
                    _ if ent.starts_with("#x") || ent.starts_with("#X") => {
                        u32::from_str_radix(&ent[2..], 16).ok().and_then(char::from_u32)
                    }
                    _ if ent.starts_with('#') => ent[1..].parse::<u32>().ok().and_then(char::from_u32),
                    _ => None,
                };
                if let Some(r) = rep {
                    out.push(r);
                    i += semi + 1;
                    continue;
                }
            }
        }
        out.push(c);
        i += c.len_utf8();
    }
    out
}

// ---------------------------------------------------------------- DOCX ----

fn parse_docx(bytes: &[u8]) -> anyhow::Result<(Meta, Vec<(bool, String)>)> {
    let mut zip = zip::ZipArchive::new(std::io::Cursor::new(bytes))?;
    let doc = zip_text(&mut zip, "word/document.xml")?;
    let core = zip_text(&mut zip, "docProps/core.xml").unwrap_or_default();
    let meta = Meta {
        title: element_text(&core, "dc:title").unwrap_or_default(),
        author: element_text(&core, "dc:creator").unwrap_or_default(),
        language: element_text(&core, "dc:language").unwrap_or_default(),
    };
    let mut blocks = Vec::new();
    for para in doc.split("</w:p>") {
        let heading = tags(para, "pStyle")
            .iter()
            .filter_map(|t| attr(t, "w:val"))
            .any(|v| v.to_lowercase().starts_with("heading") || v.eq_ignore_ascii_case("title"));
        let mut text = String::new();
        let mut rest = para;
        while let Some(s) = rest.find("<w:t") {
            let after = &rest[s + 4..];
            if !(after.starts_with('>') || after.starts_with(' ')) {
                rest = after;
                continue;
            }
            let Some(gt) = after.find('>') else { break };
            let body = &after[gt + 1..];
            let Some(end) = body.find("</w:t>") else { break };
            text.push_str(&body[..end]);
            rest = &body[end..];
        }
        if para.contains("<w:tab/>") && text.is_empty() {
            continue;
        }
        let t = collapse(&decode_entities(&text));
        if !t.is_empty() {
            blocks.push((heading, t));
        }
    }
    Ok((meta, blocks))
}

// --------------------------------------------------------------- TEXT -----

/// Plain text / Markdown: a short opening line (or "# Title" / Gutenberg
/// "Title:" header) is the title.
fn text_with_title(text: &str, markdown: bool) -> (Meta, Vec<(bool, String)>) {
    let mut meta = Meta::default();
    for line in text.lines().take(40) {
        let l = line.trim();
        if let Some(t) = l.strip_prefix("Title:") {
            meta.title = t.trim().to_string();
        } else if let Some(a) = l.strip_prefix("Author:") {
            meta.author = a.trim().to_string();
        }
    }
    if meta.title.is_empty() {
        if let Some(first) = text.lines().map(|l| l.trim()).find(|l| !l.is_empty()) {
            let t = first.trim_start_matches('#').trim();
            if t.chars().count() <= 100 {
                meta.title = t.to_string();
            }
        }
    }
    (meta, text_blocks(text, markdown))
}

fn text_blocks(text: &str, markdown: bool) -> Vec<(bool, String)> {
    let text = text.replace("\r\n", "\n");
    let mut out = Vec::new();
    for para in text.split("\n\n") {
        let lines: Vec<&str> = para.lines().map(|l| l.trim()).filter(|l| !l.is_empty()).collect();
        if lines.is_empty() {
            continue;
        }
        let joined = lines.join(" ");
        let first = lines[0];
        let md_heading = markdown && first.starts_with('#');
        let lower = first.to_lowercase();
        let chapterish = lines.len() == 1
            && first.len() <= 80
            && (lower.starts_with("chapter ")
                || lower.starts_with("book ")
                || lower.starts_with("part ")
                || lower.starts_with("stave ")
                || lower.starts_with("letter ")
                || (first.chars().any(|c| c.is_alphabetic())
                    && first.chars().filter(|c| c.is_alphabetic()).all(|c| c.is_uppercase())
                    && first.len() <= 60));
        if md_heading {
            out.push((true, first.trim_start_matches('#').trim().to_string()));
            if lines.len() > 1 {
                out.push((false, lines[1..].join(" ")));
            }
        } else {
            out.push((chapterish, joined));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn html_blocks_and_entities() {
        let b = html_blocks(
            "<html><head><title>x</title></head><body><h2>CHAPTER I.</h2><p>It is a truth&#8212;universally <i>acknowledged</i>,</p><p>Mr.&nbsp;Bennet &amp; co.</p><script>var x;</script></body></html>",
        );
        assert_eq!(
            b,
            vec![
                (true, "CHAPTER I.".into()),
                (false, "It is a truth—universally acknowledged,".into()),
                (false, "Mr. Bennet & co.".into())
            ]
        );
    }

    #[test]
    fn chapters_from_headings() {
        let blocks = vec![
            (false, "*** START OF THE PROJECT GUTENBERG EBOOK X ***".to_string()),
            (true, "CHAPTER I.".into()),
            (true, "The Arrival".into()),
            (false, "One.".into()),
            (false, "Two.".into()),
            (true, "CHAPTER II.".into()),
            (false, "Three.".into()),
            (false, "*** END OF THE PROJECT GUTENBERG EBOOK X ***".into()),
            (false, "licence".into()),
        ];
        let b = assemble("t".into(), "T".into(), String::new(), String::new(), "h".into(), blocks);
        assert_eq!(b.chapters.len(), 2);
        assert_eq!(b.chapters[0].title, "CHAPTER I. The Arrival");
        assert_eq!(b.passages.len(), 6);
        assert_eq!(b.passages.last().unwrap().text, "Three.");
        assert_eq!(b.passages.last().unwrap().chapter, 1);
    }
}
