<?php
declare(strict_types=1);

require_once __DIR__ . '/RoomStore.php';
require_once __DIR__ . '/MessageLog.php';
require_once __DIR__ . '/Playlist.php';
require_once __DIR__ . '/PlaybackState.php';
require_once __DIR__ . '/Source.php';
require_once __DIR__ . '/Webhooks.php';

/**
 * The JSON API behind api.php, as plain methods so the contract test can call it
 * without HTTP. Every action returns [status, body]; every error body carries an
 * `error` message and a machine `code` the client maps to a recovery.
 */
final class WatchRoomApi
{
    private array $config;

    public function __construct(private readonly RoomStore $rooms, private readonly string $mediaDir, private readonly bool $lookupTitles = true, array $config = [])
    {
        $this->config = $config + ['webhook_timeout' => 2, 'webhooks_per_room' => 5, 'room_max_age' => RoomStore::IDLE_MAX_AGE];
        Playlist::$cacheDir = $rooms->dir() . '/_cache';
    }

    public function rooms(): RoomStore { return $this->rooms; }
    public function mediaDir(): string { return $this->mediaDir; }

    /** @return array{0: int, 1: array} */
    public function handle(string $action, string $method, array $input): array
    {
        try {
            return match ($action) {
                'room.create' => $this->post($method, fn () => $this->roomCreate($input)),
                'room.join' => $this->post($method, fn () => $this->roomJoin($input)),
                'room.get' => $this->roomGet($input),
                'room.settings' => $this->post($method, fn () => $this->roomSettings($input)),
                'chat.send' => $this->post($method, fn () => $this->chatSend($input)),
                'messages.list' => $this->messagesList($input),
                'sync.poll' => $this->syncPoll($input),
                'playlist.get' => $this->playlistGet($input),
                'playlist.add' => $this->post($method, fn () => $this->playlistAdd($input)),
                'playlist.import' => $this->post($method, fn () => $this->playlistImport($input)),
                'playlist.set' => $this->post($method, fn () => $this->playlistSet($input)),
                'state.get' => $this->stateGet($input),
                'state.set' => $this->post($method, fn () => $this->stateSet($input)),
                'resolve' => $this->resolve($input),
                'webhook.list' => $this->webhookList($input),
                'webhook.add' => $this->post($method, fn () => $this->webhookAdd($input)),
                'webhook.remove' => $this->post($method, fn () => $this->webhookRemove($input)),
                'health' => [200, $this->health()],
                default => [404, ['error' => 'Unknown action.', 'code' => 'unknown_action']],
            };
        } catch (InvalidArgumentException $e) {
            return [400, ['error' => $e->getMessage(), 'code' => 'bad_request']];
        } catch (OverflowException $e) {
            return [429, ['error' => $e->getMessage(), 'code' => 'rate_limited']];
        } catch (UnexpectedValueException $e) {
            return [403, ['error' => $e->getMessage(), 'code' => 'forbidden']];
        } catch (RuntimeException $e) {
            return [404, ['error' => $e->getMessage(), 'code' => 'not_found']];
        } catch (Throwable $e) {
            return [500, ['error' => 'The server hit an unexpected problem.', 'code' => 'server_error']];
        }
    }

    private function post(string $method, callable $fn): array
    {
        if ($method !== 'POST') {
            return [405, ['error' => 'POST required.', 'code' => 'method']];
        }
        return $fn();
    }

    // ---- rooms ----

    private function roomCreate(array $in): array
    {
        $created = $this->rooms->create((string) ($in['name'] ?? ''));
        $room = $created['room'];
        $member = $created['member'];
        $path = $this->rooms->path($room['id']);
        $playlist = Playlist::empty();
        $first = null;
        $parsed = Playlist::parseUrl((string) ($in['src'] ?? ''), $this->mediaDir)
            ?? Playlist::parseUrl('media/' . Source::SAMPLE, $this->mediaDir);
        if ($parsed !== null && $parsed['kind'] !== 'youtube-playlist') {
            $first = Playlist::makeItem($parsed, $member['id'], $this->lookupTitles);
            $playlist['items'][] = $first;
            $playlist['current'] = $first['id'];
        }
        $playlist = Playlist::save($path, $playlist);
        $state = PlaybackState::apply($path, PlaybackState::initial($first['id'] ?? null), ['itemId' => $first['id'] ?? null, 'playing' => false, 'mediaTime' => 0], $member['id']);
        $log = $this->log($room['id']);
        $log->append($this->system($member, $member['name'] . ' opened the room'));
        return [200, $this->joinPayload($room, $member, $playlist, $state, $log) + ['hostToken' => $created['hostToken']]];
    }

    private function roomJoin(array $in): array
    {
        $roomId = (string) ($in['roomId'] ?? '');
        $memberId = isset($in['memberId']) && is_string($in['memberId']) && $in['memberId'] !== '' ? $in['memberId'] : null;
        $before = $this->rooms->load($roomId);
        $joined = $this->rooms->join($roomId, (string) ($in['name'] ?? ''), $memberId);
        $room = $joined['room'];
        $member = $joined['member'];
        $log = $this->log($roomId);
        $isNew = $before === null || !isset($before['members'][$member['id']]);
        if ($isNew) {
            $log->append($this->system($member, $member['name'] . ' joined'));
            $this->notify($room, 'member', ['id' => $member['id'], 'name' => $member['name'], 'colour' => $member['colour'], 'event' => 'joined']);
        } elseif (($before['members'][$member['id']]['name'] ?? '') !== $member['name']) {
            $log->append($this->system($member, ($before['members'][$member['id']]['name'] ?? '?') . ' is now ' . $member['name']));
        }
        $path = $this->rooms->path($roomId);
        $playlist = Playlist::load($path);
        $state = PlaybackState::load($path, $playlist['current']);
        return [200, $this->joinPayload($room, $member, $playlist, $state, $log)];
    }

    private function roomGet(array $in): array
    {
        [$room] = $this->requireMember($in);
        $path = $this->rooms->path($room['id']);
        $playlist = Playlist::load($path);
        return [200, ['room' => $this->publicRoom($room), 'playlist' => $playlist, 'state' => PlaybackState::load($path, $playlist['current']), 'actingHostId' => RoomStore::actingHostId($room), 'serverTime' => RoomStore::now()]];
    }

    private function messagesList(array $in): array
    {
        [$room] = $this->requireMember($in);
        $log = $this->log($room['id']);
        $limit = max(1, min(500, (int) ($in['limit'] ?? 100)));
        $since = isset($in['since']) ? max(0, (int) $in['since']) : null;
        $messages = $since === null ? $log->latest($limit) : $log->since($since, $limit);
        return [200, ['messages' => $messages, 'since' => $messages === [] ? ($since ?? 0) : (int) end($messages)['seq'], 'serverTime' => RoomStore::now()]];
    }

    private function playlistGet(array $in): array
    {
        [$room] = $this->requireMember($in);
        return [200, ['playlist' => Playlist::load($this->rooms->path($room['id'])), 'serverTime' => RoomStore::now()]];
    }

    private function stateGet(array $in): array
    {
        [$room] = $this->requireMember($in);
        $path = $this->rooms->path($room['id']);
        $playlist = Playlist::load($path);
        $state = PlaybackState::load($path, $playlist['current']);
        return [200, ['state' => $state, 'expectedPosition' => round(PlaybackState::expectedPosition($state, RoomStore::now()), 3), 'serverTime' => RoomStore::now()]];
    }

    /** What a URL would become as a playlist item, without adding it. */
    private function resolve(array $in): array
    {
        $parsed = Playlist::parseUrl((string) ($in['url'] ?? ''), $this->mediaDir);
        if ($parsed === null) {
            throw new InvalidArgumentException('Not a supported video link.');
        }
        if ($parsed['kind'] === 'youtube-playlist') {
            return [200, ['kind' => 'youtube-playlist', 'list' => $parsed['list'], 'firstVideo' => $parsed['id'], 'note' => 'Playlist contents are read in the browser through the YouTube player; POST the video ids to playlist.import.']];
        }
        $item = Playlist::makeItem($parsed, 'preview', $this->lookupTitles);
        unset($item['id'], $item['addedBy'], $item['addedAt']);
        return [200, $item];
    }

    private function webhookList(array $in): array
    {
        [$room] = $this->requireHost($in);
        return [200, ['webhooks' => Webhooks::listing($room)]];
    }

    private function webhookAdd(array $in): array
    {
        [$room] = $this->requireHost($in);
        [$room, $hook] = Webhooks::add($room, (string) ($in['url'] ?? ''), is_array($in['events'] ?? null) ? $in['events'] : [], (int) $this->config['webhooks_per_room']);
        $this->rooms->save($room);
        return [201, ['webhook' => $hook + ['note' => 'Store the secret now; it is not shown again.']]];
    }

    private function webhookRemove(array $in): array
    {
        [$room] = $this->requireHost($in);
        $room = Webhooks::remove($room, (string) ($in['webhookId'] ?? ''));
        $this->rooms->save($room);
        return [200, ['webhooks' => Webhooks::listing($room)]];
    }

    /** @return array{0: array, 1: array} */
    private function requireHost(array $in): array
    {
        [$room, $member] = $this->requireMember($in);
        if (!$this->rooms->isHost($room, (string) ($in['hostToken'] ?? ''))) {
            throw new UnexpectedValueException('This needs the host token.');
        }
        return [$room, $member];
    }

    private function notify(array $room, string $event, array $payload): void
    {
        if (empty($room['webhooks'])) {
            return;
        }
        $fresh = $this->rooms->load($room['id']) ?? $room;
        $after = Webhooks::dispatch($fresh, $event, $payload, (int) $this->config['webhook_timeout']);
        if ($after['webhooks'] !== $fresh['webhooks']) {
            $this->rooms->save($after);
        }
    }

    private function roomSettings(array $in): array
    {
        [$room] = $this->requireMember($in);
        if (!$this->rooms->isHost($room, (string) ($in['hostToken'] ?? ''))) {
            throw new UnexpectedValueException('Only the host can change room settings.');
        }
        if (isset($in['chatMode'])) {
            $room['chatMode'] = in_array($in['chatMode'], ['overlay', 'docked'], true) ? $in['chatMode'] : $room['chatMode'];
        }
        if (isset($in['guestsControl'])) {
            $room['guestsControl'] = (bool) $in['guestsControl'];
        }
        if (isset($in['hostMemberId']) && isset($room['members'][$in['hostMemberId']])) {
            $room['hostMemberId'] = (string) $in['hostMemberId'];
        }
        $room['updatedAt'] = RoomStore::now();
        $this->rooms->save($room);
        return [200, ['room' => $this->publicRoom($room), 'serverTime' => RoomStore::now()]];
    }

    // ---- chat ----

    private function chatSend(array $in): array
    {
        [$room, $member] = $this->requireMember($in);
        $text = MessageLog::cleanText((string) ($in['text'] ?? ''));
        if ($text === '') {
            throw new InvalidArgumentException('Say something first.');
        }
        $id = (string) ($in['id'] ?? '');
        if (preg_match('/^[A-Za-z0-9_-]{6,64}$/', $id) !== 1) {
            throw new InvalidArgumentException('A client message id is required.');
        }
        $mediaTime = isset($in['mediaTime']) && is_numeric($in['mediaTime']) ? round(max(0, (float) $in['mediaTime']), 2) : null;
        $itemId = isset($in['itemId']) && is_string($in['itemId']) && preg_match('/^[A-Za-z0-9_-]{1,32}$/', $in['itemId']) === 1 ? $in['itemId'] : null;
        $message = [
            'seq' => 0, 'id' => $id, 'kind' => 'chat',
            'memberId' => $member['id'], 'name' => $member['name'], 'colour' => $member['colour'],
            'text' => $text, 'mediaTime' => $mediaTime, 'itemId' => $itemId, 'sentAt' => RoomStore::now(),
        ];
        $stored = $this->log($room['id'])->append($message);
        $this->rooms->touch($room, $member['id']);
        $this->notify($room, 'message', $stored);
        return [200, ['seq' => (int) $stored['seq'], 'message' => $stored, 'serverTime' => RoomStore::now()]];
    }

    private function syncPoll(array $in): array
    {
        [$room, $member] = $this->requireMember($in);
        $room = $this->rooms->touch($room, $member['id']);
        $path = $this->rooms->path($room['id']);
        $since = max(0, (int) ($in['since'] ?? 0));
        $messages = $this->log($room['id'])->since($since, 200);
        $playlist = Playlist::load($path);
        $state = PlaybackState::load($path, $playlist['current']);
        $out = [
            'messages' => $messages,
            'since' => $messages === [] ? $since : (int) end($messages)['seq'],
            'members' => RoomStore::publicMembers($room),
            'actingHostId' => RoomStore::actingHostId($room),
            'serverTime' => RoomStore::now(),
        ];
        if ((int) $playlist['rev'] > (int) ($in['prev'] ?? 0)) {
            $out['playlist'] = $playlist;
        }
        if ((int) $state['rev'] > (int) ($in['srev'] ?? 0)) {
            $out['state'] = $state;
        }
        if (isset($in['rrev']) && (int) $room['updatedAt'] > (int) $in['rrev']) {
            $out['room'] = $this->publicRoom($room);
        }
        $this->maybeGc();
        return [200, $out];
    }

    // ---- playlist ----

    private function playlistAdd(array $in): array
    {
        [$room, $member] = $this->requireMember($in);
        $parsed = Playlist::parseUrl((string) ($in['url'] ?? ''), $this->mediaDir);
        if ($parsed === null) {
            throw new InvalidArgumentException('Use a YouTube link, a YouTube playlist link, an https link to an .mp4/.webm file, or a file from the media folder.');
        }
        if ($parsed['kind'] === 'youtube-playlist') {
            return [200, ['needsImport' => true, 'list' => $parsed['list'], 'firstVideo' => $parsed['id'], 'serverTime' => RoomStore::now()]];
        }
        $this->enforceAddLimit($room, $member['id']);
        $path = $this->rooms->path($room['id']);
        $playlist = Playlist::load($path);
        if (count($playlist['items']) >= Playlist::MAX_ITEMS) {
            throw new OverflowException('The playlist is full (' . Playlist::MAX_ITEMS . ' items).');
        }
        $item = Playlist::makeItem($parsed, $member['id'], $this->lookupTitles);
        $playlist['items'][] = $item;
        $playlist['current'] ??= $item['id'];
        $playlist = Playlist::save($path, $playlist);
        $this->log($room['id'])->append($this->system($member, $member['name'] . ' added ' . $item['title']));
        $this->notify($room, 'playlist', $playlist);
        return [200, ['playlist' => $playlist, 'item' => $item, 'serverTime' => RoomStore::now()]];
    }

    /** The browser resolved a YouTube playlist to video ids through the IFrame API. */
    private function playlistImport(array $in): array
    {
        [$room, $member] = $this->requireMember($in);
        $ids = is_array($in['videoIds'] ?? null) ? array_values(array_unique(array_filter($in['videoIds'], static fn ($v) => is_string($v) && preg_match('/^[A-Za-z0-9_-]{11}$/', $v) === 1))) : [];
        if ($ids === []) {
            throw new InvalidArgumentException('That playlist has no playable videos.');
        }
        $this->enforceAddLimit($room, $member['id']);
        $path = $this->rooms->path($room['id']);
        $playlist = Playlist::load($path);
        $room_left = Playlist::MAX_ITEMS - count($playlist['items']);
        $ids = array_slice($ids, 0, max(0, $room_left));
        $added = 0;
        foreach ($ids as $id) {
            $item = Playlist::makeItem(['kind' => 'youtube', 'id' => $id], $member['id'], $this->lookupTitles && $added < 25);
            $playlist['items'][] = $item;
            $playlist['current'] ??= $item['id'];
            $added++;
        }
        $playlist = Playlist::save($path, $playlist);
        $this->log($room['id'])->append($this->system($member, $member['name'] . ' imported ' . $added . ' videos'));
        return [200, ['playlist' => $playlist, 'added' => $added, 'serverTime' => RoomStore::now()]];
    }

    private function playlistSet(array $in): array
    {
        [$room, $member] = $this->requireMember($in);
        $path = $this->rooms->path($room['id']);
        $playlist = Playlist::load($path);
        $isHost = $this->rooms->isHost($room, (string) ($in['hostToken'] ?? '')) || RoomStore::actingHostId($room) === $member['id'];
        $changed = false;
        if (isset($in['order']) && is_array($in['order'])) {
            if (!$isHost) {
                throw new UnexpectedValueException('Only the host can reorder the playlist.');
            }
            $byId = [];
            foreach ($playlist['items'] as $item) {
                $byId[$item['id']] = $item;
            }
            $ordered = [];
            foreach ($in['order'] as $id) {
                if (is_string($id) && isset($byId[$id])) {
                    $ordered[] = $byId[$id];
                    unset($byId[$id]);
                }
            }
            $playlist['items'] = array_merge($ordered, array_values($byId));
            $changed = true;
        }
        if (isset($in['remove']) && is_string($in['remove'])) {
            if (!$isHost) {
                throw new UnexpectedValueException('Only the host can remove items.');
            }
            $playlist['items'] = array_values(array_filter($playlist['items'], static fn ($i) => $i['id'] !== $in['remove']));
            if ($playlist['current'] === $in['remove']) {
                $playlist['current'] = $playlist['items'][0]['id'] ?? null;
            }
            $changed = true;
        }
        if (isset($in['status']) && is_array($in['status']) && isset($in['status']['itemId'])) {
            // Any member may report that an item failed for everyone (blocked, removed, not embeddable).
            foreach ($playlist['items'] as &$item) {
                if ($item['id'] === $in['status']['itemId']) {
                    $item['status'] = ($in['status']['status'] ?? 'ok') === 'error' ? 'error' : 'ok';
                    $item['error'] = $item['status'] === 'error' ? Text::cut((string) ($in['status']['error'] ?? 'failed'), 120) : null;
                    $changed = true;
                }
            }
            unset($item);
        }
        if (isset($in['current']) && is_string($in['current'])) {
            if (!$isHost && !$room['guestsControl']) {
                throw new UnexpectedValueException('Only the host can change what is playing.');
            }
            if (Playlist::find($playlist, $in['current']) === null) {
                throw new InvalidArgumentException('That item is not in the playlist.');
            }
            $playlist['current'] = $in['current'];
            $changed = true;
            $state = PlaybackState::load($path, $playlist['current']);
            PlaybackState::apply($path, $state, ['itemId' => $in['current'], 'playing' => true, 'mediaTime' => 0, 'rate' => 1], $member['id']);
        }
        if ($changed) {
            $playlist = Playlist::save($path, $playlist);
            $this->notify($room, 'playlist', $playlist);
        }
        $state = PlaybackState::load($path, $playlist['current']);
        return [200, ['playlist' => $playlist, 'state' => $state, 'serverTime' => RoomStore::now()]];
    }

    // ---- playback state ----

    private function stateSet(array $in): array
    {
        [$room, $member] = $this->requireMember($in);
        $isHost = $this->rooms->isHost($room, (string) ($in['hostToken'] ?? '')) || RoomStore::actingHostId($room) === $member['id'];
        if (!$isHost && !$room['guestsControl']) {
            throw new UnexpectedValueException('Only the host controls playback in this room.');
        }
        $update = is_array($in['state'] ?? null) ? $in['state'] : [];
        $path = $this->rooms->path($room['id']);
        $playlist = Playlist::load($path);
        $current = PlaybackState::load($path, $playlist['current']);
        if (isset($update['itemId']) && Playlist::find($playlist, (string) $update['itemId']) === null) {
            throw new InvalidArgumentException('That item is not in the playlist.');
        }
        $state = PlaybackState::apply($path, $current, $update, $member['id']);
        if ($state === null) {
            return [409, ['error' => 'Someone else changed playback first.', 'code' => 'stale', 'state' => $current, 'serverTime' => RoomStore::now()]];
        }
        if (isset($update['itemId']) && $update['itemId'] !== $playlist['current']) {
            $playlist['current'] = (string) $update['itemId'];
            Playlist::save($path, $playlist);
        }
        $this->notify($room, 'state', $state);
        return [200, ['state' => $state, 'serverTime' => RoomStore::now()]];
    }

    // ---- health ----

    /** Self-checks the server side; the client shows any failure and the CLI selftest uses it too. */
    public function health(): array
    {
        $checks = [];
        $checks[] = ['name' => 'php', 'ok' => PHP_VERSION_ID >= 80100, 'detail' => PHP_VERSION];
        $checks[] = ['name' => 'json', 'ok' => function_exists('json_encode'), 'detail' => 'ext-json'];
        $checks[] = ['name' => 'mbstring', 'ok' => true, 'detail' => function_exists('mb_substr') ? 'ext-mbstring' : 'fallback cutter'];
        $dir = $this->rooms->dir();
        $writable = (is_dir($dir) || @mkdir($dir, 0775, true)) && is_writable($dir);
        $checks[] = ['name' => 'rooms_writable', 'ok' => $writable, 'detail' => $dir];
        if ($writable) {
            $probe = $dir . '/.probe-' . bin2hex(random_bytes(3));
            $roundTrip = @file_put_contents($probe, 'ok') === 2 && @file_get_contents($probe) === 'ok';
            @unlink($probe);
            $checks[] = ['name' => 'rooms_roundtrip', 'ok' => $roundTrip, 'detail' => 'write+read+delete'];
            $free = @disk_free_space($dir);
            $checks[] = ['name' => 'disk', 'ok' => $free === false || $free > 50 * 1024 * 1024, 'detail' => $free === false ? 'unknown' : round($free / 1048576) . ' MB free'];
        }
        $checks[] = ['name' => 'media_dir', 'ok' => true, 'detail' => is_dir($this->mediaDir) ? count(Source::library($this->mediaDir)) . ' file(s)' : 'absent (URLs only)'];
        $checks[] = ['name' => 'outbound_https', 'ok' => true, 'detail' => function_exists('curl_init') ? 'curl' : (ini_get('allow_url_fopen') ? 'streams' : 'none: YouTube titles unavailable')];
        $checks[] = ['name' => 'clock', 'ok' => true, 'detail' => (string) RoomStore::now()];
        $ok = array_reduce($checks, static fn (bool $c, array $x) => $c && $x['ok'], true);
        return ['ok' => $ok, 'checks' => $checks, 'serverTime' => RoomStore::now()];
    }

    // ---- helpers ----

    private function joinPayload(array $room, array $member, array $playlist, array $state, MessageLog $log): array
    {
        $history = $log->latest(50);
        return [
            'room' => $this->publicRoom($room),
            'memberId' => $member['id'],
            'playlist' => $playlist,
            'state' => $state,
            'messages' => $history,
            'since' => $history === [] ? 0 : (int) end($history)['seq'],
            'actingHostId' => RoomStore::actingHostId($room),
            'serverTime' => RoomStore::now(),
        ];
    }

    /** @return array{0: array, 1: array} */
    private function requireMember(array $in): array
    {
        $room = $this->rooms->load((string) ($in['roomId'] ?? ''));
        if ($room === null) {
            throw new RuntimeException('That room does not exist or has expired.');
        }
        $memberId = (string) ($in['memberId'] ?? '');
        if (!isset($room['members'][$memberId])) {
            throw new InvalidArgumentException('Join the room first.');
        }
        return [$room, $room['members'][$memberId]];
    }

    private function enforceAddLimit(array $room, string $memberId): void
    {
        $file = $this->rooms->path($room['id']) . '/adds-' . $memberId . '.json';
        $now = RoomStore::now();
        $times = is_file($file) ? (array) json_decode((string) file_get_contents($file), true) : [];
        $times = array_values(array_filter($times, static fn ($t) => is_int($t) && $now - $t < Playlist::ADD_LIMIT_WINDOW_MS));
        if (count($times) >= Playlist::ADD_LIMIT_COUNT) {
            throw new OverflowException('Slow down: at most ' . Playlist::ADD_LIMIT_COUNT . ' additions per minute.');
        }
        $times[] = $now;
        file_put_contents($file, json_encode($times));
    }

    private function system(array $member, string $text): array
    {
        return [
            'seq' => 0, 'id' => 's_' . bin2hex(random_bytes(6)), 'kind' => 'system',
            'memberId' => $member['id'], 'name' => $member['name'], 'colour' => $member['colour'],
            'text' => $text, 'mediaTime' => null, 'itemId' => null, 'sentAt' => RoomStore::now(),
        ];
    }

    private function publicRoom(array $room): array
    {
        return [
            'id' => $room['id'],
            'createdAt' => $room['createdAt'],
            'updatedAt' => $room['updatedAt'],
            'chatMode' => $room['chatMode'],
            'guestsControl' => $room['guestsControl'],
            'hostMemberId' => $room['hostMemberId'],
            'members' => RoomStore::publicMembers($room),
        ];
    }

    private function log(string $roomId): MessageLog
    {
        return new MessageLog($this->rooms->path($roomId) . '/messages.jsonl');
    }

    private function maybeGc(): void
    {
        if (random_int(1, 50) === 1) {
            $this->rooms->gc((int) $this->config['room_max_age']);
        }
    }
}
