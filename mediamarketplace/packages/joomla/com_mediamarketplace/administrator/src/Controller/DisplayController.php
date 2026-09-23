<?php

namespace Joomla\Component\Mediamarketplace\Administrator\Controller;

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\Language\Text;
use Joomla\CMS\MVC\Controller\BaseController;
use Joomla\CMS\Plugin\PluginHelper;

/** Default view signs the administrator into the bundled server; "status" shows the process status. */
final class DisplayController extends BaseController
{
    protected $default_view = 'status';

    public function display($cachable = false, $urlparams = [])
    {
        $app = Factory::getApplication();
        $plugin = $this->plugin();
        if ($plugin === null) {
            $app->enqueueMessage(Text::_('COM_MEDIAMARKETPLACE_PLUGIN_DISABLED'), 'error');
            return parent::display($cachable, $urlparams);
        }
        $view = $this->input->get('view', 'open');
        $task = $this->input->get('task', '');
        if ($task === 'restart' || $task === 'stop') {
            $this->checkToken('get');
            try {
                $rt = $plugin->runtime();
                if ($task === 'restart') {
                    $rt->ensureInstalled();
                    $rt->restart();
                } else {
                    $rt->stop();
                }
            } catch (\Throwable $e) {
                $app->enqueueMessage($e->getMessage(), 'error');
            }
            $this->setRedirect('index.php?option=com_mediamarketplace&view=status');
            return $this;
        }
        if ($view === 'open') {
            try {
                $plugin->runtime()->ensureRunning();
            } catch (\Throwable $e) {
                $app->enqueueMessage($e->getMessage(), 'error');
                $this->setRedirect('index.php?option=com_mediamarketplace&view=status');
                return $this;
            }
            $url = $plugin->ssoUrl('/admin', true);
            if ($url !== null) {
                $app->redirect($url);
            }
        }
        $this->input->set('view', 'status');
        return parent::display($cachable, $urlparams);
    }

    private function plugin(): ?object
    {
        if (!PluginHelper::isEnabled('system', 'mediamarketplace')) {
            return null;
        }
        $plugin = Factory::getApplication()->bootPlugin('mediamarketplace', 'system');
        return method_exists($plugin, 'runtime') ? $plugin : null;
    }
}
