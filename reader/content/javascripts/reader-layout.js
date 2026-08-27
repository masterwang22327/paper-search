(function () {
  "use strict";

  const storageKey = "research-reader-navigation-collapsed";
  let toggle;
  let sectionTools;
  let scrollHandler;
  let clickHandler;
  let readingMemo;
  let readingProgressGeneration = 0;
  let readingProgressToken = "";
  let readingProgressDocument;
  let readingProgressArticle;
  let readingProgressHeadings = [];
  let readingProgressState;
  let readingProgressAbort;
  let readingProgressSaveTimer;
  let readingProgressSaveChain = Promise.resolve();
  let readingProgressLastSignature = "";
  let readingProgressPendingPosition;
  let readingProgressScrollHandler;
  let readingProgressVisibilityHandler;
  let readingProgressPagehideHandler;
  let readingProgressSuppress = false;
  let readingProgressVisualPosition;
  let readingMemoExpanded = false;

  function apply(collapsed) {
    document.body.classList.toggle("reader-nav-collapsed", collapsed);
    if (!toggle) return;
    toggle.textContent = collapsed ? "›" : "‹";
    toggle.title = collapsed ? "展开左侧项目栏" : "收起左侧项目栏";
    toggle.setAttribute("aria-label", toggle.title);
    toggle.setAttribute("aria-expanded", String(!collapsed));
  }

  function clamp(value, minimum = 0, maximum = 1) {
    return Math.max(minimum, Math.min(maximum, Number(value) || 0));
  }

  function readingPositionRank(position) {
    if (!position) return null;
    const section = position.section_index == null || position.section_index === ""
      ? -1
      : Number(position.section_index);
    return [
      clamp(position.scroll_ratio),
      Number.isFinite(section) ? section : -1,
      clamp(position.offset_ratio)
    ];
  }

  function isReadingPositionAhead(candidate, baseline) {
    const candidateRank = readingPositionRank(candidate);
    if (!candidateRank) return false;
    const baselineRank = readingPositionRank(baseline);
    if (!baselineRank) return true;
    for (let index = 0; index < candidateRank.length; index += 1) {
      if (candidateRank[index] > baselineRank[index] + 0.000001) return true;
      if (candidateRank[index] < baselineRank[index] - 0.000001) return false;
    }
    return false;
  }

  function readingApi(path, options = {}, tokenOverride) {
    const token = tokenOverride === undefined ? readingProgressToken : tokenOverride;
    const headers = {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { "X-Reader-Token": token } : {}),
      ...(options.headers || {})
    };
    return fetch(path, {
      cache: "no-store",
      ...options,
      headers
    }).then(async response => {
      let value;
      try {
        value = await response.json();
      } catch (error) {
        throw new Error("阅读记录服务未启动");
      }
      if (!response.ok) throw new Error(value.error || `请求失败：${response.status}`);
      return value;
    });
  }

  function formatReadingTime(value) {
    const timestamp = Date.parse(String(value || ""));
    if (!Number.isFinite(timestamp)) return "时间未知";
    const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    if (seconds < 60) return "刚刚";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
    if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)} 天前`;
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).format(new Date(timestamp));
  }

  function readingPositionLabel(position) {
    if (!position) return "尚未记录";
    const heading = String(position.heading_title || "正文").replace(/\s*\u00b6\s*$/, "").trim() || "正文";
    const percentage = Math.round(clamp(position.scroll_ratio) * 100);
    return `${heading} · ${percentage}%`;
  }

  function readingHistoryLabel(position) {
    const percentage = position ? Math.round(clamp(position.scroll_ratio) * 100) : 0;
    return `历史完整度：${percentage}%`;
  }

  function updateReadingMemoLauncherLabel() {
    const launcher = readingMemo?.querySelector("[data-reading-action='toggle']");
    if (!launcher) return;
    const percentage = readingProgressVisualPosition
      ? Math.round(clamp(readingProgressVisualPosition.scroll_ratio) * 100)
      : 0;
    const progress = readingProgressVisualPosition ? `（最远 ${percentage}%）` : "";
    const action = readingMemoExpanded ? "收起" : "打开";
    launcher.title = `${action}阅读便签${progress}`;
    launcher.setAttribute("aria-label", `${action}阅读便签${progress}`);
  }

  function updateReadingMemoProgress(position) {
    if (position && (!readingProgressVisualPosition
      || isReadingPositionAhead(position, readingProgressVisualPosition))) {
      readingProgressVisualPosition = position;
    }
    const displayPosition = readingProgressVisualPosition;
    const ratio = clamp(displayPosition?.scroll_ratio);
    const ring = readingMemo?.querySelector("[data-reading-role='progress-ring']");
    if (ring) {
      ring.style.strokeDashoffset = String(1 - ratio);
      ring.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
    }
    updateReadingMemoLauncherLabel();
  }

  function setReadingMemoExpanded(expanded, focus = false) {
    if (!readingMemo) return;
    readingMemoExpanded = Boolean(expanded);
    const panel = readingMemo.querySelector("[data-reading-role='panel']");
    const launcher = readingMemo.querySelector("[data-reading-action='toggle']");
    if (panel) panel.hidden = !readingMemoExpanded;
    readingMemo.classList.toggle("is-expanded", readingMemoExpanded);
    launcher?.setAttribute("aria-expanded", String(readingMemoExpanded));
    updateReadingMemoLauncherLabel();
    if (!focus) return;
    const target = readingMemoExpanded
      ? readingMemo.querySelector("[data-reading-action='toggle-close']")
      : launcher;
    target?.focus();
  }

  function placeReadingMemo(memo = readingMemo) {
    if (!memo) return;
    const dock = document.querySelector(".reader-tool-dock");
    (dock || document.body).appendChild(memo);
  }

  function updateReadingMemoCurrent(position = captureReadingPosition()) {
    const current = readingMemo?.querySelector("[data-reading-role='current']");
    if (!current) return;
    current.hidden = !position;
    current.textContent = position ? `当前：${readingPositionLabel(position)}` : "";
  }

  function readingPositionSignature(position) {
    if (!position) return "";
    return JSON.stringify([
      position.block_id || "",
      position.heading_id || "",
      Math.round(clamp(position.offset_ratio) * 1_000_000),
      Math.round(clamp(position.scroll_ratio) * 1_000_000)
    ]);
  }

  function leafReadingBlocks(article) {
    return Array.from(article?.querySelectorAll("[data-reader-block]") || [])
      .filter(block => !block.querySelector("[data-reader-block]"));
  }

  function captureReadingPosition(marker = window.scrollY + Math.max(80, window.innerHeight * 0.35), headingIndex) {
    const article = readingProgressArticle;
    if (!article) return null;
    const blocks = leafReadingBlocks(article);
    let block = blocks[0] || null;
    for (const candidate of blocks) {
      const top = candidate.getBoundingClientRect().top + window.scrollY;
      if (top <= marker) block = candidate;
      else break;
    }
    let activeIndex = Number.isInteger(headingIndex) ? headingIndex : 0;
    if (!Number.isInteger(headingIndex)) {
      readingProgressHeadings.forEach((heading, index) => {
        if (heading.getBoundingClientRect().top + window.scrollY <= marker) activeIndex = index;
      });
    }
    const blockTop = block
      ? block.getBoundingClientRect().top + window.scrollY
      : article.getBoundingClientRect().top + window.scrollY;
    const blockHeight = Math.max(1, block?.getBoundingClientRect().height || 1);
    const maximumScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const markerOffset = Math.max(80, window.innerHeight * 0.35);
    return {
      block_id: block?.dataset.readerBlock || null,
      heading_id: readingProgressHeadings[activeIndex]?.id || null,
      heading_title: readingProgressHeadings[activeIndex]?.textContent.replace(/\s*\u00b6\s*$/, "").trim() || "",
      section_index: readingProgressHeadings.length ? activeIndex : null,
      offset_ratio: clamp((marker - blockTop) / blockHeight),
      scroll_ratio: clamp((marker - markerOffset) / maximumScroll),
      text_hint: block?.textContent.trim().replace(/\s+/g, " ").slice(0, 240) || ""
    };
  }

  function readingPositionForHeading(heading, index, sectionOffset = 0) {
    const article = readingProgressArticle;
    if (!article) return null;
    const articleTop = article.getBoundingClientRect().top + window.scrollY;
    if (!heading) {
      return {
        block_id: null,
        heading_id: null,
        heading_title: "文档开头",
        section_index: null,
        offset_ratio: 0,
        scroll_ratio: 0,
        text_hint: ""
      };
    }
    const start = heading.getBoundingClientRect().top + window.scrollY;
    const nextHeading = readingProgressHeadings[index + 1];
    const end = nextHeading
      ? nextHeading.getBoundingClientRect().top + window.scrollY
      : articleTop + article.scrollHeight;
    const offset = clamp(sectionOffset);
    const position = captureReadingPosition(start + Math.max(1, end - start) * offset, index);
    if (!position) return null;
    position.heading_id = heading.id || null;
    position.heading_title = heading.textContent.replace(/\s*\u00b6\s*$/, "").trim();
    position.section_index = index;
    if (offset === 0) {
      position.block_id = null;
      position.offset_ratio = 0;
      position.text_hint = "";
    }
    return position;
  }

  function renderReadingMemo() {
    if (!readingMemo) return;
    const checkpoint = readingProgressState?.checkpoint;
    const resumePosition = readingProgressState?.resume_position || checkpoint;
    const note = readingProgressState?.note;
    const status = readingMemo.querySelector("[data-reading-role='status']");
    const history = readingMemo.querySelector("[data-reading-role='history']");
    const resumeLocation = readingMemo.querySelector("[data-reading-role='resume-position']");
    const detail = readingMemo.querySelector("[data-reading-role='detail']");
    const resume = readingMemo.querySelector("[data-reading-action='resume']");
    const noteButton = readingMemo.querySelector("[data-reading-action='note']");
    const edit = readingMemo.querySelector("[data-reading-action='edit-note']");
    const remove = readingMemo.querySelector("[data-reading-action='delete-note']");
    const noteText = readingMemo.querySelector("[data-reading-role='note-text']");
    if (checkpoint) {
      const stale = readingProgressState?.stale ? " · 文档已更新" : "";
      status.textContent = `最远读到：${formatReadingTime(checkpoint.updated_at)} · ${readingPositionLabel(checkpoint)}${stale}`;
    } else {
      status.textContent = "尚未记录阅读位置";
    }
    history.textContent = readingHistoryLabel(checkpoint);
    resume.hidden = !resumePosition;
    resumeLocation.hidden = !resumePosition;
    resumeLocation.textContent = resumePosition ? `恢复位置：${readingPositionLabel(resumePosition)}` : "";
    noteButton.textContent = note ? "编辑便签" : "写便签";
    edit.hidden = !note;
    remove.hidden = !note;
    if (note) {
      detail.hidden = false;
      noteText.textContent = note.text;
    } else {
      detail.hidden = true;
      noteText.textContent = "";
    }
    readingMemo.classList.toggle("is-stale", Boolean(readingProgressState?.stale));
    updateReadingMemoProgress(readingProgressState?.checkpoint);
    updateReadingMemoCurrent();
  }

  function toggleReadingEditor(open, value = "") {
    if (!readingMemo) return;
    const editor = readingMemo.querySelector("[data-reading-role='editor']");
    const textarea = readingMemo.querySelector("textarea");
    editor.hidden = !open;
    if (open) {
      textarea.value = value;
      textarea.focus();
    }
  }

  function updateReadingLocatorPreview() {
    const select = readingMemo?.querySelector("[data-reading-role='locator-heading']");
    const preview = readingMemo?.querySelector("[data-reading-role='locator-preview']");
    if (!select || !preview) return;
    const index = Number(select.selectedOptions[0]?.dataset.index);
    const heading = readingProgressHeadings[index];
    const range = readingMemo.querySelector("[data-reading-role='locator-offset']");
    const output = readingMemo.querySelector("[data-reading-role='locator-offset-value']");
    const sectionOffset = index < 0 ? 0 : clamp(Number(range?.value) / 100);
    if (range) range.disabled = index < 0;
    if (output) output.textContent = index < 0 ? "" : `${Math.round(sectionOffset * 100)}%`;
    const position = readingPositionForHeading(heading, index, sectionOffset);
    preview.textContent = position ? `将定位到：${readingPositionLabel(position)}` : "请选择章节";
  }

  function populateReadingLocator() {
    const select = readingMemo?.querySelector("[data-reading-role='locator-heading']");
    if (!select) return;
    select.replaceChildren();
    const documentStart = document.createElement("option");
    documentStart.value = "__document_start__";
    documentStart.dataset.index = "-1";
    documentStart.textContent = "文档开头";
    select.appendChild(documentStart);
    readingProgressHeadings.forEach((heading, index) => {
      const option = document.createElement("option");
      option.value = heading.id || String(index);
      option.dataset.index = String(index);
      option.textContent = `${index + 1}. ${heading.textContent.replace(/\s*\u00b6\s*$/, "").trim()}`;
      select.appendChild(option);
    });
    const resumePosition = readingProgressState?.resume_position || readingProgressState?.checkpoint;
    const selectedIndex = readingProgressHeadings.findIndex(heading =>
      heading.id && heading.id === resumePosition?.heading_id
    );
    if (selectedIndex >= 0) select.value = readingProgressHeadings[selectedIndex].id || String(selectedIndex);
    else if (!resumePosition?.heading_id) select.value = "__document_start__";
    readingMemo.querySelector("[data-reading-role='locator-offset']").value = "0";
    updateReadingLocatorPreview();
  }

  function toggleReadingLocator(open) {
    if (!readingMemo) return;
    const locator = readingMemo.querySelector("[data-reading-role='locator']");
    locator.hidden = !open;
    if (open) {
      populateReadingLocator();
      readingMemo.querySelector("[data-reading-role='locator-heading']")?.focus();
    }
  }

  async function saveReadingLocator() {
    if (!readingMemo || !readingProgressToken || !readingProgressDocument) return;
    const select = readingMemo.querySelector("[data-reading-role='locator-heading']");
    const save = readingMemo.querySelector("[data-reading-action='save-location']");
    const index = Number(select?.selectedOptions[0]?.dataset.index);
    const sectionOffset = clamp(Number(
      readingMemo.querySelector("[data-reading-role='locator-offset']")?.value
    ) / 100);
    const position = readingPositionForHeading(readingProgressHeadings[index], index, sectionOffset);
    if (!position) return;
    save.disabled = true;
    const generation = readingProgressGeneration;
    const token = readingProgressToken;
    const readingDocument = { ...readingProgressDocument };
    try {
      const value = await queueReadingSave(() => readingApi("/api/reading-progress", {
        method: "POST",
        body: JSON.stringify({
          kind: "document",
          action: "set_position",
          document_id: readingDocument.id,
          document_sha256: readingDocument.sha256,
          position
        })
      }, token));
      if (generation !== readingProgressGeneration) return;
      readingProgressState = value;
      readingProgressLastSignature = readingPositionSignature(value?.checkpoint || readingProgressState?.checkpoint);
      toggleReadingLocator(false);
      renderReadingMemo();
      restoreReadingPosition(value?.resume_position || position);
    } catch (error) {
      if (generation === readingProgressGeneration) {
        readingMemo?.querySelector("[data-reading-role='status']")?.replaceChildren(
          window.document.createTextNode(`定位保存失败：${error.message}`)
        );
      }
    } finally {
      save.disabled = false;
    }
  }

  function queueReadingSave(task) {
    readingProgressSaveChain = readingProgressSaveChain
      .catch(() => {})
      .then(task);
    return readingProgressSaveChain;
  }

  function sendReadingCheckpoint(position, keepalive = false) {
    if (!readingProgressToken || !readingProgressDocument || !position) return Promise.resolve();
    if (!isReadingPositionAhead(position, readingProgressState?.checkpoint)) return Promise.resolve();
    const generation = readingProgressGeneration;
    const signature = readingPositionSignature(position);
    const token = readingProgressToken;
    const document = { ...readingProgressDocument };
    if (signature === readingProgressLastSignature) return Promise.resolve();
    return queueReadingSave(async () => {
      try {
        if ((generation !== readingProgressGeneration && !keepalive)
          || !isReadingPositionAhead(position, readingProgressState?.checkpoint)) return;
        const value = await readingApi("/api/reading-progress", {
          method: "POST",
          keepalive,
          body: JSON.stringify({
            kind: "document",
            action: "checkpoint",
            document_id: document.id,
            document_sha256: document.sha256,
            position
          })
        }, token);
        if (generation !== readingProgressGeneration) return;
        readingProgressState = value;
        updateReadingMemoProgress(value?.checkpoint || position);
        readingProgressLastSignature = readingPositionSignature(value?.checkpoint || position);
        renderReadingMemo();
      } catch (error) {
        if (generation === readingProgressGeneration && readingMemo) {
          readingMemo.querySelector("[data-reading-role='status']").textContent = `保存失败：${error.message}`;
        }
      }
    });
  }

  function flushReadingCheckpoint(keepalive = false) {
    if (!readingProgressArticle || readingProgressSuppress) return;
    clearTimeout(readingProgressSaveTimer);
    readingProgressSaveTimer = undefined;
    const position = readingProgressPendingPosition || captureReadingPosition();
    readingProgressPendingPosition = null;
    sendReadingCheckpoint(position, keepalive);
  }

  function scheduleReadingCheckpoint(position = captureReadingPosition()) {
    if (!readingProgressToken || !readingProgressArticle || readingProgressSuppress) return;
    updateReadingMemoCurrent(position);
    const signature = readingPositionSignature(position);
    const baseline = readingProgressPendingPosition || readingProgressState?.checkpoint;
    if (!position || !isReadingPositionAhead(position, baseline) || signature === readingProgressLastSignature) return;
    updateReadingMemoProgress(position);
    readingProgressPendingPosition = position;
    clearTimeout(readingProgressSaveTimer);
    readingProgressSaveTimer = setTimeout(() => flushReadingCheckpoint(false), 900);
  }

  function restoreReadingPosition(checkpoint) {
    if (!checkpoint || !readingProgressArticle) return;
    clearTimeout(readingProgressSaveTimer);
    readingProgressPendingPosition = null;
    readingProgressSuppress = true;
    let block = !readingProgressState?.stale && checkpoint.block_id
      ? readingProgressArticle.querySelector(`[data-reader-block="${CSS.escape(checkpoint.block_id)}"]`)
      : null;
    const heading = checkpoint.heading_id
      ? readingProgressArticle.querySelector(`#${CSS.escape(checkpoint.heading_id)}`)
      : null;
    if (!block && checkpoint.text_hint) {
      const hint = String(checkpoint.text_hint).trim();
      const matches = leafReadingBlocks(readingProgressArticle).filter(candidate =>
        candidate.textContent.includes(hint)
      );
      if (matches.length === 1) block = matches[0];
    }
    let target = null;
    if (block) {
      const top = block.getBoundingClientRect().top + window.scrollY;
      target = top + clamp(checkpoint.offset_ratio) * Math.max(1, block.getBoundingClientRect().height)
        - Math.max(80, window.innerHeight * 0.35);
    } else if (heading) {
      target = heading.getBoundingClientRect().top + window.scrollY - 96;
    } else {
      const maximumScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      target = maximumScroll * clamp(checkpoint.scroll_ratio);
    }
    window.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
    readingProgressLastSignature = readingPositionSignature(checkpoint);
    setTimeout(() => {
      readingProgressSuppress = false;
      renderReadingMemo();
    }, 900);
  }

  async function saveReadingNote() {
    if (!readingMemo || !readingProgressToken || !readingProgressDocument) return;
    const textarea = readingMemo.querySelector("textarea");
    const save = readingMemo.querySelector("[data-reading-action='save-note']");
    const text = textarea.value.trim();
    if (!text) {
      textarea.focus();
      return;
    }
    const position = captureReadingPosition();
    save.disabled = true;
    const generation = readingProgressGeneration;
    const token = readingProgressToken;
    const readingDocument = { ...readingProgressDocument };
    try {
      const value = await queueReadingSave(() => readingApi("/api/reading-progress", {
        method: "POST",
        body: JSON.stringify({
          kind: "document",
          action: "note",
          document_id: readingDocument.id,
          document_sha256: readingDocument.sha256,
          text,
          position
        })
      }, token));
      if (generation !== readingProgressGeneration) return;
      readingProgressState = value;
      toggleReadingEditor(false);
      renderReadingMemo();
    } catch (error) {
      if (generation === readingProgressGeneration) {
        readingMemo?.querySelector("[data-reading-role='status']")?.replaceChildren(
          window.document.createTextNode(`便签保存失败：${error.message}`)
        );
      }
    } finally {
      save.disabled = false;
    }
  }

  async function deleteReadingNote() {
    if (!readingProgressToken || !readingProgressDocument) return;
    const generation = readingProgressGeneration;
    const token = readingProgressToken;
    const readingDocument = { ...readingProgressDocument };
    try {
      const value = await queueReadingSave(() => readingApi("/api/reading-progress", {
        method: "POST",
        body: JSON.stringify({
          kind: "document",
          action: "delete_note",
          document_id: readingDocument.id,
          document_sha256: readingDocument.sha256
        })
      }, token));
      if (generation !== readingProgressGeneration) return;
      readingProgressState = value;
      toggleReadingEditor(false);
      renderReadingMemo();
    } catch (error) {
      if (generation === readingProgressGeneration) {
        readingMemo?.querySelector("[data-reading-role='status']")?.replaceChildren(
          window.document.createTextNode(`便签删除失败：${error.message}`)
        );
      }
    }
  }

  function buildReadingMemo(article) {
    const memo = document.createElement("section");
    memo.className = "reader-reading-memo reader-reading-memo--floating";
    memo.setAttribute("aria-label", "阅读便签");
    memo.innerHTML = [
      '<button class="reader-reading-memo__launcher" type="button"',
      '  data-reading-action="toggle" aria-controls="reader-reading-memo-panel"',
      '  aria-expanded="false" title="打开阅读便签">',
      '  <svg class="reader-reading-memo__ring" viewBox="0 0 48 48" aria-hidden="true" focusable="false">',
      '    <circle class="reader-reading-memo__ring-track" cx="24" cy="24" r="20"></circle>',
      '    <circle class="reader-reading-memo__ring-progress" data-reading-role="progress-ring"',
      '      cx="24" cy="24" r="20" pathLength="1" stroke-dasharray="1"',
      '      stroke-dashoffset="1" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"></circle>',
      '  </svg>',
      '  <span class="reader-reading-memo__mark" aria-hidden="true"></span>',
      '</button>',
      '<div class="reader-reading-memo__panel" data-reading-role="panel" id="reader-reading-memo-panel" hidden>',
      '  <div class="reader-reading-memo__bar">',
      '    <div class="reader-reading-memo__heading">',
      '      <span class="reader-reading-memo__mark" aria-hidden="true"></span>',
      '      <strong>阅读便签</strong>',
      '    </div>',
      '    <button class="reader-reading-memo__close" type="button"',
      '      data-reading-action="toggle-close" title="收起阅读便签" aria-label="收起阅读便签">&#215;</button>',
      '  </div>',
      '  <div class="reader-reading-memo__status" data-reading-role="status" aria-live="polite">正在读取…</div>',
      '  <div class="reader-reading-memo__history" data-reading-role="history">历史完整度：0%</div>',
      '  <div class="reader-reading-memo__body">',
      '    <div class="reader-reading-memo__current" data-reading-role="current" hidden></div>',
      '    <div class="reader-reading-memo__resume" data-reading-role="resume-position" hidden></div>',
      '    <div class="reader-reading-memo__actions">',
      '      <button type="button" data-reading-action="resume" title="跳转到已保存的恢复位置">继续</button>',
      '      <button type="button" data-reading-action="locate" title="人工选择下一次恢复阅读的位置">人工定位</button>',
      '      <button type="button" data-reading-action="note" title="在当前位置写一条便签">写便签</button>',
      '      <button type="button" data-reading-action="edit-note" title="编辑当前便签" hidden>编辑</button>',
      '      <button type="button" data-reading-action="delete-note" title="删除当前便签" hidden>删除</button>',
      '    </div>',
      '    <div class="reader-reading-memo__locator" data-reading-role="locator" hidden>',
      '      <label for="reader-reading-location">恢复章节</label>',
      '      <select id="reader-reading-location" data-reading-role="locator-heading"></select>',
      '      <label for="reader-reading-location-offset">章节内位置 <output data-reading-role="locator-offset-value">0%</output></label>',
      '      <input id="reader-reading-location-offset" data-reading-role="locator-offset" type="range" min="0" max="100" step="5" value="0">',
      '      <div data-reading-role="locator-preview"></div>',
      '      <div class="reader-reading-memo__editor-actions">',
      '        <button type="button" data-reading-action="save-location">保存并跳转</button>',
      '        <button type="button" data-reading-action="cancel-location">取消</button>',
      '      </div>',
      '    </div>',
      '    <div class="reader-reading-memo__detail" data-reading-role="detail" hidden>',
      '      <span class="reader-reading-memo__note-label">便签</span>',
      '      <span data-reading-role="note-text"></span>',
      '    </div>',
      '    <div class="reader-reading-memo__editor" data-reading-role="editor" hidden>',
      '      <textarea maxlength="2000" rows="3" aria-label="便签内容" placeholder="写下这篇文档的便签"></textarea>',
      '      <div class="reader-reading-memo__editor-actions">',
      '        <button type="button" data-reading-action="save-note">保存</button>',
      '        <button type="button" data-reading-action="cancel-note">取消</button>',
      '      </div>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join("");
    readingMemoExpanded = false;
    readingMemo = memo;
    placeReadingMemo(memo);
    memo.querySelector("[data-reading-action='toggle']").addEventListener("click", () => {
      setReadingMemoExpanded(!readingMemoExpanded, true);
    });
    memo.querySelector("[data-reading-action='toggle-close']").addEventListener("click", () => {
      setReadingMemoExpanded(false, true);
    });
    memo.addEventListener("keydown", event => {
      if (event.key === "Escape" && readingMemoExpanded) setReadingMemoExpanded(false, true);
    });
    memo.querySelector("[data-reading-action='resume']").addEventListener("click", () => {
      restoreReadingPosition(readingProgressState?.resume_position || readingProgressState?.checkpoint);
    });
    memo.querySelector("[data-reading-action='locate']").addEventListener("click", () => {
      toggleReadingLocator(true);
    });
    memo.querySelector("[data-reading-action='note']").addEventListener("click", () => {
      toggleReadingEditor(true, readingProgressState?.note?.text || "");
    });
    memo.querySelector("[data-reading-action='edit-note']").addEventListener("click", () => {
      toggleReadingEditor(true, readingProgressState?.note?.text || "");
    });
    memo.querySelector("[data-reading-action='delete-note']").addEventListener("click", deleteReadingNote);
    memo.querySelector("[data-reading-action='save-location']").addEventListener("click", saveReadingLocator);
    memo.querySelector("[data-reading-action='cancel-location']").addEventListener("click", () => toggleReadingLocator(false));
    memo.querySelector("[data-reading-role='locator-heading']").addEventListener("change", updateReadingLocatorPreview);
    memo.querySelector("[data-reading-role='locator-offset']").addEventListener("input", updateReadingLocatorPreview);
    memo.querySelector("[data-reading-action='save-note']").addEventListener("click", saveReadingNote);
    memo.querySelector("[data-reading-action='cancel-note']").addEventListener("click", () => toggleReadingEditor(false));
    memo.querySelector("textarea").addEventListener("keydown", event => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") saveReadingNote();
    });
    return memo;
  }

  function cleanupReadingProgress() {
    if (readingProgressArticle && readingProgressToken && !readingProgressSuppress) flushReadingCheckpoint(true);
    readingProgressGeneration += 1;
    clearTimeout(readingProgressSaveTimer);
    readingProgressSaveTimer = undefined;
    readingProgressAbort?.abort();
    readingProgressAbort = undefined;
    if (readingProgressScrollHandler) window.removeEventListener("scroll", readingProgressScrollHandler);
    if (readingProgressVisibilityHandler) document.removeEventListener("visibilitychange", readingProgressVisibilityHandler);
    if (readingProgressPagehideHandler) window.removeEventListener("pagehide", readingProgressPagehideHandler);
    readingProgressScrollHandler = undefined;
    readingProgressVisibilityHandler = undefined;
    readingProgressPagehideHandler = undefined;
    readingMemo?.remove();
    readingMemo = undefined;
    readingProgressVisualPosition = undefined;
    readingMemoExpanded = false;
    readingProgressToken = "";
    readingProgressDocument = undefined;
    readingProgressArticle = undefined;
    readingProgressHeadings = [];
    readingProgressState = undefined;
    readingProgressLastSignature = "";
    readingProgressPendingPosition = undefined;
    readingProgressSuppress = false;
  }

  async function startReadingProgress(documentMeta, article, headings) {
    const generation = readingProgressGeneration;
    readingProgressDocument = {
      id: documentMeta.dataset.documentId || "",
      sha256: documentMeta.dataset.documentSha256 || ""
    };
    readingProgressArticle = article;
    readingProgressHeadings = headings;
    const controller = new AbortController();
    readingProgressAbort = controller;
    try {
      const bootstrapResponse = await fetch("/api/bootstrap", { cache: "no-store", signal: controller.signal });
      if (!bootstrapResponse.ok) throw new Error("reading service unavailable");
      const bootstrap = await bootstrapResponse.json();
      if (generation !== readingProgressGeneration) return;
      readingProgressToken = bootstrap.token || "";
      const state = await readingApi(
        `/api/reading-progress?document_id=${encodeURIComponent(readingProgressDocument.id)}`,
        { signal: controller.signal }
      );
      if (generation !== readingProgressGeneration) return;
      readingProgressState = state;
      readingProgressVisualPosition = state.checkpoint;
      readingProgressDocument.sha256 = state.document_sha256 || readingProgressDocument.sha256;
      readingProgressLastSignature = readingPositionSignature(state.checkpoint);
      readingMemo = buildReadingMemo(article);
      renderReadingMemo();
      readingProgressScrollHandler = () => {
        const position = captureReadingPosition();
        updateReadingMemoCurrent(position);
        if (!readingProgressSuppress) scheduleReadingCheckpoint(position);
      };
      readingProgressVisibilityHandler = () => {
        if (document.visibilityState === "hidden") flushReadingCheckpoint(true);
      };
      readingProgressPagehideHandler = () => flushReadingCheckpoint(true);
      window.addEventListener("scroll", readingProgressScrollHandler, { passive: true });
      document.addEventListener("visibilitychange", readingProgressVisibilityHandler);
      window.addEventListener("pagehide", readingProgressPagehideHandler);
    } catch (error) {
      if (error.name !== "AbortError") {
        // The static site can be previewed without the stateful Reader server.
        readingProgressToken = "";
      }
    }
  }

  function initialize() {
    cleanupReadingProgress();
    const documentMeta = document.querySelector(".reader-document-meta");
    const documentId = documentMeta?.dataset.documentId || "";
    const researchPage = documentId.startsWith("papers/") || documentId === "report/index.md";
    document.body.classList.toggle("reader-research-page", researchPage);
    const article = document.querySelector(".md-content__inner");
    const headings = Array.from(article?.querySelectorAll("h2[id]") || []);
    if (document.querySelector(".md-sidebar--primary") && !toggle) {
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
    if (toggle) apply(localStorage.getItem(storageKey) === "true");
    buildSectionTools();
    if (researchPage && documentMeta && article) startReadingProgress(documentMeta, article, headings);
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

  window.addEventListener("reader:tool-dock-change", () => placeReadingMemo());
})();
