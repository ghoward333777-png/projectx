<?php

namespace Joomla\Component\Mediamarketplace\Administrator\View\Virtuemart;

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\Language\Text;
use Joomla\CMS\MVC\View\HtmlView as BaseHtmlView;
use Joomla\CMS\Plugin\PluginHelper;
use Joomla\CMS\Toolbar\ToolbarHelper;

/** Sell through VirtueMart: status, product import and the checkout switch. */
final class HtmlView extends BaseHtmlView
{
    public ?object $bridge = null;
    /** @var array<string,mixed>|null */
    public ?array $status = null;
    /** @var array<int,array<string,mixed>> */
    public array $catalog = [];
    public bool $virtuemartInstalled = false;

    public function display($tpl = null): void
    {
        ToolbarHelper::title(Text::_('COM_MEDIAMARKETPLACE_VM_TITLE'), 'store');
        if (PluginHelper::isEnabled('system', 'mediamarketplace')) {
            $plugin = Factory::getApplication()->bootPlugin('mediamarketplace', 'system');
            if (method_exists($plugin, 'virtuemart')) {
                $this->bridge = $plugin->virtuemart();
                $this->virtuemartInstalled = $this->bridge !== null;
                if ($this->bridge !== null) {
                    $this->status = $this->bridge->status();
                    $this->catalog = $this->status === null ? [] : $this->bridge->catalog();
                }
            }
        }
        parent::display($tpl);
    }
}
