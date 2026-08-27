(function () {
  "use strict";

  let panel;
  let frame;
  let title;
  let meta;
  let externalLink;
  let activeLink;
  let pendingLink;
  let toggle;
  const widthStorageKey = "research-reader-evidence-width-v2";
  const defaultWidth = "min(44vw, 46rem)";

  function widthBounds() {
    const viewportWidth = window.innerWidth;
    // Browser zoom reduces the CSS viewport. Ratio-based bounds keep the
    // outer divider movable instead of collapsing min/max to the same value.
    const minimumPanel = Math.min(360, viewportWidth * 0.28);
    const minimumReadingArea = Math.min(560, viewportWidth * 0.28);
    return {
      min: minimumPanel,
      max: Math.max(minimumPanel, viewportWidth - minimumReadingArea)
    };
  }

  function applyPanelWidth(width, persist) {
    const bounds = widthBounds();
    const clamped = Math.round(Math.min(bounds.max, Math.max(bounds.min, width)));
    document.body.style.setProperty("--evidence-panel-width", clamped + "px");
    const resizer = panel && panel.querySelector(".evidence-panel__resizer");
    if (resizer) {
      resizer.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
      resizer.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
      resizer.setAttribute("aria-valuenow", String(clamped));
    }
    if (persist) localStorage.setItem(widthStorageKey, String(clamped));
  }

  function restorePanelWidth() {
    const saved = Number(localStorage.getItem(widthStorageKey));
    if (Number.isFinite(saved) && saved > 0) applyPanelWidth(saved, false);
  }

  function resetPanelWidth() {
    localStorage.removeItem(widthStorageKey);
    document.body.style.setProperty("--evidence-panel-width", defaultWidth);
  }

  function beginResize(event) {
    event.preventDefault();
    const resizer = event.currentTarget;
    resizer.setPointerCapture(event.pointerId);
    document.body.classList.add("evidence-panel-resizing");

    function move(moveEvent) {
      applyPanelWidth(window.innerWidth - moveEvent.clientX, false);
    }

    function finish(upEvent) {
      if (resizer.hasPointerCapture(upEvent.pointerId)) {
        resizer.releasePointerCapture(upEvent.pointerId);
      }
      document.body.classList.remove("evidence-panel-resizing");
      const width = parseFloat(getComputedStyle(document.body).getPropertyValue("--evidence-panel-width"));
      if (Number.isFinite(width)) localStorage.setItem(widthStorageKey, String(Math.round(width)));
      resizer.removeEventListener("pointermove", move);
      resizer.removeEventListener("pointerup", finish);
      resizer.removeEventListener("pointercancel", finish);
    }

    resizer.addEventListener("pointermove", move);
    resizer.addEventListener("pointerup", finish);
    resizer.addEventListener("pointercancel", finish);
  }

  function ensureToolDock() {
    const sidebar = document.querySelector(".md-sidebar--secondary");
    if (!sidebar) return null;
    let dock = sidebar.querySelector(":scope > .reader-tool-dock");
    if (!dock) {
      dock = document.createElement("div");
      dock.className = "reader-tool-dock";
      dock.setAttribute("aria-label", "阅读工具");
      sidebar.classList.add("reader-tools-docked");
      const scrollwrap = sidebar.querySelector(":scope > .md-sidebar__scrollwrap");
      sidebar.insertBefore(dock, scrollwrap || sidebar.firstChild);
    }
    return dock;
  }

  function placeToggle() {
    if (!toggle) return;
    const topline = document.querySelector(".paper-reading-card__topline");
    const hasEvidenceLayout = Boolean(topline || document.querySelector("a.evidence-link[data-pdf]"));
    const dock = hasEvidenceLayout ? ensureToolDock() : null;
    if (dock) dock.appendChild(toggle);
    else document.body.appendChild(toggle);
    window.dispatchEvent(new CustomEvent("reader:tool-dock-change", {
      detail: { dock }
    }));
  }

  function handleToggleResize() {
    placeToggle();
    const saved = Number(localStorage.getItem(widthStorageKey));
    if (Number.isFinite(saved) && saved > 0) applyPanelWidth(saved, false);
  }

  function buildPanel() {
    if (panel) {
      placeToggle();
      return;
    }
    panel = document.createElement("aside");
    panel.className = "evidence-panel";
    panel.setAttribute("aria-label", "论文 PDF 证据面板");
    panel.innerHTML = [
      '<button class="evidence-panel__resizer" type="button" role="separator" aria-label="拖动调整正文和论文阅读面板宽度；双击恢复默认" aria-orientation="vertical"></button>',
      '<div class="evidence-panel__header">',
      '  <div class="evidence-panel__identity">',
      '    <div class="evidence-panel__title">论文 PDF</div>',
      '    <div class="evidence-panel__meta"></div>',
      "  </div>",
      '  <a class="evidence-panel__button evidence-panel__external" target="_blank" rel="noopener" title="在新窗口打开">新窗口</a>',
      '  <button class="evidence-panel__button evidence-panel__close" type="button" title="返回正文阅读模式">阅读模式</button>',
      "</div>",
      '<nav class="evidence-panel__tabs" aria-label="阅读工具">',
      '  <button class="evidence-panel__tab is-active" type="button" data-reader-tab="pdf">论文 PDF</button>',
      '  <button class="evidence-panel__tab" type="button" data-reader-tab="assistant">知识问答</button>',
      '  <button class="evidence-panel__tab" type="button" data-reader-tab="faq">FAQ</button>',
      "</nav>",
      '<div class="evidence-panel__pane is-active" data-reader-pane="pdf">',
      '  <iframe class="evidence-panel__frame" title="固定论文 PDF" loading="lazy"></iframe>',
      "</div>",
      '<div class="evidence-panel__pane" data-reader-pane="assistant"></div>',
      '<div class="evidence-panel__pane" data-reader-pane="faq"></div>'
    ].join("");
    document.body.appendChild(panel);
    frame = panel.querySelector(".evidence-panel__frame");
    title = panel.querySelector(".evidence-panel__title");
    meta = panel.querySelector(".evidence-panel__meta");
    externalLink = panel.querySelector(".evidence-panel__external");
    panel.querySelector(".evidence-panel__close").addEventListener("click", closePanel);
    const resizer = panel.querySelector(".evidence-panel__resizer");
    resizer.addEventListener("pointerdown", beginResize);
    resizer.addEventListener("dblclick", resetPanelWidth);
    restorePanelWidth();

    toggle = document.createElement("button");
    toggle.className = "evidence-panel-toggle";
    toggle.type = "button";
    toggle.innerHTML = '<span>论文 PDF</span><small>打开证据模式</small>';
    toggle.addEventListener("click", function () {
      if (pendingLink) showEvidence(pendingLink, true);
      else setPanelOpen(true);
    });
    placeToggle();
    window.addEventListener("resize", handleToggleResize);
    window.dispatchEvent(new CustomEvent("reader:evidence-panel-ready", { detail: { panel } }));
  }

  function closePanel() {
    setPanelOpen(false);
  }

  function setPanelOpen(open) {
    document.body.classList.toggle("evidence-panel-open", open);
    window.dispatchEvent(new CustomEvent("reader:evidence-panel-change", {
      detail: { open }
    }));
  }

  function showEvidence(link, openPanel) {
    buildPanel();
    pendingLink = null;
    // Give the PDF viewer its real viewport before it computes the initial page.
    if (openPanel) setPanelOpen(true);
    const page = link.dataset.page || "1";
    // Resolve against the document URL before assigning iframe.src. This keeps
    // nested MkDocs pages from interpreting the PDF path at the wrong depth.
    const cleanPdf = new URL(link.dataset.pdf, document.baseURI);
    cleanPdf.hash = "page=" + page;
    const viewerUrl = new URL("../../pdf-viewer/", link.href);
    viewerUrl.searchParams.set("file", cleanPdf.pathname);
    viewerUrl.searchParams.set("page", page);
    viewerUrl.searchParams.set("source_id", link.dataset.sourceId || "");
    if (link.dataset.locator) viewerUrl.searchParams.set("locator", link.dataset.locator);
    frame.src = viewerUrl.href;
    if (activeLink) activeLink.classList.remove("is-active");
    activeLink = link;
    activeLink.classList.add("is-active");
    title.textContent = link.dataset.sourceTitle || "固定论文 PDF";
    meta.textContent = (link.dataset.sourceId || "固定来源") + " · PDF 第 " + page + " 页" +
      (link.dataset.locator ? " · " + link.dataset.locator : "");
    externalLink.href = cleanPdf.href;
    document.body.classList.add("evidence-panel-available");
    window.__readerPdfContext = { sourceId: link.dataset.sourceId, page: Number(page) };
    window.dispatchEvent(new CustomEvent("reader:pdf-context", {
      detail: window.__readerPdfContext
    }));
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== window.location.origin || event.source !== frame?.contentWindow) return;
    if (event.data?.type !== "research-reader-pdf-page") return;
    const page = Number(event.data.page);
    if (!Number.isFinite(page)) return;
    meta.textContent = (activeLink?.dataset.sourceId || "固定来源") + " · PDF 第 " + page + " 页";
    window.__readerPdfContext = { sourceId: activeLink?.dataset.sourceId, page };
    window.dispatchEvent(new CustomEvent("reader:pdf-context", {
      detail: window.__readerPdfContext
    }));
  });

  window.addEventListener("reader:open-pdf-context", function (event) {
    const sourceId = event.detail?.source_id;
    const page = Number(event.detail?.page);
    if (!/^[A-Za-z0-9._-]{1,128}$/.test(sourceId || "") || !Number.isInteger(page) || page < 1) return;
    const sourceLink = Array.from(document.querySelectorAll("a.evidence-link[data-pdf]")).find(
      link => link.dataset.sourceId === sourceId
    );
    if (!sourceLink) return;
    const link = document.createElement("a");
    link.href = sourceLink.href;
    Object.assign(link.dataset, sourceLink.dataset, { page: String(page) });
    showEvidence(link, true);
    panel.querySelector('[data-reader-tab="pdf"]')?.click();
  });

  function initializePage() {
    buildPanel();
    placeToggle();
    document.body.classList.remove("evidence-panel-available", "evidence-panel-open");
    const links = Array.from(document.querySelectorAll("a.evidence-link[data-pdf][data-page]"));
    if (!links.length) return;
    document.body.classList.add("evidence-panel-available");
    links.forEach(function (link) {
      link.addEventListener("click", function (event) {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        showEvidence(link, true);
      });
    });
    const primary = links.find(function (link) { return link.dataset.primary === "true"; }) || links[0];
    // Defer the iframe work until the reader explicitly enters evidence mode.
    pendingLink = primary;
    const page = primary.dataset.page || "1";
    title.textContent = primary.dataset.sourceTitle || "固定论文 PDF";
    meta.textContent = (primary.dataset.sourceId || "固定来源") + " · PDF 第 " + page + " 页";
  }

  if (typeof document$ !== "undefined") {
    document$.subscribe(initializePage);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializePage);
  } else {
    initializePage();
  }
})();
