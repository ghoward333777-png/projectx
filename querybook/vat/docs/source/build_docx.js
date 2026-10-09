// Generic JSON-blocks -> .docx builder. Usage: node build_docx.js in.json out.docx
const fs = require("fs");
const d = require("docx");
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType, AlignmentType,
  HeadingLevel, LevelFormat, BorderStyle, Footer, Header, PageNumber, PageBreak, TableLayoutType } = d;
const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const F = spec.font || "Times New Roman", SZ = (spec.size || 12) * 2, MONO = "Consolas";
const LINE = spec.line || 276;
const CONTENT_W = 12240 - 2 * 1440;
function runs(text, base = {}) {
  const out = [];
  const parts = String(text).split(/(\*\*[^*]+?\*\*|`[^`]+?`|\*[^*\s][^*]*?\*)/);
  for (const p of parts) {
    if (!p) continue;
    if (p.startsWith("**") && p.endsWith("**")) out.push(new TextRun({ text: p.slice(2, -2), bold: true, ...base }));
    else if (p.startsWith("`") && p.endsWith("`")) out.push(new TextRun({ text: p.slice(1, -1), font: MONO, size: Math.round(SZ * 0.9), ...base }));
    else if (p.length > 2 && p.startsWith("*") && p.endsWith("*")) out.push(new TextRun({ text: p.slice(1, -1), italics: true, ...base }));
    else out.push(new TextRun({ text: p, ...base }));
  }
  return out;
}
const children = [];
let listInst = 0, paraNo = 0;
const border = { style: BorderStyle.SINGLE, size: 4, color: "808080" };
const borders = { top: border, bottom: border, left: border, right: border };
for (const b of spec.blocks) {
  switch (b.t) {
    case "title":
      children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: b.before || 0, after: 240 },
        children: runs(b.text, { bold: true, size: SZ + 4 }) })); break;
    case "center":
      children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: b.after ?? 120 },
        children: runs(b.text, { bold: !!b.bold, italics: !!b.italic }) })); break;
    case "h1": children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: runs(b.text) })); break;
    case "h2": children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: runs(b.text) })); break;
    case "h3": children.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: runs(b.text) })); break;
    case "p":
      children.push(new Paragraph({ alignment: spec.justify ? AlignmentType.JUSTIFIED : AlignmentType.LEFT,
        indent: b.indent ? { firstLine: 720 } : undefined, spacing: { after: 160 },
        children: runs(b.text, { italics: !!b.italic }) })); break;
    case "np": // numbered patent paragraph [0001]
      paraNo++;
      children.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 160 },
        children: [new TextRun({ text: `[${String(paraNo).padStart(4, "0")}]\t`, bold: true }), ...runs(b.text)],
        tabStops: [{ type: "left", position: 1080 }] })); break;
    case "bullets": case "numbered": {
      listInst++;
      for (const it of b.items)
        children.push(new Paragraph({ numbering: { reference: b.t === "bullets" ? "bul" : "num", level: 0, instance: listInst },
          spacing: { after: 80 }, children: runs(it) }));
      children.push(new Paragraph({ spacing: { after: 60 }, children: [] }));
      break; }
    case "code": {
      const csz = Math.max(...b.lines.map(l => l.length)) > 90 ? 13 : 16;
      for (let i = 0; i < b.lines.length; i++)
        children.push(new Paragraph({ shading: { type: ShadingType.CLEAR, fill: "F2F2F2", color: "auto" },
          spacing: { after: i === b.lines.length - 1 ? 200 : 0, line: 240 }, indent: { left: 144, right: 144 },
          children: [new TextRun({ text: b.lines[i].replace(/\t/g, "    ") || " ", font: MONO, size: csz })] }));
      break; }
    case "table": {
      const n = b.header.length;
      let cw;
      if (b.minc) {
        cw = b.minc.map(c => c * 130 + 240);
        const extra = CONTENT_W - cw.reduce((a, c) => a + c, 0);
        const want = b.pref.map((p, i) => Math.max(0, p - b.minc[i]));
        const wt = want.reduce((a, c) => a + c, 0) || 1;
        cw = cw.map((c, i) => c + Math.floor(extra * want[i] / wt));
      } else {
        const w = b.widths || Array(n).fill(1), tot = w.reduce((a, c) => a + c, 0);
        cw = w.map(x => Math.floor(CONTENT_W * x / tot));
      }
      cw[n - 1] += CONTENT_W - cw.reduce((a, c) => a + c, 0);
      const cell = (txt, i, hdr) => new TableCell({ borders, width: { size: cw[i], type: WidthType.DXA },
        shading: hdr ? { type: ShadingType.CLEAR, fill: "D9E2F3", color: "auto" } : undefined,
        margins: { top: 60, bottom: 60, left: 100, right: 100 },
        children: [new Paragraph({ spacing: { after: 0, line: 240 }, children: runs(txt, { bold: hdr, size: Math.round(SZ * 0.85) }) })] });
      children.push(new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: cw, layout: TableLayoutType.FIXED,
        rows: [new TableRow({ tableHeader: true, children: b.header.map((h, i) => cell(h, i, true)) }),
               ...b.rows.map(r => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, i, false)) }))] }));
      children.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
      break; }
    case "claim":
      children.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 120 }, indent: { firstLine: 720 },
        children: [new TextRun({ text: `${b.num}.  `, bold: true }), ...runs(b.text)] }));
      for (const el of b.elements || [])
        children.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { after: 80 }, indent: { left: 1440 }, children: runs(el) }));
      break;
    case "rule":
      children.push(new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "808080", space: 1 } }, spacing: { after: 200 }, children: [] })); break;
    case "pagebreak": children.push(new Paragraph({ children: [new PageBreak()] })); break;
    default: throw new Error("unknown block " + b.t);
  }
}
const hs = (sz, before) => ({ run: { size: sz, bold: true, font: F }, paragraph: { spacing: { before, after: 120 }, keepNext: true } });
const doc = new Document({
  creator: spec.creator || "", title: spec.title,
  styles: { default: { document: { run: { font: F, size: SZ } , paragraph: { spacing: { line: LINE } } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, ...hs(SZ + 2, 280), paragraph: { spacing: { before: 280, after: 120 }, keepNext: true, outlineLevel: 0, alignment: spec.h1center ? AlignmentType.CENTER : AlignmentType.LEFT } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, ...hs(SZ, 220), paragraph: { spacing: { before: 220, after: 100 }, keepNext: true, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: SZ, bold: true, italics: true, font: F }, paragraph: { spacing: { before: 160, after: 80 }, keepNext: true, outlineLevel: 2 } },
    ] },
  numbering: { config: [
    { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] } ] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: spec.header ? { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: spec.header, size: 16, color: "595959" })] })] }) } : undefined,
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 18 })] })] }) },
    children }] });
Packer.toBuffer(doc).then(buf => fs.writeFileSync(process.argv[3], buf));
