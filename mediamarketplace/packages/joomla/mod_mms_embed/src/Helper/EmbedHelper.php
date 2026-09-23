<?php

namespace Joomla\Module\MmsEmbed\Site\Helper;

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\Plugin\PluginHelper;
use Joomla\Registry\Registry;

/** Builds the embed markup by asking the system plugin, which owns the runtime. */
final class EmbedHelper
{
    public function markup(Registry $params): string
    {
        if (!PluginHelper::isEnabled('system', 'mediamarketplace')) {
            return '';
        }
        $plugin = Factory::getApplication()->bootPlugin('mediamarketplace', 'system');
        if (!method_exists($plugin, 'embed')) {
            return '';
        }
        return $plugin->embed((string) $params->get('kind', 'showcase'), [
            'id'       => (string) $params->get('id', ''),
            'view'     => (string) $params->get('view', ''),
            'category' => (string) $params->get('category', ''),
        ]);
    }
}
