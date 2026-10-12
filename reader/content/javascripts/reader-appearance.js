(function () {
  "use strict";
  const key = "reader-appearance";
  const defaults = { font: 18, width: 960, tone: "default", focus: false };
  let preferences = { ...defaults };
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "{}");
    if ([16, 18, 20].includes(saved.font)) preferences.font = saved.font;
    if ([800, 960, 1120].includes(saved.width)) preferences.width = saved.width;
    if (["default", "warm", "dark"].includes(saved.tone)) preferences.tone = saved.tone;
    preferences.focus = saved.focus === true;
  } catch (_) {}
  const baseScheme = window.__readerBaseScheme || document.body.dataset.mdColorScheme || "default";
  let toolbar;
  let panel;

  function apply() {
    document.body.style.setProperty("--reader-font-size", `${preferences.font}px`);
    document.body.style.setProperty("--reader-text-width", `${preferences.width}px`);
    document.body.dataset.readerTone = preferences.tone;
    document.body.classList.toggle("reader-focus-mode", preferences.focus);
    if (document.body.classList.contains("reader-research-page")) {
      document.body.dataset.mdColorScheme = preferences.tone === "dark" ? "slate"
        : preferences.tone === "warm" ? "default" : baseScheme;
    }
    const focus = toolbar?.querySelector("[data-reader-focus]");
    if (focus) {
      focus.textContent = preferences.focus ? "退出专注" : "专注";
      focus.setAttribute("aria-pressed", String(preferences.focus));
      focus.title = preferences.focus ? "恢复两侧导航" : "收起两侧栏，专注阅读";
    }
    panel?.querySelectorAll("[data-preference]").forEach(button => {
      button.setAttribute("aria-pressed", String(String(preferences[button.dataset.preference]) === button.dataset.value));
    });
    window.dispatchEvent(new Event("reader:appearance-change"));
  }

  function change(patch) {
    // Keep the same paragraph at the same viewport position when text reflows.
    const edge = toolbar ? toolbar.getBoundingClientRect().bottom + 12 : 100;
    const blocks = [...document.querySelectorAll(".md-content__inner [data-reader-block]")]
      .filter(el => !el.querySelector("[data-reader-block]"));
    const anchor = blocks.find(el => el.getBoundingClientRect().bottom > edge);
    const before = anchor?.getBoundingClientRect();
    const fraction = before ? Math.max(0, (edge - before.top) / Math.max(1, before.height)) : 0;
    Object.assign(preferences, patch);
    try { localStorage.setItem(key, JSON.stringify(preferences)); } catch (_) {}
    apply();
    if (anchor && before && window.scrollY > 0) {
      const after = anchor.getBoundingClientRect();
      window.scrollBy({ top: after.top + fraction * after.height - (before.top + fraction * before.height), behavior: "instant" });
    }
    window.dispatchEvent(new Event("scroll"));
  }

  function close(restoreFocus = false) {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    toolbar.querySelector("[data-reader-appearance]").setAttribute("aria-expanded", "false");
    if (restoreFocus) toolbar.querySelector("[data-reader-appearance]").focus({ preventScroll: true });
  }

  function mount(element) {
    toolbar = element;
    panel = document.createElement("div");
    panel.id = "reader-appearance-panel";
    panel.className = "reader-appearance-panel";
    panel.hidden = true;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "阅读设置");
    panel.innerHTML = '<div class="reader-appearance-heading"><strong>阅读设置</strong><button type="button" data-appearance-close aria-label="关闭阅读设置">×</button></div>';
    [
      ["font", "字号", [[16, "小"], [18, "标准"], [20, "大"]]],
      ["width", "正文宽度", [[800, "紧凑"], [960, "适中"], [1120, "宽松"]]],
      ["tone", "背景", [["default", "跟随主题"], ["warm", "暖纸"], ["dark", "深色"]]]
    ].forEach(([name, label, options]) => {
      const field = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = label;
      field.appendChild(legend);
      options.forEach(([value, text]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.preference = name;
        button.dataset.value = value;
        button.textContent = text;
        if (name === "font") button.title = `${value}px`;
        field.appendChild(button);
      });
      panel.appendChild(field);
    });
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "reader-appearance-reset";
    reset.textContent = "恢复默认";
    reset.addEventListener("click", () => change({ ...defaults }));
    panel.appendChild(reset);
    toolbar.appendChild(panel);
    panel.addEventListener("click", event => {
      const button = event.target.closest("[data-preference]");
      if (button) change({ [button.dataset.preference]: button.dataset.preference === "tone" ? button.dataset.value : Number(button.dataset.value) });
    });
    panel.querySelector("[data-appearance-close]").addEventListener("click", () => close(true));
    toolbar.querySelector("[data-reader-focus]").addEventListener("click", () => change({ focus: !preferences.focus }));
    toolbar.querySelector("[data-reader-appearance]").addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      toolbar.querySelector("[data-reader-appearance]").setAttribute("aria-expanded", String(!panel.hidden));
      const menu = toolbar.querySelector(".reader-section-tools__menu");
      if (menu) menu.hidden = true;
      toolbar.querySelector(".reader-section-tools__current").setAttribute("aria-expanded", "false");
      if (!panel.hidden) panel.querySelector("[data-appearance-close]").focus({ preventScroll: true });
    });
    apply();
  }

  document.addEventListener("click", event => {
    if (!panel?.contains(event.target) && !event.target.closest("[data-reader-appearance]")) close();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && panel && !panel.hidden) {
      event.preventDefault();
      close(true);
    }
  });
  window.ReaderAppearance = { mount };
  apply();
})();
