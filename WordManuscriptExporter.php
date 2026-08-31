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

    /**
     * Render the manuscript as .docx bytes.
     *
     * @param array<string, mixed> $book Output of generateBookFromTableOfContents().
     * @param array<string, mixed> $metadata Listing metadata (title, subtitle, author).
     */
    public function export(array $book, array $metadata): string
    {
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
        $zip->addFromString('[Content_Types].xml', $this->contentTypesXml());
        $zip->addFromString('_rels/.rels', $this->packageRelsXml());
        $zip->addFromString('word/_rels/document.xml.rels', $this->documentRelsXml());
        $zip->addFromString('word/styles.xml', $this->stylesXml());
        $zip->addFromString('word/document.xml', $this->documentXml($book, $metadata));
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
        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            . '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            . '</Relationships>';
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
            $body .= $this->paragraph(((int) ($entry['number'] ?? 0)) . '. ' . (string) ($entry['title'] ?? ''));
        }

        foreach ((array) ($book['chapters'] ?? []) as $chapter) {
            $body .= $this->paragraph('Chapter ' . (int) ($chapter['number'] ?? 0) . ': ' . (string) ($chapter['title'] ?? ''), 'Heading1');
            foreach ((array) ($chapter['blocks'] ?? []) as $index => $block) {
                $content = (string) ($block['content'] ?? '');
                if ($content === '' || ($index === 0 && ($block['kind'] ?? '') === 'heading')) {
                    continue; // the chapter heading is already rendered above
                }
                $body .= $this->paragraph($content);
            }
        }

        $body .= $this->paragraph('About the Author', 'Heading1');
        $body .= $this->paragraph($author . ' writes practical, reader-first guides. If this book helped you, please consider leaving a review on Amazon — it is the best way to help other readers find it.');

        $sectPr = '<w:sectPr>'
            . '<w:pgSz w:w="' . self::PAGE_WIDTH . '" w:h="' . self::PAGE_HEIGHT . '"/>'
            . '<w:pgMar w:top="' . self::PAGE_MARGIN . '" w:right="' . self::PAGE_MARGIN . '" w:bottom="' . self::PAGE_MARGIN . '" w:left="' . self::PAGE_MARGIN . '" w:header="720" w:footer="720" w:gutter="0"/>'
            . '</w:sectPr>';

        return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            . '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
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
