<?php

namespace Joomla\Plugin\System\Mmsbridge\Helper;

/**
 * Single sign-on token helper shared with the MediaMarketplace server.
 * No Joomla dependencies so it can be unit tested on its own.
 *
 * Token = base64url(json) . "." . base64url(HMAC-SHA256(json, secret)).
 * The claim order is canonical and must not change.
 */
final class TokenHelper
{
    /**
     * @param array{sub:string,email:string,name:string,host:string,exp:int} $claims
     */
    public static function sign(array $claims, string $secret): string
    {
        $ordered = [
            'sub'   => (string) $claims['sub'],
            'email' => (string) $claims['email'],
            'name'  => (string) $claims['name'],
            'host'  => (string) $claims['host'],
            'exp'   => (int) $claims['exp'],
        ];
        $json = json_encode($ordered, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($json === false) {
            throw new \RuntimeException('Could not encode SSO claims');
        }
        $mac = hash_hmac('sha256', $json, $secret, true);
        return self::b64url($json) . '.' . self::b64url($mac);
    }

    public static function b64url(string $raw): string
    {
        return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
    }
}
