<?php

namespace Joomla\Component\Mediamarketplace\Site\View\Widget;

\defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\MVC\View\HtmlView as BaseHtmlView;
use Joomla\Component\Mediamarketplace\Site\View\Showcase\HtmlView as ShowcaseView;

/** A widget built in the store's widget builder (or a product page / player), placed as a menu item. */
final class HtmlView extends BaseHtmlView
{
    public string $html = '';
    public string $problem = '';

    public function display($tpl = null): void
    {
        $params = Factory::getApplication()->getParams();
        $id = trim((string) $params->get('widget_id', ''));
        $kind = (string) $params->get('kind', 'widget');
        if ($id === '') {
            $this->problem = 'COM_MEDIAMARKETPLACE_WIDGET_ID_MISSING';
        } else {
            $this->html = ShowcaseView::embed($kind, ['id' => $id, 'view' => (string) $params->get('view', '')], $this->problem);
        }
        $title = (string) $params->get('page_title', '');
        if ($title !== '') {
            $this->getDocument()->setTitle($title);
        }
        parent::display($tpl);
    }
}
