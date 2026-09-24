<?php
declare(strict_types=1);

namespace WatchRoom\Module\WatchRoom\Site\Dispatcher;

defined('_JEXEC') or die;

use Joomla\CMS\Dispatcher\AbstractModuleDispatcher;
use Joomla\CMS\Helper\HelperFactoryAwareInterface;
use Joomla\CMS\Helper\HelperFactoryAwareTrait;

final class Dispatcher extends AbstractModuleDispatcher implements HelperFactoryAwareInterface
{
    use HelperFactoryAwareTrait;

    protected function getLayoutData(): array
    {
        $data = parent::getLayoutData();
        $data['embed'] = $this->getHelperFactory()->getHelper('WatchRoomHelper')->getEmbed($data['params'], $this->getApplication());
        return $data;
    }
}
