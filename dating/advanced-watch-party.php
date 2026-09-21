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
        } elseif ($_GET['fragment'] === 'game') {
            // Background games: the room's one shared game state, polled by everyone.
            header('Content-Type: application/json');
            echo json_encode($engine->advancedGame($roomId, $userId));
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
        echo in_array((string) $_GET['fragment'], ['state', 'game'], true) ? '{}' : '';
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
            case 'video':
                $result = $engine->setAdvancedVideo($roomId, $userId, (string) ($_POST['video_url'] ?? ''));
                $notice = 'The room\'s video changed — everyone\'s player follows.';
                break;
            case 'game':
                $gameState = json_decode((string) ($_POST['state'] ?? '{}'), true);
                $result = $engine->setAdvancedGame(
                    $roomId,
                    $userId,
                    (string) ($_POST['game'] ?? ''),
                    is_array($gameState) ? $gameState : [],
                );
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

/**
 * The full Watch Party library, replicated here: every channel category
 * and every video, with the YouTube thumbnails as the buttons. Inside a
 * room a pick swaps the room's video for everyone; in the lobby it fills
 * the create form's YouTube source.
 */
function awp_library(SlowDatingEngine $engine, string $roomId): void
{
    $channels = $engine->watchChannels();
    $ch = (string) ($_GET['ch'] ?? 'romance');
    if (!isset($channels[$ch])) {
        $ch = 'romance';
    }
    $q = trim((string) ($_GET['q'] ?? ''));
    $page = max(0, (int) ($_GET['p'] ?? 0));
    $perPage = 24;
    $library = $engine->channelLibrary($ch, $q, $perPage, $page * $perPage);
    $base = $roomId !== '' ? '?room=' . sd_e(rawurlencode($roomId)) . '&amp;' : '?';
    ?>
    <style>
        .chmenu { position: relative; display: inline-block; margin: 0 4px 0 0; }
        .chmenu summary { list-style: none; cursor: pointer; display: inline-block; background: #3a2a3e;
            color: #ffc4da; border-radius: 999px; padding: 6px 14px; font-size: 13px; font-weight: 700; }
        .chmenu summary::-webkit-details-marker { display: none; }
        .chmenu[open] summary { background: #ff9cc0; color: #2a0f1d; }
        .chmenu-list { position: absolute; top: calc(100% + 6px); left: 0; z-index: 40; min-width: 220px;
            background: #1d1824; border: 1px solid #574a61; border-radius: 12px; padding: 8px;
            display: flex; flex-direction: column; gap: 2px; box-shadow: 0 16px 32px rgba(0,0,0,.5); }
        .chmenu-list a { display: block; padding: 7px 10px; border-radius: 8px; color: #ffb8d2;
            text-decoration: none; font-size: 13px; margin: 0; }
        .chmenu-list a:hover { background: #262030; text-decoration: none; }
        .chmenu-list a.on { background: #4a2440; color: #ffd4e5; font-weight: 800; }
    </style>
    <section>
        <h2>The Watch Party library — every channel, every video</h2>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 10px">
            <?php foreach (SlowDatingEngine::WATCH_CHANNEL_GROUPS as $groupLabel => $groupChannels): ?>
                <details class="chmenu">
                    <summary><?= sd_e($groupLabel) ?> ▾</summary>
                    <div class="chmenu-list">
                        <?php foreach ($groupChannels as $slug): ?>
                            <a href="<?= $base ?>ch=<?= sd_e($slug) ?>"<?= $ch === $slug ? ' class="on"' : '' ?>><?= sd_e((string) $channels[$slug]['label']) ?></a>
                        <?php endforeach; ?>
                    </div>
                </details>
            <?php endforeach; ?>
        </div>
        <p style="margin:0 0 10px"><strong style="color:#f3eef6"><?= sd_e((string) $channels[$ch]['label']) ?></strong> ·
            <?= sd_e((string) $channels[$ch]['blurb']) ?>
            <?= $roomId !== '' ? ' A pick swaps the room\'s video for everyone in it.' : ' A pick fills the room form above — create the room and it plays there.' ?></p>
        <form method="get" style="background:none;border:0;padding:0;margin:0 0 12px">
            <?php if ($roomId !== ''): ?><input type="hidden" name="room" value="<?= sd_e($roomId) ?>"><?php endif; ?>
            <input type="hidden" name="ch" value="<?= sd_e($ch) ?>">
            <label>Search this channel</label>
            <input name="q" value="<?= sd_e($q) ?>" placeholder="The Notebook, waterfall, psalms…">
            <button type="submit">Search</button>
        </form>
        <p style="margin:0 0 8px;font-size:13px"><?= (int) $library['total'] ?> title<?= $library['total'] === 1 ? '' : 's' ?><?= $q !== '' ? ' matching "' . sd_e($q) . '"' : ' in this channel' ?> · page <?= $page + 1 ?></p>
        <div class="grid">
            <?php foreach ($library['films'] as $entry): ?>
                <?php $watchUrl = !empty($entry['youtube_id']) ? 'https://www.youtube.com/watch?v=' . (string) $entry['youtube_id'] : ''; ?>
                <div class="card" style="padding:12px">
                    <?php if ($watchUrl !== ''): ?>
                        <!-- The YouTube thumbnail IS the button: the art sells the video. -->
                        <?php if ($roomId !== ''): ?>
                            <form method="post" style="background:none;border:0;padding:0;margin:0 0 8px">
                                <input type="hidden" name="action" value="video">
                                <input type="hidden" name="room_id" value="<?= sd_e($roomId) ?>">
                                <input type="hidden" name="video_url" value="<?= sd_e($watchUrl) ?>">
                                <button type="submit" title="Play <?= sd_e((string) $entry['title']) ?> in this room"
                                        style="display:block;width:100%;padding:0;margin:0;border:0;background:none;cursor:pointer;border-radius:10px;overflow:hidden">
                                    <img src="https://i.ytimg.com/vi/<?= sd_e((string) $entry['youtube_id']) ?>/mqdefault.jpg" alt=""
                                         loading="lazy" style="display:block;width:100%;aspect-ratio:16/9;object-fit:cover"
                                         onerror="this.parentNode.parentNode.style.display='none'">
                                </button>
                            </form>
                        <?php else: ?>
                            <button type="button" class="awp-fill" data-vurl="<?= sd_e($watchUrl) ?>" title="Use <?= sd_e((string) $entry['title']) ?> for a new room"
                                    style="display:block;width:100%;padding:0;margin:0 0 8px;border:0;background:none;cursor:pointer;border-radius:10px;overflow:hidden">
                                <img src="https://i.ytimg.com/vi/<?= sd_e((string) $entry['youtube_id']) ?>/mqdefault.jpg" alt=""
                                     loading="lazy" style="display:block;width:100%;aspect-ratio:16/9;object-fit:cover"
                                     onerror="this.parentNode.parentNode.style.display='none'">
                            </button>
                        <?php endif; ?>
                    <?php endif; ?>
                    <strong><?= (int) $entry['rank'] > 0 && $ch === 'romance' ? '#' . (int) $entry['rank'] . ' · ' : '' ?><?= sd_e((string) $entry['title']) ?></strong>
                    <p style="margin:6px 0"><?php if ((int) $entry['year'] > 0): ?><span class="pill"><?= (int) $entry['year'] ?></span><?php endif; ?>
                        <span class="pill"><?= sd_e((string) $entry['tag']) ?></span>
                        <?php if (!empty($entry['live'])): ?><span class="pill" style="background:#3c1f32;color:#ff9cba">● LIVE</span><?php endif; ?></p>
                    <?php if ($watchUrl !== '' && $roomId !== ''): ?>
                        <form method="post" style="background:none;border:0;padding:0;margin:0">
                            <input type="hidden" name="action" value="video">
                            <input type="hidden" name="room_id" value="<?= sd_e($roomId) ?>">
                            <input type="hidden" name="video_url" value="<?= sd_e($watchUrl) ?>">
                            <button type="submit" style="margin-top:6px">Play in this room</button>
                        </form>
                    <?php elseif ($watchUrl !== ''): ?>
                        <button type="button" class="awp-fill" data-vurl="<?= sd_e($watchUrl) ?>" style="margin-top:6px">Use for a new room</button>
                    <?php else: ?>
                        <p style="margin:6px 0 0;font-size:12px;color:#a294ad">No verified in-page stream yet.</p>
                    <?php endif; ?>
                </div>
            <?php endforeach; ?>
        </div>
        <p class="links" style="margin-top:12px">
            <?php if ($page > 0): ?><a href="<?= $base ?>ch=<?= sd_e($ch) ?>&amp;q=<?= sd_e(rawurlencode($q)) ?>&amp;p=<?= $page - 1 ?>">&#8249; Previous page</a><?php endif; ?>
            <?php if (($page + 1) * $perPage < (int) $library['total']): ?><a href="<?= $base ?>ch=<?= sd_e($ch) ?>&amp;q=<?= sd_e(rawurlencode($q)) ?>&amp;p=<?= $page + 1 ?>">Next page &#8250;</a><?php endif; ?>
        </p>
    </section>
    <?php if ($roomId === ''): ?>
    <script>
        // Lobby: a thumbnail pick fills the create form's YouTube source.
        document.addEventListener('click', function (e) {
            var pick = e.target.closest('button.awp-fill');
            if (!pick) { return; }
            var input = document.querySelector('input[name=video_url]');
            if (input) {
                input.value = pick.getAttribute('data-vurl');
                input.scrollIntoView({ block: 'center' });
                input.focus();
            }
        });
    </script>
    <?php endif; ?>
    <?php
}

sd_page_open('Advanced Watch Party · BETA', 'SlowMoDating.com · rooms, split payments, shared controls · beta preview');
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
                    <?php if (preg_match('#/embed/([A-Za-z0-9_-]{11})(?:[/?]|$)#', (string) $room['embed_url'], $thumbMatch) === 1): ?>
                        <img src="https://i.ytimg.com/vi/<?= sd_e($thumbMatch[1]) ?>/mqdefault.jpg" alt="" loading="lazy"
                             style="display:block;width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;margin-bottom:8px"
                             onerror="this.style.display='none'">
                    <?php endif; ?>
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
    <?php awp_library($engine, ''); ?>
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
    /* Sized like the couple's Watch Party player: never taller than the
       viewport leaves room for, so the room's panels stay on screen. */
    #awp .video-wrapper { position: relative; aspect-ratio: 16 / 9; overflow: hidden; border-radius: 12px; border: 1px solid <?= $accent ?>; background: #020617;
        max-width: min(100%, calc((100vh - 280px) * 1.7778)); margin: 0 auto; width: 100%; }
    #awp .video-wrapper iframe { position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0; }
    /* Background games: the same semi-transparent pop-up the couple's
       Watch Party carries — play while watching, nothing pauses. */
    #wpg { position: fixed; top: 12%; right: 4%; width: 300px; z-index: 1000;
        background: rgba(10, 8, 16, .68); backdrop-filter: blur(9px); -webkit-backdrop-filter: blur(9px);
        border: 1px solid rgba(255, 156, 192, .35); border-radius: 14px; padding: 12px; color: #fff; }
    #wpg h3 { margin: 0; font-size: 14px; }
    #wpg .wpg-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
    #wpg .wpg-top button, #wpg .wpg-menu button, #wpg .wpg-body button { margin: 0; padding: 5px 10px; font-size: 12px;
        border-radius: 8px; background: rgba(255, 255, 255, .14); color: #fff; }
    #wpg .wpg-menu { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
    #wpg .wpg-menu button { text-align: left; padding: 8px 10px; }
    #wpg .wpg-menu small { display: block; color: #c9bfd2; font-weight: 400; font-size: 10.5px; }
    #wpg .wpg-status { font-size: 12px; color: #ffc4da; margin: 6px 0; min-height: 15px; }
    #wpg .wpg-grid { display: grid; gap: 4px; }
    #wpg .wpg-cell { display: flex; align-items: center; justify-content: center; background: rgba(255, 255, 255, .09);
        border-radius: 7px; cursor: pointer; user-select: none; font-size: 22px; }
    #wpg .wpg-cell:hover { background: rgba(255, 255, 255, .18); }
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
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
        <h2 style="margin:0 0 10px">Room chat</h2>
        <?php if ($view['unlocked']): ?>
            <button type="button" id="wpg-open" style="margin:0;padding:6px 14px;font-size:12.5px;background:#3a2a3e;color:#ffc4da">🎲 Games</button>
        <?php endif; ?>
    </div>
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

<?php awp_library($engine, $roomId); ?>

<p class="links" style="margin-top:16px"><a href="advanced-watch-party.php">← All rooms</a>
    <a href="watch-party.php">Couple's Watch Party</a></p>
</div>

<?php if ($view['unlocked'] && !$view['ended']): ?>
<!-- Background games pop-up: floats over player + chat, never pauses either. -->
<div id="wpg" hidden>
    <div class="wpg-top">
        <h3 id="wpg-title">🎲 Background games</h3>
        <div>
            <button type="button" id="wpg-menu-btn" title="All games">☰</button>
            <button type="button" id="wpg-close" title="Close">✕</button>
        </div>
    </div>
    <div class="wpg-status" id="wpg-status">Pick a game — you can keep chatting and watching.</div>
    <div id="wpg-body"></div>
</div>
<?php endif; ?>

<?php
$playerIds = array_map(static fn (array $p): string => (string) $p['user_id'], $view['participants']);
$gamePartnerName = 'another participant';
foreach ($view['participants'] as $person) {
    if ($person['user_id'] !== $userId) {
        $gamePartnerName = (string) ($person['display_name'] ?: $person['user_id']);
        break;
    }
}
?>
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

    // Games adapter (Advanced rooms): the room record's shared game
    // state — every participant polls it; the first two seats hold the
    // pieces, the rest of the room watches the board.
    var WPG_ME = <?= json_encode($userId) ?>;
    var WPG_PARTNER = <?= json_encode($gamePartnerName) ?>;
    var WPG_PLAYERS = <?= json_encode($playerIds) ?>;
    var WPG_CHAT = roomId;
    function WPG_PUSH(game, state, ack) {
        post('game', { game: game, state: JSON.stringify(state) })
            .then(function (d) { if (d && d.updated_at) { ack(d.updated_at); } })
            .catch(function () {});
    }
    function WPG_POLL(apply) {
        setInterval(function () {
            fetch('advanced-watch-party.php?room=' + encodeURIComponent(roomId) + '&fragment=game', { credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(apply)
                .catch(function () {});
        }, 3500);
    }

        // ---- Background games: shared state on the chat, both players
        // poll it — the movie and the chat never pause for a move. ----
        (function () {
            var box = document.getElementById('wpg');
            if (!box) { return; }
            var me = WPG_ME;
            var partnerName = WPG_PARTNER;
            var players = WPG_PLAYERS;
            var chatRef = WPG_CHAT;
            var seat = Math.max(0, players.indexOf(me));
            var bodyEl = document.getElementById('wpg-body');
            var statusEl = document.getElementById('wpg-status');
            var titleEl = document.getElementById('wpg-title');
            var current = '';
            var state = null;
            var lastApplied = 0;
            function rng(seed) { return function () { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }; }
            function shuffled(list, seed) {
                var copy = list.slice(); var r = rng(seed);
                for (var i = copy.length - 1; i > 0; i--) { var j = Math.floor(r() * (i + 1)); var t = copy[i]; copy[i] = copy[j]; copy[j] = t; }
                return copy;
            }
            var WYR = [['Travel the world for a year', 'Buy a home right now'], ['Always know the movie ending', 'Never see a spoiler again'],
                ['Dinner and dancing', 'Blanket fort and takeout'], ['Live by the ocean', 'Live in the mountains'],
                ['Re-live your best day', 'Preview one day of the future'], ['Only sunrise dates', 'Only midnight dates'],
                ['Sing everything you say', 'Dance everywhere you walk'], ['Cook together every night', 'Eat out every night'],
                ['A road trip with no map', 'A planned trip, every detail'], ['Love letters only', 'Voice notes only']];
            var TRIVIA = [['Which film says "You had me at hello"?', ['Jerry Maguire', 'Notting Hill', 'Ghost'], 0],
                ['Casablanca is set in which country?', ['Morocco', 'France', 'Egypt'], 0],
                ['In Titanic, Jack draws Rose wearing.', ['The Heart of the Ocean', 'A red scarf', 'A tiara'], 0],
                ['The Notebook couple are Noah and.', ['Allie', 'Emma', 'Rose'], 0],
                ['"To me, you are perfect" is from.', ['Love Actually', 'About Time', 'The Holiday'], 0],
                ['Audrey Hepburn stars in.', ['Charade', 'Pillow Talk', 'Gilda'], 0],
                ['Dirty Dancing: "Nobody puts ___ in a corner"', ['Baby', 'Frances', 'Penny'], 0],
                ['When Harry Met Sally ends on.', ['New Year\'s Eve', 'Valentine\'s Day', 'Christmas'], 0]];
            var BINGO_POOL = ['A kiss', 'Car chase', 'Plot twist', 'Sunset shot', 'Dance scene', 'Phone call', 'Rain scene', 'Flashback',
                'Wedding', 'Airport run', 'Slow motion', 'Tears', 'Big laugh', 'Song moment', 'A letter', '"I love you"'];
            var MEMO = ['❤️', '🌹', '🍷', '🎬', '🌙', '🎵', '☕', '💌'];
            var GAMES = {
                tictactoe: { name: 'Tic-Tac-Toe', tag: 'ultra-simple idle play',
                    init: function () { return { b: ['', '', '', '', '', '', '', '', ''], n: 0, over: '' }; } },
                connect4: { name: 'Connect Four', tag: 'drop tokens, four in a row',
                    init: function () { var b = []; for (var i = 0; i < 42; i++) { b.push(0); } return { b: b, n: 0, over: 0 }; } },
                memory: { name: 'Memory Match', tag: 'flip cards, find pairs',
                    init: function () { return { seed: Date.now() % 1000000, up: [], done: [], n: 0, score: [0, 0] }; } },
                wyr: { name: 'Would You Rather', tag: 'conversation cards',
                    init: function () { return { i: Math.floor(Math.random() * WYR.length), picks: {} }; } },
                trivia: { name: 'Trivia', tag: 'one easy question at a time',
                    init: function () { return { i: Math.floor(Math.random() * TRIVIA.length), picks: {} }; } },
                bingo: { name: 'Scene Bingo', tag: 'tap events as they happen',
                    init: function () { return { seed: Date.now() % 1000000, marks: {} }; } },
            };
            function turnOf(s) { return s.n % 2; }
            function myTurn(s) { return turnOf(s) === seat; }
            function escapeHtml(text) { var d = document.createElement('span'); d.textContent = String(text); return d.innerHTML; }
            function status(text) { statusEl.textContent = text; }
            function menu() {
                current = '';
                titleEl.textContent = '🎲 Background games';
                status('Pick a game - you can keep chatting and watching.');
                var html = '';
                for (var key in GAMES) {
                    html += '<button data-wpg-pick="' + key + '"><strong>' + GAMES[key].name + '</strong><small>' + GAMES[key].tag + '</small></button>';
                }
                bodyEl.innerHTML = '<div class="wpg-menu">' + html + '</div>';
            }
            function render() {
                if (!current || !state) { menu(); return; }
                titleEl.textContent = '🎲 ' + GAMES[current].name;
                var html = '';
                var i;
                if (current === 'tictactoe') {
                    var sym = ['X', 'O'];
                    html = '<div class="wpg-grid" style="grid-template-columns:repeat(3,1fr)">';
                    for (i = 0; i < 9; i++) { html += '<div class="wpg-cell" style="height:56px" data-wpg-m="' + i + '">' + (state.b[i] || '') + '</div>'; }
                    html += '</div>';
                    status(state.over ? (state.over === 'draw' ? 'Draw!' : state.over + ' wins!')
                        : (myTurn(state) ? 'Your move - you are ' + sym[seat] : partnerName + "'s move (" + sym[1 - seat] + ')'));
                } else if (current === 'connect4') {
                    html = '<div class="wpg-grid" style="grid-template-columns:repeat(7,1fr)">';
                    for (i = 0; i < 42; i++) {
                        var token = state.b[i] === 1 ? '🔴' : state.b[i] === 2 ? '🟡' : '';
                        html += '<div class="wpg-cell" style="height:32px;font-size:16px" data-wpg-m="' + (i % 7) + '">' + token + '</div>';
                    }
                    html += '</div>';
                    status(state.over ? (state.over === 3 ? 'Draw!' : (state.over === 1 ? 'Red' : 'Yellow') + ' wins!')
                        : (myTurn(state) ? 'Your drop - you are ' + (seat === 0 ? 'red' : 'yellow') : partnerName + "'s drop"));
                } else if (current === 'memory') {
                    var deck = shuffled(MEMO.concat(MEMO), state.seed);
                    html = '<div class="wpg-grid" style="grid-template-columns:repeat(4,1fr)">';
                    for (i = 0; i < 16; i++) {
                        var shown = state.done.indexOf(i) >= 0 || state.up.indexOf(i) >= 0;
                        html += '<div class="wpg-cell" style="height:44px" data-wpg-m="' + i + '">' + (shown ? deck[i] : '❔') + '</div>';
                    }
                    html += '</div>';
                    status('You ' + state.score[seat] + ' · ' + partnerName + ' ' + state.score[1 - seat]
                        + (state.done.length === 16 ? ' - finished!' : (myTurn(state) ? ' · your turn' : ' · their turn')));
                } else if (current === 'wyr') {
                    var pair = WYR[state.i % WYR.length];
                    var mine = state.picks[me];
                    html = '<p style="font-size:13px;margin:0 0 8px">Would you rather.</p>'
                        + '<button style="display:block;width:100%;margin-bottom:6px' + (mine === 0 ? ';background:#4a2440' : '') + '" data-wpg-m="0">' + escapeHtml(pair[0]) + '</button>'
                        + '<button style="display:block;width:100%' + (mine === 1 ? ';background:#4a2440' : '') + '" data-wpg-m="1">' + escapeHtml(pair[1]) + '</button>'
                        + '<button style="margin-top:8px" data-wpg-m="next">Next card →</button>';
                    var theirs = state.picks[players[1 - seat]];
                    status(mine === undefined ? 'Tap your pick - talk it out!'
                        : (theirs === undefined ? 'Waiting for ' + partnerName + '.'
                            : (mine === theirs ? 'Same pick - you two agree!' : 'Opposite picks - discuss!')));
                } else if (current === 'trivia') {
                    var q = TRIVIA[state.i % TRIVIA.length];
                    var picked = state.picks[me];
                    html = '<p style="font-size:13px;margin:0 0 8px">' + escapeHtml(q[0]) + '</p>';
                    for (i = 0; i < q[1].length; i++) {
                        var mark = picked !== undefined ? (i === q[2] ? ' ✓' : (i === picked ? ' ✗' : '')) : '';
                        html += '<button style="display:block;width:100%;margin-bottom:6px' + (picked !== undefined && i === q[2] ? ';background:#17351f' : '') + '" data-wpg-m="' + i + '">' + escapeHtml(q[1][i]) + mark + '</button>';
                    }
                    html += '<button style="margin-top:4px" data-wpg-m="next">Next question →</button>';
                    status(picked === undefined ? 'No pressure - one question at a time.' : (picked === q[2] ? 'Right!' : 'The answer: ' + q[1][q[2]]));
                } else if (current === 'bingo') {
                    var card = shuffled(BINGO_POOL, state.seed + seat * 7919);
                    var marks = state.marks[me] || [];
                    html = '<div class="wpg-grid" style="grid-template-columns:repeat(4,1fr)">';
                    for (i = 0; i < 16; i++) {
                        html += '<div class="wpg-cell" style="height:44px;font-size:9.5px;text-align:center;padding:2px'
                            + (marks.indexOf(i) >= 0 ? ';background:#4a2440' : '') + '" data-wpg-m="' + i + '">' + escapeHtml(card[i]) + '</div>';
                    }
                    html += '</div>';
                    var lines = [[0,1,2,3],[4,5,6,7],[8,9,10,11],[12,13,14,15],[0,4,8,12],[1,5,9,13],[2,6,10,14],[3,7,11,15],[0,5,10,15],[3,6,9,12]];
                    var bingo = lines.some(function (line) { return line.every(function (cell) { return marks.indexOf(cell) >= 0; }); });
                    var theirMarks = (state.marks[players[1 - seat]] || []).length;
                    status(bingo ? 'BINGO! Tell ' + partnerName + '!' : 'Tap events as they happen · ' + partnerName + ' has ' + theirMarks + ' marked');
                }
                bodyEl.innerHTML = html + '<p style="margin:8px 0 0"><button data-wpg-reset="1">↺ New round</button></p>';
            }
            function push() { WPG_PUSH(current, state, function (at) { lastApplied = at; }); }
            function ticWin(b) {
                var wins = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
                for (var w = 0; w < wins.length; w++) {
                    var a = wins[w];
                    if (b[a[0]] && b[a[0]] === b[a[1]] && b[a[0]] === b[a[2]]) { return b[a[0]]; }
                }
                return b.every(function (cell) { return cell; }) ? 'draw' : '';
            }
            function c4Win(b, who) {
                for (var r = 0; r < 6; r++) {
                    for (var c = 0; c < 7; c++) {
                        var dirs = [[0, 1], [1, 0], [1, 1], [1, -1]];
                        for (var d = 0; d < 4; d++) {
                            var hit = 0;
                            for (var k = 0; k < 4; k++) {
                                var rr = r + dirs[d][0] * k, cc = c + dirs[d][1] * k;
                                if (rr >= 0 && rr < 6 && cc >= 0 && cc < 7 && b[rr * 7 + cc] === who) { hit++; }
                            }
                            if (hit === 4) { return true; }
                        }
                    }
                }
                return false;
            }
            function move(action) {
                if (!current || !state) { return; }
                var i;
                if (current === 'tictactoe') {
                    i = +action;
                    if (state.over || state.b[i] || !myTurn(state)) { return; }
                    state.b[i] = seat === 0 ? 'X' : 'O';
                    state.n++;
                    state.over = ticWin(state.b);
                } else if (current === 'connect4') {
                    if (state.over || !myTurn(state)) { return; }
                    var col = +action, row = -1;
                    for (i = 5; i >= 0; i--) { if (!state.b[i * 7 + col]) { row = i; break; } }
                    if (row < 0) { return; }
                    var who = seat + 1;
                    state.b[row * 7 + col] = who;
                    state.n++;
                    if (c4Win(state.b, who)) { state.over = who; } else if (state.n === 42) { state.over = 3; }
                } else if (current === 'memory') {
                    i = +action;
                    if (!myTurn(state) || state.done.indexOf(i) >= 0 || state.up.indexOf(i) >= 0 || state.up.length === 2) { return; }
                    state.up.push(i);
                    if (state.up.length === 2) {
                        var deck = shuffled(MEMO.concat(MEMO), state.seed);
                        var a = state.up[0], b = state.up[1];
                        if (deck[a] === deck[b]) {
                            state.done.push(a, b); state.score[seat]++; state.up = [];
                        } else {
                            render(); push();
                            setTimeout(function () { state.up = []; state.n++; render(); push(); }, 1100);
                            return;
                        }
                    }
                } else if (current === 'wyr') {
                    if (action === 'next') { state = { i: (state.i + 1) % WYR.length, picks: {} }; }
                    else { state.picks[me] = +action; }
                } else if (current === 'trivia') {
                    if (action === 'next') { state = { i: (state.i + 1) % TRIVIA.length, picks: {} }; }
                    else if (state.picks[me] === undefined) { state.picks[me] = +action; }
                } else if (current === 'bingo') {
                    i = +action;
                    var marks = state.marks[me] || [];
                    var at = marks.indexOf(i);
                    if (at >= 0) { marks.splice(at, 1); } else { marks.push(i); }
                    state.marks[me] = marks;
                }
                render();
                push();
            }
            document.getElementById('wpg-open').addEventListener('click', function () { box.hidden = false; if (!current) { menu(); } });
            document.getElementById('wpg-close').addEventListener('click', function () { box.hidden = true; });
            document.getElementById('wpg-menu-btn').addEventListener('click', menu);
            box.addEventListener('click', function (event) {
                var pick = event.target.closest('[data-wpg-pick]');
                if (pick) { current = pick.getAttribute('data-wpg-pick'); state = GAMES[current].init(); render(); push(); return; }
                var reset = event.target.closest('[data-wpg-reset]');
                if (reset) { state = GAMES[current].init(); render(); push(); return; }
                var action = event.target.closest('[data-wpg-m]');
                if (action) { move(action.getAttribute('data-wpg-m')); }
            });
            WPG_POLL(function (d) {
                if (!d || !d.updated_at || d.updated_at <= lastApplied || d.set_by === me) { return; }
                lastApplied = d.updated_at;
                current = d.game;
                state = d.state;
                if (!box.hidden) { render(); }
                else if (d.game) { box.hidden = false; render(); }
            });
            window.WPG_TEST = { open: function () { box.hidden = false; menu(); }, pick: function (k) { current = k; state = GAMES[k].init(); render(); }, move: move, get: function () { return { current: current, state: state, seat: seat }; } };
        })();
})();
</script>
<?php endif; ?>

<?php sd_page_close(); ?>
