(function () {
  "use strict";

  const storageKey = "research-reader-navigation-collapsed";
  let toggle;
  let sectionTools;
  let scrollHandler;
  let clickHandler;

  function apply(collapsed) {
    document.body.classList.toggle("reader-nav-collapsed", collapsed);
    if (!toggle) return;
    toggle.textContent = collapsed ? "›" : "‹";
    toggle.title = collapsed ? "展开左侧项目栏" : "收起左侧项目栏";
    toggle.setAttribute("aria-label", toggle.title);
    toggle.setAttribute("aria-expanded", String(!collapsed));
  }

  function initialize() {
    const documentMeta = document.querySelector(".reader-document-meta");
    const documentId = documentMeta?.dataset.documentId || "";
    document.body.classList.toggle(
      "reader-research-page",
      documentId.startsWith("papers/") || documentId === "report/index.md"
    );
    if (!document.querySelector(".md-sidebar--primary")) return;
    if (!toggle) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "reader-nav-toggle";
      toggle.addEventListener("click", () => {
        const collapsed = !document.body.classList.contains("reader-nav-collapsed");
        localStorage.setItem(storageKey, String(collapsed));
        apply(collapsed);
      });
      document.body.appendChild(toggle);
    }
    apply(localStorage.getItem(storageKey) === "true");
    buildSectionTools();
  }

  function buildSectionTools() {
    sectionTools?.remove();
    if (scrollHandler) window.removeEventListener("scroll", scrollHandler);
    if (clickHandler) document.removeEventListener("click", clickHandler);

    const article = document.querySelector(".md-content__inner");
    const headings = Array.from(article?.querySelectorAll("h2[id]") || []);
    if (!article || headings.length < 2 || !document.body.classList.contains("reader-research-page")) return;

    sectionTools = document.createElement("nav");
    sectionTools.className = "reader-section-tools";
    sectionTools.setAttribute("aria-label", "文章章节导航");
    sectionTools.innerHTML = [
      '<span class="reader-section-tools__progress" aria-hidden="true"><i></i></span>',
      '<button class="reader-section-tools__step" type="button" data-section-step="previous" title="上一节">‹</button>',
      '<button class="reader-section-tools__current" type="button" aria-expanded="false">',
      '  <span></span><small></small>',
      '</button>',
      '<button class="reader-section-tools__step" type="button" data-section-step="next" title="下一节">›</button>',
      '<div class="reader-section-tools__menu" hidden></div>'
    ].join("");
    const anchor = article.querySelector(".paper-reading-card") || article.querySelector("h1");
    anchor?.insertAdjacentElement("afterend", sectionTools);

    const menu = sectionTools.querySelector(".reader-section-tools__menu");
    headings.forEach((heading, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.sectionIndex = String(index);
      button.innerHTML = `<small>${String(index + 1).padStart(2, "0")}</small><span>${heading.textContent.trim()}</span>`;
      button.addEventListener("click", () => {
        menu.hidden = true;
        sectionTools.querySelector(".reader-section-tools__current").setAttribute("aria-expanded", "false");
        heading.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      menu.appendChild(button);
    });

    let activeIndex = 0;
    const current = sectionTools.querySelector(".reader-section-tools__current");
    const previous = sectionTools.querySelector('[data-section-step="previous"]');
    const next = sectionTools.querySelector('[data-section-step="next"]');

    function render() {
      const marker = window.scrollY + 150;
      activeIndex = 0;
      headings.forEach((heading, index) => {
        if (heading.getBoundingClientRect().top + window.scrollY <= marker) activeIndex = index;
      });
      const articleTop = article.getBoundingClientRect().top + window.scrollY;
      const available = Math.max(1, article.scrollHeight - window.innerHeight * 0.7);
      const percentage = Math.max(0, Math.min(100, ((window.scrollY - articleTop) / available) * 100));
      sectionTools.style.setProperty("--reader-progress", percentage + "%");
      current.querySelector("span").textContent = headings[activeIndex].textContent.trim();
      current.querySelector("small").textContent = `${activeIndex + 1} / ${headings.length}`;
      previous.disabled = activeIndex === 0;
      next.disabled = activeIndex === headings.length - 1;
      menu.querySelectorAll("button").forEach((button, index) => {
        button.classList.toggle("is-active", index === activeIndex);
      });
    }

    current.addEventListener("click", event => {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
      current.setAttribute("aria-expanded", String(!menu.hidden));
    });
    previous.addEventListener("click", () => headings[Math.max(0, activeIndex - 1)].scrollIntoView({ behavior: "smooth" }));
    next.addEventListener("click", () => headings[Math.min(headings.length - 1, activeIndex + 1)].scrollIntoView({ behavior: "smooth" }));

    let scheduled = false;
    scrollHandler = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        render();
      });
    };
    clickHandler = event => {
      if (!sectionTools.contains(event.target)) {
        menu.hidden = true;
        current.setAttribute("aria-expanded", "false");
      }
    };
    window.addEventListener("scroll", scrollHandler, { passive: true });
    document.addEventListener("click", clickHandler);
    render();
  }

  if (typeof document$ !== "undefined") document$.subscribe(initialize);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
  else initialize();
})();
