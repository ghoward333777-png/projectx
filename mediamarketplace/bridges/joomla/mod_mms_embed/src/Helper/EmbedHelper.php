<?php

namespace Joomla\Module\MmsEmbed\Site\Helper;

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\Plugin\PluginHelper;
use Joomla\Registry\Registry;

/** Builds the embed markup by asking the system plugin, which owns the connection settings. */
final class EmbedHelper
{
    public function markup(Registry $params): string
    {
        if (!PluginHelper::isEnabled('system', 'mmsbridge')) {
            return '';
        }
        $plugin = Factory::getApplication()->bootPlugin('mmsbridge', 'system');
        if (!method_exists($plugin, 'embed')) {
            return '';
        }
        $kind = (string) $params->get('kind', 'showcase');
        return $plugin->embed($kind, [
            'id'       => (string) $params->get('id', ''),
            'view'     => (string) $params->get('view', ''),
            'category' => (string) $params->get('category', ''),
        ]);
    }
}
