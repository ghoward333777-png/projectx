<?php

declare(strict_types=1);

/**
 * Safe article markup. Everything is HTML-escaped first; only this small grammar is rendered:
 *
 *   ## Heading            > Quote            - list item
 *   **bold**  *italic*  `code`  [text](https://link)
 *   A YouTube link alone on a line becomes an embedded player.
 *   [scorecard: Product]
 *   Criterion: 4 | optional reasoning
 *   [/scorecard]
 */
final class MagazineMarkup
{
    public static function e(string $s): string
    {
        return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }

    /** Extract the 11-character video id from any common YouTube URL form, or '' if it is not one. */
    public static function youtubeId(string $url): string
    {
        $url = trim($url);
        if (preg_match('~^[A-Za-z0-9_-]{11}$~', $url)) {
            return $url;
        }
        $pattern = '~^(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?(?:[^\s#]*&)?v=|embed/|shorts/|live/|v/)|youtu\.be/|youtube-nocookie\.com/embed/)([A-Za-z0-9_-]{11})(?:[?&#/][^\s]*)?$~i';
        return preg_match($pattern, $url, $m) ? $m[1] : '';
    }

    /** Privacy-enhanced player: no cookies are set until the reader presses play. */
    public static function youtubeEmbed(string $id): string
    {
        if (!preg_match('~^[A-Za-z0-9_-]{11}$~', $id)) {
            return '';
        }
        return '<div class="video"><iframe src="https://www.youtube-nocookie.com/embed/' . $id . '" title="YouTube video" loading="lazy"'
            . ' allow="accelerometer; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen'
            . ' referrerpolicy="strict-origin-when-cross-origin"></iframe></div>';
    }

    private static function inline(string $text): string
    {
        $out = self::e($text);
        $out = (string) preg_replace('~`([^`]+)`~', '<code>$1</code>', $out);
        $out = (string) preg_replace('~\*\*(.+?)\*\*~', '<strong>$1</strong>', $out);
        $out = (string) preg_replace('~(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])~', '<em>$1</em>', $out);
        return (string) preg_replace_callback(
            '~\[([^\]]+)\]\((https?://[^\s)]+)\)~',
            static fn ($m) => '<a href="' . $m[2] . '" rel="noopener">' . $m[1] . '</a>',
            $out
        );
    }

    /** @param array<int, string> $rows */
    private static function scorecard(string $title, array $rows): string
    {
        $html = '<figure class="scorecard"><figcaption>Scorecard: ' . self::e($title) . '</figcaption><table>';
        $total = 0;
        $count = 0;
        foreach ($rows as $row) {
            if (!preg_match('~^(.+?):\s*([0-5])\s*(?:\|\s*(.*))?$~', trim($row), $m)) {
                continue;
            }
            $score = (int) $m[2];
            $total += $score;
            $count++;
            $html .= '<tr><th scope="row">' . self::e(trim($m[1])) . '</th>'
                . '<td class="pips" aria-label="' . $score . ' out of 5">' . str_repeat('<i class="on"></i>', $score) . str_repeat('<i></i>', 5 - $score) . '</td>'
                . '<td class="num">' . $score . '/5</td>'
                . '<td class="why">' . self::inline($m[3] ?? '') . '</td></tr>';
        }
        if ($count > 0) {
            $html .= '<tr class="total"><th scope="row">Overall</th><td></td><td class="num">' . $total . '/' . ($count * 5) . '</td><td></td></tr>';
        }
        return $html . '</table></figure>';
    }

    public static function render(string $source): string
    {
        $blocks = preg_split("~\n\s*\n~", trim(str_replace(["\r\n", "\r"], "\n", $source))) ?: [];
        $html = [];
        foreach ($blocks as $block) {
            $lines = array_values(array_filter(array_map('trim', explode("\n", $block)), static fn ($l) => $l !== ''));
            if ($lines === []) {
                continue;
            }
            $first = $lines[0];
            if (count($lines) === 1 && ($id = self::youtubeId($first)) !== '' && strlen($first) > 11) {
                $html[] = self::youtubeEmbed($id);
            } elseif (preg_match('~^\[scorecard:\s*(.+?)\]$~i', $first, $m)) {
                $html[] = self::scorecard($m[1], array_filter(array_slice($lines, 1), static fn ($l) => strcasecmp($l, '[/scorecard]') !== 0));
            } elseif (preg_match('~^(#{2,3})\s+(.+)$~', $first, $m) && count($lines) === 1) {
                $tag = strlen($m[1]) === 2 ? 'h2' : 'h3';
                $html[] = "<{$tag}>" . self::inline($m[2]) . "</{$tag}>";
            } elseif (count(preg_grep('~^[-*]\s+~', $lines)) === count($lines)) {
                $html[] = '<ul>' . implode('', array_map(static fn ($l) => '<li>' . self::inline((string) preg_replace('~^[-*]\s+~', '', $l)) . '</li>', $lines)) . '</ul>';
            } elseif (count(preg_grep('~^>\s?~', $lines)) === count($lines)) {
                $html[] = '<blockquote><p>' . self::inline(implode(' ', array_map(static fn ($l) => (string) preg_replace('~^>\s?~', '', $l), $lines))) . '</p></blockquote>';
            } else {
                $html[] = '<p>' . implode('<br>', array_map([self::class, 'inline'], $lines)) . '</p>';
            }
        }
        return implode("\n", $html);
    }

    /** Plain-text excerpt for cards, feeds, and share previews. */
    public static function excerpt(string $source, int $length = 180): string
    {
        $text = (string) preg_replace('~\[scorecard:.*?\[/scorecard\]~is', ' ', $source);
        $text = (string) preg_replace('~^\s*(?:#{2,3}|>|[-*])\s+~m', '', $text);
        $text = (string) preg_replace('~\[([^\]]+)\]\(https?://[^\s)]+\)~', '$1', $text);
        $text = trim((string) preg_replace('~\s+~', ' ', str_replace(['**', '`'], '', $text)));
        if (mb_strlen($text) <= $length) {
            return $text;
        }
        return rtrim((string) preg_replace('~\s+\S*$~u', '', mb_substr($text, 0, $length)), ' ,;:') . '…';
    }
}
