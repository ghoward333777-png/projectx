<?php

\defined('_JEXEC') or die;

use Joomla\CMS\Extension\Service\Provider\HelperFactory;
use Joomla\CMS\Extension\Service\Provider\Module;
use Joomla\CMS\Extension\Service\Provider\ModuleDispatcherFactory;
use Joomla\DI\Container;
use Joomla\DI\ServiceProviderInterface;

return new class () implements ServiceProviderInterface {
    public function register(Container $container): void
    {
        $container->registerServiceProvider(new ModuleDispatcherFactory('\\Joomla\\Module\\MmsEmbed'));
        $container->registerServiceProvider(new HelperFactory('\\Joomla\\Module\\MmsEmbed\\Site\\Helper'));
        $container->registerServiceProvider(new Module());
    }
};
