// Page associations come from the document's saved conversations in the parent.
export function createPageQuestions({ sourceId, embedded, onNavigate }) {
  if (!embedded) return { setPage() {} };
  const bar = document.createElement("section");
  bar.className = "pdf-questions";
  bar.setAttribute("aria-label", "论文历史问题");
  bar.innerHTML = `<details class="pdf-questions__details">
    <summary aria-controls="pdf-question-list">本页问过 · 加载中</summary>
    <div id="pdf-question-list" class="pdf-questions__list"></div>
  </details><select aria-label="跳到有问题的 PDF 页"><option value="">有问题的页</option></select>`;
  document.querySelector("#viewport").before(bar);
  const details = bar.querySelector("details");
  const summary = bar.querySelector("summary");
  const list = bar.querySelector(".pdf-questions__list");
  const select = bar.querySelector("select");
  let currentPage = 1;
  let questions = [];
  let loaded = false;
  let error = "";
  let busy = false;

  function render() {
    const items = questions.filter(item => item.page === currentPage);
    summary.textContent = `本页问过 · ${error ? "加载失败" : loaded ? items.length : "加载中"}`;
    summary.title = `PDF 第 ${currentPage} 页的历史问题`;
    bar.classList.toggle("has-questions", Boolean(items.length));
    list.replaceChildren();
    const heading = document.createElement("p");
    heading.className = "pdf-questions__hint";
    heading.textContent = error || (!loaded ? "正在读取历史问题…" : items.length
      ? `第 ${currentPage} 页 · 点击问题查看原对话${busy ? "（本轮回答结束后可跳转）" : ""}`
      : `第 ${currentPage} 页还没有关联问题。将本页 PDF 图像加入问题后，会在这里显示。`);
    list.append(heading);
    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pdf-questions__item";
      button.disabled = busy;
      const question = document.createElement("span");
      question.textContent = item.question;
      const meta = document.createElement("small");
      meta.textContent = ["附过此页", item.thread_title, item.archived ? "已归档" : "",
        String(item.created_at || "").slice(0, 10)].filter(Boolean).join(" · ");
      button.append(question, meta);
      button.addEventListener("click", () => {
        details.open = false;
        window.parent.postMessage({ type: "reader:open-question", source_id: sourceId,
          page: currentPage, thread_id: item.thread_id, message_id: item.message_id }, location.origin);
      });
      list.append(button);
    }
    select.replaceChildren(new Option("有问题的页", ""));
    const counts = new Map();
    questions.forEach(item => counts.set(item.page, (counts.get(item.page) || 0) + 1));
    [...counts].sort((a, b) => a[0] - b[0]).forEach(([page, count]) => {
      select.add(new Option(`第 ${page} 页 · ${count} 问`, String(page)));
    });
    select.disabled = !counts.size;
    select.value = counts.has(currentPage) ? String(currentPage) : "";
  }

  select.addEventListener("change", () => {
    if (!select.value) return;
    onNavigate(Number(select.value));
    details.open = true;
  });
  bar.addEventListener("keydown", event => {
    if (event.key === "Escape") { details.open = false; summary.focus(); }
  });
  document.addEventListener("pointerdown", event => {
    if (!bar.contains(event.target)) details.open = false;
  });
  window.addEventListener("message", event => {
    if (event.origin !== location.origin || event.source !== window.parent
        || event.data?.type !== "reader:pdf-questions" || event.data.source_id !== sourceId) return;
    questions = (event.data.items || []).filter(item => item.source_id === sourceId && Number.isInteger(item.page));
    loaded = event.data.loaded;
    error = event.data.error || "";
    busy = Boolean(event.data.busy);
    render();
  });
  render();
  window.parent.postMessage({ type: "reader:pdf-questions-ready" }, location.origin);
  return { setPage(page) { if (currentPage !== page) { currentPage = page; render(); } } };
}
