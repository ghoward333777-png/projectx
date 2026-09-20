<?php

declare(strict_types=1);

require_once __DIR__ . '/../dating/SlowDatingApi.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

putenv(SlowDatingApi::WEBHOOK_SECRET_ENV . '=test-webhook-secret');

$stateDir = sys_get_temp_dir() . '/slowdating-api-test-' . getmypid();
exec('rm -rf ' . escapeshellarg($stateDir));
$api = new SlowDatingApi(new SlowDatingEngine(new SlowDatingStore($stateDir)));
$t0 = gmmktime(12, 0, 0, 1, 1, 2026);

/** @return array{0: int, 1: mixed} */
function call(SlowDatingApi $api, string $method, string $path, array $query = [], array $body = [], ?string $token = null, int $now = 0, array $extraHeaders = []): array
{
    $headers = $extraHeaders;
    if ($token !== null) {
        $headers['authorization'] = 'Bearer ' . $token;
    }
    return $api->route($method, $path, $query, $body, $headers, $now);
}

// ---- Signup & auth ---------------------------------------------------------
[$status, $alice] = call($api, 'POST', '/auth/signup', [], ['email' => 'alice@example.com', 'use_auto_password' => true], null, $t0);
contract_check($status === 201 && isset($alice['token'], $alice['auto_password']), 'signup must return a token and the one-time auto password');
[$status, $bob] = call($api, 'POST', '/auth/signup', [], ['email' => 'bob@example.com', 'password' => 'Str0ng!Passw0rd#'], null, $t0);
contract_check($status === 201, 'signup with a strong chosen password must succeed');
[$status, $weak] = call($api, 'POST', '/auth/signup', [], ['email' => 'weak@example.com', 'password' => 'weakpass'], null, $t0);
contract_check($status === 422, 'weak passwords must be rejected with 422');
[$status] = call($api, 'GET', '/users/me/profile', [], [], null, $t0);
contract_check($status === 401, 'protected routes must require a bearer token');

// ---- Profiles ----------------------------------------------------------------
[$status] = call($api, 'PATCH', '/users/me/profile', [], [
    'display_name' => 'Alice', 'age' => 27, 'gender' => 'female', 'zip_code' => '90210',
    'interests' => 'jazz, travel', 'dating_type' => 'long_term', 'income_range' => '60k_100k',
    'automobile' => 'ev', 'occupation_category' => 'tech', 'politics' => 'moderate',
], $alice['token'], $t0);
contract_check($status === 200, 'profile updates must succeed');
call($api, 'PATCH', '/users/me/profile', [], [
    'display_name' => 'Bob', 'age' => 31, 'gender' => 'male', 'zip_code' => '90211',
    'interests' => 'jazz', 'dating_type' => 'long_term',
], $bob['token'], $t0);
[$status, $video] = call($api, 'POST', '/users/me/profile/videos', [], ['youtube_url' => 'https://youtu.be/dQw4w9WgXcQ'], $alice['token'], $t0);
contract_check($status === 201 && $video['embed_url'] === 'https://www.youtube.com/embed/dQw4w9WgXcQ', 'video embedding must work over the API');

// ---- Search, matches, popularity ----------------------------------------------
[$status, $results] = call($api, 'GET', '/users/search', ['gender' => 'female', 'income_range' => '60k_100k'], [], $bob['token'], $t0);
contract_check($status === 200 && count($results) === 1, 'search with income filters must work over the API');
[$status, $prefs] = call($api, 'PATCH', '/users/me/preferences', [], ['seeking_gender' => 'female', 'age_min' => 21, 'age_max' => 35, 'max_distance_km' => 50], $bob['token'], $t0);
contract_check($status === 200 && $prefs['seeking_gender'] === 'female', 'preferences must save over the API');
[$status, $browse] = call($api, 'GET', '/browse', [], [], $bob['token'], $t0);
contract_check($status === 200 && count($browse) === 1 && $browse[0]['user_id'] === $alice['user_id'], 'browse must return preference-filtered best matches');
[$status, $matches] = call($api, 'GET', '/matches', [], [], $bob['token'], $t0);
contract_check($status === 200 && $matches[0]['user_id'] === $alice['user_id'], 'matches must rank Alice first for Bob');
[$status, $pop] = call($api, 'GET', '/users/' . $alice['user_id'] . '/popularity', [], [], $bob['token'], $t0);
contract_check($status === 200 && isset($pop['popularity_score']), 'popularity lookup must work');
[$status] = call($api, 'GET', '/users/' . $alice['user_id'] . '/popularity/breakdown', [], [], $bob['token'], $t0);
contract_check($status === 403, 'the popularity breakdown is owner-only');
[$status, $breakdown] = call($api, 'GET', '/users/me/popularity/breakdown', [], [], $alice['token'], $t0);
contract_check($status === 200 && $breakdown['metrics']['profile_view'] === 1, 'viewing another profile must record a profile_view event');

// ---- Slow chat over the API -----------------------------------------------------
[$status, $chat] = call($api, 'POST', '/chats', [], ['user_id' => $alice['user_id']], $bob['token'], $t0);
contract_check($status === 201, 'starting a chat must succeed');
$chatId = (string) $chat['id'];
[$status, $message] = call($api, 'POST', '/chats/' . $chatId . '/messages', [], ['text' => 'Email me: bob@fastmail.com'], $bob['token'], $t0 + 60);
contract_check($status === 201 && !str_contains($message['text'], 'fastmail'), 'contact data must be erased in the slow-chat stage');
[$status, $chatStatus] = call($api, 'GET', '/chats/' . $chatId . '/status', [], [], $bob['token'], $t0 + 60);
contract_check($chatStatus['stage'] === 'slow_chat' && $chatStatus['daily_message_limit'] === 5, 'chat status must report slow-chat pacing');

// ---- Three pictures & per-chat reveal ---------------------------------------------
$png = base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==');
$api->engine()->setMemberPhoto($alice['user_id'], $png, 'image/png', 'private');
[$status, $roster] = call($api, 'GET', '/users/me/pictures', [], [], $alice['token'], $t0);
contract_check($status === 200 && $roster['generated'] && $roster['private'] && !$roster['public'], 'the picture roster must be served over the API');
[$status, $choice] = call($api, 'POST', '/chats/' . $chatId . '/image', [], ['choice' => 'private'], $alice['token'], $t0);
contract_check($status === 200 && $choice['image_choice'] === 'private', 'a member must be able to choose their chat picture over the API');
[$status] = call($api, 'POST', '/chats/' . $chatId . '/image', [], ['choice' => 'public'], $bob['token'], $t0);
contract_check($status === 422, 'choosing a picture that is not uploaded must fail over the API');

// ---- Partner portal over the API ------------------------------------------------
[$status, $partner] = call($api, 'POST', '/partners/v1/signup', [], [
    'business_name' => 'Blue Note Lounge', 'email' => 'owner@bluenote.example',
    'password' => 'Partner!Pass123', 'plan_tier' => 'pro',
], null, $t0);
contract_check($status === 201, 'partner signup must succeed');
[$status, $venue] = call($api, 'POST', '/partners/v1/venues', [], [
    'name' => 'Blue Note Lounge', 'zip_code' => '90210', 'category' => 'lounge',
    'atmosphere_tags' => ['jazz', 'quiet', 'romantic'],
], $partner['token'], $t0);
contract_check($status === 201, 'venue creation must succeed');
$venueId = (string) $venue['id'];
[$status, $coupon] = call($api, 'POST', '/partners/v1/venues/' . $venueId . '/coupons/targeted', [], [
    'discount_type' => 'percent', 'discount_amount' => 20, 'max_recipients' => 5,
    'targeting' => ['gender' => 'female', 'age_min' => 18, 'age_max' => 30, 'zip_radius_km' => 20],
], $partner['token'], $t0);
contract_check($status === 201 && $coupon['estimated_reach'] === 1, 'targeted coupons must reach the matching segment');
[$status, $wallet] = call($api, 'GET', '/users/me/coupons', [], [], $alice['token'], $t0);
contract_check($status === 200 && count($wallet) === 1, 'targeted members must see the coupon in their wallet');
[$status] = call($api, 'POST', '/coupons/' . $coupon['id'] . '/redeem', [], [], $alice['token'], $t0 + 3600);
contract_check($status === 201, 'coupon redemption must succeed');

[$status, $event] = call($api, 'POST', '/partners/v1/venues/' . $venueId . '/events', [], [
    'title' => 'Singles Jazz Night', 'capacity' => 40, 'ticket_price' => 25.0, 'tags' => ['singles'],
], $partner['token'], $t0);
contract_check($status === 201, 'event creation must succeed');
[$status, $contest] = call($api, 'POST', '/partners/v1/venues/' . $venueId . '/contests', [], [
    'prize' => 'Dinner for two', 'event_id' => (string) $event['id'],
], $partner['token'], $t0);
contract_check($status === 201, 'contest creation must succeed');
[$status, $ticket] = call($api, 'POST', '/events/' . $event['id'] . '/tickets', [], ['quantity' => 2], $alice['token'], $t0 + 7200);
contract_check($status === 201 && (float) $ticket['total_amount'] === 50.0, 'members must be able to buy event tickets');
[$status, $entries] = call($api, 'GET', '/partners/v1/contests/' . $contest['id'] . '/entries', [], [], $partner['token'], $t0);
contract_check($status === 200 && $entries['entries_count'] === 1, 'contest entries must aggregate ticket buyers');
[$status, $analytics] = call($api, 'GET', '/partners/v1/venues/' . $venueId . '/analytics', [], [], $partner['token'], $t0);
contract_check($status === 200 && $analytics['total_tickets_sold'] === 2 && $analytics['total_redemptions'] === 1, 'venue analytics must roll up over the API');

// Partners cannot call member routes with a partner token.
[$status] = call($api, 'GET', '/users/me/profile', [], [], $partner['token'], $t0);
contract_check($status === 404, 'member routes must not resolve for partner tokens');

// ---- Marketplace -----------------------------------------------------------------
[$status, $product] = call($api, 'POST', '/partners/v1/venues/' . $venueId . '/products', [], [
    'name' => 'Date Night Kit', 'price' => 39.99, 'inventory' => 5,
], $partner['token'], $t0);
contract_check($status === 201, 'product creation must succeed');
[$status, $order] = call($api, 'POST', '/orders', [], ['product_id' => (string) $product['id'], 'quantity' => 1], $alice['token'], $t0);
contract_check($status === 201 && (float) $order['total_price'] === 39.99, 'orders must succeed over the API');

// ---- Concierge & safety ------------------------------------------------------------
call($api, 'POST', '/chats/' . $chatId . '/messages', [], ['text' => 'I love jazz nights'], $alice['token'], $t0 + 300);
[$status, $suggestions] = call($api, 'GET', '/chats/' . $chatId . '/concierge', [], [], $bob['token'], $t0 + 400);
contract_check($status === 200 && $suggestions[0]['venue_name'] === 'Blue Note Lounge', 'the concierge must suggest the jazz lounge');
[$status, $resources] = call($api, 'GET', '/users/me/safety/resources', [], [], $alice['token'], $t0);
contract_check($status === 200 && isset($resources['red_flags']), 'safety resources must be served to members');
[$status, $public] = call($api, 'GET', '/safety/resources', [], [], null, $t0);
contract_check($status === 200 && isset($public['first_date_checklist']), 'safety education must also be public');

// ---- Admin rewards -------------------------------------------------------------------
[$status, $admin] = call($api, 'POST', '/admin/v1/bootstrap', [], ['email' => 'admin@slowdating.example'], null, $t0);
contract_check($status === 201 && isset($admin['token']), 'admin bootstrap must succeed once');
[$status] = call($api, 'POST', '/admin/v1/bootstrap', [], ['email' => 'rogue@slowdating.example'], null, $t0);
contract_check($status === 422, 'a second bootstrap must be rejected');
[$status, $board] = call($api, 'GET', '/admin/v1/leaderboard', ['count' => 10], [], $admin['token'], $t0);
contract_check($status === 200 && count($board) === 2, 'the admin leaderboard must list members');
[$status, $campaign] = call($api, 'POST', '/admin/v1/rewards/top', [], [
    'cohort' => 10, 'benefit' => ['type' => 'gift_certificate', 'amount' => 100.0],
], $admin['token'], $t0);
contract_check($status === 201 && $campaign['granted'] === 2, 'reward campaigns must grant to the whole cohort');
[$status, $rewards] = call($api, 'GET', '/users/me/rewards', [], [], $alice['token'], $t0);
contract_check($status === 200 && $rewards[0]['reward_type'] === 'gift_certificate', 'members must see their granted rewards');
[$status, $settings] = call($api, 'PATCH', '/admin/v1/settings', [], ['avatar_mode' => 'uploads'], $admin['token'], $t0);
contract_check($status === 200 && $settings['avatar_mode'] === 'uploads', 'admins must switch the image mode over the API');
[$status, $settings] = call($api, 'GET', '/admin/v1/settings', [], [], $admin['token'], $t0);
contract_check($status === 200 && $settings['avatar_mode'] === 'uploads', 'the image mode must read back');
call($api, 'PATCH', '/admin/v1/settings', [], ['avatar_mode' => 'generated'], $admin['token'], $t0);
[$status] = call($api, 'GET', '/admin/v1/leaderboard', [], [], $alice['token'], $t0);
contract_check($status === 404, 'admin routes must not resolve for member tokens');

// ---- Webhooks ---------------------------------------------------------------------------
[$status] = call($api, 'POST', '/webhooks/tickets/purchased', [], ['event_id' => (string) $event['id']], null, $t0);
contract_check($status === 401, 'webhooks without the shared secret must be rejected');
[$status, $hook] = call($api, 'POST', '/webhooks/bookings/created', [], [
    'booking_id' => 'bk_555', 'venue_external_id' => 'ven_321',
    'user_external_id' => $alice['user_id'], 'party_size' => 2, 'status' => 'confirmed',
], null, $t0, ['x-webhook-signature' => 'test-webhook-secret']);
contract_check($status === 200 && $hook['status'] === 'recorded', 'signed booking webhooks must record');

exec('rm -rf ' . escapeshellarg($stateDir));
fwrite(STDOUT, "Dating API contract passed\n");
