/*
 * Print-style probe, evaluated in the rendered document by probe_cdp.py. Every
 * value here is resolved from the cascade of the vendored carve-css and this
 * repository's themes, which is where the defects hid: a rule in one file
 * silently undoing a rule in the other.
 */
(() => {
  const cs = (el, pseudo) => getComputedStyle(el, pseudo || null);
  const one = (sel) => document.querySelector(sel);
  const body = cs(document.body);

  const startsPage = (el) => !!el && el.tagName === 'SECTION' && el.firstElementChild?.tagName === 'H2';
  const hrs = [...document.querySelectorAll('hr')].map((hr) => ({
    inEndnotes: !!hr.closest('[role="doc-endnotes"]'),
    beforePageBreak: startsPage(hr.nextElementSibling)
      || (!hr.nextElementSibling && startsPage(hr.parentElement?.nextElementSibling)),
    display: cs(hr).display,
  }));

  const ins = one('ins');
  const s = one('s');
  const abbr = one('abbr[title]');
  const nested = one('li > ul');
  const lastCell = one('tbody tr:last-child td');

  const single = one('figure:not(.carve-figure-group):not(.carve-figure-panel) > img');
  const fig = single.closest('figure').getBoundingClientRect();
  const img = single.getBoundingClientRect();

  const group = one('.carve-figure-group');
  const groupCaption = one('.carve-figure-group > figcaption');

  const quotedPre = one('blockquote pre');
  const titled = one('pre[title]');

  const panels = (sel, label) => [...document.querySelectorAll(sel)].map((p) => ({
    marginTop: cs(p).marginTop,
    labelPaddingLeft: cs(p.querySelector(label)).paddingLeft,
  }));

  return {
    hrs,
    ins: { boxShadow: cs(ins).boxShadow, line: cs(ins).textDecorationLine },
    strikeColor: cs(s).color,
    bodyColor: body.color,
    abbrAfter: { display: cs(abbr, '::after').display, content: cs(abbr, '::after').content },
    nestedMarginBottom: cs(nested).marginBottom,
    lastCellBorderBottom: cs(lastCell).borderBottomWidth,
    figure: { leftGap: img.left - fig.left, rightGap: fig.right - img.right },
    groupCaption: {
      width: groupCaption.getBoundingClientRect().width,
      groupWidth: group.getBoundingClientRect().width,
      align: cs(groupCaption).textAlign,
    },
    quotedPreStyle: cs(quotedPre).fontStyle,
    titleLabel: cs(titled, '::after').content,
    tabs: panels('.tabs-panel', '.tabs-label'),
    codeGroups: panels('.code-group-panel', '.code-group-label'),
    math: [...document.querySelectorAll('.math')].map((m) => ({
      katex: !!m.querySelector('.katex'),
      background: cs(m).backgroundColor,
      border: cs(m).borderTopWidth,
    })),
    bylineBreak: one('.doc-byline') ? cs(one('.doc-byline')).breakBefore : null,
  };
})()
