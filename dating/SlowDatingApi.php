<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';

/**
 * Slow Dating API
 *
 * The HTTP contract of the SaaS platform as one dependency-free router.
 * Paths mirror the consolidated design specification (dating/DESIGN_SPEC.md
 * and dating/openapi.yaml). The router is a plain method so the same
 * contract is exercised by api.php over HTTP and by the tests directly.
 *
 * Auth: `Authorization: Bearer <token>` — member, partner, or admin tokens
 * issued at signup/login. Webhook endpoints instead verify the shared
 * secret header `X-Webhook-Signature`.
 */
final class SlowDatingApi
{
    public const WEBHOOK_SECRET_ENV = 'SLOWDATING_WEBHOOK_SECRET';

    private SlowDatingEngine $engine;

    public function __construct(?SlowDatingEngine $engine = null)
    {
        $this->engine = $engine ?? new SlowDatingEngine();
    }

    public function engine(): SlowDatingEngine
    {
        return $this->engine;
    }

    /**
     * @param array<string, mixed> $query
     * @param array<string, mixed> $body
     * @param array<string, string> $headers Lower-case header names.
     * @return array{0: int, 1: array<string, mixed>|array<int, mixed>} [status, payload]
     */
    public function route(string $method, string $path, array $query, array $body, array $headers, ?int $now = null): array
    {
        $now ??= time();
        $path = '/' . trim($path, '/');
        try {
            return $this->dispatch(strtoupper($method), $path, $query, $body, $headers, $now);
        } catch (InvalidArgumentException $exception) {
            return [422, ['error_code' => 'invalid_request', 'message' => $exception->getMessage()]];
        } catch (Throwable $exception) {
            return [500, ['error_code' => 'server_error', 'message' => $exception->getMessage()]];
        }
    }

    /** @return array{0: int, 1: array<string, mixed>|array<int, mixed>} */
    private function dispatch(string $method, string $path, array $query, array $body, array $headers, int $now): array
    {
        $engine = $this->engine;
        $segments = array_values(array_filter(explode('/', $path), static fn (string $s): bool => $s !== ''));

        // ---- Public: auth ------------------------------------------------
        if ($method === 'POST' && $path === '/auth/signup') {
            return [201, $engine->signupMember(
                (string) ($body['email'] ?? ''),
                isset($body['password']) ? (string) $body['password'] : null,
                (bool) ($body['use_auto_password'] ?? false),
                $now,
            )];
        }
        if ($method === 'POST' && $path === '/auth/login') {
            return [200, $engine->login((string) ($body['email'] ?? ''), (string) ($body['password'] ?? ''), $now)];
        }
        if ($method === 'POST' && $path === '/partners/v1/signup') {
            return [201, $engine->signupPartner(
                (string) ($body['business_name'] ?? ''),
                (string) ($body['email'] ?? ''),
                isset($body['password']) ? (string) $body['password'] : null,
                (string) ($body['plan_tier'] ?? 'basic'),
                $now,
            )];
        }
        if ($method === 'POST' && $path === '/partners/v1/login') {
            return [200, $engine->partnerLogin((string) ($body['email'] ?? ''), (string) ($body['password'] ?? ''), $now)];
        }
        if ($method === 'POST' && $path === '/admin/v1/login') {
            return [200, $engine->adminLogin((string) ($body['email'] ?? ''), (string) ($body['password'] ?? ''), $now)];
        }
        if ($method === 'POST' && $path === '/admin/v1/bootstrap') {
            return [201, $engine->createAdmin(
                (string) ($body['email'] ?? ''),
                isset($body['password']) ? (string) $body['password'] : null,
                null,
                $now,
            )];
        }

        // ---- Public: safety education & webhooks -------------------------
        if ($method === 'GET' && $path === '/safety/resources') {
            return [200, $engine->safetyResources()];
        }
        if ($method === 'POST' && str_starts_with($path, '/webhooks/')) {
            $secret = getenv(self::WEBHOOK_SECRET_ENV) ?: '';
            if ($secret === '' || !hash_equals($secret, $headers['x-webhook-signature'] ?? '')) {
                return [401, ['error_code' => 'unauthorized', 'message' => 'Invalid webhook signature.']];
            }
            return match ($path) {
                '/webhooks/tickets/purchased' => [200, $engine->ingestTicketWebhook($body, $now)],
                '/webhooks/bookings/created' => [200, $engine->ingestBookingWebhook($body, $now)],
                '/webhooks/bodyguard/booked' => [200, $engine->ingestBodyguardWebhook($body, $now)],
                default => [404, ['error_code' => 'not_found', 'message' => 'Unknown webhook.']],
            };
        }

        // ---- Everything below requires a bearer token --------------------
        $auth = $this->bearer($headers);
        if ($auth === null) {
            return [401, ['error_code' => 'unauthorized', 'message' => 'A bearer token is required.']];
        }
        [$subjectId, $kind] = $auth;

        if ($kind === 'member') {
            $memberResult = $this->memberRoutes($method, $path, $segments, $query, $body, $subjectId, $now);
            if ($memberResult !== null) {
                return $memberResult;
            }
        }
        if ($kind === 'partner') {
            $partnerResult = $this->partnerRoutes($method, $path, $segments, $body, $subjectId, $now);
            if ($partnerResult !== null) {
                return $partnerResult;
            }
        }
        if ($kind === 'admin') {
            $adminResult = $this->adminRoutes($method, $path, $segments, $query, $body, $subjectId, $now);
            if ($adminResult !== null) {
                return $adminResult;
            }
        }
        return [404, ['error_code' => 'not_found', 'message' => 'Unknown route for this credential: ' . $method . ' ' . $path]];
    }

    /** @return array{0: int, 1: mixed}|null */
    private function memberRoutes(string $method, string $path, array $segments, array $query, array $body, string $userId, int $now): ?array
    {
        $engine = $this->engine;
        if ($method === 'GET' && $path === '/users/me/profile') {
            return [200, $engine->profile($userId)];
        }
        if ($method === 'PATCH' && $path === '/users/me/profile') {
            return [200, $engine->updateProfile($userId, $body)];
        }
        if ($method === 'POST' && $path === '/users/me/profile/videos') {
            return [201, $engine->addProfileVideo($userId, (string) ($body['youtube_url'] ?? ''))];
        }
        if ($method === 'DELETE' && count($segments) === 5 && $path === '/users/me/profile/videos/' . $segments[4]) {
            $engine->removeProfileVideo($userId, $segments[4]);
            return [204, []];
        }
        if ($method === 'GET' && $path === '/users/search') {
            return [200, $engine->searchUsers($query, $now)];
        }
        if ($method === 'GET' && $path === '/users/search/popular') {
            $query['min_popularity'] = $query['min_score'] ?? ($query['min_popularity'] ?? 60);
            return [200, $engine->searchUsers($query, $now)];
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'users' && $segments[2] === 'profile') {
            // Another member's profile page (own id works too). Viewing
            // someone else counts as a profile view for their popularity.
            return [200, $engine->profileView($userId, $segments[1] === 'me' ? $userId : $segments[1], $now)];
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'users' && $segments[2] === 'popularity') {
            $target = $segments[1] === 'me' ? $userId : $segments[1];
            if ($target !== $userId) {
                $engine->recordPopularityEvent($target, 'profile_view', $now);
            }
            return [200, $engine->popularity($target, $now)];
        }
        if ($method === 'GET' && count($segments) === 4 && $segments[0] === 'users' && $segments[2] === 'popularity' && $segments[3] === 'breakdown') {
            $target = $segments[1] === 'me' ? $userId : $segments[1];
            if ($target !== $userId) {
                return [403, ['error_code' => 'forbidden', 'message' => 'The metric breakdown is visible only to the profile owner.']];
            }
            return [200, $engine->popularityBreakdown($target, $now)];
        }
        if ($method === 'POST' && $path === '/popularity/events') {
            $engine->recordPopularityEvent((string) ($body['user_id'] ?? ''), (string) ($body['event_type'] ?? ''), $now);
            return [201, ['status' => 'recorded']];
        }
        if ($method === 'GET' && $path === '/browse') {
            return [200, $engine->browseFor($userId, max(1, (int) ($query['limit'] ?? 12)), $now)];
        }
        if ($method === 'GET' && $path === '/users/me/preferences') {
            return [200, $engine->preferences($userId)];
        }
        if ($method === 'PATCH' && $path === '/users/me/preferences') {
            return [200, $engine->updatePreferences($userId, $body)];
        }
        if ($method === 'GET' && $path === '/matches') {
            return [200, $engine->matchesFor($userId, $query, $now)];
        }
        if ($method === 'GET' && $path === '/matches/search') {
            return [200, $engine->matchesFor($userId, $query, $now)];
        }
        if ($method === 'POST' && $path === '/chats') {
            return [201, $engine->startChat($userId, (string) ($body['user_id'] ?? ''), $now)];
        }
        if ($method === 'GET' && $path === '/chats') {
            return [200, array_map(
                static fn (array $chat): array => ['chat_id' => $chat['id'], 'participants' => $chat['participants'], 'started_at' => $chat['started_at'], 'message_count' => count((array) $chat['messages'])],
                $engine->chatsFor($userId),
            )];
        }
        if ($method === 'POST' && count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'images') {
            $bytes = base64_decode((string) ($body['image_base64'] ?? ''), true);
            if ($bytes === false) {
                return [422, ['error_code' => 'invalid_request', 'message' => 'image_base64 must be valid base64.']];
            }
            return [201, $engine->sendImageMessage($segments[1], $userId, $bytes, (string) ($body['mime'] ?? ''), (string) ($body['caption'] ?? ''), $now)];
        }
        if (count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'messages') {
            if ($method === 'POST') {
                return [201, $engine->sendMessage($segments[1], $userId, (string) ($body['text'] ?? ''), $now)];
            }
            if ($method === 'GET') {
                $chat = $engine->store()->get('chats', $segments[1]);
                if ($chat === null || !in_array($userId, (array) $chat['participants'], true)) {
                    return [404, ['error_code' => 'not_found', 'message' => 'Unknown chat.']];
                }
                return [200, (array) $chat['messages']];
            }
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'status') {
            return [200, $engine->chatStatus($segments[1], $now)];
        }
        if ($method === 'POST' && count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'image') {
            return [200, $engine->setChatImageChoice($segments[1], $userId, (string) ($body['choice'] ?? ''))];
        }
        if ($method === 'GET' && $path === '/users/me/blocks') {
            return [200, $engine->blockedMembers($userId)];
        }
        if ($method === 'POST' && $path === '/users/me/blocks') {
            return [201, $engine->blockMember($userId, (string) ($body['user_id'] ?? ''))];
        }
        if ($method === 'DELETE' && count($segments) === 4 && $segments[0] === 'users' && $segments[1] === 'me' && $segments[2] === 'blocks') {
            return [200, $engine->unblockMember($userId, $segments[3])];
        }
        if ($method === 'GET' && $path === '/users/me/pictures') {
            return [200, $engine->pictureRoster($userId)];
        }
        if ($method === 'GET' && $path === '/users/me/coach') {
            return [200, $engine->profileCoach($userId)];
        }
        if ($method === 'POST' && $path === '/users/me/prompts') {
            return [200, $engine->setPrompts($userId, (array) ($body['answers'] ?? []))];
        }
        if ($method === 'POST' && $path === '/users/me/verification') {
            return [200, $engine->requestVerification($userId, $now)];
        }
        if ($method === 'GET' && $path === '/users/me/daily-drop') {
            return [200, $engine->dailyDrop($userId, $now)];
        }
        if ($method === 'GET' && $path === '/swipe/next') {
            return [200, $engine->nextSwipe($userId, $now) ?? ['done' => true]];
        }
        if ($method === 'POST' && $path === '/swipe') {
            return [201, $engine->recordSwipe($userId, (string) ($body['user_id'] ?? ''), (string) ($body['action'] ?? ''), $now)];
        }
        if ($method === 'GET' && $path === '/matches/top') {
            return [200, $engine->topMatches($userId, (int) ($query['count'] ?? 10), $now)];
        }
        if ($method === 'GET' && $path === '/communities') {
            return [200, SlowDatingEngine::COMMUNITIES];
        }
        if (count($segments) === 2 && $segments[0] === 'communities' && $method === 'GET') {
            return [200, $engine->communityMembers($segments[1], $now)];
        }
        if (count($segments) === 4 && $segments[0] === 'users' && $segments[1] === 'me' && $segments[2] === 'communities') {
            if ($method === 'POST') {
                return [200, $engine->joinCommunity($userId, $segments[3])];
            }
            if ($method === 'DELETE') {
                return [200, $engine->leaveCommunity($userId, $segments[3])];
            }
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'icebreakers') {
            return [200, $engine->iceBreakers($segments[1], $userId)];
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'health') {
            return [200, $engine->conversationHealth($segments[1])];
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'ads') {
            return [200, $engine->meetupAdsForChat($segments[1], $now)];
        }
        if ($method === 'POST' && count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'unlock') {
            return [200, $engine->purchaseEarlyUnlock($segments[1], $userId, $now)];
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'concierge') {
            return [200, $engine->conciergeSuggestions($segments[1], $now)];
        }
        if ($method === 'GET' && $path === '/users/me/coupons') {
            return [200, $engine->couponsForMember($userId)];
        }
        if ($method === 'POST' && count($segments) === 3 && $segments[0] === 'coupons' && $segments[2] === 'redeem') {
            return [201, $engine->redeemCoupon($segments[1], $userId, $now)];
        }
        if ($method === 'GET' && $path === '/products') {
            return [200, $engine->products()];
        }
        if ($method === 'POST' && $path === '/orders') {
            return [201, $engine->placeOrder($userId, (string) ($body['product_id'] ?? ''), (int) ($body['quantity'] ?? 1), $now)];
        }
        if ($method === 'POST' && count($segments) === 3 && $segments[0] === 'events' && $segments[2] === 'tickets') {
            return [201, $engine->buyTicket($segments[1], $userId, (int) ($body['quantity'] ?? 1), $now)];
        }
        if ($method === 'GET' && $path === '/users/me/safety/events') {
            return [200, $engine->safetyEventsFor($userId)];
        }
        if ($method === 'GET' && $path === '/users/me/safety/resources') {
            return [200, $engine->safetyResources()];
        }
        if ($method === 'GET' && $path === '/users/me/rewards') {
            return [200, $engine->rewardsFor($userId)];
        }
        if ($method === 'GET' && $path === '/users/me/earn') {
            return [200, $engine->earnPortal($userId, $now)];
        }
        if ($method === 'POST' && $path === '/users/me/earn/enroll') {
            return [201, $engine->enrollEarnProgram($userId, (string) ($body['program'] ?? ''), $now)];
        }
        if ($method === 'POST' && $path === '/users/me/earn/withdraw') {
            return [200, $engine->withdrawEarnProgram($userId, (string) ($body['program'] ?? ''))];
        }
        if ($method === 'GET' && $path === '/users/me/earn/earnings') {
            return [200, $engine->earningsFor($userId)];
        }
        if ($method === 'POST' && $path === '/users/me/earn/activity/claim') {
            return [200, $engine->claimActivityEarnings($userId, $now)];
        }
        if ($method === 'POST' && $path === '/users/me/gallery') {
            $bytes = base64_decode((string) ($body['image_base64'] ?? ''), true);
            if ($bytes === false) {
                return [422, ['error_code' => 'invalid_request', 'message' => 'image_base64 must be valid base64.']];
            }
            return [201, $engine->addGalleryPhoto($userId, $bytes, (string) ($body['mime'] ?? ''), (string) ($body['caption'] ?? ''), $now)];
        }
        if ($method === 'DELETE' && count($segments) === 4 && $segments[0] === 'users' && $segments[1] === 'me' && $segments[2] === 'gallery') {
            $engine->removeGalleryPhoto($userId, $segments[3]);
            return [204, []];
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'users' && $segments[2] === 'gallery') {
            $target = $segments[1] === 'me' ? $userId : $segments[1];
            return [200, $engine->viewGallery($userId, $target, $now)];
        }
        if ($method === 'GET' && $path === '/earn/testimonials') {
            return [200, $engine->testimonialScripts()];
        }
        if ($method === 'POST' && count($segments) === 4 && $segments[0] === 'earn' && $segments[1] === 'testimonials' && $segments[3] === 'submit') {
            return [201, $engine->submitTestimonial($userId, $segments[2], (string) ($body['video_url'] ?? ''), (string) ($body['notes'] ?? ''), $now)];
        }
        if ($method === 'GET' && $path === '/users/me/testimonials') {
            return [200, $engine->testimonialsForMember($userId)];
        }
        if ($method === 'GET' && $path === '/films') {
            return [200, $engine->romanceFilms(
                (string) ($query['query'] ?? ''),
                (int) ($query['limit'] ?? 24),
                (int) ($query['offset'] ?? 0),
            )];
        }
        if ($method === 'GET' && $path === '/films/daily') {
            return [200, $engine->filmOfTheDay($now)];
        }
        if ($method === 'GET' && $path === '/films/premium-romcoms') {
            return [200, $engine->premiumRomcoms()];
        }
        if ($method === 'GET' && $path === '/films/channels') {
            return [200, $engine->watchChannels()];
        }
        if ($method === 'GET' && count($segments) === 3 && $segments[0] === 'films' && $segments[1] === 'channels') {
            return [200, $engine->channelLibrary(
                $segments[2],
                (string) ($query['query'] ?? ''),
                (int) ($query['limit'] ?? 24),
                (int) ($query['offset'] ?? 0),
            )];
        }
        if ($method === 'POST' && $path === '/advanced-rooms') {
            return [201, $engine->createAdvancedRoom(
                $userId,
                (string) ($body['mode'] ?? ''),
                (string) ($body['theme'] ?? ''),
                (string) ($body['video_url'] ?? ''),
                (float) ($body['price_per_user'] ?? 0),
                (int) ($body['required_participants'] ?? 2),
                $now,
            )];
        }
        if ($method === 'GET' && $path === '/advanced-rooms') {
            return [200, $engine->advancedRoomsFor($userId)];
        }
        if ($method === 'POST' && $path === '/advanced-rooms/join') {
            return [200, $engine->joinAdvancedRoom((string) ($body['invite_code'] ?? ''), $userId, $now)];
        }
        if (count($segments) >= 2 && $segments[0] === 'advanced-rooms') {
            $roomId = $segments[1];
            if ($method === 'GET' && count($segments) === 2) {
                return [200, $engine->advancedRoomView($roomId, $userId)];
            }
            if ($method === 'GET' && count($segments) === 3 && $segments[2] === 'recap') {
                return [200, $engine->advancedRecap($roomId, $userId)];
            }
            if ($method === 'GET' && count($segments) === 3 && $segments[2] === 'messages') {
                return [200, $engine->advancedMessages($roomId, $userId)];
            }
            if ($method === 'POST' && count($segments) === 3) {
                switch ($segments[2]) {
                    case 'pay':
                        return [200, $engine->payAdvancedShare($roomId, $userId, $now)];
                    case 'sync':
                        return [200, $engine->setAdvancedSync($roomId, $userId, $body, $now)];
                    case 'remote':
                        return [200, $engine->passAdvancedRemote($roomId, $userId, (string) ($body['user_id'] ?? ''))];
                    case 'reactions':
                        return [201, $engine->addAdvancedReaction($roomId, $userId, (string) ($body['type'] ?? ''), (float) ($body['t'] ?? 0), $now)];
                    case 'highlights':
                        return [201, $engine->markAdvancedHighlight($roomId, $userId, (float) ($body['t'] ?? 0), (string) ($body['note'] ?? ''), $now)];
                    case 'messages':
                        return [201, $engine->sendAdvancedMessage($roomId, $userId, (string) ($body['text'] ?? ''), $now)];
                    case 'end':
                        return [200, $engine->endAdvancedRoom($roomId, $userId, $now)];
                }
            }
        }
        if (count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'watch-sync') {
            if ($method === 'GET') {
                return [200, $engine->watchSync($segments[1], $userId)];
            }
            if ($method === 'POST') {
                return [200, $engine->setWatchSync($segments[1], $userId, $body, $now)];
            }
        }
        if (count($segments) === 3 && $segments[0] === 'chats' && $segments[2] === 'watch-party') {
            if ($method === 'GET') {
                return [200, $engine->watchPartyFor($segments[1], $userId, $now)];
            }
            if ($method === 'POST') {
                return [200, $engine->chooseWatchPartyFilm($segments[1], $userId, (string) ($body['film_id'] ?? 'daily'), $now)];
            }
        }
        if ($method === 'POST' && $path === '/users/me/billing/subscribe') {
            return [200, $engine->subscribeMembership($userId, (string) ($body['tier'] ?? 'member'), $now)];
        }
        return null;
    }

    /** @return array{0: int, 1: mixed}|null */
    private function partnerRoutes(string $method, string $path, array $segments, array $body, string $partnerId, int $now): ?array
    {
        $engine = $this->engine;
        if ($method === 'GET' && $path === '/partners/v1/me') {
            return [200, $engine->partner($partnerId)];
        }
        if ($path === '/partners/v1/venues') {
            if ($method === 'GET') {
                return [200, $engine->venuesForPartner($partnerId)];
            }
            if ($method === 'POST') {
                return [201, $engine->createVenue($partnerId, $body, $now)];
            }
        }
        if (count($segments) === 3 && $segments[0] === 'partners' && $segments[1] === 'v1' && $segments[2] === 'billing') {
            // handled below via exact paths
        }
        if ($method === 'GET' && $path === '/partners/v1/billing/plan') {
            $partner = $engine->partner($partnerId);
            return [200, ['plan_tier' => $partner['plan_tier']]];
        }
        if ($method === 'POST' && $path === '/partners/v1/billing/plan/change') {
            return [200, $engine->changePartnerPlan($partnerId, (string) ($body['new_plan_tier'] ?? ''))];
        }
        if (count($segments) >= 4 && $segments[0] === 'partners' && $segments[1] === 'v1' && $segments[2] === 'venues') {
            $venueId = $segments[3];
            $tail = array_slice($segments, 4);
            if ($tail === [] && $method === 'PATCH') {
                return [200, $engine->updateVenue($partnerId, $venueId, $body)];
            }
            if ($tail === ['coupons', 'random'] && $method === 'POST') {
                return [201, $engine->createRandomCoupon($partnerId, $venueId, $body, $now)];
            }
            if ($tail === ['coupons', 'targeted'] && $method === 'POST') {
                return [201, $engine->createTargetedCoupon($partnerId, $venueId, $body, (array) ($body['targeting'] ?? []), $now)];
            }
            if ($tail === ['coupons'] && $method === 'GET') {
                return [200, $engine->couponsForVenue($venueId)];
            }
            if ($tail === ['events'] && $method === 'POST') {
                return [201, $engine->createEvent($partnerId, $venueId, $body, $now)];
            }
            if ($tail === ['events'] && $method === 'GET') {
                return [200, $engine->eventsForVenue($venueId)];
            }
            if ($tail === ['contests'] && $method === 'POST') {
                return [201, $engine->createContest($partnerId, $venueId, $body, $now)];
            }
            if ($tail === ['contests'] && $method === 'GET') {
                return [200, $engine->contestsForVenue($venueId)];
            }
            if ($tail === ['products'] && $method === 'POST') {
                return [201, $engine->createProduct($partnerId, $venueId, $body, $now)];
            }
            if ($tail === ['products'] && $method === 'GET') {
                return [200, $engine->products($venueId)];
            }
            if ($tail === ['ads', 'meetup'] && $method === 'POST') {
                return [201, $engine->createMeetupAd($partnerId, $venueId, $body, $now)];
            }
            if ($tail === ['ads'] && $method === 'GET') {
                return [200, $engine->adsForVenue($venueId)];
            }
            if ($tail === ['testimonials'] && $method === 'POST') {
                return [201, $engine->createTestimonialScript($partnerId, $venueId, $body, $now)];
            }
            if ($tail === ['testimonials'] && $method === 'GET') {
                return [200, [
                    'scripts' => $engine->testimonialScripts($venueId),
                    'submissions' => $engine->testimonialsForVenue($venueId),
                ]];
            }
            if ($tail === ['analytics'] && $method === 'GET') {
                return [200, $engine->venueAnalytics($venueId)];
            }
        }
        if ($method === 'POST' && count($segments) === 5 && $segments[0] === 'partners' && $segments[2] === 'testimonials' && $segments[4] === 'review') {
            return [200, $engine->reviewTestimonial($partnerId, $segments[3], (string) ($body['action'] ?? ''), $body, $now)];
        }
        if ($method === 'GET' && count($segments) === 5 && $segments[0] === 'partners' && $segments[2] === 'contests' && $segments[4] === 'entries') {
            return [200, $engine->contestEntries($segments[3])];
        }
        return null;
    }

    /** @return array{0: int, 1: mixed}|null */
    private function adminRoutes(string $method, string $path, array $segments, array $query, array $body, string $adminId, int $now): ?array
    {
        $engine = $this->engine;
        if ($method === 'GET' && $path === '/admin/v1/leaderboard') {
            return [200, $engine->topMembers((int) ($query['count'] ?? 100), $now)];
        }
        if ($method === 'POST' && $path === '/admin/v1/rewards/top') {
            return [201, $engine->grantTopMemberRewards($adminId, (int) ($body['cohort'] ?? 0), (array) ($body['benefit'] ?? []), $now)];
        }
        if ($method === 'GET' && $path === '/admin/v1/verifications') {
            return [200, $engine->pendingVerifications()];
        }
        if ($method === 'POST' && count($segments) === 4 && $segments[0] === 'admin' && $segments[2] === 'verifications') {
            return [200, $engine->reviewVerification($adminId, $segments[3], (bool) ($body['approve'] ?? false), $now)];
        }
        if ($method === 'GET' && $path === '/admin/v1/settings') {
            return [200, [
                'avatar_mode' => $engine->avatarMode(),
                'photo_reveal_days' => $engine->photoRevealDays(),
                'watch_party_embed' => $engine->watchPartyEmbed(),
            ]];
        }
        if ($method === 'PATCH' && $path === '/admin/v1/settings') {
            $updated = [];
            if (array_key_exists('avatar_mode', $body)) {
                $updated += $engine->setAvatarMode($adminId, (string) $body['avatar_mode']);
            }
            if (array_key_exists('photo_reveal_days', $body)) {
                $updated += $engine->setPhotoRevealDays($adminId, (int) $body['photo_reveal_days']);
            }
            if (array_key_exists('watch_party_embed', $body)) {
                $updated += $engine->setWatchPartyEmbed($adminId, (string) $body['watch_party_embed']);
            }
            if ($updated === []) {
                return [422, ['error_code' => 'invalid_request', 'message' => 'Send avatar_mode and/or photo_reveal_days.']];
            }
            return [200, $updated];
        }
        if ($method === 'POST' && $path === '/admin/v1/admins') {
            return [201, $engine->createAdmin((string) ($body['email'] ?? ''), isset($body['password']) ? (string) $body['password'] : null, $adminId, $now)];
        }
        return null;
    }

    /** @return array{0: string, 1: string}|null [subject id, kind] */
    private function bearer(array $headers): ?array
    {
        $header = $headers['authorization'] ?? '';
        if (preg_match('/^Bearer\s+(\S+)$/i', $header, $m) !== 1) {
            return null;
        }
        return $this->engine->authenticate($m[1]);
    }
}
