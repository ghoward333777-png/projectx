<?php

namespace Joomla\Component\Mediamarketplace\Administrator\View\Status;

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\Language\Text;
use Joomla\CMS\MVC\View\HtmlView as BaseHtmlView;
use Joomla\CMS\Plugin\PluginHelper;
use Joomla\CMS\Toolbar\ToolbarHelper;

final class HtmlView extends BaseHtmlView
{
    public ?\MmsRuntime $runtime = null;
    public ?string $problem = null;
    /** @var array{ok:bool,version:string}|null */
    public ?array $ping = null;

    public function display($tpl = null): void
    {
        ToolbarHelper::title(Text::_('COM_MEDIAMARKETPLACE_STATUS_TITLE'), 'store');
        if (PluginHelper::isEnabled('system', 'mediamarketplace')) {
            $plugin = Factory::getApplication()->bootPlugin('mediamarketplace', 'system');
            if (method_exists($plugin, 'runtime')) {
                $this->runtime = $plugin->runtime();
                $this->problem = $this->runtime->platformProblem();
                $this->ping = $this->problem ? null : $this->runtime->ping();
            }
        }
        parent::display($tpl);
    }
}
