/*
 * Panel visibility probe, evaluated in the rendered document by probe_cdp.py.
 *
 * The failure this exists to catch is a panel that is styled out of existence:
 * `display: none` with no rule reaching it, a zero height, or a cover drawn
 * over it. None of the three is visible in the stylesheet text, because all
 * three are resolved values. Returns one record per panel plus a label
 * comparison, and the shell gate decides.
 */
(() => {
  const px = (v) => parseFloat(v) || 0;

  // A panel's own text, with its label's text removed, so a visible label over
  // a hidden body cannot read as a visible panel.
  const bodyText = (panel, labelSel) => {
    const label = panel.querySelector(labelSel);
    const whole = panel.innerText || "";
    const head = label ? label.innerText || "" : "";
    return whole.startsWith(head) ? whole.slice(head.length).trim() : whole.trim();
  };

  const chainHidden = (el) => {
    // `display: none` anywhere up the tree takes the panel with it, and the
    // panel's own computed style still reports `block`.
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.display === "none" || s.visibility === "hidden" || px(s.opacity) === 0) {
        return n === el ? "self" : (n.className || n.tagName);
      }
    }
    return null;
  };

  const occluder = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return "zero-rect";
    const x = Math.min(r.left + r.width / 2, window.innerWidth - 2);
    const y = Math.min(r.top + Math.min(r.height / 2, 8), window.innerHeight - 2);
    if (x < 0 || y < 0) return null; // scrolled out of the viewport, not covered
    const hit = document.elementFromPoint(x, y);
    if (!hit) return "no-hit";
    return el.contains(hit) || hit.contains(el) ? null : (hit.className || hit.tagName);
  };

  const describe = (panel, labelSel) => {
    const s = getComputedStyle(panel);
    const r = panel.getBoundingClientRect();
    const label = panel.querySelector(labelSel);
    const ls = label ? getComputedStyle(label) : null;
    return {
      cls: panel.className,
      display: s.display,
      visibility: s.visibility,
      opacity: s.opacity,
      height: Math.round(r.height),
      hiddenAttr: panel.hasAttribute("hidden"),
      hiddenBy: chainHidden(panel),
      occludedBy: occluder(panel),
      body: bodyText(panel, labelSel),
      // `innerText` falls back to `textContent` on a `display: none` element,
      // so the text of a hidden panel still reads as present. Whether it
      // RENDERED is a separate question, and only the page's own visible text
      // answers it.
      bodyRendered: (document.body.innerText || "").includes(
        bodyText(panel, labelSel).slice(0, 24)),
      visible: panel.checkVisibility
        ? panel.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
        : null,
      label: label ? (label.innerText || "").trim() : null,
      labelTag: label ? label.tagName : null,
      // Distinguishable means it does not render as another line of body text.
      labelWeight: ls ? ls.fontWeight : null,
      labelColor: ls ? ls.color : null,
      labelSize: ls ? ls.fontSize : null,
      labelDisplay: ls ? ls.display : null,
      bodyWeight: s.fontWeight,
      bodyColor: s.color,
      bodySize: s.fontSize,
    };
  };

  const tabs = [...document.querySelectorAll(".tabs-panel")].map((p) =>
    describe(p, ".tabs-label"));
  const groups = [...document.querySelectorAll(".code-group-panel")].map((p) =>
    describe(p, ".code-group-label"));

  // The interactive shape, when the document carries one: exactly one panel of
  // each set should be showing, and the checked control should look different
  // from an unchecked one.
  const controls = [...document.querySelectorAll(".tabs-radio, .code-group-radio")]
    .map((radio) => {
      const label = document.querySelector(`label[for="${radio.id}"]`);
      const ls = label ? getComputedStyle(label) : null;
      return {
        id: radio.id,
        checked: radio.checked,
        labelColor: ls ? ls.color : null,
        labelBorderColor: ls ? ls.borderBlockEndColor : null,
        labelWeight: ls ? ls.fontWeight : null,
      };
    });

  return {
    url: location.href,
    tabsPanels: tabs,
    codeGroupPanels: groups,
    controls,
    // Every marker the fixture plants, and whether the page shows it.
    markers: ["PANELBODYALPHA", "PANELBODYBETA", "PANELBODYGAMMA", "PANELBODYDELTA"]
      .map((m) => ({ marker: m, inRenderedText: (document.body.innerText || "").includes(m) })),
  };
})();
