import * as pdfjsLib from "../vendor/pdfjs/pdf.mjs";
import { locateBlocks, locationLabel } from "./source-locator.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "../vendor/pdfjs/pdf.worker.mjs",
  import.meta.url
).href;

const params = new URLSearchParams(window.location.search);
const file = params.get("file");
const sourceId = params.get("source_id") || "";
const citationLocator = (params.get("locator") || "").trim();
let pageNumber = Math.max(1, Number.parseInt(params.get("page") || "1", 10));
let scaleMode = "fit";
let manualScale = 1;
let pdfDocument;
let fileUrl;
let pageRecords = [];
let pageObserver;
let resizeTimer;
let scrollFrame;
let pageDetectionSuspended = false;
let pageDetectionGeneration = 0;
let readerToken;
let translationBusy = false;
let translationRequestId = 0;
let translationPanelOpen = false;
let fullTranslationRunning = false;
let fullTranslationStopRequested = false;
let fullTranslationTimer;
let fullTranslationStatusState;
let statusHintTimer;
let citationCentered = false;

const blockTypeLabels = {
  heading: "标题",
  paragraph: "正文",
  caption: "图注",
  figure: "图片",
  table: "表格",
  table_row: "表格行",
  equation: "公式",
  footnote: "脚注",
  reference: "参考文献",
  other: "内容"
};

const viewportElement = document.querySelector("#viewport");
const pagesElement = document.querySelector("#pages");
const statusElement = document.querySelector("#status");
const pageInput = document.querySelector("#page-number");
const pageCount = document.querySelector("#page-count");
const previousButton = document.querySelector("#previous");
const nextButton = document.querySelector("#next");
const zoomLabel = document.querySelector("#zoom-label");
const openOriginal = document.querySelector("#open-original");
const translatePageButton = document.querySelector("#translate-page");
const translateAllButton = document.querySelector("#translate-all");
const fullTranslationProgress = document.querySelector("#full-translation-progress");
const fullTranslationStatus = document.querySelector("#full-translation-status");
const fullTranslationStatusTitle = document.querySelector("#full-translation-status-title");
const fullTranslationElapsed = document.querySelector("#full-translation-elapsed");
const fullTranslationMeter = document.querySelector("#full-translation-meter");
const fullTranslationDetail = document.querySelector("#full-translation-detail");
const translationPanel = document.querySelector("#translation-panel");
const translationResizer = document.querySelector("#translation-resizer");
const translationTitle = document.querySelector("#translation-title");
const translationState = document.querySelector("#translation-state");
const translationContent = document.querySelector("#translation-content");
const retranslatePageButton = document.querySelector("#retranslate-page");
const closeTranslationButton = document.querySelector("#close-translation");
const showSourceToggle = document.querySelector("#show-source");
const translationWidthKey = "research-reader-translation-width";
const translationSourceKey = "research-reader-translation-show-source";
const combiningMathDisplayReplacements = new Map([
  ["\u20d0", "↼"],
  ["\u20d1", "⇀"],
  ["\u20d6", "←"],
  ["\u20d7", "→"],
  ["\u20e1", "↔"]
]);

function readableMathText(value) {
  return String(value ?? "").replace(/[\u20d0-\u20ff]/gu, character => (
    combiningMathDisplayReplacements.get(character)
      || `[U+${character.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}]`
  ));
}

function showError(message) {
  clearTimeout(statusHintTimer);
  statusElement.textContent = message;
  statusElement.classList.add("is-error");
  statusElement.hidden = false;
}

function showStatusHint(message) {
  clearTimeout(statusHintTimer);
  statusElement.textContent = message;
  statusElement.classList.remove("is-error");
  statusElement.hidden = false;
  statusHintTimer = setTimeout(() => {
    statusElement.hidden = true;
  }, 2200);
}

function blockOrdinal(block) {
  const match = String(block.id || "").match(/-[bcft](\d+)$/i);
  return match ? Number(match[1]) : 0;
}

function blockLabel(block) {
  const name = blockTypeLabels[block.type] || "内容";
  const ordinal = blockOrdinal(block);
  const reference = (block.refs || []).find(ref => /^(figure|fig|table|tab)[-_ ]?\d+$/i.test(String(ref)));
  if (reference) {
    const match = String(reference).match(/^(figure|fig|table|tab)[-_ ]?(\d+)$/i);
    if (match) {
      const prefix = /^(figure|fig)$/i.test(match[1]) ? "图" : "表";
      if (block.type === "caption") return `${prefix} ${match[2]} 图注`;
      if (block.type === "figure") return `${prefix} ${match[2]}`;
      if (block.type === "table" || block.type === "table_row") return `${prefix} ${match[2]}${block.type === "table_row" ? " · 表格行" : ""}`;
    }
  }
  if (!ordinal) return name;
  if (block.type === "paragraph") return `正文第 ${ordinal} 段`;
  if (block.type === "caption") return `图注第 ${ordinal} 项`;
  if (block.type === "table_row") return `表格第 ${ordinal} 行`;
  return `${name}第 ${ordinal} 项`;
}

function blockConfidenceLabel(confidence) {
  return { high: "高置信度", medium: "中置信度", low: "低置信度" }[confidence] || "中置信度";
}

function setRecordBlocks(record, blocks) {
  if (!record) return;
  record.translationBlocks = Array.isArray(blocks) ? blocks : [];
  if (!record.translationBlocks.some(block => block.id === record.selectedBlockId)) {
    record.selectedBlockId = null;
  }
  updateBlockOverlay(record);
}

async function addTextLayerLocations(record, blocks) {
  if (await locateBlocks(record, blocks)) {
    updateBlockOverlay(record);
    refreshLocationBadges(blocks);
  }
}

function refreshLocationBadges(blocks) {
  for (const block of blocks) {
    translationContent.querySelectorAll(`[data-block-id="${CSS.escape(block.id || "page")}"] .translation-block__location`)
      .forEach(badge => {
        badge.textContent = locationLabel(block);
        badge.className = `translation-block__location is-${block.location_match === "visual-text-fuzzy" ? "fuzzy" : (Array.isArray(block.bbox) ? "exact" : "page")}`;
      });
  }
}

function updateBlockOverlay(record) {
  if (!record?.blockOverlay) return;
  record.blockOverlay.replaceChildren();
  if (Array.isArray(record.citationBox)) {
    const rectangle = record.page.getViewport({ scale: scaleFor(record) }).convertToViewportRectangle(record.citationBox);
    const marker = document.createElement("div");
    marker.className = "pdf-citation-highlight";
    marker.title = `引用位置：${citationLocator}`;
    marker.style.left = `${Math.min(rectangle[0], rectangle[2])}px`;
    marker.style.top = `${Math.min(rectangle[1], rectangle[3])}px`;
    marker.style.width = `${Math.abs(rectangle[2] - rectangle[0])}px`;
    marker.style.height = `${Math.abs(rectangle[3] - rectangle[1])}px`;
    record.blockOverlay.appendChild(marker);
  }
  const viewport = record.page.getViewport({ scale: scaleFor(record) });
  for (const block of record.translationBlocks || []) {
    if (!Array.isArray(block.bbox) || block.bbox.length !== 4) continue;
    const rectangle = viewport.convertToViewportRectangle(block.bbox);
    const left = Math.min(rectangle[0], rectangle[2]);
    const top = Math.min(rectangle[1], rectangle[3]);
    const width = Math.abs(rectangle[2] - rectangle[0]);
    const height = Math.abs(rectangle[3] - rectangle[1]);
    if (!(width > 0 && height > 0)) continue;
    const highlight = document.createElement("button");
    highlight.type = "button";
    highlight.className = "pdf-block-highlight";
    highlight.classList.toggle("is-selected", block.id === record.selectedBlockId);
    highlight.dataset.blockId = block.id;
    highlight.title = `${blockLabel(block)} · ${block.id}`;
    highlight.style.left = `${left}px`;
    highlight.style.top = `${top}px`;
    highlight.style.width = `${width}px`;
    highlight.style.height = `${height}px`;
    highlight.addEventListener("click", () => focusPdfBlock(block, "pdf"));
    record.blockOverlay.appendChild(highlight);
  }
}

function locatorPattern(locator) {
  const escaped = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  let match = locator.match(/^§+\s*([\w.\-]+)/i) || locator.match(/^(?:sec(?:tion)?)\.?\s*([\w.\-]+)/i);
  if (match) return new RegExp(`^\\s*${escaped(match[1])}(?:\\s|$)`, "i");
  match = locator.match(/^(fig(?:ure)?|table|eq(?:uation)?|algorithm|app(?:endix)?)\.?\s*([\w.()\-]+)/i);
  if (!match) return null;
  const names = {
    fig: "fig(?:ure)?", figure: "fig(?:ure)?", table: "table",
    eq: "eq(?:uation)?", equation: "eq(?:uation)?", algorithm: "algorithm",
    app: "app(?:endix)?", appendix: "app(?:endix)?"
  };
  return new RegExp(`\\b${names[match[1].toLowerCase()]}\\.?\\s*${escaped(match[2])}\\b`, "i");
}

async function locateCitation(record) {
  if (!citationLocator || record.number !== pageNumber || Array.isArray(record.citationBox)) return;
  const pattern = locatorPattern(citationLocator);
  if (!pattern) return;
  record.textContentPromise ||= record.page.getTextContent();
  const content = await record.textContentPromise;
  const item = content.items.find(candidate => pattern.test(String(candidate.str || "")));
  if (!item) return;
  const x = item.transform[4];
  const baseline = item.transform[5];
  const height = item.height || Math.hypot(item.transform[2], item.transform[3]);
  record.citationBox = [x, baseline, x + item.width, baseline + height];
  updateBlockOverlay(record);
  if (!citationCentered) {
    citationCentered = true;
    centerPdfBox(record, record.citationBox, "auto");
  }
  showStatusHint(`已定位引用：${citationLocator}`);
}

function selectRenderedBlock(blockId) {
  translationContent.querySelectorAll(".translation-block").forEach(article => {
    article.classList.toggle("is-selected", article.dataset.blockId === blockId);
  });
}

function centerTranslationBlock(blockId, behavior = "smooth") {
  const escaped = CSS.escape(blockId || "page");
  const element = translationContent.querySelector(`.translation-target [data-block-id="${escaped}"]`)
    || translationContent.querySelector(`[data-block-id="${escaped}"]`);
  if (!element) return;
  const container = translationContent.getBoundingClientRect();
  const target = element.getBoundingClientRect();
  translationContent.scrollTo({
    top: translationContent.scrollTop + target.top + target.height / 2 - container.top - container.height / 2,
    behavior
  });
}

function centerPdfBox(record, box, behavior = "smooth") {
  const viewport = record.page.getViewport({ scale: scaleFor(record) });
  const rectangle = viewport.convertToViewportRectangle(box);
  const targetCenter = record.element.offsetTop + (rectangle[1] + rectangle[3]) / 2;
  viewportElement.scrollTo({
    top: Math.max(0, targetCenter - viewportElement.clientHeight / 2),
    left: 0,
    behavior
  });
}

async function focusPdfBlock(block, origin = "translation") {
  const page = Number(block?.physical_page || pageNumber);
  if (!Number.isInteger(page) || page < 1 || page > pageRecords.length) return;
  const record = pageRecords[page - 1];
  if (!Array.isArray(block.bbox)) {
    await addTextLayerLocations(record, [block]).catch(() => {});
  }
  record.selectedBlockId = block.id;
  selectRenderedBlock(block.id);
  updateBlockOverlay(record);
  setCurrentPage(page);
  renderNearPage(page);
  await renderPage(record);
  if (Array.isArray(block.bbox)) {
    centerPdfBox(record, block.bbox);
    const method = block.location_match === "visual-text-fuzzy" ? "图像原文模糊匹配" : "原文匹配";
    showStatusHint(`${blockLabel(block)} · 已通过${method}定位`);
  } else {
    scrollToPage(page, "smooth");
    showStatusHint(`${blockLabel(block)} · 已定位到第 ${page} 页（该块没有可靠坐标）`);
  }
  if (origin === "pdf") centerTranslationBlock(block.id);
}

function appendStructureSection(container, title, content) {
  if (!content) return;
  const section = document.createElement("section");
  section.className = "translation-structure__section";
  const heading = document.createElement("h4");
  heading.textContent = title;
  section.append(heading, content);
  container.appendChild(section);
}

function makeNotes(items) {
  if (!Array.isArray(items) || !items.length) return null;
  const list = document.createElement("ul");
  list.className = "translation-structure__notes";
  for (const item of items) {
    const entry = document.createElement("li");
    entry.textContent = readableMathText(item);
    list.appendChild(entry);
  }
  return list;
}

function makeTableData(value) {
  if (!value?.headers?.length || !value?.rows?.length) return null;
  const container = document.createElement("div");
  container.className = "translation-structure translation-table-data";
  const scroll = document.createElement("div");
  scroll.className = "translation-table-scroll";
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const cell of value.headers) {
    const header = document.createElement("th");
    header.scope = "col";
    header.textContent = readableMathText(cell);
    headRow.appendChild(header);
  }
  head.appendChild(headRow);
  const body = document.createElement("tbody");
  for (const row of value.rows) {
    const tableRow = document.createElement("tr");
    for (const cell of row) {
      const tableCell = document.createElement("td");
      tableCell.textContent = readableMathText(cell);
      tableRow.appendChild(tableCell);
    }
    body.appendChild(tableRow);
  }
  table.append(head, body);
  scroll.appendChild(table);
  container.appendChild(scroll);
  appendStructureSection(container, "表格说明", makeNotes(value.notes));
  return container;
}

function makeFigureData(value) {
  if (!value?.summary) return null;
  const container = document.createElement("div");
  container.className = "translation-structure translation-figure-data";
  const summary = document.createElement("p");
  summary.textContent = readableMathText(value.summary);
  appendStructureSection(container, "整图说明", summary);
  if (value.flow_steps?.length) {
    const flow = document.createElement("ol");
    flow.className = "translation-figure-flow";
    for (const step of value.flow_steps) {
      const entry = document.createElement("li");
      entry.textContent = readableMathText(step);
      flow.appendChild(entry);
    }
    appendStructureSection(container, "流程", flow);
  }
  if (value.labels?.length) {
    const labels = document.createElement("dl");
    labels.className = "translation-figure-labels";
    for (const label of value.labels) {
      const original = document.createElement("dt");
      original.textContent = readableMathText(label.original);
      const translated = document.createElement("dd");
      translated.textContent = readableMathText(label.translation);
      labels.append(original, translated);
    }
    appendStructureSection(container, "图中标签", labels);
  }
  appendStructureSection(container, "核对提示", makeNotes(value.notes));
  return container;
}

function makeTranslationBlock(block, source) {
  const article = document.createElement("article");
  article.className = "translation-block";
  article.dataset.blockId = block.id || "page";
  article.tabIndex = 0;
  article.setAttribute("role", "button");
  article.title = `${blockLabel(block)} · ${block.id || "page"} · ${blockConfidenceLabel(block.confidence)}`;
  const label = document.createElement("span");
  label.className = "translation-block__label";
  const natural = document.createElement("span");
  natural.className = "translation-block__natural";
  natural.textContent = blockLabel(block);
  const technical = document.createElement("span");
  technical.className = "translation-block__technical";
  technical.textContent = block.id || "page";
  const confidence = document.createElement("span");
  confidence.className = `translation-block__confidence is-${block.confidence || "medium"}`;
  confidence.textContent = `译文：${blockConfidenceLabel(block.confidence)}`;
  const location = document.createElement("span");
  location.className = `translation-block__location is-${block.location_match === "visual-text-fuzzy" ? "fuzzy" : (Array.isArray(block.bbox) ? "exact" : "page")}`;
  location.textContent = locationLabel(block);
  label.append(natural, technical, confidence, location);
  const text = document.createElement("div");
  text.textContent = readableMathText(
    source ? (block.original_text || "（该块没有可用原文文本层）") : (block.translation || "")
  );
  article.append(label, text);
  const structure = !source && block.table_data
    ? makeTableData(block.table_data)
    : (!source && block.figure_data ? makeFigureData(block.figure_data) : null);
  if (structure) article.appendChild(structure);
  article.addEventListener("click", () => focusPdfBlock(block, "translation"));
  article.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      focusPdfBlock(block, "translation");
    }
  });
  return article;
}

function translationApi(path, options = {}) {
  return fetch(path, {
    cache: "no-store",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(readerToken ? { "X-Reader-Token": readerToken } : {}),
      ...(options.headers || {})
    }
  }).then(async response => {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
    return data;
  });
}

function retryableTranslationError(error) {
  return /524|连接失败|连接中断|超时|closed connection/i.test(error?.message || "");
}

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function translatePageWithOneRetry(requestedPage, force) {
  const options = {
    method: "POST",
    body: JSON.stringify({ source_id: sourceId, page: requestedPage, force, bulk: true })
  };
  try {
    return await translationApi("/api/translation/page", options);
  } catch (error) {
    if (!retryableTranslationError(error) || fullTranslationStopRequested) throw error;
    updateFullTranslationProgress(
      fullTranslationStatusState?.completed || 0,
      fullTranslationStatusState?.total || pdfDocument.numPages,
      requestedPage,
      fullTranslationStatusState?.failures || 0,
      `第 ${requestedPage} 页遇到临时连接问题，正在重试一次`
    );
    await delay(1200);
    return translationApi("/api/translation/page", options);
  }
}

function applyTranslationWidth(width) {
  const bounds = document.querySelector("#workspace").getBoundingClientRect();
  // Keep both reading surfaces usable inside a narrow evidence panel. This
  // also corrects older saved widths that could collapse the translation pane.
  const minimumPdfWidth = Math.min(300, bounds.width * 0.42);
  const minimumTranslationWidth = Math.min(300, bounds.width * 0.38);
  const clamped = Math.max(
    minimumTranslationWidth,
    Math.min(bounds.width - minimumPdfWidth, width)
  );
  translationPanel.style.setProperty("--translation-panel-width", `${Math.round(clamped)}px`);
}

function setTranslationPanel(open) {
  const changed = translationPanelOpen !== open;
  const targetPage = pageNumber;
  translationPanelOpen = open;
  translationPanel.hidden = !open;
  translationResizer.hidden = !open;
  if (open) {
    const saved = Number(localStorage.getItem(translationWidthKey));
    if (Number.isFinite(saved) && saved > 0) applyTranslationWidth(saved);
  }
  pageDetectionSuspended = true;
  pageDetectionGeneration += 1;
  if (scrollFrame) cancelAnimationFrame(scrollFrame);
  scrollFrame = null;
  requestAnimationFrame(() => {
    updatePageLayouts();
    renderNearPage(targetPage);
    if (changed) scrollToPage(targetPage);
    else suspendPageDetectionUntilSettled();
  });
}

function renderTranslation(value, sourceText = "", { preserveScroll = false } = {}) {
  const previousScrollTop = preserveScroll ? translationContent.scrollTop : 0;
  translationTitle.textContent = `PDF 第 ${pageNumber} 页 · 中文译文`;
  translationContent.innerHTML = "";
  translationContent.scrollTop = previousScrollTop;
  const currentRecord = pageRecords[pageNumber - 1];
  if (!value) {
    setRecordBlocks(currentRecord, []);
    translationState.textContent = "尚未翻译";
    translationContent.innerHTML = '<div class="translation-empty">该页尚未翻译。原始 PDF 保持在左侧，点击“翻译当前页”开始。</div>';
    return;
  }
  translationState.textContent = value.visual_input
    ? "已缓存 · 已结合页面图像校正 · 点击块可回查 PDF"
    : "已缓存 · 点击块可回查 PDF";
  const columns = document.createElement("div");
  columns.className = "translation-columns";
  columns.classList.toggle("show-source", showSourceToggle.checked);
  const source = document.createElement("div");
  source.className = "translation-source";
  const sourceBlocks = Array.isArray(value.blocks) && value.blocks.length
    ? value.blocks
    : [{ id: "page", original_text: value.source_text || sourceText || "（没有可用原文文本层）", confidence: "medium" }];
  const targetBlocks = Array.isArray(value.blocks) && value.blocks.length
    ? value.blocks
    : [{ id: "page", translation: value.translation, confidence: "medium" }];
  setRecordBlocks(currentRecord, sourceBlocks);
  addTextLayerLocations(currentRecord, sourceBlocks).catch(() => {});
  for (const block of sourceBlocks) {
    source.appendChild(makeTranslationBlock(block, true));
  }
  const target = document.createElement("div");
  target.className = "translation-target";
  for (const block of targetBlocks) {
    target.appendChild(makeTranslationBlock(block, false));
  }
  columns.append(source, target);
  translationContent.appendChild(columns);
  selectRenderedBlock(currentRecord?.selectedBlockId);
  if (value.warnings?.length) {
    const warning = document.createElement("div");
    warning.className = "translation-warning";
    warning.textContent = `核对提示：${value.warnings.join("；")}`;
    translationContent.appendChild(warning);
  }
  if (preserveScroll) translationContent.scrollTop = previousScrollTop;
}

async function loadTranslationState({ preserveScroll = false } = {}) {
  if (!sourceId || !pdfDocument || !readerToken) return;
  const requestId = ++translationRequestId;
  translationTitle.textContent = `PDF 第 ${pageNumber} 页 · 中文译文`;
  translationState.textContent = "正在检查本地缓存…";
  try {
    const state = await translationApi(
      `/api/translation/page?source_id=${encodeURIComponent(sourceId)}&page=${pageNumber}`
    );
    if (requestId !== translationRequestId) return;
    if (state.translation) {
      setTranslationPanel(true);
      renderTranslation(state.translation, state.source_text, { preserveScroll });
    } else if (translationPanelOpen) {
      renderTranslation(null, state.source_text, { preserveScroll });
    }
  } catch (error) {
    if (requestId !== translationRequestId) return;
    translationState.textContent = "缓存读取失败";
    if (translationPanelOpen) {
      translationContent.innerHTML = `<div class="translation-error"></div>`;
      translationContent.firstElementChild.textContent = error.message;
    }
  }
}

async function translateCurrentPage(force) {
  if (translationBusy || !sourceId || !readerToken) return;
  const requestedPage = pageNumber;
  translationBusy = true;
  setTranslationPanel(true);
  translatePageButton.disabled = true;
  translateAllButton.disabled = true;
  retranslatePageButton.disabled = true;
  translatePageButton.textContent = "正在翻译…";
  translationTitle.textContent = `PDF 第 ${requestedPage} 页 · 中文译文`;
  translationState.textContent = "Codex 正在结合页面文本与图像翻译…";
  translationContent.innerHTML = '<div class="translation-loading">翻译当前物理页。完成后会自动保存到本机缓存。</div>';
  try {
    const result = await translationApi("/api/translation/page", {
      method: "POST",
      body: JSON.stringify({ source_id: sourceId, page: requestedPage, force })
    });
    if (requestedPage === pageNumber) renderTranslation(result);
  } catch (error) {
    if (requestedPage === pageNumber) {
      translationState.textContent = "翻译失败，可重试";
      translationContent.innerHTML = '<div class="translation-error"></div>';
      translationContent.firstElementChild.textContent = error.message;
    }
  } finally {
    translationBusy = false;
    translatePageButton.disabled = false;
    translateAllButton.disabled = false;
    retranslatePageButton.disabled = false;
    translatePageButton.textContent = "翻译当前页";
  }
}

function formatElapsed(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function renderFullTranslationStatus() {
  if (!fullTranslationStatusState) return;
  const { completed, total, current, currentPages, concurrency, failures, currentStartedAt, lastError, status } = fullTranslationStatusState;
  const elapsed = currentStartedAt ? formatElapsed(Date.now() - currentStartedAt) : "00:00";
  fullTranslationStatus.hidden = false;
  fullTranslationMeter.max = Math.max(1, total);
  fullTranslationMeter.value = Math.min(total, completed);
  fullTranslationElapsed.textContent = elapsed;
  if (status === "stopping") {
    fullTranslationStatusTitle.textContent = "将在当前页完成后停止";
    fullTranslationDetail.textContent = `正在处理 PDF 第 ${current || "-"} 页 · 已缓存 ${completed}/${total}`;
  } else if (fullTranslationRunning) {
    fullTranslationStatusTitle.textContent = status === "queued"
      ? `正在启动 ${concurrency} 路全文翻译`
      : (fullTranslationStopRequested
      ? "将在进行中的页面完成后停止"
      : "后台全文翻译进行中");
    fullTranslationDetail.textContent = current
      ? `${currentPages.length}/${concurrency} 路正在处理 PDF 第 ${current} 页 · 已缓存 ${completed}/${total}${failures ? ` · ${failures} 页失败` : ""}`
      : `正在分配首批页面 · 已确认缓存 ${completed}/${total}`;
  } else if (status === "stopped") {
    fullTranslationStatusTitle.textContent = "全文翻译已停止";
    fullTranslationDetail.textContent = `已缓存 ${completed}/${total} 页；再次点击“翻译全文”将继续补齐。`;
  } else if (status === "interrupted") {
    fullTranslationStatusTitle.textContent = "上次全文翻译已中断";
    fullTranslationDetail.textContent = `已缓存 ${completed}/${total} 页；点击“继续全文”补齐剩余页面。`;
  } else if (status === "idle") {
    fullTranslationStatusTitle.textContent = completed ? "全文翻译尚未完成" : "尚未开始全文翻译";
    fullTranslationDetail.textContent = `本地已缓存 ${completed}/${total} 页。`;
  } else if (failures || status === "failed" || status === "partial") {
    fullTranslationStatusTitle.textContent = "全文翻译暂未全部完成";
    fullTranslationDetail.textContent = `已缓存 ${completed}/${total} 页 · ${failures} 页失败${lastError ? ` · ${lastError}` : ""}`;
  } else {
    fullTranslationStatusTitle.textContent = "全文翻译完成";
    fullTranslationDetail.textContent = `全部 ${total} 页均已保存在本地缓存。`;
  }
}

function applyFullTranslationJob(state) {
  const status = state.status || "idle";
  fullTranslationRunning = ["queued", "running", "stopping"].includes(status);
  fullTranslationStopRequested = status === "stopping";
  fullTranslationStatusState = {
    status,
    completed: Number(state.completed) || 0,
    total: Number(state.total) || pdfDocument?.numPages || 0,
    current: Array.isArray(state.current_pages) && state.current_pages.length
      ? state.current_pages.join(", ")
      : (Number(state.current_page) || 0),
    currentPages: Array.isArray(state.current_pages) ? state.current_pages : [],
    concurrency: Number(state.concurrency) || 8,
    failures: Number(state.failures) || 0,
    lastError: state.last_error || "",
    currentStartedAt: state.current_started_at ? Date.parse(state.current_started_at) : null
  };
  fullTranslationProgress.hidden = false;
  if (fullTranslationRunning) {
    fullTranslationProgress.textContent = `${fullTranslationStatusState.currentPages.length || 0}/${fullTranslationStatusState.concurrency} 路 · ${fullTranslationStatusState.completed}/${fullTranslationStatusState.total}${fullTranslationStatusState.current ? ` · 第 ${fullTranslationStatusState.current} 页` : ""}`;
    translateAllButton.textContent = status === "stopping" ? "停止中…" : "停止全文";
    translateAllButton.disabled = status === "stopping";
    translateAllButton.classList.add("is-running");
    translateAllButton.setAttribute("aria-busy", "true");
  } else {
    fullTranslationProgress.textContent = `${status === "completed" ? "已完成" : "已缓存"} ${fullTranslationStatusState.completed}/${fullTranslationStatusState.total}`;
    translateAllButton.textContent = fullTranslationStatusState.completed ? "继续全文" : "翻译全文";
    translateAllButton.disabled = false;
    translateAllButton.classList.remove("is-running");
    translateAllButton.removeAttribute("aria-busy");
  }
  translatePageButton.disabled = fullTranslationRunning;
  retranslatePageButton.disabled = fullTranslationRunning;
  renderFullTranslationStatus();
}

async function refreshFullTranslationJob() {
  if (!sourceId || !readerToken || !pdfDocument) return;
  try {
    const wasRunning = fullTranslationRunning;
    const state = await translationApi(`/api/translation/full?source_id=${encodeURIComponent(sourceId)}`);
    applyFullTranslationJob(state);
    if (wasRunning && !fullTranslationRunning && fullTranslationStatusState?.status === "completed" && translationPanelOpen) {
      loadTranslationState({ preserveScroll: true });
    }
  } catch (_) {
    // Page translation remains usable if a transient status poll fails.
  }
}

function updateFullTranslationProgress(completed, total, current = 0, failures = 0, lastError = "") {
  const previousCurrent = fullTranslationStatusState?.current;
  fullTranslationStatusState = {
    completed,
    total,
    current,
    failures,
    lastError: lastError || fullTranslationStatusState?.lastError || "",
    currentStartedAt: current && current === previousCurrent
      ? fullTranslationStatusState.currentStartedAt
      : (current ? Date.now() : null)
  };
  fullTranslationProgress.hidden = false;
  if (fullTranslationRunning) {
    fullTranslationProgress.textContent = `${completed}/${total}${current ? ` · 第 ${current} 页` : ""}`;
  } else if (failures) {
    fullTranslationProgress.textContent = `${completed}/${total} · ${failures} 页失败`;
  } else if (fullTranslationStopRequested) {
    fullTranslationProgress.textContent = `已停止 · ${completed}/${total}`;
  } else {
    fullTranslationProgress.textContent = `已完成 ${completed}/${total}`;
  }
  renderFullTranslationStatus();
}

async function translateAllPages(force = false) {
  if (fullTranslationRunning) {
    translateAllButton.textContent = "停止中…";
    translateAllButton.disabled = true;
    try {
      applyFullTranslationJob(await translationApi("/api/translation/full/stop", {
        method: "POST",
        body: JSON.stringify({ source_id: sourceId })
      }));
    } catch (error) {
      translateAllButton.disabled = false;
      fullTranslationDetail.textContent = error.message;
    }
    return;
  }
  if (translationBusy || !sourceId || !readerToken || !pdfDocument) return;
  setTranslationPanel(true);
  translateAllButton.disabled = true;
  translateAllButton.textContent = "正在启动…";
  try {
    applyFullTranslationJob(await translationApi("/api/translation/full/start", {
      method: "POST",
      body: JSON.stringify({ source_id: sourceId, page: pageNumber, force })
    }));
    setTimeout(refreshFullTranslationJob, 150);
    setTimeout(refreshFullTranslationJob, 600);
  } catch (error) {
    translateAllButton.disabled = false;
    translateAllButton.textContent = "翻译全文";
    fullTranslationStatus.hidden = false;
    fullTranslationStatusTitle.textContent = "全文翻译启动失败";
    fullTranslationDetail.textContent = error.message;
  }
}

function beginTranslationResize(event) {
  event.preventDefault();
  translationResizer.setPointerCapture(event.pointerId);
  const workspace = document.querySelector("#workspace");
  document.body.classList.add("translation-resizing");
  function move(moveEvent) {
    const bounds = workspace.getBoundingClientRect();
    applyTranslationWidth(bounds.right - moveEvent.clientX);
  }
  function finish(upEvent) {
    if (translationResizer.hasPointerCapture(upEvent.pointerId)) {
      translationResizer.releasePointerCapture(upEvent.pointerId);
    }
    document.body.classList.remove("translation-resizing");
    const width = Math.round(translationPanel.getBoundingClientRect().width);
    localStorage.setItem(translationWidthKey, String(width));
    translationResizer.removeEventListener("pointermove", move);
    translationResizer.removeEventListener("pointerup", finish);
    translationResizer.removeEventListener("pointercancel", finish);
    updatePageLayouts();
    renderNearPage(pageNumber);
  }
  translationResizer.addEventListener("pointermove", move);
  translationResizer.addEventListener("pointerup", finish);
  translationResizer.addEventListener("pointercancel", finish);
}

function resetTranslationWidth() {
  localStorage.removeItem(translationWidthKey);
  translationPanel.style.removeProperty("--translation-panel-width");
  updatePageLayouts();
  renderNearPage(pageNumber);
}

function scaleFor(record) {
  if (scaleMode === "manual") return manualScale;
  const availableWidth = Math.max(200, viewportElement.clientWidth - 32);
  return availableWidth / record.baseViewport.width;
}

function updateUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("page", String(pageNumber));
  history.replaceState(null, "", url);
}

function updateControls() {
  pageInput.value = String(pageNumber);
  previousButton.disabled = pageNumber <= 1;
  nextButton.disabled = !pdfDocument || pageNumber >= pdfDocument.numPages;
  if (fileUrl) openOriginal.href = `${fileUrl.href}#page=${pageNumber}`;
  const record = pageRecords[pageNumber - 1];
  if (record) zoomLabel.textContent = `${Math.round(scaleFor(record) * 100)}%`;
}

function setCurrentPage(value, notify = true) {
  if (!pdfDocument) return;
  const nextPage = Math.min(pdfDocument.numPages, Math.max(1, Number(value)));
  if (!Number.isFinite(nextPage)) return;
  const changed = nextPage !== pageNumber;
  pageNumber = nextPage;
  updateControls();
  updateUrl();
  if (changed) pruneDistantPages();
  if (changed) loadTranslationState();
  if (notify) {
    window.parent.postMessage(
      { type: "research-reader-pdf-page", page: pageNumber },
      window.location.origin
    );
  }
}

function clearPage(record) {
  record.generation += 1;
  if (record.renderTask) record.renderTask.cancel();
  record.renderTask = null;
  record.renderedScale = null;
  record.canvas.classList.remove("is-rendered");
  record.canvas.width = 1;
  record.canvas.height = 1;
  record.blockOverlay?.replaceChildren();
}

function pruneDistantPages() {
  for (const record of pageRecords) {
    if (!record.nearViewport && Math.abs(record.number - pageNumber) > 4 && record.renderedScale) {
      clearPage(record);
    }
  }
}

async function renderPageOnce(record) {
  const cssScale = scaleFor(record);
  if (record.renderedScale && Math.abs(record.renderedScale - cssScale) < 0.005) return;

  if (record.renderTask) {
    record.renderTask.cancel();
    try {
      await record.renderTask.promise;
    } catch (error) {
      if (error?.name !== "RenderingCancelledException") throw error;
    }
  }

  const generation = ++record.generation;
  const outputScale = Math.min(window.devicePixelRatio || 1, 2);
  const displayViewport = record.page.getViewport({ scale: cssScale });
  const renderViewport = record.page.getViewport({ scale: cssScale * outputScale });
  const nextCanvas = document.createElement("canvas");
  nextCanvas.setAttribute("aria-label", `PDF 第 ${record.number} 页内容`);
  const context = nextCanvas.getContext("2d", { alpha: false });

  nextCanvas.width = Math.floor(renderViewport.width);
  nextCanvas.height = Math.floor(renderViewport.height);
  nextCanvas.style.width = `${Math.floor(displayViewport.width)}px`;
  nextCanvas.style.height = `${Math.floor(displayViewport.height)}px`;
  record.renderTask = record.page.render({ canvasContext: context, viewport: renderViewport });
  try {
    await record.renderTask.promise;
    if (record.generation !== generation) return;
    record.renderTask = null;
    if (Math.abs(scaleFor(record) - cssScale) >= 0.005) {
      record.renderRequested = true;
      return;
    }
    nextCanvas.classList.add("is-rendered");
    record.element.replaceChildren(nextCanvas, record.blockOverlay);
    record.canvas = nextCanvas;
    record.renderedScale = cssScale;
    updateBlockOverlay(record);
    locateCitation(record);
    if (record.number === pageNumber) statusElement.hidden = true;
  } catch (error) {
    if (error?.name !== "RenderingCancelledException") showError(`PDF 渲染失败：${error.message}`);
  }
}

function renderPage(record) {
  record.renderRequested = true;
  if (record.renderPromise) return record.renderPromise;
  record.renderPromise = (async () => {
    while (record.renderRequested) {
      record.renderRequested = false;
      await renderPageOnce(record);
    }
  })().finally(() => {
    record.renderPromise = null;
    if (record.renderRequested) renderPage(record);
  });
  return record.renderPromise;
}

function renderNearPage(number) {
  for (let index = Math.max(0, number - 2); index <= Math.min(pageRecords.length - 1, number); index += 1) {
    renderPage(pageRecords[index]);
  }
}

function updatePageLayouts() {
  for (const record of pageRecords) {
    const scale = scaleFor(record);
    const width = Math.floor(record.baseViewport.width * scale);
    const height = Math.floor(record.baseViewport.height * scale);
    record.element.style.width = `${width}px`;
    record.element.style.height = `${height}px`;
    if (record.renderedScale && Math.abs(record.renderedScale - scale) >= 0.005) {
      // Retain and stretch the last complete bitmap until its replacement is
      // ready, avoiding a blank PDF or missing figure during a resize.
      record.renderedScale = null;
      record.canvas.style.width = `${width}px`;
      record.canvas.style.height = `${height}px`;
    }
    updateBlockOverlay(record);
  }
  const current = pageRecords[pageNumber - 1];
  if (current) zoomLabel.textContent = `${Math.round(scaleFor(current) * 100)}%`;
}

function scrollToPage(value, behavior = "auto") {
  const requested = Number.parseInt(value, 10);
  if (!Number.isFinite(requested) || !pdfDocument) return;
  const target = Math.min(pdfDocument.numPages, Math.max(1, requested));
  const record = pageRecords[target - 1];
  if (behavior === "smooth") suspendPageDetectionUntilSettled(500);
  else anchorPageUntilLayoutSettles(target);
  setCurrentPage(target);
  renderNearPage(target);
  viewportElement.scrollTo({ top: Math.max(0, record.element.offsetTop - 16), left: 0, behavior });
}

function anchorPageUntilLayoutSettles(target) {
  const generation = ++pageDetectionGeneration;
  pageDetectionSuspended = true;
  if (scrollFrame) cancelAnimationFrame(scrollFrame);
  scrollFrame = null;
  let previousOffset = -1;
  let stableFrames = 0;
  let remainingFrames = 12;

  const settle = () => {
    if (generation !== pageDetectionGeneration) return;
    const record = pageRecords[target - 1];
    if (!record) {
      pageDetectionSuspended = false;
      return;
    }
    const targetTop = Math.max(0, record.element.offsetTop - 16);
    if (Math.abs(viewportElement.scrollTop - targetTop) > 1) viewportElement.scrollTop = targetTop;
    stableFrames = Math.abs(targetTop - previousOffset) <= 1 ? stableFrames + 1 : 0;
    previousOffset = targetTop;
    remainingFrames -= 1;
    if (stableFrames >= 2 || remainingFrames <= 0) {
      pageDetectionSuspended = false;
      return;
    }
    requestAnimationFrame(settle);
  };
  requestAnimationFrame(settle);
}

function suspendPageDetectionUntilSettled(delay = 0) {
  const generation = ++pageDetectionGeneration;
  pageDetectionSuspended = true;
  if (scrollFrame) cancelAnimationFrame(scrollFrame);
  scrollFrame = null;
  const release = () => {
    requestAnimationFrame(() => {
      if (generation === pageDetectionGeneration) pageDetectionSuspended = false;
    });
  };
  if (delay) setTimeout(release, delay);
  else requestAnimationFrame(release);
}

function detectCurrentPage() {
  scrollFrame = null;
  if (!pageRecords.length) return;
  const viewportTop = viewportElement.scrollTop;
  const viewportBottom = viewportTop + viewportElement.clientHeight;
  let detected = pageNumber;
  let largestVisibleArea = -1;
  for (const record of pageRecords) {
    const pageTop = record.element.offsetTop;
    if (pageTop >= viewportBottom) break;
    const pageBottom = pageTop + record.element.offsetHeight;
    const visibleArea = Math.max(0, Math.min(pageBottom, viewportBottom) - Math.max(pageTop, viewportTop));
    if (visibleArea > largestVisibleArea) {
      largestVisibleArea = visibleArea;
      detected = record.number;
    }
  }
  setCurrentPage(detected);
}

function scheduleCurrentPageDetection() {
  if (pageDetectionSuspended) return;
  if (!scrollFrame) scrollFrame = requestAnimationFrame(detectCurrentPage);
}

function zoom(factor) {
  const current = pageRecords[pageNumber - 1];
  if (!current) return;
  scaleMode = "manual";
  manualScale = Math.min(4, Math.max(0.35, scaleFor(current) * factor));
  updatePageLayouts();
  scrollToPage(pageNumber);
}

async function buildPageFlow() {
  const fragment = document.createDocumentFragment();
  for (let number = 1; number <= pdfDocument.numPages; number += 1) {
    const page = await pdfDocument.getPage(number);
    const element = document.createElement("section");
    const canvas = document.createElement("canvas");
    const blockOverlay = document.createElement("div");
    element.className = "pdf-page";
    element.dataset.page = String(number);
    element.setAttribute("aria-label", `PDF 第 ${number} 页`);
    canvas.setAttribute("aria-label", `PDF 第 ${number} 页内容`);
    blockOverlay.className = "pdf-block-overlay";
    element.append(canvas, blockOverlay);
    fragment.appendChild(element);
    pageRecords.push({
      number,
      page,
      element,
      canvas,
      blockOverlay,
      translationBlocks: [],
      selectedBlockId: null,
      citationBox: null,
      baseViewport: page.getViewport({ scale: 1 }),
      renderedScale: null,
      renderTask: null,
      renderPromise: null,
      renderRequested: false,
      generation: 0,
      nearViewport: false
    });
  }
  pagesElement.appendChild(fragment);
  updatePageLayouts();

  pageObserver = new IntersectionObserver(
    entries => {
      for (const entry of entries) {
        const record = pageRecords[Number(entry.target.dataset.page) - 1];
        record.nearViewport = entry.isIntersecting;
        if (entry.isIntersecting) renderPage(record);
      }
      pruneDistantPages();
    },
    { root: viewportElement, rootMargin: "140% 0px", threshold: 0 }
  );
  for (const record of pageRecords) pageObserver.observe(record.element);
}

previousButton.addEventListener("click", () => scrollToPage(pageNumber - 1, "smooth"));
nextButton.addEventListener("click", () => scrollToPage(pageNumber + 1, "smooth"));
pageInput.addEventListener("change", () => scrollToPage(pageInput.value));
pageInput.addEventListener("keydown", event => {
  if (event.key === "Enter") scrollToPage(pageInput.value);
});
document.querySelector("#zoom-out").addEventListener("click", () => zoom(0.85));
document.querySelector("#zoom-in").addEventListener("click", () => zoom(1.18));
document.querySelector("#fit-width").addEventListener("click", () => {
  scaleMode = "fit";
  updatePageLayouts();
  scrollToPage(pageNumber);
});
translatePageButton.addEventListener("click", () => translateCurrentPage(false));
translateAllButton.addEventListener("click", () => translateAllPages(false));
retranslatePageButton.addEventListener("click", () => translateCurrentPage(true));
closeTranslationButton.addEventListener("click", () => setTranslationPanel(false));
showSourceToggle.addEventListener("change", () => {
  localStorage.setItem(translationSourceKey, String(showSourceToggle.checked));
  translationContent.querySelector(".translation-columns")?.classList.toggle("show-source", showSourceToggle.checked);
});
translationResizer.addEventListener("pointerdown", beginTranslationResize);
translationResizer.addEventListener("dblclick", resetTranslationWidth);
viewportElement.addEventListener("scroll", scheduleCurrentPageDetection, { passive: true });
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (translationPanelOpen) {
      const saved = Number(localStorage.getItem(translationWidthKey));
      applyTranslationWidth(Number.isFinite(saved) && saved > 0 ? saved : translationPanel.getBoundingClientRect().width);
    }
    if (scaleMode === "fit") {
      updatePageLayouts();
      scrollToPage(pageNumber);
    }
  }, 120);
});

async function start() {
  if (!file) {
    showError("缺少 PDF 文件参数");
    return;
  }
  fileUrl = new URL(file, window.location.href);
  if (fileUrl.origin !== window.location.origin || !fileUrl.pathname.endsWith(".pdf")) {
    showError("只允许加载本站固定的 PDF 文件");
    return;
  }
  if (!/^[A-Za-z0-9._-]{1,128}$/.test(sourceId)) {
    showError("缺少可信 PDF 来源标识");
    translatePageButton.disabled = true;
    translateAllButton.disabled = true;
    return;
  }
  try {
    const bootstrapResponse = await fetch("/api/bootstrap", { cache: "no-store" });
    if (!bootstrapResponse.ok || !bootstrapResponse.headers.get("Content-Type")?.includes("application/json")) {
      throw new Error("translation API unavailable");
    }
    const bootstrap = await bootstrapResponse.json();
    readerToken = bootstrap.token;
  } catch (error) {
    translatePageButton.disabled = true;
    translatePageButton.title = "翻译服务未启动；请使用 ./serve.sh";
    translateAllButton.disabled = true;
    translateAllButton.title = "翻译服务未启动；请使用 ./serve.sh";
  }
  try {
    showSourceToggle.checked = localStorage.getItem(translationSourceKey) === "true";
    pdfDocument = await pdfjsLib.getDocument({ url: fileUrl.href }).promise;
    pageCount.textContent = String(pdfDocument.numPages);
    pageInput.max = String(pdfDocument.numPages);
    pageNumber = Math.min(pdfDocument.numPages, pageNumber);
    const initialPage = pageNumber;
    await buildPageFlow();
    updateControls();
    if (scrollFrame) cancelAnimationFrame(scrollFrame);
    scrollFrame = null;
    scrollToPage(initialPage);
    if (readerToken) {
      await Promise.all([loadTranslationState(), refreshFullTranslationJob()]);
      clearInterval(fullTranslationTimer);
      fullTranslationTimer = setInterval(refreshFullTranslationJob, 2000);
    }
  } catch (error) {
    showError(`PDF 载入失败：${error.message}`);
  }
}

start();
