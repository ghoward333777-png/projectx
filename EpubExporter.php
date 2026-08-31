<?php

declare(strict_types=1);

/**
 * EPUB Exporter
 *
 * Builds a native EPUB 3 package with PHP's ZipArchive — no libraries.
 * The archive follows the OCF/OPF specs: a stored (uncompressed)
 * `mimetype` as the first entry, `META-INF/container.xml`, an EPUB 3
 * package document with an EPUB 2 NCX fallback, an XHTML navigation
 * document, and one well-formed XHTML file per chapter with the
 * Illustration Studio figures embedded inline (SVG and tables).
 *
 * Identifiers are deterministic (derived from title + author) so the
 * same book always produces the same package.
 */
final class EpubExporter
{
    private const MODIFIED = '2026-01-01T00:00:00Z';

    /**
     * @param array<string, mixed> $book Output of generateBookFromTableOfContents().
     * @param array<string, mixed> $metadata Listing metadata (title, subtitle, author).
     * @param array<string, mixed>|null $media Output of IllustrationStudio::planBookMedia().
     */
    public function export(array $book, array $metadata, ?array $media = null): string
    {
        if (!class_exists(ZipArchive::class)) {
            throw new RuntimeException('The PHP zip extension is required for EPUB export.');
        }
        $parts = $this->buildParts($book, $metadata, $media);
        $path = tempnam(sys_get_temp_dir(), 'epub');
        if ($path === false) {
            throw new RuntimeException('Could not create a temporary file for the EPUB.');
        }
        $zip = new ZipArchive();
        if ($zip->open($path, ZipArchive::OVERWRITE) !== true) {
            throw new RuntimeException('Could not open the EPUB archive for writing.');
        }
        // The OCF spec requires `mimetype` first and uncompressed.
        $zip->addFromString('mimetype', 'application/epub+zip');
        $zip->setCompressionName('mimetype', ZipArchive::CM_STORE);
        foreach ($parts as $name => $content) {
            $zip->addFromString($name, $content);
        }
        $zip->close();
        $bytes = file_get_contents($path);
        unlink($path);
        if ($bytes === false) {
            throw new RuntimeException('Could not read the generated EPUB.');
        }
        return $bytes;
    }

    /**
     * All package parts except the mimetype, keyed by archive path.
     *
     * @return array<string, string>
     */
    public function buildParts(array $book, array $metadata, ?array $media = null): array
    {
        $e = static fn (string $v): string => htmlspecialchars($v, ENT_XML1 | ENT_QUOTES, 'UTF-8');
        $title = trim((string) ($metadata['title'] ?? 'Untitled')) ?: 'Untitled';
        $subtitle = trim((string) ($metadata['subtitle'] ?? ''));
        $author = trim((string) ($metadata['author'] ?? 'Independent Author')) ?: 'Independent Author';
        $uuid = $this->deterministicUuid($title . '|' . $author);
        $chapters = (array) ($book['chapters'] ?? []);

        $mediaByChapter = [];
        foreach ((array) ($media['chapters'] ?? []) as $mediaChapter) {
            $mediaByChapter[(int) $mediaChapter['number']] = (array) $mediaChapter['items'];
        }

        $parts = [];
        $parts['META-INF/container.xml'] = '<?xml version="1.0" encoding="UTF-8"?>'
            . '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            . '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
            . '</container>';

        $parts['OEBPS/style.css'] = 'body{font-family:Georgia,"Times New Roman",serif;line-height:1.5;margin:1em}'
            . "\n" . 'h1{text-align:center;margin:1.5em 0 1em;line-height:1.15}'
            . "\n" . 'h2{margin:1.2em 0 .5em}'
            . "\n" . 'p{margin:0 0 .4em;text-indent:1.5em}'
            . "\n" . 'p.noindent,figcaption{text-indent:0}'
            . "\n" . '.titlepage{text-align:center;margin-top:30%}'
            . "\n" . 'figure{margin:1.5em 0;page-break-inside:avoid;text-align:center}'
            . "\n" . 'figcaption{font-size:.85em;font-style:italic;margin-top:.4em}'
            . "\n" . 'table{border-collapse:collapse;width:100%;font-size:.85em}'
            . "\n" . 'th,td{border:1px solid #999;padding:.3em .5em;text-align:left;vertical-align:top}';

        $parts['OEBPS/title.xhtml'] = $this->xhtml($title, '<div class="titlepage"><h1>' . $e($title) . '</h1>'
            . ($subtitle !== '' ? '<p class="noindent"><em>' . $e($subtitle) . '</em></p>' : '')
            . '<p class="noindent">' . $e($author) . '</p>'
            . '<p class="noindent" style="font-size:.8em;margin-top:3em">Copyright &#169; ' . gmdate('Y') . ' ' . $e($author) . '. All rights reserved.</p></div>');

        $manifestItems = [];
        $spineItems = [];
        $navPoints = [];
        $navList = [];
        foreach ($chapters as $chapter) {
            $n = (int) ($chapter['number'] ?? 0);
            $chapterTitle = (string) ($chapter['title'] ?? '');
            $body = '<h1>Chapter ' . $n . ': ' . $e($chapterTitle) . '</h1>';
            foreach ((array) ($chapter['blocks'] ?? []) as $index => $block) {
                $content = (string) ($block['content'] ?? '');
                if ($content === '' || ($index === 0 && ($block['kind'] ?? '') === 'heading')) {
                    continue;
                }
                $isHeading = $index > 0 && mb_strlen(trim($content)) <= 60 && !str_contains($content, '. ')
                    && !str_ends_with(trim($content), '.') && !str_contains($content, "\n");
                if ($isHeading) {
                    $body .= '<h2>' . $e(trim($content)) . '</h2>';
                } else {
                    $body .= '<p>' . str_replace("\n", '<br/>', $e($content)) . '</p>';
                }
            }
            $hasSvg = false;
            $figureNumber = 0;
            foreach ($mediaByChapter[$n] ?? [] as $item) {
                if (!empty($item['placeholder'])) {
                    continue; // AI images join the eBook once actually generated
                }
                $figureNumber++;
                $body .= '<figure>';
                if (isset($item['svg'])) {
                    $body .= $item['svg'];
                    $hasSvg = true;
                } elseif (isset($item['table']['columns'], $item['table']['rows'])) {
                    $body .= '<table><thead><tr>';
                    foreach ($item['table']['columns'] as $column) {
                        $body .= '<th>' . $e((string) $column) . '</th>';
                    }
                    $body .= '</tr></thead><tbody>';
                    foreach ($item['table']['rows'] as $row) {
                        $body .= '<tr>';
                        foreach ($row as $cell) {
                            $body .= '<td>' . $e((string) $cell) . '</td>';
                        }
                        $body .= '</tr>';
                    }
                    $body .= '</tbody></table>';
                }
                $body .= '<figcaption>Figure ' . $n . '.' . $figureNumber . ' &#8212; ' . $e((string) ($item['title'] ?? '')) . '. ' . $e((string) ($item['caption'] ?? '')) . '</figcaption></figure>';
            }
            $file = 'chapter-' . $n . '.xhtml';
            $parts['OEBPS/' . $file] = $this->xhtml('Chapter ' . $n . ': ' . $chapterTitle, $body);
            $manifestItems[] = '<item id="ch' . $n . '" href="' . $file . '" media-type="application/xhtml+xml"' . ($hasSvg ? ' properties="svg"' : '') . '/>';
            $spineItems[] = '<itemref idref="ch' . $n . '"/>';
            $navList[] = '<li><a href="' . $file . '">' . $n . '. ' . $e($chapterTitle) . '</a></li>';
            $navPoints[] = '<navPoint id="np' . $n . '" playOrder="' . ($n + 1) . '"><navLabel><text>' . $e($chapterTitle) . '</text></navLabel><content src="' . $file . '"/></navPoint>';
        }

        $parts['OEBPS/about.xhtml'] = $this->xhtml('About the Author', '<h1>About the Author</h1>'
            . '<p class="noindent">' . $e($author) . ' writes practical, reader-first guides. If this book helped you, please consider leaving a review on Amazon &#8212; it is the best way to help other readers find it.</p>');

        $parts['OEBPS/nav.xhtml'] = '<?xml version="1.0" encoding="UTF-8"?>'
            . '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title>'
            . '<link rel="stylesheet" type="text/css" href="style.css"/></head><body>'
            . '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>'
            . '<li><a href="title.xhtml">' . $e($title) . '</a></li>'
            . implode('', $navList)
            . '<li><a href="about.xhtml">About the Author</a></li>'
            . '</ol></nav></body></html>';

        $parts['OEBPS/toc.ncx'] = '<?xml version="1.0" encoding="UTF-8"?>'
            . '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            . '<head><meta name="dtb:uid" content="urn:uuid:' . $uuid . '"/><meta name="dtb:depth" content="1"/>'
            . '<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>'
            . '<docTitle><text>' . $e($title) . '</text></docTitle><navMap>'
            . '<navPoint id="np0" playOrder="1"><navLabel><text>' . $e($title) . '</text></navLabel><content src="title.xhtml"/></navPoint>'
            . implode('', $navPoints)
            . '<navPoint id="npAbout" playOrder="' . (count($chapters) + 2) . '"><navLabel><text>About the Author</text></navLabel><content src="about.xhtml"/></navPoint>'
            . '</navMap></ncx>';

        $parts['OEBPS/content.opf'] = '<?xml version="1.0" encoding="UTF-8"?>'
            . '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang="en">'
            . '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            . '<dc:identifier id="pub-id">urn:uuid:' . $uuid . '</dc:identifier>'
            . '<dc:title>' . $e($title . ($subtitle !== '' ? ': ' . $subtitle : '')) . '</dc:title>'
            . '<dc:creator>' . $e($author) . '</dc:creator>'
            . '<dc:language>en</dc:language>'
            . '<meta property="dcterms:modified">' . self::MODIFIED . '</meta>'
            . '</metadata><manifest>'
            . '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            . '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            . '<item id="css" href="style.css" media-type="text/css"/>'
            . '<item id="titlepage" href="title.xhtml" media-type="application/xhtml+xml"/>'
            . implode('', $manifestItems)
            . '<item id="about" href="about.xhtml" media-type="application/xhtml+xml"/>'
            . '</manifest><spine toc="ncx">'
            . '<itemref idref="titlepage"/>'
            . implode('', $spineItems)
            . '<itemref idref="about"/>'
            . '</spine></package>';

        return $parts;
    }

    private function xhtml(string $title, string $body): string
    {
        return '<?xml version="1.0" encoding="UTF-8"?>'
            . '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>'
            . htmlspecialchars($title, ENT_XML1 | ENT_QUOTES, 'UTF-8')
            . '</title><link rel="stylesheet" type="text/css" href="style.css"/></head><body>'
            . $body . '</body></html>';
    }

    /** RFC 4122-shaped, deterministically derived from the book identity. */
    private function deterministicUuid(string $seed): string
    {
        $hash = md5('book-intelligence-studio:' . $seed);
        return substr($hash, 0, 8) . '-' . substr($hash, 8, 4) . '-4' . substr($hash, 13, 3)
            . '-8' . substr($hash, 17, 3) . '-' . substr($hash, 20, 12);
    }
}
