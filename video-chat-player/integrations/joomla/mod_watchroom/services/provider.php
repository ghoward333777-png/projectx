<?php
declare(strict_types=1);

defined('_JEXEC') or die;

use Joomla\CMS\Extension\Service\Provider\HelperFactory;
use Joomla\CMS\Extension\Service\Provider\Module;
use Joomla\CMS\Extension\Service\Provider\ModuleDispatcherFactory;
use Joomla\DI\Container;
use Joomla\DI\ServiceProviderInterface;

return new class () implements ServiceProviderInterface {
    public function register(Container $container): void
    {
        $container->registerServiceProvider(new ModuleDispatcherFactory('\\WatchRoom\\Module\\WatchRoom'));
        $container->registerServiceProvider(new HelperFactory('\\WatchRoom\\Module\\WatchRoom\\Site\\Helper'));
        $container->registerServiceProvider(new Module());
    }
};
