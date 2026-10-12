(function () {
  "use strict";

  let panel, frame, title, meta, activeLink, pendingLink, toggle, currentPdf;
  let pendingNavigation;
  let documentScroll = 0;
  let activePane = window.__readerInitialLayout?.pane || "translation";
  let lastCompanion = window.__readerInitialLayout?.companion || "translation";
  let closedPdfAnchor = null;
  let documentShare = Math.max(20, Math.min(45, Number(localStorage.getItem("reader-document-share")) || 30));
  let initialDocumentTop = 0;
  let paneVersion = 0;
  let share = Math.max(35, Math.min(70, Number(localStorage.getItem("reader-paper-share")) || 54));
  const readingPositions = new Map();
  const paneScroll = new Map();

  function placeToggle() {
    if (!toggle) return;
    const sidebar = document.querySelector(".md-sidebar--secondary");
    let dock = sidebar?.querySelector(":scope > .reader-tool-dock");
    if (sidebar && !dock) {
      dock = document.createElement("div");
      dock.className = "reader-tool-dock";
      sidebar.classList.add("reader-tools-docked");
      sidebar.prepend(dock);
    }
    (dock || document.body).appendChild(toggle);
    window.dispatchEvent(new CustomEvent("reader:tool-dock-change", { detail: { dock } }));
  }

  function savePaneScroll() {
    for (const selector of [".knowledge-messages", ".knowledge-faq"]) {
      const node = panel.querySelector(selector);
      if (node?.clientHeight) paneScroll.set(selector, node.scrollTop);
    }
  }

  function restorePaneScroll() {
    requestAnimationFrame(() => {
      for (const [selector, top] of paneScroll) {
        const node = panel.querySelector(selector);
        if (node?.clientHeight) node.scrollTop = top;
      }
    });
  }

  function documentAnchor(inPanel) {
    const main = document.querySelector(".md-main");
    const edge = inPanel ? main.getBoundingClientRect().top : 0;
    const nodes = document.querySelectorAll(".md-content__inner :is(p,h1,h2,h3,li,pre,table)");
    for (const node of nodes) {
      if (node.closest(".paper-reading-card, .reader-section-tools")) continue;
      const box = node.getBoundingClientRect();
      if (box.height && box.bottom > edge && box.top < innerHeight) {
        return { node, fraction: (edge - box.top) / box.height };
      }
    }
    return null;
  }

  function restoreDocumentAnchor(anchor, inPanel) {
    if (!anchor?.node.isConnected) return;
    const main = document.querySelector(".md-main");
    const box = anchor.node.getBoundingClientRect();
    const delta = box.top + box.height * anchor.fraction - (inPanel ? main.getBoundingClientRect().top : 0);
    if (inPanel) main.scrollTop += delta;
    else window.scrollTo({ top: window.scrollY + delta, behavior: "instant" });
  }

  function setPanelOpen(open) {
    const wasOpen = document.body.classList.contains("evidence-panel-open");
    const main = document.querySelector(".md-main");
    const anchor = open !== wasOpen ? documentAnchor(wasOpen) : null;
    const documentMoved = wasOpen && Math.abs(main.scrollTop - initialDocumentTop) > 2;
    if (open && !wasOpen) documentScroll = window.scrollY;
    if (!open) {
      savePaneScroll();
      closedPdfAnchor = frame.contentWindow?.ReaderPdf?.snapshot().anchor || closedPdfAnchor;
    }
    document.body.classList.toggle("evidence-panel-open", open);
    document.body.classList.toggle("reader-pdf-focus", open);
    panel?.setAttribute("aria-hidden", "false");
    toggle?.setAttribute("aria-expanded", String(open));
    if (open && !wasOpen) {
      restoreDocumentAnchor(anchor, true);
      initialDocumentTop = main.scrollTop;
      requestAnimationFrame(() => {
        if (document.body.classList.contains("evidence-panel-open")) {
          restoreDocumentAnchor(anchor, true);
          initialDocumentTop = main.scrollTop;
        }
      });
    } else if (!open && wasOpen) {
      if (documentMoved) restoreDocumentAnchor(anchor, false);
      else window.scrollTo({ top: documentScroll, behavior: "instant" });
    }
    syncViewControls();
    try {
      sessionStorage.setItem("reader-studio-layout", JSON.stringify({
        open, pane: activePane, companion: lastCompanion
      }));
    } catch (_) { /* Reading still works if browser storage is unavailable. */ }
    window.dispatchEvent(new CustomEvent("reader:evidence-panel-change", { detail: { open } }));
  }

  function syncViewControls() {
    const open = document.body.classList.contains("evidence-panel-open");
    const columns = open ? (activePane === "pdf" ? "2" : "3") : "1";
    panel.querySelectorAll("[data-reader-columns]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.readerColumns === columns));
    });
    panel.querySelectorAll("[data-reader-tab]").forEach(button => {
      const selected = open && button.dataset.readerTab === activePane;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  function applyDocumentShare(value) {
    const anchor = documentAnchor(true);
    const previousTop = document.querySelector(".md-main").scrollTop;
    const viewer = frame.contentWindow?.ReaderPdf;
    const pdfAnchor = viewer?.snapshot().anchor;
    documentShare = Math.max(20, Math.min(45, value));
    document.body.style.setProperty("--reader-document-share", `${documentShare}vw`);
    panel.querySelector(".reader-document-splitter").setAttribute("aria-valuenow", String(Math.round(documentShare)));
    restoreDocumentAnchor(anchor, true);
    initialDocumentTop += document.querySelector(".md-main").scrollTop - previousTop;
    viewer?.setSidePane(activePane, pdfAnchor, share);
  }

  async function setPane(name, toggleCurrent = false) {
    if (!["pdf", "insight", "translation", "assistant", "faq"].includes(name)) return;
    if (!panel) buildPanel();
    if (toggleCurrent && activePane === name && document.body.classList.contains("evidence-panel-open")) name = "pdf";
    const version = ++paneVersion;
    savePaneScroll();
    const viewer = frame.contentWindow?.ReaderPdf;
    const anchor = viewer?.snapshot().anchor || closedPdfAnchor;
    activePane = name;
    if (name !== "pdf") lastCompanion = name;
    panel.dataset.readerActivePane = name;
    panel.querySelectorAll("[data-reader-tab]").forEach(button => {
      const selected = button.dataset.readerTab === name;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    panel.querySelectorAll("[data-reader-pane]").forEach(pane => {
      pane.classList.toggle("is-active", pane.dataset.readerPane === "pdf" || pane.dataset.readerPane === name);
    });
    setPanelOpen(true);
    if (pendingLink) showEvidence(pendingLink, true);
    if (viewer) {
      await viewer.ready;
      if (version !== paneVersion || viewer !== frame.contentWindow?.ReaderPdf) return;
      viewer.setSidePane(name, anchor, share);
    }
    restorePaneScroll();
    window.dispatchEvent(new CustomEvent("reader:pane-change", { detail: { name } }));
  }

  function applyShare(value) {
    const viewer = frame.contentWindow?.ReaderPdf;
    const anchor = viewer?.snapshot().anchor;
    share = Math.max(35, Math.min(70, value));
    panel.style.setProperty("--paper-share", `${share}%`);
    panel.querySelector(".reader-splitter").setAttribute("aria-valuenow", String(Math.round(share)));
    viewer?.setSidePane(activePane, anchor, share);
  }

  function buildPanel() {
    if (panel) { placeToggle(); return; }
    // The shell is rendered by MkDocs, before deferred Reader initialization.
    panel = document.querySelector(".reader-studio");
    panel.dataset.readerActivePane = activePane;
    panel.style.setProperty("--paper-share", `${share}%`);
    document.body.style.setProperty("--reader-document-share", `${documentShare}vw`);
    const bar = panel.querySelector(".reader-studio-bar");
    new ResizeObserver(() => {
      if (bar.offsetHeight) document.body.style.setProperty("--reader-bar-height", `${bar.offsetHeight}px`);
    }).observe(bar);
    frame = panel.querySelector("iframe");
    title = panel.querySelector(".evidence-panel__title");
    meta = panel.querySelector(".evidence-panel__meta");
    panel.querySelectorAll("[data-reader-columns]").forEach(button => button.addEventListener("click", () => {
      const columns = button.dataset.readerColumns;
      if (columns === "1") setPanelOpen(false);
      else setPane(columns === "2" ? "pdf" : lastCompanion);
    }));
    panel.querySelectorAll("[data-reader-tab]").forEach(button => button.addEventListener("click", () => setPane(button.dataset.readerTab, true)));
    function wireSplitter(selector, article) {
      const splitter = panel.querySelector(selector);
      const update = article ? applyDocumentShare : applyShare;
      const current = () => article ? documentShare : share;
      const key = article ? "reader-document-share" : "reader-paper-share";
      const defaultValue = article ? 30 : 54;
      splitter.setAttribute("aria-valuenow", String(Math.round(current())));
      splitter.addEventListener("pointerdown", event => {
        if (event.button !== 0) return;
        event.preventDefault();
        splitter.setPointerCapture(event.pointerId);
        panel.classList.add("is-resizing");
        const move = next => {
          const bounds = panel.querySelector(".evidence-panel__panes").getBoundingClientRect();
          update(article ? next.clientX / innerWidth * 100 : (next.clientX - bounds.left) / bounds.width * 100);
        };
        const finish = () => {
          panel.classList.remove("is-resizing");
          localStorage.setItem(key, String(current()));
          splitter.removeEventListener("pointermove", move);
          splitter.removeEventListener("pointerup", finish);
          splitter.removeEventListener("pointercancel", finish);
        };
        splitter.addEventListener("pointermove", move);
        splitter.addEventListener("pointerup", finish);
        splitter.addEventListener("pointercancel", finish);
      });
      splitter.addEventListener("dblclick", () => { update(defaultValue); localStorage.removeItem(key); });
      splitter.addEventListener("keydown", event => {
        if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
        event.preventDefault();
        update(event.key === "Home" ? defaultValue : current() + (event.key === "ArrowLeft" ? -2 : 2));
        localStorage.setItem(key, String(current()));
      });
    }
    wireSplitter(".reader-splitter", false);
    wireSplitter(".reader-document-splitter", true);
    frame.addEventListener("load", async () => {
      const viewer = frame.contentWindow?.ReaderPdf;
      if (!viewer) return;
      await viewer.ready;
      if (viewer !== frame.contentWindow?.ReaderPdf) return;
      viewer.setSidePane(activePane, null, share);
      const navigation = pendingNavigation;
      if (navigation) {
        await viewer.navigate(navigation);
        if (pendingNavigation === navigation) pendingNavigation = null;
      }
    });
    toggle = document.createElement("button");
    toggle.className = "evidence-panel-toggle";
    toggle.type = "button";
    toggle.innerHTML = "<span>论文 PDF</span><small>打开阅读工作台</small>";
    toggle.addEventListener("click", () => pendingLink ? showEvidence(pendingLink, true) : setPanelOpen(true));
    placeToggle();
    window.dispatchEvent(new CustomEvent("reader:evidence-panel-ready", { detail: { panel } }));
  }

  window.addEventListener("reader:set-pane", event => setPane(event.detail?.name));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && document.body.classList.contains("evidence-panel-open") && !document.querySelector(".reader-revision-editor, .knowledge-faq-editor")) setPanelOpen(false);
  });

  function showEvidence(link, openPanel) {
    buildPanel();
    pendingLink = null;
    if (openPanel) setPanelOpen(true);
    const page = link.dataset.page || "1";
    const cleanPdf = new URL(link.dataset.pdf, document.baseURI);
    const viewerUrl = new URL("../../pdf-viewer/", link.href);
    viewerUrl.searchParams.set("embedded", "1");
    viewerUrl.searchParams.set("file", cleanPdf.pathname);
    viewerUrl.searchParams.set("page", page);
    viewerUrl.searchParams.set("source_id", link.dataset.sourceId || "");
    if (link.dataset.locator) viewerUrl.searchParams.set("locator", link.dataset.locator);
    if (link.dataset.quote) viewerUrl.searchParams.set("quote", link.dataset.quote);
    const previous = frame.contentWindow?.ReaderPdf;
    if (currentPdf && previous?.sourceId === currentPdf.sourceId) {
      const snapshot = previous.snapshot();
      if (snapshot.anchor) readingPositions.set(currentPdf.path, snapshot);
    }
    const samePdf = currentPdf?.path === cleanPdf.pathname && previous?.sourceId === link.dataset.sourceId;
    const saved = samePdf ? null : readingPositions.get(cleanPdf.pathname);
    const restorePage = saved && page === "1" && !link.dataset.locator && !link.dataset.quote ? saved.page : Number(page);
    const navigation = { page: restorePage, locator: link.dataset.locator || "", quote: link.dataset.quote || "", restore: saved };
    if (link.dataset.openTranslation === "true") setPane("translation");
    if (samePdf) previous.navigate(navigation);
    else {
      closedPdfAnchor = null;
      currentPdf = { path: cleanPdf.pathname, sourceId: link.dataset.sourceId };
      pendingNavigation = saved ? navigation : null;
      frame.src = viewerUrl.href;
    }
    activeLink?.classList.remove("is-active");
    activeLink = link;
    activeLink.classList.add("is-active");
    title.textContent = link.dataset.sourceTitle || "论文原文";
    title.title = title.textContent;
    meta.textContent = (link.dataset.sourceId || "固定来源") + " · PDF 第 " + page + " 页";
    document.body.classList.add("evidence-panel-available");
    window.__readerPdfContext = { sourceId: link.dataset.sourceId, page: Number(page) };
    window.dispatchEvent(new CustomEvent("reader:pdf-context", { detail: window.__readerPdfContext }));
  }

  window.addEventListener("message", event => {
    if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
    if (event.data?.type === "reader:pdf-controls") return;
    if (event.data?.type === "reader:pdf-selection") {
      window.dispatchEvent(new CustomEvent("reader:pdf-selection", { detail: event.data }));
      setPane("assistant");
      return;
    }
    if (event.data?.type !== "research-reader-pdf-page") return;
    const page = Number(event.data.page);
    if (!Number.isFinite(page)) return;
    meta.textContent = (activeLink?.dataset.sourceId || "固定来源") + " · PDF 第 " + page + " 页";
    window.__readerPdfContext = { sourceId: activeLink?.dataset.sourceId, page };
    window.dispatchEvent(new CustomEvent("reader:pdf-context", { detail: window.__readerPdfContext }));
  });
  window.addEventListener("reader:open-pdf-context", event => {
    const { source_id: sourceId, page, quote, locator } = event.detail || {};
    if (!/^[A-Za-z0-9._-]{1,128}$/.test(sourceId || "") || !Number.isInteger(Number(page)) || Number(page) < 1) return;
    const source = Array.from(document.querySelectorAll("a.evidence-link[data-pdf]")).find(link => link.dataset.sourceId === sourceId);
    if (!source) return;
    const link = document.createElement("a");
    link.href = source.href;
    Object.assign(link.dataset, source.dataset, { page: String(page), quote: String(quote || "").slice(0, 2000), locator: String(locator || "").slice(0, 160) });
    showEvidence(link, true);
  });

  function initializePage() {
    buildPanel();
    placeToggle();
    const links = Array.from(document.querySelectorAll("a.evidence-link[data-pdf][data-page]"));
    document.body.classList.toggle("evidence-panel-available", Boolean(links.length));
    if (!links.length) {
      document.body.classList.remove("reader-pdf-focus", "evidence-panel-open");
      panel.setAttribute("aria-hidden", "true");
      pendingLink = null;
      return;
    }
    panel.setAttribute("aria-hidden", "false");
    syncViewControls();
    links.forEach(link => link.addEventListener("click", event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      showEvidence(link, true);
    }));
    pendingLink = links.find(link => link.dataset.primary === "true") || links[0];
    title.textContent = pendingLink.dataset.sourceTitle || "论文原文";
    meta.textContent = (pendingLink.dataset.sourceId || "固定来源") + " · PDF 第 " + (pendingLink.dataset.page || "1") + " 页";
    if (document.body.classList.contains("evidence-panel-open")) setPane(activePane);
  }
  if (typeof document$ !== "undefined") document$.subscribe(initializePage);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initializePage);
  else initializePage();
})();
