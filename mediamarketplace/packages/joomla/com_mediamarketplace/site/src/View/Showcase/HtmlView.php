<?php

namespace Joomla\Component\Mediamarketplace\Site\View\Showcase;

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\MVC\View\HtmlView as BaseHtmlView;
use Joomla\CMS\Plugin\PluginHelper;

/** The product showcase served by the bundled server, placed as a menu item. */
final class HtmlView extends BaseHtmlView
{
    public string $html = '';
    public string $problem = '';

    public function display($tpl = null): void
    {
        $params = Factory::getApplication()->getParams();
        $this->html = self::embed('showcase', [
            'view'     => (string) $params->get('view', 'grid'),
            'category' => (string) $params->get('category', ''),
        ], $this->problem);
        $this->setTitle($params);
        parent::display($tpl);
    }

    /** @param array<string,string> $args */
    public static function embed(string $kind, array $args, string &$problem): string
    {
        if (!PluginHelper::isEnabled('system', 'mediamarketplace')) {
            $problem = 'COM_MEDIAMARKETPLACE_PLUGIN_DISABLED';
            return '';
        }
        $plugin = Factory::getApplication()->bootPlugin('mediamarketplace', 'system');
        if (!method_exists($plugin, 'embed')) {
            $problem = 'COM_MEDIAMARKETPLACE_PLUGIN_DISABLED';
            return '';
        }
        return $plugin->embed($kind, $args);
    }

    protected function setTitle($params): void
    {
        $title = (string) $params->get('page_title', '');
        if ($title !== '') {
            $this->getDocument()->setTitle($title);
        }
    }
}
