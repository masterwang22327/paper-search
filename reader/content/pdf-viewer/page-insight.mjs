function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function createPageInsight({ sourceId, api, onLayoutChange, onOpen, onLocate, onClearRegions }) {
  let regionVersion = 0;
  const panel = document.querySelector("#insight-panel");
  const resizer = document.querySelector("#insight-resizer");
  const workspace = document.querySelector("#workspace");
  const widthKey = "research-reader-insight-width";
  let preferredWidth = 0;
  let layoutFrame;
  try { preferredWidth = Number(localStorage.getItem(widthKey)) || 0; } catch { /* Optional preference. */ }

  function applyWidth(width) {
    if (window.innerWidth <= 560 || panel.hidden) return;
    const available = workspace.clientWidth - resizer.getBoundingClientRect().width;
    const minimum = Math.min(300, available * 0.38);
    const maximum = Math.min(available - Math.min(300, available * 0.42), workspace.clientWidth * 0.62 - 8);
    const clamped = Math.round(Math.max(minimum, Math.min(maximum, width)));
    panel.style.setProperty("--insight-panel-width", `${clamped}px`);
    resizer.setAttribute("aria-valuemin", String(Math.round(minimum)));
    resizer.setAttribute("aria-valuemax", String(Math.round(maximum)));
    resizer.setAttribute("aria-valuenow", String(clamped));
    if (!layoutFrame) layoutFrame = requestAnimationFrame(() => {
      layoutFrame = undefined;
      onLayoutChange();
    });
  }
  function saveWidth() {
    preferredWidth = Math.round(panel.getBoundingClientRect().width);
    try { localStorage.setItem(widthKey, String(preferredWidth)); } catch { /* Optional preference. */ }
  }
  function resetWidth() {
    preferredWidth = 0;
    try { localStorage.removeItem(widthKey); } catch { /* Optional preference. */ }
    panel.style.removeProperty("--insight-panel-width");
    applyWidth(panel.getBoundingClientRect().width);
  }
  resizer.addEventListener("pointerdown", event => {
    if (event.button !== 0 || window.innerWidth <= 560) return;
    event.preventDefault();
    resizer.setPointerCapture(event.pointerId);
    document.body.classList.add("translation-resizing");
    function move(next) { applyWidth(workspace.getBoundingClientRect().right - next.clientX); }
    function finish(next) {
      resizer.removeEventListener("pointermove", move);
      resizer.removeEventListener("pointerup", finish);
      resizer.removeEventListener("pointercancel", finish);
      resizer.removeEventListener("lostpointercapture", finish);
      if (resizer.hasPointerCapture(next.pointerId)) resizer.releasePointerCapture(next.pointerId);
      document.body.classList.remove("translation-resizing");
      saveWidth();
      onLayoutChange();
    }
    resizer.addEventListener("pointermove", move);
    resizer.addEventListener("pointerup", finish);
    resizer.addEventListener("pointercancel", finish);
    resizer.addEventListener("lostpointercapture", finish);
  });
  resizer.addEventListener("dblclick", resetWidth);
  resizer.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") resetWidth();
    else {
      applyWidth(panel.getBoundingClientRect().width + (event.key === "ArrowLeft" ? 24 : -24));
      saveWidth();
    }
  });
  new ResizeObserver(() => {
    if (!panel.hidden) applyWidth(preferredWidth || Math.min(480, Math.max(300, workspace.clientWidth * 0.4)));
  }).observe(workspace);
  const toggle = document.querySelector("#insight-toggle");
  const title = document.querySelector("#insight-title");
  const status = document.querySelector("#insight-status");
  const content = document.querySelector("#insight-content");
  const model = document.querySelector("#insight-model");
  const effort = document.querySelector("#insight-effort");
  const generate = document.querySelector("#generate-insight");
  const cache = new Map();
  const pending = new Map();
  let page = 1;
  let ready = false;
  let readController;
  let readVersion = 0;

  for (const option of document.querySelector("#retranslation-model").options) model.append(option.cloneNode(true));
  for (const option of document.querySelector("#retranslation-effort").options) effort.append(option.cloneNode(true));
  try {
    model.value = localStorage.getItem("research-reader-insight-model") || "gpt-5.6-terra";
    effort.value = localStorage.getItem("research-reader-insight-effort") || "medium";
  } catch { /* Storage may be unavailable in embedded or private browsing. */ }
  if (!model.value) model.value = "gpt-5.6-terra";

  function syncSettings() {
    const astra = model.value === "gpt-6-astra";
    for (const option of effort.options) {
      option.disabled = astra ? option.value === "ultra" : option.value === "low";
      option.hidden = option.disabled;
    }
    if (!effort.value || effort.selectedOptions[0].disabled) effort.value = "medium";
    try {
      localStorage.setItem("research-reader-insight-model", model.value);
      localStorage.setItem("research-reader-insight-effort", effort.value);
    } catch { /* Generation does not depend on saving preferences. */ }
  }
  syncSettings();

  function request() {
    return { source_id: sourceId, page, model: model.value, reasoning_effort: effort.value };
  }
  function keyFor(value = request()) {
    return JSON.stringify(value);
  }
  function updateControls() {
    toggle.disabled = !ready;
    generate.disabled = !ready || pending.has(keyFor());
    generate.textContent = pending.has(keyFor()) ? "正在解析…" : cache.get(keyFor()) ? "重新解析" : "解析本页知识";
    panel.setAttribute("aria-busy", String(pending.has(keyFor())));
  }
  function setStatus(text, error = false) {
    status.textContent = text;
    status.classList.toggle("is-error", error);
  }
  function section(heading, body, className = "") {
    const group = element("section", `insight-section ${className}`);
    group.append(element("h3", "", heading), body);
    return group;
  }
  function render(saved) {
    const version = ++regionVersion;
    onClearRegions();
    title.textContent = `PDF 第 ${page} 页 · 知识解析`;
    content.replaceChildren();
    if (saved) {
      const value = saved.content;
      const summary = element("div", "insight-summary");
      summary.append(element("p", "insight-main", value.main_point));
      content.append(summary);
      const details = element("div", "insight-details");
      if (value.context.length) {
        const body = element("div", "insight-prose");
        for (const paragraph of value.context) body.append(element("p", "", paragraph));
        details.append(section("理解前提", body));
      }
      for (const [index, analysis] of value.sections.entries()) {
        let article;
        function selectExplanation() {
          if (version !== regionVersion || panel.hidden || saved.page !== page) return;
          content.querySelectorAll(".insight-analysis").forEach(node => node.classList.toggle("is-selected", node === article));
          content.scrollTo({top: content.scrollTop + article.getBoundingClientRect().top - content.getBoundingClientRect().top - 12, behavior: "smooth"});
        }
        const body = element("div", "insight-prose");
        const anchor = element("button", "insight-source-anchor");
        anchor.type = "button";
        anchor.title = "框选对应原文";
        anchor.append(element("span", "insight-source-location", `p.${saved.page} · ${analysis.source_location}`));
        anchor.addEventListener("click", async () => {
          anchor.disabled = true;
          try {
            const matched = await onLocate(saved.page, analysis.source_quote, analysis.source_regions, selectExplanation, {
              id: index, isCurrent: () => version === regionVersion && !panel.hidden
            });
            if (saved.page !== page || !anchor.isConnected) return;
            anchor.title = matched === "region" ? "已框选原文区域（图像估计，文本校验）" : matched ? "已定位原文摘录" : "未找到可靠位置，请按本块位置说明回查";
            setStatus(anchor.title);
          } catch {
            if (saved.page === page && anchor.isConnected) setStatus("原文定位失败，可重试", true);
          } finally { anchor.disabled = false; }
        });
        body.append(element("p", "insight-original-meaning", analysis.original_meaning));
        body.append(anchor);
        for (const paragraph of analysis.paragraphs) body.append(element("p", "", paragraph));
        if (analysis.boundary) {
          body.append(element("h4", "insight-step-label", "需要辨清"));
          body.append(element("p", "", analysis.boundary));
        }
        const references = element("details", "insight-references");
        references.append(element("summary", "", "原文与出处"));
        references.append(element("q", "insight-source-quote", analysis.source_quote));
        references.append(element("small", "insight-evidence", analysis.evidence.join(" · ")));
        body.append(references);
        article = section(`${index + 1}. ${analysis.title}`, body, `insight-analysis is-${analysis.kind}`);
        details.append(article);
        // Draw all current-page anchors without moving either reading surface.
        onLocate(saved.page, analysis.source_quote, analysis.source_regions, selectExplanation, {
          id: index, center: false, isCurrent: () => version === regionVersion && !panel.hidden
        }).catch(() => {});
      }
      if (value.takeaways.length) {
        const list = element("ol", "insight-takeaways");
        for (const takeaway of value.takeaways) {
          list.append(element("li", "", takeaway));
        }
        details.append(section("综合启发", list));
      }
      if (value.caveats.length) {
        const list = element("ul", "");
        for (const caveat of value.caveats) list.append(element("li", "", caveat));
        details.append(section("证据边界", list, "insight-caveats"));
      }
      content.append(details);
      setStatus(`已保存 · ${saved.model} / ${saved.reasoning_effort}`);
    } else {
      setStatus("尚未生成");
    }
    if (pending.has(keyFor())) setStatus(saved ? "正在重新解析 · 保留上次结果" : "正在解析本页知识…");
    updateControls();
  }
  async function loadCached() {
    readController?.abort();
    const version = ++readVersion;
    const key = keyFor();
    render(cache.get(key));
    if (!ready || panel.hidden || pending.has(key)) return;
    const controller = new AbortController();
    readController = controller;
    const timeout = setTimeout(() => controller.abort(), 15000);
    if (!cache.get(key)) setStatus("正在读取解析…");
    try {
      const result = await api(`/api/pdf/page-insight?${new URLSearchParams(request())}`, { signal: controller.signal });
      if (version !== readVersion || key !== keyFor()) return;
      cache.set(key, result.insight);
      render(result.insight);
    } catch (error) {
      if (version !== readVersion || key !== keyFor() || panel.hidden) return;
      setStatus(error.name === "AbortError" ? "读取解析超时，可手动重试" : error.message, true);
    } finally {
      clearTimeout(timeout);
    }
  }
  async function generateCurrent() {
    const payload = request();
    const key = keyFor(payload);
    if (!ready || pending.has(key)) return;
    readController?.abort();
    ++readVersion;
    pending.set(key, true);
    render(cache.get(key));
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 930000);
    try {
      const result = await api("/api/pdf/page-insight", {
        method: "POST",
        body: JSON.stringify({ ...payload, force: Boolean(cache.get(key)) }),
        signal: controller.signal
      });
      cache.set(key, result.insight);
      pending.delete(key);
      if (key === keyFor()) render(result.insight);
    } catch (error) {
      pending.delete(key);
      if (key === keyFor()) {
        render(cache.get(key));
        const message = error.name === "AbortError" ? "等待解析超时，服务端可能仍在生成；稍后重新打开查看" : error.message;
        setStatus(`${message}${cache.get(key) ? " · 保留上次结果" : ""}`, true);
      }
    } finally {
      clearTimeout(timeout);
      updateControls();
    }
  }
  function setOpen(open) {
    if (open) onOpen();
    panel.hidden = !open;
    resizer.hidden = !open;
    if (open) applyWidth(preferredWidth || Math.min(480, Math.max(300, workspace.clientWidth * 0.4)));
    document.querySelector("#workspace").classList.toggle("has-insight", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.classList.toggle("is-active", open);
    toggle.title = open ? "收起知识解析" : "打开知识解析";
    if (open) loadCached();
    else {
      ++regionVersion;
      onClearRegions();
      readController?.abort();
      ++readVersion;
    }
    onLayoutChange();
  }
  toggle.addEventListener("click", () => setOpen(panel.hidden));
  document.querySelector("#close-insight").addEventListener("click", () => setOpen(false));
  generate.addEventListener("click", generateCurrent);
  for (const select of [model, effort]) select.addEventListener("change", () => {
    syncSettings();
    loadCached();
  });
  return {
    close() { if (!panel.hidden) setOpen(false); },
    setReady(value) { ready = value; updateControls(); },
    setPage(value) {
      if (page === value) return;
      page = value;
      content.scrollTop = 0;
      loadCached();
    }
  };
}
