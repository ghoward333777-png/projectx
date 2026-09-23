<?php
/**
 * Single sign-on token helper shared with the MediaMarketplace server.
 * Pure PHP: no WordPress dependencies so it can be unit tested.
 *
 * Token = base64url(json) . "." . base64url(HMAC-SHA256(json, secret)).
 * The server verifies the signature over the raw JSON bytes, so the claim
 * order below is the canonical one and must not change.
 */

if (!function_exists('mms_bridge_sign_token')) {
    /**
     * @param array{sub:string,email:string,name:string,host:string,exp:int} $claims
     */
    function mms_bridge_sign_token(array $claims, string $secret): string
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
            throw new RuntimeException('Could not encode SSO claims');
        }
        $mac = hash_hmac('sha256', $json, $secret, true);
        return mms_bridge_b64url($json) . '.' . mms_bridge_b64url($mac);
    }

    function mms_bridge_b64url(string $raw): string
    {
        return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
    }
}
