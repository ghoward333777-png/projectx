<?php

declare(strict_types=1);

/**
 * Word Manuscript Exporter
 *
 * Builds a real .docx (Office Open XML) manuscript with PHP's ZipArchive —
 * no Composer packages. The document uses a 6 x 9 in page (the KDP trim),
 * Times New Roman 12pt at 1.5 line spacing, a title page, copyright page,
 * contents list, and one Heading 1 chapter per manuscript chapter, so
 * Word's own dynamic Table of Contents and navigation pane work out of
 * the box.
 */
final class WordManuscriptExporter
{
    /** 6 x 9 inch page in twentieths of a point (1440 per inch). */
    private const PAGE_WIDTH = 8640;
    private const PAGE_HEIGHT = 12960;
    private const PAGE_MARGIN = 1080; // 0.75 in

    /** EMU per inch; figures fill the 4.5 in text column of the 6x9 page. */
    private const EMU_PER_INCH = 914400;
    private const FIGURE_WIDTH_EMU = 4114800; // 4.5 in

    /** @var array<int, array<int, array<string, mixed>>> */
    private array $mediaByChapter = [];

    /** @var array<int, string> SVG bytes keyed by figure index. */
    private array $svgParts = [];

    /** @var int Bookmark id counter. */
    private int $bookmarkId = 0;

    /**
     * Render the manuscript as .docx bytes.
     *
     * @param array<string, mixed> $book Output of generateBookFromTableOfContents().
     * @param array<string, mixed> $metadata Listing metadata (title, subtitle, author).
     */
    /**
     * @param array<string, mixed>|null $media Output of IllustrationStudio::planBookMedia();
     *   figures become captioned placeholders the author replaces in Word.
     */
    public function export(array $book, array $metadata, ?array $media = null): string
    {
        $this->mediaByChapter = [];
        $this->svgParts = [];
        $this->bookmarkId = 0;
        foreach ((array) ($media['chapters'] ?? []) as $mediaChapter) {
            $this->mediaByChapter[(int) $mediaChapter['number']] = (array) $mediaChapter['items'];
        }
        if (!class_exists(ZipArchive::class)) {
            throw new RuntimeException('The PHP zip extension is required for Word export.');
        }
        $path = tempnam(sys_get_temp_dir(), 'docx');
        if ($path === false) {
            throw new RuntimeException('Could not create a temporary file for the Word export.');
        }
        $zip = new ZipArchive();
        if ($zip->open($path, ZipArchive::OVERWRITE) !== true) {
            throw new RuntimeException('Could not open the Word archive for writing.');
        }
        $documentXml = $this->documentXml($book, $metadata); // fills svgParts
        $zip->addFromString('[Content_Types].xml', $this->contentTypesXml());
        $zip->addFromString('_rels/.rels', $this->packageRelsXml());
        $zip->addFromString('word/_rels/document.xml.rels', $this->documentRelsXml());
        $zip->addFromString('word/styles.xml', $this->stylesXml());
        $zip->addFromString('word/document.xml', $documentXml);
        if ($this->svgParts !== []) {
            $zip->addFromString('word/media/fallback.png', $this->fallbackPng());
            foreach ($this->svgParts as $index => $svg) {
                $zip->addFromString('word/media/figure' . $index . '.svg', $svg);
            }
        }
        $zip->close();
        $bytes = file_get_contents($path);
        unlink($path);
        if ($bytes === false) {
            throw new RuntimeException('Could not read the generated Word archive.');
        }
        return $bytes;
    }

    private function contentTypesXml(): string
    {
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            . '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            . '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            . '<Default Extension="xml" ContentType="application/xml"/>'
            . '<Default Extension="png" ContentType="image/png"/>'
            . '<Default Extension="svg" ContentType="image/svg+xml"/>'
            . '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            . '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            . '</Types>';
    }

    private function packageRelsXml(): string
    {
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            . '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            . '</Relationships>';
    }

    private function documentRelsXml(): string
    {
        $rels = '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>';
        if ($this->svgParts !== []) {
            $rels .= '<Relationship Id="rIdPng" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/fallback.png"/>';
            foreach (array_keys($this->svgParts) as $index) {
                $rels .= '<Relationship Id="rIdSvg' . $index . '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/figure' . $index . '.svg"/>';
            }
        }
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            . $rels
            . '</Relationships>';
    }

    /** A small white PNG used as the raster fallback beneath each SVG figure. */
    private function fallbackPng(): string
    {
        $width = 8;
        $height = 8;
        $raw = '';
        for ($y = 0; $y < $height; $y++) {
            $raw .= "\x00" . str_repeat("\xFF", $width * 3);
        }
        $chunk = static function (string $type, string $data): string {
            return pack('N', strlen($data)) . $type . $data . pack('N', crc32($type . $data));
        };
        return "\x89PNG\r\n\x1a\n"
            . $chunk('IHDR', pack('NN', $width, $height) . "\x08\x02\x00\x00\x00")
            . $chunk('IDAT', gzcompress($raw, 9))
            . $chunk('IEND', '');
    }

    /** Inline drawing referencing the SVG part (with PNG fallback). */
    private function figureDrawing(int $index, string $svg, string $name): string
    {
        $this->svgParts[$index] = $svg;
        $width = 640;
        $height = 200;
        if (preg_match('/viewBox="0 0 (\d+) (\d+)"/', $svg, $m) === 1) {
            $width = max(1, (int) $m[1]);
            $height = max(1, (int) $m[2]);
        }
        $cx = self::FIGURE_WIDTH_EMU;
        $cy = (int) round($cx * $height / max(1, $width));
        $nameEsc = $this->escape($name);
        return '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
            . '<wp:inline distT="0" distB="0" distL="0" distR="0">'
            . '<wp:extent cx="' . $cx . '" cy="' . $cy . '"/>'
            . '<wp:docPr id="' . ($index + 1000) . '" name="' . $nameEsc . '"/>'
            . '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            . '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            . '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            . '<pic:nvPicPr><pic:cNvPr id="' . ($index + 1000) . '" name="' . $nameEsc . '"/><pic:cNvPicPr/></pic:nvPicPr>'
            . '<pic:blipFill><a:blip r:embed="rIdPng">'
            . '<a:extLst><a:ext uri="{96DAC541-7B7A-43D3-8B79-37D633B846F1}">'
            . '<asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" r:embed="rIdSvg' . $index . '"/>'
            . '</a:ext></a:extLst></a:blip><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            . '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="' . $cx . '" cy="' . $cy . '"/></a:xfrm>'
            . '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            . '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>';
    }

    /**
     * A native Word table with borders and a bold header row.
     *
     * @param array{columns: array<int, string>, rows: array<int, array<int, string>>} $table
     */
    private function tableXml(array $table): string
    {
        $xml = '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>'
            . '<w:top w:val="single" w:sz="4" w:color="999999"/><w:left w:val="single" w:sz="4" w:color="999999"/>'
            . '<w:bottom w:val="single" w:sz="4" w:color="999999"/><w:right w:val="single" w:sz="4" w:color="999999"/>'
            . '<w:insideH w:val="single" w:sz="4" w:color="BBBBBB"/><w:insideV w:val="single" w:sz="4" w:color="BBBBBB"/>'
            . '</w:tblBorders></w:tblPr><w:tblGrid/>';
        $cell = function (string $text, bool $bold): string {
            $runs = '';
            foreach (preg_split('/\R/u', $text) ?: [$text] as $lineIndex => $line) {
                if ($lineIndex > 0) {
                    $runs .= '<w:r><w:br/></w:r>';
                }
                $runs .= '<w:r><w:rPr>' . ($bold ? '<w:b/>' : '') . '<w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr>'
                    . '<w:t xml:space="preserve">' . $this->escape($line) . '</w:t></w:r>';
            }
            return '<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>'
                . '<w:p><w:pPr><w:spacing w:line="240" w:lineRule="auto" w:after="40"/><w:ind w:firstLine="0"/></w:pPr>' . $runs . '</w:p></w:tc>';
        };
        $xml .= '<w:tr>';
        foreach ($table['columns'] as $column) {
            $xml .= $cell((string) $column, true);
        }
        $xml .= '</w:tr>';
        foreach ($table['rows'] as $row) {
            $xml .= '<w:tr>';
            foreach ($row as $value) {
                $xml .= $cell((string) $value, false);
            }
            $xml .= '</w:tr>';
        }
        return $xml . '</w:tbl>';
    }

    private function stylesXml(): string
    {
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            . '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            . '<w:docDefaults><w:rPrDefault><w:rPr>'
            . '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
            . '<w:sz w:val="24"/><w:szCs w:val="24"/>'
            . '</w:rPr></w:rPrDefault>'
            . '<w:pPrDefault><w:pPr><w:spacing w:line="360" w:lineRule="auto" w:after="120"/></w:pPr></w:pPrDefault>'
            . '</w:docDefaults>'
            . '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
            . '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
            . '<w:pPr><w:spacing w:before="2400" w:after="240"/><w:jc w:val="center"/></w:pPr>'
            . '<w:rPr><w:b/><w:sz w:val="56"/><w:szCs w:val="56"/></w:rPr></w:style>'
            . '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
            . '<w:pPr><w:keepNext/><w:pageBreakBefore/><w:spacing w:before="1440" w:after="360"/><w:jc w:val="center"/><w:outlineLvl w:val="0"/></w:pPr>'
            . '<w:rPr><w:b/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>'
            . '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
            . '<w:pPr><w:keepNext/><w:spacing w:before="360" w:after="160"/><w:outlineLvl w:val="1"/></w:pPr>'
            . '<w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>'
            . '</w:styles>';
    }

    private function documentXml(array $book, array $metadata): string
    {
        $title = trim((string) ($metadata['title'] ?? 'Untitled')) ?: 'Untitled';
        $subtitle = trim((string) ($metadata['subtitle'] ?? ''));
        $author = trim((string) ($metadata['author'] ?? 'Independent Author')) ?: 'Independent Author';
        $year = gmdate('Y');

        $body = $this->paragraph($title, 'Title');
        if ($subtitle !== '') {
            $body .= $this->paragraph($subtitle, null, ['italic' => true, 'center' => true]);
        }
        $body .= $this->paragraph($author, null, ['center' => true]);
        $body .= $this->pageBreakParagraph();

        $body .= $this->paragraph('Copyright © ' . $year . ' ' . $author . '. All rights reserved.', null, ['center' => true, 'small' => true]);
        $body .= $this->paragraph('No part of this book may be reproduced in any form without written permission, except for brief quotations in reviews.', null, ['center' => true, 'small' => true]);
        $body .= $this->pageBreakParagraph();

        $body .= $this->paragraph('Contents', 'Heading2');
        foreach ((array) ($book['table_of_contents'] ?? []) as $entry) {
            $n = (int) ($entry['number'] ?? 0);
            // Clickable contents: internal hyperlink to the chapter bookmark.
            $body .= '<w:p><w:pPr><w:ind w:firstLine="0"/></w:pPr><w:hyperlink w:anchor="chapter' . $n . '" w:history="1">'
                . '<w:r><w:rPr><w:color w:val="1F4E79"/><w:u w:val="single"/></w:rPr>'
                . '<w:t xml:space="preserve">' . $n . '. ' . $this->escape((string) ($entry['title'] ?? '')) . '</w:t></w:r>'
                . '</w:hyperlink></w:p>';
        }

        $figureCounter = 0;
        foreach ((array) ($book['chapters'] ?? []) as $chapter) {
            $chapterNumber = (int) ($chapter['number'] ?? 0);
            $headingText = 'Chapter ' . $chapterNumber . ': ' . (string) ($chapter['title'] ?? '');
            $bid = ++$this->bookmarkId;
            $body .= '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                . '<w:bookmarkStart w:id="' . $bid . '" w:name="chapter' . $chapterNumber . '"/>'
                . '<w:r><w:t xml:space="preserve">' . $this->escape($headingText) . '</w:t></w:r>'
                . '<w:bookmarkEnd w:id="' . $bid . '"/></w:p>';
            foreach ((array) ($chapter['blocks'] ?? []) as $index => $block) {
                $content = (string) ($block['content'] ?? '');
                if ($content === '' || ($index === 0 && ($block['kind'] ?? '') === 'heading')) {
                    continue; // the chapter heading is already rendered above
                }
                $body .= $this->paragraph($content);
            }
            $figureNumber = 0;
            foreach ($this->mediaByChapter[$chapterNumber] ?? [] as $item) {
                if (!empty($item['placeholder'])) {
                    continue; // AI images join the manuscript once actually generated
                }
                $label = 'Figure ' . $chapterNumber . '.' . (++$figureNumber);
                if (isset($item['svg'])) {
                    $body .= $this->figureDrawing($figureCounter++, (string) $item['svg'], $label);
                } elseif (isset($item['table']['columns'], $item['table']['rows'])) {
                    $body .= $this->tableXml($item['table']);
                }
                $body .= $this->paragraph(
                    $label . ' — ' . (string) ($item['title'] ?? '') . '. ' . (string) ($item['caption'] ?? ''),
                    null,
                    ['italic' => true, 'center' => true, 'small' => true],
                );
            }
        }

        $body .= $this->paragraph('About the Author', 'Heading1');
        $body .= $this->paragraph($author . ' writes practical, reader-first guides. If this book helped you, please consider leaving a review on Amazon — it is the best way to help other readers find it.');

        $sectPr = '<w:sectPr>'
            . '<w:pgSz w:w="' . self::PAGE_WIDTH . '" w:h="' . self::PAGE_HEIGHT . '"/>'
            . '<w:pgMar w:top="' . self::PAGE_MARGIN . '" w:right="' . self::PAGE_MARGIN . '" w:bottom="' . self::PAGE_MARGIN . '" w:left="' . self::PAGE_MARGIN . '" w:header="720" w:footer="720" w:gutter="0"/>'
            . '</w:sectPr>';

        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            . '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
            . ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
            . ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
            . '<w:body>' . $body . $sectPr . '</w:body></w:document>';
    }

    /**
     * One paragraph. Line breaks inside the text become soft breaks so
     * job-card blocks keep their line structure.
     *
     * @param array{italic?:bool, center?:bool, small?:bool} $format
     */
    private function paragraph(string $text, ?string $style = null, array $format = []): string
    {
        $pPr = '';
        $props = '';
        if ($style !== null) {
            $props .= '<w:pStyle w:val="' . $style . '"/>';
        }
        if (!empty($format['center'])) {
            $props .= '<w:jc w:val="center"/>';
        }
        if ($props !== '') {
            $pPr = '<w:pPr>' . $props . '</w:pPr>';
        }
        $rPr = '';
        if (!empty($format['italic'])) {
            $rPr .= '<w:i/>';
        }
        if (!empty($format['small'])) {
            $rPr .= '<w:sz w:val="20"/><w:szCs w:val="20"/>';
        }
        if ($rPr !== '') {
            $rPr = '<w:rPr>' . $rPr . '</w:rPr>';
        }
        $lines = preg_split('/\R/u', $text) ?: [$text];
        $runs = '';
        foreach ($lines as $index => $line) {
            if ($index > 0) {
                $runs .= '<w:r>' . $rPr . '<w:br/></w:r>';
            }
            if ($line !== '') {
                $runs .= '<w:r>' . $rPr . '<w:t xml:space="preserve">' . $this->escape($line) . '</w:t></w:r>';
            }
        }
        return '<w:p>' . $pPr . $runs . '</w:p>';
    }

    private function pageBreakParagraph(): string
    {
        return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>';
    }

    private function escape(string $value): string
    {
        return htmlspecialchars($value, ENT_XML1 | ENT_QUOTES, 'UTF-8');
    }
}
