/*
 * Code listing layout probe, evaluated in the rendered document by probe_cdp.py.
 * Alignment and break hints are resolved values, so only a browser can
 * report them.
 */
(() => {
  const pres = [...document.querySelectorAll("pre")];
  return {
    listings: pres.map((pre) => {
      const code = pre.querySelector("code") || pre;
      const prev = pre.closest("figure")?.previousElementSibling ?? pre.previousElementSibling;
      return {
        inFigure: !!pre.closest("figure"),
        preAlign: getComputedStyle(pre).textAlign,
        codeAlign: getComputedStyle(code).textAlign,
        leadIn: prev && prev.tagName === "P" ? prev.innerText.trim() : null,
        leadInBreakAfter: prev && prev.tagName === "P" ? getComputedStyle(prev).breakAfter : null,
      };
    }),
  };
})()
