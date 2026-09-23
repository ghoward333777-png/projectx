<?php

namespace Joomla\Component\Mediamarketplace\Site\View\Account;

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\MVC\View\HtmlView as BaseHtmlView;
use Joomla\CMS\Plugin\PluginHelper;
use Joomla\CMS\Router\Route;
use Joomla\CMS\Uri\Uri;

/**
 * "My Media": signed-in Joomla users are sent straight into their store account through SSO;
 * guests see the Joomla login with a return to this page.
 */
final class HtmlView extends BaseHtmlView
{
    public string $loginUrl = '';
    public string $problem = '';

    public function display($tpl = null): void
    {
        $app = Factory::getApplication();
        $params = $app->getParams();
        $user = $app->getIdentity();
        if ($user !== null && !$user->guest) {
            if (PluginHelper::isEnabled('system', 'mediamarketplace')) {
                $plugin = $app->bootPlugin('mediamarketplace', 'system');
                if (method_exists($plugin, 'ssoUrl')) {
                    $url = $plugin->ssoUrl((string) $params->get('return', '/account'));
                    if ($url !== null) {
                        $app->redirect($url);
                        return;
                    }
                }
            }
            $this->problem = 'COM_MEDIAMARKETPLACE_PLUGIN_DISABLED';
        } else {
            $this->loginUrl = Route::_('index.php?option=com_users&view=login&return=' . base64_encode(Uri::getInstance()->toString()));
        }
        parent::display($tpl);
    }
}
