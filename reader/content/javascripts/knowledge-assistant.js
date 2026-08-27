(function () {
  "use strict";

  let token;
  let taskId;
  let documentId;
  let documentSha;
  let assistantPane;
  let faqPane;
  let messageList;
  let contextList;
  let questionInput;
  let sessionLabel;
  let threadSelect;
  let archiveThreadButton;
  let deleteThreadButton;
  let newThreadButton;
  let knowledgeModelSelect;
  let knowledgeEffortSelect;
  let selectionMenu;
  let selectionNotice;
  let faqSearchInput;
  let faqSearchCount;
  let currentSessionId = null;
  let activeThreadId = null;
  let selectedThreadId = null;
  let chatThreads = [];
  let pdfjsPromise;
  let contexts = [];
  let currentPdfContext = null;
  let pdfContexts = [];
  let pendingFaq = null;
  let revisions = [];
  let revisionSettings = { model: "gpt-5.6-terra", effort: "medium" };
  let knowledgeSettings = { model: "gpt-5.6-terra", effort: "medium" };
  let knowledgeSettingsSave = Promise.resolve();
  let knowledgeSettingsVersion = 0;
  let knowledgeSettingsTouched = false;
  let revisionDiscussions = [];
  let shouldRevealLatestMessage = false;
  let initializedPanel = null;
  let mathTypesetQueue = Promise.resolve();
  const pendingMathBodies = new WeakSet();

  function revealMessage(element, behavior = "auto") {
    if (!element || !messageList?.clientHeight) return;
    const listBox = messageList.getBoundingClientRect();
    const messageBox = element.getBoundingClientRect();
    const top = messageList.scrollTop + messageBox.top - listBox.top - 10;
    messageList.scrollTo({ top: Math.max(0, top), behavior });
  }

  function revealLatestMessage() {
    if (!shouldRevealLatestMessage) return;
    const latest = messageList?.querySelector(".knowledge-message:last-child");
    if (!latest || !messageList.clientHeight) return;
    revealMessage(latest);
    shouldRevealLatestMessage = false;
  }

  function switchTab(name) {
    const panel = document.querySelector(".evidence-panel");
    document.querySelectorAll(".evidence-panel__tab").forEach(tab => {
      tab.classList.toggle("is-active", tab.dataset.readerTab === name);
    });
    document.querySelectorAll(".evidence-panel__pane").forEach(pane => {
      pane.classList.toggle("is-active", pane.dataset.readerPane === name);
    });
    document.body.classList.add("evidence-panel-open");
    if (panel) panel.dataset.readerActivePane = name;
    if (name === "assistant") {
      // MathJax cannot measure formulas while the assistant pane is display:none.
      // Re-typeset after the pane is visible so hidden answers do not retain a
      // zero-width container and wrap one symbol per line.
      requestAnimationFrame(() => {
        typesetVisibleMessages();
        revealLatestMessage();
      });
    }
  }

  function createUi() {
    const panel = document.querySelector(".evidence-panel");
    if (!panel || panel.dataset.knowledgeReady === "true") return Boolean(panel);
    panel.dataset.knowledgeReady = "true";
    assistantPane = panel.querySelector('[data-reader-pane="assistant"]');
    faqPane = panel.querySelector('[data-reader-pane="faq"]');
    assistantPane.innerHTML = [
      '<section class="knowledge-assistant">',
      '  <div class="knowledge-threadbar" title="知识问答只读取原始调研 Markdown 和主动附加的原始 PDF；手动修改、AI 修订与补充图解不会进入对话上下文。">',
      '    <select data-action="select-thread" aria-label="选择 Codex 对话"></select>',
      '    <div class="knowledge-session">尚未建立 Codex 会话</div>',
      '    <button type="button" data-action="archive-thread" title="将当前对话保存为只读历史">归档</button>',
      '    <button type="button" data-action="delete-thread" title="永久删除当前对话及其消息">删除</button>',
      '    <button type="button" data-action="new-thread" title="开启独立的 Codex 对话">+ 新建</button>',
      '  </div>',
      '  <div class="knowledge-messages" aria-live="polite"></div>',
      '  <div class="knowledge-contexts"></div>',
      '  <div class="knowledge-composer">',
      '    <textarea placeholder="针对当前文档提问。可先在正文中选中文字加入上下文。"></textarea>',
      '    <div class="knowledge-toolbar">',
      '      <div class="knowledge-model-settings">',
      '        <select data-setting="knowledge-model" aria-label="知识问答模型" title="知识问答模型"><option value="gpt-5.6-terra">gpt-5.6-terra</option><option value="gpt-5.6-sol">gpt-5.6-sol</option></select>',
      '        <select data-setting="knowledge-effort" aria-label="知识问答推理强度" title="知识问答推理强度"><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option><option value="max">max</option><option value="ultra">ultra</option></select>',
      "      </div>",
      '      <div class="knowledge-toolbar-actions">',
      '        <button type="button" data-action="add-pdf" title="把当前物理页渲染为图像并交给 Codex 观察">加入当前 PDF 页图像</button>',
      '        <button type="button" data-action="send">发送问题</button>',
      "      </div>",
      "    </div>",
      "  </div>",
      "</section>"
    ].join("");
    faqPane.innerHTML = [
      '<section class="knowledge-faq">',
      '  <div class="knowledge-faq-search"><input type="search" placeholder="搜索问题、答案、备注或来源" aria-label="搜索已固化知识"><span aria-live="polite"></span></div>',
      '  <div class="knowledge-faq-list"></div>',
      "</section>"
    ].join("");
    sessionLabel = assistantPane.querySelector(".knowledge-session");
    threadSelect = assistantPane.querySelector('[data-action="select-thread"]');
    archiveThreadButton = assistantPane.querySelector('[data-action="archive-thread"]');
    deleteThreadButton = assistantPane.querySelector('[data-action="delete-thread"]');
    newThreadButton = assistantPane.querySelector('[data-action="new-thread"]');
    knowledgeModelSelect = assistantPane.querySelector('[data-setting="knowledge-model"]');
    knowledgeEffortSelect = assistantPane.querySelector('[data-setting="knowledge-effort"]');
    messageList = assistantPane.querySelector(".knowledge-messages");
    contextList = assistantPane.querySelector(".knowledge-contexts");
    questionInput = assistantPane.querySelector("textarea");
    faqSearchInput = faqPane.querySelector('.knowledge-faq-search input');
    faqSearchCount = faqPane.querySelector('.knowledge-faq-search span');

    panel.querySelectorAll(".evidence-panel__tab").forEach(tab => {
      tab.addEventListener("click", () => switchTab(tab.dataset.readerTab));
    });
    assistantPane.querySelector('[data-action="send"]').addEventListener("click", sendQuestion);
    assistantPane.querySelector('[data-action="add-pdf"]').addEventListener("click", addPdfContext);
    threadSelect.addEventListener("change", () => selectChatThread(threadSelect.value));
    archiveThreadButton.addEventListener("click", archiveCurrentThread);
    deleteThreadButton.addEventListener("click", deleteCurrentThread);
    newThreadButton.addEventListener("click", createNewThread);
    knowledgeModelSelect.addEventListener("change", queueKnowledgeSettingsSave);
    knowledgeEffortSelect.addEventListener("change", queueKnowledgeSettingsSave);
    questionInput.addEventListener("keydown", event => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") sendQuestion();
    });
    faqSearchInput.addEventListener("input", filterFaqItems);
    selectionMenu = document.createElement("div");
    selectionMenu.className = "knowledge-selection-menu";
    selectionMenu.innerHTML = '<button type="button" data-action="context">加入问答</button><button type="button" data-action="manual-edit">手动修改</button><button type="button" data-action="edit">AI 修订</button>';
    selectionMenu.querySelector('[data-action="context"]').addEventListener("click", captureSelection);
    selectionMenu.querySelector('[data-action="manual-edit"]').addEventListener("click", openManualRevisionEditor);
    selectionMenu.querySelector('[data-action="edit"]').addEventListener("click", openRevisionEditor);
    document.body.appendChild(selectionMenu);
    selectionNotice = document.createElement("div");
    selectionNotice.className = "knowledge-selection-notice";
    selectionNotice.textContent = "修订内容不能加入知识问答；请点击“查看原文”后框选原始文字。";
    document.body.appendChild(selectionNotice);
    document.addEventListener("selectionchange", scheduleSelectionMenu);
    return true;
  }

  async function api(path, options) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Reader-Token": token,
        ...(options?.headers || {})
      }
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
    return data;
  }

  function validPdfContext(value) {
    if (!value || !/^[A-Za-z0-9._-]{1,128}$/.test(value.source_id)) return null;
    const page = Number(value.page);
    if (!Number.isInteger(page) || page < 1) return null;
    return { source_id: value.source_id, page };
  }

  function loadPdfjs() {
    if (!pdfjsPromise) {
      pdfjsPromise = import("/vendor/pdfjs/pdf.mjs").then(pdfjs => {
        pdfjs.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.mjs";
        return pdfjs;
      });
    }
    return pdfjsPromise;
  }

  async function renderPdfThumbnail(canvas, context) {
    try {
      const pdfjs = await loadPdfjs();
      const url = `/sources/${encodeURIComponent(context.source_id)}/paper.pdf`;
      const loadingTask = pdfjs.getDocument(url);
      const pdf = await loadingTask.promise;
      const page = await pdf.getPage(context.page);
      const base = page.getViewport({ scale: 1 });
      const cssWidth = Math.min(180, Math.max(120, canvas.parentElement.clientWidth || 160));
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = page.getViewport({ scale: (cssWidth / base.width) * pixelRatio });
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      canvas.style.width = `${Math.round(viewport.width / pixelRatio)}px`;
      canvas.style.height = `${Math.round(viewport.height / pixelRatio)}px`;
      await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
      canvas.dataset.rendered = "true";
      await pdf.destroy();
    } catch (error) {
      canvas.replaceWith(Object.assign(document.createElement("div"), {
        className: "knowledge-message__pdf-error",
        textContent: "PDF 页面缩略图加载失败"
      }));
    }
  }

  function pdfAttachment(context) {
    const attachment = document.createElement("button");
    attachment.type = "button";
    attachment.className = "knowledge-message__pdf";
    attachment.title = "在论文 PDF 面板打开这一页";
    const preview = document.createElement("span");
    preview.className = "knowledge-message__pdf-preview";
    const canvas = document.createElement("canvas");
    canvas.setAttribute("aria-label", `${context.source_id} PDF 物理页 ${context.page} 缩略图`);
    preview.appendChild(canvas);
    const metadata = document.createElement("span");
    metadata.className = "knowledge-message__pdf-meta";
    metadata.innerHTML = `<strong>本轮 PDF 页面</strong><span>${context.source_id}</span><span>物理页 ${context.page}</span>`;
    attachment.append(preview, metadata);
    attachment.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("reader:open-pdf-context", { detail: context }));
    });
    requestAnimationFrame(() => renderPdfThumbnail(canvas, context));
    return attachment;
  }

  function diagramElement(value) {
    if (!value?.nodes?.length || !value?.edges?.length) return null;
    const figure = document.createElement("figure");
    figure.className = "knowledge-diagram";
    const title = document.createElement("strong");
    title.textContent = value.title || "示意图";
    const flow = document.createElement("div");
    flow.className = "knowledge-diagram__flow";
    const nodeMap = new Map(value.nodes.map(node => [node.id, node]));
    value.nodes.forEach((node, index) => {
      const card = document.createElement("div");
      card.className = "knowledge-diagram__node";
      const label = document.createElement("strong");
      label.textContent = node.label;
      const detail = document.createElement("span");
      detail.textContent = node.detail || "";
      card.append(label, detail);
      flow.appendChild(card);
      if (index < value.nodes.length - 1) {
        const next = value.nodes[index + 1];
        const edge = value.edges.find(item => item.from === node.id && item.to === next.id);
        const arrow = document.createElement("div");
        arrow.className = "knowledge-diagram__edge";
        arrow.textContent = edge?.label ? `${edge.label} →` : "→";
        flow.appendChild(arrow);
      }
    });
    figure.append(title, flow);
    if (value.caption) {
      const caption = document.createElement("figcaption");
      caption.textContent = value.caption;
      figure.appendChild(caption);
    }
    return figure;
  }

  function appendInlineMarkdown(container, value) {
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\\\([\s\S]+?\\\)|\$[^$\n]+\$)/g;
    let cursor = 0;
    for (const match of value.matchAll(pattern)) {
      container.appendChild(document.createTextNode(value.slice(cursor, match.index)));
      const token = match[0];
      let node;
      if (token.startsWith("**")) {
        node = document.createElement("strong");
        node.textContent = token.slice(2, -2);
      } else if (token.startsWith("`")) {
        node = document.createElement("code");
        node.textContent = token.slice(1, -1);
      } else {
        node = document.createElement("span");
        node.className = "arithmatex knowledge-math-inline";
        node.textContent = token;
      }
      container.appendChild(node);
      cursor = match.index + token.length;
    }
    container.appendChild(document.createTextNode(value.slice(cursor)));
  }

  function renderMarkdown(value) {
    const root = document.createDocumentFragment();
    const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index += 1; continue; }
      if (/^```/.test(line)) {
        const language = line.slice(3).trim();
        const codeLines = [];
        index += 1;
        while (index < lines.length && !/^```/.test(lines[index])) codeLines.push(lines[index++]);
        index += index < lines.length ? 1 : 0;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        if (language) code.dataset.language = language;
        code.textContent = codeLines.join("\n");
        pre.appendChild(code);
        root.appendChild(pre);
        continue;
      }
      if (/^\\\[$/.test(line.trim())) {
        const formula = [line.trim()];
        index += 1;
        while (index < lines.length) {
          formula.push(lines[index]);
          if (/\\\]$/.test(lines[index].trim())) { index += 1; break; }
          index += 1;
        }
        const block = document.createElement("div");
        block.className = "arithmatex knowledge-math-block";
        block.textContent = formula.join("\n");
        root.appendChild(block);
        continue;
      }
      const tableHeader = line.trim();
      const tableDivider = lines[index + 1]?.trim() || "";
      if (/^\|.*\|$/.test(tableHeader) && /^\|(?:\s*:?-{3,}:?\s*\|)+$/.test(tableDivider)) {
        const splitRow = row => row.slice(1, -1).split("|").map(cell => cell.trim());
        const headers = splitRow(tableHeader);
        const table = document.createElement("table");
        const head = document.createElement("thead");
        const headRow = document.createElement("tr");
        for (const cell of headers) {
          const th = document.createElement("th");
          appendInlineMarkdown(th, cell);
          headRow.appendChild(th);
        }
        head.appendChild(headRow);
        const body = document.createElement("tbody");
        index += 2;
        while (index < lines.length && /^\|.*\|$/.test(lines[index].trim())) {
          const cells = splitRow(lines[index].trim());
          const row = document.createElement("tr");
          for (let column = 0; column < headers.length; column += 1) {
            const td = document.createElement("td");
            appendInlineMarkdown(td, cells[column] || "");
            row.appendChild(td);
          }
          body.appendChild(row);
          index += 1;
        }
        table.append(head, body);
        const wrapper = document.createElement("div");
        wrapper.className = "knowledge-markdown-table";
        wrapper.appendChild(table);
        root.appendChild(wrapper);
        continue;
      }
      const headingMatch = line.match(/^(#{2,4})\s+(.+)$/);
      if (headingMatch) {
        const heading = document.createElement(`h${Math.min(4, headingMatch[1].length)}`);
        appendInlineMarkdown(heading, headingMatch[2]);
        root.appendChild(heading);
        index += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = document.createElement("blockquote");
        const quoteLines = [];
        while (index < lines.length && /^>\s?/.test(lines[index])) quoteLines.push(lines[index++].replace(/^>\s?/, ""));
        appendInlineMarkdown(quote, quoteLines.join("\n"));
        root.appendChild(quote);
        continue;
      }
      const listMatch = line.match(/^\s*(?:([-*])|(\d+)\.)\s+(.+)$/);
      if (listMatch) {
        const ordered = Boolean(listMatch[2]);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const itemMatch = lines[index].match(/^\s*(?:([-*])|(\d+)\.)\s+(.+)$/);
          if (!itemMatch || Boolean(itemMatch[2]) !== ordered) break;
          const item = document.createElement("li");
          appendInlineMarkdown(item, itemMatch[3]);
          list.appendChild(item);
          index += 1;
        }
        root.appendChild(list);
        continue;
      }
      const paragraphLines = [line];
      index += 1;
      while (index < lines.length && lines[index].trim() && !/^(#{2,4})\s+|^```|^>\s?|^\s*(?:[-*]|\d+\.)\s+|^\\\[$/.test(lines[index]) && !(/^\|.*\|$/.test(lines[index].trim()) && /^\|(?:\s*:?-{3,}:?\s*\|)+$/.test(lines[index + 1]?.trim() || ""))) {
        paragraphLines.push(lines[index++]);
      }
      const paragraph = document.createElement("p");
      appendInlineMarkdown(paragraph, paragraphLines.join(" "));
      root.appendChild(paragraph);
    }
    return root;
  }

  function typesetMessage(body) {
    const mathJax = window.MathJax;
    if (!body?.getClientRects().length || body.clientWidth <= 0) return;
    if (!mathJax?.typesetPromise) {
      mathJax?.startup?.promise?.then(() => typesetMessage(body)).catch(() => {});
      return;
    }
    const mathNodes = Array.from(body.querySelectorAll(".knowledge-math-inline, .knowledge-math-block"));
    if (!mathNodes.some(node => !node.querySelector("mjx-container")) || pendingMathBodies.has(body)) return;
    pendingMathBodies.add(body);
    mathTypesetQueue = mathTypesetQueue
      .catch(() => undefined)
      .then(() => {
        if (!body.isConnected || !body.getClientRects().length || body.clientWidth <= 0) return;
        const pendingNodes = Array.from(body.querySelectorAll(".knowledge-math-inline, .knowledge-math-block"));
        if (!pendingNodes.some(node => !node.querySelector("mjx-container"))) return;
        return mathJax.typesetPromise([body]);
      })
      .catch(() => undefined)
      .finally(() => pendingMathBodies.delete(body));
  }

  function typesetVisibleMessages() {
    if (!assistantPane?.getClientRects().length) return;
    assistantPane.querySelectorAll(".knowledge-rich-text").forEach(typesetMessage);
  }

  function renderRichText(element, value) {
    element.replaceChildren(renderMarkdown(value));
    requestAnimationFrame(() => typesetMessage(element));
  }

  function visualHtmlElement(value, title) {
    if (typeof value !== "string" || !value.trim()) return null;
    const frame = document.createElement("iframe");
    frame.className = "reader-visual-html";
    frame.title = title || "模型生成的交互式可视化";
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("loading", "lazy");
    const base = [
      '<meta charset="utf-8">',
      '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src \'none\'; form-action \'none\'; base-uri \'none\'">',
      '<style>html,body{margin:0;padding:0;background:transparent;color:#263238;font:14px/1.5 system-ui,sans-serif}*{box-sizing:border-box}svg,canvas,img{max-width:100%;height:auto}button,input,select{font:inherit}</style>'
    ].join("");
    const resizeBridge = '<script>(()=>{const send=()=>parent.postMessage({type:"reader-visual-height",height:Math.ceil(document.documentElement.scrollHeight)},"*");new ResizeObserver(send).observe(document.documentElement);addEventListener("load",send);send()})()<\/script>';
    frame.srcdoc = `${base}${value}${resizeBridge}`;
    const onMessage = event => {
      if (event.source !== frame.contentWindow || event.data?.type !== "reader-visual-height") return;
      const height = Math.max(120, Math.min(1200, Number(event.data.height) || 320));
      frame.style.height = `${height}px`;
    };
    window.addEventListener("message", onMessage);
    frame.addEventListener("load", () => {
      if (!frame.isConnected) window.removeEventListener("message", onMessage);
    });
    return frame;
  }

  function revisionDisplayKey() {
    return `reader-revision-display:${taskId || "reader"}:${documentId || "document"}`;
  }

  function collapsedRevisionIds() {
    try {
      const value = JSON.parse(localStorage.getItem(revisionDisplayKey()) || "[]");
      return new Set(Array.isArray(value) ? value.filter(item => typeof item === "string") : []);
    } catch (_) {
      return new Set();
    }
  }

  function saveRevisionCollapsed(revisionId, collapsed) {
    const ids = collapsedRevisionIds();
    if (collapsed) ids.add(revisionId);
    else ids.delete(revisionId);
    try {
      localStorage.setItem(revisionDisplayKey(), JSON.stringify([...ids]));
    } catch (_) {}
  }

  function setRevisionCollapsed(card, toggle, collapsed, persist = true) {
    card.classList.toggle("is-collapsed", collapsed);
    toggle.textContent = collapsed ? "展开" : "折叠";
    toggle.setAttribute("aria-expanded", String(!collapsed));
    if (persist && card.dataset.revisionId) saveRevisionCollapsed(card.dataset.revisionId, collapsed);
  }

  function revisionCard(item) {
    const card = document.createElement("aside");
    card.className = "reader-revision";
    card.dataset.revisionId = item.id || "";
    const header = document.createElement("header");
    const label = document.createElement("span");
    label.className = "reader-revision__source";
    label.textContent = item.source === "manual" ? "手动修改" : "AI 修订";
    const title = document.createElement("strong");
    title.textContent = item.title;
    header.append(label, title);
    if (item.id) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "reader-revision__toggle";
      toggle.setAttribute("aria-label", `折叠或展开：${item.title}`);
      const collapsed = collapsedRevisionIds().has(item.id);
      toggle.addEventListener("click", () => setRevisionCollapsed(card, toggle, !card.classList.contains("is-collapsed")));
      header.appendChild(toggle);
      setRevisionCollapsed(card, toggle, collapsed, false);
    }
    const content = document.createElement("div");
    content.className = "reader-revision__content knowledge-rich-text";
    renderRichText(content, item.markdown);
    card.append(header, content);
    const diagram = diagramElement(item.diagram);
    if (diagram) card.appendChild(diagram);
    const visual = visualHtmlElement(item.visual_html, item.title);
    if (visual) card.appendChild(visual);
    const footer = document.createElement("footer");
    const note = document.createElement("span");
    note.textContent = item.change_note || item.summary || "";
    footer.appendChild(note);
    if (item.id) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "恢复原文";
      remove.addEventListener("click", async () => {
        if (!window.confirm("移除这条本地修订并恢复只显示原文？")) return;
        remove.disabled = true;
        try {
          const saved = await api("/api/revision/delete", {
            method: "POST",
            body: JSON.stringify({ document_id: documentId, revision_id: item.id })
          });
          saveRevisionCollapsed(item.id, false);
          renderRevisions(saved.items || []);
        } catch (error) {
          remove.disabled = false;
          remove.textContent = error.message;
        }
      });
      footer.appendChild(remove);
    }
    card.appendChild(footer);
    return card;
  }

  function restoreManualReplacements() {
    document.querySelectorAll(".reader-manual-original").forEach(original => original.replaceWith(...original.childNodes));
    document.querySelectorAll("[data-reader-manual-hidden]").forEach(block => {
      block.classList.remove("reader-manual-block-original", "is-showing-original");
      block.removeAttribute("data-reader-manual-hidden");
    });
    document.querySelectorAll(".reader-manual-replacement").forEach(element => element.remove());
  }

  function textRange(block, start, end) {
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        return node.parentElement?.closest(".reader-manual-replacement")
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT;
      }
    });
    let offset = 0;
    let startNode = null;
    let endNode = null;
    let startOffset = 0;
    let endOffset = 0;
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const next = offset + node.data.length;
      if (!startNode && start >= offset && start <= next) {
        startNode = node;
        startOffset = start - offset;
      }
      if (end >= offset && end <= next) {
        endNode = node;
        endOffset = end - offset;
        break;
      }
      offset = next;
    }
    if (!startNode || !endNode) return null;
    const range = document.createRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    return range;
  }

  function revisionBlocks(prefix = "") {
    return Array.from(document.querySelectorAll("[data-reader-block]"))
      .filter(block => !block.querySelector("[data-reader-block]") && (!prefix || block.dataset.readerBlock?.startsWith(prefix)));
  }

  function normalizedRevisionText(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLowerCase()
      .replace(/\[[^\]]*\bpdf:[^\]]*\]/gi, "")
      .replace(/[^a-z0-9\u3400-\u9fff]+/g, "");
  }

  function revisionBigrams(value) {
    const normalized = normalizedRevisionText(value);
    const result = new Set();
    for (let index = 0; index + 1 < normalized.length; index += 1) result.add(normalized.slice(index, index + 2));
    return result;
  }

  function revisionTextSimilarity(left, right) {
    const leftText = normalizedRevisionText(left);
    const rightText = normalizedRevisionText(right);
    if (!leftText || !rightText) return 0;
    if (leftText.length >= 12 && rightText.includes(leftText)) return 1;
    if (rightText.length >= 12 && leftText.includes(rightText)) return 0.98;
    const leftPairs = revisionBigrams(leftText);
    const rightPairs = revisionBigrams(rightText);
    if (!leftPairs.size || !rightPairs.size) return leftText === rightText ? 1 : 0;
    let shared = 0;
    for (const pair of leftPairs) if (rightPairs.has(pair)) shared += 1;
    return (2 * shared) / (leftPairs.size + rightPairs.size);
  }

  function uniquelyMatchingRevisionBlock(text, prefix = "") {
    const normalized = normalizedRevisionText(text);
    if (normalized.length < 6) return null;
    const ranked = revisionBlocks(prefix)
      .map(block => ({ block, score: revisionTextSimilarity(text, block.textContent) }))
      .sort((left, right) => right.score - left.score);
    if (!ranked.length || ranked[0].score < 0.42) return null;
    if (ranked[1] && ranked[0].score - ranked[1].score < 0.08) return null;
    return ranked[0].block;
  }

  function shiftedRevisionBlock(sourceId, sourceBlock, anchorId) {
    const sourceMatch = /^([a-z]+)(\d+)$/.exec(sourceId || "");
    const currentMatch = /^([a-z]+)(\d+)$/.exec(sourceBlock?.dataset.readerBlock || "");
    const anchorMatch = /^([a-z]+)(\d+)$/.exec(anchorId || "");
    if (!sourceMatch || !currentMatch || !anchorMatch || sourceMatch[1] !== currentMatch[1] || sourceMatch[1] !== anchorMatch[1]) {
      return null;
    }
    const shifted = Number(currentMatch[2]) + Number(anchorMatch[2]) - Number(sourceMatch[2]);
    const candidateId = `${anchorMatch[1]}${String(shifted).padStart(anchorMatch[2].length, "0")}`;
    return document.querySelector(`[data-reader-block="${CSS.escape(candidateId)}"]`);
  }

  function revisionOffsetKey(item, prefix) {
    return `${item.document_sha256 || ""}:${prefix}`;
  }

  function revisionAnchorOffsets(items) {
    const counts = new Map();
    for (const item of items) {
      const targetIds = Array.isArray(item.target_blocks) ? item.target_blocks : [];
      const parts = targetIds.length > 1 ? String(item.target_text || "").split("\n\n") : [String(item.target_text || "")];
      for (let index = 0; index < Math.min(targetIds.length, parts.length); index += 1) {
        const sourceMatch = /^([a-z]+)(\d+)$/.exec(targetIds[index]);
        if (!sourceMatch) continue;
        const matched = uniquelyMatchingRevisionBlock(parts[index], sourceMatch[1]);
        const currentMatch = /^([a-z]+)(\d+)$/.exec(matched?.dataset.readerBlock || "");
        if (!currentMatch || currentMatch[1] !== sourceMatch[1]) continue;
        const key = revisionOffsetKey(item, sourceMatch[1]);
        const delta = Number(currentMatch[2]) - Number(sourceMatch[2]);
        const values = counts.get(key) || new Map();
        values.set(delta, (values.get(delta) || 0) + 1);
        counts.set(key, values);
      }
    }
    const offsets = new Map();
    for (const [key, values] of counts) {
      const ranked = [...values].sort((left, right) => right[1] - left[1]);
      if (!ranked[1] || ranked[0][1] > ranked[1][1]) offsets.set(key, ranked[0][0]);
    }
    return offsets;
  }

  function revisionAnchor(item, offsets = new Map()) {
    const anchorId = item.anchor_block_id || "";
    const targetIds = Array.isArray(item.target_blocks) ? item.target_blocks : [];
    const parts = targetIds.length > 1 ? String(item.target_text || "").split("\n\n") : [String(item.target_text || "")];
    const anchorIndex = targetIds.indexOf(anchorId);
    for (let index = parts.length - 1; index >= 0; index -= 1) {
      const sourceId = targetIds[index] || anchorId;
      const matched = uniquelyMatchingRevisionBlock(parts[index], sourceId.slice(0, 1));
      if (!matched) continue;
      if (index === anchorIndex || anchorIndex < 0) return matched;
      const shifted = shiftedRevisionBlock(sourceId, matched, anchorId);
      if (shifted) return shifted;
    }
    const anchorMatch = /^([a-z]+)(\d+)$/.exec(anchorId);
    const offset = anchorMatch ? offsets.get(revisionOffsetKey(item, anchorMatch[1])) : undefined;
    if (anchorMatch && Number.isInteger(offset)) {
      const candidateId = `${anchorMatch[1]}${String(Number(anchorMatch[2]) + offset).padStart(anchorMatch[2].length, "0")}`;
      return document.querySelector(`[data-reader-block="${CSS.escape(candidateId)}"]`);
    }
    return null;
  }

  function manualRevisionContexts(item) {
    if (Array.isArray(item.selection_contexts) && item.selection_contexts.length) {
      return item.selection_contexts.map(context => {
        const block = document.querySelector(`[data-reader-block="${CSS.escape(context.block_id || "")}"]`);
        if (block?.textContent.slice(context.start, context.end) === context.text) return context;
        const matches = revisionBlocks(context.block_id?.slice(0, 1)).filter(candidate => candidate.textContent.includes(context.text));
        if (matches.length !== 1) return null;
        const start = matches[0].textContent.indexOf(context.text);
        return { ...context, block_id: matches[0].dataset.readerBlock, start, end: start + context.text.length };
      }).filter(Boolean);
    }
    const blockIds = Array.isArray(item.target_blocks) ? item.target_blocks : [];
    const parts = blockIds.length > 1 ? String(item.target_text || "").split("\n\n") : [String(item.target_text || "")];
    return blockIds.map((blockId, index) => {
      const block = document.querySelector(`[data-reader-block="${CSS.escape(blockId)}"]`);
      const text = parts[index] || "";
      const start = block?.textContent.indexOf(text) ?? -1;
      return start < 0 ? null : { block_id: blockId, start, end: start + text.length, text };
    }).filter(Boolean);
  }

  function manualReplacementToolbar(item, replacement, originals) {
    const toolbar = document.createElement("span");
    toolbar.className = "reader-manual-replacement__toolbar";
    const status = document.createElement("span");
    status.textContent = "已手动修改";
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.textContent = "查看原文";
    reveal.addEventListener("click", () => {
      const showing = replacement.classList.toggle("is-showing-original");
      originals.forEach(original => original.classList.toggle("is-showing-original", showing));
      reveal.textContent = showing ? "隐藏原文" : "查看原文";
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "恢复";
    remove.addEventListener("click", async () => {
      if (!window.confirm("恢复为原文并删除这次手动修改？")) return;
      remove.disabled = true;
      try {
        const saved = await api("/api/revision/delete", {
          method: "POST",
          body: JSON.stringify({ document_id: documentId, revision_id: item.id })
        });
        renderRevisions(saved.items || []);
      } catch (error) {
        remove.disabled = false;
        remove.textContent = error.message;
      }
    });
    toolbar.append(status, reveal, remove);
    return toolbar;
  }

  function renderManualRevision(item) {
    const contexts = manualRevisionContexts(item);
    if (!contexts.length) return false;
    const entries = contexts.map(context => ({
      context,
      block: document.querySelector(`[data-reader-block="${CSS.escape(context.block_id)}"]`)
    })).filter(entry => entry.block);
    if (!entries.length) return false;
    const coversWholeBlocks = entries.every(({ context, block }) =>
      context.start === 0 && context.end === block.textContent.length
    );
    const blockReplacement = coversWholeBlocks || entries.length > 1;
    const replacement = document.createElement(blockReplacement ? "div" : "span");
    replacement.className = `reader-manual-replacement${blockReplacement ? " reader-manual-replacement--block" : " reader-manual-replacement--inline"}`;
    replacement.dataset.revisionId = item.id || "";
    const content = document.createElement(blockReplacement ? "div" : "span");
    content.className = "reader-manual-replacement__content knowledge-rich-text";
    renderRichText(content, item.markdown);
    const originals = [];
    if (coversWholeBlocks) {
      for (const { block } of entries) {
        block.classList.add("reader-manual-block-original");
        block.dataset.readerManualHidden = item.id || "manual";
        originals.push(block);
      }
      entries[0].block.before(replacement);
    } else if (entries.length > 1) {
      let insertionPoint = null;
      for (const { context, block } of [...entries].reverse()) {
        const range = textRange(block, context.start, context.end);
        if (!range) continue;
        const original = document.createElement("span");
        original.className = "reader-manual-original";
        original.appendChild(range.extractContents());
        range.insertNode(original);
        originals.push(original);
        insertionPoint = original;
      }
      if (!insertionPoint) return false;
      entries[0].block.before(replacement);
    } else {
      let insertionPoint = null;
      for (const { context, block } of entries) {
        const range = textRange(block, context.start, context.end);
        if (!range) continue;
        const original = document.createElement("span");
        original.className = "reader-manual-original";
        original.appendChild(range.extractContents());
        range.insertNode(original);
        originals.push(original);
        if (context === entries[0].context) insertionPoint = original;
      }
      if (!insertionPoint) return false;
      insertionPoint.after(replacement);
    }
    replacement.append(content, manualReplacementToolbar(item, replacement, originals));
    return true;
  }

  function renderRevisions(items) {
    revisions = items;
    restoreManualReplacements();
    document.querySelectorAll(".reader-revision[data-revision-id]").forEach(element => element.remove());
    const lastByAnchor = new Map();
    const latestManual = new Map();
    const anchorOffsets = revisionAnchorOffsets(items);
    for (const item of items) {
      if (item.source !== "manual") continue;
      const key = JSON.stringify([item.document_sha256, item.target_blocks, item.target_text]);
      latestManual.set(key, item.id);
    }
    for (const item of items) {
      if (item.source === "manual") {
        const key = JSON.stringify([item.document_sha256, item.target_blocks, item.target_text]);
        if (latestManual.get(key) !== item.id) continue;
        if (renderManualRevision(item)) continue;
        // If prose evolved enough that the literal selection disappeared, keep
        // the accepted wording visible as a card instead of replacing new text.
        const anchor = revisionAnchor(item, anchorOffsets);
        if (!anchor) continue;
        const card = revisionCard(item);
        const anchorId = anchor.dataset.readerBlock;
        const previous = lastByAnchor.get(anchorId);
        (previous || anchor).insertAdjacentElement("afterend", card);
        lastByAnchor.set(anchorId, card);
        continue;
      }
      // Accepted revisions survive appended or rewritten surrounding prose only
      // when their saved source text still identifies one current block.
      const anchor = revisionAnchor(item, anchorOffsets);
      if (!anchor) continue;
      const card = revisionCard(item);
      const anchorId = anchor.dataset.readerBlock;
      const previous = lastByAnchor.get(anchorId);
      (previous || anchor).insertAdjacentElement("afterend", card);
      lastByAnchor.set(anchorId, card);
    }
  }

  function showRevisionDiscussion(discussion, overlay, dialog) {
    dialog._discussion = discussion;
    const preview = dialog.querySelector(".reader-revision-editor__preview");
    preview.innerHTML = "";
    const original = document.createElement("details");
    original.className = "reader-revision-editor__original";
    const summary = document.createElement("summary");
    summary.textContent = "查看原文";
    const originalText = document.createElement("blockquote");
    originalText.textContent = discussion.target_text;
    original.append(summary, originalText);
    preview.appendChild(original);
    for (const [index, turn] of (discussion.turns || []).entries()) {
      const turnElement = document.createElement("section");
      turnElement.className = "reader-revision-turn";
      const question = document.createElement("div");
      question.className = "reader-revision-turn__question";
      question.textContent = `你的要求 ${index + 1}：${turn.instruction}`;
      const candidate = revisionCard(turn.candidate);
      const choose = document.createElement("button");
      choose.type = "button";
      choose.className = "reader-revision-turn__choose";
      choose.textContent = "选为最终修订";
      choose.addEventListener("click", async () => {
        choose.disabled = true;
        choose.textContent = "保存中…";
        try {
          const saved = await api("/api/revision/accept", {
            method: "POST",
            body: JSON.stringify({ document_id: documentId, candidate_id: turn.candidate.candidate_id })
          });
          revisionDiscussions = revisionDiscussions.filter(item => item.id !== discussion.id);
          overlay.remove();
          renderRevisions(saved.items || []);
          document.querySelector(`[data-revision-id="${CSS.escape(saved.items.at(-1)?.id || "")}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        } catch (error) {
          choose.disabled = false;
          choose.textContent = error.message;
        }
      });
      turnElement.append(question, candidate, choose);
      preview.appendChild(turnElement);
    }
    const controls = dialog.querySelector(".reader-revision-editor__controls");
    controls.querySelector('[name="instruction"]').value = "";
    controls.querySelector('[name="instruction"]').placeholder = "继续追问，例如：保留公式，但把图改成可交互版本";
    const actions = dialog.querySelector(".reader-revision-editor__actions");
    dialog._generateButton.disabled = false;
    dialog._generateButton.textContent = "发送追问并生成候选";
    actions.replaceChildren(dialog._cancelButton, dialog._deleteButton, dialog._generateButton);
    dialog.elements.instruction.focus();
  }

  function openManualRevisionEditor() {
    const selection = selectionDetails();
    if (!selection) return;
    selectionMenu.classList.remove("is-visible");
    window.getSelection()?.removeAllRanges();
    document.querySelector(".reader-revision-editor")?.remove();
    const overlay = document.createElement("div");
    overlay.className = "reader-revision-editor";
    const dialog = document.createElement("form");
    dialog.className = "reader-revision-editor__dialog reader-manual-editor";
    dialog.innerHTML = [
      "<h3>手动修改选中的正文</h3>",
      '<div class="reader-revision-editor__controls">',
      '<label>标题<input name="title" maxlength="120" value="手动修改"></label>',
      '<label>修改后的内容<textarea name="markdown" maxlength="8000" required></textarea></label>',
      '<p>直接保存为当前采用版本，不调用模型。原始 Markdown 不会被覆盖，可随时恢复原文。</p>',
      "</div>",
      '<details class="reader-revision-editor__original"><summary>查看原文</summary><blockquote></blockquote></details>',
      '<div class="reader-revision-editor__actions"><button type="button" data-action="cancel">取消</button><button type="submit" class="reader-revision-editor__primary">保存修改</button></div>'
    ].join("");
    const original = selection.contexts.map(item => item.text).join("\n\n");
    dialog.elements.markdown.value = original;
    dialog.querySelector("blockquote").textContent = original;
    dialog.querySelector('[data-action="cancel"]').addEventListener("click", () => overlay.remove());
    dialog.addEventListener("submit", async event => {
      event.preventDefault();
      const save = dialog.querySelector('[type="submit"]');
      save.disabled = true;
      save.textContent = "保存中…";
      try {
        const saved = await api("/api/revision/manual", {
          method: "POST",
          body: JSON.stringify({
            document_id: documentId,
            document_sha256: documentSha,
            contexts: selection.contexts,
            title: dialog.elements.title.value.trim(),
            markdown: dialog.elements.markdown.value.trim()
          })
        });
        overlay.remove();
        renderRevisions(saved.items || []);
        const latest = saved.items?.at(-1);
        document.querySelector(`[data-revision-id="${CSS.escape(latest?.id || "")}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      } catch (error) {
        save.disabled = false;
        save.textContent = "保存修改";
        let message = dialog.querySelector(".reader-manual-editor__error");
        if (!message) {
          message = document.createElement("p");
          message.className = "reader-manual-editor__error";
          dialog.querySelector(".reader-revision-editor__actions").before(message);
        }
        message.textContent = error.message;
      }
    });
    overlay.addEventListener("click", event => { if (event.target === overlay) overlay.remove(); });
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    dialog.elements.markdown.focus();
    dialog.elements.markdown.setSelectionRange(0, dialog.elements.markdown.value.length);
  }

  function openRevisionEditor() {
    const selection = selectionDetails();
    if (!selection) return;
    selectionMenu.classList.remove("is-visible");
    window.getSelection()?.removeAllRanges();
    document.querySelector(".reader-revision-editor")?.remove();
    const overlay = document.createElement("div");
    overlay.className = "reader-revision-editor";
    const dialog = document.createElement("form");
    dialog.className = "reader-revision-editor__dialog";
    dialog.innerHTML = [
      "<h3>编辑选中的正文</h3>",
      '<div class="reader-revision-editor__controls">',
      '<div class="reader-revision-editor__model">',
      '<label>模型<select name="model"><option value="gpt-5.6-terra">gpt-5.6-terra</option><option value="gpt-5.6-sol">gpt-5.6-sol</option></select></label>',
      '<label>推理强度<select name="effort"><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option><option value="max">max</option><option value="ultra">ultra</option></select></label>',
      "</div>",
      '<label>修改要求<textarea name="instruction" maxlength="2000" required placeholder="例如：核对这段结论的适用边界，并用一个简化图解释"></textarea></label>',
      '<p>可继续追问候选；原文不会被直接覆盖。</p>',
      "</div>",
      '<div class="reader-revision-editor__preview"></div>',
      '<div class="reader-revision-editor__actions"></div>'
    ].join("");
    dialog.elements.model.value = revisionSettings.model;
    dialog.elements.effort.value = revisionSettings.effort;
    const saveSettings = async () => {
      const previous = { ...revisionSettings };
      revisionSettings = { model: dialog.elements.model.value, effort: dialog.elements.effort.value };
      try {
        revisionSettings = await api("/api/revision/settings", {
          method: "POST",
          body: JSON.stringify(revisionSettings)
        });
      } catch (error) {
        revisionSettings = previous;
        dialog.elements.model.value = previous.model;
        dialog.elements.effort.value = previous.effort;
        dialog.querySelector(".reader-revision-editor__preview").textContent = error.message;
      }
    };
    dialog.elements.model.addEventListener("change", saveSettings);
    dialog.elements.effort.addEventListener("change", saveSettings);
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "取消";
    cancel.addEventListener("click", () => overlay.remove());
    const generate = document.createElement("button");
    generate.type = "submit";
    generate.className = "reader-revision-editor__primary";
    generate.textContent = "生成修改预览";
    const discardDiscussion = document.createElement("button");
    discardDiscussion.type = "button";
    discardDiscussion.textContent = "删除本次讨论";
    discardDiscussion.hidden = true;
    discardDiscussion.addEventListener("click", async () => {
      if (!dialog._discussion || !window.confirm("删除这次未完成的修订讨论？")) return;
      await api("/api/revision/discussion/delete", {
        method: "POST",
        body: JSON.stringify({ document_id: documentId, discussion_id: dialog._discussion.id })
      });
      revisionDiscussions = revisionDiscussions.filter(item => item.id !== dialog._discussion.id);
      overlay.remove();
    });
    dialog._cancelButton = cancel;
    dialog._generateButton = generate;
    dialog._deleteButton = discardDiscussion;
    dialog.querySelector(".reader-revision-editor__actions").append(cancel, generate);
    dialog.addEventListener("submit", async event => {
      event.preventDefault();
      generate.disabled = true;
      generate.textContent = "正在生成…";
      try {
        const candidate = await api("/api/revision/propose", {
          method: "POST",
          body: JSON.stringify({
            document_id: documentId,
            document_sha256: documentSha,
            contexts: selection.contexts,
            instruction: dialog.elements.instruction.value.trim(),
            pdf_contexts: pdfContexts,
            model: dialog.elements.model.value,
            effort: dialog.elements.effort.value,
            ...(dialog._discussion?.id ? { discussion_id: dialog._discussion.id } : {})
          })
        });
        discardDiscussion.hidden = false;
        showRevisionDiscussion(candidate, overlay, dialog);
      } catch (error) {
        generate.disabled = false;
        generate.textContent = dialog._discussion ? "发送追问并生成候选" : "生成修改预览";
        dialog.querySelector(".reader-revision-editor__preview").textContent = error.message;
      }
    });
    overlay.addEventListener("click", event => { if (event.target === overlay) overlay.remove(); });
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    const selectedIds = selection.contexts.map(item => item.block_id);
    const draft = [...revisionDiscussions].reverse().find(item =>
      item.status === "draft" && JSON.stringify(item.target_blocks) === JSON.stringify(selectedIds)
    );
    if (draft) {
      discardDiscussion.hidden = false;
      showRevisionDiscussion(draft, overlay, dialog);
    } else {
      dialog.elements.instruction.focus();
    }
  }

  function appendMessage(message) {
    const element = document.createElement("div");
    element.className = `knowledge-message knowledge-message--${message.role}`;
    if (message.id) element.dataset.messageId = message.id;
    const body = document.createElement("div");
    body.className = `knowledge-message__body${message.role === "assistant" ? " knowledge-rich-text" : ""}`;
    if (message.role === "assistant") body.appendChild(renderMarkdown(message.content));
    else body.textContent = message.content;
    element.appendChild(body);
    const diagram = diagramElement(message.visualization);
    if (diagram) element.appendChild(diagram);
    if (message.role === "user" && Array.isArray(message.contexts)) {
      for (const context of message.contexts) {
        const quote = document.createElement("button");
        quote.type = "button";
        quote.className = "knowledge-message__quote";
        const source = document.createElement("strong");
        source.textContent = `原始正文 ${context.block_id}`;
        const text = document.createElement("span");
        text.textContent = context.text;
        quote.append(source, text);
        quote.addEventListener("click", () => {
          const block = document.querySelector(`[data-reader-block="${CSS.escape(context.block_id)}"]`);
          if (!block) return;
          block.scrollIntoView({ behavior: "smooth", block: "center" });
          block.classList.remove("reader-context-highlight");
          requestAnimationFrame(() => block.classList.add("reader-context-highlight"));
          setTimeout(() => block.classList.remove("reader-context-highlight"), 2200);
        });
        element.appendChild(quote);
      }
    }
    const attachedPdfs = message.role === "user"
      ? (Array.isArray(message.pdf_contexts) ? message.pdf_contexts : [message.pdf_context]).map(validPdfContext).filter(Boolean)
      : [];
    attachedPdfs.forEach(context => element.appendChild(pdfAttachment(context)));
    if (message.role === "assistant" && message.id) {
      const actions = document.createElement("div");
      actions.className = "knowledge-message__actions";
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "保存为 FAQ";
      save.addEventListener("click", () => openFaqEditor(message));
      actions.appendChild(save);
      element.appendChild(actions);
    }
    messageList.appendChild(element);
    if (message.role === "assistant") requestAnimationFrame(() => typesetMessage(body));
    messageList.scrollTop = messageList.scrollHeight;
    return element;
  }

  function renderMessages(messages) {
    messageList.innerHTML = "";
    if (!messages.length) {
      messageList.innerHTML = '<div class="knowledge-empty">这是该文档的知识问答会话。选择正文后提问，或直接询问整篇精读。</div>';
      return;
    }
    messages.filter(message => ["user", "assistant", "system"].includes(message.role)).forEach(appendMessage);
    shouldRevealLatestMessage = true;
    requestAnimationFrame(revealLatestMessage);
  }

  function previousUserQuestion(messageId) {
    const message = messageList.querySelector(`[data-message-id="${CSS.escape(messageId)}"]`);
    let previous = message?.previousElementSibling;
    while (previous && !previous.classList.contains("knowledge-message--user")) previous = previous.previousElementSibling;
    return previous?.querySelector(".knowledge-message__body")?.textContent?.trim() || "值得保留的研究结论";
  }

  function openFaqEditor(message, faq = null) {
    document.querySelector(".knowledge-faq-editor")?.remove();
    const overlay = document.createElement("div");
    overlay.className = "knowledge-faq-editor";
    const dialog = document.createElement("form");
    dialog.className = "knowledge-faq-editor__dialog";
    dialog.innerHTML = [
      `<h3>${faq ? "编辑研究备忘录" : "保存为研究备忘录"}</h3>`,
      '<label>标题<input name="question" maxlength="300" required></label>',
      '<label>核心结论<textarea name="answer" maxlength="5000" required></textarea></label>',
      '<label>个人备注（可选）<textarea name="note" maxlength="2000" placeholder="为什么值得记住？以后在什么场景使用？"></textarea></label>',
      '<div class="knowledge-faq-editor__actions"><button type="button" data-action="cancel">取消</button><button type="submit">保存</button></div>'
    ].join("");
    dialog.elements.question.value = faq?.question || previousUserQuestion(message.id).slice(0, 300);
    dialog.elements.answer.value = faq?.answer || message.content.slice(0, 5000);
    dialog.elements.note.value = faq?.note || "";
    dialog.querySelector('[data-action="cancel"]').addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", event => { if (event.target === overlay) overlay.remove(); });
    dialog.addEventListener("submit", async event => {
      event.preventDefault();
      const submit = dialog.querySelector('[type="submit"]');
      submit.disabled = true;
      submit.textContent = "保存中…";
      try {
        const saved = await api(faq ? "/api/faq/edit" : "/api/faq/save-message", {
          method: "POST",
          body: JSON.stringify({
            document_id: documentId,
            ...(faq ? { faq_id: faq.id } : { message_id: message.id }),
            question: dialog.elements.question.value.trim(),
            answer: dialog.elements.answer.value.trim(),
            note: dialog.elements.note.value.trim()
          })
        });
        overlay.remove();
        renderFaq({ faq: saved, pending: pendingFaq });
        switchTab("faq");
      } catch (error) {
        submit.disabled = false;
        submit.textContent = "保存";
        dialog.querySelector(".knowledge-error")?.remove();
        const errorBox = document.createElement("div");
        errorBox.className = "knowledge-error";
        errorBox.textContent = error.message;
        dialog.prepend(errorBox);
      }
    });
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    dialog.elements.question.focus();
  }

  function renderContexts() {
    contextList.innerHTML = "";
    contexts.forEach((context, index) => {
      const item = document.createElement("div");
      item.className = "knowledge-context";
      const text = document.createElement("div");
      text.className = "knowledge-context__text";
      text.textContent = `原始正文 ${context.block_id}: ${context.text}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "移除";
      remove.addEventListener("click", () => {
        contexts.splice(index, 1);
        renderContexts();
      });
      item.append(text, remove);
      contextList.appendChild(item);
    });
    pdfContexts.forEach((pdfContext, index) => {
      const item = document.createElement("div");
      item.className = "knowledge-context";
      item.innerHTML = `<div class="knowledge-context__text">PDF 整页图像：${pdfContext.source_id} · 物理页 ${pdfContext.page}</div>`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "移除";
      remove.addEventListener("click", () => {
        pdfContexts.splice(index, 1);
        renderContexts();
      });
      item.appendChild(remove);
      contextList.appendChild(item);
    });
  }

  function renderFaq(state) {
    const list = faqPane.querySelector(".knowledge-faq-list");
    list.innerHTML = "";
    pendingFaq = null;
    const saved = state.faq?.items || [];
    const heading = document.createElement("h3");
    heading.textContent = "已固化知识";
    list.appendChild(heading);
    if (!saved.length) list.insertAdjacentHTML("beforeend", '<div class="knowledge-empty">尚未固化 FAQ。</div>');
    saved.forEach(item => list.appendChild(faqItem(item, false)));
    filterFaqItems();
    syncFaqToDocument(saved);
  }

  function filterFaqItems() {
    if (!faqPane || !faqSearchCount) return;
    const query = faqSearchInput?.value.trim().toLocaleLowerCase() || "";
    const cards = [...faqPane.querySelectorAll(".knowledge-faq-item")];
    let visible = 0;
    for (const card of cards) {
      const matched = !query || card.dataset.searchText.includes(query);
      card.hidden = !matched;
      if (matched) visible += 1;
      const details = card.querySelector("details");
      if (details) details.open = Boolean(query && matched);
    }
    faqSearchCount.textContent = query ? `${visible}/${cards.length} 条` : `${cards.length} 条`;
  }

  function syncFaqToDocument(items) {
    let section = document.querySelector("#reader-personal-faq");
    if (!items.length) {
      section?.remove();
      return;
    }
    if (!section) {
      section = document.createElement("section");
      section.id = "reader-personal-faq";
      document.querySelector(".md-content__inner")?.appendChild(section);
    }
    section.innerHTML = "";
    const collection = document.createElement("details");
    collection.className = "reader-personal-notes";
    const collectionSummary = document.createElement("summary");
    const title = document.createElement("span");
    title.textContent = "我的个人备忘录";
    const count = document.createElement("small");
    count.textContent = `${items.length} 条 · 默认折叠，不属于论文正文`;
    collectionSummary.append(title, count);
    const intro = document.createElement("p");
    intro.className = "reader-personal-notes__intro";
    intro.textContent = "这些内容保留你的具体追问和复习线索；可迁移的通用解释应回填到正文第一次出现处。";
    collection.append(collectionSummary, intro);
    items.forEach(item => {
      const details = document.createElement("details");
      details.className = "reader-faq-details";
      const question = document.createElement("summary");
      question.textContent = item.question;
      const answer = document.createElement("div");
      answer.className = "knowledge-faq-answer knowledge-rich-text";
      renderRichText(answer, item.answer);
      details.append(question, answer);
      const diagram = diagramElement(item.visualization);
      if (diagram) details.appendChild(diagram);
      if (item.note) {
        const note = document.createElement("blockquote");
        note.className = "knowledge-faq-note";
        note.textContent = `个人备注：${item.note}`;
        details.appendChild(note);
      }
      collection.appendChild(details);
    });
    section.appendChild(collection);
  }

  function faqItem(item, selectable, index) {
    const element = document.createElement("article");
    element.className = "knowledge-faq-item";
    element.dataset.searchText = [item.question, item.answer, item.note, ...(item.evidence || []).map(entry => `${entry.source_id} ${entry.page}`)]
      .filter(Boolean).join(" ").toLocaleLowerCase();
    if (selectable) {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = true;
      checkbox.dataset.faqIndex = String(index);
      element.appendChild(checkbox);
    }
    const details = document.createElement("details");
    const question = document.createElement("summary");
    question.className = "knowledge-faq-question";
    question.textContent = item.question;
    const answer = document.createElement("div");
    answer.className = "knowledge-faq-answer knowledge-rich-text";
    renderRichText(answer, item.answer);
    const evidence = document.createElement("small");
    evidence.textContent = (item.evidence || []).map(entry => `${entry.source_id} p.${entry.page}`).join(" · ") || item.knowledge_type;
    details.append(question, answer);
    const diagram = diagramElement(item.visualization);
    if (diagram) details.appendChild(diagram);
    if (item.note) {
      const note = document.createElement("div");
      note.className = "knowledge-faq-note";
      note.textContent = `个人备注：${item.note}`;
      details.appendChild(note);
    }
    details.appendChild(evidence);
    if (!selectable) {
      const actions = document.createElement("div");
      actions.className = "knowledge-faq-item__actions";
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "knowledge-faq__edit";
      edit.textContent = "编辑";
      edit.addEventListener("click", () => openFaqEditor({ id: item.source_message_id || "", content: item.answer }, item));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "knowledge-faq__delete";
      remove.textContent = "删除这条 FAQ";
      remove.addEventListener("click", () => deleteFaq(item, remove));
      actions.append(edit, remove);
      details.appendChild(actions);
    }
    element.appendChild(details);
    return element;
  }

  function selectedThread() {
    return chatThreads.find(thread => thread.id === selectedThreadId) || null;
  }

  function applyKnowledgeSettings(value) {
    if (!value || !knowledgeModelSelect || !knowledgeEffortSelect) return;
    const model = ["gpt-5.6-terra", "gpt-5.6-sol"].includes(value.model)
      ? value.model
      : "gpt-5.6-terra";
    const effort = ["medium", "high", "xhigh", "max", "ultra"].includes(value.effort)
      ? value.effort
      : "medium";
    knowledgeSettings = { model, effort };
    knowledgeModelSelect.value = model;
    knowledgeEffortSelect.value = effort;
  }

  function queueKnowledgeSettingsSave() {
    const requested = {
      model: knowledgeModelSelect.value,
      effort: knowledgeEffortSelect.value
    };
    const requestedDocumentId = documentId;
    knowledgeSettingsTouched = true;
    const version = ++knowledgeSettingsVersion;
    knowledgeSettingsSave = knowledgeSettingsSave
      .catch(() => undefined)
      .then(() => api("/api/chat/settings", {
        method: "POST",
        body: JSON.stringify({ document_id: requestedDocumentId, ...requested })
      }))
      .then(saved => {
        if (version !== knowledgeSettingsVersion || requestedDocumentId !== documentId) return;
        knowledgeSettings = { model: saved.model, effort: saved.effort };
        applyKnowledgeSettings(saved);
      })
      .catch(error => {
        if (version === knowledgeSettingsVersion && requestedDocumentId === documentId) {
          applyKnowledgeSettings(knowledgeSettings);
          sessionLabel.textContent = error.message;
        }
      });
    return knowledgeSettingsSave;
  }

  function renderThreadControls() {
    threadSelect.innerHTML = "";
    if (!chatThreads.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "尚无对话";
      threadSelect.appendChild(option);
    } else {
      chatThreads.forEach(thread => {
        const option = document.createElement("option");
        option.value = thread.id;
        option.textContent = `${thread.status === "archived" ? "[已归档] " : ""}${thread.title || "未命名对话"} · ${thread.message_count || 0} 条`;
        threadSelect.appendChild(option);
      });
    }
    threadSelect.value = selectedThreadId || "";
    const current = selectedThread();
    const writable = Boolean(current && current.id === activeThreadId && current.status !== "archived");
    archiveThreadButton.disabled = !writable;
    archiveThreadButton.hidden = !current;
    deleteThreadButton.disabled = !current;
    deleteThreadButton.hidden = !current;
    questionInput.disabled = !writable;
    assistantPane.querySelector('[data-action="send"]').disabled = !writable;
    assistantPane.querySelector('[data-action="add-pdf"]').disabled = !writable;
    knowledgeModelSelect.disabled = !writable;
    knowledgeEffortSelect.disabled = !writable;
    questionInput.placeholder = writable
      ? "针对当前文档提问。可先在正文中选中文字加入上下文。"
      : "该对话已归档，只能查看历史；请新建对话后继续提问。";
  }

  function applyChatState(state) {
    activeThreadId = state.active_thread_id || null;
    selectedThreadId = state.selected_thread_id || state.thread?.id || null;
    chatThreads = state.threads || [];
    if (!chatThreads.length && (state.session || state.messages?.length)) {
      const compatibilityId = "legacy-ui-state";
      chatThreads = [{
        id: compatibilityId,
        title: "历史对话",
        status: "open",
        session_id: state.session?.session_id || null,
        message_count: (state.messages || []).filter(message => message.role === "user" || message.role === "assistant").length
      }];
      activeThreadId = compatibilityId;
      selectedThreadId = compatibilityId;
    }
    currentSessionId = state.session?.session_id || null;
    if (state.thread?.session_id) currentSessionId = state.thread.session_id;
    renderThreadControls();
    restoreSessionLabel();
    renderMessages(state.messages || []);
  }

  async function loadState(threadId = "") {
    const requestedDocumentId = documentId;
    const settingsVersion = knowledgeSettingsVersion;
    const query = new URLSearchParams({ document_id: documentId });
    if (threadId) query.set("thread_id", threadId);
    const state = await api(`/api/state?${query}`, { method: "GET" });
    if (requestedDocumentId !== documentId) return;
    applyChatState(state);
    renderFaq(state);
    renderRevisions(state.revisions?.items || []);
    if (state.revision_settings?.model && state.revision_settings?.effort) {
      revisionSettings = state.revision_settings;
    }
    if (
      state.knowledge_settings?.model
      && state.knowledge_settings?.effort
      && !knowledgeSettingsTouched
      && settingsVersion === knowledgeSettingsVersion
    ) {
      applyKnowledgeSettings(state.knowledge_settings);
    }
    revisionDiscussions = state.revision_discussions?.items || [];
  }

  async function selectChatThread(threadId) {
    if (!threadId || threadId === selectedThreadId) return;
    try {
      await loadState(threadId);
    } catch (error) {
      sessionLabel.textContent = error.message;
      threadSelect.value = selectedThreadId || "";
    }
  }

  async function createNewThread() {
    const current = selectedThread();
    const warning = current && current.id === activeThreadId && current.status !== "archived" && (current.message_count || 0) > 0
      ? "新建对话后，当前对话会归档为只读历史。继续吗？"
      : "新建一个独立的 Codex 对话？";
    if (!window.confirm(warning)) return;
    newThreadButton.disabled = true;
    try {
      const state = await api("/api/chat/new", {
        method: "POST",
        body: JSON.stringify({ document_id: documentId })
      });
      currentSessionId = null;
      applyChatState(state);
      contexts = [];
      pdfContexts = [];
      renderContexts();
      questionInput.focus();
    } catch (error) {
      sessionLabel.textContent = error.message;
    } finally {
      newThreadButton.disabled = false;
    }
  }

  async function archiveCurrentThread() {
    const current = selectedThread();
    if (!current || current.id !== activeThreadId || current.status === "archived") return;
    if (!window.confirm("归档后该对话保留在页面中，但不能再继续调用 Codex。继续吗？")) return;
    archiveThreadButton.disabled = true;
    try {
      const state = await api("/api/chat/archive", {
        method: "POST",
        body: JSON.stringify({ document_id: documentId, thread_id: current.id })
      });
      currentSessionId = current.session_id || null;
      applyChatState(state);
    } catch (error) {
      sessionLabel.textContent = error.message;
      renderThreadControls();
    }
  }

  async function deleteCurrentThread() {
    const current = selectedThread();
    if (!current) return;
    const title = current.title || "当前对话";
    if (!window.confirm(`确定永久删除“${title}”吗？\n\n该 Session 的全部问题、回答和上下文都会被删除，且无法恢复。`)) return;
    deleteThreadButton.disabled = true;
    try {
      const state = await api("/api/chat/delete", {
        method: "POST",
        body: JSON.stringify({ document_id: documentId, thread_id: current.id })
      });
      currentSessionId = state.thread?.session_id || null;
      contexts = [];
      pdfContexts = [];
      renderContexts();
      applyChatState(state);
    } catch (error) {
      sessionLabel.textContent = error.message;
      renderThreadControls();
    }
  }

  function selectionDetails() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const startElement = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
    const endElement = range.endContainer.nodeType === Node.ELEMENT_NODE ? range.endContainer : range.endContainer.parentElement;
    const startBlock = startElement?.closest("[data-reader-block]");
    const endBlock = endElement?.closest("[data-reader-block]");
    const article = startBlock?.closest(".md-content__inner");
    if (!startBlock || !endBlock || !article || endBlock.closest(".md-content__inner") !== article) return null;
    const blocks = Array.from(article.querySelectorAll("[data-reader-block]"));
    const startIndex = blocks.indexOf(startBlock);
    const endIndex = blocks.indexOf(endBlock);
    if (startIndex < 0 || endIndex < startIndex || endIndex - startIndex >= 48) return null;
    const selected = [];
    let total = 0;
    for (const block of blocks.slice(startIndex, endIndex + 1)) {
      // Ignore annotated ancestors when a table cell or other nested block is
      // selected; otherwise the same visible text would be sent twice.
      if (blocks.slice(startIndex, endIndex + 1).some(candidate => candidate !== block && block.contains(candidate))) continue;
      const intersection = document.createRange();
      intersection.selectNodeContents(block);
      if (block === startBlock || block.contains(range.startContainer)) intersection.setStart(range.startContainer, range.startOffset);
      if (block === endBlock || block.contains(range.endContainer)) intersection.setEnd(range.endContainer, range.endOffset);
      const text = originalRangeText(intersection);
      if (!text.trim()) continue;
      const prefix = document.createRange();
      prefix.selectNodeContents(block);
      prefix.setEnd(intersection.startContainer, intersection.startOffset);
      const start = originalRangeText(prefix).length;
      total += text.length;
      selected.push({ block_id: block.dataset.readerBlock, start, end: start + text.length, text });
    }
    if (!selected.length || total > 20_000) return null;
    return { contexts: selected, rect: range.getBoundingClientRect() };
  }

  function originalRangeText(range) {
    const holder = document.createElement("div");
    holder.appendChild(range.cloneContents());
    holder.querySelectorAll(".reader-manual-replacement, .reader-revision").forEach(element => element.remove());
    return holder.textContent || "";
  }

  function selectionTouchesRevision(range) {
    const start = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
    const end = range.endContainer.nodeType === Node.ELEMENT_NODE ? range.endContainer : range.endContainer.parentElement;
    if (start?.closest(".reader-revision, .reader-manual-replacement") || end?.closest(".reader-revision, .reader-manual-replacement")) return true;
    return Array.from(document.querySelectorAll(".reader-revision, .reader-manual-replacement:not(.is-showing-original)"))
      .some(element => range.intersectsNode(element));
  }

  let selectionTimer;
  function scheduleSelectionMenu() {
    clearTimeout(selectionTimer);
    selectionTimer = setTimeout(() => {
      const rawSelection = window.getSelection();
      const rawRange = rawSelection && rawSelection.rangeCount === 1 && !rawSelection.isCollapsed
        ? rawSelection.getRangeAt(0)
        : null;
      if (rawRange && selectionTouchesRevision(rawRange)) {
        selectionMenu?.classList.remove("is-visible");
        const rect = rawRange.getBoundingClientRect();
        selectionNotice.style.left = `${Math.max(8, Math.min(window.innerWidth - 360, rect.left))}px`;
        selectionNotice.style.top = `${Math.max(50, rect.bottom + 8)}px`;
        selectionNotice.classList.add("is-visible");
        return;
      }
      selectionNotice?.classList.remove("is-visible");
      const selection = selectionDetails();
      if (!selection || !documentId) {
        selectionMenu?.classList.remove("is-visible");
        return;
      }
      selectionMenu.style.left = `${Math.max(8, Math.min(window.innerWidth - 280, selection.rect.left))}px`;
      selectionMenu.style.top = `${Math.max(50, selection.rect.bottom + 8)}px`;
      selectionMenu.classList.add("is-visible");
    }, 60);
  }

  function captureSelection() {
    const selection = selectionDetails();
    if (!selection) return;
    const additions = selection.contexts.filter(context =>
      !contexts.some(item => item.block_id === context.block_id && item.start === context.start && item.end === context.end)
    );
    const nextLength = contexts.reduce((sum, context) => sum + context.text.length, 0)
      + additions.reduce((sum, context) => sum + context.text.length, 0);
    if (contexts.length + additions.length > 48 || nextLength > 20_000) {
      selectionMenu.querySelector('[data-action="context"]').textContent = "选区过长，请缩短";
      setTimeout(() => {
        const button = selectionMenu?.querySelector('[data-action="context"]');
        if (button) button.textContent = "加入问答";
      }, 1800);
      return;
    }
    contexts.push(...additions);
    selectionMenu.classList.remove("is-visible");
    window.getSelection()?.removeAllRanges();
    renderContexts();
    switchTab("assistant");
  }

  function addPdfContext() {
    if (!currentPdfContext && window.__readerPdfContext?.sourceId) {
      currentPdfContext = {
        source_id: window.__readerPdfContext.sourceId,
        page: window.__readerPdfContext.page
      };
    }
    if (!currentPdfContext) {
      contextList.insertAdjacentHTML("afterbegin", '<div class="knowledge-error">请先在“论文 PDF”标签打开一个固定来源。</div>');
      return;
    }
    if (!pdfContexts.some(item => item.source_id === currentPdfContext.source_id && item.page === currentPdfContext.page)) {
      if (pdfContexts.length >= 6) {
        contextList.insertAdjacentHTML("afterbegin", '<div class="knowledge-error">每轮最多加入 6 个 PDF 页面。</div>');
        return;
      }
      pdfContexts.push({ ...currentPdfContext });
    }
    renderContexts();
  }

  function setBusy(busy, label) {
    assistantPane.querySelector('[data-action="send"]').disabled = busy;
    threadSelect.disabled = busy;
    archiveThreadButton.disabled = busy;
    deleteThreadButton.disabled = busy;
    newThreadButton.disabled = busy;
    knowledgeModelSelect.disabled = busy;
    knowledgeEffortSelect.disabled = busy;
    if (label) sessionLabel.textContent = label;
  }

  function restoreSessionLabel() {
    const current = selectedThread();
    if (current?.status === "archived" || (current && current.id !== activeThreadId)) {
      sessionLabel.textContent = "只读";
      sessionLabel.title = current.session_id ? `Codex Session：${current.session_id}` : "只读历史";
    } else {
      sessionLabel.textContent = currentSessionId ? currentSessionId.slice(0, 8) : "未连接";
      sessionLabel.title = currentSessionId ? `Codex Session：${currentSessionId}` : "新对话尚未调用 Codex";
    }
  }

  async function sendQuestion() {
    const question = questionInput.value.trim();
    const current = selectedThread();
    if (!question || !current || current.id !== activeThreadId || current.status === "archived") return;
    const sentContexts = contexts.map(context => ({ ...context }));
    const sentPdfContexts = pdfContexts.map(context => ({ ...context }));
    contexts = [];
    pdfContexts = [];
    questionInput.value = "";
    renderContexts();
    if (messageList.querySelector(".knowledge-empty")) messageList.innerHTML = "";
    const pendingMessage = {
      id: `pending-${Date.now()}`,
      role: "user",
      content: question,
      contexts: sentContexts,
      pdf_contexts: sentPdfContexts
    };
    const pendingElement = appendMessage(pendingMessage);
    pendingElement.classList.add("is-pending");
    setBusy(true, "回答中…");
    try {
      await knowledgeSettingsSave;
      const result = await api("/api/ask", {
        method: "POST",
        body: JSON.stringify({
          document_id: documentId,
          document_sha256: documentSha,
          thread_id: selectedThreadId,
          question,
          contexts: sentContexts,
          pdf_contexts: sentPdfContexts,
          model: knowledgeModelSelect.value,
          effort: knowledgeEffortSelect.value
        })
      });
      pendingElement.classList.remove("is-pending");
      const userMessage = result.messages.find(message => message.role === "user");
      if (userMessage?.id) pendingElement.dataset.messageId = userMessage.id;
      result.messages.filter(message => message.role === "assistant").forEach(appendMessage);
      activeThreadId = result.active_thread_id || result.thread_id || activeThreadId;
      selectedThreadId = result.thread_id || selectedThreadId;
      if (Array.isArray(result.threads)) chatThreads = result.threads;
      currentSessionId = result.session_id;
      if (result.knowledge_settings) applyKnowledgeSettings(result.knowledge_settings);
      renderThreadControls();
      restoreSessionLabel();
      requestAnimationFrame(() => revealMessage(messageList.lastElementChild, "smooth"));
    } catch (error) {
      pendingElement.classList.remove("is-pending");
      appendMessage({ role: "system", content: `Codex 调用失败：${error.message}` });
      sessionLabel.textContent = error.message;
    } finally {
      setBusy(false);
      renderThreadControls();
    }
  }

  async function deleteFaq(item, button) {
    if (!item.id || !window.confirm(`确定删除这条 FAQ？\n\n${item.question}`)) return;
    button.disabled = true;
    button.textContent = "正在删除…";
    try {
      const saved = await api("/api/faq/delete", {
        method: "POST",
        body: JSON.stringify({ document_id: documentId, faq_id: item.id })
      });
      renderFaq({ faq: saved, pending: pendingFaq });
    } catch (error) {
      button.disabled = false;
      button.textContent = "删除这条 FAQ";
      faqPane.querySelector(".knowledge-faq-list").insertAdjacentHTML("afterbegin", `<div class="knowledge-error">${error.message}</div>`);
    }
  }

  async function initializePage() {
    const metadata = document.querySelector(".reader-document-meta");
    const nextDocumentId = metadata?.dataset.documentId;
    const nextDocumentSha = metadata?.dataset.documentSha256;
    const panel = document.querySelector(".evidence-panel");
    if (!nextDocumentId || !panel || panel === initializedPanel || !createUi()) return;
    initializedPanel = panel;
    documentId = nextDocumentId;
    documentSha = nextDocumentSha;
    knowledgeSettings = { model: "gpt-5.6-terra", effort: "medium" };
    knowledgeSettingsTouched = false;
    knowledgeSettingsVersion += 1;
    knowledgeSettingsSave = Promise.resolve();
    if (window.__readerPdfContext?.sourceId) {
      currentPdfContext = {
        source_id: window.__readerPdfContext.sourceId,
        page: window.__readerPdfContext.page
      };
    }
    try {
      const bootstrap = await fetch("/api/bootstrap", { cache: "no-store" }).then(response => response.json());
      token = bootstrap.token;
      taskId = bootstrap.task_id;
      await loadState();
    } catch (error) {
      sessionLabel.textContent = "知识问答服务未启动；请使用 ./serve.sh。";
    }
  }

  window.addEventListener("reader:evidence-panel-ready", initializePage);
  window.addEventListener("reader:pdf-context", event => {
    if (event.detail?.sourceId && Number.isFinite(event.detail.page)) {
      currentPdfContext = { source_id: event.detail.sourceId, page: event.detail.page };
    }
  });
  if (typeof document$ !== "undefined") document$.subscribe(initializePage);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initializePage);
  else initializePage();
})();
