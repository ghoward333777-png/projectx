<?php
/**
 * Optional WooCommerce integration ("sell through WooCommerce").
 *
 * Loaded by MMS_Plugin only when WooCommerce is active. The store's own checkout stays
 * the default; switching to WooCommerce here makes every Buy button in the store add
 * the linked WooCommerce product to the WooCommerce cart. WooCommerce takes the money;
 * this module reports paid, refunded and cancelled orders (and WooCommerce
 * Subscriptions changes) to the store, which grants or revokes access and issues the
 * receipt. Nothing here touches card data or WooCommerce's own tables.
 */

if (!defined('ABSPATH')) {
    exit;
}

final class MMS_WooCommerce
{
    public const META = '_mms_product';          // store product slug on a WooCommerce product
    public const META_ORDER = '_mms_order_state'; // last state reported to the store for an order
    public const CRON = 'mms_woocommerce_reconcile';
    public const ENDPOINT = 'mediamarketplace';
    private const CATALOG_TRANSIENT = 'mms_wc_catalog';

    private static ?self $instance = null;
    private MMS_Plugin $plugin;

    public static function boot(MMS_Plugin $plugin): self
    {
        return self::$instance ??= new self($plugin);
    }

    private function __construct(MMS_Plugin $plugin)
    {
        $this->plugin = $plugin;
        add_action('admin_menu', [$this, 'adminMenu'], 20);
        add_filter('woocommerce_product_data_tabs', [$this, 'productTab']);
        add_action('woocommerce_product_data_panels', [$this, 'productPanel']);
        add_action('woocommerce_process_product_meta', [$this, 'saveProduct']);
        // Orders: every path that means "paid" and every path that means "money went back".
        add_action('woocommerce_payment_complete', [$this, 'orderPaid']);
        add_action('woocommerce_order_status_processing', [$this, 'orderPaid']);
        add_action('woocommerce_order_status_completed', [$this, 'orderPaid']);
        add_action('woocommerce_order_status_refunded', [$this, 'orderRefunded']);
        add_action('woocommerce_order_fully_refunded', [$this, 'orderRefunded']);
        add_action('woocommerce_order_status_cancelled', [$this, 'orderCancelled']);
        add_action('woocommerce_order_status_failed', [$this, 'orderCancelled']);
        // WooCommerce Subscriptions (when installed) for recurring site passes.
        add_action('woocommerce_subscription_status_updated', [$this, 'subscriptionChanged'], 10, 3);
        add_action('woocommerce_subscription_renewal_payment_complete', [$this, 'subscriptionRenewed'], 10, 2);
        // My account → My media.
        add_action('init', [$this, 'registerEndpoint']);
        add_filter('woocommerce_account_menu_items', [$this, 'accountMenu']);
        add_action('woocommerce_account_' . self::ENDPOINT . '_endpoint', [$this, 'accountPage']);
        add_action('woocommerce_order_details_after_order_table', [$this, 'orderDetails']);
        // Safety net: re-report recent orders hourly (idempotent on the store side).
        add_action(self::CRON, [$this, 'reconcile']);
        if (!wp_next_scheduled(self::CRON)) {
            wp_schedule_event(time() + 300, 'hourly', self::CRON);
        }
    }

    // ----- store API ---------------------------------------------------------------

    /** @param array<string,mixed>|null $body @return array{ok:bool,status:int,data:mixed,error:string} */
    private function api(string $method, string $path, ?array $body = null): array
    {
        return $this->plugin->runtime()->apiCall($method, '/api/v1/commerce' . $path, $body);
    }

    /** @return array<int,array<string,mixed>> */
    private function catalog(bool $fresh = false): array
    {
        $cached = $fresh ? false : get_transient(self::CATALOG_TRANSIENT);
        if (is_array($cached)) {
            return $cached;
        }
        $r = $this->api('GET', '/catalog?system=woocommerce');
        $list = $r['ok'] && is_array($r['data']) ? $r['data'] : [];
        set_transient(self::CATALOG_TRANSIENT, $list, 5 * MINUTE_IN_SECONDS);
        return $list;
    }

    // ----- products -----------------------------------------------------------------

    /** @param array<string,array<string,mixed>> $tabs @return array<string,array<string,mixed>> */
    public function productTab(array $tabs): array
    {
        $tabs['mediamarketplace'] = ['label' => 'MediaMarketplace', 'target' => 'mms_product_data', 'class' => [], 'priority' => 75];
        return $tabs;
    }

    public function productPanel(): void
    {
        global $post;
        $current = (string) get_post_meta($post->ID, self::META, true);
        echo '<div id="mms_product_data" class="panel woocommerce_options_panel"><div class="options_group">';
        echo '<p class="form-field"><label for="mms_product">' . esc_html__('Store product', 'mediamarketplace-studio') . '</label><select id="mms_product" name="mms_product" style="width:60%"><option value="">' . esc_html__('— not a MediaMarketplace product —', 'mediamarketplace-studio') . '</option>';
        foreach ($this->catalog() as $p) {
            printf('<option value="%s"%s>%s (%s, %s %s)</option>', esc_attr((string) $p['slug']), selected($current, (string) $p['slug'], false), esc_html((string) $p['title']), esc_html((string) $p['type_label']), esc_html((string) $p['currency']), esc_html(number_format(((int) $p['price_cents']) / 100, 2)));
        }
        echo '</select><span class="description">' . esc_html__('When this WooCommerce product is bought, the customer gets the linked store product in My media. The store keeps the price shown in its showcase; keep the WooCommerce price the same.', 'mediamarketplace-studio') . '</span></p>';
        echo '</div></div>';
    }

    public function saveProduct(int $post_id): void
    {
        if (!isset($_POST['mms_product'])) {
            return;
        }
        $slug = sanitize_text_field(wp_unslash((string) $_POST['mms_product']));
        $old = (string) get_post_meta($post_id, self::META, true);
        if ($slug === '') {
            delete_post_meta($post_id, self::META);
            if ($old !== '') {
                $this->api('POST', '/link', ['system' => 'woocommerce', 'unlink' => [$old]]);
            }
            return;
        }
        update_post_meta($post_id, self::META, $slug);
        $this->api('POST', '/link', ['system' => 'woocommerce', 'links' => [['slug' => $slug, 'external_id' => (string) $post_id, 'external_url' => (string) get_permalink($post_id)]]]);
    }

    /** Store slug for a WooCommerce product or variation, or ''. */
    private function slugFor(int $product_id): string
    {
        $slug = (string) get_post_meta($product_id, self::META, true);
        if ($slug === '' && ($parent = (int) wp_get_post_parent_id($product_id)) > 0) {
            $slug = (string) get_post_meta($parent, self::META, true);
        }
        return $slug;
    }

    /**
     * Creates a WooCommerce product for every store product that has none yet and
     * refreshes title, price and description of the ones already linked. Returns
     * [created, updated, errors].
     *
     * @return array{0:int,1:int,2:string[]}
     */
    public function importProducts(bool $refresh): array
    {
        $created = 0;
        $updated = 0;
        $errors = [];
        $links = [];
        foreach ($this->catalog(true) as $p) {
            $slug = (string) $p['slug'];
            $existing = (int) ($p['external_id'] ?? 0);
            if ($existing > 0 && get_post_status($existing) === false) {
                $existing = 0; // deleted in WooCommerce
            }
            if ($existing === 0) {
                $found = get_posts(['post_type' => 'product', 'post_status' => 'any', 'meta_key' => self::META, 'meta_value' => $slug, 'fields' => 'ids', 'numberposts' => 1]);
                $existing = $found ? (int) $found[0] : 0;
            }
            try {
                $product = $existing > 0 ? wc_get_product($existing) : null;
                if ($product === null || $product === false) {
                    $product = new WC_Product_Simple();
                    $product->set_name((string) $p['title']);
                    $product->set_slug($slug);
                    $product->set_status($p['status'] === 'published' ? 'publish' : 'draft');
                    $product->set_virtual(true);
                    $product->set_sold_individually(true);
                    $product->set_sku('MMS-' . strtoupper($slug));
                    $product->set_regular_price(number_format(((int) $p['price_cents']) / 100, 2, '.', ''));
                    $product->set_description((string) $p['description']);
                    $product->set_short_description((string) $p['type_label']);
                    $product->update_meta_data(self::META, $slug);
                    $id = $product->save();
                    $this->attachImage($id, (string) ($p['image_url'] ?? ''));
                    $created++;
                } elseif ($refresh) {
                    $product->set_name((string) $p['title']);
                    $product->set_regular_price(number_format(((int) $p['price_cents']) / 100, 2, '.', ''));
                    $product->set_description((string) $p['description']);
                    $product->set_status($p['status'] === 'published' ? 'publish' : 'draft');
                    $product->update_meta_data(self::META, $slug);
                    $id = $product->save();
                    $updated++;
                } else {
                    $id = $product->get_id();
                }
                $links[] = ['slug' => $slug, 'external_id' => (string) $id, 'external_url' => (string) get_permalink($id)];
            } catch (Throwable $e) {
                $errors[] = $slug . ': ' . $e->getMessage();
            }
        }
        if ($links) {
            $r = $this->api('POST', '/link', ['system' => 'woocommerce', 'links' => $links]);
            if (!$r['ok']) {
                $errors[] = 'link: ' . $r['error'];
            }
        }
        delete_transient(self::CATALOG_TRANSIENT);
        return [$created, $updated, $errors];
    }

    private function attachImage(int $product_id, string $url): void
    {
        if ($url === '' || has_post_thumbnail($product_id)) {
            return;
        }
        require_once ABSPATH . 'wp-admin/includes/media.php';
        require_once ABSPATH . 'wp-admin/includes/file.php';
        require_once ABSPATH . 'wp-admin/includes/image.php';
        $id = media_sideload_image($url, $product_id, null, 'id');
        if (is_int($id)) {
            set_post_thumbnail($product_id, $id);
        }
    }

    // ----- orders -------------------------------------------------------------------

    public function orderPaid(int $order_id): void
    {
        $this->report($order_id, 'paid');
    }

    public function orderRefunded(int $order_id): void
    {
        $this->report($order_id, 'refunded');
    }

    public function orderCancelled(int $order_id): void
    {
        $this->report($order_id, 'cancelled');
    }

    /** Tells the store about an order; safe to call repeatedly (the store is idempotent). */
    public function report(int $order_id, string $status): void
    {
        $order = wc_get_order($order_id);
        if (!$order) {
            return;
        }
        $items = [];
        foreach ($order->get_items() as $item) {
            if (!$item instanceof WC_Order_Item_Product) {
                continue;
            }
            $pid = $item->get_variation_id() ?: $item->get_product_id();
            $slug = $this->slugFor((int) $pid);
            if ($slug === '') {
                continue;
            }
            $qty = max(1, (int) $item->get_quantity());
            $items[] = ['slug' => $slug, 'quantity' => $qty, 'unit_cents' => (int) round(((float) $item->get_subtotal()) * 100 / $qty)];
        }
        if (!$items) {
            return; // not a store order
        }
        $last = (string) $order->get_meta(self::META_ORDER);
        if ($last === $status && $status !== 'paid') {
            return;
        }
        $user = $order->get_user();
        $body = [
            'system'         => 'woocommerce',
            'external_id'    => (string) $order->get_id(),
            'status'         => $status,
            'customer'       => [
                'id'    => $user ? (string) $user->ID : 'guest:' . strtolower((string) $order->get_billing_email()),
                'email' => (string) $order->get_billing_email(),
                'name'  => trim($order->get_billing_first_name() . ' ' . $order->get_billing_last_name()),
            ],
            'currency'       => (string) $order->get_currency(),
            'items'          => $items,
            'discount_cents' => (int) round(((float) $order->get_discount_total()) * 100),
            'tax_cents'      => (int) round(((float) $order->get_total_tax()) * 100),
            'country'        => (string) $order->get_billing_country(),
        ];
        if ($status === 'paid' && function_exists('wcs_get_subscriptions_for_order')) {
            foreach (wcs_get_subscriptions_for_order($order, ['order_type' => 'parent']) as $sub) {
                $body['subscription'] = ['external_id' => (string) $sub->get_id(), 'period_end' => $this->periodEnd($sub)];
                break;
            }
        }
        $r = $this->api('POST', '/orders', $body);
        if ($r['ok']) {
            $order->update_meta_data(self::META_ORDER, $status);
            $order->save_meta_data();
            $outcome = is_array($r['data']) ? (string) ($r['data']['outcome'] ?? '') : '';
            $number = is_array($r['data']) && isset($r['data']['order']['number']) ? (string) $r['data']['order']['number'] : '';
            $order->add_order_note(sprintf('MediaMarketplace: %s%s', $outcome !== '' ? $outcome : $status, $number !== '' ? " ({$number})" : ''));
        } else {
            $order->add_order_note('MediaMarketplace: could not report the order (' . $r['error'] . '). It will be retried by the hourly check.');
        }
    }

    /** Re-reports recent orders so a missed hook never leaves a customer without access. */
    public function reconcile(): void
    {
        $orders = wc_get_orders(['limit' => 100, 'date_modified' => '>' . (time() - 2 * DAY_IN_SECONDS), 'status' => ['processing', 'completed', 'refunded', 'cancelled'], 'return' => 'ids']);
        foreach ($orders as $id) {
            $order = wc_get_order($id);
            if (!$order) {
                continue;
            }
            $status = match ($order->get_status()) {
                'processing', 'completed' => 'paid',
                'refunded' => 'refunded',
                default => 'cancelled',
            };
            $this->report((int) $id, $status);
        }
    }

    // ----- subscriptions --------------------------------------------------------------

    /** @param mixed $subscription */
    private function periodEnd($subscription): string
    {
        foreach (['next_payment', 'end', 'trial_end'] as $k) {
            $d = (string) $subscription->get_date($k);
            if ($d !== '' && $d !== '0') {
                return gmdate('Y-m-d\TH:i:s\Z', strtotime($d . ' UTC') ?: time());
            }
        }
        return '';
    }

    /** @param mixed $subscription */
    public function subscriptionChanged($subscription, string $new_status, string $old_status): void
    {
        $status = match ($new_status) {
            'active' => 'active',
            'pending-cancel' => 'pending_cancel',
            'on-hold' => 'on_hold',
            'cancelled', 'expired', 'switched' => $new_status,
            default => '',
        };
        if ($status === '') {
            return;
        }
        $this->reportSubscription($subscription, $status);
    }

    /** @param mixed $subscription @param mixed $last_order */
    public function subscriptionRenewed($subscription, $last_order): void
    {
        $this->reportSubscription($subscription, 'renewed');
    }

    /** @param mixed $subscription */
    private function reportSubscription($subscription, string $status): void
    {
        $product_external = '';
        foreach ($subscription->get_items() as $item) {
            if ($item instanceof WC_Order_Item_Product) {
                $pid = $item->get_variation_id() ?: $item->get_product_id();
                if ($this->slugFor((int) $pid) !== '') {
                    $product_external = (string) $pid;
                    break;
                }
            }
        }
        if ($product_external === '') {
            return;
        }
        $user = $subscription->get_user();
        $parent = $subscription->get_parent();
        $this->api('POST', '/subscriptions', [
            'system'              => 'woocommerce',
            'external_id'         => (string) $subscription->get_id(),
            'status'              => $status,
            'customer'            => ['id' => $user ? (string) $user->ID : '', 'email' => (string) $subscription->get_billing_email(), 'name' => trim($subscription->get_billing_first_name() . ' ' . $subscription->get_billing_last_name())],
            'product_external_id' => $product_external,
            'period_end'          => $this->periodEnd($subscription),
            'order_external_id'   => $parent ? (string) $parent->get_id() : '',
        ]);
    }

    // ----- My account ---------------------------------------------------------------

    public function registerEndpoint(): void
    {
        add_rewrite_endpoint(self::ENDPOINT, EP_ROOT | EP_PAGES);
    }

    /** @param array<string,string> $items @return array<string,string> */
    public function accountMenu(array $items): array
    {
        $out = [];
        foreach ($items as $k => $v) {
            $out[$k] = $v;
            if ($k === 'orders') {
                $out[self::ENDPOINT] = __('My media', 'mediamarketplace-studio');
            }
        }
        if (!isset($out[self::ENDPOINT])) {
            $out[self::ENDPOINT] = __('My media', 'mediamarketplace-studio');
        }
        return $out;
    }

    public function accountPage(): void
    {
        $u = wp_get_current_user();
        $rt = $this->plugin->runtime();
        $sso = static fn(string $return): string => $rt->ssoUrl(['id' => $u->ID, 'email' => $u->user_email, 'name' => $u->display_name], $return);
        $r = $this->api('GET', '/customers/' . rawurlencode((string) $u->ID));
        $ents = $r['ok'] && is_array($r['data']) ? (array) ($r['data']['entitlements'] ?? []) : [];
        echo '<h2>' . esc_html__('My media', 'mediamarketplace-studio') . '</h2>';
        if (!$ents) {
            echo '<p>' . esc_html__('Nothing yet. Items you buy appear here and in your media library.', 'mediamarketplace-studio') . '</p>';
        } else {
            echo '<table class="woocommerce-orders-table shop_table"><thead><tr><th>' . esc_html__('Item', 'mediamarketplace-studio') . '</th><th>' . esc_html__('Until', 'mediamarketplace-studio') . '</th><th></th></tr></thead><tbody>';
            foreach ($ents as $e) {
                $title = isset($e['product']['title']) ? (string) $e['product']['title'] : ($e['scope'] === 'site' ? __('Site pass (whole library)', 'mediamarketplace-studio') : (string) $e['scope']);
                printf('<tr><td>%s</td><td>%s</td><td><a class="button" href="%s">%s</a></td></tr>', esc_html($title), esc_html($e['ends_at'] ? substr((string) $e['ends_at'], 0, 10) : __('no end', 'mediamarketplace-studio')), esc_url($sso((string) $e['open_path'])), esc_html__('Open', 'mediamarketplace-studio'));
            }
            echo '</tbody></table>';
        }
        printf('<p><a class="button" href="%s">%s</a> <a class="button" href="%s">%s</a></p>', esc_url($sso('/account')), esc_html__('Open my media library', 'mediamarketplace-studio'), esc_url($sso('/account/orders')), esc_html__('Store receipts', 'mediamarketplace-studio'));
    }

    /** @param WC_Order $order */
    public function orderDetails($order): void
    {
        if (!$order instanceof WC_Order || !is_user_logged_in()) {
            return;
        }
        foreach ($order->get_items() as $item) {
            if ($item instanceof WC_Order_Item_Product && $this->slugFor((int) ($item->get_variation_id() ?: $item->get_product_id())) !== '') {
                $u = wp_get_current_user();
                $url = $this->plugin->runtime()->ssoUrl(['id' => $u->ID, 'email' => $u->user_email, 'name' => $u->display_name], '/account');
                printf('<p><a class="button" href="%s">%s</a></p>', esc_url($url), esc_html__('Open in My media', 'mediamarketplace-studio'));
                return;
            }
        }
    }

    // ----- admin page ---------------------------------------------------------------

    public function adminMenu(): void
    {
        add_submenu_page('mms-open', 'WooCommerce', 'WooCommerce', 'manage_woocommerce', 'mms-woocommerce', [$this, 'page']);
    }

    public function page(): void
    {
        $notice = '';
        $error = '';
        if (isset($_POST['mms_wc_action']) && check_admin_referer('mms_woocommerce')) {
            $action = sanitize_key((string) $_POST['mms_wc_action']);
            if ($action === 'import' || $action === 'refresh') {
                [$c, $u, $errs] = $this->importProducts($action === 'refresh');
                $notice = sprintf(__('%d WooCommerce products created, %d refreshed.', 'mediamarketplace-studio'), $c, $u);
                $error = implode(' ', $errs);
            } elseif ($action === 'mode_woocommerce' || $action === 'mode_native') {
                $r = $this->api('POST', '/mode', ['mode' => $action === 'mode_woocommerce' ? 'woocommerce' : 'native', 'unlinked' => isset($_POST['mms_unlinked_hide']) ? 'hide' : 'native']);
                $notice = $r['ok'] ? ($action === 'mode_woocommerce' ? __('Checkout now runs in WooCommerce.', 'mediamarketplace-studio') : __('Checkout now runs in the store.', 'mediamarketplace-studio')) : '';
                $error = $r['ok'] ? '' : $r['error'];
            } elseif ($action === 'reconcile') {
                $this->reconcile();
                $notice = __('Recent orders re-sent to the store.', 'mediamarketplace-studio');
            }
        }
        $status = $this->api('GET', '/status');
        $s = $status['ok'] && is_array($status['data']) ? $status['data'] : null;
        $catalog = $this->catalog(true);
        ?>
        <div class="wrap">
            <h1><?php esc_html_e('MediaMarketplace and WooCommerce', 'mediamarketplace-studio'); ?></h1>
            <?php if ($notice) : ?><div class="notice notice-success"><p><?php echo esc_html($notice); ?></p></div><?php endif; ?>
            <?php if ($error) : ?><div class="notice notice-error"><p><?php echo esc_html($error); ?></p></div><?php endif; ?>
            <?php if ($s === null) : ?>
                <div class="notice notice-error"><p><?php echo esc_html($status['error']); ?></p></div>
            <?php else : ?>
            <p><?php esc_html_e('Optional. Leave the store on its own checkout, or sell through WooCommerce: Buy buttons then add the linked WooCommerce product to the WooCommerce cart, WooCommerce takes the payment, and the store grants access and issues the receipt when the order is paid. Refunds and cancellations in WooCommerce take the access back.', 'mediamarketplace-studio'); ?></p>
            <table class="widefat striped" style="max-width:900px">
                <tr><th style="width:220px"><?php esc_html_e('Checkout runs in', 'mediamarketplace-studio'); ?></th><td><b><?php echo $s['mode'] === 'woocommerce' ? 'WooCommerce' : ($s['mode'] === 'virtuemart' ? 'VirtueMart' : esc_html__('the store (native)', 'mediamarketplace-studio')); ?></b></td></tr>
                <tr><th><?php esc_html_e('Linked products', 'mediamarketplace-studio'); ?></th><td><?php echo (int) ($s['linked']['woocommerce'] ?? 0); ?> <?php esc_html_e('of', 'mediamarketplace-studio'); ?> <?php echo (int) $s['products']; ?></td></tr>
                <tr><th><?php esc_html_e('Unlinked products', 'mediamarketplace-studio'); ?></th><td><?php echo $s['unlinked'] === 'hide' ? esc_html__('hide their Buy button', 'mediamarketplace-studio') : esc_html__('use the store checkout', 'mediamarketplace-studio'); ?></td></tr>
            </table>
            <form method="post" style="margin-top:12px"><?php wp_nonce_field('mms_woocommerce'); ?>
                <p>
                    <button class="button button-primary" name="mms_wc_action" value="import"><?php esc_html_e('Import store products into WooCommerce', 'mediamarketplace-studio'); ?></button>
                    <button class="button" name="mms_wc_action" value="refresh"><?php esc_html_e('Refresh titles and prices', 'mediamarketplace-studio'); ?></button>
                    <button class="button" name="mms_wc_action" value="reconcile"><?php esc_html_e('Re-send recent orders', 'mediamarketplace-studio'); ?></button>
                </p>
                <p>
                    <label><input type="checkbox" name="mms_unlinked_hide" value="1" <?php checked($s['unlinked'], 'hide'); ?>> <?php esc_html_e('Hide the Buy button on products that have no WooCommerce product', 'mediamarketplace-studio'); ?></label>
                </p>
                <p>
                    <?php if ($s['mode'] === 'woocommerce') : ?>
                        <button class="button" name="mms_wc_action" value="mode_native"><?php esc_html_e('Switch back to the store checkout', 'mediamarketplace-studio'); ?></button>
                    <?php else : ?>
                        <button class="button button-primary" name="mms_wc_action" value="mode_woocommerce"><?php esc_html_e('Sell through WooCommerce', 'mediamarketplace-studio'); ?></button>
                    <?php endif; ?>
                </p>
            </form>
            <h2><?php esc_html_e('Products', 'mediamarketplace-studio'); ?></h2>
            <table class="widefat striped" style="max-width:900px"><thead><tr><th><?php esc_html_e('Store product', 'mediamarketplace-studio'); ?></th><th><?php esc_html_e('Type', 'mediamarketplace-studio'); ?></th><th><?php esc_html_e('Price', 'mediamarketplace-studio'); ?></th><th><?php esc_html_e('WooCommerce product', 'mediamarketplace-studio'); ?></th></tr></thead><tbody>
            <?php foreach ($catalog as $p) : ?>
                <tr><td><?php echo esc_html((string) $p['title']); ?></td><td><?php echo esc_html((string) $p['type_label']); ?></td><td><?php echo esc_html((string) $p['currency'] . ' ' . number_format(((int) $p['price_cents']) / 100, 2)); ?></td>
                <td><?php if (!empty($p['external_id'])) : ?><a href="<?php echo esc_url(get_edit_post_link((int) $p['external_id']) ?: '#'); ?>">#<?php echo (int) $p['external_id']; ?></a><?php else : ?><span style="color:#b32d2e"><?php esc_html_e('not linked', 'mediamarketplace-studio'); ?></span><?php endif; ?></td></tr>
            <?php endforeach; ?>
            </tbody></table>
            <?php if (!empty($s['events'])) : ?>
            <h2><?php esc_html_e('Recent messages to the store', 'mediamarketplace-studio'); ?></h2>
            <table class="widefat striped" style="max-width:900px"><thead><tr><th><?php esc_html_e('Kind', 'mediamarketplace-studio'); ?></th><th><?php esc_html_e('WooCommerce id', 'mediamarketplace-studio'); ?></th><th><?php esc_html_e('Status', 'mediamarketplace-studio'); ?></th><th><?php esc_html_e('Result', 'mediamarketplace-studio'); ?></th><th><?php esc_html_e('When', 'mediamarketplace-studio'); ?></th></tr></thead><tbody>
            <?php foreach ($s['events'] as $e) : if ($e['system'] !== 'woocommerce') { continue; } ?>
                <tr><td><?php echo esc_html((string) $e['kind']); ?></td><td>#<?php echo esc_html((string) $e['external_id']); ?></td><td><?php echo esc_html((string) $e['status']); ?></td><td><?php echo esc_html((string) $e['result']); ?></td><td><?php echo esc_html((string) $e['created_at']); ?></td></tr>
            <?php endforeach; ?>
            </tbody></table>
            <?php endif; ?>
            <p class="description"><?php esc_html_e('Any WooCommerce product can also be linked by hand: edit the product and pick the store product under Product data → MediaMarketplace. Customers find everything they bought under My account → My media.', 'mediamarketplace-studio'); ?></p>
            <?php endif; ?>
        </div>
        <?php
    }
}
