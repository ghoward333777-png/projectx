<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

/**
 * Advanced Watch Party — a separate product from the couple's Watch
 * Party. Standalone rooms with modes (Couples, Friends, Family,
 * Creator) and themes, BYOYA playback (each viewer signs into their own
 * YouTube account, so YouTube Premium plays ad-free on their own
 * subscription — the platform sells the ROOM, never the movie), split
 * payments that unlock the room only when every required participant
 * has paid, a server-authoritative sync timeline with a passable
 * remote, reaction bursts on an emotion timeline, highlights, room
 * chat, and a post-movie recap.
 */

$engine = new SlowDatingEngine();
$error = null;
$notice = null;
$userId = null;

if (isset($_SESSION['sd_member_token'])) {
    $auth = $engine->authenticate((string) $_SESSION['sd_member_token']);
    if ($auth !== null && $auth[1] === 'member') {
        $userId = $auth[0];
    }
}

$roomId = (string) ($_GET['room'] ?? ($_POST['room_id'] ?? ''));

// Poll endpoints: room state as JSON, chat as an HTML fragment. Both are
// swapped into the page over fetch() — the player is never reloaded.
if ($userId !== null && (string) ($_GET['fragment'] ?? '') !== '') {
    header('Cache-Control: private, no-store');
    try {
        if ($_GET['fragment'] === 'state') {
            header('Content-Type: application/json');
            echo json_encode($engine->advancedRoomView($roomId, $userId));
        } else {
            header('Content-Type: text/html; charset=utf-8');
            foreach ($engine->advancedMessages($roomId, $userId) as $message) {
                $mine = $message['user_id'] === $userId;
                $sender = $mine ? 'You' : (string) ($engine->profile((string) $message['user_id'])['display_name'] ?: $message['user_id']);
                echo '<div class="message' . ($mine ? ' me' : '') . '"><span>' . sd_e((string) $message['text']) . '</span>'
                    . '<div class="message-meta"><span>' . sd_e($sender) . '</span><span>' . sd_e(gmdate('M j, H:i', (int) $message['at'])) . '</span></div></div>';
            }
        }
    } catch (Throwable) {
        echo $_GET['fragment'] === 'state' ? '{}' : '';
    }
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && $userId !== null) {
    $ajax = isset($_POST['ajax']);
    try {
        $result = null;
        switch ((string) ($_POST['action'] ?? '')) {
            case 'create':
                $view = $engine->createAdvancedRoom(
                    $userId,
                    (string) ($_POST['mode'] ?? ''),
                    (string) ($_POST['theme'] ?? ''),
                    (string) ($_POST['video_url'] ?? ''),
                    (float) ($_POST['price_per_user'] ?? 0),
                    (int) ($_POST['required_participants'] ?? 2),
                );
                header('Location: advanced-watch-party.php?room=' . urlencode((string) $view['room_id']));
                exit;
            case 'join':
                $view = $engine->joinAdvancedRoom((string) ($_POST['invite_code'] ?? ''), $userId);
                header('Location: advanced-watch-party.php?room=' . urlencode((string) $view['room_id']));
                exit;
            case 'pay':
                $view = $engine->payAdvancedShare($roomId, $userId);
                $notice = $view['unlocked']
                    ? 'Your share is paid — every required share has cleared, the room is unlocked. Enjoy the movie!'
                    : 'Your share is paid. The room unlocks when ' . (int) $view['required_participants'] . ' shares have cleared (' . (int) $view['paid_count'] . ' so far).';
                break;
            case 'sync':
                $result = $engine->setAdvancedSync($roomId, $userId, [
                    'position' => (float) ($_POST['position'] ?? 0),
                    'playing' => ($_POST['playing'] ?? '') === '1',
                ]);
                break;
            case 'remote':
                $result = $engine->passAdvancedRemote($roomId, $userId, (string) ($_POST['user_id'] ?? ''));
                $notice = 'The remote was passed.';
                break;
            case 'react':
                $result = $engine->addAdvancedReaction($roomId, $userId, (string) ($_POST['type'] ?? ''), (float) ($_POST['t'] ?? 0));
                break;
            case 'highlight':
                $result = $engine->markAdvancedHighlight($roomId, $userId, (float) ($_POST['t'] ?? 0), (string) ($_POST['note'] ?? ''));
                $notice = 'Moment saved to the shared timeline.';
                break;
            case 'room_chat':
                $result = $engine->sendAdvancedMessage($roomId, $userId, (string) ($_POST['text'] ?? ''));
                break;
            case 'end':
                $engine->endAdvancedRoom($roomId, $userId);
                $notice = 'Session ended — the recap is below.';
                break;
        }
        if ($ajax) {
            header('Content-Type: application/json');
            echo json_encode($result ?? ['status' => 'ok']);
            exit;
        }
    } catch (Throwable $exception) {
        if ($ajax) {
            http_response_code(422);
            header('Content-Type: text/plain; charset=utf-8');
            echo $exception->getMessage();
            exit;
        }
        $error = $exception->getMessage();
    }
}

sd_page_open('Advanced Watch Party', 'SlowDating · rooms, split payments, shared controls');
sd_flash($error, $notice);

if ($userId === null) {
    ?>
    <section>
        <h2>Watch parties with modes, split payments, and shared controls</h2>
        <p>A separate product from the couple's Watch Party: paid rooms in Couples, Friends, Family, or Creator
            mode. Each viewer watches on their <strong style="color:#f3eef6">own YouTube account</strong> (YouTube
            Premium plays ad-free on their own subscription) while the room keeps everyone in lock-step. The
            session fee splits between participants — you pay for the room, never the movie.
            <a href="index.php">Sign in or create a free account</a> to open a room.</p>
    </section>
    <?php
    sd_page_close();
    exit;
}

$view = null;
if ($roomId !== '') {
    try {
        $view = $engine->advancedRoomView($roomId, $userId);
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
        sd_flash($error, null);
    }
}

if ($view === null) {
    // ---- Lobby: create a room, join by invite code, your rooms. ----
    ?>
    <section>
        <h2>Open an Advanced Watch Party room</h2>
        <p>Pick a mode and a theme, paste any YouTube source, set the session price — the fee splits evenly and
            the room unlocks when every required share is paid. Everyone watches on their own YouTube account
            (Premium plays ad-free); the room keeps you in lock-step.</p>
        <form method="post">
            <input type="hidden" name="action" value="create">
            <div class="grid">
                <div><label>Mode</label>
                    <select name="mode" id="awp-mode">
                        <?php foreach (SlowDatingEngine::ADV_MODES as $slug => $meta): ?>
                            <option value="<?= sd_e($slug) ?>"><?= sd_e((string) $meta['label']) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div><label>Theme</label>
                    <select name="theme" id="awp-theme">
                        <?php foreach (SlowDatingEngine::ADV_MODES['couples']['themes'] as $theme): ?>
                            <option value="<?= sd_e($theme) ?>"><?= sd_e(ucfirst($theme)) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div><label>Price per person ($0 = free room)</label>
                    <input name="price_per_user" type="number" min="0" max="<?= (int) SlowDatingEngine::ADV_MAX_PRICE ?>" step="0.50" value="2.00"></div>
                <div><label>Required participants</label>
                    <input name="required_participants" type="number" min="2" max="<?= (int) SlowDatingEngine::ADV_MAX_PARTICIPANTS ?>" value="2"></div>
            </div>
            <label>YouTube source (video, playlist, or embed link)</label>
            <input name="video_url" placeholder="https://www.youtube.com/watch?v=..." required>
            <button type="submit">Create the room</button>
        </form>
        <script>
            (function () {
                var themes = <?= json_encode(array_map(static fn (array $m): array => $m['themes'], SlowDatingEngine::ADV_MODES)) ?>;
                var mode = document.getElementById('awp-mode');
                var theme = document.getElementById('awp-theme');
                mode.addEventListener('change', function () {
                    theme.innerHTML = themes[mode.value].map(function (t) {
                        return '<option value="' + t + '">' + t.charAt(0).toUpperCase() + t.slice(1) + '</option>';
                    }).join('');
                });
            })();
        </script>
    </section>
    <section>
        <h2>Join with an invite code</h2>
        <form method="post" style="background:none;border:0;padding:0;margin:0">
            <input type="hidden" name="action" value="join">
            <label>Invite code</label>
            <input name="invite_code" placeholder="A1B2C3" style="max-width:220px;text-transform:uppercase">
            <button type="submit">Join the room</button>
        </form>
    </section>
    <?php $mine = $engine->advancedRoomsFor($userId); ?>
    <?php if ($mine !== []): ?>
    <section>
        <h2>Your rooms</h2>
        <div class="grid">
            <?php foreach ($mine as $room): ?>
                <div class="card">
                    <strong><?= sd_e((string) SlowDatingEngine::ADV_MODES[$room['mode']]['label']) ?> · <?= sd_e(ucfirst((string) $room['theme'])) ?></strong>
                    <p style="margin:6px 0"><span class="pill"><?= sd_e((string) $room['status']) ?></span>
                        <span class="pill">invite <?= sd_e((string) $room['invite_code']) ?></span>
                        <?php if ($room['price_per_user'] > 0): ?><span class="pill">$<?= number_format((float) $room['price_per_user'], 2) ?>/person</span><?php endif; ?></p>
                    <a href="?room=<?= urlencode((string) $room['room_id']) ?>" style="color:#ffb8d2">Open the room →</a>
                </div>
            <?php endforeach; ?>
        </div>
    </section>
    <?php endif; ?>
    <?php
    sd_page_close();
    exit;
}

// ---- Inside a room. ----
$accents = ['couples' => '#ff9cc0', 'friends' => '#7fdede', 'family' => '#ffd97a', 'creator' => '#b49cff'];
$accent = $accents[(string) $view['mode']] ?? '#ff9cc0';
$isOwner = $view['owner_user_id'] === $userId;
$controller = (string) ($view['sync']['controller_user_id'] ?? $view['owner_user_id']);
$myPayment = 'n/a';
foreach ($view['participants'] as $person) {
    if ($person['user_id'] === $userId) {
        $myPayment = (string) $person['payment'];
    }
}
$recap = $view['ended'] ? $engine->advancedRecap($roomId, $userId) : null;
?>
<style>
    #awp .video-wrapper { position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; border-radius: 12px; border: 1px solid <?= $accent ?>; background: #020617; }
    #awp .video-wrapper iframe { position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0; }
    #awp .burst { position: absolute; font-size: 42px; animation: awp-rise 1.6s ease-out forwards; pointer-events: none; z-index: 5; }
    @keyframes awp-rise { from { opacity: 1; transform: translateY(0) scale(1); } to { opacity: 0; transform: translateY(-120px) scale(1.6); } }
    #awp .messages { max-height: 300px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
    #awp .message { display: inline-flex; flex-direction: column; max-width: 70%; padding: 8px 10px; border-radius: 10px; background: #262030; font-size: 13px; align-self: flex-start; }
    #awp .message.me { align-self: flex-end; background: #4a2440; }
    #awp .message-meta { display: flex; justify-content: space-between; gap: 12px; font-size: 11px; color: #a294ad; }
</style>

<div id="awp">
<section style="border-color:<?= $accent ?>">
    <h2 style="color:<?= $accent ?>"><?= sd_e((string) SlowDatingEngine::ADV_MODES[$view['mode']]['label']) ?> room · <?= sd_e(ucfirst((string) $view['theme'])) ?> theme</h2>
    <p style="margin:0">
        <span class="pill">invite code: <strong><?= sd_e((string) $view['invite_code']) ?></strong></span>
        <span class="pill" id="awp-status"><?= sd_e((string) $view['status']) ?></span>
        <?php foreach ($view['participants'] as $person): ?>
            <span class="pill"><?= sd_e((string) ($person['display_name'] ?: $person['user_id'])) ?><?= $person['role'] === 'owner' ? ' · host' : '' ?><?= $view['price_per_user'] > 0 ? ' · ' . sd_e((string) $person['payment']) : '' ?></span>
        <?php endforeach; ?>
    </p>
    <p style="margin:10px 0 0;font-size:12.5px;color:#a294ad">Bring your own YouTube: each of you watches signed
        into your own account — YouTube Premium plays ad-free on your own subscription. The room fee pays for the
        sync service, chat, and recap — never for the movie.</p>
</section>

<?php if (!$view['unlocked'] && !$view['ended']): ?>
<section>
    <h2>Split payment — $<?= number_format((float) $view['price_per_user'], 2) ?> per person</h2>
    <p><?= (int) $view['paid_count'] ?> of <?= (int) $view['required_participants'] ?> shares paid. The room —
        player, shared controls, reactions — unlocks the moment every required share clears.</p>
    <?php if ($myPayment === 'pending'): ?>
        <form method="post" style="background:none;border:0;padding:0;margin:0">
            <input type="hidden" name="action" value="pay">
            <input type="hidden" name="room_id" value="<?= sd_e($roomId) ?>">
            <button type="submit">Pay my share — $<?= number_format((float) $view['price_per_user'], 2) ?></button>
        </form>
    <?php else: ?>
        <p style="color:#b8ffd3">Your share is paid — waiting on the others. Share the invite code
            <strong><?= sd_e((string) $view['invite_code']) ?></strong>.</p>
    <?php endif; ?>
</section>
<?php endif; ?>

<?php if ($view['unlocked'] || $view['ended']): ?>
<section style="position:relative" id="awp-stage">
    <div class="video-wrapper">
        <iframe id="awp-player" src="<?= sd_e((string) $view['embed_url']) ?><?= str_contains((string) $view['embed_url'], '?') ? '&' : '?' ?>enablejsapi=1"
                title="Advanced Watch Party" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
    </div>
    <?php if (!$view['ended']): ?>
    <p style="margin:12px 0 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button type="button" class="act" id="awp-play" style="margin:0;padding:8px 14px">▶ Play together</button>
        <button type="button" class="quiet" id="awp-pause" style="margin:0;padding:8px 14px">⏸ Pause both</button>
        <button type="button" class="quiet" id="awp-resync" style="margin:0;padding:8px 14px">⟲ Re-sync everyone</button>
        <span id="awp-sync-line" style="font-size:12.5px;color:#a294ad">
            Remote: <?= sd_e($controller === $userId ? 'you' : 'another participant') ?></span>
    </p>
    <?php if ($controller === $userId || $isOwner): ?>
    <form method="post" style="background:none;border:0;padding:0;margin:10px 0 0;display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap">
        <input type="hidden" name="action" value="remote">
        <input type="hidden" name="room_id" value="<?= sd_e($roomId) ?>">
        <div><label style="margin:0 0 4px">Pass the remote to</label>
            <select name="user_id" style="min-width:180px">
                <?php foreach ($view['participants'] as $person): ?>
                    <?php if ($person['user_id'] !== $controller): ?>
                        <option value="<?= sd_e((string) $person['user_id']) ?>"><?= sd_e((string) ($person['display_name'] ?: $person['user_id'])) ?></option>
                    <?php endif; ?>
                <?php endforeach; ?>
            </select>
        </div>
        <button type="submit" class="quiet" style="margin:0;padding:9px 14px">Pass it</button>
    </form>
    <?php endif; ?>
    <p style="margin:12px 0 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <span style="font-size:12.5px;color:#a294ad">React:</span>
        <?php foreach (['laugh' => '😂', 'shock' => '😱', 'cry' => '😢', 'love' => '❤️', 'wow' => '🤩', 'bored' => '🥱'] as $type => $emoji): ?>
            <button type="button" class="quiet" data-awp-react="<?= sd_e($type) ?>" data-emoji="<?= $emoji ?>" style="margin:0;padding:6px 10px;font-size:18px"><?= $emoji ?></button>
        <?php endforeach; ?>
        <button type="button" class="quiet" id="awp-highlight" style="margin:0;padding:6px 12px;font-size:12.5px">⭐ Mark this moment</button>
    </p>
    <?php endif; ?>
</section>

<?php if (!$view['ended']): ?>
<section>
    <h2>Room chat</h2>
    <form id="awp-chat-form" style="background:none;border:0;padding:0;margin:0">
        <textarea id="awp-chat-text" placeholder="Say something…" style="min-height:60px"></textarea>
        <button type="submit" style="margin-top:8px">Send</button>
        <span id="awp-chat-flash" style="display:block;color:#ff9cba;font-size:12.5px;margin-top:6px"></span>
    </form>
    <div class="messages" id="awp-messages"></div>
</section>
<?php endif; ?>
<?php endif; ?>

<?php if ($recap !== null): ?>
<section style="border-color:<?= $accent ?>">
    <h2>The recap</h2>
    <div class="grid">
        <?php foreach ($recap['reaction_totals'] as $type => $count): ?>
            <div class="metric card"><strong><?= (int) $count ?></strong><span><?= sd_e((string) $type) ?></span></div>
        <?php endforeach; ?>
    </div>
    <?php if ($recap['peak_moment'] !== null): ?>
        <p>Most intense stretch: around <?= sd_e(gmdate('H:i:s', (int) $recap['peak_moment']['from_seconds'])) ?>
            (<?= (int) $recap['peak_moment']['reactions'] ?> reactions).</p>
    <?php endif; ?>
    <?php if ((array) $recap['sync_moments'] !== []): ?>
        <p><strong style="color:<?= $accent ?>"><?= count((array) $recap['sync_moments']) ?> emotion sync moment<?= count((array) $recap['sync_moments']) === 1 ? '' : 's' ?></strong>
            — times you reacted within a second of each other.</p>
    <?php endif; ?>
    <?php if ((array) $recap['highlights'] !== []): ?>
        <h3 style="margin:12px 0 6px">Marked moments</h3>
        <?php foreach ((array) $recap['highlights'] as $highlight): ?>
            <span class="pill">⭐ <?= sd_e(gmdate('H:i:s', (int) $highlight['t'])) ?><?= (string) $highlight['note'] !== '' ? ' · ' . sd_e((string) $highlight['note']) : '' ?></span>
        <?php endforeach; ?>
    <?php endif; ?>
</section>
<?php elseif ($isOwner && $view['unlocked']): ?>
<section>
    <form method="post" style="background:none;border:0;padding:0;margin:0">
        <input type="hidden" name="action" value="end">
        <input type="hidden" name="room_id" value="<?= sd_e($roomId) ?>">
        <button type="submit" class="quiet" style="margin:0">End the session → see the recap</button>
    </form>
</section>
<?php endif; ?>

<p class="links" style="margin-top:16px"><a href="advanced-watch-party.php">← All rooms</a>
    <a href="watch-party.php">Couple's Watch Party</a></p>
</div>

<?php if ($view['unlocked'] && !$view['ended']): ?>
<script>
(function () {
    var roomId = <?= json_encode($roomId) ?>;
    var player = document.getElementById('awp-player');
    var lastTime = 0;
    var lastApplied = <?= (int) ($view['sync']['updated_at'] ?? 0) ?>;
    function ytCmd(func, args) {
        if (player && player.contentWindow) {
            player.contentWindow.postMessage(JSON.stringify({ event: 'command', func: func, args: args || [] }), '*');
        }
    }
    window.addEventListener('message', function (event) {
        try {
            var data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
            if (data && data.info && typeof data.info.currentTime === 'number') { lastTime = data.info.currentTime; }
        } catch (ignored) {}
    });
    setTimeout(function () {
        if (player && player.contentWindow) {
            player.contentWindow.postMessage(JSON.stringify({ event: 'listening', id: 'awp' }), '*');
        }
    }, 1500);
    function post(action, extra) {
        var data = new FormData();
        data.append('action', action);
        data.append('ajax', '1');
        data.append('room_id', roomId);
        for (var key in (extra || {})) { data.append(key, extra[key]); }
        return fetch('advanced-watch-party.php?room=' + encodeURIComponent(roomId), { method: 'POST', body: data, credentials: 'same-origin' })
            .then(function (response) {
                return response.text().then(function (body) {
                    if (!response.ok) { throw new Error(body); }
                    return body ? JSON.parse(body) : {};
                });
            });
    }
    function applySync(sync) {
        if (!sync || !sync.updated_at || sync.updated_at <= lastApplied) { return; }
        lastApplied = sync.updated_at;
        ytCmd('seekTo', [sync.position || 0, true]);
        ytCmd(sync.playing ? 'playVideo' : 'pauseVideo');
    }
    var play = document.getElementById('awp-play');
    var pause = document.getElementById('awp-pause');
    var resync = document.getElementById('awp-resync');
    var line = document.getElementById('awp-sync-line');
    function syncPush(playing) {
        ytCmd(playing ? 'playVideo' : 'pauseVideo');
        post('sync', { playing: playing ? '1' : '0', position: String(Math.floor(lastTime)) })
            .then(applySync)
            .catch(function (problem) { if (line) { line.textContent = problem.message; } });
    }
    if (play) { play.addEventListener('click', function () { syncPush(true); }); }
    if (pause) { pause.addEventListener('click', function () { syncPush(false); }); }
    if (resync) { resync.addEventListener('click', function () { syncPush(true); }); }

    // Reaction bursts on the emotion timeline.
    var stage = document.getElementById('awp-stage');
    document.querySelectorAll('button[data-awp-react]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            post('react', { type: btn.getAttribute('data-awp-react'), t: String(Math.floor(lastTime)) }).catch(function () {});
            var burst = document.createElement('span');
            burst.className = 'burst';
            burst.textContent = btn.getAttribute('data-emoji');
            burst.style.left = (20 + Math.random() * 60) + '%';
            burst.style.top = '45%';
            stage.appendChild(burst);
            setTimeout(function () { burst.remove(); }, 1700);
        });
    });
    var highlight = document.getElementById('awp-highlight');
    if (highlight) {
        highlight.addEventListener('click', function () {
            post('highlight', { t: String(Math.floor(lastTime)), note: '' }).then(function () {
                highlight.textContent = '⭐ Saved at ' + Math.floor(lastTime) + 's';
                setTimeout(function () { highlight.textContent = '⭐ Mark this moment'; }, 2000);
            }).catch(function () {});
        });
    }

    // Chat: send + poll, never touching the player.
    var chatForm = document.getElementById('awp-chat-form');
    var chatText = document.getElementById('awp-chat-text');
    var chatFlash = document.getElementById('awp-chat-flash');
    var log = document.getElementById('awp-messages');
    function refreshChat() {
        fetch('advanced-watch-party.php?room=' + encodeURIComponent(roomId) + '&fragment=chat', { credentials: 'same-origin' })
            .then(function (response) { return response.ok ? response.text() : null; })
            .then(function (body) { if (body !== null && log && body !== log.innerHTML) { log.innerHTML = body; } })
            .catch(function () {});
    }
    if (chatForm) {
        chatForm.addEventListener('submit', function (event) {
            event.preventDefault();
            post('room_chat', { text: chatText.value })
                .then(function () { chatText.value = ''; chatFlash.textContent = ''; refreshChat(); })
                .catch(function (problem) { chatFlash.textContent = problem.message; });
        });
        refreshChat();
        setInterval(refreshChat, 6000);
    }

    // Everyone follows the room's timecode authority.
    setInterval(function () {
        fetch('advanced-watch-party.php?room=' + encodeURIComponent(roomId) + '&fragment=state', { credentials: 'same-origin' })
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (state) { if (state && state.sync) { applySync(state.sync); } })
            .catch(function () {});
    }, 4000);
})();
</script>
<?php endif; ?>

<?php sd_page_close(); ?>
