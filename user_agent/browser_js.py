JS_FOCUS_INIT = r"""
() => {
  try {
    window.focus();
    if (document.body) {
      document.body.setAttribute("tabindex", "-1");
      document.body.focus();
    }
  } catch (_) {}
  return true;
}
"""

JS_TAB_FALLBACK = r"""
() => {
  const isVisible = (el) => {
    if (!(el instanceof Element)) return false;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || cs.opacity === "0") return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };

  const isDisabled = (el) => {
    if (!(el instanceof Element)) return true;
    if (el.hasAttribute("disabled")) return true;
    if ((el.getAttribute("aria-disabled") || "").toLowerCase() === "true") return true;
    return false;
  };

  const isTabbable = (el) => {
    if (!(el instanceof HTMLElement)) return false;
    if (isDisabled(el)) return false;
    if (!isVisible(el)) return false;
    if (el.tabIndex < 0) return false;

    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute("role") || "").toLowerCase();

    if (tag === "a") return !!el.getAttribute("href");
    if (["button", "input", "select", "textarea"].includes(tag)) return true;
    if (el.tabIndex >= 0) return true;
    if (["button","link","textbox","checkbox","radio","switch","tab","menuitem"].includes(role)) return true;
    return false;
  };

  const all = Array.from(document.querySelectorAll("*")).filter(isTabbable);
  if (!all.length) return { ok:false, reason:"no_tabbable" };

  const positive = all.filter(e => e.tabIndex > 0).sort((a,b) => a.tabIndex - b.tabIndex);
  const zero = all.filter(e => e.tabIndex === 0);
  const ordered = [...positive, ...zero];

  const ae = document.activeElement;
  let idx = ordered.indexOf(ae);
  if (idx < 0) idx = -1;

  const next = ordered[(idx + 1) % ordered.length];
  try { next.focus({preventScroll:false}); } catch (_) { try { next.focus(); } catch(__){} }

  return { ok:true, count: ordered.length };
}
"""

JS_GET_ACTIVE_INFO = r"""
(step) => {
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim();

  const cssPath = (node) => {
    if (!(node instanceof Element)) return "";
    const parts = [];
    let cur = node;
    while (cur && cur.nodeType === 1 && parts.length < 10) {
      let sel = cur.tagName.toLowerCase();
      if (cur.id) {
        sel += "#" + CSS.escape(cur.id);
        parts.unshift(sel);
        break;
      } else {
        let i = 1;
        let sib = cur;
        while ((sib = sib.previousElementSibling)) {
          if (sib.tagName === cur.tagName) i++;
        }
        sel += `:nth-of-type(${i})`;
      }
      parts.unshift(sel);
      cur = cur.parentElement;
    }
    return parts.join(" > ");
  };

  const textById = (id) => {
    try {
      const el = document.getElementById(id);
      return norm(el ? (el.innerText || el.textContent || "") : "");
    } catch (_) {
      return "";
    }
  };

  const getAccName = (el) => {
    if (!(el instanceof Element)) return "";

    const ariaLabel = norm(el.getAttribute("aria-label") || "");
    if (ariaLabel) return ariaLabel;

    const labelledby = norm(el.getAttribute("aria-labelledby") || "");
    if (labelledby) {
      const txt = labelledby.split(/\s+/).map(textById).filter(Boolean).join(" ");
      if (txt) return norm(txt);
    }

    const alt = norm(el.getAttribute("alt") || "");
    if (alt) return alt;

    if (el.id) {
      try {
        const byFor = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        const t = norm(byFor ? (byFor.innerText || byFor.textContent || "") : "");
        if (t) return t;
      } catch (_) {}
    }

    try {
      const wrapLabel = el.closest("label");
      const t = norm(wrapLabel ? (wrapLabel.innerText || wrapLabel.textContent || "") : "");
      if (t) return t;
    } catch (_) {}

    const title = norm(el.getAttribute("title") || "");
    if (title) return title;

    const placeholder = norm(el.getAttribute("placeholder") || "");
    if (placeholder) return placeholder;

    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      const v = norm(el.value || "");
      if (v) return v;
    }

    const txt = norm(el.innerText || el.textContent || "");
    if (txt) return txt;

    return "";
  };

  const ae = document.activeElement;
  if (!ae || ae === document.body || ae === document.documentElement) {
    return { ok:false, step, reason:"no_active_focus" };
  }

  const tag = (ae.tagName || "").toLowerCase();
  const role = ae.getAttribute ? (ae.getAttribute("role") || "") : "";
  const type = ae.getAttribute ? (ae.getAttribute("type") || "") : "";
  const href = ae.getAttribute ? (ae.getAttribute("href") || "") : "";
  const tabIndex = typeof ae.tabIndex === "number" ? ae.tabIndex : -1;
  const disabled = !!(
    ae.hasAttribute &&
    (ae.hasAttribute("disabled") || (ae.getAttribute("aria-disabled") || "").toLowerCase() === "true")
  );

  const interactive = (!disabled) && (
    (tag === "a" && !!href) ||
    ["button","input","select","textarea","summary"].includes(tag) ||
    tabIndex >= 0 ||
    ["button","link","textbox","checkbox","radio","switch","tab","menuitem","combobox"].includes((role || "").toLowerCase())
  );

  // 포커스 표시(빨간 박스)
  const r = ae.getBoundingClientRect();
  let box = document.getElementById("__mcp_focus_box__");
  if (!box) {
    box = document.createElement("div");
    box.id = "__mcp_focus_box__";
    box.style.position = "fixed";
    box.style.zIndex = "2147483647";
    box.style.border = "3px solid #ff2d2d";
    box.style.pointerEvents = "none";
    box.style.boxSizing = "border-box";
    document.body.appendChild(box);
  }

  box.style.left = `${Math.max(0, r.left - 2)}px`;
  box.style.top = `${Math.max(0, r.top - 2)}px`;
  box.style.width = `${Math.max(2, r.width + 4)}px`;
  box.style.height = `${Math.max(2, r.height + 4)}px`;

  const html = ae.outerHTML || "";
  const snippet = html.length > 2000 ? html.slice(0, 2000) + "…" : html;

  const vv = window.visualViewport;
  const viewportW = vv ? vv.width : window.innerWidth;
  const viewportH = vv ? vv.height : window.innerHeight;

  return {
    ok: true,
    step,
    selector: cssPath(ae),
    tag, role, type,
    interactive,
    accName: getAccName(ae),
    text: norm(ae.innerText || ae.textContent || ""),
    bbox: { x:r.x, y:r.y, w:r.width, h:r.height },
    dpr: window.devicePixelRatio || 1,
    scrollX: window.scrollX || 0,
    scrollY: window.scrollY || 0,
    viewportW,
    viewportH,
    url: location.href,
    htmlSnippet: snippet
  };
}
"""
