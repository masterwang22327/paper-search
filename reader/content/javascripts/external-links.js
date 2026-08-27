(function () {
  "use strict";

  function openExternalLinksInNewTab() {
    document.querySelectorAll("a[href]").forEach(link => {
      let url;
      try {
        url = new URL(link.getAttribute("href"), document.baseURI);
      } catch (error) {
        return;
      }
      if (!/^https?:$/.test(url.protocol) || url.origin === window.location.origin) return;

      link.target = "_blank";
      const rel = new Set(link.rel.split(/\s+/).filter(Boolean));
      rel.add("noopener");
      rel.add("noreferrer");
      link.rel = [...rel].join(" ");
    });
  }

  if (typeof document$ !== "undefined") document$.subscribe(openExternalLinksInNewTab);
  else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", openExternalLinksInNewTab);
  } else {
    openExternalLinksInNewTab();
  }
})();
