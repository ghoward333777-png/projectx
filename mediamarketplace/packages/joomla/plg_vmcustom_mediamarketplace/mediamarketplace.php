<?php
/**
 * VirtueMart custom plugin: "MediaMarketplace" product field and order events.
 *
 * Optional. Installed with the MediaMarketplace package; VirtueMart loads it only when
 * VirtueMart itself is installed. It does two things: it lets a VirtueMart product carry
 * the store product it delivers (custom field, or the SKU MMS-<slug> without any field),
 * and it reports order status changes to the store the moment VirtueMart records them.
 * The reconciliation in the system plugin covers anything this hook misses.
 */

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\Language\Text;
use Joomla\CMS\Plugin\PluginHelper;

if (!class_exists('vmCustomPlugin')) {
    if (\defined('JPATH_VM_PLUGINS') && is_file(JPATH_VM_PLUGINS . '/vmcustomplugin.php')) {
        require JPATH_VM_PLUGINS . '/vmcustomplugin.php';
    } else {
        return; // VirtueMart is not installed; nothing to register
    }
}

class plgVmCustomMediamarketplace extends vmCustomPlugin
{
    public function __construct(&$subject, $config)
    {
        parent::__construct($subject, $config);
        $this->_tablepkey = 'id';
        $this->_tableId = 'id';
        $varsToPush = $this->getVarsToPush();
        $this->setConfigParameterable($this->_configTableFieldName, $varsToPush);
    }

    /** VirtueMart 3 and 4: declare the per-product parameters (the store slug). */
    public function plgVmDeclarePluginParamsCustomVM3(&$data)
    {
        return $this->declarePluginParams('custom', $data);
    }

    public function plgVmSetOnTablePluginParamsCustom($name, $id, &$table)
    {
        return $this->setOnTablePluginParams($name, $id, $table);
    }

    /** Shown on the product page: what the buyer gets and where to open it. */
    public function plgVmOnDisplayProductFEVM3(&$product, &$group)
    {
        if ($group->custom_element !== $this->_name) {
            return false;
        }
        $bridge = $this->bridge();
        $account = $bridge !== null ? $bridge->api('GET', '/status') : null;
        $html = '<div class="mms-vm-field"><p>' . Text::_('PLG_VMCUSTOM_MEDIAMARKETPLACE_DELIVERY') . '</p>';
        $plugin = $this->systemPlugin();
        if ($plugin !== null && method_exists($plugin, 'ssoUrl')) {
            $url = $plugin->ssoUrl('/account');
            if ($url !== null) {
                $html .= '<p><a class="btn btn-secondary btn-sm" rel="nofollow" href="' . htmlspecialchars($url, ENT_QUOTES) . '">' . Text::_('PLG_VMCUSTOM_MEDIAMARKETPLACE_OPEN') . '</a></p>';
            }
        }
        $html .= '</div>';
        foreach ($group->options as $option) {
            $option->display = $html;
        }
        return true;
    }

    /** Never adds to the price and is never a cart attribute. */
    public function plgVmOnViewCartVM3(&$product, &$productCustom, &$html)
    {
        return false;
    }

    /** The order's payment status changed (VirtueMart's own trigger). */
    public function plgVmOnUpdateOrderPayment(&$order, $old_order_status)
    {
        $this->report((int) ($order->virtuemart_order_id ?? 0));
        return null;
    }

    /** A line of the order changed status (VirtueMart's per-line trigger for custom plugins). */
    public function plgVmOnUpdateOrderLine($type, $name, $id, &$data)
    {
        if ($name !== $this->_name) {
            return null;
        }
        $this->report((int) ($data->virtuemart_order_id ?? 0));
        return null;
    }

    private function report(int $orderId): void
    {
        if ($orderId <= 0) {
            return;
        }
        try {
            $bridge = $this->bridge();
            if ($bridge !== null) {
                $bridge->reportOrder($orderId);
            }
        } catch (\Throwable $e) {
            // The reconciliation in the system plugin retries within minutes.
        }
    }

    private function systemPlugin(): ?object
    {
        if (!PluginHelper::isEnabled('system', 'mediamarketplace')) {
            return null;
        }
        $plugin = Factory::getApplication()->bootPlugin('mediamarketplace', 'system');
        return method_exists($plugin, 'virtuemart') ? $plugin : null;
    }

    /** @return \Joomla\Plugin\System\Mediamarketplace\Commerce\VirtueMartBridge|null */
    private function bridge(): ?object
    {
        $plugin = $this->systemPlugin();
        return $plugin === null ? null : $plugin->virtuemart();
    }
}
