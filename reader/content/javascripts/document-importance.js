(function () {
  "use strict";

  const labels = ["未评分", "略读即可", "按需查阅", "值得复习", "重点掌握", "优先复习"];
  let generation = 0;
  let ratings = {};
  let token = "";
  let rows = [];
  let groups = [];
  let toolbar;
  let dialog;
  let filter = "all";
  let saving = false;
  let taskId = "";
  let refreshSequence = 0;

  async function api(path, options = {}) {
    return window.ReaderApi.request(path, {
      cache: "no-store",
      ...options,
      headers: { "Content-Type": "application/json", "X-Reader-Token": token }
    });
  }

  function closeDialog() {
    dialog?.close();
    dialog?.remove();
    dialog = undefined;
  }

  function render() {
    if (!toolbar) return;
    let count = 0;
    rows.forEach(row => {
      const score = ratings[row.id] || 0;
      row.button.textContent = score ? `★${score}` : "☆";
      row.button.dataset.score = String(score);
      row.button.title = `${row.title}：${score ? score + "/5 · " : ""}${labels[score]}；点击修改重要性`;
      row.button.setAttribute("aria-label", row.button.title);
      const visible = filter === "all" || (filter === "high" ? score >= 4 : score > 0);
      row.item.classList.toggle("reader-importance-hidden", !visible);
      if (visible) count += 1;
    });
    groups.forEach(({ item, input, checked }) => {
      const matching = rows.some(row => item.contains(row.item) && !row.item.classList.contains("reader-importance-hidden"));
      item.classList.toggle("reader-importance-hidden", filter !== "all" && !matching);
      if (input) input.checked = filter === "all" ? checked : matching;
    });
    toolbar.querySelector("[data-importance-status]").textContent = filter === "all"
      ? "点击 ☆ 评分 · 5 分最高"
      : count ? `显示 ${count} 篇文档` : "暂无匹配文档，切换“全部文档”后评分";
  }

  function openRating(row) {
    closeDialog();
    const currentGeneration = generation;
    const panel = document.createElement("dialog");
    dialog = panel;
    panel.className = "reader-importance-dialog";
    panel.setAttribute("aria-labelledby", "reader-importance-title");
    panel.innerHTML = '<div class="reader-importance-dialog__header"><strong id="reader-importance-title">文档重要性</strong><button type="button" data-close aria-label="关闭评分">×</button></div>' +
      '<p class="reader-importance-dialog__document"></p><p class="reader-importance-dialog__hint">按你的复习需求评分，5 分最高</p>' +
      '<div class="reader-importance-dialog__scores"></div><button type="button" data-clear>清除评分</button><p role="status" aria-live="polite" data-result></p>';
    panel.querySelector(".reader-importance-dialog__document").textContent = row.title;
    const scoreList = panel.querySelector(".reader-importance-dialog__scores");
    for (let score = 1; score <= 5; score += 1) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.score = String(score);
      button.textContent = `★ ${score}`;
      button.title = labels[score];
      button.setAttribute("aria-label", `${score} 分：${labels[score]}`);
      button.setAttribute("aria-pressed", String(ratings[row.id] === score));
      button.addEventListener("click", () => save(score));
      scoreList.appendChild(button);
    }
    panel.querySelector("[data-clear]").addEventListener("click", () => save(0));
    panel.querySelector("[data-close]").addEventListener("click", closeDialog);
    panel.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
    panel.addEventListener("close", () => {
      panel.remove();
      if (dialog === panel) dialog = undefined;
    });
    panel.addEventListener("click", event => {
      const box = panel.getBoundingClientRect();
      if (!saving && event.target === panel && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) closeDialog();
    });
    document.body.appendChild(panel);
    panel.showModal();
    const box = row.button.getBoundingClientRect();
    panel.style.left = `${Math.max(8, Math.min(box.left, window.innerWidth - panel.offsetWidth - 8))}px`;
    panel.style.top = `${Math.max(8, Math.min(box.bottom + 6, window.innerHeight - panel.offsetHeight - 8))}px`;
    (panel.querySelector('[aria-pressed="true"]') || scoreList.firstElementChild).focus();

    async function save(score) {
      if (saving) return;
      saving = true;
      refreshSequence += 1;
      panel.querySelectorAll("button").forEach(button => { button.disabled = true; });
      panel.querySelector("[data-result]").textContent = "正在保存…";
      try {
        await api("/api/document-importance", {
          method: "POST", body: JSON.stringify({ document_id: row.id, score })
        });
        if (generation !== currentGeneration) return;
        if (score) ratings[row.id] = score;
        else delete ratings[row.id];
        closeDialog();
        render();
        // The edited document may disappear under the current filter.
        if (row.item.classList.contains("reader-importance-hidden")) toolbar.querySelector("select").focus();
        else row.button.focus();
        toolbar.querySelector("[data-importance-status]").textContent = score ? `已保存：${score} 分 · ${labels[score]}` : "已清除评分";
      } catch (error) {
        panel.querySelector("[data-result]").textContent = `保存失败：${error.message}`;
      } finally {
        saving = false;
        panel.querySelectorAll("button").forEach(button => { button.disabled = false; });
      }
    }
  }

  async function refresh(currentGeneration = generation) {
    const sequence = ++refreshSequence;
    try {
      const [bootstrap, value] = await Promise.all([api("/api/bootstrap"), api("/api/document-importance")]);
      if (currentGeneration !== generation || sequence !== refreshSequence || saving) return;
      token = bootstrap.token;
      if (taskId !== bootstrap.task_id) {
        taskId = bootstrap.task_id;
        try {
          const saved = sessionStorage.getItem(`reader-importance-filter:${taskId}`);
          filter = ["all", "high", "rated"].includes(saved) ? saved : "all";
        } catch (error) { filter = "all"; }
        toolbar.querySelector("select").value = filter;
      }
      ratings = value.ratings || {};
      rows.forEach(row => { row.button.disabled = false; });
      toolbar.querySelector("select").disabled = false;
      toolbar.querySelector("[data-retry]").hidden = true;
      render();
    } catch (error) {
      if (currentGeneration !== generation || sequence !== refreshSequence || !toolbar) return;
      toolbar.querySelector("[data-importance-status]").textContent = "评分加载失败，请重试";
      toolbar.querySelector("[data-retry]").hidden = false;
    }
  }

  function initialize() {
    generation += 1;
    closeDialog();
    toolbar?.remove();
    toolbar = undefined;
    rows = [];
    groups = [];
    const nav = document.querySelector(".md-sidebar--primary .md-nav--primary");
    if (!nav) return;
    nav.querySelectorAll(".reader-importance-button").forEach(button => button.remove());
    nav.querySelectorAll(".reader-importance-hidden").forEach(item => item.classList.remove("reader-importance-hidden"));
    nav.querySelectorAll("a.md-nav__link").forEach(link => {
      const url = new URL(link.href);
      if (url.origin !== location.origin || url.hash) return;
      const match = url.pathname.match(/^\/papers\/([^/]+)\/$/);
      const id = match ? `papers/${decodeURIComponent(match[1])}.md` : url.pathname === "/report/" ? "report/index.md" : "";
      if (!id) return;
      const item = link.closest("li");
      item.classList.add("reader-importance-item");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "reader-importance-button";
      button.disabled = true;
      button.setAttribute("aria-haspopup", "dialog");
      button.dataset.documentId = id;
      const row = { id, item, button, title: link.querySelector(".md-ellipsis")?.textContent.trim() || link.textContent.trim() };
      button.addEventListener("click", event => { event.preventDefault(); event.stopPropagation(); openRating(row); });
      link.before(button);
      rows.push(row);
    });
    if (!rows.length) return;
    nav.querySelectorAll(".md-nav__item--nested").forEach(item => {
      if (!rows.some(row => item.contains(row.item))) return;
      const input = item.querySelector(":scope > input");
      const group = { item, input, checked: input?.checked };
      input?.addEventListener("change", () => { if (filter === "all") group.checked = input.checked; });
      groups.push(group);
    });
    toolbar = document.createElement("div");
    toolbar.className = "reader-importance-toolbar";
    toolbar.innerHTML = '<label for="reader-importance-filter">我的重要性</label><select id="reader-importance-filter" disabled><option value="all">全部文档</option><option value="high">★ 4–5 分 · 优先复习</option><option value="rated">★ 已评分</option></select><p data-importance-status role="status" aria-live="polite"></p><button type="button" data-retry hidden>重试</button>';
    const select = toolbar.querySelector("select");
    select.value = filter;
    select.addEventListener("change", () => {
      filter = select.value;
      try { sessionStorage.setItem(`reader-importance-filter:${taskId}`, filter); } catch (error) { /* Filtering still works without browser storage. */ }
      closeDialog();
      render();
    });
    toolbar.querySelector("[data-retry]").addEventListener("click", () => refresh());
    nav.querySelector(":scope > .md-nav__title").after(toolbar);
    render();
    toolbar.querySelector("[data-importance-status]").textContent = "正在加载评分…";
    refresh();
  }

  window.addEventListener("focus", () => { if (toolbar && !dialog && !saving) refresh(); });
  if (typeof document$ !== "undefined") document$.subscribe(initialize);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize);
  else initialize();
})();
