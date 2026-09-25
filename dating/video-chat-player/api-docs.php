<?php
declare(strict_types=1);

// Human-readable API reference generated from the same OpenAPI document the server serves.
require_once __DIR__ . '/lib/OpenApi.php';

header("Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'none'; img-src 'self' data:");
$scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
$base = $scheme . '://' . ($_SERVER['HTTP_HOST'] ?? 'localhost') . dirname((string) ($_SERVER['SCRIPT_NAME'] ?? '/api-docs.php')) . '/api.php';
$spec = OpenApi::spec($base);
$e = static fn (string $s): string => htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
$schemaName = static fn (array $s): string => isset($s['$ref']) ? basename((string) $s['$ref']) : ($s['type'] ?? 'object');
$pretty = static fn (mixed $v): string => (string) json_encode($v, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Watch Room API</title>
<link rel="stylesheet" href="assets/styles.css">
<link rel="stylesheet" href="assets/docs.css">
</head>
<body>
<main class="app docs">
    <header class="topbar">
        <h1 class="topbar__title">Watch Room API <span class="topbar__step">v<?= $e($spec['info']['version']) ?></span></h1>
        <nav class="docs__nav"><a href="index.php">Player</a> <a href="api.php/v1/openapi.json">openapi.json</a> <a href="API.md">API.md</a></nav>
    </header>
    <p class="docs__lead"><?= $e($spec['info']['summary']) ?></p>
    <pre class="docs__pre"><?= $e($spec['info']['description']) ?></pre>
    <p class="docs__lead">Base URL: <code><?= $e($base) ?></code> · REST paths hang off it as <code>api.php/v1/…</code> (or <code>api.php?route=/v1/…</code> where PATH_INFO is unavailable).</p>

    <h2 class="docs__h2">Quick start</h2>
<pre class="docs__pre">curl -X POST "<?= $e($base) ?>/v1/rooms" -H "Content-Type: application/json" \
     -d '{"name":"Bot","src":"https://www.youtube.com/watch?v=aqz-KE-bpKQ"}'
# → { "room": {"id":"quiet-otter-41"}, "memberId":"m_…", "hostToken":"…", "playlist":…, "state":… }

curl "<?= $e($base) ?>/v1/rooms/quiet-otter-41/messages?since=0" -H "Authorization: Bearer m_…"
curl -X PUT "<?= $e($base) ?>/v1/rooms/quiet-otter-41/state" -H "Authorization: Bearer m_…" \
     -H "Content-Type: application/json" -d '{"state":{"playing":true,"mediaTime":0,"baseRev":1}}'
curl -N "<?= $e($base) ?>/v1/rooms/quiet-otter-41/events" -H "Authorization: Bearer m_…"   # live stream</pre>

    <h2 class="docs__h2">Endpoints</h2>
    <?php foreach ($spec['paths'] as $path => $ops): ?>
        <?php foreach ($ops as $verb => $op): ?>
        <section class="ep" id="<?= $e($op['operationId']) ?>">
            <h3 class="ep__title"><span class="ep__verb ep__verb--<?= $e($verb) ?>"><?= $e(strtoupper($verb)) ?></span> <code><?= $e($path) ?></code></h3>
            <p class="ep__summary"><?= $e($op['summary']) ?><?php if (!empty($op['security'])): ?> <span class="ep__auth"><?= implode(' + ', array_map(static fn ($s) => implode(' + ', array_keys($s)) ?: 'none', $op['security'])) ?></span><?php endif; ?></p>
            <?php if (!empty($op['parameters'])): ?>
            <dl class="ep__params">
                <?php foreach ($op['parameters'] as $p): ?>
                <dt><code><?= $e($p['name']) ?></code> <span class="ep__in"><?= $e($p['in']) ?><?= !empty($p['required']) ? ', required' : '' ?></span></dt>
                <dd><?= $e((string) ($p['description'] ?? ($p['schema']['type'] ?? ''))) ?></dd>
                <?php endforeach; ?>
            </dl>
            <?php endif; ?>
            <?php if (isset($op['requestBody'])): $ref = $schemaName($op['requestBody']['content']['application/json']['schema']); ?>
            <details class="ep__schema"><summary>Request body: <code><?= $e($ref) ?></code></summary><pre class="docs__pre"><?= $e($pretty($spec['components']['schemas'][$ref] ?? [])) ?></pre></details>
            <?php endif; ?>
            <ul class="ep__responses">
                <?php foreach ($op['responses'] as $code => $r): $schema = $r['content']['application/json']['schema'] ?? null; ?>
                <li><code><?= $e((string) $code) ?></code> <?= $e($r['description']) ?><?php if ($schema): $ref = $schemaName($schema); ?> → <details class="ep__schema ep__schema--inline"><summary><code><?= $e($ref) ?></code></summary><pre class="docs__pre"><?= $e($pretty($spec['components']['schemas'][$ref] ?? [])) ?></pre></details><?php endif; ?></li>
                <?php endforeach; ?>
            </ul>
        </section>
        <?php endforeach; ?>
    <?php endforeach; ?>

    <h2 class="docs__h2">Webhook envelope</h2>
    <p class="docs__lead">Each delivery is a POST with <code>X-WatchRoom-Event</code> and <code>X-WatchRoom-Signature: sha256=&lt;hex HMAC-SHA256 of the raw body with the webhook secret&gt;</code>. Answer 2xx within 2 seconds; ten failures in a row remove the webhook.</p>
<pre class="docs__pre">{ "id": "evt_…", "event": "message", "roomId": "quiet-otter-41", "at": 1790280000000,
  "data": { "seq": 12, "kind": "chat", "name": "Ana", "text": "did you see that", "mediaTime": 134.2, … } }</pre>

    <h2 class="docs__h2">JavaScript SDK and embedding</h2>
    <p class="docs__lead">Browsers and Node: <code>import { WatchRoomClient } from './assets/sdk.js'</code>. Host pages: <code>&lt;script src="assets/embed.js"&gt;</code> then <code>WatchRoom.embed(el, { base, room, name })</code>. See <a href="API.md">API.md</a> for both.</p>
</main>
</body>
</html>
