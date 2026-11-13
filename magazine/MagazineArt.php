<?php

declare(strict_types=1);

/**
 * Department artwork: one bold poster-style cover per department, drawn as inline SVG.
 * No image files, no downloads, a few hundred bytes each, sharp at any size.
 */
final class MagazineArt
{
    public const INK = '#0e0f12';

    /** Background, main shape, accent: one trio per department, in masthead order. */
    public const PALETTE = [
        ['#ff4d2e', '#0e0f12', '#ffd23f'],
        ['#00c389', '#0e0f12', '#ffffff'],
        ['#ffd23f', '#0e0f12', '#ff4d2e'],
        ['#2f5bff', '#ffffff', '#ffd23f'],
        ['#ff7ac3', '#0e0f12', '#ffffff'],
        ['#0e0f12', '#00e0c6', '#ffd23f'],
        ['#00b7ff', '#0e0f12', '#ffffff'],
        ['#7b4dff', '#ffffff', '#00e0c6'],
        ['#ff9f1c', '#0e0f12', '#ffffff'],
        ['#ff2e7e', '#ffffff', '#ffd23f'],
        ['#00e0c6', '#0e0f12', '#2f5bff'],
        ['#0e0f12', '#ffd23f', '#00c389'],
        ['#2f5bff', '#ffd23f', '#ffffff'],
        ['#ffd23f', '#0e0f12', '#ffffff'],
        ['#00c389', '#ffffff', '#0e0f12'],
        ['#ff4d2e', '#ffffff', '#0e0f12'],
        ['#7b4dff', '#ffd23f', '#ffffff'],
        ['#00b7ff', '#ffffff', '#ff2e7e'],
        ['#ff2e7e', '#0e0f12', '#00e0c6'],
        ['#0e0f12', '#ff4d2e', '#ffd23f'],
    ];

    /** Motifs on a 400 x 250 canvas. {b} background, {f} main shape, {a} accent. */
    private const MOTIFS = [
        // 1 The Human Multiplier: two circles, and what they make together
        '<circle cx="160" cy="125" r="78" fill="{f}"/><circle cx="240" cy="125" r="78" fill="{a}"/><path d="M200 58A78 78 0 0 1 200 192A78 78 0 0 1 200 58Z" fill="#fff"/><path d="M184 109l32 32M216 109l-32 32" stroke="{f}" stroke-width="10" stroke-linecap="round"/>',
        // 2 Clean Intelligence: sun over clean water
        '<circle cx="292" cy="84" r="48" fill="{a}"/><path d="M0 168Q50 138 100 168T200 168T300 168T400 168V250H0Z" fill="{f}"/><path d="M0 206Q50 182 100 206T200 206T300 206T400 206V250H0Z" fill="{a}" fill-opacity=".3"/>',
        // 3 Pro-Human Defined: a person, plus
        '<circle cx="190" cy="92" r="38" fill="{f}"/><path d="M106 222A84 84 0 0 1 274 222Z" fill="{f}"/><circle cx="280" cy="78" r="30" fill="{a}"/><path d="M280 62v32M264 78h32" stroke="#fff" stroke-width="9" stroke-linecap="round"/>',
        // 4 Lean Compute: a small chip
        '<path d="M165 38v28M200 38v28M235 38v28M165 184v28M200 184v28M235 184v28M113 90h28M113 125h28M113 160h28M259 90h28M259 125h28M259 160h28" stroke="{f}" stroke-width="9" stroke-linecap="round"/><rect x="140" y="65" width="120" height="120" rx="12" fill="{f}"/><rect x="172" y="97" width="56" height="56" rx="6" fill="{a}"/>',
        // 5 Small Footprint: the same thing, smaller each time
        '<rect x="100" y="30" width="190" height="190" fill="{f}"/><rect x="100" y="95" width="125" height="125" fill="{a}"/><rect x="100" y="150" width="70" height="70" fill="{b}"/><rect x="100" y="188" width="32" height="32" fill="{f}"/>',
        // 6 At the Edge: work happening at the rim, not the centre
        '<path d="M200 125L285 125M200 125L200 40M200 125L115 125M200 125L200 210M200 125L260 65M200 125L140 185" stroke="{f}" stroke-width="3"/><circle cx="200" cy="125" r="85" fill="none" stroke="{f}" stroke-width="6"/><circle cx="200" cy="125" r="10" fill="{f}"/><circle cx="285" cy="125" r="15" fill="{a}"/><circle cx="200" cy="40" r="15" fill="{f}"/><circle cx="115" cy="125" r="15" fill="{a}"/><circle cx="200" cy="210" r="15" fill="{f}"/><circle cx="260" cy="65" r="15" fill="{a}"/><circle cx="140" cy="185" r="15" fill="{a}"/>',
        // 7 Ground Truth: on target, and checked
        '<circle cx="200" cy="125" r="92" fill="{f}"/><circle cx="200" cy="125" r="64" fill="{b}"/><circle cx="200" cy="125" r="36" fill="{f}"/><path d="M152 126l36 36 70-80" fill="none" stroke="{a}" stroke-width="17" stroke-linecap="round" stroke-linejoin="round"/>',
        // 8 Glass Box: a box you can see into
        '<rect x="170" y="42" width="120" height="120" fill="none" stroke="{f}" stroke-width="6"/><path d="M110 90L170 42M230 90L290 42M110 210L170 162M230 210L290 162" stroke="{f}" stroke-width="6"/><rect x="110" y="90" width="120" height="120" fill="{a}" fill-opacity=".45" stroke="{f}" stroke-width="6"/><circle cx="200" cy="126" r="14" fill="{f}"/>',
        // 9 The Written Word: lines of text and a cursor
        '<rect x="85" y="58" width="230" height="20" rx="6" fill="{f}"/><rect x="85" y="96" width="180" height="20" rx="6" fill="{f}"/><rect x="85" y="134" width="230" height="20" rx="6" fill="{f}"/><rect x="85" y="172" width="110" height="20" rx="6" fill="{f}"/><rect x="208" y="164" width="9" height="36" fill="{a}"/>',
        // 10 Synthetic Studio: a made frame, with a spark
        '<rect x="70" y="55" width="250" height="150" rx="16" fill="{f}"/><path d="M172 92v76l64-38Z" fill="{b}"/><path d="M322 18l7 22 22 7-22 7-7 22-7-22-22-7 22-7Z" fill="{a}"/><path d="M62 190l4 13 13 4-13 4-4 13-4-13-13-4 13-4Z" fill="{a}"/>',
        // 11 Pocket AI: the model in the phone
        '<rect x="148" y="28" width="104" height="194" rx="20" fill="{f}"/><rect x="159" y="50" width="82" height="140" rx="6" fill="{b}"/><circle cx="200" cy="120" r="24" fill="{a}"/><circle cx="200" cy="120" r="9" fill="{b}"/><circle cx="200" cy="206" r="6" fill="{b}"/>',
        // 12 The ROI Ledger: bars and the line through them
        '<rect x="88" y="160" width="42" height="52" fill="{f}"/><rect x="148" y="125" width="42" height="87" fill="{f}"/><rect x="208" y="90" width="42" height="122" fill="{f}"/><rect x="268" y="52" width="42" height="160" fill="{f}"/><path d="M109 140L169 104L229 70L289 30" fill="none" stroke="{a}" stroke-width="8" stroke-linecap="round"/><circle cx="289" cy="30" r="11" fill="{a}"/>',
        // 13 The Teachable Workforce: climbing a step at a time
        '<path d="M60 218H140V172H210V126H280V80H345V218Z" fill="{f}"/><circle cx="175" cy="150" r="22" fill="{a}"/>',
        // 14 Rules of the Road: the sign
        '<rect x="193" y="196" width="14" height="54" fill="{f}"/><path d="M200 24L294 118L200 212L106 118Z" fill="{f}"/><path d="M200 66L238 110H214V168H186V110H162Z" fill="{b}"/>',
        // 15 Trust and Safety: the shield
        '<path d="M200 28L288 58V124C288 176 246 208 200 226C154 208 112 176 112 124V58Z" fill="{f}"/><path d="M160 124l30 30 52-58" fill="none" stroke="{b}" stroke-width="17" stroke-linecap="round" stroke-linejoin="round"/>',
        // 16 Open Bench: open source
        '<path d="M150 68L94 125L150 182M250 68L306 125L250 182" fill="none" stroke="{f}" stroke-width="20" stroke-linecap="round" stroke-linejoin="round"/><path d="M218 56L182 194" stroke="{a}" stroke-width="18" stroke-linecap="round"/>',
        // 17 The Corner Office: a conversation
        '<rect x="72" y="46" width="180" height="100" rx="20" fill="{f}"/><path d="M112 140V182L156 140Z" fill="{f}"/><rect x="190" y="118" width="142" height="82" rx="18" fill="{a}"/><path d="M294 194V226L258 194Z" fill="{a}"/><circle cx="124" cy="96" r="9" fill="{b}"/><circle cx="162" cy="96" r="9" fill="{b}"/><circle cx="200" cy="96" r="9" fill="{b}"/>',
        // 18 Sector Watch: one sector pulled into focus
        '<circle cx="194" cy="131" r="88" fill="{f}"/><path d="M194 131V43A88 88 0 0 0 106 131Z" fill="#0e0f12"/><path d="M210 115V27A88 88 0 0 1 298 115Z" fill="{a}"/>',
        // 19 Agents at Work: a workflow, with a supervised last step
        '<path d="M128 125L168 70M128 125L168 180M232 70L272 125M232 180L272 125" stroke="{f}" stroke-width="6"/><rect x="58" y="98" width="72" height="54" rx="12" fill="{f}"/><rect x="164" y="43" width="72" height="54" rx="12" fill="{f}"/><rect x="164" y="153" width="72" height="54" rx="12" fill="{f}"/><rect x="270" y="98" width="72" height="54" rx="12" fill="{a}"/><path d="M291 126l10 10 20-22" fill="none" stroke="{f}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>',
        // 20 Buyer's Brief: the scorecard (pips are generated)
        '',
    ];

    private static function scorecardMotif(string $f, string $a): string
    {
        $svg = '';
        foreach ([[78, 5], [125, 3], [172, 4]] as [$y, $filled]) {
            $svg .= '<rect x="62" y="' . ($y - 9) . '" width="84" height="18" rx="9" fill="' . $f . '"/>';
            for ($i = 0; $i < 5; $i++) {
                $x = 182 + $i * 38;
                $svg .= $i < $filled
                    ? '<circle cx="' . $x . '" cy="' . $y . '" r="13" fill="' . $a . '"/>'
                    : '<circle cx="' . $x . '" cy="' . $y . '" r="11" fill="none" stroke="' . $a . '" stroke-width="4"/>';
            }
        }
        return $svg;
    }

    /** Inline SVG cover for department $number (1-20). Decorative unless a label is given. */
    public static function cover(int $number, string $label = ''): string
    {
        $i = max(1, min(20, $number)) - 1;
        [$b, $f, $a] = self::PALETTE[$i];
        $motif = $i === 19 ? self::scorecardMotif($f, $a) : str_replace(['{b}', '{f}', '{a}'], [$b, $f, $a], self::MOTIFS[$i]);
        $access = $label !== ''
            ? ' role="img" aria-label="' . htmlspecialchars($label, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . '"'
            : ' aria-hidden="true"';
        return '<svg class="art" viewBox="0 0 400 250" preserveAspectRatio="xMidYMid slice"' . $access . '>'
            . '<rect width="400" height="250" fill="' . $b . '"/>' . $motif
            . '<text x="20" y="38" font-family="Arial Black, Arial, Helvetica, sans-serif" font-weight="900" font-size="22" fill="' . $f . '">' . sprintf('%02d', $i + 1) . '</text></svg>';
    }

    /** The MINDATION mark: an M with a signal dot. */
    public static function mark(): string
    {
        return '<svg class="mark" viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="9" fill="#0e0f12"/>'
            . '<path d="M9 29V11L18 23L27 11V29" fill="none" stroke="#fff" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"/>'
            . '<circle cx="33" cy="28.5" r="3.2" fill="#ff4d2e"/></svg>';
    }
}
