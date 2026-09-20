<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingStore.php';

/**
 * Slow Dating Engine
 *
 * The complete domain logic for the SlowDating SaaS application:
 * members, strong-password auth, slow-chat pacing with the 30-day +
 * 10-session unlock, contact-data filtering, popularity scoring, matching,
 * the partner ecosystem (venues, coupons, events, contests, products),
 * the deterministic date concierge, safety monitoring, memberships, and
 * partner analytics. Dependency-free PHP 8.1+, deterministic wherever the
 * product depends on it, no database, no API keys.
 *
 * Every time-sensitive method accepts an explicit `$now` unix timestamp so
 * behaviour is reproducible in tests and identical across environments.
 */
final class SlowDatingEngine
{
    /** Slow-chat pacing schedule: [min chat age in days => [max messages/day per sender, max characters per message]]. */
    public const PACING = [
        0 => [5, 280],
        7 => [10, 500],
        14 => [20, 1000],
        21 => [40, 2000],
    ];

    public const UNLOCK_DAYS = 30;
    public const UNLOCK_SESSIONS = 10;

    /** Popularity event weights (spec: engagement received, never sent). */
    public const POPULARITY_WEIGHTS = [
        'chat_request' => 3,
        'message_received' => 2,
        'compliment' => 4,
        'photo_received' => 5,
        'profile_view' => 1,
        'like' => 2,
        'event_invite' => 3,
        'coupon_target' => 1,
    ];

    /** Match score factor weights (must sum to 1.0). */
    public const MATCH_WEIGHTS = [
        'distance' => 0.20,
        'interests' => 0.15,
        'hobbies' => 0.10,
        'outdoor_activities' => 0.05,
        'dating_type' => 0.15,
        'faith' => 0.08,
        'politics' => 0.07,
        'income' => 0.05,
        'automobile' => 0.03,
        'occupation' => 0.05,
        'popularity_balance' => 0.07,
    ];

    public const INCOME_RANGES = ['under_30k', '30k_60k', '60k_100k', '100k_150k', '150k_plus'];
    public const AUTOMOBILES = ['none', 'economy', 'sedan', 'luxury', 'sports', 'suv', 'truck', 'ev'];
    public const DATING_TYPES = ['long_term', 'short_term', 'casual', 'marriage', 'slow_dating'];
    public const EDUCATION_LEVELS = ['high_school', 'trade_school', 'some_college', 'bachelors', 'masters', 'doctorate'];
    public const FAMILY_PLANS = ['wants_kids', 'has_kids', 'no_kids', 'open'];
    public const SMOKING = ['never', 'socially', 'regularly'];
    public const DRINKING = ['never', 'socially', 'regularly'];
    public const PETS = ['none', 'dog', 'cat', 'other'];

    /** Everything a member can require the other person to SHARE with them. */
    public const SHAREABLE_FACTS = [
        'dating_type' => 'Relationship goal',
        'faith' => 'Faith',
        'politics' => 'Politics',
        'income_range' => 'Income bracket',
        'education' => 'Education level',
        'occupation_category' => 'Occupation',
        'automobile' => 'Automobile',
        'family_plans' => 'Family plans',
        'smoking' => 'Smoking habits',
        'drinking' => 'Drinking habits',
        'pets' => 'Pets',
    ];

    /** Generic interest classifications — requirements speak in these, never in raw items. */
    public const INTEREST_CATEGORIES = [
        'adventures' => 'Adventures',
        'arts_culture' => 'Arts & culture',
        'food_dining' => 'Food & dining',
        'music_nightlife' => 'Music & nightlife',
        'outdoors' => 'Outdoors',
        'sports_fitness' => 'Sports & fitness',
        'travel' => 'Travel',
        'games' => 'Games & trivia',
        'wellness' => 'Wellness & mindfulness',
        'film_tv' => 'Film & TV',
        'reading_ideas' => 'Reading & ideas',
        'faith_community' => 'Faith & community',
    ];

    /** How raw profile items map into the generic classifications. */
    private const CATEGORY_PATTERNS = [
        'adventures' => ['escape room', 'adventure', 'climbing', 'skydiv', 'kayak', 'camping', 'road trip', 'detective', 'mystery'],
        'arts_culture' => ['art', 'museum', 'opera', 'painting', 'pottery', 'photography', 'poetry', 'theatre', 'gallery'],
        'food_dining' => ['food', 'cooking', 'baking', 'dining', 'restaurant', 'wine', 'coffee', 'dessert', 'pizza', 'pasta', 'italian'],
        'music_nightlife' => ['jazz', 'music', 'concert', 'danc', 'salsa', 'club', 'lounge', 'karaoke', 'guitar'],
        'outdoors' => ['hik', 'beach', 'sail', 'fishing', 'garden', 'picnic', 'nature', 'camping', 'cycling', 'running'],
        'sports_fitness' => ['gym', 'fitness', 'yoga', 'tennis', 'run', 'cycling', 'volleyball', 'sports', 'golf'],
        'travel' => ['travel', 'cruise', 'trip', 'tour'],
        'games' => ['board game', 'chess', 'trivia', 'puzzle', 'gaming', 'cards', 'escape room'],
        'wellness' => ['yoga', 'meditation', 'mindful', 'wellness', 'spa'],
        'film_tv' => ['film', 'movie', 'cinema', 'series'],
        'reading_ideas' => ['read', 'book', 'writing', 'poetry', 'philosophy'],
        'faith_community' => ['church', 'faith', 'volunteer', 'community'],
    ];

    /**
     * The generic classifications a profile's interests, hobbies, and
     * outdoor activities fall into — derived automatically, so "escape
     * rooms" reads as Adventures and Games, never as a raw item.
     *
     * @param array<string, mixed> $profile
     * @return array<int, string>
     */
    public function interestCategories(array $profile): array
    {
        $items = strtolower(implode(' | ', array_merge(
            (array) ($profile['interests'] ?? []),
            (array) ($profile['hobbies'] ?? []),
            (array) ($profile['outdoor_activities'] ?? []),
        )));
        $categories = [];
        foreach (self::CATEGORY_PATTERNS as $category => $patterns) {
            foreach ($patterns as $pattern) {
                if ($items !== '' && str_contains($items, $pattern)) {
                    $categories[] = $category;
                    break;
                }
            }
        }
        return $categories;
    }
    public const MEMBER_TIERS = ['free', 'member', 'vip', 'elite'];
    public const PARTNER_TIERS = ['basic', 'pro', 'elite'];
    public const VENUE_CATEGORIES = ['restaurant', 'lounge', 'cruise', 'tour', 'experience', 'bodyguard', 'vendor'];

    public const MEMBERSHIP_PRICES = ['member' => 19.00, 'vip' => 79.00, 'elite' => 199.00];

    private const COMMON_PASSWORDS = [
        'password', 'password1', '123456', '12345678', 'qwerty', 'letmein',
        'iloveyou', 'admin', 'welcome', 'monkey', 'dragon', 'sunshine',
        'princess', 'football', 'baseball', 'abc123', 'trustno1', 'password123',
    ];

    private const COMPLIMENT_PATTERNS = [
        '/\byou look\b/i', '/\bbeautiful\b/i', '/\bgorgeous\b/i', '/\bhandsome\b/i',
        '/\bgreat smile\b/i', '/\blove your profile\b/i', '/\bcute\b/i', '/\bstunning\b/i',
    ];

    private const RED_FLAG_PATTERNS = [
        'money_request' => '/\b(wire (me )?money|gift ?cards?|western union|moneygram|send (me )?(money|cash|bitcoin|crypto)|bank details|routing number)\b/i',
        'urgency_pressure' => '/\b(right now or|hurry up|last chance|act now|before it\'?s too late|don\'?t tell anyone)\b/i',
        'off_platform_push' => '/\b(text me|call me|whats?app|telegram|snapchat|kik|move (this|our chat) off)\b/i',
        'coercion' => '/\b(you owe me|if you really loved|prove you love|send (me )?(a )?(photo|pic)s? or)\b/i',
    ];

    private SlowDatingStore $store;

    public function __construct(?SlowDatingStore $store = null)
    {
        $this->store = $store ?? new SlowDatingStore();
    }

    public function store(): SlowDatingStore
    {
        return $this->store;
    }

    // ------------------------------------------------------------------
    // Accounts, passwords, sessions
    // ------------------------------------------------------------------

    /**
     * Register a member. The user id is always generated by the platform.
     * The caller may supply a password (validated against the strong
     * policy) or request an auto-generated strong password, returned once.
     *
     * @return array{user_id: string, email: string, password_generated: bool, auto_password: ?string, token: string}
     */
    public function signupMember(string $email, ?string $password, bool $useAutoPassword, ?int $now = null): array
    {
        $now ??= time();
        $email = strtolower(trim($email));
        if (filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
            throw new InvalidArgumentException('A valid email address is required.');
        }
        if ($this->store->where('users', ['email' => $email]) !== []) {
            throw new InvalidArgumentException('An account already exists for this email address.');
        }
        $generated = false;
        if ($useAutoPassword || $password === null || $password === '') {
            $password = $this->generateStrongPassword();
            $generated = true;
        } else {
            $problems = $this->passwordProblems($password);
            if ($problems !== []) {
                throw new InvalidArgumentException('Weak password: ' . implode(' ', $problems));
            }
        }
        $userId = $this->newUserId($now);
        $this->store->put('users', $userId, [
            'email' => $email,
            'password_hash' => password_hash($password, PASSWORD_DEFAULT),
            'membership_tier' => 'free',
            'membership_expires_at' => null,
            'created_at' => $now,
            'profile' => $this->defaultProfile(),
            'videos' => [],
        ]);
        return [
            'user_id' => $userId,
            'email' => $email,
            'password_generated' => $generated,
            'auto_password' => $generated ? $password : null,
            'token' => $this->issueToken($userId, 'member', $now),
        ];
    }

    /** @return array{token: string, user_id: string} */
    public function login(string $email, string $password, ?int $now = null): array
    {
        $now ??= time();
        $rows = $this->store->where('users', ['email' => strtolower(trim($email))]);
        $user = $rows[0] ?? null;
        if ($user === null || !password_verify($password, (string) $user['password_hash'])) {
            throw new InvalidArgumentException('Invalid email or password.');
        }
        return ['token' => $this->issueToken((string) $user['id'], 'member', $now), 'user_id' => (string) $user['id']];
    }

    /** Resolve a bearer token to [subject id, kind] or null. */
    public function authenticate(string $token): ?array
    {
        $record = $this->store->get('tokens', hash('sha256', $token));
        return $record === null ? null : [(string) $record['subject_id'], (string) $record['kind']];
    }

    /** Generate a strong password: 20 chars, all four character classes. */
    public function generateStrongPassword(int $length = 20): string
    {
        $length = max(16, min(24, $length));
        $sets = [
            'ABCDEFGHJKLMNPQRSTUVWXYZ',
            'abcdefghijkmnopqrstuvwxyz',
            '23456789',
            '!@#$%^&*()-_=+[]{}',
        ];
        $all = implode('', $sets);
        do {
            $chars = [];
            foreach ($sets as $set) {
                $chars[] = $set[random_int(0, strlen($set) - 1)];
            }
            while (count($chars) < $length) {
                $chars[] = $all[random_int(0, strlen($all) - 1)];
            }
            shuffle($chars);
            $password = implode('', $chars);
        } while ($this->passwordProblems($password) !== []);
        return $password;
    }

    /**
     * Strong-password policy: >=12 chars, upper, lower, digit, symbol,
     * and not on the common-password blacklist.
     *
     * @return array<int, string> Problems (empty when the password is strong).
     */
    public function passwordProblems(string $password): array
    {
        $problems = [];
        if (strlen($password) < 12) {
            $problems[] = 'Use at least 12 characters.';
        }
        if (preg_match('/[A-Z]/', $password) !== 1) {
            $problems[] = 'Add an uppercase letter.';
        }
        if (preg_match('/[a-z]/', $password) !== 1) {
            $problems[] = 'Add a lowercase letter.';
        }
        if (preg_match('/\d/', $password) !== 1) {
            $problems[] = 'Add a digit.';
        }
        if (preg_match('/[^A-Za-z0-9]/', $password) !== 1) {
            $problems[] = 'Add a symbol.';
        }
        if (in_array(strtolower($password), self::COMMON_PASSWORDS, true)) {
            $problems[] = 'This password is too common.';
        }
        return $problems;
    }

    // ------------------------------------------------------------------
    // Profiles & YouTube videos
    // ------------------------------------------------------------------

    /** @return array<string, mixed> */
    public function profile(string $userId): array
    {
        $user = $this->requireUser($userId);
        return ['user_id' => $userId] + (array) $user['profile'] + ['videos' => (array) $user['videos']];
    }

    /**
     * @param array<string, mixed> $fields
     * @return array<string, mixed>
     */
    public function updateProfile(string $userId, array $fields): array
    {
        $user = $this->requireUser($userId);
        $profile = (array) $user['profile'];
        foreach (['age' => 'int', 'gender' => 'string', 'zip_code' => 'string', 'dating_type' => 'string',
                  'faith' => 'string', 'politics' => 'string', 'income_range' => 'string',
                  'automobile' => 'string', 'occupation_category' => 'string', 'education' => 'string',
                  'family_plans' => 'string', 'smoking' => 'string', 'drinking' => 'string', 'pets' => 'string',
                  'display_name' => 'string'] as $field => $type) {
            if (array_key_exists($field, $fields)) {
                $profile[$field] = $type === 'int' ? (int) $fields[$field] : trim((string) $fields[$field]);
            }
        }
        foreach (['interests', 'hobbies', 'outdoor_activities'] as $listField) {
            if (array_key_exists($listField, $fields)) {
                $value = $fields[$listField];
                $items = is_array($value) ? $value : preg_split('/\s*,\s*/', (string) $value, -1, PREG_SPLIT_NO_EMPTY);
                $profile[$listField] = array_values(array_unique(array_map(
                    static fn ($item): string => strtolower(trim((string) $item)),
                    (array) $items,
                )));
            }
        }
        if ($profile['income_range'] !== '' && !in_array($profile['income_range'], self::INCOME_RANGES, true)) {
            throw new InvalidArgumentException('Unknown income range.');
        }
        if ($profile['automobile'] !== '' && !in_array($profile['automobile'], self::AUTOMOBILES, true)) {
            throw new InvalidArgumentException('Unknown automobile category.');
        }
        if ($profile['dating_type'] !== '' && !in_array($profile['dating_type'], self::DATING_TYPES, true)) {
            throw new InvalidArgumentException('Unknown dating type.');
        }
        if (($profile['education'] ?? '') !== '' && !in_array($profile['education'], self::EDUCATION_LEVELS, true)) {
            throw new InvalidArgumentException('Unknown education level.');
        }
        foreach (['family_plans' => self::FAMILY_PLANS, 'smoking' => self::SMOKING,
                  'drinking' => self::DRINKING, 'pets' => self::PETS] as $lifestyleField => $allowed) {
            if (($profile[$lifestyleField] ?? '') !== '' && !in_array($profile[$lifestyleField], $allowed, true)) {
                throw new InvalidArgumentException('Unknown ' . str_replace('_', ' ', $lifestyleField) . ' value.');
            }
        }
        if ($profile['age'] !== 0 && $profile['age'] < 18) {
            throw new InvalidArgumentException('Members must be 18 or older.');
        }
        $user['profile'] = $profile;
        $this->store->put('users', $userId, $user);
        return $this->profile($userId);
    }

    /**
     * Attach a YouTube video to a profile. Only real YouTube URLs are
     * accepted; the stored embed URL is always derived server-side.
     *
     * @return array{video_id: string, youtube_url: string, embed_url: string}
     */
    public function addProfileVideo(string $userId, string $youtubeUrl): array
    {
        $videoKey = $this->youtubeVideoKey($youtubeUrl);
        if ($videoKey === null) {
            throw new InvalidArgumentException('Only valid YouTube video URLs can be embedded.');
        }
        $user = $this->requireUser($userId);
        $videos = (array) $user['videos'];
        if (count($videos) >= 5) {
            throw new InvalidArgumentException('A profile can carry at most 5 videos.');
        }
        $record = [
            'video_id' => 'vid_' . substr(hash('sha256', $userId . '|' . $videoKey), 0, 10),
            'youtube_url' => 'https://www.youtube.com/watch?v=' . $videoKey,
            'embed_url' => 'https://www.youtube.com/embed/' . $videoKey,
        ];
        foreach ($videos as $existing) {
            if ($existing['video_id'] === $record['video_id']) {
                throw new InvalidArgumentException('This video is already on the profile.');
            }
        }
        $videos[] = $record;
        $user['videos'] = $videos;
        $this->store->put('users', $userId, $user);
        return $record;
    }

    public function removeProfileVideo(string $userId, string $videoId): void
    {
        $user = $this->requireUser($userId);
        $user['videos'] = array_values(array_filter(
            (array) $user['videos'],
            static fn (array $video): bool => $video['video_id'] !== $videoId,
        ));
        $this->store->put('users', $userId, $user);
    }

    public function youtubeVideoKey(string $url): ?string
    {
        $parts = parse_url(trim($url));
        if (!is_array($parts) || !isset($parts['host'])) {
            return null;
        }
        $host = strtolower($parts['host']);
        $path = $parts['path'] ?? '';
        $key = null;
        if (in_array($host, ['www.youtube.com', 'youtube.com', 'm.youtube.com'], true)) {
            if ($path === '/watch') {
                parse_str($parts['query'] ?? '', $query);
                $key = $query['v'] ?? null;
            } elseif (preg_match('#^/(embed|shorts)/([A-Za-z0-9_-]{5,20})#', $path, $m) === 1) {
                $key = $m[2];
            }
        } elseif ($host === 'youtu.be' && preg_match('#^/([A-Za-z0-9_-]{5,20})#', $path, $m) === 1) {
            $key = $m[1];
        }
        return is_string($key) && preg_match('/^[A-Za-z0-9_-]{5,20}$/', $key) === 1 ? $key : null;
    }

    // ------------------------------------------------------------------
    // Profile images: generated art or uploaded photos (admin-switched)
    // ------------------------------------------------------------------

    public const AVATAR_MODES = ['generated', 'uploads'];
    public const PHOTO_MAX_BYTES = 2 * 1024 * 1024;
    private const PHOTO_TYPES = [
        'image/jpeg' => ['ext' => 'jpg', 'magic' => "\xFF\xD8\xFF"],
        'image/png' => ['ext' => 'png', 'magic' => "\x89PNG"],
        'image/webp' => ['ext' => 'webp', 'magic' => 'RIFF'],
    ];

    /** Platform-wide image source: 'generated' (SVG art) or 'uploads'. */
    public function avatarMode(): string
    {
        $setting = $this->store->get('settings', 'avatar_mode');
        $mode = (string) ($setting['value'] ?? 'generated');
        return in_array($mode, self::AVATAR_MODES, true) ? $mode : 'generated';
    }

    /** Admin-only switch between generated art and uploaded photos. */
    public function setAvatarMode(string $adminId, string $mode): array
    {
        if ($this->store->get('admins', $adminId) === null) {
            throw new InvalidArgumentException('Only admins can change the profile-image mode.');
        }
        if (!in_array($mode, self::AVATAR_MODES, true)) {
            throw new InvalidArgumentException('Profile images are either "generated" or "uploads".');
        }
        $this->store->put('settings', 'avatar_mode', ['value' => $mode]);
        return ['avatar_mode' => $mode];
    }

    /** The three profile pictures: generated artwork plus two upload slots. */
    public const PHOTO_SLOTS = ['public', 'private'];
    public const IMAGE_CHOICES = ['generated', 'public', 'private'];

    /**
     * Store one of a member's pictures (JPEG, PNG, or WebP, max 2 MB) in a
     * slot: 'public' is their real picture, 'private' is the picture only
     * revealed inside chats where they choose it. Bytes are validated
     * against the declared type's magic signature and written under
     * <state>/photos with a server-chosen name.
     *
     * @return array{file: string, mime: string}
     */
    public function setMemberPhoto(string $userId, string $bytes, string $mime, string $slot = 'public'): array
    {
        $user = $this->requireUser($userId);
        if (!in_array($slot, self::PHOTO_SLOTS, true)) {
            throw new InvalidArgumentException('Picture slots are "public" (real picture) or "private".');
        }
        $type = self::PHOTO_TYPES[strtolower(trim($mime))] ?? null;
        if ($type === null) {
            throw new InvalidArgumentException('Photos must be JPEG, PNG, or WebP.');
        }
        if ($bytes === '' || strlen($bytes) > self::PHOTO_MAX_BYTES) {
            throw new InvalidArgumentException('Photos must be between 1 byte and 2 MB.');
        }
        if (!str_starts_with($bytes, $type['magic'])) {
            throw new InvalidArgumentException('The file does not look like a ' . $mime . ' image.');
        }
        $dir = $this->store->directory() . '/photos';
        if (!is_dir($dir) && !@mkdir($dir, 0775, true) && !is_dir($dir)) {
            throw new RuntimeException('Could not create the photos directory.');
        }
        $file = $userId . '.' . $slot . '.' . $type['ext'];
        foreach (self::PHOTO_TYPES as $other) {
            @unlink($dir . '/' . $userId . '.' . $slot . '.' . $other['ext']);
        }
        if (file_put_contents($dir . '/' . $file, $bytes) === false) {
            throw new RuntimeException('Could not store the photo.');
        }
        $photos = (array) ($user['photos'] ?? []);
        $photos[$slot] = ['file' => $file, 'mime' => strtolower(trim($mime))];
        $user['photos'] = $photos;
        $this->store->put('users', $userId, $user);
        return $photos[$slot];
    }

    /** @return array{path: string, mime: string}|null The stored picture in a slot, when one exists. */
    public function memberPhoto(string $userId, string $slot = 'public'): ?array
    {
        $user = $this->store->get('users', $userId);
        $photo = ($user['photos'][$slot] ?? null);
        if (!is_array($photo) && $slot === 'public') {
            $photo = $user['photo'] ?? null;   // legacy single-photo records
        }
        if (!is_array($photo)) {
            return null;
        }
        $path = $this->store->directory() . '/photos/' . basename((string) $photo['file']);
        return is_file($path) ? ['path' => $path, 'mime' => (string) $photo['mime']] : null;
    }

    /**
     * The profile's picture roster: every member has the generated artwork;
     * the real and private pictures fill in as they upload. A complete
     * profile has all three.
     *
     * @return array{generated: bool, public: bool, private: bool, complete: bool}
     */
    public function pictureRoster(string $userId): array
    {
        $this->requireUser($userId);
        $roster = [
            'generated' => true,
            'public' => $this->memberPhoto($userId, 'public') !== null,
            'private' => $this->memberPhoto($userId, 'private') !== null,
        ];
        $roster['complete'] = $roster['public'] && $roster['private'];
        return $roster;
    }

    /**
     * When two members connect, each chooses which of their three pictures
     * the other person sees in that chat: generated artwork (the default
     * until they choose), their real picture, or their private picture.
     */
    public function setChatImageChoice(string $chatId, string $userId, string $choice): array
    {
        $chat = $this->requireChat($chatId);
        if (!in_array($userId, (array) $chat['participants'], true)) {
            throw new InvalidArgumentException('Only chat participants can choose a picture for this chat.');
        }
        if (!in_array($choice, self::IMAGE_CHOICES, true)) {
            throw new InvalidArgumentException('The choices are artwork, your real picture, or your private picture.');
        }
        if ($choice !== 'generated' && $this->memberPhoto($userId, $choice) === null) {
            throw new InvalidArgumentException('Upload that picture to your profile first.');
        }
        $choices = (array) ($chat['image_choices'] ?? []);
        $choices[$userId] = $choice;
        $chat['image_choices'] = $choices;
        $this->store->put('chats', (string) $chat['id'], $chat);
        return ['chat_id' => (string) $chat['id'], 'user_id' => $userId, 'image_choice' => $choice];
    }

    /** The picture a viewer is entitled to see for a member inside one chat. */
    public function chatImageChoice(string $chatId, string $memberId): string
    {
        $chat = $this->requireChat($chatId);
        if (!in_array($memberId, (array) $chat['participants'], true)) {
            throw new InvalidArgumentException('That member is not part of this chat.');
        }
        $choice = (string) (($chat['image_choices'][$memberId] ?? '') ?: 'generated');
        return in_array($choice, self::IMAGE_CHOICES, true) ? $choice : 'generated';
    }

    // ------------------------------------------------------------------
    // Membership billing
    // ------------------------------------------------------------------

    /** @return array{membership_tier: string, membership_expires_at: int, price: float} */
    public function subscribeMembership(string $userId, string $tier, ?int $now = null): array
    {
        $now ??= time();
        if (!isset(self::MEMBERSHIP_PRICES[$tier])) {
            throw new InvalidArgumentException('Unknown membership tier.');
        }
        $user = $this->requireUser($userId);
        $user['membership_tier'] = $tier;
        $user['membership_expires_at'] = $now + 365 * 86400;
        $this->store->put('users', $userId, $user);
        $this->logAnalytics('membership_purchase', $userId, null, ['tier' => $tier], $now);
        return [
            'membership_tier' => $tier,
            'membership_expires_at' => $user['membership_expires_at'],
            'price' => self::MEMBERSHIP_PRICES[$tier],
        ];
    }

    // ------------------------------------------------------------------
    // Slow chat
    // ------------------------------------------------------------------

    /** @return array<string, mixed> */
    public function startChat(string $initiatorId, string $recipientId, ?int $now = null): array
    {
        $now ??= time();
        $this->requireUser($initiatorId);
        $this->requireUser($recipientId);
        if ($initiatorId === $recipientId) {
            throw new InvalidArgumentException('A chat needs two different members.');
        }
        $pairKey = implode('|', [min($initiatorId, $recipientId), max($initiatorId, $recipientId)]);
        foreach ($this->store->all('chats') as $chat) {
            if ($chat['pair_key'] === $pairKey) {
                return $chat;
            }
        }
        $chatId = 'chat_' . substr(hash('sha256', $pairKey . $now), 0, 12);
        $chat = [
            'pair_key' => $pairKey,
            'participants' => [$initiatorId, $recipientId],
            'started_at' => $now,
            'early_unlock' => false,
            'messages' => [],
        ];
        $this->store->put('chats', $chatId, $chat);
        $this->recordPopularityEvent($recipientId, 'chat_request', $now);
        return $chat + ['id' => $chatId];
    }

    /** @return array<int, array<string, mixed>> */
    public function chatsFor(string $userId): array
    {
        $rows = [];
        foreach ($this->store->all('chats') as $chat) {
            if (in_array($userId, (array) $chat['participants'], true)) {
                $rows[] = $chat;
            }
        }
        usort($rows, static fn (array $a, array $b): int => $b['started_at'] <=> $a['started_at']);
        return $rows;
    }

    /**
     * The live pacing/unlock state of a chat.
     *
     * @return array<string, mixed>
     */
    public function chatStatus(string $chatId, ?int $now = null): array
    {
        $now ??= time();
        $chat = $this->requireChat($chatId);
        $ageDays = intdiv(max(0, $now - (int) $chat['started_at']), 86400);
        $sessions = $this->completedSessions($chat);
        $unlocked = (bool) $chat['early_unlock']
            || ($ageDays >= self::UNLOCK_DAYS && $sessions >= self::UNLOCK_SESSIONS);
        [$dailyLimit, $sizeLimit] = $this->pacingFor($ageDays);
        return [
            'chat_id' => $chatId,
            'stage' => $unlocked ? 'real_time' : 'slow_chat',
            'age_days' => $ageDays,
            'completed_sessions' => $sessions,
            'sessions_required' => self::UNLOCK_SESSIONS,
            'days_required' => self::UNLOCK_DAYS,
            'unlocked' => $unlocked,
            'early_unlock' => (bool) $chat['early_unlock'],
            'daily_message_limit' => $unlocked ? null : $dailyLimit,
            'message_size_limit' => $unlocked ? null : $sizeLimit,
            'contact_sharing_allowed' => $unlocked,
        ];
    }

    /**
     * Send a message under the slow-chat contract. Before unlock, personal
     * contact data (emails, phone numbers, URLs, social handles) is ERASED
     * from the stored text and reported back as a filter notice; pacing
     * limits apply; red-flag patterns always raise safety events.
     *
     * @return array<string, mixed>
     */
    public function sendMessage(string $chatId, string $senderId, string $text, ?int $now = null): array
    {
        $now ??= time();
        $chat = $this->requireChat($chatId);
        if (!in_array($senderId, (array) $chat['participants'], true)) {
            throw new InvalidArgumentException('Only chat participants can send messages.');
        }
        $text = trim($text);
        if ($text === '') {
            throw new InvalidArgumentException('A message needs some text.');
        }
        $status = $this->chatStatus($chatId, $now);
        if (!$status['unlocked']) {
            if (mb_strlen($text) > $status['message_size_limit']) {
                throw new InvalidArgumentException(sprintf(
                    'Slow-chat stage: messages are limited to %d characters right now.',
                    $status['message_size_limit'],
                ));
            }
            $sentToday = 0;
            $dayStart = $now - ($now % 86400);
            foreach ((array) $chat['messages'] as $message) {
                if ($message['sender_id'] === $senderId && $message['sent_at'] >= $dayStart) {
                    $sentToday++;
                }
            }
            if ($sentToday >= $status['daily_message_limit']) {
                throw new InvalidArgumentException(sprintf(
                    'Slow-chat stage: you have used all %d messages for today. The pace opens up as the chat matures.',
                    $status['daily_message_limit'],
                ));
            }
        }
        $filtered = ['text' => $text, 'redactions' => 0];
        if (!$status['unlocked']) {
            $filtered = $this->filterContactData($text);
        }
        $recipientId = $this->otherParticipant($chat, $senderId);
        $flags = [];
        foreach (self::RED_FLAG_PATTERNS as $flag => $pattern) {
            if (preg_match($pattern, $text) === 1) {
                $flags[] = $flag;
            }
        }
        if ($flags !== []) {
            $this->logSafetyEvent($recipientId, $senderId, $chatId, $flags, $now);
        }
        $message = [
            'message_id' => 'msg_' . substr(hash('sha256', $chatId . $senderId . $now . count((array) $chat['messages'])), 0, 12),
            'sender_id' => $senderId,
            'text' => $filtered['text'],
            'sent_at' => $now,
            'contact_data_removed' => $filtered['redactions'],
            'red_flags' => $flags,
        ];
        $chat['messages'][] = $message;
        $chatRecordId = (string) $chat['id'];
        $this->store->put('chats', $chatRecordId, $chat);
        $this->recordPopularityEvent($recipientId, 'message_received', $now);
        foreach (self::COMPLIMENT_PATTERNS as $pattern) {
            if (preg_match($pattern, $text) === 1) {
                $this->recordPopularityEvent($recipientId, 'compliment', $now);
                break;
            }
        }
        return $message + ['chat_status' => $this->chatStatus($chatRecordId, $now)];
    }

    /**
     * Erase personal contact data from a message: emails, phone numbers,
     * URLs, and social handles are removed, never stored.
     *
     * @return array{text: string, redactions: int}
     */
    public function filterContactData(string $text): array
    {
        $patterns = [
            '/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/',                    // email
            '/\+?\d[\d\s().-]{6,}\d/',                                              // phone-like digit runs
            '/\bhttps?:\/\/\S+/i',                                                  // URLs
            '/\bwww\.\S+/i',
            '/(?<=^|\s)@[A-Za-z0-9_.]{3,}/',                                        // social handles
            '/\b(insta(gram)?|snap(chat)?|telegram|whats?app|signal)\s*[:\-]?\s*[A-Za-z0-9_.]{3,}/i',
        ];
        $redactions = 0;
        foreach ($patterns as $pattern) {
            $text = (string) preg_replace_callback($pattern, static function () use (&$redactions): string {
                $redactions++;
                return '[contact info removed]';
            }, $text);
        }
        return ['text' => $text, 'redactions' => $redactions];
    }

    /**
     * Share an image in a chat (JPEG, PNG, or WebP, max 2 MB, optional
     * caption). An image message counts against the slow-chat daily quota
     * like any other message; captions pass through the contact-data
     * filter before unlock and red-flag detection always; the recipient
     * is credited a photo_received popularity event. The file is visible
     * only to the two participants (served by chatimage.php).
     *
     * @return array<string, mixed>
     */
    public function sendImageMessage(string $chatId, string $senderId, string $bytes, string $mime, string $caption = '', ?int $now = null): array
    {
        $now ??= time();
        $chat = $this->requireChat($chatId);
        if (!in_array($senderId, (array) $chat['participants'], true)) {
            throw new InvalidArgumentException('Only chat participants can share images.');
        }
        $type = self::PHOTO_TYPES[strtolower(trim($mime))] ?? null;
        if ($type === null) {
            throw new InvalidArgumentException('Shared images must be JPEG, PNG, or WebP.');
        }
        if ($bytes === '' || strlen($bytes) > self::PHOTO_MAX_BYTES) {
            throw new InvalidArgumentException('Shared images must be between 1 byte and 2 MB.');
        }
        if (!str_starts_with($bytes, $type['magic'])) {
            throw new InvalidArgumentException('The file does not look like a ' . $mime . ' image.');
        }
        $status = $this->chatStatus($chatId, $now);
        if (!$status['unlocked']) {
            $sentToday = 0;
            $dayStart = $now - ($now % 86400);
            foreach ((array) $chat['messages'] as $message) {
                if ($message['sender_id'] === $senderId && $message['sent_at'] >= $dayStart) {
                    $sentToday++;
                }
            }
            if ($sentToday >= $status['daily_message_limit']) {
                throw new InvalidArgumentException(sprintf(
                    'Slow-chat stage: you have used all %d messages for today. The pace opens up as the chat matures.',
                    $status['daily_message_limit'],
                ));
            }
        }
        $caption = trim($caption);
        $filtered = ['text' => $caption, 'redactions' => 0];
        if ($caption !== '' && !$status['unlocked']) {
            $filtered = $this->filterContactData($caption);
        }
        $recipientId = $this->otherParticipant($chat, $senderId);
        $flags = [];
        foreach (self::RED_FLAG_PATTERNS as $flag => $pattern) {
            if ($caption !== '' && preg_match($pattern, $caption) === 1) {
                $flags[] = $flag;
            }
        }
        if ($flags !== []) {
            $this->logSafetyEvent($recipientId, $senderId, $chatId, $flags, $now);
        }
        $dir = $this->store->directory() . '/chatmedia';
        if (!is_dir($dir) && !@mkdir($dir, 0775, true) && !is_dir($dir)) {
            throw new RuntimeException('Could not create the chat media directory.');
        }
        $messageId = 'msg_' . substr(hash('sha256', $chatId . $senderId . $now . count((array) $chat['messages'])), 0, 12);
        $file = $messageId . '.' . $type['ext'];
        if (file_put_contents($dir . '/' . $file, $bytes) === false) {
            throw new RuntimeException('Could not store the shared image.');
        }
        $message = [
            'message_id' => $messageId,
            'sender_id' => $senderId,
            'text' => $filtered['text'],
            'sent_at' => $now,
            'contact_data_removed' => $filtered['redactions'],
            'red_flags' => $flags,
            'image' => ['file' => $file, 'mime' => strtolower(trim($mime))],
        ];
        $chat['messages'][] = $message;
        $chatRecordId = (string) $chat['id'];
        $this->store->put('chats', $chatRecordId, $chat);
        $this->recordPopularityEvent($recipientId, 'photo_received', $now);
        return $message + ['chat_status' => $this->chatStatus($chatRecordId, $now)];
    }

    /** @return array{path: string, mime: string}|null A shared image, for participants only. */
    public function chatImage(string $chatId, string $messageId, string $viewerId): ?array
    {
        $chat = $this->requireChat($chatId);
        if (!in_array($viewerId, (array) $chat['participants'], true)) {
            return null;
        }
        foreach ((array) $chat['messages'] as $message) {
            if (($message['message_id'] ?? '') === $messageId && isset($message['image'])) {
                $path = $this->store->directory() . '/chatmedia/' . basename((string) $message['image']['file']);
                return is_file($path) ? ['path' => $path, 'mime' => (string) $message['image']['mime']] : null;
            }
        }
        return null;
    }

    /** VIP/Elite members may unlock a chat to real time before the schedule. */
    public function purchaseEarlyUnlock(string $chatId, string $userId, ?int $now = null): array
    {
        $now ??= time();
        $chat = $this->requireChat($chatId);
        if (!in_array($userId, (array) $chat['participants'], true)) {
            throw new InvalidArgumentException('Only chat participants can unlock a chat.');
        }
        $user = $this->requireUser($userId);
        if (!in_array((string) $user['membership_tier'], ['vip', 'elite'], true)) {
            throw new InvalidArgumentException('Early unlock is a VIP membership feature.');
        }
        $chat['early_unlock'] = true;
        $this->store->put('chats', (string) $chat['id'], $chat);
        $this->logAnalytics('early_unlock', $userId, null, ['chat_id' => $chatId], $now);
        return $this->chatStatus($chatId, $now);
    }

    // ------------------------------------------------------------------
    // Popularity
    // ------------------------------------------------------------------

    public function recordPopularityEvent(string $userId, string $type, ?int $now = null): void
    {
        $now ??= time();
        if (!isset(self::POPULARITY_WEIGHTS[$type])) {
            throw new InvalidArgumentException('Unknown popularity event type: ' . $type);
        }
        $id = 'pop_' . substr(hash('sha256', $userId . $type . $now . $this->store->count('popularity_events')), 0, 14);
        $this->store->put('popularity_events', $id, [
            'user_id' => $userId,
            'event_type' => $type,
            'weight' => self::POPULARITY_WEIGHTS[$type],
            'timestamp' => $now,
        ]);
    }

    /**
     * Normalized popularity: raw weighted engagement scaled so that the
     * cohort average sits at 50, capped at 100. Cohorts are per gender so
     * one gender's volume never distorts the other's scores. Raw counts
     * are never exposed to other members — only via the owner breakdown.
     *
     * @return array{user_id: string, popularity_score: int, percentile: int, trend: string, last_updated: int}
     */
    public function popularity(string $userId, ?int $now = null): array
    {
        $now ??= time();
        $user = $this->requireUser($userId);
        $gender = (string) ($user['profile']['gender'] ?? '');
        $raw = $this->rawPopularity($userId);
        $cohort = [];
        foreach ($this->store->all('users') as $other) {
            if ((string) ($other['profile']['gender'] ?? '') === $gender) {
                $cohort[(string) $other['id']] = $this->rawPopularity((string) $other['id']);
            }
        }
        $average = count($cohort) > 0 ? array_sum($cohort) / count($cohort) : 0.0;
        $score = $average > 0 ? (int) min(100, round($raw / $average * 50)) : 0;
        $below = count(array_filter($cohort, static fn (int $value): bool => $value < $raw));
        $percentile = count($cohort) > 0
            ? (int) max(1, min(100, round(100 - ($below / count($cohort) * 100))))
            : 100;
        return [
            'user_id' => $userId,
            'popularity_score' => $score,
            'percentile' => $percentile,
            'trend' => $this->popularityTrend($userId, $now),
            'last_updated' => $now,
        ];
    }

    /** @return array<string, mixed> Owner-only metric breakdown. */
    public function popularityBreakdown(string $userId, ?int $now = null): array
    {
        $now ??= time();
        $metrics = array_fill_keys(array_keys(self::POPULARITY_WEIGHTS), 0);
        foreach ($this->store->where('popularity_events', ['user_id' => $userId]) as $event) {
            $metrics[(string) $event['event_type']]++;
        }
        return [
            'user_id' => $userId,
            'metrics' => $metrics,
            'weights' => self::POPULARITY_WEIGHTS,
            'raw_score' => $this->rawPopularity($userId),
            'normalized_score' => $this->popularity($userId, $now)['popularity_score'],
        ];
    }

    private function rawPopularity(string $userId): int
    {
        $raw = 0;
        foreach ($this->store->where('popularity_events', ['user_id' => $userId]) as $event) {
            $raw += (int) $event['weight'];
        }
        return $raw;
    }

    private function popularityTrend(string $userId, int $now): string
    {
        $recent = 0;
        $previous = 0;
        foreach ($this->store->where('popularity_events', ['user_id' => $userId]) as $event) {
            $age = $now - (int) $event['timestamp'];
            if ($age <= 7 * 86400) {
                $recent += (int) $event['weight'];
            } elseif ($age <= 14 * 86400) {
                $previous += (int) $event['weight'];
            }
        }
        if ($recent > $previous) {
            return 'rising';
        }
        return $recent < $previous ? 'falling' : 'stable';
    }

    // ------------------------------------------------------------------
    // 2026 pack: verification, prompts, co-pilot, daily drop, communities
    // ------------------------------------------------------------------

    /** Prompt catalog (Hinge-style personality depth). */
    public const PROMPTS = [
        'p1' => 'The way to my heart is…',
        'p2' => 'A perfect Saturday looks like…',
        'p3' => 'I geek out about…',
        'p4' => 'The last thing that made me laugh out loud…',
        'p5' => 'I\'m looking for someone who…',
        'p6' => 'My most controversial food opinion…',
        'p7' => 'Three things I can\'t live without…',
        'p8' => 'The trip I can\'t stop talking about…',
    ];

    /** Niche community hubs. */
    public const COMMUNITIES = [
        'creatives' => 'Creatives',
        'tech-founders' => 'Tech founders',
        'spiritual' => 'Spiritual & mindful',
        'single-parents' => 'Single parents',
        'lgbtq' => 'LGBTQ+',
        'fitness' => 'Fitness lifestyle',
        'travelers' => 'Travelers',
        'entrepreneurs' => 'Entrepreneurs',
    ];

    public const DAILY_DROP_SIZE = 3;

    /** Member asks to be verified; an admin reviews (trust badge). */
    public function requestVerification(string $userId, ?int $now = null): array
    {
        $now ??= time();
        $user = $this->requireUser($userId);
        $status = (string) ($user['verification']['status'] ?? 'none');
        if ($status === 'verified') {
            return ['status' => 'verified'];
        }
        $user['verification'] = ['status' => 'pending', 'requested_at' => $now];
        $this->store->put('users', $userId, $user);
        return ['status' => 'pending'];
    }

    public function verificationStatus(string $userId): string
    {
        $user = $this->requireUser($userId);
        $status = (string) ($user['verification']['status'] ?? 'none');
        return in_array($status, ['none', 'pending', 'verified'], true) ? $status : 'none';
    }

    /** @return array<int, array<string, mixed>> Members awaiting review. */
    public function pendingVerifications(): array
    {
        $rows = [];
        foreach ($this->store->all('users') as $user) {
            if (($user['verification']['status'] ?? '') === 'pending') {
                $rows[] = [
                    'user_id' => (string) $user['id'],
                    'display_name' => (string) ($user['profile']['display_name'] ?? ''),
                    'requested_at' => (int) ($user['verification']['requested_at'] ?? 0),
                ];
            }
        }
        usort($rows, static fn (array $a, array $b): int => $a['requested_at'] <=> $b['requested_at']);
        return $rows;
    }

    /** Admin approves or rejects a verification request. */
    public function reviewVerification(string $adminId, string $userId, bool $approve, ?int $now = null): array
    {
        $now ??= time();
        if ($this->store->get('admins', $adminId) === null) {
            throw new InvalidArgumentException('Only admins review verifications.');
        }
        $user = $this->requireUser($userId);
        $user['verification'] = $approve
            ? ['status' => 'verified', 'verified_at' => $now, 'by' => $adminId]
            : ['status' => 'none'];
        $this->store->put('users', $userId, $user);
        return ['user_id' => $userId, 'status' => $approve ? 'verified' : 'none'];
    }

    /**
     * Save up to three prompt answers (personality depth on the profile).
     *
     * @param array<int, array{id: string, text: string}> $answers
     */
    public function setPrompts(string $userId, array $answers): array
    {
        $user = $this->requireUser($userId);
        $stored = [];
        foreach (array_slice($answers, 0, 3) as $answer) {
            $id = (string) ($answer['id'] ?? '');
            $text = trim((string) ($answer['text'] ?? ''));
            if (!isset(self::PROMPTS[$id])) {
                throw new InvalidArgumentException('Unknown prompt.');
            }
            if ($text === '' || mb_strlen($text) > 200) {
                throw new InvalidArgumentException('Prompt answers are 1–200 characters.');
            }
            $stored[] = ['id' => $id, 'question' => self::PROMPTS[$id], 'answer' => $text];
        }
        $user['prompts'] = $stored;
        $this->store->put('users', $userId, $user);
        return $stored;
    }

    /** @return array<int, array{id: string, question: string, answer: string}> */
    public function prompts(string $userId): array
    {
        $user = $this->requireUser($userId);
        return array_values((array) ($user['prompts'] ?? []));
    }

    /**
     * Profile coach: a deterministic strength score (0–100) with the
     * specific next steps that would raise it. The co-pilot that helps
     * members succeed instead of judging them.
     */
    public function profileCoach(string $userId): array
    {
        $user = $this->requireUser($userId);
        $profile = (array) $user['profile'];
        $score = 0;
        $suggestions = [];
        $facts = ['age', 'gender', 'zip_code', 'dating_type', 'faith', 'politics', 'income_range', 'automobile', 'occupation_category'];
        $filled = count(array_filter($facts, static fn (string $f): bool => ($profile[$f] ?? '') !== '' && ($profile[$f] ?? 0) !== 0));
        $lists = count(array_filter(['interests', 'hobbies', 'outdoor_activities'], static fn (string $f): bool => (array) ($profile[$f] ?? []) !== []));
        $score += (int) round(($filled / 9) * 25) + $lists * 5;
        if ($filled < 9) {
            $suggestions[] = 'Fill in the rest of your profile facts — every one is searchable.';
        }
        if ($lists < 3) {
            $suggestions[] = 'Add interests, hobbies, and outdoor activities so matching has more to work with.';
        }
        $roster = $this->pictureRoster($userId);
        $score += ($roster['public'] ? 10 : 0) + ($roster['private'] ? 10 : 0);
        if (!$roster['public']) {
            $suggestions[] = 'Upload your real picture — profiles with one start far more chats.';
        }
        if (!$roster['private']) {
            $suggestions[] = 'Add a private picture to reveal in chats you trust.';
        }
        $promptCount = count($this->prompts($userId));
        $score += $promptCount * 5;
        if ($promptCount < 3) {
            $suggestions[] = 'Answer ' . (3 - $promptCount) . ' more prompt' . ($promptCount === 2 ? '' : 's') . ' — they are the best conversation starters.';
        }
        if ((array) ($user['videos'] ?? []) !== []) {
            $score += 10;
        } else {
            $suggestions[] = 'Embed a short profile video (10 seconds or less).';
        }
        if ((array) ($user['preferences'] ?? []) !== []) {
            $score += 10;
        } else {
            $suggestions[] = 'Save your Browse preferences so daily drops know who to pick.';
        }
        if ($this->verificationStatus($userId) === 'verified') {
            $score += 10;
        } else {
            $suggestions[] = 'Request verification — verified profiles carry a trust badge everywhere.';
        }
        return ['score' => min(100, $score), 'suggestions' => $suggestions];
    }

    /**
     * Ice breakers: deterministic first-message suggestions built from the
     * other member's prompt answers and your shared interests.
     *
     * @return array<int, string>
     */
    public function iceBreakers(string $chatId, string $viewerId): array
    {
        $chat = $this->requireChat($chatId);
        if (!in_array($viewerId, (array) $chat['participants'], true)) {
            throw new InvalidArgumentException('Only participants get ice breakers.');
        }
        $otherId = $this->otherParticipant($chat, $viewerId);
        $other = $this->requireUser($otherId);
        $me = $this->requireUser($viewerId);
        $name = (string) ($other['profile']['display_name'] ?? 'they');
        $ideas = [];
        foreach (array_slice($this->prompts($otherId), 0, 2) as $prompt) {
            $ideas[] = sprintf('%s answered "%s" with "%s" — ask for the story behind it.', $name, $prompt['question'], $prompt['answer']);
        }
        $shared = array_values(array_intersect(
            (array) ($me['profile']['interests'] ?? []),
            (array) ($other['profile']['interests'] ?? []),
        ));
        if ($shared !== []) {
            $ideas[] = sprintf('You both love %s — ask about the best %s moment they\'ve had lately.', $shared[0], $shared[0]);
        }
        if ($ideas === []) {
            $ideas[] = 'Ask what a perfect slow first date would look like for them — you have 30 days to plan it.';
        }
        return array_slice($ideas, 0, 3);
    }

    /**
     * Conversation health: a deterministic read on how balanced and safe
     * a chat is — reply balance, two-sided days, and red flags.
     */
    public function conversationHealth(string $chatId): array
    {
        $chat = $this->requireChat($chatId);
        $messages = (array) $chat['messages'];
        if ($messages === []) {
            return ['score' => 50, 'label' => 'just starting', 'notes' => ['No messages yet — send the first one.']];
        }
        $bySender = [];
        $days = [];
        $flags = 0;
        foreach ($messages as $message) {
            $bySender[(string) $message['sender_id']] = ($bySender[(string) $message['sender_id']] ?? 0) + 1;
            $days[gmdate('Y-m-d', (int) $message['sent_at'])][(string) $message['sender_id']] = true;
            $flags += count((array) ($message['red_flags'] ?? []));
        }
        $counts = array_values($bySender) + [0, 0];
        $balance = max($counts) > 0 ? min($counts) / max($counts) : 0.0;
        $twoSided = count(array_filter($days, static fn (array $senders): bool => count($senders) >= 2));
        $daysRatio = count($days) > 0 ? $twoSided / count($days) : 0.0;
        $score = max(5, min(100, (int) round(50 * $balance + 50 * $daysRatio) - $flags * 15));
        $notes = [];
        if ($balance < 0.5) {
            $notes[] = 'One side is carrying the conversation — ask a question and leave room.';
        }
        if ($flags > 0) {
            $notes[] = 'Safety flags were raised in this chat — review them in your safety timeline.';
        }
        if ($notes === []) {
            $notes[] = 'Balanced and steady — exactly how slow chats grow.';
        }
        return [
            'score' => $score,
            'label' => $score >= 75 ? 'thriving' : ($score >= 45 ? 'steady' : 'needs care'),
            'notes' => $notes,
        ];
    }

    /**
     * The daily drop: a small curated set from the member's Browse pool,
     * rotated deterministically by date — fewer, better matches instead
     * of endless swiping. Same member, same day, same drop.
     *
     * @return array<int, array<string, mixed>>
     */
    public function dailyDrop(string $userId, ?int $now = null): array
    {
        $now ??= time();
        $pool = $this->browseFor($userId, 9, $now);
        if ($pool === []) {
            return [];
        }
        $date = gmdate('Y-m-d', $now);
        usort($pool, static fn (array $a, array $b): int =>
            strcmp(md5($date . $userId . $a['user_id']), md5($date . $userId . $b['user_id'])));
        $drop = array_slice($pool, 0, self::DAILY_DROP_SIZE);
        foreach ($drop as &$row) {
            $row['drop_date'] = $date;
        }
        return $drop;
    }

    /**
     * Swipe mode: the next candidate from the member's Browse pool that
     * they have not swiped on yet (one at a time, preference-filtered).
     *
     * @return array<string, mixed>|null
     */
    public function nextSwipe(string $userId, ?int $now = null): ?array
    {
        $now ??= time();
        foreach ($this->browseFor($userId, 50, $now) as $candidate) {
            if ($this->store->get('swipes', $this->swipeId($userId, (string) $candidate['user_id'])) === null) {
                return $candidate;
            }
        }
        return null;
    }

    /**
     * Record a like or pass. A like credits the other member's popularity
     * and reports back whether it completed a mutual like.
     *
     * @return array{target_id: string, action: string, mutual: bool}
     */
    public function recordSwipe(string $userId, string $targetId, string $action, ?int $now = null): array
    {
        $now ??= time();
        $this->requireUser($userId);
        $this->requireUser($targetId);
        if ($userId === $targetId || !in_array($action, ['like', 'pass'], true)) {
            throw new InvalidArgumentException('A swipe is a like or a pass on another member.');
        }
        $this->store->put('swipes', $this->swipeId($userId, $targetId), [
            'from' => $userId,
            'to' => $targetId,
            'action' => $action,
            'at' => $now,
        ]);
        $mutual = false;
        if ($action === 'like') {
            $this->recordPopularityEvent($targetId, 'like', $now);
            $reverse = $this->store->get('swipes', $this->swipeId($targetId, $userId));
            $mutual = $reverse !== null && $reverse['action'] === 'like';
        }
        return ['target_id' => $targetId, 'action' => $action, 'mutual' => $mutual];
    }

    /**
     * Top-N matches: the member's best-scoring matches across the whole
     * community (no preference filters — the widest ranked view).
     *
     * @return array<int, array<string, mixed>>
     */
    public function topMatches(string $userId, int $count = 10, ?int $now = null): array
    {
        return $this->matchesFor($userId, ['limit' => max(1, min(50, $count))], $now);
    }

    private function swipeId(string $from, string $to): string
    {
        return 'sw_' . substr(hash('sha256', $from . '>' . $to), 0, 16);
    }

    /** Join a niche community hub. */
    public function joinCommunity(string $userId, string $slug): array
    {
        if (!isset(self::COMMUNITIES[$slug])) {
            throw new InvalidArgumentException('Unknown community.');
        }
        $user = $this->requireUser($userId);
        $communities = array_values(array_unique(array_merge((array) ($user['communities'] ?? []), [$slug])));
        $user['communities'] = $communities;
        $this->store->put('users', $userId, $user);
        return $communities;
    }

    public function leaveCommunity(string $userId, string $slug): array
    {
        $user = $this->requireUser($userId);
        $user['communities'] = array_values(array_filter(
            (array) ($user['communities'] ?? []),
            static fn (string $joined): bool => $joined !== $slug,
        ));
        $this->store->put('users', $userId, $user);
        return $user['communities'];
    }

    /** @return array<int, string> */
    public function memberCommunities(string $userId): array
    {
        $user = $this->requireUser($userId);
        return array_values((array) ($user['communities'] ?? []));
    }

    /**
     * A community's member grid, most popular first.
     *
     * @return array<int, array<string, mixed>>
     */
    public function communityMembers(string $slug, ?int $now = null): array
    {
        $now ??= time();
        if (!isset(self::COMMUNITIES[$slug])) {
            throw new InvalidArgumentException('Unknown community.');
        }
        $rows = [];
        foreach ($this->store->all('users') as $user) {
            if (!in_array($slug, (array) ($user['communities'] ?? []), true)) {
                continue;
            }
            $userId = (string) $user['id'];
            $popularity = $this->popularity($userId, $now);
            $rows[] = [
                'user_id' => $userId,
                'display_name' => (string) ($user['profile']['display_name'] ?? ''),
                'age' => (int) ($user['profile']['age'] ?? 0),
                'dating_type' => (string) ($user['profile']['dating_type'] ?? ''),
                'interests' => (array) ($user['profile']['interests'] ?? []),
                'popularity_score' => $popularity['popularity_score'],
                'verified' => ($user['verification']['status'] ?? '') === 'verified',
            ];
        }
        usort($rows, static fn (array $a, array $b): int =>
            [$b['popularity_score'], $a['user_id']] <=> [$a['popularity_score'], $b['user_id']]);
        return $rows;
    }

    // ------------------------------------------------------------------
    // Browse preferences
    // ------------------------------------------------------------------

    /** @return array<string, mixed> The member's saved browse preferences. */
    public function preferences(string $userId): array
    {
        $user = $this->requireUser($userId);
        return (array) ($user['preferences'] ?? []) + self::defaultPreferences();
    }

    /**
     * Save who the member is looking for. These preferences drive Browse.
     *
     * @param array<string, mixed> $fields
     * @return array<string, mixed>
     */
    public function updatePreferences(string $userId, array $fields): array
    {
        $user = $this->requireUser($userId);
        $preferences = (array) ($user['preferences'] ?? []) + self::defaultPreferences();
        if (array_key_exists('seeking_gender', $fields)) {
            $preferences['seeking_gender'] = trim((string) $fields['seeking_gender']);
        }
        if (array_key_exists('age_min', $fields)) {
            $preferences['age_min'] = max(18, (int) $fields['age_min']);
        }
        if (array_key_exists('age_max', $fields)) {
            $preferences['age_max'] = max(18, (int) $fields['age_max']);
        }
        if ($preferences['age_max'] < $preferences['age_min']) {
            throw new InvalidArgumentException('The age range is upside down.');
        }
        if (array_key_exists('max_distance_km', $fields)) {
            $preferences['max_distance_km'] = max(1.0, (float) $fields['max_distance_km']);
        }
        if (array_key_exists('dating_type', $fields)) {
            $type = trim((string) $fields['dating_type']);
            if ($type !== '' && !in_array($type, self::DATING_TYPES, true)) {
                throw new InvalidArgumentException('Unknown dating type preference.');
            }
            $preferences['dating_type'] = $type;
        }
        if (array_key_exists('interests', $fields)) {
            $value = $fields['interests'];
            $items = is_array($value) ? $value : preg_split('/\s*,\s*/', (string) $value, -1, PREG_SPLIT_NO_EMPTY);
            $preferences['interests'] = array_values(array_unique(array_map(
                static fn ($item): string => strtolower(trim((string) $item)),
                (array) $items,
            )));
        }
        if (array_key_exists('must_share', $fields)) {
            $value = $fields['must_share'];
            $items = is_array($value) ? $value : preg_split('/\s*,\s*/', (string) $value, -1, PREG_SPLIT_NO_EMPTY);
            $mustShare = [];
            foreach ((array) $items as $criterion) {
                $criterion = strtolower(trim((string) $criterion));
                if ($criterion === '') {
                    continue;
                }
                if (!isset(self::SHAREABLE_FACTS[$criterion]) && !isset(self::INTEREST_CATEGORIES[$criterion])) {
                    throw new InvalidArgumentException('Unknown must-share criterion: ' . $criterion);
                }
                $mustShare[] = $criterion;
            }
            $preferences['must_share'] = array_values(array_unique($mustShare));
        }
        if (array_key_exists('shared_categories', $fields)) {
            $value = $fields['shared_categories'];
            $items = is_array($value) ? $value : preg_split('/\s*,\s*/', (string) $value, -1, PREG_SPLIT_NO_EMPTY);
            $categories = [];
            foreach ((array) $items as $category) {
                $category = strtolower(trim((string) $category));
                if ($category === '') {
                    continue;
                }
                if (!isset(self::INTEREST_CATEGORIES[$category])) {
                    throw new InvalidArgumentException('Unknown shared-interest category: ' . $category);
                }
                $categories[] = $category;
            }
            $preferences['shared_categories'] = array_values(array_unique($categories));
        }
        // "Must match" criteria — each empty string means "any".
        $enumChecks = [
            'income_range' => self::INCOME_RANGES,
            'automobile' => self::AUTOMOBILES,
            'education' => self::EDUCATION_LEVELS,
            'family_plans' => self::FAMILY_PLANS,
            'smoking' => self::SMOKING,
            'drinking' => self::DRINKING,
            'pets' => self::PETS,
        ];
        foreach (['faith', 'politics', 'income_range', 'automobile', 'education', 'occupation_category',
                  'family_plans', 'smoking', 'drinking', 'pets'] as $criterion) {
            if (!array_key_exists($criterion, $fields)) {
                continue;
            }
            $value = strtolower(trim((string) $fields[$criterion]));
            if ($value !== '' && isset($enumChecks[$criterion]) && !in_array($value, $enumChecks[$criterion], true)) {
                throw new InvalidArgumentException('Unknown ' . str_replace('_', ' ', $criterion) . ' preference.');
            }
            $preferences[$criterion] = $value;
        }
        $user['preferences'] = $preferences;
        $this->store->put('users', $userId, $user);
        return $preferences;
    }

    /**
     * Browse: the member's best matches with their saved preferences
     * applied as hard filters, ranked by compatibility score.
     *
     * @return array<int, array<string, mixed>>
     */
    public function browseFor(string $userId, int $limit = 12, ?int $now = null): array
    {
        $now ??= time();
        $preferences = $this->preferences($userId);
        $me = $this->requireUser($userId);
        $filters = [
            'age_min' => $preferences['age_min'],
            'age_max' => $preferences['age_max'],
            'zip_code' => (string) ($me['profile']['zip_code'] ?? ''),
            'zip_radius_km' => $preferences['max_distance_km'],
            'limit' => $limit,
        ];
        if ($preferences['seeking_gender'] !== '') {
            $filters['gender'] = $preferences['seeking_gender'];
        }
        if ($preferences['dating_type'] !== '') {
            $filters['dating_type'] = $preferences['dating_type'];
        }
        if ($preferences['interests'] !== []) {
            $filters['interests'] = $preferences['interests'];
        }
        foreach (['faith', 'politics', 'income_range', 'automobile', 'education', 'occupation_category',
                  'family_plans', 'smoking', 'drinking', 'pets'] as $criterion) {
            if (($preferences[$criterion] ?? '') !== '') {
                $filters[$criterion] = $preferences[$criterion];
            }
        }
        if ((array) ($preferences['shared_categories'] ?? []) !== []) {
            $filters['shared_categories'] = $preferences['shared_categories'];
        }
        // "Must share with me": each checked criterion pins the candidate to
        // the member's OWN value (facts) or to a classification the member
        // has themselves. Criteria the member hasn't filled in are skipped.
        $myProfile = (array) $me['profile'];
        $myCategories = $this->interestCategories($myProfile);
        foreach ((array) ($preferences['must_share'] ?? []) as $criterion) {
            if (isset(self::SHAREABLE_FACTS[$criterion])) {
                $mine = (string) ($myProfile[$criterion] ?? '');
                if ($mine !== '') {
                    $filters[$criterion] = $mine;
                }
            } elseif (isset(self::INTEREST_CATEGORIES[$criterion]) && in_array($criterion, $myCategories, true)) {
                $filters['shared_categories'] = array_values(array_unique(array_merge(
                    (array) ($filters['shared_categories'] ?? []),
                    [$criterion],
                )));
            }
        }
        if ($filters['zip_code'] === '') {
            unset($filters['zip_code'], $filters['zip_radius_km']);
        }
        return $this->matchesFor($userId, $filters, $now);
    }

    /** @return array<string, mixed> */
    private static function defaultPreferences(): array
    {
        return [
            'seeking_gender' => '',
            'age_min' => 18,
            'age_max' => 99,
            'max_distance_km' => 100.0,
            'dating_type' => '',
            'interests' => [],
            'shared_categories' => [],
            'must_share' => [],
            'faith' => '',
            'politics' => '',
            'income_range' => '',
            'automobile' => '',
            'education' => '',
            'occupation_category' => '',
            'family_plans' => '',
            'smoking' => '',
            'drinking' => '',
            'pets' => '',
        ];
    }

    // ------------------------------------------------------------------
    // Search & matching
    // ------------------------------------------------------------------

    /**
     * Member search across every profile dimension.
     *
     * @param array<string, mixed> $filters
     * @return array<int, array<string, mixed>>
     */
    public function searchUsers(array $filters, ?int $now = null): array
    {
        $now ??= time();
        $rows = [];
        foreach ($this->store->all('users') as $user) {
            $profile = (array) $user['profile'];
            if (!$this->profileMatchesFilters($profile, $filters)) {
                continue;
            }
            $popularity = $this->popularity((string) $user['id'], $now);
            if (isset($filters['min_popularity']) && $popularity['popularity_score'] < (int) $filters['min_popularity']) {
                continue;
            }
            if (isset($filters['max_popularity']) && $popularity['popularity_score'] > (int) $filters['max_popularity']) {
                continue;
            }
            $row = [
                'user_id' => (string) $user['id'],
                'display_name' => (string) ($profile['display_name'] ?? ''),
                'popularity_score' => $popularity['popularity_score'],
                'percentile' => $popularity['percentile'],
                'verified' => ($user['verification']['status'] ?? '') === 'verified',
            ] + array_intersect_key($profile, array_flip([
                'age', 'gender', 'zip_code', 'interests', 'hobbies', 'outdoor_activities',
                'dating_type', 'faith', 'politics', 'income_range', 'automobile', 'occupation_category',
            ]));
            if (isset($filters['zip_code'])) {
                $row['zip_distance_km'] = $this->zipProximityKm((string) $filters['zip_code'], (string) $profile['zip_code']);
            }
            $rows[] = $row;
        }
        usort($rows, static fn (array $a, array $b): int => [$b['popularity_score'], $a['user_id']] <=> [$a['popularity_score'], $b['user_id']]);
        $limit = isset($filters['limit']) ? max(1, (int) $filters['limit']) : 50;
        return array_slice($rows, 0, $limit);
    }

    /**
     * Ranked matches for a member, honoring the same filter set as search.
     *
     * @param array<string, mixed> $filters
     * @return array<int, array<string, mixed>>
     */
    public function matchesFor(string $userId, array $filters = [], ?int $now = null): array
    {
        $now ??= time();
        $me = $this->requireUser($userId);
        $myProfile = (array) $me['profile'];
        $myPopularity = $this->popularity($userId, $now)['popularity_score'];
        $rows = [];
        foreach ($this->store->all('users') as $candidate) {
            $candidateId = (string) $candidate['id'];
            if ($candidateId === $userId) {
                continue;
            }
            $profile = (array) $candidate['profile'];
            if (!$this->profileMatchesFilters($profile, $filters)) {
                continue;
            }
            $candidatePopularity = $this->popularity($candidateId, $now)['popularity_score'];
            $factors = $this->compatibilityFactors($myProfile, $profile, $myPopularity, $candidatePopularity);
            $score = 0.0;
            foreach (self::MATCH_WEIGHTS as $factor => $weight) {
                $score += $factors[$factor] * $weight;
            }
            $rows[] = [
                'match_id' => 'm_' . substr(hash('sha256', $userId . '|' . $candidateId), 0, 10),
                'user_id' => $candidateId,
                'display_name' => (string) ($profile['display_name'] ?? ''),
                'verified' => ($candidate['verification']['status'] ?? '') === 'verified',
                'dating_type' => (string) ($profile['dating_type'] ?? ''),
                'match_score' => (int) round($score * 100),
                'popularity_score' => $candidatePopularity,
                'zip_distance_km' => $this->zipProximityKm((string) $myProfile['zip_code'], (string) $profile['zip_code']),
                'shared_interests' => array_values(array_intersect((array) $myProfile['interests'], (array) $profile['interests'])),
                'shared_hobbies' => array_values(array_intersect((array) $myProfile['hobbies'], (array) $profile['hobbies'])),
                'compatibility_factors' => $factors,
                'recommended_venues' => array_map(
                    static fn (array $venue): string => (string) $venue['id'],
                    array_slice($this->venuesNear((string) $profile['zip_code']), 0, 2),
                ),
            ];
        }
        usort($rows, static fn (array $a, array $b): int => [$b['match_score'], $a['user_id']] <=> [$a['match_score'], $b['user_id']]);
        $limit = isset($filters['limit']) ? max(1, (int) $filters['limit']) : 25;
        return array_slice($rows, 0, $limit);
    }

    /**
     * Deterministic zip-proximity proxy. With no geo dataset in a
     * dependency-free app, shared leading digits stand in for distance;
     * swap this method for a real geo lookup without touching callers.
     */
    public function zipProximityKm(string $zipA, string $zipB): float
    {
        $zipA = preg_replace('/\D/', '', $zipA) ?? '';
        $zipB = preg_replace('/\D/', '', $zipB) ?? '';
        if ($zipA === '' || $zipB === '') {
            return 999.0;
        }
        if ($zipA === $zipB) {
            return 0.0;
        }
        $shared = 0;
        $max = min(strlen($zipA), strlen($zipB), 5);
        while ($shared < $max && $zipA[$shared] === $zipB[$shared]) {
            $shared++;
        }
        return [400.0, 120.0, 40.0, 15.0, 5.0, 2.0][$shared];
    }

    /**
     * @param array<string, mixed> $a
     * @param array<string, mixed> $b
     * @return array<string, float> Every factor scored 0.0–1.0.
     */
    public function compatibilityFactors(array $a, array $b, int $popularityA, int $popularityB): array
    {
        $distanceKm = $this->zipProximityKm((string) $a['zip_code'], (string) $b['zip_code']);
        return [
            'distance' => max(0.0, 1.0 - $distanceKm / 200.0),
            'interests' => $this->overlap((array) $a['interests'], (array) $b['interests']),
            'hobbies' => $this->overlap((array) $a['hobbies'], (array) $b['hobbies']),
            'outdoor_activities' => $this->overlap((array) $a['outdoor_activities'], (array) $b['outdoor_activities']),
            'dating_type' => $this->categoryAffinity((string) $a['dating_type'], (string) $b['dating_type']),
            'faith' => $this->categoryAffinity((string) $a['faith'], (string) $b['faith']),
            'politics' => $this->categoryAffinity((string) $a['politics'], (string) $b['politics']),
            'income' => $this->incomeAffinity((string) $a['income_range'], (string) $b['income_range']),
            'automobile' => (string) $a['automobile'] !== '' && $a['automobile'] === $b['automobile'] ? 1.0 : 0.7,
            'occupation' => $this->categoryAffinity((string) $a['occupation_category'], (string) $b['occupation_category']),
            'popularity_balance' => 1.0 - abs($popularityA - $popularityB) / 100.0,
        ];
    }

    /** Jaccard overlap of two tag lists; empty lists score a neutral 0.5. */
    private function overlap(array $a, array $b): float
    {
        if ($a === [] || $b === []) {
            return 0.5;
        }
        $intersection = count(array_intersect($a, $b));
        $union = count(array_unique(array_merge($a, $b)));
        return $union === 0 ? 0.5 : $intersection / $union;
    }

    /** Exact category match scores 1.0; unspecified sides stay neutral. */
    private function categoryAffinity(string $a, string $b): float
    {
        if ($a === '' || $b === '') {
            return 0.6;
        }
        return $a === $b ? 1.0 : 0.2;
    }

    /** Adjacent income brackets stay compatible; distance decays the score. */
    private function incomeAffinity(string $a, string $b): float
    {
        $indexA = array_search($a, self::INCOME_RANGES, true);
        $indexB = array_search($b, self::INCOME_RANGES, true);
        if ($indexA === false || $indexB === false) {
            return 0.6;
        }
        return max(0.2, 1.0 - abs($indexA - $indexB) * 0.2);
    }

    // ------------------------------------------------------------------
    // Partners, venues, offers, events, contests, products
    // ------------------------------------------------------------------

    /** @return array{partner_id: string, token: string, auto_password: ?string} */
    public function signupPartner(string $businessName, string $email, ?string $password = null, string $planTier = 'basic', ?int $now = null): array
    {
        $now ??= time();
        $businessName = trim($businessName);
        $email = strtolower(trim($email));
        if ($businessName === '' || filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
            throw new InvalidArgumentException('A business name and valid email are required.');
        }
        if (!in_array($planTier, self::PARTNER_TIERS, true)) {
            throw new InvalidArgumentException('Unknown partner plan tier.');
        }
        if ($this->store->where('partners', ['contact_email' => $email]) !== []) {
            throw new InvalidArgumentException('A partner account already exists for this email address.');
        }
        $generated = null;
        if ($password === null || $password === '') {
            $password = $this->generateStrongPassword();
            $generated = $password;
        } elseif ($this->passwordProblems($password) !== []) {
            throw new InvalidArgumentException('Weak password: ' . implode(' ', $this->passwordProblems($password)));
        }
        $partnerId = 'p_' . substr(hash('sha256', $email . $now), 0, 12);
        $this->store->put('partners', $partnerId, [
            'business_name' => $businessName,
            'contact_email' => $email,
            'password_hash' => password_hash($password, PASSWORD_DEFAULT),
            'plan_tier' => $planTier,
            'created_at' => $now,
        ]);
        return ['partner_id' => $partnerId, 'token' => $this->issueToken($partnerId, 'partner', $now), 'auto_password' => $generated];
    }

    /** @return array{token: string, partner_id: string} */
    public function partnerLogin(string $email, string $password, ?int $now = null): array
    {
        $now ??= time();
        $rows = $this->store->where('partners', ['contact_email' => strtolower(trim($email))]);
        $partner = $rows[0] ?? null;
        if ($partner === null || !password_verify($password, (string) ($partner['password_hash'] ?? ''))) {
            throw new InvalidArgumentException('Invalid email or password.');
        }
        return ['token' => $this->issueToken((string) $partner['id'], 'partner', $now), 'partner_id' => (string) $partner['id']];
    }

    /** @return array{token: string, admin_id: string} */
    public function adminLogin(string $email, string $password, ?int $now = null): array
    {
        $now ??= time();
        $rows = $this->store->where('admins', ['email' => strtolower(trim($email))]);
        $admin = $rows[0] ?? null;
        if ($admin === null || !password_verify($password, (string) ($admin['password_hash'] ?? ''))) {
            throw new InvalidArgumentException('Invalid email or password.');
        }
        return ['token' => $this->issueToken((string) $admin['id'], 'admin', $now), 'admin_id' => (string) $admin['id']];
    }

    /** @return array<string, mixed> */
    public function partner(string $partnerId): array
    {
        $partner = $this->store->get('partners', $partnerId);
        if ($partner === null) {
            throw new InvalidArgumentException('Unknown partner: ' . $partnerId);
        }
        return $partner;
    }

    public function changePartnerPlan(string $partnerId, string $newTier): array
    {
        if (!in_array($newTier, self::PARTNER_TIERS, true)) {
            throw new InvalidArgumentException('Unknown partner plan tier.');
        }
        $partner = $this->partner($partnerId);
        $partner['plan_tier'] = $newTier;
        $this->store->put('partners', $partnerId, $partner);
        return $partner;
    }

    /**
     * @param array<string, mixed> $fields
     * @return array<string, mixed>
     */
    public function createVenue(string $partnerId, array $fields, ?int $now = null): array
    {
        $now ??= time();
        $this->partner($partnerId);
        $name = trim((string) ($fields['name'] ?? ''));
        $category = (string) ($fields['category'] ?? '');
        if ($name === '' || !in_array($category, self::VENUE_CATEGORIES, true)) {
            throw new InvalidArgumentException('A venue needs a name and a known category.');
        }
        $venueId = 'v_' . substr(hash('sha256', $partnerId . $name . $now), 0, 12);
        $venue = [
            'partner_id' => $partnerId,
            'name' => $name,
            'address' => trim((string) ($fields['address'] ?? '')),
            'zip_code' => trim((string) ($fields['zip_code'] ?? '')),
            'category' => $category,
            'atmosphere_tags' => array_values(array_map('strval', (array) ($fields['atmosphere_tags'] ?? []))),
            'safety_score' => 70,
            'status' => 'active',
            'created_at' => $now,
        ];
        $this->store->put('venues', $venueId, $venue);
        return $venue + ['id' => $venueId];
    }

    /**
     * @param array<string, mixed> $fields
     * @return array<string, mixed>
     */
    public function updateVenue(string $partnerId, string $venueId, array $fields): array
    {
        $venue = $this->requireVenue($venueId, $partnerId);
        foreach (['name', 'address', 'zip_code', 'status'] as $field) {
            if (array_key_exists($field, $fields)) {
                $venue[$field] = trim((string) $fields[$field]);
            }
        }
        if (array_key_exists('atmosphere_tags', $fields)) {
            $venue['atmosphere_tags'] = array_values(array_map('strval', (array) $fields['atmosphere_tags']));
        }
        if (array_key_exists('category', $fields)) {
            if (!in_array($fields['category'], self::VENUE_CATEGORIES, true)) {
                throw new InvalidArgumentException('Unknown venue category.');
            }
            $venue['category'] = (string) $fields['category'];
        }
        $this->store->put('venues', $venueId, $venue);
        return $venue;
    }

    /** @return array<int, array<string, mixed>> */
    public function venuesForPartner(string $partnerId): array
    {
        return $this->store->where('venues', ['partner_id' => $partnerId]);
    }

    /** @return array<int, array<string, mixed>> Active venues sorted by proximity. */
    public function venuesNear(string $zipCode): array
    {
        $venues = array_values(array_filter(
            $this->store->all('venues'),
            static fn (array $venue): bool => $venue['status'] === 'active',
        ));
        usort($venues, fn (array $a, array $b): int =>
            [$this->zipProximityKm($zipCode, (string) $a['zip_code']), (string) $a['id']]
            <=> [$this->zipProximityKm($zipCode, (string) $b['zip_code']), (string) $b['id']]);
        return $venues;
    }

    /**
     * Random coupon: delivered to up to max_recipients members near the venue.
     *
     * @param array<string, mixed> $fields
     * @return array<string, mixed>
     */
    public function createRandomCoupon(string $partnerId, string $venueId, array $fields, ?int $now = null): array
    {
        return $this->createCoupon($partnerId, $venueId, 'random', $fields, [], $now);
    }

    /**
     * Targeted coupon (Pro/Elite plans): segment members by profile facts.
     *
     * @param array<string, mixed> $fields
     * @param array<string, mixed> $targeting
     * @return array<string, mixed>
     */
    public function createTargetedCoupon(string $partnerId, string $venueId, array $fields, array $targeting, ?int $now = null): array
    {
        $partner = $this->partner($partnerId);
        if (!in_array((string) $partner['plan_tier'], ['pro', 'elite'], true)) {
            throw new InvalidArgumentException('Targeted coupons require the Pro or Elite partner plan.');
        }
        return $this->createCoupon($partnerId, $venueId, 'targeted', $fields, $targeting, $now);
    }

    /** @return array<int, array<string, mixed>> */
    public function couponsForVenue(string $venueId): array
    {
        return $this->store->where('coupons', ['venue_id' => $venueId]);
    }

    /** Coupons delivered to a member and not yet redeemed by them. */
    public function couponsForMember(string $userId): array
    {
        $rows = [];
        foreach ($this->store->all('coupons') as $coupon) {
            if (!in_array($userId, (array) $coupon['recipients'], true)) {
                continue;
            }
            $redeemed = false;
            foreach ($this->store->where('redemptions', ['coupon_id' => $coupon['id']]) as $redemption) {
                if ($redemption['user_id'] === $userId) {
                    $redeemed = true;
                    break;
                }
            }
            if (!$redeemed) {
                $rows[] = $coupon;
            }
        }
        return $rows;
    }

    public function redeemCoupon(string $couponId, string $userId, ?int $now = null): array
    {
        $now ??= time();
        $coupon = $this->store->get('coupons', $couponId);
        if ($coupon === null || !in_array($userId, (array) $coupon['recipients'], true)) {
            throw new InvalidArgumentException('This coupon was not issued to this member.');
        }
        if ($now > (int) $coupon['valid_to'] || $now < (int) $coupon['valid_from']) {
            throw new InvalidArgumentException('This coupon is not valid right now.');
        }
        $redemptionId = 'red_' . substr(hash('sha256', $couponId . $userId), 0, 12);
        if ($this->store->get('redemptions', $redemptionId) !== null) {
            throw new InvalidArgumentException('This coupon was already redeemed.');
        }
        $this->store->put('redemptions', $redemptionId, [
            'coupon_id' => $couponId,
            'user_id' => $userId,
            'redeemed_at' => $now,
        ]);
        $this->logAnalytics('coupon_redemption', $userId, (string) $coupon['venue_id'], ['coupon_id' => $couponId], $now);
        return $this->store->get('redemptions', $redemptionId) ?? [];
    }

    /**
     * @param array<string, mixed> $fields
     * @return array<string, mixed>
     */
    public function createEvent(string $partnerId, string $venueId, array $fields, ?int $now = null): array
    {
        $now ??= time();
        $this->requireVenue($venueId, $partnerId);
        $title = trim((string) ($fields['title'] ?? ''));
        if ($title === '') {
            throw new InvalidArgumentException('An event needs a title.');
        }
        $eventId = 'evt_' . substr(hash('sha256', $venueId . $title . $now), 0, 12);
        $event = [
            'venue_id' => $venueId,
            'title' => $title,
            'description' => trim((string) ($fields['description'] ?? '')),
            'date_time' => (int) ($fields['date_time'] ?? $now + 7 * 86400),
            'capacity' => max(1, (int) ($fields['capacity'] ?? 50)),
            'tags' => array_values(array_map('strval', (array) ($fields['tags'] ?? []))),
            'ticket_price' => round((float) ($fields['ticket_price'] ?? 0.0), 2),
            'status' => 'scheduled',
            'created_at' => $now,
        ];
        $this->store->put('events', $eventId, $event);
        return $event + ['id' => $eventId];
    }

    /** @return array<int, array<string, mixed>> */
    public function eventsForVenue(string $venueId): array
    {
        return $this->store->where('events', ['venue_id' => $venueId]);
    }

    public function buyTicket(string $eventId, string $userId, int $quantity = 1, ?int $now = null): array
    {
        $now ??= time();
        $event = $this->store->get('events', $eventId);
        if ($event === null) {
            throw new InvalidArgumentException('Unknown event: ' . $eventId);
        }
        $this->requireUser($userId);
        $sold = 0;
        foreach ($this->store->where('tickets', ['event_id' => $eventId]) as $ticket) {
            $sold += (int) $ticket['quantity'];
        }
        $quantity = max(1, $quantity);
        if ($sold + $quantity > (int) $event['capacity']) {
            throw new InvalidArgumentException('This event is sold out.');
        }
        $ticketId = 'tix_' . substr(hash('sha256', $eventId . $userId . $now . $sold), 0, 12);
        $this->store->put('tickets', $ticketId, [
            'event_id' => $eventId,
            'user_id' => $userId,
            'quantity' => $quantity,
            'total_amount' => round($quantity * (float) $event['ticket_price'], 2),
            'purchased_at' => $now,
            'source' => 'internal',
        ]);
        $this->logAnalytics('ticket_purchase', $userId, (string) $event['venue_id'], ['event_id' => $eventId, 'quantity' => $quantity], $now);
        $this->enterEligibleContests($eventId, $userId, $now);
        return $this->store->get('tickets', $ticketId) ?? [];
    }

    /**
     * Contests (Pro/Elite plans) are open only to members who bought
     * tickets; entries are created automatically at purchase time.
     *
     * @param array<string, mixed> $fields
     * @return array<string, mixed>
     */
    public function createContest(string $partnerId, string $venueId, array $fields, ?int $now = null): array
    {
        $now ??= time();
        $partner = $this->partner($partnerId);
        if (!in_array((string) $partner['plan_tier'], ['pro', 'elite'], true)) {
            throw new InvalidArgumentException('Contests require the Pro or Elite partner plan.');
        }
        $this->requireVenue($venueId, $partnerId);
        $prize = trim((string) ($fields['prize'] ?? ''));
        if ($prize === '') {
            throw new InvalidArgumentException('A contest needs a prize.');
        }
        $contestId = 'c_' . substr(hash('sha256', $venueId . $prize . $now), 0, 12);
        $contest = [
            'venue_id' => $venueId,
            'prize' => $prize,
            'rules' => trim((string) ($fields['rules'] ?? '')),
            'eligibility_type' => 'ticket_buyers',
            'event_id' => (string) ($fields['event_id'] ?? ''),
            'start_date' => (int) ($fields['start_date'] ?? $now),
            'end_date' => (int) ($fields['end_date'] ?? $now + 30 * 86400),
            'draw_date' => (int) ($fields['draw_date'] ?? $now + 31 * 86400),
            'created_at' => $now,
        ];
        $this->store->put('contests', $contestId, $contest);
        return $contest + ['id' => $contestId];
    }

    /** @return array<int, array<string, mixed>> */
    public function contestsForVenue(string $venueId): array
    {
        return $this->store->where('contests', ['venue_id' => $venueId]);
    }

    /** Aggregated, privacy-preserving entry stats. */
    public function contestEntries(string $contestId): array
    {
        $entries = $this->store->where('contest_entries', ['contest_id' => $contestId]);
        return [
            'contest_id' => $contestId,
            'entries_count' => count($entries),
            'winner_selected' => false,
        ];
    }

    /**
     * @param array<string, mixed> $fields
     * @return array<string, mixed>
     */
    public function createProduct(string $partnerId, string $venueId, array $fields, ?int $now = null): array
    {
        $now ??= time();
        $this->requireVenue($venueId, $partnerId);
        $name = trim((string) ($fields['name'] ?? ''));
        $price = round((float) ($fields['price'] ?? 0.0), 2);
        if ($name === '' || $price <= 0) {
            throw new InvalidArgumentException('A product needs a name and a positive price.');
        }
        $productId = 'prod_' . substr(hash('sha256', $venueId . $name . $now), 0, 12);
        $product = [
            'venue_id' => $venueId,
            'name' => $name,
            'description' => trim((string) ($fields['description'] ?? '')),
            'category' => trim((string) ($fields['category'] ?? 'gift')),
            'price' => $price,
            'inventory' => max(0, (int) ($fields['inventory'] ?? 0)),
            'status' => 'active',
            'created_at' => $now,
        ];
        $this->store->put('products', $productId, $product);
        return $product + ['id' => $productId];
    }

    /** @return array<int, array<string, mixed>> Whole marketplace or one venue's shelf. */
    public function products(?string $venueId = null): array
    {
        $rows = $venueId === null
            ? array_values($this->store->all('products'))
            : $this->store->where('products', ['venue_id' => $venueId]);
        return array_values(array_filter($rows, static fn (array $product): bool => $product['status'] === 'active'));
    }

    public function placeOrder(string $userId, string $productId, int $quantity, ?int $now = null): array
    {
        $now ??= time();
        $this->requireUser($userId);
        $product = $this->store->get('products', $productId);
        if ($product === null || $product['status'] !== 'active') {
            throw new InvalidArgumentException('Unknown product: ' . $productId);
        }
        $quantity = max(1, $quantity);
        if ($quantity > (int) $product['inventory']) {
            throw new InvalidArgumentException('Not enough inventory for this order.');
        }
        $product['inventory'] = (int) $product['inventory'] - $quantity;
        $this->store->put('products', $productId, $product);
        $orderId = 'ord_' . substr(hash('sha256', $userId . $productId . $now), 0, 12);
        $this->store->put('orders', $orderId, [
            'user_id' => $userId,
            'product_id' => $productId,
            'quantity' => $quantity,
            'total_price' => round($quantity * (float) $product['price'], 2),
            'created_at' => $now,
        ]);
        $this->logAnalytics('order_placed', $userId, (string) $product['venue_id'], ['product_id' => $productId], $now);
        return $this->store->get('orders', $orderId) ?? [];
    }

    // ------------------------------------------------------------------
    // Date concierge (deterministic, no external AI required)
    // ------------------------------------------------------------------

    /** Chat-topic keywords mapped to venue affinities. */
    private const CONCIERGE_TOPICS = [
        'jazz' => ['tags' => ['jazz', 'quiet', 'live_music'], 'categories' => ['lounge', 'restaurant']],
        'italian' => ['tags' => ['romantic', 'quiet'], 'categories' => ['restaurant']],
        'dance' => ['tags' => ['dance_friendly'], 'categories' => ['lounge', 'experience']],
        'dancing' => ['tags' => ['dance_friendly'], 'categories' => ['lounge', 'experience']],
        'wine' => ['tags' => ['romantic', 'quiet'], 'categories' => ['restaurant', 'experience']],
        'puzzle' => ['tags' => ['game_night'], 'categories' => ['experience']],
        'escape room' => ['tags' => ['game_night'], 'categories' => ['experience']],
        'mystery' => ['tags' => ['game_night'], 'categories' => ['experience']],
        'cruise' => ['tags' => ['romantic'], 'categories' => ['cruise']],
        'travel' => ['tags' => ['romantic'], 'categories' => ['cruise', 'tour']],
        'hike' => ['tags' => ['outdoor'], 'categories' => ['tour', 'experience']],
        'hiking' => ['tags' => ['outdoor'], 'categories' => ['tour', 'experience']],
        'coffee' => ['tags' => ['quiet'], 'categories' => ['restaurant', 'lounge']],
        'dinner' => ['tags' => ['romantic', 'quiet'], 'categories' => ['restaurant']],
    ];

    /**
     * Read the chat (with both members on the platform — this is the
     * consent gate), extract shared topics, and suggest nearby vetted
     * venues whose atmosphere fits quiet, adult, date-compatible outings.
     *
     * @return array<int, array<string, mixed>>
     */
    public function conciergeSuggestions(string $chatId, ?int $now = null): array
    {
        $now ??= time();
        $chat = $this->requireChat($chatId);
        $text = strtolower(implode(' ', array_map(
            static fn (array $message): string => (string) $message['text'],
            (array) $chat['messages'],
        )));
        $topics = [];
        foreach (self::CONCIERGE_TOPICS as $keyword => $affinity) {
            if ($text !== '' && str_contains($text, $keyword)) {
                $topics[$keyword] = $affinity;
            }
        }
        if ($topics === []) {
            $topics['dinner'] = self::CONCIERGE_TOPICS['dinner'];
        }
        [$userA, $userB] = (array) $chat['participants'];
        $zip = (string) ($this->requireUser((string) $userA)['profile']['zip_code'] ?? '');
        $suggestions = [];
        foreach ($this->venuesNear($zip) as $venue) {
            $best = null;
            foreach ($topics as $keyword => $affinity) {
                $tagHit = array_intersect($affinity['tags'], (array) $venue['atmosphere_tags']) !== [];
                $categoryHit = in_array((string) $venue['category'], $affinity['categories'], true);
                $strength = ($tagHit ? 2 : 0) + ($categoryHit ? 1 : 0);
                if ($strength > 0 && ($best === null || $strength > $best['strength'])) {
                    $best = ['keyword' => (string) $keyword, 'strength' => $strength];
                }
            }
            if ($best !== null) {
                $suggestions[] = [
                    'venue_id' => (string) $venue['id'],
                    'venue_name' => (string) $venue['name'],
                    'category' => (string) $venue['category'],
                    'atmosphere_tags' => (array) $venue['atmosphere_tags'],
                    'zip_distance_km' => $this->zipProximityKm($zip, (string) $venue['zip_code']),
                    'strength' => $best['strength'],
                    'reason' => sprintf('You both talked about %s — %s fits that mood.', $best['keyword'], (string) $venue['name']),
                ];
            }
        }
        usort($suggestions, static fn (array $a, array $b): int =>
            [$b['strength'], $a['zip_distance_km'], $a['venue_id']]
            <=> [$a['strength'], $b['zip_distance_km'], $b['venue_id']]);
        return array_map(static function (array $suggestion): array {
            unset($suggestion['strength']);
            return $suggestion;
        }, array_slice($suggestions, 0, 3));
    }

    // ------------------------------------------------------------------
    // Safety
    // ------------------------------------------------------------------

    /** @return array<int, array<string, mixed>> Safety events raised to protect this member. */
    public function safetyEventsFor(string $userId): array
    {
        return $this->store->where('safety_events', ['protected_user_id' => $userId]);
    }

    /**
     * The Women's Safety Center content: education, red flags, and
     * checklists. Static and reviewable — no generated advice.
     *
     * @return array<string, array<int, string>>
     */
    public function safetyResources(): array
    {
        return [
            'red_flags' => [
                'Pushes to move the conversation off the platform right away.',
                'Asks for money, gift cards, or financial details — in any form, ever.',
                'Creates urgency: "decide now", "last chance", "don\'t tell anyone".',
                'Refuses video verification or gives inconsistent personal details.',
                'Excessive flattery and instant intensity before you have met.',
            ],
            'first_date_checklist' => [
                'Meet at a vetted public venue from the app — never a private address.',
                'Tell a friend where you are going and share your check-in plan.',
                'Arrange your own transport there and back.',
                'Keep your drink in sight at all times.',
                'Book a VIP chaperone through the app if you want a professional nearby.',
            ],
            'exit_strategies' => [
                'Use the in-app emergency button — it alerts our safety desk with your venue.',
                'Ask venue staff for help; partner venues train staff on discreet assists.',
                'Have a scheduled "check-in call" as a natural exit point.',
            ],
        ];
    }

    // ------------------------------------------------------------------
    // Meet-up intent advertising (second ad + purchasable keys)
    // ------------------------------------------------------------------

    /** Purchasable ad keys and the date-talk they match. */
    public const AD_KEYS = [
        'italian_restaurant' => ['italian', 'pasta', 'trattoria', 'pizza'],
        'movies' => ['movie', 'cinema', 'film', 'theater', 'theatre', 'double feature'],
        'coffee' => ['coffee', 'espresso', 'cafe'],
        'jazz_lounge' => ['jazz', 'live music', 'lounge'],
        'wine_bar' => ['wine', 'tasting'],
        'dancing' => ['dance', 'dancing', 'salsa'],
        'escape_room' => ['escape room', 'puzzle', 'mystery', 'detective'],
        'fine_dining' => ['dinner', 'restaurant', 'reservation'],
        'outdoors' => ['hike', 'picnic', 'beach', 'park'],
        'dessert' => ['dessert', 'ice cream', 'gelato'],
    ];

    /** Signals that a chat has started arranging an in-person meet-up. */
    private const MEETUP_PATTERNS = [
        'meet up', 'meet in person', 'let\'s meet', 'lets meet', 'meet at', 'meet for',
        'see you at', 'this weekend', 'saturday', 'sunday', 'friday night',
        'grab dinner', 'grab a coffee', 'date night', 'pick you up', 'before the movie',
        'are you free', 'when are you free',
    ];

    private const MEETUP_AD_RADIUS_KM = 40.0;
    private const MEETUP_AD_WINDOW = 12;   // most recent messages considered

    /**
     * The advertiser's second ad: shown only when a chat starts arranging
     * a real meet-up, matched by purchased keys. Pro/Elite plans only.
     *
     * @param array<string, mixed> $fields headline, message, offer, keys[]
     * @return array<string, mixed>
     */
    public function createMeetupAd(string $partnerId, string $venueId, array $fields, ?int $now = null): array
    {
        $now ??= time();
        $partner = $this->partner($partnerId);
        if (!in_array((string) $partner['plan_tier'], ['pro', 'elite'], true)) {
            throw new InvalidArgumentException('Meet-up ads and keys require the Pro or Elite partner plan.');
        }
        $venue = $this->requireVenue($venueId, $partnerId);
        $headline = trim((string) ($fields['headline'] ?? ''));
        if ($headline === '') {
            throw new InvalidArgumentException('A meet-up ad needs a headline.');
        }
        $keys = array_values(array_unique(array_map('strval', (array) ($fields['keys'] ?? []))));
        if ($keys === []) {
            throw new InvalidArgumentException('Purchase at least one key so the ad knows which date-talk to match.');
        }
        foreach ($keys as $key) {
            if (!isset(self::AD_KEYS[$key])) {
                throw new InvalidArgumentException('Unknown ad key: ' . $key);
            }
        }
        $adId = 'ad_' . substr(hash('sha256', $venueId . $headline . $now), 0, 12);
        $ad = [
            'venue_id' => $venueId,
            'partner_id' => $partnerId,
            'kind' => 'meetup',
            'headline' => $headline,
            'message' => trim((string) ($fields['message'] ?? '')),
            'offer' => trim((string) ($fields['offer'] ?? '')),
            'keys' => $keys,
            'status' => 'active',
            'created_at' => $now,
        ];
        $this->store->put('ads', $adId, $ad);
        $this->logAnalytics('ad_key_purchase', null, $venueId, ['ad_id' => $adId, 'keys' => $keys], $now);
        return $ad + ['id' => $adId];
    }

    /** @return array<int, array<string, mixed>> */
    public function adsForVenue(string $venueId): array
    {
        return $this->store->where('ads', ['venue_id' => $venueId]);
    }

    /**
     * Whether a chat has started arranging an in-person meet-up, and which
     * purchased keys its date-talk matches. Reads only the on-platform
     * conversation (the same consent boundary as the concierge); the
     * actual meeting place is never known, stored, or shared.
     *
     * @return array{meetup: bool, keys: array<int, string>}
     */
    public function meetupIntent(string $chatId): array
    {
        $chat = $this->requireChat($chatId);
        $recent = array_slice((array) $chat['messages'], -self::MEETUP_AD_WINDOW);
        $text = strtolower(implode(' ', array_map(
            static fn (array $message): string => (string) $message['text'],
            $recent,
        )));
        $meetup = false;
        foreach (self::MEETUP_PATTERNS as $pattern) {
            if ($text !== '' && str_contains($text, $pattern)) {
                $meetup = true;
                break;
            }
        }
        $keys = [];
        if ($meetup) {
            foreach (self::AD_KEYS as $key => $patterns) {
                foreach ($patterns as $pattern) {
                    if (str_contains($text, $pattern)) {
                        $keys[] = $key;
                        break;
                    }
                }
            }
        }
        return ['meetup' => $meetup, 'keys' => $keys];
    }

    /**
     * The meet-up ads to flash in a chat right now: shown only once the
     * pair starts arranging to meet, matched to the date-talk keys, from
     * advertisers near either member's town (Elite plans first, then
     * proximity). At most two — e.g. the Italian spot AND the theater.
     *
     * @return array<int, array<string, mixed>>
     */
    public function meetupAdsForChat(string $chatId, ?int $now = null): array
    {
        $now ??= time();
        $intent = $this->meetupIntent($chatId);
        if (!$intent['meetup'] || $intent['keys'] === []) {
            return [];
        }
        $chat = $this->requireChat($chatId);
        $zips = [];
        foreach ((array) $chat['participants'] as $participantId) {
            $zip = (string) ($this->requireUser((string) $participantId)['profile']['zip_code'] ?? '');
            if ($zip !== '') {
                $zips[] = $zip;
            }
        }
        $candidates = [];
        foreach ($this->store->all('ads') as $ad) {
            if ($ad['kind'] !== 'meetup' || $ad['status'] !== 'active') {
                continue;
            }
            $matched = array_values(array_intersect((array) $ad['keys'], $intent['keys']));
            if ($matched === []) {
                continue;
            }
            $venue = $this->store->get('venues', (string) $ad['venue_id']);
            if ($venue === null || $venue['status'] !== 'active') {
                continue;
            }
            $distance = 999.0;
            foreach ($zips as $zip) {
                $distance = min($distance, $this->zipProximityKm($zip, (string) $venue['zip_code']));
            }
            if ($distance > self::MEETUP_AD_RADIUS_KM) {
                continue;
            }
            $partner = $this->store->get('partners', (string) $ad['partner_id']);
            $candidates[] = [
                'ad_id' => (string) $ad['id'],
                'venue_id' => (string) $ad['venue_id'],
                'venue_name' => (string) $venue['name'],
                'headline' => (string) $ad['headline'],
                'message' => (string) $ad['message'],
                'offer' => (string) $ad['offer'],
                'matched_key' => $matched[0],
                'distance_km' => $distance,
                'elite' => ($partner['plan_tier'] ?? '') === 'elite',
            ];
        }
        usort($candidates, static fn (array $a, array $b): int =>
            [$b['elite'], -$a['distance_km'], $b['ad_id']] <=> [$a['elite'], -$b['distance_km'], $a['ad_id']]);
        // One ad per key, so an Italian-then-a-movie plan surfaces BOTH businesses.
        $chosen = [];
        foreach ($candidates as $candidate) {
            if (isset($chosen[$candidate['matched_key']])) {
                continue;
            }
            $chosen[$candidate['matched_key']] = $candidate;
            if (count($chosen) >= 2) {
                break;
            }
        }
        foreach ($chosen as $ad) {
            $this->logAnalytics('meetup_ad_impression', null, $ad['venue_id'], ['ad_id' => $ad['ad_id'], 'key' => $ad['matched_key']], $now);
        }
        return array_values($chosen);
    }

    // ------------------------------------------------------------------
    // Admin: leaderboard rewards program
    // ------------------------------------------------------------------

    public const REWARD_COHORTS = [10, 50, 100];
    public const REWARD_TYPES = ['free_membership', 'gift_certificate', 'product', 'event_tickets', 'promo_trip'];

    /**
     * Create an admin account. The first admin bootstraps the system;
     * afterwards only an existing admin can create another one.
     *
     * @return array{admin_id: string, token: string, auto_password: ?string}
     */
    public function createAdmin(string $email, ?string $password, ?string $createdByAdminId = null, ?int $now = null): array
    {
        $now ??= time();
        $email = strtolower(trim($email));
        if (filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
            throw new InvalidArgumentException('A valid admin email address is required.');
        }
        if ($this->store->count('admins') > 0) {
            if ($createdByAdminId === null || $this->store->get('admins', $createdByAdminId) === null) {
                throw new InvalidArgumentException('Only an existing admin can create another admin.');
            }
        }
        if ($this->store->where('admins', ['email' => $email]) !== []) {
            throw new InvalidArgumentException('An admin already exists for this email address.');
        }
        $generated = null;
        if ($password === null || $password === '') {
            $password = $this->generateStrongPassword();
            $generated = $password;
        } elseif ($this->passwordProblems($password) !== []) {
            throw new InvalidArgumentException('Weak password: ' . implode(' ', $this->passwordProblems($password)));
        }
        $adminId = 'adm_' . substr(hash('sha256', $email . $now), 0, 12);
        $this->store->put('admins', $adminId, [
            'email' => $email,
            'password_hash' => password_hash($password, PASSWORD_DEFAULT),
            'created_at' => $now,
        ]);
        return ['admin_id' => $adminId, 'token' => $this->issueToken($adminId, 'admin', $now), 'auto_password' => $generated];
    }

    /**
     * The popularity leaderboard, most popular first. Ties break on the
     * raw engagement score, then user id, so the order is deterministic.
     *
     * @return array<int, array<string, mixed>>
     */
    public function topMembers(int $count, ?int $now = null): array
    {
        $now ??= time();
        $rows = [];
        foreach ($this->store->all('users') as $user) {
            $userId = (string) $user['id'];
            $popularity = $this->popularity($userId, $now);
            $rows[] = [
                'user_id' => $userId,
                'display_name' => (string) ($user['profile']['display_name'] ?? ''),
                'popularity_score' => $popularity['popularity_score'],
                'percentile' => $popularity['percentile'],
                'raw_score' => $this->rawPopularity($userId),
            ];
        }
        // Rank on raw engagement received: normalized scores are per-gender
        // cohort relative, so they cannot be compared across the whole base.
        usort($rows, static fn (array $a, array $b): int =>
            [$b['raw_score'], $b['popularity_score'], $a['user_id']]
            <=> [$a['raw_score'], $a['popularity_score'], $b['user_id']]);
        return array_slice($rows, 0, max(1, $count));
    }

    /**
     * Grant a free benefit to every member in a top-N popularity cohort
     * (N must be 10, 50, or 100). Free memberships are applied
     * immediately; every grant is recorded for the member and audit log.
     *
     * @param array<string, mixed> $benefit  ['type' => one of REWARD_TYPES, plus
     *   'membership_tier' | 'amount' | 'product_id' | 'event_id' + 'quantity' | 'description']
     * @return array{campaign_id: string, cohort: int, granted: int, reward_type: string}
     */
    public function grantTopMemberRewards(string $adminId, int $cohort, array $benefit, ?int $now = null): array
    {
        $now ??= time();
        if ($this->store->get('admins', $adminId) === null) {
            throw new InvalidArgumentException('Only admins can grant leaderboard rewards.');
        }
        if (!in_array($cohort, self::REWARD_COHORTS, true)) {
            throw new InvalidArgumentException('Reward cohorts are the top 10, top 50, or top 100 members.');
        }
        $type = (string) ($benefit['type'] ?? '');
        if (!in_array($type, self::REWARD_TYPES, true)) {
            throw new InvalidArgumentException('Unknown reward type: ' . $type);
        }
        $campaignId = 'rwc_' . substr(hash('sha256', $adminId . $cohort . $type . $now), 0, 12);
        $granted = 0;
        foreach ($this->topMembers($cohort, $now) as $rank => $member) {
            $userId = (string) $member['user_id'];
            $detail = ['rank' => $rank + 1];
            switch ($type) {
                case 'free_membership':
                    $tier = (string) ($benefit['membership_tier'] ?? 'member');
                    if (!isset(self::MEMBERSHIP_PRICES[$tier])) {
                        throw new InvalidArgumentException('Unknown membership tier for the reward.');
                    }
                    $user = $this->requireUser($userId);
                    $user['membership_tier'] = $tier;
                    $user['membership_expires_at'] = $now + 365 * 86400;
                    $this->store->put('users', $userId, $user);
                    $detail['membership_tier'] = $tier;
                    break;
                case 'gift_certificate':
                    $amount = round((float) ($benefit['amount'] ?? 0), 2);
                    if ($amount <= 0) {
                        throw new InvalidArgumentException('A gift certificate needs a positive amount.');
                    }
                    $detail['amount'] = $amount;
                    break;
                case 'product':
                    $productId = (string) ($benefit['product_id'] ?? '');
                    if ($this->store->get('products', $productId) === null) {
                        throw new InvalidArgumentException('Unknown product for the reward.');
                    }
                    $detail['product_id'] = $productId;
                    break;
                case 'event_tickets':
                    $eventId = (string) ($benefit['event_id'] ?? '');
                    if ($this->store->get('events', $eventId) === null) {
                        throw new InvalidArgumentException('Unknown event for the reward.');
                    }
                    $detail['event_id'] = $eventId;
                    $detail['quantity'] = max(1, (int) ($benefit['quantity'] ?? 2));
                    break;
                case 'promo_trip':
                    $description = trim((string) ($benefit['description'] ?? ''));
                    if ($description === '') {
                        throw new InvalidArgumentException('A promo trip reward needs a description.');
                    }
                    $detail['description'] = $description;
                    break;
            }
            $rewardId = 'rwd_' . substr(hash('sha256', $campaignId . $userId), 0, 12);
            $this->store->put('rewards', $rewardId, [
                'campaign_id' => $campaignId,
                'user_id' => $userId,
                'reward_type' => $type,
                'detail' => $detail,
                'granted_by' => $adminId,
                'granted_at' => $now,
                'status' => 'granted',
            ]);
            $granted++;
        }
        $this->logAnalytics('reward_campaign', null, null, ['campaign_id' => $campaignId, 'cohort' => $cohort, 'type' => $type, 'granted' => $granted], $now);
        return ['campaign_id' => $campaignId, 'cohort' => $cohort, 'granted' => $granted, 'reward_type' => $type];
    }

    /** @return array<int, array<string, mixed>> Rewards granted to one member. */
    public function rewardsFor(string $userId): array
    {
        return $this->store->where('rewards', ['user_id' => $userId]);
    }

    // ------------------------------------------------------------------
    // Webhooks & analytics
    // ------------------------------------------------------------------

    /**
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    public function ingestTicketWebhook(array $payload, ?int $now = null): array
    {
        $now ??= time();
        $eventId = (string) ($payload['event_id'] ?? '');
        $userId = $this->externalUser((string) ($payload['user_external_id'] ?? ''));
        $ticketId = 'tix_' . substr(hash('sha256', 'ext' . ($payload['external_ticket_id'] ?? '') . $eventId), 0, 12);
        $event = $this->store->get('events', $eventId);
        $this->store->put('tickets', $ticketId, [
            'event_id' => $eventId,
            'user_id' => $userId,
            'quantity' => max(1, (int) ($payload['quantity'] ?? 1)),
            'total_amount' => round((float) ($payload['total_amount'] ?? 0.0), 2),
            'purchased_at' => $now,
            'source' => 'external',
        ]);
        $this->logAnalytics('ticket_purchase', $userId, $event !== null ? (string) $event['venue_id'] : null, ['event_id' => $eventId, 'source' => 'webhook'], $now);
        if ($userId !== null && $event !== null) {
            $this->enterEligibleContests($eventId, $userId, $now);
        }
        return ['ticket_id' => $ticketId, 'status' => 'recorded'];
    }

    /**
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    public function ingestBookingWebhook(array $payload, ?int $now = null): array
    {
        $now ??= time();
        $bookingId = 'bk_' . substr(hash('sha256', 'ext' . ($payload['booking_id'] ?? '') . ($payload['venue_external_id'] ?? '')), 0, 12);
        $userId = $this->externalUser((string) ($payload['user_external_id'] ?? ''));
        $this->store->put('bookings', $bookingId, [
            'kind' => 'venue',
            'venue_external_id' => (string) ($payload['venue_external_id'] ?? ''),
            'user_id' => $userId,
            'date_time' => (string) ($payload['date_time'] ?? ''),
            'party_size' => (int) ($payload['party_size'] ?? 2),
            'status' => (string) ($payload['status'] ?? 'confirmed'),
            'created_at' => $now,
        ]);
        $this->logAnalytics('booking_created', $userId, null, ['booking_id' => $bookingId], $now);
        return ['booking_id' => $bookingId, 'status' => 'recorded'];
    }

    /**
     * @param array<string, mixed> $payload
     * @return array<string, mixed>
     */
    public function ingestBodyguardWebhook(array $payload, ?int $now = null): array
    {
        $now ??= time();
        $bookingId = 'bg_' . substr(hash('sha256', 'ext' . ($payload['booking_id'] ?? '') . ($payload['service_id'] ?? '')), 0, 12);
        $userId = $this->externalUser((string) ($payload['user_external_id'] ?? ''));
        $this->store->put('bookings', $bookingId, [
            'kind' => 'bodyguard',
            'service_id' => (string) ($payload['service_id'] ?? ''),
            'user_id' => $userId,
            'date_time' => (string) ($payload['date_time'] ?? ''),
            'duration_minutes' => (int) ($payload['duration_minutes'] ?? 0),
            'status' => (string) ($payload['status'] ?? 'confirmed'),
            'created_at' => $now,
        ]);
        $this->logAnalytics('bodyguard_booking', $userId, null, ['booking_id' => $bookingId], $now);
        return ['booking_id' => $bookingId, 'status' => 'recorded'];
    }

    /** Partner-facing analytics rollup for one venue. */
    public function venueAnalytics(string $venueId): array
    {
        $coupons = $this->couponsForVenue($venueId);
        $redemptions = 0;
        foreach ($coupons as $coupon) {
            $redemptions += count($this->store->where('redemptions', ['coupon_id' => $coupon['id']]));
        }
        $ticketsSold = 0;
        $ticketRevenue = 0.0;
        foreach ($this->eventsForVenue($venueId) as $event) {
            foreach ($this->store->where('tickets', ['event_id' => $event['id']]) as $ticket) {
                $ticketsSold += (int) $ticket['quantity'];
                $ticketRevenue += (float) $ticket['total_amount'];
            }
        }
        $entries = 0;
        foreach ($this->contestsForVenue($venueId) as $contest) {
            $entries += count($this->store->where('contest_entries', ['contest_id' => $contest['id']]));
        }
        return [
            'venue_id' => $venueId,
            'total_coupons_created' => count($coupons),
            'total_redemptions' => $redemptions,
            'total_events' => count($this->eventsForVenue($venueId)),
            'total_tickets_sold' => $ticketsSold,
            'ticket_revenue' => round($ticketRevenue, 2),
            'total_contest_entries' => $entries,
            'meetup_ad_impressions' => count($this->store->where('analytics_events', ['type' => 'meetup_ad_impression', 'venue_id' => $venueId])),
        ];
    }

    // ------------------------------------------------------------------
    // Internals
    // ------------------------------------------------------------------

    /**
     * @param array<string, mixed> $fields
     * @param array<string, mixed> $targeting
     * @return array<string, mixed>
     */
    private function createCoupon(string $partnerId, string $venueId, string $type, array $fields, array $targeting, ?int $now): array
    {
        $now ??= time();
        $venue = $this->requireVenue($venueId, $partnerId);
        $discountAmount = (float) ($fields['discount_amount'] ?? 0);
        $discountType = (string) ($fields['discount_type'] ?? 'percent');
        if ($discountAmount <= 0 || !in_array($discountType, ['percent', 'fixed'], true)) {
            throw new InvalidArgumentException('A coupon needs a positive discount and a known discount type.');
        }
        $maxRecipients = max(1, (int) ($fields['max_recipients'] ?? 100));
        $recipients = $this->selectCouponRecipients($venue, $type, $targeting, $maxRecipients, $now);
        $couponId = 'cpn_' . substr(hash('sha256', $venueId . $type . $now . $this->store->count('coupons')), 0, 12);
        $coupon = [
            'venue_id' => $venueId,
            'type' => $type,
            'discount_type' => $discountType,
            'discount_amount' => $discountAmount,
            'valid_from' => (int) ($fields['valid_from'] ?? $now),
            'valid_to' => (int) ($fields['valid_to'] ?? $now + 30 * 86400),
            'max_recipients' => $maxRecipients,
            'targeting' => $targeting,
            'recipients' => $recipients,
            'created_at' => $now,
        ];
        $this->store->put('coupons', $couponId, $coupon);
        foreach ($recipients as $recipientId) {
            if ($type === 'targeted') {
                $this->recordPopularityEvent($recipientId, 'coupon_target', $now);
            }
        }
        $this->logAnalytics('coupon_created', null, $venueId, ['coupon_id' => $couponId, 'type' => $type], $now);
        return $coupon + ['id' => $couponId, 'estimated_reach' => count($recipients)];
    }

    /**
     * @param array<string, mixed> $venue
     * @param array<string, mixed> $targeting
     * @return array<int, string> Recipient user ids, deterministic order.
     */
    private function selectCouponRecipients(array $venue, string $type, array $targeting, int $maxRecipients, int $now): array
    {
        $candidates = [];
        foreach ($this->store->all('users') as $user) {
            $profile = (array) $user['profile'];
            if ($type === 'random') {
                if ($this->zipProximityKm((string) $venue['zip_code'], (string) $profile['zip_code']) <= 40.0) {
                    $candidates[] = (string) $user['id'];
                }
                continue;
            }
            if ($this->profileMatchesFilters($profile, [
                'gender' => $targeting['gender'] ?? null,
                'age_min' => $targeting['age_min'] ?? null,
                'age_max' => $targeting['age_max'] ?? null,
                'interests' => $targeting['interests'] ?? null,
                'dating_type' => $targeting['relationship_stage'] ?? null,
            ])) {
                $radius = (float) ($targeting['zip_radius_km'] ?? 40.0);
                if ($this->zipProximityKm((string) $venue['zip_code'], (string) $profile['zip_code']) <= $radius) {
                    $candidates[] = (string) $user['id'];
                }
            }
        }
        sort($candidates);
        return array_slice($candidates, 0, $maxRecipients);
    }

    private function enterEligibleContests(string $eventId, ?string $userId, int $now): void
    {
        if ($userId === null) {
            return;
        }
        foreach ($this->store->all('contests') as $contest) {
            $tied = (string) $contest['event_id'];
            if ($tied !== '' && $tied !== $eventId) {
                continue;
            }
            $event = $this->store->get('events', $eventId);
            if ($event === null || $event['venue_id'] !== $contest['venue_id']) {
                continue;
            }
            if ($now < (int) $contest['start_date'] || $now > (int) $contest['end_date']) {
                continue;
            }
            $entryId = 'ent_' . substr(hash('sha256', $contest['id'] . $userId), 0, 12);
            if ($this->store->get('contest_entries', $entryId) === null) {
                $this->store->put('contest_entries', $entryId, [
                    'contest_id' => (string) $contest['id'],
                    'user_id' => $userId,
                    'entry_date' => $now,
                ]);
            }
        }
    }

    /**
     * @param array<string, mixed> $profile
     * @param array<string, mixed> $filters
     */
    private function profileMatchesFilters(array $profile, array $filters): bool
    {
        $checks = [
            'gender' => static fn ($value): bool => (string) $profile['gender'] === (string) $value,
            'dating_type' => static fn ($value): bool => (string) $profile['dating_type'] === (string) $value,
            'faith' => static fn ($value): bool => (string) $profile['faith'] === (string) $value,
            'politics' => static fn ($value): bool => (string) $profile['politics'] === (string) $value,
            'income_range' => static fn ($value): bool => (string) $profile['income_range'] === (string) $value,
            'automobile' => static fn ($value): bool => (string) $profile['automobile'] === (string) $value,
            'occupation_category' => static fn ($value): bool => (string) $profile['occupation_category'] === (string) $value,
            'education' => static fn ($value): bool => (string) ($profile['education'] ?? '') === (string) $value,
            'family_plans' => static fn ($value): bool => (string) ($profile['family_plans'] ?? '') === (string) $value,
            'smoking' => static fn ($value): bool => (string) ($profile['smoking'] ?? '') === (string) $value,
            'drinking' => static fn ($value): bool => (string) ($profile['drinking'] ?? '') === (string) $value,
            'pets' => static fn ($value): bool => (string) ($profile['pets'] ?? '') === (string) $value,
            'age_min' => static fn ($value): bool => (int) $profile['age'] >= (int) $value,
            'age_max' => static fn ($value): bool => (int) $profile['age'] <= (int) $value,
        ];
        foreach ($checks as $field => $check) {
            $value = $filters[$field] ?? null;
            if ($value !== null && $value !== '' && !$check($value)) {
                return false;
            }
        }
        foreach (['interests', 'hobbies', 'outdoor_activities'] as $listField) {
            $wanted = $filters[$listField] ?? null;
            if ($wanted === null || $wanted === '' || $wanted === []) {
                continue;
            }
            $wantedList = is_array($wanted) ? $wanted : preg_split('/\s*,\s*/', (string) $wanted, -1, PREG_SPLIT_NO_EMPTY);
            $have = array_map('strtolower', (array) $profile[$listField]);
            foreach ((array) $wantedList as $item) {
                if (!in_array(strtolower(trim((string) $item)), $have, true)) {
                    return false;
                }
            }
        }
        $wantedCategories = $filters['shared_categories'] ?? null;
        if ($wantedCategories !== null && $wantedCategories !== [] && $wantedCategories !== '') {
            $wantedList = is_array($wantedCategories) ? $wantedCategories : preg_split('/\s*,\s*/', (string) $wantedCategories, -1, PREG_SPLIT_NO_EMPTY);
            $have = $this->interestCategories($profile);
            foreach ((array) $wantedList as $category) {
                if (!in_array((string) $category, $have, true)) {
                    return false;
                }
            }
        }
        if (isset($filters['zip_code'], $filters['zip_radius_km']) && $filters['zip_code'] !== '') {
            if ($this->zipProximityKm((string) $filters['zip_code'], (string) $profile['zip_code']) > (float) $filters['zip_radius_km']) {
                return false;
            }
        }
        return true;
    }

    /** @return array<string, mixed> */
    private function defaultProfile(): array
    {
        return [
            'display_name' => '',
            'age' => 0,
            'gender' => '',
            'zip_code' => '',
            'interests' => [],
            'hobbies' => [],
            'outdoor_activities' => [],
            'dating_type' => '',
            'faith' => '',
            'politics' => '',
            'income_range' => '',
            'automobile' => '',
            'occupation_category' => '',
            'education' => '',
            'family_plans' => '',
            'smoking' => '',
            'drinking' => '',
            'pets' => '',
        ];
    }

    /** @return array{0: int, 1: int} [daily message limit, size limit] for a chat age. */
    private function pacingFor(int $ageDays): array
    {
        $current = self::PACING[0];
        foreach (self::PACING as $minDays => $limits) {
            if ($ageDays >= $minDays) {
                $current = $limits;
            }
        }
        return $current;
    }

    /**
     * A completed session is a calendar day (UTC) on which BOTH members
     * sent at least one message — a real conversation, not a monologue.
     *
     * @param array<string, mixed> $chat
     */
    private function completedSessions(array $chat): int
    {
        $days = [];
        foreach ((array) $chat['messages'] as $message) {
            $day = gmdate('Y-m-d', (int) $message['sent_at']);
            $days[$day][(string) $message['sender_id']] = true;
        }
        return count(array_filter($days, static fn (array $senders): bool => count($senders) >= 2));
    }

    /** @param array<string, mixed> $chat */
    private function otherParticipant(array $chat, string $userId): string
    {
        foreach ((array) $chat['participants'] as $participant) {
            if ($participant !== $userId) {
                return (string) $participant;
            }
        }
        return $userId;
    }

    private function logSafetyEvent(string $protectedUserId, string $actorId, string $chatId, array $flags, int $now): void
    {
        $id = 'sfe_' . substr(hash('sha256', $chatId . $actorId . $now . implode(',', $flags)), 0, 12);
        $this->store->put('safety_events', $id, [
            'protected_user_id' => $protectedUserId,
            'actor_user_id' => $actorId,
            'chat_id' => $chatId,
            'flags' => $flags,
            'created_at' => $now,
        ]);
    }

    private function logAnalytics(string $type, ?string $userId, ?string $venueId, array $details, int $now): void
    {
        $id = 'ana_' . substr(hash('sha256', $type . $now . $this->store->count('analytics_events')), 0, 14);
        $this->store->put('analytics_events', $id, [
            'type' => $type,
            'user_id' => $userId,
            'venue_id' => $venueId,
            'details' => $details,
            'timestamp' => $now,
        ]);
    }

    private function externalUser(string $externalId): ?string
    {
        if ($externalId === '') {
            return null;
        }
        return $this->store->get('users', $externalId) !== null ? $externalId : null;
    }

    private function newUserId(int $now): string
    {
        do {
            $suffix = '';
            $alphabet = 'ABCDEFGHJKMNPQRSTVWXYZ0123456789';
            for ($i = 0; $i < 5; $i++) {
                $suffix .= $alphabet[random_int(0, strlen($alphabet) - 1)];
            }
            $id = 'U' . gmdate('Ymd', $now) . '-' . $suffix;
        } while ($this->store->get('users', $id) !== null);
        return $id;
    }

    private function issueToken(string $subjectId, string $kind, int $now): string
    {
        $token = bin2hex(random_bytes(24));
        $this->store->put('tokens', hash('sha256', $token), [
            'subject_id' => $subjectId,
            'kind' => $kind,
            'issued_at' => $now,
        ]);
        return $token;
    }

    /** @return array<string, mixed> */
    private function requireUser(string $userId): array
    {
        $user = $this->store->get('users', $userId);
        if ($user === null) {
            throw new InvalidArgumentException('Unknown member: ' . $userId);
        }
        return $user;
    }

    /** @return array<string, mixed> */
    private function requireChat(string $chatId): array
    {
        $chat = $this->store->get('chats', $chatId);
        if ($chat === null) {
            throw new InvalidArgumentException('Unknown chat: ' . $chatId);
        }
        return $chat;
    }

    /** @return array<string, mixed> */
    private function requireVenue(string $venueId, ?string $partnerId = null): array
    {
        $venue = $this->store->get('venues', $venueId);
        if ($venue === null) {
            throw new InvalidArgumentException('Unknown venue: ' . $venueId);
        }
        if ($partnerId !== null && $venue['partner_id'] !== $partnerId) {
            throw new InvalidArgumentException('This venue belongs to another partner.');
        }
        return $venue;
    }
}
