<?php
declare(strict_types=1);

/** String helpers that work with or without ext-mbstring. */
final class Text
{
    public static function cut(string $s, int $max): string
    {
        if (function_exists('mb_substr')) {
            return mb_substr($s, 0, $max);
        }
        if (strlen($s) <= $max) {
            return $s;
        }
        // Cut on a UTF-8 boundary without mbstring.
        $out = substr($s, 0, $max);
        while ($out !== '' && !preg_match('//u', $out)) {
            $out = substr($out, 0, -1);
        }
        return $out;
    }
}
