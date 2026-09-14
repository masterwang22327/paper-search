window.MathJax = {
  loader: { load: ["[tex]/boldsymbol"] },
  tex: {
    packages: { "[+]": ["boldsymbol"] },
    inlineMath: [["\\(", "\\)"], ["$", "$"]],
    displayMath: [["\\[", "\\]"], ["$$", "$$"]],
    processEscapes: true,
    processEnvironments: true
  },
  options: {
    ignoreHtmlClass: "no-mathjax",
    processHtmlClass: "arithmatex"
  },
  chtml: {
    // Answers are inserted after startup and may introduce glyphs that were
    // absent from the document. A complete stylesheet keeps their dimensions
    // independent of render order, tab visibility, and browser cache state.
    adaptiveCSS: false
  },
  startup: {
    ready() {
      preserveReaderMathSource();
      MathJax.startup.defaultReady();
      installReaderMathNavigation();
    }
  }
};

function preserveReaderMathSource() {
  document.querySelectorAll("article .arithmatex").forEach(node => {
    if (!node.hasAttribute("data-reader-math-source") && !node.querySelector("mjx-container")) {
      node.dataset.readerMathSource = node.textContent || "";
    }
  });
}

function installReaderMathNavigation() {
  let queue = Promise.resolve();
  let scheduled = false;

  function scheduleTypeset() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      queue = queue.then(async () => {
        await MathJax.startup.promise;
        // Instant navigation replaces the article without reloading MathJax.
        // Forget detached formula records, but preserve live assistant math.
        const stale = Array.from(MathJax.startup.document.math).filter(
          item => item.start?.node && !item.start.node.isConnected
        );
        stale.forEach(item => MathJax.startup.document.math.remove(item));
        const pending = Array.from(document.querySelectorAll(
          "article .arithmatex"
        )).filter(node => !node.closest(".knowledge-rich-text") &&
          !node.querySelector("mjx-container"));
        preserveReaderMathSource();
        if (pending.length) await MathJax.typesetPromise(pending);
      }).catch(error => console.error("Reader formula rendering failed", error));
    });
  }

  // Material's document stream also covers pages restored from its cache.
  if (typeof document$ !== "undefined") document$.subscribe(scheduleTypeset);
  window.addEventListener("hashchange", scheduleTypeset);
  window.addEventListener("popstate", scheduleTypeset);
  // Re-clicking the current TOC anchor need not emit a hashchange event.
  document.addEventListener("click", event => {
    const link = event.target.closest?.("a[href]");
    if (!link) return;
    const target = new URL(link.href, location.href);
    if (target.origin === location.origin && target.pathname === location.pathname && target.hash) {
      scheduleTypeset();
    }
  });
  document.addEventListener("toggle", event => {
    if (event.target.matches?.("article details[open]")) scheduleTypeset();
  }, true);
  scheduleTypeset();
}
