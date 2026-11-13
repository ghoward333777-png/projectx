<?php

declare(strict_types=1);

/**
 * Merch shop. The magazine lists products; checkout always happens on PayPal or Amazon,
 * so no payment details ever touch this site.
 *
 *  - PayPal:  a hosted button ID, a PayPal payment link, or a paypal.me link.
 *  - Amazon:  an ASIN or an Amazon product link; the Associates tag is added automatically.
 */
final class MagazineShop
{
    public const AMAZON_DISCLOSURE = 'As an Amazon Associate we earn from qualifying purchases.';
    private const PAYPAL_HOSTS = '~^(?:www\.)?(?:paypal\.com|paypal\.me|py\.pl)$~i';
    private const AMAZON_HOSTS = '~^(?:(?:www|smile)\.)?amazon\.(?:com|ca|co\.uk|de|fr|it|es|nl|se|pl|com\.au|co\.jp|in|com\.mx|com\.br|sg|ae|sa|com\.tr|eg|com\.be)$~i';
    private const AMAZON_SHORT_HOSTS = '~^(?:amzn\.to|a\.co|amzn\.eu|amzn\.asia)$~i';

    public function __construct(private MagazineStore $store)
    {
    }

    /** @return array{amazon_tag: string, amazon_domain: string, paypal_store_url: string, amazon_store_url: string} */
    public function settings(): array
    {
        return array_merge(
            ['amazon_tag' => '', 'amazon_domain' => 'www.amazon.com', 'paypal_store_url' => '', 'amazon_store_url' => ''],
            (array) $this->store->read('shop-settings', [])
        );
    }

    /** @param array<string, mixed> $in */
    public function saveSettings(array $in): void
    {
        $tag = trim((string) ($in['amazon_tag'] ?? ''));
        if ($tag !== '' && !preg_match('~^[A-Za-z0-9-]{3,40}$~', $tag)) {
            throw new DomainException('An Amazon Associates tag looks like yourname-20.');
        }
        $domain = strtolower(trim((string) ($in['amazon_domain'] ?? ''))) ?: 'www.amazon.com';
        if (!preg_match(self::AMAZON_HOSTS, $domain)) {
            throw new DomainException('Enter an Amazon site such as www.amazon.com or www.amazon.co.uk.');
        }
        $paypal = trim((string) ($in['paypal_store_url'] ?? ''));
        if ($paypal !== '' && !self::hostMatches($paypal, self::PAYPAL_HOSTS)) {
            throw new DomainException('The PayPal store link must be an https link on paypal.com or paypal.me.');
        }
        $amazon = trim((string) ($in['amazon_store_url'] ?? ''));
        if ($amazon !== '' && !self::hostMatches($amazon, self::AMAZON_HOSTS) && !self::hostMatches($amazon, self::AMAZON_SHORT_HOSTS)) {
            throw new DomainException('The Amazon store link must be an https link on an Amazon site.');
        }
        $this->store->write('shop-settings', [
            'amazon_tag' => $tag, 'amazon_domain' => $domain, 'paypal_store_url' => $paypal, 'amazon_store_url' => $amazon,
        ]);
    }

    private static function hostMatches(string $url, string $pattern): bool
    {
        $parts = parse_url($url);
        return is_array($parts) && strtolower($parts['scheme'] ?? '') === 'https' && preg_match($pattern, $parts['host'] ?? '') === 1;
    }

    /** Add the Associates tag to an Amazon link, replacing any tag already on it. */
    public static function withAmazonTag(string $url, string $tag): string
    {
        if ($tag === '' || !self::hostMatches($url, self::AMAZON_HOSTS)) {
            return $url;
        }
        [$base, $fragment] = array_pad(explode('#', $url, 2), 2, null);
        [$path, $query] = array_pad(explode('?', $base, 2), 2, '');
        parse_str((string) $query, $params);
        $params['tag'] = $tag;
        return $path . '?' . http_build_query($params) . ($fragment !== null ? '#' . $fragment : '');
    }

    /**
     * Turn what the editor typed into the outbound checkout link.
     *
     * @param array<string, string>|null $settings
     */
    public function resolveLink(string $kind, string $target, ?array $settings = null): string
    {
        $settings ??= $this->settings();
        $target = trim($target);
        if ($kind === 'paypal') {
            if (preg_match('~^[A-Z0-9]{8,20}$~', $target)) {
                return 'https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=' . $target;
            }
            if (self::hostMatches($target, self::PAYPAL_HOSTS)) {
                return $target;
            }
            throw new DomainException('For PayPal, enter a hosted button ID or an https link on paypal.com or paypal.me.');
        }
        if ($kind === 'amazon') {
            if (preg_match('~^[A-Z0-9]{10}$~', $target)) {
                return self::withAmazonTag('https://' . $settings['amazon_domain'] . '/dp/' . $target, $settings['amazon_tag']);
            }
            if (self::hostMatches($target, self::AMAZON_HOSTS)) {
                return self::withAmazonTag($target, $settings['amazon_tag']);
            }
            if (self::hostMatches($target, self::AMAZON_SHORT_HOSTS)) {
                return $target; // short links already carry the tag they were created with
            }
            throw new DomainException('For Amazon, enter a 10-character ASIN or an https link on an Amazon site.');
        }
        throw new DomainException('Choose PayPal or Amazon for this product.');
    }

    /** Products with their outbound link resolved. @return array<int, array<string, mixed>> */
    public function products(): array
    {
        $settings = $this->settings();
        $out = [];
        foreach ($this->store->read('products', []) as $p) {
            try {
                $p['url'] = $this->resolveLink($p['kind'], $p['target'], $settings);
                $out[] = $p;
            } catch (DomainException) {
                // A product whose link no longer validates is not shown.
            }
        }
        return $out;
    }

    /** @param array<string, mixed> $in */
    public function saveProduct(array $in): void
    {
        $name = trim((string) ($in['name'] ?? ''));
        if ($name === '' || mb_strlen($name) > 120) {
            throw new DomainException('A product needs a name of up to 120 characters.');
        }
        $kind = (string) ($in['kind'] ?? '');
        $target = trim((string) ($in['target'] ?? ''));
        $this->resolveLink($kind, $target);
        $image = trim((string) ($in['image'] ?? ''));
        if ($image !== '' && (!filter_var($image, FILTER_VALIDATE_URL) || !str_starts_with(strtolower($image), 'https://'))) {
            throw new DomainException('The image must be an https link.');
        }
        $product = [
            'id' => bin2hex(random_bytes(6)),
            'name' => $name,
            'blurb' => mb_substr(trim((string) ($in['blurb'] ?? '')), 0, 300),
            'price' => mb_substr(trim((string) ($in['price'] ?? '')), 0, 30),
            'image' => $image,
            'kind' => $kind,
            'target' => $target,
        ];
        $this->store->mutate('products', static fn ($list) => array_merge($list, [$product]));
    }

    public function deleteProduct(string $id): void
    {
        $this->store->mutate('products', static fn ($list) => array_values(array_filter($list, static fn ($p) => $p['id'] !== $id)));
    }
}
