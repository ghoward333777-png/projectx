//! A small dependency-free PDF writer: A4 pages of Helvetica text with rules and
//! simple two-column rows. Enough for receipts and signed agreements, and fully
//! deterministic (no timestamps or random IDs inside the file).

use std::fmt::Write as _;

const PAGE_W: f64 = 595.28;
const PAGE_H: f64 = 841.89;
const MARGIN: f64 = 56.0;

#[derive(Default)]
pub struct Document {
    pages: Vec<String>,
    current: String,
    y: f64,
    title: String,
}

impl Document {
    pub fn new(title: &str) -> Self {
        let mut d = Self {
            title: title.to_string(),
            ..Default::default()
        };
        d.new_page();
        d
    }

    fn new_page(&mut self) {
        if !self.current.is_empty() {
            let page = std::mem::take(&mut self.current);
            self.pages.push(page);
        }
        self.y = PAGE_H - MARGIN;
    }

    fn ensure(&mut self, height: f64) {
        if self.y - height < MARGIN {
            self.new_page();
        }
    }

    /// One line of text; `bold` selects Helvetica-Bold.
    pub fn text(&mut self, size: f64, bold: bool, s: &str) {
        self.text_at(MARGIN, size, bold, s);
        self.y -= size * 1.4;
    }

    fn text_at(&mut self, x: f64, size: f64, bold: bool, s: &str) {
        self.ensure(size * 1.4);
        let font = if bold { "F2" } else { "F1" };
        let _ = writeln!(
            self.current,
            "BT /{font} {size:.1} Tf {x:.2} {:.2} Td ({}) Tj ET",
            self.y - size,
            escape(s)
        );
    }

    /// Paragraph wrapped to the page width (approximate Helvetica metrics).
    pub fn paragraph(&mut self, size: f64, s: &str) {
        let max_chars = ((PAGE_W - 2.0 * MARGIN) / (size * 0.5)) as usize;
        for para in s.split('\n') {
            if para.trim().is_empty() {
                self.y -= size * 0.8;
                continue;
            }
            let mut line = String::new();
            for word in para.split_whitespace() {
                if !line.is_empty() && line.len() + 1 + word.len() > max_chars {
                    self.text(size, false, &line);
                    line.clear();
                }
                if !line.is_empty() {
                    line.push(' ');
                }
                line.push_str(word);
            }
            if !line.is_empty() {
                self.text(size, false, &line);
            }
        }
    }

    /// A row with a left label and a right-aligned value.
    pub fn row(&mut self, size: f64, bold: bool, left: &str, right: &str) {
        self.ensure(size * 1.4);
        let y = self.y;
        self.text_at(MARGIN, size, bold, left);
        self.y = y;
        let width = right.len() as f64 * size * 0.5;
        self.text_at(PAGE_W - MARGIN - width, size, bold, right);
        self.y = y - size * 1.4;
    }

    pub fn rule(&mut self) {
        self.ensure(8.0);
        let _ = writeln!(
            self.current,
            "0.6 w {:.2} {:.2} m {:.2} {:.2} l S",
            MARGIN,
            self.y - 3.0,
            PAGE_W - MARGIN,
            self.y - 3.0
        );
        self.y -= 10.0;
    }

    pub fn space(&mut self, pt: f64) {
        self.y -= pt;
    }

    /// Serialises the document. The output is byte-stable for the same input.
    pub fn finish(mut self) -> Vec<u8> {
        self.new_page();
        let n = self.pages.len();
        // Objects: 1 catalog, 2 pages, 3 font regular, 4 font bold, 5 info, then per page: page, content.
        let mut objects: Vec<String> = Vec::new();
        let kids: Vec<String> = (0..n).map(|i| format!("{} 0 R", 6 + i * 2)).collect();
        objects.push("<< /Type /Catalog /Pages 2 0 R >>".into());
        objects.push(format!(
            "<< /Type /Pages /Kids [{}] /Count {n} >>",
            kids.join(" ")
        ));
        objects.push(
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
                .into(),
        );
        objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>".into());
        objects.push(format!(
            "<< /Title ({}) /Producer (MediaMarketplace Studio) >>",
            escape(&self.title)
        ));
        for (i, content) in self.pages.iter().enumerate() {
            let content_obj = 7 + i * 2;
            objects.push(format!("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2} {PAGE_H:.2}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_obj} 0 R >>"));
            objects.push(format!(
                "<< /Length {} >>\nstream\n{}endstream",
                content.len(),
                content
            ));
        }
        let mut out = String::from("%PDF-1.4\n%\u{e2}\u{e3}\u{cf}\u{d3}\n");
        let mut offsets = Vec::new();
        for (i, obj) in objects.iter().enumerate() {
            offsets.push(out.len());
            let _ = write!(out, "{} 0 obj\n{}\nendobj\n", i + 1, obj);
        }
        let xref = out.len();
        let _ = write!(out, "xref\n0 {}\n0000000000 65535 f \n", objects.len() + 1);
        for o in offsets {
            let _ = writeln!(out, "{o:010} 00000 n ");
        }
        let _ = write!(
            out,
            "trailer\n<< /Size {} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n",
            objects.len() + 1
        );
        // Text is written as WinAnsi; map the few non-Latin-1 characters we produce.
        out.chars()
            .map(|c| {
                if (c as u32) < 256 {
                    c as u32 as u8
                } else {
                    b'?'
                }
            })
            .collect()
    }
}

fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '(' | ')' | '\\' => {
                out.push('\\');
                out.push(c);
            }
            '\r' | '\n' => out.push(' '),
            '\u{2013}' | '\u{2014}' => out.push('-'),
            '\u{2018}' | '\u{2019}' => out.push('\''),
            '\u{201c}' | '\u{201d}' => out.push('"'),
            '\u{2026}' => out.push_str("..."),
            c if (c as u32) < 256 => out.push(c),
            _ => out.push('?'),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writes_a_parsable_deterministic_pdf() {
        let build = || {
            let mut d = Document::new("Receipt R-2026-0001");
            d.text(18.0, true, "Receipt R-2026-0001");
            d.rule();
            d.row(11.0, false, "Coastal Textures Pack (x1)", "USD 29.00");
            d.row(11.0, true, "Total", "USD 29.00");
            d.paragraph(10.0, &"Terms and conditions apply. ".repeat(60));
            d.finish()
        };
        let a = build();
        let b = build();
        assert_eq!(a, b);
        let s = String::from_utf8_lossy(&a);
        assert!(s.starts_with("%PDF-1.4"));
        assert!(s.contains("/Type /Page ") && s.contains("(Receipt R-2026-0001) Tj"));
        assert!(s.contains("Helvetica-Bold"));
        assert!(s.ends_with("%%EOF\n"));
        // Parentheses are escaped in strings.
        let mut d = Document::new("x");
        d.text(10.0, false, "a (b) \\ c");
        assert!(String::from_utf8_lossy(&d.finish()).contains("(a \\(b\\) \\\\ c) Tj"));
    }

    #[test]
    fn long_documents_paginate() {
        let mut d = Document::new("Long");
        for i in 0..200 {
            d.text(11.0, false, &format!("Line {i}"));
        }
        let s = String::from_utf8_lossy(&d.finish()).to_string();
        assert!(s.matches("/Type /Page ").count() >= 3);
    }
}
