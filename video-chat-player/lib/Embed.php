<?php
declare(strict_types=1);

/** The machine-readable description of how to embed this deployment (embed.php?format=json). */
final class Embed
{
    public static function describe(string $base, string $room, array $config): array
    {
        $embedUrl = $base . 'embed.php' . ($room !== '' ? '?room=' . rawurlencode($room) : '');
        return [
            'name' => 'Watch Room',
            'version' => '1.0.0',
            'base' => $base,
            'embedUrl' => $embedUrl,
            'iframe' => '<iframe src="' . htmlspecialchars($embedUrl, ENT_QUOTES, 'UTF-8') . '" allow="autoplay; fullscreen; clipboard-write" allowfullscreen style="border:0;width:100%;aspect-ratio:16/9"></iframe>',
            'script' => $base . 'assets/embed.js',
            'sdk' => $base . 'assets/sdk.js',
            'api' => $base . 'api.php/v1',
            'openapi' => $base . 'api.php/v1/openapi.json',
            'oembed' => $base . 'api.php/v1/oembed?url=' . rawurlencode($embedUrl),
            'createRoom' => ['method' => 'POST', 'url' => $base . 'api.php/v1/rooms', 'body' => ['name' => 'Host', 'src' => 'https://youtu.be/…']],
            'parameters' => ['room' => 'room id to join', 'src' => 'first item for a new room (YouTube video/playlist link, https .mp4/.webm, media/<file>)', 'name' => 'display name', 'chat' => '0 hides the chat', 'autoplay' => '0 waits for a tap', 'idle' => 'overlay hide delay in ms (1500–10000)', 'compact' => '0 shows the full page with the playlist rail'],
            'allowedEmbedders' => $config['cors_origins'] === [] ? ['same origin only'] : $config['cors_origins'],
        ];
    }
}
