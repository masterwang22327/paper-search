(function () {
  "use strict";

  const storageKey = "research-reader-navigation-collapsed";
  let toggle;
  let sectionTools;
  let tableResizeObserver;
  let sectionResizeObserver;
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
  let readingNotePosition;
  let readingNoteId;
  let readingNoteSaving = false;
  let readingNotesSignature = "";

  function apply(collapsed) {
    const narrow = window.matchMedia("(max-width: 76.1875em)").matches;
    document.body.classList.toggle("reader-nav-collapsed", !narrow && collapsed);
    if (!toggle) return;
    const expanded = narrow ? Boolean(document.getElementById("__drawer")?.checked) : !collapsed;
    toggle.textContent = narrow ? "☰" : collapsed ? "›" : "‹";
    toggle.title = expanded ? "收起文档导航" : "展开文档导航";
    toggle.setAttribute("aria-label", toggle.title);
    toggle.setAttribute("aria-expanded", String(expanded));
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
    return window.ReaderApi.request(path, {
      cache: "no-store",
      ...options,
      headers
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
    if (readingMemoExpanded) arrangeReadingNotes(true);
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
    const dock = !document.body.classList.contains("reader-focus-mode") && window.innerWidth > 1440
      ? document.querySelector(".reader-tool-dock") : null;
    const parent = dock || document.body;
    if (memo.parentElement !== parent) parent.appendChild(memo);
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

  function renderReadingMemo() {
    if (!readingMemo) return;
    const checkpoint = readingProgressState?.checkpoint;
    const resumePosition = readingProgressState?.resume_position || checkpoint;
    const status = readingMemo.querySelector("[data-reading-role='status']");
    const resumeLocation = readingMemo.querySelector("[data-reading-role='resume-position']");
    const resume = readingMemo.querySelector("[data-reading-action='resume']");
    status.textContent = readingProgressState?.stale
      ? "文档已更新，跳转时会尝试匹配原段落。"
      : resumePosition ? `续读位置已保存 · ${formatReadingTime(resumePosition.updated_at)}` : "浏览时自动保存进度，也可以在这里设置续读点。";
    resume.hidden = !resumePosition;
    resumeLocation.hidden = !resumePosition;
    resumeLocation.textContent = resumePosition ? readingPositionLabel(resumePosition) : "";
    renderReadingNotes();
    readingMemo.classList.toggle("is-stale", Boolean(readingProgressState?.stale));
    updateReadingMemoProgress(readingProgressState?.checkpoint);
    updateReadingMemoCurrent();
  }

  function readingNotes() {
    return readingProgressState?.notes || (readingProgressState?.note
      ? [{ ...readingProgressState.note, id: readingProgressState.note.id || "legacy-note" }] : []);
  }

  function updateReadingNoteControls() {
    const editing = !readingMemo.querySelector("[data-reading-role='editor']").hidden;
    readingMemo.querySelectorAll("[data-reading-action='note'], [data-reading-action='edit-note'], [data-reading-action='delete-note']")
      .forEach(button => { button.disabled = readingNoteSaving || editing; });
    readingMemo.querySelectorAll("[data-reading-action='save-note'], [data-reading-action='cancel-note'], textarea")
      .forEach(control => { control.disabled = readingNoteSaving; });
  }

  function renderReadingNotes() {
    const notes = readingNotes();
    const signature = JSON.stringify(notes);
    if (signature === readingNotesSignature) return;
    readingNotesSignature = signature;
    const list = readingMemo.querySelector("[data-reading-role='notes']");
    list.replaceChildren();
    readingMemo.querySelector("[data-reading-role='notes-title']").textContent = `章节便签 · ${notes.length}`;
    readingMemo.querySelector("[data-reading-role='note-empty']").hidden = notes.length > 0;
    const groups = new Map();
    [...notes].sort((a, b) => (a.position.section_index ?? -1) - (b.position.section_index ?? -1)
      || a.position.scroll_ratio - b.position.scroll_ratio).forEach(note => {
      const key = note.position.heading_id || note.position.heading_title || "正文";
      if (!groups.has(key)) {
        const group = document.createElement("details");
        group.className = "reader-reading-memo__note-group";
        group.dataset.chapter = key;
        const title = document.createElement("summary");
        title.className = "reader-reading-memo__chapter";
        title.textContent = note.position.heading_title || "正文";
        group.appendChild(title);
        groups.set(key, group);
        list.appendChild(group);
      }
      const card = document.createElement("div");
      card.className = "reader-reading-memo__detail";
      card.dataset.noteId = note.id;
      const text = document.createElement("div");
      text.dataset.readingRole = "note-text";
      text.textContent = note.text;
      card.appendChild(text);
      const actions = document.createElement("div");
      actions.className = "reader-reading-memo__actions";
      [["note-location", "回到原文"], ["edit-note", "编辑"], ["delete-note", "删除"]].forEach(([action, label]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.readingAction = action;
        button.textContent = label;
        actions.appendChild(button);
      });
      card.appendChild(actions);
      groups.get(key).appendChild(card);
    });
    arrangeReadingNotes(true);
    updateReadingNoteControls();
  }

  function arrangeReadingNotes(reset = false) {
    const position = captureReadingPosition();
    const key = position?.heading_id || position?.heading_title || "正文";
    const list = readingMemo?.querySelector("[data-reading-role='notes']");
    if (!list) return;
    // Reorder only on opening or saving, never while the user is using a card.
    const groups = [...list.children];
    groups.forEach(group => {
      const current = group.dataset.chapter === key;
      group.classList.toggle("is-current", current);
      if (reset) group.open = current || group.contains(document.activeElement);
      const title = group.querySelector("summary");
      title.setAttribute("aria-label", `${current ? "当前章节，" : ""}${title.textContent}`);
    });
    const current = groups.find(group => group.dataset.chapter === key);
    if (current) list.prepend(current);
  }

  function toggleReadingEditor(open, note = null) {
    if (!readingMemo || readingNoteSaving) return;
    const editor = readingMemo.querySelector("[data-reading-role='editor']");
    const textarea = readingMemo.querySelector("textarea");
    editor.hidden = !open;
    if (open) {
      readingNoteId = note?.id || null;
      readingNotePosition = note?.position || captureReadingPosition();
      readingMemo.querySelector("[data-reading-role='editor-position']").textContent = `关联章节：${readingNotePosition?.heading_title || "正文"}`;
      textarea.value = note?.text || "";
    } else {
      readingNoteId = undefined;
      readingNotePosition = undefined;
    }
    updateReadingNoteControls();
    if (open) textarea.focus();
    else readingMemo.querySelector("[data-reading-action='note']").focus();
  }

  async function saveReadingLocation(position, save) {
    if (!readingMemo || !readingProgressToken || !readingProgressDocument) return;
    if (!position) return;
    clearTimeout(readingProgressSaveTimer);
    readingProgressPendingPosition = null;
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
      renderReadingMemo();
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

  function restoreReadingPosition(checkpoint, stale = readingProgressState?.stale) {
    if (!checkpoint || !readingProgressArticle) return;
    clearTimeout(readingProgressSaveTimer);
    readingProgressPendingPosition = null;
    readingProgressSuppress = true;
    let block = !stale && checkpoint.block_id
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
    if (!readingMemo || !readingProgressToken || !readingProgressDocument || readingNoteSaving) return;
    const textarea = readingMemo.querySelector("textarea");
    const text = textarea.value.trim();
    if (!text) {
      textarea.focus();
      return;
    }
    const position = readingNotePosition || captureReadingPosition();
    const noteId = readingNoteId;
    readingNoteSaving = true;
    updateReadingNoteControls();
    const generation = readingProgressGeneration;
    const token = readingProgressToken;
    const readingDocument = { ...readingProgressDocument };
    try {
      const value = await queueReadingSave(() => readingApi("/api/reading-progress", {
        method: "POST",
        body: JSON.stringify({
          kind: "document",
          action: "note",
          note_id: noteId,
          document_id: readingDocument.id,
          document_sha256: readingDocument.sha256,
          text,
          position
        })
      }, token));
      if (generation !== readingProgressGeneration) return;
      readingProgressState = value;
      readingNoteSaving = false;
      toggleReadingEditor(false);
      renderReadingMemo();
    } catch (error) {
      if (generation === readingProgressGeneration) {
        readingMemo?.querySelector("[data-reading-role='status']")?.replaceChildren(
          window.document.createTextNode(`便签保存失败：${error.message}`)
        );
      }
    } finally {
      if (generation === readingProgressGeneration) {
        readingNoteSaving = false;
        updateReadingNoteControls();
      }
    }
  }

  async function deleteReadingNote(noteId) {
    if (!readingProgressToken || !readingProgressDocument || readingNoteSaving) return;
    readingNoteSaving = true;
    updateReadingNoteControls();
    const generation = readingProgressGeneration;
    const token = readingProgressToken;
    const readingDocument = { ...readingProgressDocument };
    try {
      const value = await queueReadingSave(() => readingApi("/api/reading-progress", {
        method: "POST",
        body: JSON.stringify({
          kind: "document",
          action: "delete_note",
          note_id: noteId,
          document_id: readingDocument.id,
          document_sha256: readingDocument.sha256
        })
      }, token));
      if (generation !== readingProgressGeneration) return;
      readingProgressState = value;
      renderReadingMemo();
    } catch (error) {
      if (generation === readingProgressGeneration) {
        readingMemo?.querySelector("[data-reading-role='status']")?.replaceChildren(
          window.document.createTextNode(`便签删除失败：${error.message}`)
        );
      }
    } finally {
      if (generation === readingProgressGeneration) {
        readingNoteSaving = false;
        updateReadingNoteControls();
        readingMemo.querySelector("[data-reading-action='note']").focus();
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
      '  <div class="reader-reading-memo__body">',
      '    <section class="reader-reading-memo__section">',
      '    <strong class="reader-reading-memo__label">接着读</strong>',
      '    <div class="reader-reading-memo__resume" data-reading-role="resume-position" hidden></div>',
      '    <div class="reader-reading-memo__status" data-reading-role="status" aria-live="polite">正在读取…</div>',
      '    <button class="reader-reading-memo__primary" type="button" data-reading-action="resume">回到续读位置</button>',
      '    <div class="reader-reading-memo__current" data-reading-role="current" hidden></div>',
      '    <button type="button" data-reading-action="save-current" title="将当前阅读位置保存为续读点，保留最远浏览进度">下次从这里读</button>',
      '    </section>',
      '    <section class="reader-reading-memo__section">',
      '    <strong class="reader-reading-memo__label" data-reading-role="notes-title">章节便签</strong>',
      '    <button type="button" data-reading-action="note">＋ 为当前章节添加便签</button>',
      '    <div class="reader-reading-memo__empty" data-reading-role="note-empty">记下疑问或下一步，每条便签都能带你回到原文。</div>',
      '    <div class="reader-reading-memo__editor" data-reading-role="editor" hidden>',
      '      <div class="reader-reading-memo__current" data-reading-role="editor-position"></div>',
      '      <textarea maxlength="2000" rows="3" aria-label="便签内容" placeholder="例如：还没理解这个 baseline 为什么无偏，下次从这里推一遍。"></textarea>',
      '      <div class="reader-reading-memo__editor-actions">',
      '        <button type="button" data-reading-action="save-note">保存便签</button>',
      '        <button type="button" data-reading-action="cancel-note">取消</button>',
      '      </div>',
      '    </div>',
      '    <div class="reader-reading-memo__notes" data-reading-role="notes"></div>',
      '    </section>',
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
      setReadingMemoExpanded(false);
    });
    memo.querySelector("[data-reading-action='save-current']").addEventListener("click", event => {
      saveReadingLocation(captureReadingPosition(), event.currentTarget);
    });
    memo.querySelector("[data-reading-action='note']").addEventListener("click", () => toggleReadingEditor(true));
    memo.querySelector("[data-reading-role='notes']").addEventListener("click", event => {
      const button = event.target.closest("button[data-reading-action]");
      const card = button?.closest("[data-note-id]");
      const note = readingNotes().find(item => item.id === card?.dataset.noteId);
      if (!note) return;
      if (button.dataset.readingAction === "note-location") {
        const stale = note.document_sha256 ? note.document_sha256 !== readingProgressDocument.sha256 : readingProgressState?.stale;
        restoreReadingPosition(note.position, stale);
        setReadingMemoExpanded(false);
      } else if (button.dataset.readingAction === "edit-note") {
        toggleReadingEditor(true, note);
      } else if (button.dataset.readingAction === "delete-note") {
        deleteReadingNote(note.id);
      }
    });
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
    readingNotePosition = undefined;
    readingNoteId = undefined;
    readingNoteSaving = false;
    readingNotesSignature = "";
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
      const bootstrap = await readingApi("/api/bootstrap", { signal: controller.signal });
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

  function simplifySidebar() {
    const sidebar = document.querySelector(".md-sidebar--primary");
    if (!sidebar) return;
    const titles = {
      "deepseek-v2-v3-r1-lineage": "DeepSeek 系列演进",
      "llama1-llama2-llama31-lineage": "LLaMA 系列演进",
      "qwen2-qwen25-qwen3-lineage": "Qwen 系列演进"
    };
    sidebar.querySelectorAll("a.md-nav__link").forEach(link => {
      const url = new URL(link.href);
      if (url.hash || !url.pathname.includes("/papers/")) return;
      const label = link.querySelector(".md-ellipsis");
      if (!label) return;
      const full = link.title || label.textContent.trim();
      const slug = url.pathname.split("/").filter(Boolean).pop();
      const prefix = full.match(/^\d+\s*·\s*/)?.[0] || "";
      const short = titles[slug] ? prefix + titles[slug] : full.split(/[：:]/)[0];
      link.title = full;
      link.setAttribute("aria-label", full);
      label.textContent = short;
      link.classList.add("reader-nav-paper");
    });
    sidebar.querySelectorAll(".md-nav__item--nested").forEach(item => {
      const label = item.querySelector(":scope > label");
      if (!/^阶段\s*\d+/.test(label?.textContent.trim() || "")) return;
      const input = item.querySelector(":scope > input");
      if (input) input.checked = item.classList.contains("md-nav__item--active");
    });
  }

  function simplifyHeaderTitle(documentId) {
    const topic = document.querySelector('[data-md-component="header-topic"] .md-ellipsis');
    if (!topic || !documentId.startsWith("papers/")) return;
    const slug = documentId.split("/").pop().replace(/\.md$/, "");
    const titles = {
      "deepseek-v2-v3-r1-lineage": "66 · DeepSeek 系列演进",
      "llama1-llama2-llama31-lineage": "64 · LLaMA 系列演进",
      "qwen2-qwen25-qwen3-lineage": "65 · Qwen 系列演进"
    };
    const full = topic.title || topic.textContent.trim();
    topic.title = full;
    topic.textContent = titles[slug] || full.split(/[：:]/)[0];
  }

  function prepareReadingTables(article) {
    tableResizeObserver?.disconnect();
    if (!article) return;
    tableResizeObserver = new ResizeObserver(entries => {
      entries.forEach(({ target }) => {
        const overflowing = target.scrollWidth > target.clientWidth + 2;
        const hint = target.nextElementSibling;
        if (hint?.matches(".reader-table-hint, .reader-math-hint")) hint.hidden = !overflowing;
        target.tabIndex = overflowing ? 0 : -1;
      });
    });
    article.querySelectorAll("table").forEach(table => {
      if (!table.querySelector("[data-reader-block]")) return;
      const wrapper = table.closest(".md-typeset__scrollwrap");
      if (!wrapper) return;
      wrapper.classList.add("reader-table-scroll");
      wrapper.classList.toggle("reader-table-compact", table.rows[0]?.cells.length <= 3);
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("aria-label", "正文表格，可横向滚动查看");
      let hint = wrapper.nextElementSibling;
      if (!hint?.classList.contains("reader-table-hint")) {
        hint = document.createElement("div");
        hint.className = "reader-table-hint";
        hint.textContent = "左右滑动查看完整表格 ↔";
        hint.hidden = true;
        wrapper.after(hint);
      }
      tableResizeObserver.observe(wrapper);
    });
    article.querySelectorAll("div.arithmatex").forEach(formula => {
      formula.setAttribute("role", "region");
      formula.setAttribute("aria-label", "公式，可横向滚动查看");
      let hint = formula.nextElementSibling;
      if (!hint?.classList.contains("reader-math-hint")) {
        hint = document.createElement("div");
        hint.className = "reader-math-hint";
        // Keep navigation hints out of copied text and AI selection contexts.
        hint.setAttribute("aria-hidden", "true");
        hint.hidden = true;
        formula.after(hint);
      }
      tableResizeObserver.observe(formula);
    });
  }

  function initialize() {
    cleanupReadingProgress();
    const documentMeta = document.querySelector(".reader-document-meta");
    const documentId = documentMeta?.dataset.documentId || "";
    const researchPage = documentId.startsWith("papers/") || documentId === "report/index.md";
    document.body.classList.toggle("reader-research-page", researchPage);
    const article = document.querySelector(".md-content__inner");
    simplifySidebar();
    simplifyHeaderTitle(documentId);
    requestAnimationFrame(() => prepareReadingTables(article));
    const headings = Array.from(article?.querySelectorAll("h2[id]") || []);
    if (document.querySelector(".md-sidebar--primary") && !toggle) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "reader-nav-toggle";
      toggle.addEventListener("click", () => {
        const drawer = document.getElementById("__drawer");
        if (window.matchMedia("(max-width: 76.1875em)").matches && drawer) {
          drawer.checked = !drawer.checked;
          drawer.dispatchEvent(new Event("change", { bubbles: true }));
          apply(false);
          return;
        }
        const collapsed = !document.body.classList.contains("reader-nav-collapsed");
        localStorage.setItem(storageKey, String(collapsed));
        apply(collapsed);
      });
      document.body.appendChild(toggle);
      document.getElementById("__drawer")?.addEventListener("change", () => apply(localStorage.getItem(storageKey) === "true"));
    }
    if (toggle) apply(localStorage.getItem(storageKey) === "true");
    buildSectionTools();
    if (researchPage && documentMeta && article) startReadingProgress(documentMeta, article, headings);
  }

  function buildSectionTools() {
    sectionResizeObserver?.disconnect();
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
      '<button class="reader-appearance-focus" type="button" data-reader-focus aria-pressed="false" title="收起两侧栏，专注阅读">专注</button>',
      '<button class="reader-appearance-toggle" type="button" data-reader-appearance aria-expanded="false" aria-controls="reader-appearance-panel" aria-label="阅读设置" title="阅读设置">Aa</button>',
      '<div class="reader-section-tools__menu" hidden></div>'
    ].join("");
    const anchor = article.querySelector(".paper-reading-card") || article.querySelector("h1");
    anchor?.insertAdjacentElement("afterend", sectionTools);
    window.ReaderAppearance?.mount(sectionTools);
    const updateClearance = () => {
      const top = parseFloat(getComputedStyle(sectionTools).top) || 0;
      article.style.setProperty("--reader-scroll-clearance", `${top + sectionTools.offsetHeight + 24}px`);
    };
    sectionResizeObserver = new ResizeObserver(updateClearance);
    sectionResizeObserver.observe(sectionTools);
    updateClearance();

    const menu = sectionTools.querySelector(".reader-section-tools__menu");
    headings.forEach((heading, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.sectionIndex = String(index);
      const number = document.createElement("small");
      number.textContent = String(index + 1).padStart(2, "0");
      const label = document.createElement("span");
      label.textContent = heading.textContent.replace(/\s*\u00b6\s*$/, "").trim();
      button.append(number, label);
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
      const marker = window.scrollY + (parseFloat(getComputedStyle(article).getPropertyValue("--reader-scroll-clearance")) || 150) + 2;
      activeIndex = 0;
      headings.forEach((heading, index) => {
        if (heading.getBoundingClientRect().top + window.scrollY <= marker) activeIndex = index;
      });
      const articleTop = article.getBoundingClientRect().top + window.scrollY;
      const available = Math.max(1, article.scrollHeight - window.innerHeight * 0.7);
      const percentage = Math.max(0, Math.min(100, ((window.scrollY - articleTop) / available) * 100));
      sectionTools.style.setProperty("--reader-progress", percentage + "%");
      current.querySelector("span").textContent = headings[activeIndex].textContent.replace(/\s*\u00b6\s*$/, "").trim();
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
  window.addEventListener("reader:appearance-change", () => placeReadingMemo());
  window.addEventListener("resize", () => {
    placeReadingMemo();
    apply(localStorage.getItem(storageKey) === "true");
  });
})();
