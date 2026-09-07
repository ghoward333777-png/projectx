<?php

declare(strict_types=1);

/**
 * Manuscript Hygiene
 *
 * Text that arrives from an AI writer, a paste, or a word processor carries
 * junk that has no business in a printed book: composed vs. decomposed
 * accents, zero-width characters, non-breaking spaces, stray tabs, CRLF line
 * endings, trailing spaces, and runs of blank lines. Left in place they break
 * DOCX/EPUB validation, confuse KDP's converters, and show up as gaps and
 * boxes on a Kindle page.
 *
 * This is ordinary manuscript preparation — the cleanup step every publishing
 * toolchain runs before typesetting. It is deterministic: the same input
 * always produces the same output.
 */
final class ManuscriptHygiene
{
    /** Characters that must never survive into a manuscript. */
    private const INVISIBLE = [
        "\u{200B}", // zero-width space
        "\u{200C}", // zero-width non-joiner
        "\u{200D}", // zero-width joiner
        "\u{2060}", // word joiner
        "\u{FEFF}", // byte-order mark / zero-width no-break space
        "\u{00AD}", // soft hyphen
        "\u{180E}", // Mongolian vowel separator
    ];

    /** Exotic spaces that should read as an ordinary space. */
    private const SPACES = [
        "\u{00A0}", // no-break space
        "\u{1680}", "\u{2000}", "\u{2001}", "\u{2002}", "\u{2003}", "\u{2004}",
        "\u{2005}", "\u{2006}", "\u{2007}", "\u{2008}", "\u{2009}", "\u{200A}",
        "\u{202F}", "\u{205F}", "\u{3000}",
    ];

    /**
     * Clean a whole chapter or manuscript: normalize, strip the invisible,
     * regularize spacing, and keep paragraph breaks intact.
     */
    public static function clean(string $text): string
    {
        $text = self::normalize($text);
        $text = str_replace(self::INVISIBLE, '', $text);
        $text = str_replace(self::SPACES, ' ', $text);
        // One line-ending convention.
        $text = (string) preg_replace('/\r\n?/', "\n", $text);
        // Tabs read as spaces; runs of spaces collapse to one.
        $text = str_replace("\t", ' ', $text);
        $text = (string) preg_replace('/ {2,}/', ' ', $text);
        // No trailing or leading spaces on any line.
        $text = (string) preg_replace('/[ ]+$/m', '', $text);
        $text = (string) preg_replace('/^[ ]+/m', '', $text);
        // A blank line separates paragraphs; never more than one.
        $text = (string) preg_replace('/\n{3,}/', "\n\n", $text);
        return trim($text);
    }

    /** Clean a single line (an outline row, a title, a caption). */
    public static function cleanLine(string $text): string
    {
        return trim((string) preg_replace('/\s+/u', ' ', self::clean($text)));
    }

    /**
     * Unicode NFC normalization when the intl extension is present. The app
     * is dependency-free by design, so its absence must not be fatal — the
     * rest of the cleanup still runs.
     */
    public static function normalize(string $text): string
    {
        if (class_exists('Normalizer')) {
            $normalized = \Normalizer::normalize($text, \Normalizer::FORM_C);
            if (is_string($normalized)) {
                return $normalized;
            }
        }
        return $text;
    }

    /** True when the text carries nothing this class would strip. */
    public static function isClean(string $text): bool
    {
        return self::clean($text) === trim($text);
    }
}
