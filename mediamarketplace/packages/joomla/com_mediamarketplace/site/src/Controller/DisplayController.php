<?php

namespace Joomla\Component\Mediamarketplace\Site\Controller;

\defined('_JEXEC') or die;

use Joomla\CMS\MVC\Controller\BaseController;

/** Site side: menu item types Showcase, Widget and My Media. */
final class DisplayController extends BaseController
{
    protected $default_view = 'showcase';

    public function display($cachable = false, $urlparams = [])
    {
        $view = $this->input->get('view', $this->default_view);
        if (!\in_array($view, ['showcase', 'widget', 'account'], true)) {
            $this->input->set('view', $this->default_view);
        }
        return parent::display($cachable, $urlparams);
    }
}
