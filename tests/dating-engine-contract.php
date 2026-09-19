<?php

declare(strict_types=1);

require_once __DIR__ . '/../dating/SlowDatingEngine.php';

function contract_check(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "FAIL: {$message}\n");
        exit(1);
    }
}

$stateDir = sys_get_temp_dir() . '/slowdating-engine-test-' . getmypid();
exec('rm -rf ' . escapeshellarg($stateDir));
$engine = new SlowDatingEngine(new SlowDatingStore($stateDir));
$t0 = gmmktime(12, 0, 0, 1, 1, 2026);

// ---- Passwords & signup ---------------------------------------------------
$password = $engine->generateStrongPassword();
contract_check(strlen($password) >= 16, 'auto password must be at least 16 characters');
contract_check($engine->passwordProblems($password) === [], 'auto password must pass the strong policy');
contract_check($engine->passwordProblems('short1!') !== [], 'short passwords must be rejected');
contract_check($engine->passwordProblems('alllowercaseletters') !== [], 'single-class passwords must be rejected');
contract_check($engine->passwordProblems('Password123!') === [], 'a compliant password must pass');

$alice = $engine->signupMember('alice@example.com', null, true, $t0);
contract_check($alice['password_generated'] && $alice['auto_password'] !== null, 'auto password must be returned once at signup');
contract_check(preg_match('/^U\d{8}-[A-Z0-9]{5}$/', $alice['user_id']) === 1, 'user ids are platform generated');
$bob = $engine->signupMember('bob@example.com', 'Str0ng!Passw0rd#', false, $t0);
contract_check(!$bob['password_generated'], 'a user-chosen strong password must be accepted');
$threw = false;
try {
    $engine->signupMember('carol@example.com', 'weakpass', false, $t0);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'weak user-chosen passwords must be rejected');
$carol = $engine->signupMember('carol@example.com', null, true, $t0);
$dave = $engine->signupMember('dave@example.com', null, true, $t0);

$session = $engine->login('bob@example.com', 'Str0ng!Passw0rd#', $t0);
contract_check($engine->authenticate($session['token']) === [$bob['user_id'], 'member'], 'login tokens must authenticate');

// ---- Profiles & YouTube ---------------------------------------------------
$engine->updateProfile($alice['user_id'], [
    'display_name' => 'Alice', 'age' => 29, 'gender' => 'female', 'zip_code' => '90210',
    'interests' => 'jazz, italian food, travel', 'hobbies' => ['hiking', 'photography'],
    'outdoor_activities' => 'hiking', 'dating_type' => 'long_term', 'faith' => 'none',
    'politics' => 'moderate', 'income_range' => '60k_100k', 'automobile' => 'ev',
    'occupation_category' => 'tech',
]);
$engine->updateProfile($bob['user_id'], [
    'display_name' => 'Bob', 'age' => 33, 'gender' => 'male', 'zip_code' => '90211',
    'interests' => 'jazz, travel', 'hobbies' => 'hiking', 'outdoor_activities' => 'hiking',
    'dating_type' => 'long_term', 'faith' => 'none', 'politics' => 'moderate',
    'income_range' => '100k_150k', 'automobile' => 'sedan', 'occupation_category' => 'tech',
]);
$engine->updateProfile($carol['user_id'], [
    'display_name' => 'Carol', 'age' => 41, 'gender' => 'female', 'zip_code' => '10001',
    'interests' => 'opera', 'dating_type' => 'marriage', 'faith' => 'christian',
    'politics' => 'conservative', 'income_range' => '150k_plus', 'automobile' => 'luxury',
    'occupation_category' => 'finance',
]);
$engine->updateProfile($dave['user_id'], [
    'display_name' => 'Dave', 'age' => 27, 'gender' => 'male', 'zip_code' => '90210',
    'interests' => 'italian food', 'dating_type' => 'casual', 'politics' => 'liberal',
]);
$threw = false;
try {
    $engine->updateProfile($dave['user_id'], ['age' => 17]);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'members under 18 must be rejected');

$video = $engine->addProfileVideo($alice['user_id'], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
contract_check($video['embed_url'] === 'https://www.youtube.com/embed/dQw4w9WgXcQ', 'embed URLs are derived server side');
contract_check($engine->youtubeVideoKey('https://youtu.be/dQw4w9WgXcQ') === 'dQw4w9WgXcQ', 'youtu.be links must parse');
contract_check($engine->youtubeVideoKey('https://evil.example.com/watch?v=x') === null, 'non-YouTube hosts must be rejected');
$engine->removeProfileVideo($alice['user_id'], $video['video_id']);
contract_check($engine->profile($alice['user_id'])['videos'] === [], 'removed videos must disappear');

// ---- Slow chat: pacing, filtering, unlock ----------------------------------
$chat = $engine->startChat($bob['user_id'], $alice['user_id'], $t0);
$chatId = (string) $chat['id'];
$status = $engine->chatStatus($chatId, $t0);
contract_check($status['stage'] === 'slow_chat' && $status['daily_message_limit'] === 5 && $status['message_size_limit'] === 280, 'week one runs at 5 messages/day and 280 chars');
contract_check($status['contact_sharing_allowed'] === false, 'contact sharing is blocked before unlock');

$message = $engine->sendMessage($chatId, $bob['user_id'], 'Call me at 310-555-1234 or bob@fastmail.com — or IG @bobster99', $t0 + 60);
contract_check(!str_contains($message['text'], '310') && !str_contains($message['text'], 'fastmail') && !str_contains($message['text'], 'bobster99'), 'phone, email, and handles must be erased before unlock');
contract_check($message['contact_data_removed'] >= 3, 'the filter must report the erased contact data');

$threw = false;
try {
    $engine->sendMessage($chatId, $bob['user_id'], str_repeat('a', 281), $t0 + 120);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'oversized slow-chat messages must be rejected');

for ($i = 0; $i < 4; $i++) {
    $engine->sendMessage($chatId, $bob['user_id'], 'Slow message ' . $i, $t0 + 200 + $i);
}
$threw = false;
try {
    $engine->sendMessage($chatId, $bob['user_id'], 'One too many today', $t0 + 300);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'the daily slow-chat message quota must be enforced');

$flagged = $engine->sendMessage($chatId, $alice['user_id'], 'Please wire me money before it\'s too late', $t0 + 400);
contract_check($flagged['red_flags'] !== [], 'red-flag messages must be flagged');
contract_check($engine->safetyEventsFor($bob['user_id']) !== [], 'a safety event must protect the recipient');

// Ten two-sided sessions across 31 days -> unlock.
for ($day = 1; $day <= 10; $day++) {
    $ts = $t0 + $day * 86400;
    $engine->sendMessage($chatId, $bob['user_id'], 'Day ' . $day . ' hello', $ts);
    $engine->sendMessage($chatId, $alice['user_id'], 'Day ' . $day . ' reply', $ts + 60);
}
$at29 = $engine->chatStatus($chatId, $t0 + 29 * 86400);
contract_check($at29['unlocked'] === false, '10 sessions alone must not unlock before 30 days');
$at31 = $engine->chatStatus($chatId, $t0 + 31 * 86400);
contract_check($at31['unlocked'] === true && $at31['contact_sharing_allowed'] === true, '30 days + 10 sessions must unlock real-time chat and contact sharing');
$open = $engine->sendMessage($chatId, $bob['user_id'], 'Now you can reach me at bob@fastmail.com', $t0 + 31 * 86400);
contract_check(str_contains($open['text'], 'bob@fastmail.com'), 'after unlock contact info flows through unfiltered');

// Early unlock is a VIP feature.
$chat2 = $engine->startChat($dave['user_id'], $carol['user_id'], $t0);
$threw = false;
try {
    $engine->purchaseEarlyUnlock((string) $chat2['id'], $dave['user_id'], $t0);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'early unlock must require a VIP membership');
$engine->subscribeMembership($dave['user_id'], 'vip', $t0);
$unlocked = $engine->purchaseEarlyUnlock((string) $chat2['id'], $dave['user_id'], $t0);
contract_check($unlocked['unlocked'] === true, 'VIP members can purchase early unlock');

// ---- Popularity -------------------------------------------------------------
$breakdown = $engine->popularityBreakdown($alice['user_id'], $t0 + 40 * 86400);
contract_check($breakdown['metrics']['chat_request'] === 1, 'starting a chat records a chat request for the recipient');
contract_check($breakdown['metrics']['message_received'] > 0, 'received messages count toward popularity');
$engine->recordPopularityEvent($alice['user_id'], 'photo_received', $t0 + 40 * 86400);
$pop = $engine->popularity($alice['user_id'], $t0 + 40 * 86400);
contract_check($pop['popularity_score'] >= 0 && $pop['popularity_score'] <= 100, 'popularity is normalized 0-100');
$popCarol = $engine->popularity($carol['user_id'], $t0 + 40 * 86400);
contract_check($pop['popularity_score'] > $popCarol['popularity_score'], 'engaged members outrank quiet ones in the same gender cohort');

// ---- Search & matching --------------------------------------------------------
$results = $engine->searchUsers(['gender' => 'female', 'faith' => 'christian'], $t0);
contract_check(count($results) === 1 && $results[0]['user_id'] === $carol['user_id'], 'faith + gender filters must narrow search');
$results = $engine->searchUsers(['income_range' => '150k_plus', 'automobile' => 'luxury', 'occupation_category' => 'finance'], $t0);
contract_check(count($results) === 1 && $results[0]['user_id'] === $carol['user_id'], 'income, automobile, and occupation filters must work');
$results = $engine->searchUsers(['interests' => 'jazz', 'zip_code' => '90210', 'zip_radius_km' => 20], $t0);
contract_check(count($results) === 2, 'interest + zip radius search must find both jazz fans near 90210');

$matches = $engine->matchesFor($bob['user_id'], [], $t0);
contract_check($matches !== [] && $matches[0]['user_id'] === $alice['user_id'], 'the most compatible nearby member must rank first');
contract_check(in_array('jazz', $matches[0]['shared_interests'], true), 'shared interests must surface in matches');
contract_check(abs(array_sum(SlowDatingEngine::MATCH_WEIGHTS) - 1.0) < 0.0001, 'match weights must sum to 1.0');
contract_check($engine->zipProximityKm('90210', '90210') === 0.0, 'identical zips are distance zero');
contract_check($engine->zipProximityKm('90210', '10001') > $engine->zipProximityKm('90210', '90211'), 'zip proximity must order near before far');

// ---- Partner ecosystem ----------------------------------------------------------
$partner = $engine->signupPartner('Blue Note Lounge', 'owner@bluenote.example', 'Partner!Pass123', 'pro', $t0);
$venue = $engine->createVenue($partner['partner_id'], [
    'name' => 'Blue Note Lounge', 'zip_code' => '90210', 'category' => 'lounge',
    'atmosphere_tags' => ['jazz', 'quiet', 'romantic'],
], $t0);
$venueId = (string) $venue['id'];

$coupon = $engine->createTargetedCoupon($partner['partner_id'], $venueId, [
    'discount_type' => 'percent', 'discount_amount' => 20, 'max_recipients' => 10,
    'valid_from' => $t0, 'valid_to' => $t0 + 30 * 86400,
], ['gender' => 'female', 'age_min' => 18, 'age_max' => 30, 'zip_radius_km' => 20], $t0);
contract_check($coupon['recipients'] === [$alice['user_id']], 'targeting "women 18-30 near the venue" must reach exactly Alice');
$memberCoupons = $engine->couponsForMember($alice['user_id']);
contract_check(count($memberCoupons) === 1, 'targeted members must see their coupon');
$engine->redeemCoupon((string) $coupon['id'], $alice['user_id'], $t0 + 86400);
contract_check($engine->couponsForMember($alice['user_id']) === [], 'redeemed coupons must leave the wallet');
$threw = false;
try {
    $engine->redeemCoupon((string) $coupon['id'], $alice['user_id'], $t0 + 86400);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'double redemption must be rejected');

$basicPartner = $engine->signupPartner('Tiny Cafe', 'owner@tinycafe.example', 'Partner!Pass123', 'basic', $t0);
$threw = false;
try {
    $basicVenue = $engine->createVenue($basicPartner['partner_id'], ['name' => 'Tiny Cafe', 'zip_code' => '90210', 'category' => 'restaurant'], $t0);
    $engine->createTargetedCoupon($basicPartner['partner_id'], (string) $basicVenue['id'], ['discount_type' => 'percent', 'discount_amount' => 10], [], $t0);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'targeted coupons must require the Pro or Elite plan');

$event = $engine->createEvent($partner['partner_id'], $venueId, [
    'title' => 'Singles Jazz Night', 'capacity' => 40, 'tags' => ['singles', 'jazz'], 'ticket_price' => 25.0,
    'date_time' => $t0 + 14 * 86400,
], $t0);
$contest = $engine->createContest($partner['partner_id'], $venueId, [
    'prize' => 'Dinner for two', 'event_id' => (string) $event['id'],
    'start_date' => $t0, 'end_date' => $t0 + 30 * 86400,
], $t0);
$ticket = $engine->buyTicket((string) $event['id'], $alice['user_id'], 2, $t0 + 86400);
contract_check((float) $ticket['total_amount'] === 50.0, 'ticket totals must multiply price by quantity');
$entries = $engine->contestEntries((string) $contest['id']);
contract_check($entries['entries_count'] === 1, 'ticket buyers must be entered into the contest automatically');

$product = $engine->createProduct($partner['partner_id'], $venueId, ['name' => 'Date Night Kit', 'price' => 39.99, 'inventory' => 5], $t0);
$order = $engine->placeOrder($alice['user_id'], (string) $product['id'], 2, $t0);
contract_check((float) $order['total_price'] === 79.98, 'orders must total price times quantity');
contract_check((int) $engine->products($venueId)[0]['inventory'] === 3, 'orders must draw down inventory');

$analytics = $engine->venueAnalytics($venueId);
contract_check($analytics['total_redemptions'] === 1 && $analytics['total_tickets_sold'] === 2, 'venue analytics must roll up redemptions and tickets');

// ---- Concierge --------------------------------------------------------------
$suggestions = $engine->conciergeSuggestions($chatId, $t0);
contract_check($suggestions !== [], 'the concierge must suggest venues for an active chat');
$engine->sendMessage($chatId, $alice['user_id'], 'I love jazz and quiet places', $t0 + 32 * 86400);
$suggestions = $engine->conciergeSuggestions($chatId, $t0 + 32 * 86400);
contract_check($suggestions[0]['venue_name'] === 'Blue Note Lounge', 'chat topics must steer concierge suggestions');

// ---- Admin rewards -------------------------------------------------------------
$admin = $engine->createAdmin('admin@slowdating.example', null, null, $t0);
contract_check($admin['auto_password'] !== null, 'the bootstrap admin gets a generated strong password');
$threw = false;
try {
    $engine->createAdmin('rogue@slowdating.example', null, null, $t0);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'after bootstrap only admins can create admins');

$top = $engine->topMembers(10, $t0 + 40 * 86400);
contract_check($top[0]['user_id'] === $alice['user_id'], 'the leaderboard must rank the most popular member first');
$campaign = $engine->grantTopMemberRewards($admin['admin_id'], 10, ['type' => 'free_membership', 'membership_tier' => 'member'], $t0 + 40 * 86400);
contract_check($campaign['granted'] === 4, 'a top-10 campaign with 4 members must grant 4 rewards');
$aliceRewards = $engine->rewardsFor($alice['user_id']);
contract_check(count($aliceRewards) === 1 && $aliceRewards[0]['reward_type'] === 'free_membership', 'top members must receive the reward record');
$aliceUser = $engine->store()->get('users', $alice['user_id']);
contract_check($aliceUser['membership_tier'] === 'member', 'free membership rewards must apply immediately');
$threw = false;
try {
    $engine->grantTopMemberRewards($admin['admin_id'], 25, ['type' => 'promo_trip', 'description' => 'x'], $t0);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'reward cohorts other than 10/50/100 must be rejected');
$trip = $engine->grantTopMemberRewards($admin['admin_id'], 50, ['type' => 'promo_trip', 'description' => 'All-expense weekend at the launch gala'], $t0 + 40 * 86400);
contract_check($trip['granted'] === 4, 'promo trip campaigns must cover every member of a small cohort');

// ---- Webhooks -----------------------------------------------------------------
$hook = $engine->ingestTicketWebhook([
    'event_id' => (string) $event['id'], 'external_ticket_id' => 'tix_987',
    'user_external_id' => $bob['user_id'], 'quantity' => 1, 'total_amount' => 25.0,
], $t0 + 2 * 86400);
contract_check($hook['status'] === 'recorded', 'ticket webhooks must record');
contract_check($engine->contestEntries((string) $contest['id'])['entries_count'] === 2, 'webhook ticket buyers must enter contests too');
$booking = $engine->ingestBodyguardWebhook(['service_id' => 'svc_bg_001', 'booking_id' => 'bg_777', 'user_external_id' => $alice['user_id'], 'duration_minutes' => 120], $t0);
contract_check($booking['status'] === 'recorded', 'bodyguard webhooks must record');

exec('rm -rf ' . escapeshellarg($stateDir));
fwrite(STDOUT, "Dating engine contract passed\n");
