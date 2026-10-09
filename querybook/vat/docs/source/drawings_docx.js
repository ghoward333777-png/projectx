const fs = require("fs"); const d = require("docx");
const { Document, Packer, Paragraph, ImageRun, PageBreak, AlignmentType } = d;
const files = process.argv.slice(3);
const W = 6.5 * 96, ch = [];
files.forEach((f, i) => {
  const buf = fs.readFileSync(f);
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  const sc = Math.min(W / w, (9 * 96) / h);
  ch.push(new Paragraph({ alignment: AlignmentType.CENTER, children: [new ImageRun({ type: "png", data: buf,
    transformation: { width: Math.round(w * sc), height: Math.round(h * sc) },
    altText: { title: `FIG. ${i + 1}`, description: `Verified Agent Transport drawing, FIG. ${i + 1}`, name: `fig${i + 1}` } })] }));
  if (i < files.length - 1) ch.push(new Paragraph({ children: [new PageBreak()] }));
});
const doc = new Document({ title: "Verified Agent Transport — Drawings", sections: [{ properties: { page: { size: { width: 12240, height: 15840 },
  margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 } } }, children: ch }] });
Packer.toBuffer(doc).then(b => fs.writeFileSync(process.argv[2], b));
