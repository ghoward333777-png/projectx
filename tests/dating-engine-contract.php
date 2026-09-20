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

putenv('SLOWDATING_NO_LOOKUP=1');   // keep the contract offline & deterministic
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

// ---- Browse preferences -----------------------------------------------------
$prefs = $engine->updatePreferences($alice['user_id'], [
    'seeking_gender' => 'male', 'age_min' => 28, 'age_max' => 35,
    'max_distance_km' => 50, 'interests' => 'jazz',
]);
contract_check($prefs['seeking_gender'] === 'male' && $prefs['interests'] === ['jazz'], 'preferences must save and normalize');
$browse = $engine->browseFor($alice['user_id'], 12, $t0);
contract_check(count($browse) === 1 && $browse[0]['user_id'] === $bob['user_id'], 'browse must apply saved preferences as hard filters (only Bob fits)');
$engine->updatePreferences($alice['user_id'], ['interests' => '']);
$engine->updatePreferences($alice['user_id'], ['age_min' => 18, 'age_max' => 99]);
contract_check(count($engine->browseFor($alice['user_id'], 12, $t0)) === 2, 'widening preferences must widen browse results');
$threw = false;
try {
    $engine->updatePreferences($alice['user_id'], ['age_min' => 40, 'age_max' => 30]);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'an upside-down age range must be rejected');

// Must-match criteria: faith, income, education, occupation, automobile, politics.
$engine->updateProfile($bob['user_id'], ['education' => 'masters']);
$engine->updateProfile($dave['user_id'], ['education' => 'high_school']);
$engine->updatePreferences($alice['user_id'], ['faith' => 'none', 'income_range' => '100k_150k', 'education' => 'masters']);
$filtered = $engine->browseFor($alice['user_id'], 12, $t0);
contract_check(count($filtered) === 1 && $filtered[0]['user_id'] === $bob['user_id'], 'faith + income + education preferences must filter browse to Bob');
$engine->updatePreferences($alice['user_id'], ['faith' => '', 'income_range' => '', 'education' => '']);
$threw = false;
try {
    $engine->updatePreferences($alice['user_id'], ['education' => 'street_smarts']);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unknown education preferences must be rejected');
contract_check(count($engine->searchUsers(['education' => 'masters'], $t0)) === 1, 'education must be searchable');

// Generic classifications: raw items map to categories; requirements speak in categories.
$aliceCategories = $engine->interestCategories($engine->store()->get('users', $alice['user_id'])['profile']);
contract_check(in_array('music_nightlife', $aliceCategories, true) && in_array('food_dining', $aliceCategories, true), 'jazz and italian food must classify as music & nightlife and food & dining');
$engine->updateProfile($dave['user_id'], ['interests' => 'escape rooms']);
$daveCategories = $engine->interestCategories($engine->store()->get('users', $dave['user_id'])['profile']);
contract_check(in_array('adventures', $daveCategories, true) && in_array('games', $daveCategories, true), '"escape rooms" must classify as Adventures and Games — never a raw menu item');
$engine->updatePreferences($alice['user_id'], ['shared_categories' => ['music_nightlife']]);
$byCategory = $engine->browseFor($alice['user_id'], 12, $t0);
contract_check(count($byCategory) === 1 && $byCategory[0]['user_id'] === $bob['user_id'], 'a shared-category requirement must filter browse (only Bob shares music & nightlife)');
$engine->updatePreferences($alice['user_id'], ['shared_categories' => []]);
$threw = false;
try {
    $engine->updatePreferences($alice['user_id'], ['shared_categories' => ['juggling']]);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unknown shared categories must be rejected');

// "Must share with me": every criterion pins candidates to the member's own value.
$engine->updateProfile($alice['user_id'], ['faith' => 'none', 'education' => 'masters']);
$engine->updateProfile($bob['user_id'], ['faith' => 'none']);
$engine->updateProfile($dave['user_id'], ['faith' => 'spiritual']);
$engine->updatePreferences($alice['user_id'], ['must_share' => ['faith', 'music_nightlife']]);
$sharedWithMe = $engine->browseFor($alice['user_id'], 12, $t0);
contract_check(count($sharedWithMe) === 1 && $sharedWithMe[0]['user_id'] === $bob['user_id'], 'must-share faith + music must keep only Bob (shares both with Alice)');
$engine->updatePreferences($alice['user_id'], ['must_share' => ['pets']]);
contract_check(count($engine->browseFor($alice['user_id'], 12, $t0)) === 2, 'a must-share factor the member has not filled in is skipped, not enforced');
$engine->updatePreferences($alice['user_id'], ['must_share' => []]);
$threw = false;
try {
    $engine->updatePreferences($alice['user_id'], ['must_share' => ['shoe_size']]);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unknown must-share criteria must be rejected');

// Lifestyle requirements: family plans, smoking, drinking, pets.
$engine->updateProfile($bob['user_id'], ['family_plans' => 'wants_kids', 'smoking' => 'never', 'drinking' => 'socially', 'pets' => 'dog']);
$engine->updatePreferences($alice['user_id'], ['family_plans' => 'wants_kids', 'smoking' => 'never']);
$lifestyleMatches = $engine->browseFor($alice['user_id'], 12, $t0);
contract_check(count($lifestyleMatches) === 1 && $lifestyleMatches[0]['user_id'] === $bob['user_id'], 'family-plans and smoking requirements must filter browse');
$engine->updatePreferences($alice['user_id'], ['family_plans' => '', 'smoking' => '']);
$threw = false;
try {
    $engine->updateProfile($bob['user_id'], ['smoking' => 'like a chimney']);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unknown lifestyle values must be rejected');

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

// ---- Profile images: mode + uploads ---------------------------------------------
contract_check($engine->avatarMode() === 'generated', 'the platform defaults to generated artwork');
$png = base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==');
$photo = $engine->setMemberPhoto($alice['user_id'], $png, 'image/png');
contract_check($photo['file'] === $alice['user_id'] . '.public.png', 'photos are stored under a server-chosen slot name');
contract_check($engine->memberPhoto($alice['user_id']) !== null, 'a stored photo must be retrievable');

// Three-picture roster and the per-chat reveal choice.
$roster = $engine->pictureRoster($alice['user_id']);
contract_check($roster['generated'] && $roster['public'] && !$roster['private'] && !$roster['complete'], 'the roster must track artwork, real, and private pictures');
$engine->setMemberPhoto($alice['user_id'], $png, 'image/png', 'private');
contract_check($engine->pictureRoster($alice['user_id'])['complete'], 'uploading both pictures completes the three-picture profile');
contract_check($engine->chatImageChoice($chatId, $alice['user_id']) === 'generated', 'chats default to showing artwork until the member chooses');
$threw = false;
try {
    $engine->setChatImageChoice($chatId, $bob['user_id'], 'private');
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'choosing a picture you have not uploaded must be rejected');
$engine->setChatImageChoice($chatId, $alice['user_id'], 'private');
contract_check($engine->chatImageChoice($chatId, $alice['user_id']) === 'private', 'a member can reveal their private picture in one chat');
$threw = false;
try {
    $engine->setChatImageChoice($chatId, $carol['user_id'], 'generated');
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'non-participants cannot set a chat image choice');
$threw = false;
try {
    $engine->setMemberPhoto($alice['user_id'], 'GIF89a not allowed', 'image/gif');
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unsupported photo types must be rejected');
$threw = false;
try {
    $engine->setMemberPhoto($alice['user_id'], 'not really a png', 'image/png');
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'bytes must match the declared image type');
$threw = false;
try {
    $engine->setAvatarMode($alice['user_id'], 'uploads');
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'only admins may change the image mode');
$engine->setAvatarMode($admin['admin_id'], 'uploads');
contract_check($engine->avatarMode() === 'uploads', 'admins can switch to uploaded images');
$engine->setAvatarMode($admin['admin_id'], 'generated');

// ---- 2026 pack: verification, prompts, coach, drops, communities ------------------
contract_check($engine->verificationStatus($alice['user_id']) === 'none', 'members start unverified');
$engine->requestVerification($alice['user_id'], $t0);
contract_check($engine->verificationStatus($alice['user_id']) === 'pending', 'requesting verification queues it');
contract_check(count($engine->pendingVerifications()) === 1, 'the admin queue lists pending requests');
$threw = false;
try {
    $engine->reviewVerification($bob['user_id'], $alice['user_id'], true, $t0);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'only admins review verifications');
$engine->reviewVerification($admin['admin_id'], $alice['user_id'], true, $t0);
contract_check($engine->verificationStatus($alice['user_id']) === 'verified', 'admins grant the trust badge');
$verifiedRow = $engine->searchUsers(['gender' => 'female', 'interests' => 'jazz'], $t0)[0];
contract_check($verifiedRow['verified'] === true, 'the trust badge surfaces in search rows');

$prompts = $engine->setPrompts($alice['user_id'], [
    ['id' => 'p3', 'text' => 'Analog photography and obscure jazz pressings.'],
    ['id' => 'p2', 'text' => 'Farmers market, darkroom, live trio by night.'],
]);
contract_check(count($prompts) === 2 && $prompts[0]['question'] === SlowDatingEngine::PROMPTS['p3'], 'prompts store with their questions');
$threw = false;
try {
    $engine->setPrompts($alice['user_id'], [['id' => 'nope', 'text' => 'x']]);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unknown prompts are rejected');

$coach = $engine->profileCoach($alice['user_id']);
contract_check($coach['score'] > 0 && $coach['score'] <= 100, 'the profile coach scores 0-100');
$coachDave = $engine->profileCoach($dave['user_id']);
contract_check($coach['score'] > $coachDave['score'], 'a fuller profile outscores a thin one');
contract_check($coachDave['suggestions'] !== [], 'the coach gives thin profiles concrete suggestions');

$breakers = $engine->iceBreakers($chatId, $bob['user_id']);
contract_check($breakers !== [] && str_contains(implode(' ', $breakers), 'jazz') || str_contains(implode(' ', $breakers), 'Alice answered'), 'ice breakers build on prompts and shared interests');
$health = $engine->conversationHealth($chatId);
contract_check($health['score'] >= 5 && $health['score'] <= 100 && in_array($health['label'], ['thriving', 'steady', 'needs care'], true), 'conversation health returns a bounded score and label');

$engine->updatePreferences($alice['user_id'], ['seeking_gender' => 'male', 'age_min' => 18, 'age_max' => 99, 'max_distance_km' => 200]);
$drop1 = $engine->dailyDrop($alice['user_id'], $t0 + 40 * 86400);
$drop2 = $engine->dailyDrop($alice['user_id'], $t0 + 40 * 86400 + 3600);
contract_check($drop1 !== [] && count($drop1) <= SlowDatingEngine::DAILY_DROP_SIZE, 'the daily drop is a small curated set');
contract_check(array_column($drop1, 'user_id') === array_column($drop2, 'user_id'), 'the same day serves the same drop');

$engine->joinCommunity($alice['user_id'], 'creatives');
$engine->joinCommunity($bob['user_id'], 'creatives');
contract_check(count($engine->communityMembers('creatives', $t0)) === 2, 'community grids list joined members');
$engine->leaveCommunity($bob['user_id'], 'creatives');
contract_check(count($engine->communityMembers('creatives', $t0)) === 1, 'leaving a community removes you from its grid');
$threw = false;
try {
    $engine->joinCommunity($alice['user_id'], 'flat-earthers');
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unknown communities are rejected');

// ---- Chat image sharing -----------------------------------------------------------
$before = $engine->popularityBreakdown($alice['user_id'], $t0 + 40 * 86400)['metrics']['photo_received'];
$shared = $engine->sendImageMessage($chatId, $bob['user_id'], $png, 'image/png', 'Sunset from my run: call me at 310-555-9999', $t0 + 40 * 86400);
contract_check(isset($shared['image']['file']), 'shared images must be stored with the message');
contract_check(str_contains($shared['text'], 'call me at'), 'captions in unlocked chats flow unfiltered');
$after = $engine->popularityBreakdown($alice['user_id'], $t0 + 40 * 86400)['metrics']['photo_received'];
contract_check($after === $before + 1, 'sharing an image credits the recipient a photo_received event');
contract_check($engine->chatImage($chatId, (string) $shared['message_id'], $alice['user_id']) !== null, 'participants can retrieve a shared image');
contract_check($engine->chatImage($chatId, (string) $shared['message_id'], $carol['user_id']) === null, 'non-participants never retrieve shared images');
$lockedChat = $engine->startChat($carol['user_id'], $bob['user_id'], $t0 + 40 * 86400);
$lockedShare = $engine->sendImageMessage((string) $lockedChat['id'], $carol['user_id'], $png, 'image/png', 'my email is carol@fast.example', $t0 + 40 * 86400 + 60);
contract_check(!str_contains($lockedShare['text'], 'carol@fast'), 'captions are contact-filtered before unlock');
$threw = false;
try {
    $engine->sendImageMessage($chatId, $bob['user_id'], 'not an image', 'image/png', '', $t0 + 40 * 86400);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'shared image bytes must match the declared type');

// ---- Meet-up intent advertising ----------------------------------------------------
$threw = false;
try {
    $engine->createMeetupAd($basicPartner['partner_id'], (string) $basicVenue['id'] ?? '', ['headline' => 'x', 'keys' => ['movies']], $t0);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'meet-up ads must require the Pro or Elite plan');
$threw = false;
try {
    $engine->createMeetupAd($partner['partner_id'], $venueId, ['headline' => 'x', 'keys' => ['helicopters']], $t0);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unknown ad keys must be rejected');

$italianVenue = $engine->createVenue($partner['partner_id'], ['name' => "Ralph's Italian Spot", 'zip_code' => '90210', 'category' => 'restaurant'], $t0);
$engine->createMeetupAd($partner['partner_id'], (string) $italianVenue['id'], [
    'headline' => "Make it Ralph's", 'message' => 'Pasta before the show.', 'keys' => ['italian_restaurant'],
], $t0);
$theaterVenue = $engine->createVenue($partner['partner_id'], ['name' => 'Double Feature Theater', 'zip_code' => '90211', 'category' => 'experience'], $t0);
$engine->createMeetupAd($partner['partner_id'], (string) $theaterVenue['id'], [
    'headline' => 'Two seats tonight', 'keys' => ['movies'],
], $t0);
$farVenue = $engine->createVenue($partner['partner_id'], ['name' => 'Far Away Pasta', 'zip_code' => '10001', 'category' => 'restaurant'], $t0);
$engine->createMeetupAd($partner['partner_id'], (string) $farVenue['id'], [
    'headline' => 'Fly to NYC for dinner', 'keys' => ['italian_restaurant'],
], $t0);

$preIntent = $engine->meetupIntent((string) $lockedChat['id']);
contract_check($preIntent['meetup'] === false, 'ordinary chat does not read as a meet-up');
$engine->sendMessage($chatId, $bob['user_id'], 'Are you free Saturday? Italian place first, then a movie at the theater?', $t0 + 41 * 86400);
$engine->sendMessage($chatId, $alice['user_id'], 'Perfect — pasta then the late show. It\'s a date.', $t0 + 41 * 86400 + 60);
$intent = $engine->meetupIntent($chatId);
contract_check($intent['meetup'] === true, 'date-planning talk must register as meet-up intent');
contract_check(in_array('italian_restaurant', $intent['keys'], true) && in_array('movies', $intent['keys'], true), 'the discussed plans must map to purchased keys');
$ads = $engine->meetupAdsForChat($chatId, $t0 + 41 * 86400);
contract_check(count($ads) === 2, 'both matching local advertisers must flash — the Italian spot and the theater');
$names = array_column($ads, 'venue_name');
contract_check(in_array("Ralph's Italian Spot", $names, true) && in_array('Double Feature Theater', $names, true), 'the right advertisers must be chosen');
contract_check(!in_array('Far Away Pasta', $names, true), 'advertisers outside the couple\'s town never flash');
contract_check($engine->venueAnalytics((string) $italianVenue['id'])['meetup_ad_impressions'] === 1, 'meet-up impressions must count in venue analytics');

// ---- Webhooks -----------------------------------------------------------------
$hook = $engine->ingestTicketWebhook([
    'event_id' => (string) $event['id'], 'external_ticket_id' => 'tix_987',
    'user_external_id' => $bob['user_id'], 'quantity' => 1, 'total_amount' => 25.0,
], $t0 + 2 * 86400);
contract_check($hook['status'] === 'recorded', 'ticket webhooks must record');
contract_check($engine->contestEntries((string) $contest['id'])['entries_count'] === 2, 'webhook ticket buyers must enter contests too');
$booking = $engine->ingestBodyguardWebhook(['service_id' => 'svc_bg_001', 'booking_id' => 'bg_777', 'user_external_id' => $alice['user_id'], 'duration_minutes' => 120], $t0);
contract_check($booking['status'] === 'recorded', 'bodyguard webhooks must record');

// ---- Perks & income for popular members --------------------------------------------
$tEarn = $t0 + 44 * 86400;
for ($i = 0; $i < 20; $i++) {
    $engine->recordPopularityEvent($alice['user_id'], 'profile_view', $tEarn - 3600 - $i);
}
contract_check($engine->earnEligibility($alice['user_id'], $tEarn)['eligible'], 'a highly engaged member must qualify for income programs');
$dana = $engine->signupMember('dana@example.com', null, true, $tEarn);
$threw = false;
try {
    $engine->enrollEarnProgram($dana['user_id'], 'profile_ads', $tEarn);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'income programs must reject members who are not popular yet');
$threw = false;
try {
    $engine->enrollEarnProgram($alice['user_id'], 'lottery', $tEarn);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'unknown income programs must be rejected');
contract_check(count(SlowDatingEngine::EARN_PROGRAMS) === 9, 'all nine income programs must exist');

$engine->enrollEarnProgram($alice['user_id'], 'profile_ads', $tEarn);
$engine->recordPopularityEvent($alice['user_id'], 'profile_view', $tEarn + 60);
$ledger = $engine->earningsFor($alice['user_id']);
contract_check($ledger['total'] === 0.05 && $ledger['entries'][0]['program'] === 'profile_ads', 'profile views must pay enrolled members their ad share');

// Premium Members Only gallery — separate from profile pictures, paid tiers only.
$threw = false;
try {
    $engine->addGalleryPhoto($alice['user_id'], $png, 'image/png', 'x', $tEarn);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'the gallery must require enrollment first');
$engine->enrollEarnProgram($alice['user_id'], 'premium_gallery', $tEarn);
$shot = $engine->addGalleryPhoto($alice['user_id'], $png, 'image/png', 'Golden hour', $tEarn);
$threw = false;
try {
    $engine->viewGallery($dana['user_id'], $alice['user_id'], $tEarn);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'free members must not open the Premium Members Only gallery');
contract_check($engine->galleryPhoto($dana['user_id'], (string) $shot['photo_id']) === null, 'gallery bytes must not serve to free members');
$engine->subscribeMembership($bob['user_id'], 'member', $tEarn);
$view = $engine->viewGallery($bob['user_id'], $alice['user_id'], $tEarn + 120);
contract_check(count($view['photos']) === 1 && $view['photos'][0]['caption'] === 'Golden hour', 'premium members must see the gallery');
$engine->viewGallery($bob['user_id'], $alice['user_id'], $tEarn + 240);
$ledger = $engine->earningsFor($alice['user_id']);
contract_check($ledger['total'] === 0.30, 'a premium gallery visit must pay once per viewer per day');
contract_check($engine->galleryPhoto($bob['user_id'], (string) $shot['photo_id']) !== null, 'gallery bytes must serve to premium members');

// Paid chat hours: Alice responds across five UTC hours of one day.
$engine->enrollEarnProgram($alice['user_id'], 'chat_responder', $tEarn);
$tDay = $t0 + 45 * 86400;
for ($h = 0; $h < 5; $h++) {
    $engine->sendMessage($chatId, $alice['user_id'], 'Hour ' . $h . ' and still the best conversation on here.', $tDay + $h * 3600);
}
$claim = $engine->claimActivityEarnings($alice['user_id'], $tDay + 5 * 3600);
contract_check($claim['programs']['chat_responder']['claimed'] && $claim['programs']['chat_responder']['amount'] === 7.5, 'five responder hours must pay at the hourly rate');
contract_check(!$claim['programs']['chat_initiator']['claimed'], 'initiator hours must not pay when the member only responded');
$again = $engine->claimActivityEarnings($alice['user_id'], $tDay + 6 * 3600);
contract_check(!$again['programs']['chat_responder']['claimed'], 'a day of chat hours must pay only once');

// Scheduled dates at partner events: 10% of the ticket back.
$engine->enrollEarnProgram($alice['user_id'], 'date_scheduler', $tEarn);
$before = $engine->earningsFor($alice['user_id'])['total'];
$engine->buyTicket((string) $event['id'], $alice['user_id'], 1, $tDay + 7200);
contract_check($engine->earningsFor($alice['user_id'])['total'] === round($before + 2.5, 2), 'a partner event ticket must pay the 10% date share');

// Partner-scripted testimonials: accept pays, edit and extend rework the script.
$threw = false;
try {
    $engine->createTestimonialScript($partner['partner_id'], $venueId, ['script' => 'x', 'payout' => 0], $tEarn);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'testimonial offers must carry a positive payout');
$offer = $engine->createTestimonialScript($partner['partner_id'], $venueId, [
    'title' => 'Jazz Night testimonial', 'script' => 'I met someone real at Blue Note.', 'payout' => 40.0,
], $tEarn);
$engine->enrollEarnProgram($alice['user_id'], 'testimonials', $tEarn);
$submission = $engine->submitTestimonial($alice['user_id'], (string) $offer['id'], 'https://youtu.be/demo123', 'First take.', $tEarn + 60);
$edited = $engine->reviewTestimonial($partner['partner_id'], (string) $submission['id'], 'edit', ['script' => 'I met someone REAL at Blue Note Lounge.'], $tEarn + 120);
contract_check($edited['status'] === 'revise' && $edited['script_text'] === 'I met someone REAL at Blue Note Lounge.', 'an edit must replace the script for a re-record');
$extended = $engine->reviewTestimonial($partner['partner_id'], (string) $submission['id'], 'extend', ['script' => 'Ask for the stage table.'], $tEarn + 180);
contract_check($extended['status'] === 'extended' && str_contains((string) $extended['script_text'], 'Ask for the stage table.'), 'an extension must append to the script');
$before = $engine->earningsFor($alice['user_id'])['total'];
$accepted = $engine->reviewTestimonial($partner['partner_id'], (string) $submission['id'], 'accept', [], $tEarn + 240);
contract_check($accepted['status'] === 'accepted' && count($accepted['history']) === 3, 'the review history must carry every decision');
contract_check($engine->earningsFor($alice['user_id'])['total'] === round($before + 40.0, 2), 'an accepted testimonial must pay the offer payout');
$portal = $engine->earnPortal($alice['user_id'], $tEarn + 300);
contract_check(count($portal['programs']) === 9 && $portal['earnings_total'] > 0, 'the portal must report all programs and the ledger total');

// ---- Watch Party & the romance library ------------------------------------------------
$library = $engine->romanceFilms('', 100, 0);
contract_check($library['total'] === 1000, 'the romance playlist must hold exactly 1,000 films');
$ids = [];
$page = 0;
do {
    $slice = $engine->romanceFilms('', 100, $page * 100);
    foreach ($slice['films'] as $entry) {
        $ids[(string) $entry['id']] = true;
        contract_check($entry['rank'] >= 1 && $entry['rank'] <= 1000, 'every film must carry a playlist rank');
    }
    $page++;
} while ($page < 10);
contract_check(count($ids) === 1000, 'every film in the playlist must be unique');
$playable = $engine->romanceFilms('charade', 10, 0);
contract_check($playable['films'][0]['playable'] === true && str_contains((string) $playable['films'][0]['embed_url'], 'youtube.com/embed/'), 'verified public-domain films must embed in-page');
$searchOnly = $engine->romanceFilm('titanic-1997');
contract_check($searchOnly !== null && $searchOnly['playable'] === false && str_contains((string) $searchOnly['watch_url'], 'results?search_query='), 'unverified films must open through a YouTube search');

$daily = $engine->filmOfTheDay($tDay);
contract_check($daily['id'] === $engine->filmOfTheDay($tDay + 3600)['id'], 'the scheduled movie must hold steady all day');
$week = [];
for ($d = 0; $d < 7; $d++) {
    $week[$engine->filmOfTheDay($tDay + $d * 86400)['id']] = true;
}
contract_check(count($week) >= 4, 'the schedule must rotate through different films across a week');

$party = $engine->watchPartyFor($chatId, $alice['user_id'], $tDay);
contract_check($party['film']['id'] === $daily['id'] && $party['custom_pick'] === false, 'a fresh watch party must show the scheduled movie');
$threw = false;
try {
    $engine->watchPartyFor($chatId, $dana['user_id'], $tDay);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'outsiders must not join a couple\'s watch party');
$threw = false;
try {
    $engine->chooseWatchPartyFilm($chatId, $alice['user_id'], 'not-a-real-film', $tDay);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'only library films can be picked');
$party = $engine->chooseWatchPartyFilm($chatId, $alice['user_id'], 'charade-1963', $tDay);
contract_check($party['film']['id'] === 'charade-1963' && $party['chosen_by'] === $alice['user_id'], 'either partner can swap in any library film');
$asBob = $engine->watchPartyFor($chatId, $bob['user_id'], $tDay);
contract_check($asBob['film']['id'] === 'charade-1963', 'both partners must see the same picked film');
$party = $engine->chooseWatchPartyFilm($chatId, $bob['user_id'], 'daily', $tDay);
contract_check($party['film']['id'] === $daily['id'] && $party['custom_pick'] === false, 'the party must return to the scheduled movie on demand');
// Every film plays in-page: a resolved video (cached keyless lookup of
// YouTube search) upgrades an uncurated film to an embedded stream.
$engine->store()->put('film_videos', 'titanic-1997', ['video_id' => 'abcDEF12345', 'resolved_at' => $tDay]);
$engine->chooseWatchPartyFilm($chatId, $alice['user_id'], 'titanic-1997', $tDay);
$party = $engine->watchPartyFor($chatId, $alice['user_id'], $tDay);
contract_check($party['film']['playable'] === true && $party['film']['embed_url'] === 'https://www.youtube.com/embed/abcDEF12345', 'resolved films must embed in-page like curated ones');
$engine->chooseWatchPartyFilm($chatId, $alice['user_id'], 'daily', $tDay);

// ---- Seeking gender is absolute on every discovery surface ---------------------------
$genderOf = static function (array $row) use ($engine): string {
    $user = $engine->store()->get('users', (string) $row['user_id']);
    return (string) ($user['profile']['gender'] ?? '');
};
$engine->updatePreferences($alice['user_id'], ['seeking_gender' => 'male']);
$rows = $engine->topMatches($alice['user_id'], 20, $tDay);
contract_check($rows !== [], 'seeking men must return matches');
foreach ($rows as $row) {
    contract_check($genderOf($row) === 'male', 'Top matches must never show a gender the member is not seeking');
}
$engine->updatePreferences($alice['user_id'], ['seeking_gender' => 'female']);
foreach ($engine->topMatches($alice['user_id'], 20, $tDay) as $row) {
    contract_check($genderOf($row) === 'female', 'flipping the seeking gender must flip every result');
}
$engine->updatePreferences($alice['user_id'], ['seeking_gender' => 'male']);

// ---- Admin-pasted Watch Party embed ---------------------------------------------------
contract_check($engine->youtubeEmbedUrl('<iframe width="560" src="https://www.youtube.com/embed/videoseries?list=PLabc123DEF456" allowfullscreen></iframe>') === 'https://www.youtube.com/embed/videoseries?list=PLabc123DEF456', 'pasted iframe embed code must parse');
contract_check($engine->youtubeEmbedUrl('https://www.youtube.com/playlist?list=PLabc123DEF456') === 'https://www.youtube.com/embed/videoseries?list=PLabc123DEF456', 'playlist links must convert to playlist embeds');
contract_check($engine->youtubeEmbedUrl('https://youtu.be/jpejUwKLmfg?si=xyz') === 'https://www.youtube.com/embed/jpejUwKLmfg', 'youtu.be links must convert');
contract_check($engine->youtubeEmbedUrl('https://www.youtube.com/watch?v=jpejUwKLmfg&list=PLabc123DEF456') === 'https://www.youtube.com/embed/jpejUwKLmfg?list=PLabc123DEF456', 'watch links keep their playlist');
contract_check($engine->youtubeEmbedUrl('https://evil.example/embed/x') === null, 'non-YouTube pastes must be rejected');
$threw = false;
try {
    $engine->setWatchPartyEmbed($alice['user_id'], 'https://youtu.be/jpejUwKLmfg');
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'only admins may set the Watch Party player');
$set = $engine->setWatchPartyEmbed($admin['admin_id'], '<iframe src="https://www.youtube.com/embed/videoseries?list=PLabc123DEF456"></iframe>');
contract_check($set['watch_party_embed'] === 'https://www.youtube.com/embed/videoseries?list=PLabc123DEF456', 'admins must set the player from pasted embed code');
contract_check($engine->watchPartyEmbed() === 'https://www.youtube.com/embed/videoseries?list=PLabc123DEF456', 'the pasted player source must read back');
$engine->setWatchPartyEmbed($admin['admin_id'], '');
contract_check($engine->watchPartyEmbed() === null, 'an empty paste must clear the player override');

// ---- Photo reveal timeframe & the Peek early perk ------------------------------------
$threw = false;
try {
    $engine->setPhotoRevealDays($alice['user_id'], 2);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'only admins may set the photo reveal timeframe');
$threw = false;
try {
    $engine->setPhotoRevealDays($admin['admin_id'], 45);
} catch (InvalidArgumentException) {
    $threw = true;
}
contract_check($threw, 'the reveal delay must stay within 0-30 days');
$engine->setPhotoRevealDays($admin['admin_id'], 2);
contract_check($engine->photoRevealDays() === 2, 'the reveal timeframe must read back');
contract_check($engine->canSeeRealPhotos($alice['user_id'], $alice['user_id'], $tDay), 'owners always see their own pictures');
contract_check($engine->canSeeRealPhotos($bob['user_id'], $dana['user_id'], $tDay), 'premium members hold the Peek early perk everywhere');
contract_check(!$engine->canSeeRealPhotos($dana['user_id'], $alice['user_id'], $tDay), 'no chat means no real pictures for free members');
$engine->startChat($dana['user_id'], $alice['user_id'], $tDay);
contract_check(!$engine->canSeeRealPhotos($dana['user_id'], $alice['user_id'], $tDay + 86400), 'pictures stay hidden before the reveal day');
contract_check($engine->canSeeRealPhotos($dana['user_id'], $alice['user_id'], $tDay + 2 * 86400), 'pictures reveal once the chat reaches the admin-set day');

exec('rm -rf ' . escapeshellarg($stateDir));
fwrite(STDOUT, "Dating engine contract passed\n");
