/* MediaMarketplace Studio — block editor registration (no build step; plain wp.* globals). */
(function (wp) {
  'use strict';
  if (!wp || !wp.blocks || !wp.element) {
    return;
  }
  var el = wp.element.createElement;
  var registerBlockType = wp.blocks.registerBlockType;
  var InspectorControls = (wp.blockEditor || wp.editor).InspectorControls;
  var useBlockProps = (wp.blockEditor || wp.editor).useBlockProps;
  var PanelBody = wp.components.PanelBody;
  var SelectControl = wp.components.SelectControl;
  var TextControl = wp.components.TextControl;
  var ServerSideRender = wp.serverSideRender;
  var __ = wp.i18n.__;

  function placeholder(title, lines) {
    var children = [el('strong', { key: 't' }, title)];
    lines.forEach(function (l, i) {
      children.push(el('div', { key: 'l' + i, className: 'mms-block-line' }, l));
    });
    return el('div', { className: 'mms-block-placeholder' }, children);
  }

  function preview(block, attributes, title, lines) {
    // The real widget is rendered by the bundled server; the editor shows the summary
    // and, when ServerSideRender is available, the same markup the page will carry.
    if (ServerSideRender) {
      return el('div', {}, [
        el('div', { key: 'p', className: 'mms-block-caption' }, title),
        el(ServerSideRender, { key: 'r', block: block, attributes: attributes })
      ]);
    }
    return placeholder(title, lines);
  }

  registerBlockType('mms/showcase', {
    edit: function (props) {
      var a = props.attributes;
      var blockProps = useBlockProps ? useBlockProps() : {};
      return el('div', blockProps, [
        el(InspectorControls, { key: 'i' },
          el(PanelBody, { title: __('Showcase', 'mediamarketplace-studio') },
            el(SelectControl, {
              label: __('View', 'mediamarketplace-studio'),
              value: a.view,
              options: [
                { label: __('Grid', 'mediamarketplace-studio'), value: 'grid' },
                { label: __('List', 'mediamarketplace-studio'), value: 'list' }
              ],
              onChange: function (v) { props.setAttributes({ view: v }); }
            }),
            el(TextControl, {
              label: __('Category slug (optional)', 'mediamarketplace-studio'),
              value: a.category,
              onChange: function (v) { props.setAttributes({ category: v }); }
            })
          )
        ),
        el('div', { key: 'c' }, preview('mms/showcase', a, __('MediaMarketplace showcase', 'mediamarketplace-studio'), [
          __('View: ', 'mediamarketplace-studio') + a.view,
          a.category ? __('Category: ', 'mediamarketplace-studio') + a.category : __('All categories', 'mediamarketplace-studio')
        ]))
      ]);
    },
    save: function () { return null; }
  });

  registerBlockType('mms/embed', {
    edit: function (props) {
      var a = props.attributes;
      var blockProps = useBlockProps ? useBlockProps() : {};
      return el('div', blockProps, [
        el(InspectorControls, { key: 'i' },
          el(PanelBody, { title: __('Embed', 'mediamarketplace-studio') },
            el(SelectControl, {
              label: __('What to embed', 'mediamarketplace-studio'),
              value: a.kind,
              options: [
                { label: __('Widget (from the builder)', 'mediamarketplace-studio'), value: 'widget' },
                { label: __('Product page', 'mediamarketplace-studio'), value: 'product' },
                { label: __('Player', 'mediamarketplace-studio'), value: 'player' },
                { label: __('Showcase', 'mediamarketplace-studio'), value: 'showcase' }
              ],
              onChange: function (v) { props.setAttributes({ kind: v }); }
            }),
            el(TextControl, {
              label: __('Widget ID or product slug', 'mediamarketplace-studio'),
              help: __('Copy it from Widgets → Place (WordPress) in the store admin.', 'mediamarketplace-studio'),
              value: a.id,
              onChange: function (v) { props.setAttributes({ id: v }); }
            }),
            el(TextControl, {
              label: __('View (optional)', 'mediamarketplace-studio'),
              value: a.view,
              onChange: function (v) { props.setAttributes({ view: v }); }
            })
          )
        ),
        el('div', { key: 'c' }, a.id || a.kind === 'showcase'
          ? preview('mms/embed', a, __('MediaMarketplace ', 'mediamarketplace-studio') + a.kind, [a.id])
          : placeholder(__('MediaMarketplace embed', 'mediamarketplace-studio'), [__('Enter a widget ID or product slug in the block settings.', 'mediamarketplace-studio')]))
      ]);
    },
    save: function () { return null; }
  });

  registerBlockType('mms/signin', {
    edit: function (props) {
      var a = props.attributes;
      var blockProps = useBlockProps ? useBlockProps() : {};
      return el('div', blockProps, [
        el(InspectorControls, { key: 'i' },
          el(PanelBody, { title: __('My Media link', 'mediamarketplace-studio') },
            el(TextControl, {
              label: __('Link text', 'mediamarketplace-studio'),
              value: a.label,
              onChange: function (v) { props.setAttributes({ label: v }); }
            }),
            el(TextControl, {
              label: __('Store page to open', 'mediamarketplace-studio'),
              value: a['return'],
              onChange: function (v) { props.setAttributes({ 'return': v }); }
            })
          )
        ),
        el('a', { key: 'c', className: 'mms-signin', href: '#', onClick: function (e) { e.preventDefault(); } }, a.label || __('My media', 'mediamarketplace-studio'))
      ]);
    },
    save: function () { return null; }
  });
})(window.wp);
