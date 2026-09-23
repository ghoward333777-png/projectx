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
        if (str_starts_with($task, 'vm_')) {
            $this->checkToken('get');
            $this->virtuemartTask($task, $plugin);
            $this->setRedirect('index.php?option=com_mediamarketplace&view=virtuemart');
            return $this;
        }
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

    /** Sell-through VirtueMart actions from the VirtueMart page. */
    private function virtuemartTask(string $task, object $plugin): void
    {
        $app = Factory::getApplication();
        $vm = method_exists($plugin, 'virtuemart') ? $plugin->virtuemart() : null;
        if ($vm === null) {
            $app->enqueueMessage(Text::_('COM_MEDIAMARKETPLACE_VM_NOT_INSTALLED'), 'warning');
            return;
        }
        try {
            switch ($task) {
                case 'vm_import':
                case 'vm_refresh':
                    [$c, $u, $l, $errors] = $vm->importProducts($task === 'vm_refresh');
                    $app->enqueueMessage(Text::sprintf('COM_MEDIAMARKETPLACE_VM_IMPORTED', $c, $u, $l), 'message');
                    foreach ($errors as $e) {
                        $app->enqueueMessage($e, 'warning');
                    }
                    break;
                case 'vm_sync':
                    $n = $vm->reconcile(30);
                    $app->enqueueMessage(Text::sprintf('COM_MEDIAMARKETPLACE_VM_SYNCED', $n), 'message');
                    break;
                case 'vm_mode_virtuemart':
                case 'vm_mode_native':
                case 'vm_unlinked_hide':
                case 'vm_unlinked_native':
                    $status = $vm->status() ?? [];
                    $mode = $task === 'vm_mode_virtuemart' ? 'virtuemart' : ($task === 'vm_mode_native' ? 'native' : (string) ($status['mode'] ?? 'native'));
                    $unlinked = $task === 'vm_unlinked_hide' ? 'hide' : ($task === 'vm_unlinked_native' ? 'native' : (string) ($status['unlinked'] ?? 'native'));
                    $r = $vm->setMode($mode, $unlinked);
                    $app->enqueueMessage($r['ok'] ? Text::_('COM_MEDIAMARKETPLACE_VM_SAVED') : $r['error'], $r['ok'] ? 'message' : 'error');
                    break;
            }
        } catch (\Throwable $e) {
            $app->enqueueMessage($e->getMessage(), 'error');
        }
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
