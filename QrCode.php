<?php

declare(strict_types=1);

/**
 * QR Code encoder — pure PHP, no extensions beyond core.
 *
 * Scope: byte mode, error-correction level M, versions 1–10 (up to 213
 * bytes of data — far more than the companion URLs this app encodes),
 * mask pattern 0. Every part of the symbol is built per ISO/IEC 18004:
 * Reed–Solomon ECC over GF(256) with the 0x11D primitive polynomial,
 * block interleaving, BCH-protected format/version information, and the
 * standard zigzag placement. Output is a print-ready SVG.
 */
final class QrCode
{
    /** Total data codewords per version at ECC level M (versions 1–10). */
    private const DATA_CODEWORDS = [16, 28, 44, 64, 86, 108, 124, 154, 182, 216];

    /** ECC codewords per block, per version, at level M. */
    private const ECC_PER_BLOCK = [10, 16, 26, 18, 24, 16, 18, 22, 22, 26];

    /**
     * Block structure per version at level M: [count, dataCodewords] pairs.
     * @var array<int, array<int, array{int, int}>>
     */
    private const BLOCKS = [
        [[1, 16]],
        [[1, 28]],
        [[1, 44]],
        [[2, 32]],
        [[2, 43]],
        [[4, 27]],
        [[4, 31]],
        [[2, 38], [2, 39]],
        [[3, 36], [2, 37]],
        [[4, 43], [1, 44]],
    ];

    /** Alignment pattern center coordinates per version. */
    private const ALIGNMENT = [
        [], [6, 18], [6, 22], [6, 26], [6, 30],
        [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
    ];

    /**
     * Encode text as a QR symbol matrix of 0/1 ints (no quiet zone).
     *
     * @return array<int, array<int, int>>
     */
    public static function matrix(string $text): array
    {
        $bytes = array_values(unpack('C*', $text) ?: []);
        $version = self::pickVersion(count($bytes));
        $codewords = self::buildCodewords($bytes, $version);
        return self::buildMatrix($codewords, $version);
    }

    /** Render the QR as an SVG element with a 4-module quiet zone. */
    public static function svg(string $text, int $moduleSize = 4, string $label = ''): string
    {
        $matrix = self::matrix($text);
        $size = count($matrix);
        $quiet = 4;
        $total = ($size + 2 * $quiet) * $moduleSize;
        $svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' . $total . ' ' . $total . '" width="' . $total . '" height="' . $total . '" role="img" aria-label="'
            . htmlspecialchars($label !== '' ? $label : 'QR code: ' . $text, ENT_XML1 | ENT_QUOTES, 'UTF-8') . '" shape-rendering="crispEdges">';
        $svg .= '<rect width="' . $total . '" height="' . $total . '" fill="#ffffff"/>';
        $path = '';
        foreach ($matrix as $r => $row) {
            foreach ($row as $c => $module) {
                if ($module === 1) {
                    $x = ($c + $quiet) * $moduleSize;
                    $y = ($r + $quiet) * $moduleSize;
                    $path .= 'M' . $x . ' ' . $y . 'h' . $moduleSize . 'v' . $moduleSize . 'h-' . $moduleSize . 'z';
                }
            }
        }
        return $svg . '<path d="' . $path . '" fill="#000000"/></svg>';
    }

    private static function pickVersion(int $byteCount): int
    {
        for ($version = 1; $version <= 10; $version++) {
            $countBits = $version <= 9 ? 8 : 16;
            $bitsNeeded = 4 + $countBits + 8 * $byteCount;
            if ($bitsNeeded <= self::DATA_CODEWORDS[$version - 1] * 8) {
                return $version;
            }
        }
        throw new InvalidArgumentException('Text too long for a version-10 QR code (max 213 bytes at ECC M).');
    }

    /**
     * Data encoding, padding, Reed–Solomon ECC, and block interleaving.
     *
     * @param array<int, int> $bytes
     * @return array<int, int> Interleaved codewords.
     */
    private static function buildCodewords(array $bytes, int $version): array
    {
        $dataCapacity = self::DATA_CODEWORDS[$version - 1];
        $bits = '0100'; // byte mode
        $bits .= str_pad(decbin(count($bytes)), $version <= 9 ? 8 : 16, '0', STR_PAD_LEFT);
        foreach ($bytes as $byte) {
            $bits .= str_pad(decbin($byte), 8, '0', STR_PAD_LEFT);
        }
        $bits .= str_repeat('0', min(4, $dataCapacity * 8 - strlen($bits))); // terminator
        if (strlen($bits) % 8 !== 0) {
            $bits .= str_repeat('0', 8 - (strlen($bits) % 8));
        }
        $data = [];
        for ($i = 0; $i < strlen($bits); $i += 8) {
            $data[] = bindec(substr($bits, $i, 8));
        }
        $pad = [0xEC, 0x11];
        for ($i = 0; count($data) < $dataCapacity; $i++) {
            $data[] = $pad[$i % 2];
        }

        // Split into blocks, compute ECC per block.
        [$exp, $log] = self::galoisTables();
        $eccLen = self::ECC_PER_BLOCK[$version - 1];
        $generator = self::generatorPoly($eccLen, $exp, $log);
        $dataBlocks = [];
        $eccBlocks = [];
        $offset = 0;
        foreach (self::BLOCKS[$version - 1] as [$count, $blockLen]) {
            for ($b = 0; $b < $count; $b++) {
                $block = array_slice($data, $offset, $blockLen);
                $offset += $blockLen;
                $dataBlocks[] = $block;
                $eccBlocks[] = self::reedSolomon($block, $generator, $eccLen, $exp, $log);
            }
        }

        // Interleave data codewords, then ECC codewords.
        $interleaved = [];
        $maxData = max(array_map('count', $dataBlocks));
        for ($i = 0; $i < $maxData; $i++) {
            foreach ($dataBlocks as $block) {
                if (isset($block[$i])) {
                    $interleaved[] = $block[$i];
                }
            }
        }
        for ($i = 0; $i < $eccLen; $i++) {
            foreach ($eccBlocks as $block) {
                $interleaved[] = $block[$i];
            }
        }
        return $interleaved;
    }

    /** @return array{array<int, int>, array<int, int>} exp and log tables for GF(256). */
    private static function galoisTables(): array
    {
        $exp = array_fill(0, 512, 0);
        $log = array_fill(0, 256, 0);
        $x = 1;
        for ($i = 0; $i < 255; $i++) {
            $exp[$i] = $x;
            $log[$x] = $i;
            $x <<= 1;
            if ($x & 0x100) {
                $x ^= 0x11D;
            }
        }
        for ($i = 255; $i < 512; $i++) {
            $exp[$i] = $exp[$i - 255];
        }
        return [$exp, $log];
    }

    /** @return array<int, int> Generator polynomial coefficients (monic, degree $degree). */
    private static function generatorPoly(int $degree, array $exp, array $log): array
    {
        $poly = [1];
        for ($i = 0; $i < $degree; $i++) {
            $next = array_fill(0, count($poly) + 1, 0);
            foreach ($poly as $j => $coef) {
                $next[$j] ^= $coef === 0 ? 0 : $exp[($log[$coef] + $i) % 255];
                $next[$j + 1] ^= $coef;
            }
            $poly = $next;
        }
        return array_reverse($poly); // highest degree first
    }

    /** @return array<int, int> ECC codewords for one block. */
    private static function reedSolomon(array $block, array $generator, int $eccLen, array $exp, array $log): array
    {
        $remainder = array_merge($block, array_fill(0, $eccLen, 0));
        for ($i = 0; $i < count($block); $i++) {
            $factor = $remainder[$i];
            if ($factor === 0) {
                continue;
            }
            $logFactor = $log[$factor];
            for ($j = 1; $j < count($generator); $j++) {
                $remainder[$i + $j] ^= $generator[$j] === 0 ? 0 : $exp[($log[$generator[$j]] + $logFactor) % 255];
            }
        }
        return array_slice($remainder, count($block));
    }

    /**
     * @param array<int, int> $codewords
     * @return array<int, array<int, int>>
     */
    private static function buildMatrix(array $codewords, int $version): array
    {
        $size = 17 + 4 * $version;
        $matrix = array_fill(0, $size, array_fill(0, $size, -1)); // -1 = unset
        $isFunction = array_fill(0, $size, array_fill(0, $size, false));

        $setFunction = static function (int $r, int $c, int $v) use (&$matrix, &$isFunction, $size): void {
            if ($r >= 0 && $r < $size && $c >= 0 && $c < $size) {
                $matrix[$r][$c] = $v;
                $isFunction[$r][$c] = true;
            }
        };

        // Finder patterns + separators at three corners.
        foreach ([[0, 0], [0, $size - 7], [$size - 7, 0]] as [$fr, $fc]) {
            for ($r = -1; $r <= 7; $r++) {
                for ($c = -1; $c <= 7; $c++) {
                    $inFinder = $r >= 0 && $r <= 6 && $c >= 0 && $c <= 6;
                    // Rings: dark on the outer border and the center 3x3.
                    if ($inFinder) {
                        $on = ($r === 0 || $r === 6 || $c === 0 || $c === 6 || ($r >= 2 && $r <= 4 && $c >= 2 && $c <= 4)) ? 1 : 0;
                        $setFunction($fr + $r, $fc + $c, $on);
                    } else {
                        $setFunction($fr + $r, $fc + $c, 0); // separator
                    }
                }
            }
        }

        // Timing patterns.
        for ($i = 8; $i < $size - 8; $i++) {
            $bit = ($i % 2 === 0) ? 1 : 0;
            if (!$isFunction[6][$i]) {
                $setFunction(6, $i, $bit);
            }
            if (!$isFunction[$i][6]) {
                $setFunction($i, 6, $bit);
            }
        }

        // Alignment patterns: skip the three combinations that would
        // overlap the finder patterns; the rest may legally coincide
        // with the timing patterns.
        $centers = self::ALIGNMENT[$version - 1];
        $last = count($centers) - 1;
        foreach ($centers as $ri => $cr) {
            foreach ($centers as $ci => $cc) {
                if (($ri === 0 && $ci === 0) || ($ri === 0 && $ci === $last) || ($ri === $last && $ci === 0)) {
                    continue; // overlaps a finder
                }
                for ($r = -2; $r <= 2; $r++) {
                    for ($c = -2; $c <= 2; $c++) {
                        $on = (max(abs($r), abs($c)) !== 1) ? 1 : 0;
                        $setFunction($cr + $r, $cc + $c, $on);
                    }
                }
            }
        }

        // Dark module.
        $setFunction(4 * $version + 9, 8, 1);

        // Reserve format info areas (filled below).
        for ($i = 0; $i <= 8; $i++) {
            if (!$isFunction[8][$i]) {
                $setFunction(8, $i, 0);
            }
            if (!$isFunction[$i][8]) {
                $setFunction($i, 8, 0);
            }
        }
        for ($i = 0; $i < 8; $i++) {
            if (!$isFunction[8][$size - 1 - $i]) {
                $setFunction(8, $size - 1 - $i, 0);
            }
            if (!$isFunction[$size - 1 - $i][8]) {
                $setFunction($size - 1 - $i, 8, 0);
            }
        }

        // Version information for version >= 7.
        if ($version >= 7) {
            $versionBits = self::bchVersion($version);
            for ($i = 0; $i < 18; $i++) {
                $bit = ($versionBits >> $i) & 1;
                $setFunction((int) floor($i / 3), $size - 11 + ($i % 3), $bit);
                $setFunction($size - 11 + ($i % 3), (int) floor($i / 3), $bit);
            }
        }

        // Data placement: zigzag from bottom-right, mask 0 applied inline.
        $bitStream = '';
        foreach ($codewords as $cw) {
            $bitStream .= str_pad(decbin($cw), 8, '0', STR_PAD_LEFT);
        }
        $bitIndex = 0;
        $upward = true;
        for ($col = $size - 1; $col >= 1; $col -= 2) {
            if ($col === 6) {
                $col = 5; // skip the vertical timing column
            }
            for ($i = 0; $i < $size; $i++) {
                $r = $upward ? $size - 1 - $i : $i;
                foreach ([$col, $col - 1] as $c) {
                    if ($isFunction[$r][$c] || $matrix[$r][$c] !== -1) {
                        continue;
                    }
                    $bit = $bitIndex < strlen($bitStream) ? (int) $bitStream[$bitIndex] : 0;
                    $bitIndex++;
                    if ((($r + $c) % 2) === 0) { // mask pattern 0
                        $bit ^= 1;
                    }
                    $matrix[$r][$c] = $bit;
                }
            }
            $upward = !$upward;
        }

        // Format information: ECC level M (bits 00) with mask 0, BCH-protected.
        $formatBits = self::bchFormat(0b00000);
        for ($i = 0; $i < 15; $i++) {
            $bit = ($formatBits >> (14 - $i)) & 1;
            // First copy around the top-left finder.
            if ($i < 6) {
                $matrix[8][$i] = $bit;
            } elseif ($i < 8) {
                $matrix[8][$i + 1] = $bit;
            } elseif ($i === 8) {
                $matrix[7][8] = $bit;
            } else {
                $matrix[14 - $i][8] = $bit;
            }
            // Second copy split between the other two finders; the module
            // above the vertical arm stays the always-dark module.
            if ($i < 7) {
                $matrix[$size - 1 - $i][8] = $bit;
            } else {
                $matrix[8][$size - 15 + $i] = $bit;
            }
        }

        return $matrix;
    }

    /** 15-bit format information: 5 data bits + BCH(15,5) remainder, XOR-masked. */
    public static function bchFormat(int $data): int
    {
        $value = $data << 10;
        $g = 0b10100110111;
        for ($i = 14; $i >= 10; $i--) {
            if (($value >> $i) & 1) {
                $value ^= $g << ($i - 10);
            }
        }
        return (($data << 10) | $value) ^ 0b101010000010010;
    }

    /** 18-bit version information: 6 data bits + BCH(18,6) remainder. */
    public static function bchVersion(int $version): int
    {
        $value = $version << 12;
        $g = 0b1111100100101;
        for ($i = 17; $i >= 12; $i--) {
            if (($value >> $i) & 1) {
                $value ^= $g << ($i - 12);
            }
        }
        return ($version << 12) | $value;
    }
}
