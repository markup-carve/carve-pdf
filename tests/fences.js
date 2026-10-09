/*
 * Fence probe, evaluated in the rendered document by probe_cdp.py: the label
 * is generated content and diff rows are painted boxes, so only a browser can
 * say whether they are drawn, clear of the code and full width.
 */
(() => {
  const diffRows = [...document.querySelectorAll("pre.has-diff .line.diff")].map((row) => {
    const pre = row.closest("pre");
    const border = parseFloat(getComputedStyle(pre).borderLeftWidth) + parseFloat(getComputedStyle(pre).borderRightWidth);
    return {
      kind: row.classList.contains("add") ? "add" : "remove",
      background: getComputedStyle(row).backgroundColor,
      width: row.getBoundingClientRect().width,
      preWidth: pre.getBoundingClientRect().width - border,
    };
  });
  const fences = [...document.querySelectorAll("pre")].map((pre) => {
    const label = getComputedStyle(pre, "::before");
    const code = pre.querySelector("code") || pre;
    const range = document.createRange();
    range.setStart(code, 0);
    range.setEnd(code, Math.min(1, code.childNodes.length));
    const firstLine = range.getClientRects()[0];
    const box = pre.getBoundingClientRect();
    // ::before has no DOM rect; its top and line-height come from the style.
    const labelBottom = box.top + parseFloat(label.top) + parseFloat(label.lineHeight || label.fontSize);
    return {
      lang: pre.dataset.lang ?? null,
      content: label.content,
      labelBottom,
      firstLineTop: firstLine ? firstLine.top : null,
    };
  });
  return { fences, diffRows };
})()
