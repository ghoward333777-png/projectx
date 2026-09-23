<?php

namespace Joomla\Plugin\System\Mediamarketplace\Commerce;

\defined('_JEXEC') or die;

use Joomla\CMS\Component\ComponentHelper;
use Joomla\CMS\Factory;
use Joomla\Database\DatabaseInterface;

/**
 * Optional "sell through VirtueMart".
 *
 * The store's own checkout stays the default. When the administrator switches checkout
 * to VirtueMart (Components → MediaMarketplace → VirtueMart), Buy buttons add the linked
 * VirtueMart product to the VirtueMart cart; VirtueMart takes the money and this class
 * reports confirmed, refunded and cancelled orders to the store, which grants or
 * revokes access and issues the receipt.
 *
 * Orders are reported two ways, both idempotent on the store side: immediately from the
 * VirtueMart custom plugin when an order status changes, and by a reconciliation that
 * reads VirtueMart's order tables every few minutes, so a missed event never leaves a
 * customer without access. Only VirtueMart's public tables are read; nothing is written
 * to them except the products the administrator asks to import.
 */
final class VirtueMartBridge
{
    public const SYSTEM = 'virtuemart';
    public const SKU_PREFIX = 'MMS-';
    private const THROTTLE_SECONDS = 300;
    private const STATE = 'virtuemart-sync.json';

    private \MmsRuntime $rt;
    private DatabaseInterface $db;

    public function __construct(\MmsRuntime $rt, DatabaseInterface $db)
    {
        $this->rt = $rt;
        $this->db = $db;
    }

    /** VirtueMart is installed, enabled and has its order table. */
    public static function available(): bool
    {
        if (!ComponentHelper::isEnabled('com_virtuemart')) {
            return false;
        }
        try {
            $db = Factory::getContainer()->get(DatabaseInterface::class);
            $tables = $db->getTableList();
            $prefix = $db->getPrefix();
            return \in_array($prefix . 'virtuemart_orders', $tables, true) && \in_array($prefix . 'virtuemart_order_items', $tables, true);
        } catch (\Throwable $e) {
            return false;
        }
    }

    // ----- store API ------------------------------------------------------------------

    /** @param array<string,mixed>|null $body @return array{ok:bool,status:int,data:mixed,error:string} */
    public function api(string $method, string $path, ?array $body = null): array
    {
        return $this->rt->apiCall($method, '/api/v1/commerce' . $path, $body);
    }

    /** @return array<string,mixed>|null */
    public function status(): ?array
    {
        $r = $this->api('GET', '/status');
        return $r['ok'] && \is_array($r['data']) ? $r['data'] : null;
    }

    /** @return array<int,array<string,mixed>> */
    public function catalog(): array
    {
        $r = $this->api('GET', '/catalog?system=' . self::SYSTEM);
        return $r['ok'] && \is_array($r['data']) ? $r['data'] : [];
    }

    /** @return array{ok:bool,status:int,data:mixed,error:string} */
    public function setMode(string $mode, string $unlinked): array
    {
        return $this->api('POST', '/mode', ['mode' => $mode, 'unlinked' => $unlinked === 'hide' ? 'hide' : 'native']);
    }

    // ----- VirtueMart schema helpers -------------------------------------------------

    /** Language suffix of the VirtueMart language tables, e.g. "en_gb". */
    public function langSuffix(): string
    {
        $tables = $this->db->getTableList();
        $prefix = $this->db->getPrefix() . 'virtuemart_products_';
        $langs = [];
        foreach ($tables as $t) {
            if (str_starts_with($t, $prefix)) {
                $langs[] = substr($t, \strlen($prefix));
            }
        }
        $site = strtolower(str_replace('-', '_', (string) Factory::getApplication()->get('language', 'en-GB')));
        if (\in_array($site, $langs, true)) {
            return $site;
        }
        return $langs[0] ?? 'en_gb';
    }

    private function vendorCurrencyId(): int
    {
        $q = $this->db->getQuery(true)->select('vendor_currency')->from('#__virtuemart_vendors')->where('virtuemart_vendor_id = 1');
        return (int) $this->db->setQuery($q)->loadResult();
    }

    private function currencyCode(int $id): string
    {
        if ($id <= 0) {
            return '';
        }
        $q = $this->db->getQuery(true)->select('currency_code_3')->from('#__virtuemart_currencies')->where('virtuemart_currency_id = ' . $id);
        return (string) $this->db->setQuery($q)->loadResult();
    }

    // ----- products ---------------------------------------------------------------

    /**
     * Creates a VirtueMart product for every store product that has none, refreshes the
     * linked ones when asked, links VirtueMart products whose SKU is MMS-<slug>, and
     * records every link in the store. Returns [created, updated, linked, errors].
     *
     * @return array{0:int,1:int,2:int,3:string[]}
     */
    public function importProducts(bool $refresh): array
    {
        $created = 0;
        $updated = 0;
        $errors = [];
        $links = [];
        $lang = $this->langSuffix();
        $currency = $this->vendorCurrencyId();
        $now = Factory::getDate()->toSql();
        $uid = (int) Factory::getApplication()->getIdentity()?->id;
        foreach ($this->catalog() as $p) {
            $slug = (string) $p['slug'];
            $sku = self::SKU_PREFIX . strtoupper($slug);
            try {
                $existing = (int) ($p['external_id'] ?? 0);
                if ($existing > 0) {
                    $q = $this->db->getQuery(true)->select('virtuemart_product_id')->from('#__virtuemart_products')->where('virtuemart_product_id = ' . $existing);
                    $existing = (int) $this->db->setQuery($q)->loadResult();
                }
                if ($existing === 0) {
                    $q = $this->db->getQuery(true)->select('virtuemart_product_id')->from('#__virtuemart_products')->where('product_sku = ' . $this->db->quote($sku));
                    $existing = (int) $this->db->setQuery($q)->loadResult();
                }
                if ($existing === 0) {
                    $existing = $this->createProduct($p, $sku, $lang, $currency, $now, $uid);
                    $created++;
                } elseif ($refresh) {
                    $this->updateProduct($existing, $p, $lang, $now, $uid);
                    $updated++;
                }
                $this->ensureCustomField($existing, $slug, $now, $uid);
                $links[] = ['slug' => $slug, 'external_id' => (string) $existing, 'external_url' => $this->productUrl($existing)];
            } catch (\Throwable $e) {
                $errors[] = $slug . ': ' . $e->getMessage();
            }
        }
        $linked = 0;
        if ($links) {
            $r = $this->api('POST', '/link', ['system' => self::SYSTEM, 'links' => $links]);
            if ($r['ok'] && \is_array($r['data'])) {
                $linked = (int) ($r['data']['linked'] ?? 0);
            } else {
                $errors[] = 'link: ' . $r['error'];
            }
        }
        return [$created, $updated, $linked, $errors];
    }

    private function productUrl(int $id): string
    {
        $root = rtrim((string) \Joomla\CMS\Uri\Uri::root(), '/');
        return $root . '/index.php?option=com_virtuemart&view=productdetails&virtuemart_product_id=' . $id;
    }

    /** @param array<string,mixed> $p */
    private function createProduct(array $p, string $sku, string $lang, int $currency, string $now, int $uid): int
    {
        $row = (object) [
            'virtuemart_vendor_id' => 1, 'product_parent_id' => 0, 'product_sku' => $sku, 'product_gtin' => '', 'product_mpn' => '',
            'product_weight_uom' => 'KG', 'product_lwh_uom' => 'M', 'product_url' => '', 'product_in_stock' => 0, 'product_ordered' => 0,
            'product_availability' => '', 'product_unit' => 'KG', 'product_packaging' => 0, 'product_params' => '', 'hits' => 0,
            'intnotes' => 'Created by MediaMarketplace Studio', 'metarobot' => '', 'metaauthor' => '', 'layout' => '',
            'published' => ($p['status'] ?? '') === 'published' ? 1 : 0, 'pordering' => 0, 'product_special' => 0, 'product_sales' => 0,
            'created_on' => $now, 'created_by' => $uid, 'modified_on' => $now, 'modified_by' => $uid,
        ];
        $this->db->insertObject('#__virtuemart_products', $row);
        $id = (int) $this->db->insertid();
        $text = (object) [
            'virtuemart_product_id' => $id, 'product_s_desc' => (string) ($p['type_label'] ?? ''), 'product_desc' => (string) ($p['description'] ?? ''),
            'product_name' => (string) $p['title'], 'metadesc' => '', 'metakey' => '', 'customtitle' => '', 'slug' => (string) $p['slug'],
        ];
        $this->db->insertObject('#__virtuemart_products_' . $lang, $text);
        $price = (object) [
            'virtuemart_product_id' => $id, 'product_price' => ((int) $p['price_cents']) / 100, 'product_currency' => $currency ?: null,
            'created_on' => $now, 'created_by' => $uid, 'modified_on' => $now, 'modified_by' => $uid,
        ];
        $this->db->insertObject('#__virtuemart_product_prices', $price);
        try {
            $cat = $this->ensureCategory($lang, $now, $uid);
            if ($cat > 0) {
                $this->db->insertObject('#__virtuemart_product_categories', (object) ['virtuemart_product_id' => $id, 'virtuemart_category_id' => $cat, 'ordering' => 0]);
            }
        } catch (\Throwable $e) {
            // The product exists without a category; VirtueMart still sells it by direct link and search.
        }
        return $id;
    }

    /** @param array<string,mixed> $p */
    private function updateProduct(int $id, array $p, string $lang, string $now, int $uid): void
    {
        $this->db->updateObject('#__virtuemart_products', (object) ['virtuemart_product_id' => $id, 'published' => ($p['status'] ?? '') === 'published' ? 1 : 0, 'modified_on' => $now, 'modified_by' => $uid], 'virtuemart_product_id');
        $this->db->updateObject('#__virtuemart_products_' . $lang, (object) ['virtuemart_product_id' => $id, 'product_name' => (string) $p['title'], 'product_desc' => (string) ($p['description'] ?? '')], 'virtuemart_product_id');
        $q = $this->db->getQuery(true)->update('#__virtuemart_product_prices')->set('product_price = ' . (((int) $p['price_cents']) / 100))->set('modified_on = ' . $this->db->quote($now))->where('virtuemart_product_id = ' . $id);
        $this->db->setQuery($q)->execute();
    }

    private function ensureCategory(string $lang, string $now, int $uid): int
    {
        $q = $this->db->getQuery(true)->select('virtuemart_category_id')->from('#__virtuemart_categories_' . $lang)->where('slug = ' . $this->db->quote('mediamarketplace'));
        $id = (int) $this->db->setQuery($q)->loadResult();
        if ($id > 0) {
            return $id;
        }
        $this->db->insertObject('#__virtuemart_categories', (object) [
            'virtuemart_vendor_id' => 1, 'category_template' => '', 'category_layout' => '', 'category_product_layout' => '', 'products_per_row' => 0,
            'limit_list_step' => 0, 'limit_list_initial' => 0, 'hits' => 0, 'metarobot' => '', 'metaauthor' => '', 'published' => 1, 'ordering' => 0, 'shared' => 0,
            'created_on' => $now, 'created_by' => $uid, 'modified_on' => $now, 'modified_by' => $uid,
        ]);
        $id = (int) $this->db->insertid();
        $this->db->insertObject('#__virtuemart_categories_' . $lang, (object) ['virtuemart_category_id' => $id, 'category_name' => 'MediaMarketplace', 'category_description' => '', 'metadesc' => '', 'metakey' => '', 'customtitle' => '', 'slug' => 'mediamarketplace']);
        $this->db->insertObject('#__virtuemart_category_categories', (object) ['category_parent_id' => 0, 'category_child_id' => $id, 'ordering' => 0]);
        return $id;
    }

    /** The "MediaMarketplace" custom field (plugin field) carrying the store slug on the product. */
    private function ensureCustomField(int $productId, string $slug, string $now, int $uid): void
    {
        try {
            $q = $this->db->getQuery(true)->select('virtuemart_custom_id')->from('#__virtuemart_customs')->where('custom_element = ' . $this->db->quote('mediamarketplace'))->where('field_type = ' . $this->db->quote('E'));
            $customId = (int) $this->db->setQuery($q)->loadResult();
            if ($customId === 0) {
                $q = $this->db->getQuery(true)->select('extension_id')->from('#__extensions')->where('type = ' . $this->db->quote('plugin'))->where('folder = ' . $this->db->quote('vmcustom'))->where('element = ' . $this->db->quote('mediamarketplace'));
                $pluginId = (int) $this->db->setQuery($q)->loadResult();
                if ($pluginId === 0) {
                    return; // the VirtueMart plugin is not installed; SKU and the store mapping still work
                }
                $this->db->insertObject('#__virtuemart_customs', (object) [
                    'virtuemart_vendor_id' => 1, 'custom_jplugin_id' => $pluginId, 'custom_element' => 'mediamarketplace', 'custom_parent_id' => 0, 'admin_only' => 0,
                    'custom_title' => 'MediaMarketplace', 'show_title' => 1, 'custom_tip' => '', 'custom_value' => '', 'custom_desc' => 'Digital delivery through MediaMarketplace Studio',
                    'field_type' => 'E', 'is_list' => 0, 'is_hidden' => 0, 'is_cart_attribute' => 0, 'is_input' => 0, 'searchable' => 0, 'layout_pos' => '', 'custom_params' => '',
                    'shared' => 0, 'published' => 1, 'ordering' => 0, 'created_on' => $now, 'created_by' => $uid, 'modified_on' => $now, 'modified_by' => $uid,
                ]);
                $customId = (int) $this->db->insertid();
            }
            $q = $this->db->getQuery(true)->select('virtuemart_customfield_id')->from('#__virtuemart_product_customfields')->where('virtuemart_product_id = ' . $productId)->where('virtuemart_custom_id = ' . $customId);
            if ((int) $this->db->setQuery($q)->loadResult() > 0) {
                return;
            }
            $this->db->insertObject('#__virtuemart_product_customfields', (object) [
                'virtuemart_product_id' => $productId, 'virtuemart_custom_id' => $customId, 'customfield_value' => $slug, 'customfield_params' => 'mms_slug=' . json_encode($slug) . '|',
                'published' => 1, 'ordering' => 0, 'created_on' => $now, 'created_by' => $uid, 'modified_on' => $now, 'modified_by' => $uid,
            ]);
        } catch (\Throwable $e) {
            // Optional decoration; the SKU and the store mapping are what deliver access.
        }
    }

    /** VirtueMart product id => store slug, from the store's mapping plus MMS-<slug> SKUs. */
    private function mappedProducts(): array
    {
        $map = [];
        foreach ($this->catalog() as $p) {
            if (!empty($p['external_id'])) {
                $map[(int) $p['external_id']] = (string) $p['slug'];
            }
        }
        $q = $this->db->getQuery(true)->select(['virtuemart_product_id', 'product_sku'])->from('#__virtuemart_products')->where('product_sku LIKE ' . $this->db->quote(self::SKU_PREFIX . '%'));
        foreach ((array) $this->db->setQuery($q)->loadObjectList() as $row) {
            $id = (int) $row->virtuemart_product_id;
            if (!isset($map[$id])) {
                $map[$id] = strtolower(substr((string) $row->product_sku, \strlen(self::SKU_PREFIX)));
            }
        }
        return $map;
    }

    // ----- orders ---------------------------------------------------------------------

    /** VirtueMart order status code → what the store needs to hear, or '' to ignore. */
    public static function mapStatus(string $code): string
    {
        return match (strtoupper($code)) {
            'C', 'S' => 'paid',
            'R' => 'refunded',
            'X', 'D' => 'cancelled',
            default => '',
        };
    }

    /**
     * Reports one VirtueMart order to the store. Returns the store's answer, or null when
     * the order has no store products or its status means nothing to the store.
     *
     * @return array<string,mixed>|null
     */
    public function reportOrder(int $orderId): ?array
    {
        $q = $this->db->getQuery(true)->select('*')->from('#__virtuemart_orders')->where('virtuemart_order_id = ' . $orderId);
        $order = $this->db->setQuery($q)->loadObject();
        if (!$order) {
            return null;
        }
        $status = self::mapStatus((string) $order->order_status);
        if ($status === '') {
            return null;
        }
        $map = $this->mappedProducts();
        $q = $this->db->getQuery(true)->select('*')->from('#__virtuemart_order_items')->where('virtuemart_order_id = ' . $orderId);
        $items = [];
        foreach ((array) $this->db->setQuery($q)->loadObjectList() as $it) {
            $pid = (int) $it->virtuemart_product_id;
            if (!isset($map[$pid])) {
                continue;
            }
            $qty = max(1, (int) $it->product_quantity);
            $items[] = ['slug' => $map[$pid], 'quantity' => $qty, 'unit_cents' => (int) round(((float) $it->product_item_price) * 100)];
        }
        if (!$items) {
            return null;
        }
        $q = $this->db->getQuery(true)->select(['u.email', 'u.first_name', 'u.last_name', 'c.country_2_code'])->from('#__virtuemart_order_userinfos AS u')
            ->join('LEFT', '#__virtuemart_countries AS c ON c.virtuemart_country_id = u.virtuemart_country_id')
            ->where('u.virtuemart_order_id = ' . $orderId)->where('u.address_type = ' . $this->db->quote('BT'));
        $info = $this->db->setQuery($q)->loadObject();
        $email = (string) ($info->email ?? '');
        if ($email === '' && (int) $order->virtuemart_user_id > 0) {
            $email = (string) Factory::getUser((int) $order->virtuemart_user_id)->email;
        }
        $body = [
            'system'         => self::SYSTEM,
            'external_id'    => (string) $order->virtuemart_order_id,
            'status'         => $status,
            'customer'       => [
                'id'    => (int) $order->virtuemart_user_id > 0 ? (string) $order->virtuemart_user_id : 'guest:' . strtolower($email),
                'email' => $email,
                'name'  => trim((string) ($info->first_name ?? '') . ' ' . (string) ($info->last_name ?? '')),
            ],
            'currency'       => $this->currencyCode((int) $order->order_currency),
            'items'          => $items,
            'discount_cents' => (int) round((abs((float) ($order->coupon_discount ?? 0)) + abs((float) ($order->order_discount ?? 0))) * 100),
            'tax_cents'      => (int) round(((float) ($order->order_tax ?? 0)) * 100),
            'country'        => (string) ($info->country_2_code ?? ''),
        ];
        $r = $this->api('POST', '/orders', $body);
        return $r['ok'] && \is_array($r['data']) ? $r['data'] : ['error' => $r['error']];
    }

    /** Reports every order changed in the last days. Returns how many were reported. */
    public function reconcile(int $days = 2): int
    {
        $since = Factory::getDate('-' . $days . ' days')->toSql();
        $q = $this->db->getQuery(true)->select('virtuemart_order_id')->from('#__virtuemart_orders')
            ->where('modified_on >= ' . $this->db->quote($since))->where('order_status IN (' . implode(',', array_map([$this->db, 'quote'], ['C', 'S', 'R', 'X', 'D'])) . ')')
            ->order('virtuemart_order_id ASC');
        $n = 0;
        foreach ((array) $this->db->setQuery($q, 0, 500)->loadColumn() as $id) {
            if ($this->reportOrder((int) $id) !== null) {
                $n++;
            }
        }
        return $n;
    }

    /** Runs the reconciliation at most every few minutes; called on ordinary page loads. */
    public function maybeReconcile(): void
    {
        $file = $this->rt->dataDir() . '/' . self::STATE;
        $last = is_file($file) ? (int) ((json_decode((string) file_get_contents($file), true) ?: [])['last'] ?? 0) : 0;
        if (time() - $last < self::THROTTLE_SECONDS) {
            return;
        }
        @file_put_contents($file, json_encode(['last' => time()]), LOCK_EX);
        $status = $this->status();
        if ($status === null || ($status['mode'] ?? '') !== self::SYSTEM) {
            return; // only while checkout runs in VirtueMart
        }
        try {
            $this->reconcile();
        } catch (\Throwable $e) {
            // Never break a page load over a sync problem; the admin page shows the store's log.
        }
    }
}
