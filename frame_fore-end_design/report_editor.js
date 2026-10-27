const CONFIG = {
  apiBaseUrl: "",
  requestTimeoutMs: 60000,
  maxReadReportMs: 15000,
  useMockBackend: false,
  maxLogItems: 50,
  previewSettingsStorageKey: "compare_report_preview_style_v1"
};

const params = new URLSearchParams(window.location.search);
function getDefaultApiBaseUrl() {
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    if (window.location.port === "5173") {
      return "http://127.0.0.1:8080";
    }
    return window.location.origin;
  }
  return "http://127.0.0.1:8080";
}

const resolvedApiBaseUrl = (params.get("apiBaseUrl") || CONFIG.apiBaseUrl || getDefaultApiBaseUrl()).replace(/\/+$/, "");
const taskId = params.get("taskId") || "";
const reportId = params.get("reportId") || "";
const reportPath = params.get("reportPath") || "";

// 强制要求 reportPath，禁止自动探测和 fallback
if (!reportPath) {
  alert("未指定报告路径，无法读取报告内容。请通过首页按钮进入。");
  throw new Error("未指定 reportPath，禁止自动探测。");
}

const state = {
  mode: "preview",
  contentMd: "",
  dirty: false,
  savedAt: "",
  loadFailed: false,
  logItems: [],
  versionsVisible: false,
  versions: [],
  previewVersion: null,
  previewVersionContent: "",
  rewrite: {
    selection: null,
    pendingResult: "",
    instruction: ""
  },
  previewStyle: {
    fontPreset: "sans",
    baseSize: 16
  }
};

const dom = {
  headMeta: document.querySelector("#head-meta"),
  previewModeBtn: document.querySelector("#preview-mode-btn"),
  editModeBtn: document.querySelector("#edit-mode-btn"),
  reloadBtn: document.querySelector("#reload-btn"),
  saveBtn: document.querySelector("#save-btn"),
  versionsBtn: document.querySelector("#versions-btn"),
  versionsPanel: document.querySelector("#versions-panel"),
  versionsRefreshBtn: document.querySelector("#versions-refresh-btn"),
  versionsList: document.querySelector("#versions-list"),
  versionPreviewModal: document.querySelector("#version-preview-modal"),
  versionPreviewMeta: document.querySelector("#version-preview-meta"),
  versionPreviewContent: document.querySelector("#version-preview-content"),
  versionPreviewCloseBtn: document.querySelector("#version-preview-close-btn"),
  versionPreviewCancelBtn: document.querySelector("#version-preview-cancel-btn"),
  versionPreviewDeleteBtn: document.querySelector("#version-preview-delete-btn"),
  versionPreviewRestoreBtn: document.querySelector("#version-preview-restore-btn"),
  exportPdfBtn: document.querySelector("#export-pdf-btn"),
  exportDocxBtn: document.querySelector("#export-docx-btn"),
  previewFontSelect: document.querySelector("#preview-font-select"),
  previewSizeSelect: document.querySelector("#preview-size-select"),
  previewStyleResetBtn: document.querySelector("#preview-style-reset-btn"),
  previewPanel: document.querySelector("#preview-panel"),
  editPanel: document.querySelector("#edit-panel"),
  editorTextarea: document.querySelector("#editor-textarea"),
  rewriteSelectionMeta: document.querySelector("#rewrite-selection-meta"),
  rewriteInstruction: document.querySelector("#rewrite-instruction"),
  rewriteGenerateBtn: document.querySelector("#rewrite-generate-btn"),
  rewriteApplyBtn: document.querySelector("#rewrite-apply-btn"),
  rewriteResult: document.querySelector("#rewrite-result"),
  editorLog: document.querySelector("#editor-log")
};

const PREVIEW_FONT_PRESETS = {
  sans: {
    fontFamily: '"Noto Sans SC", "PingFang SC", "Segoe UI", sans-serif',
    lineHeight: "1.7",
    letterSpacing: "0",
    fontWeight: "400"
  },
  serif: {
    fontFamily: '"Charter", "Palatino Linotype", "Times New Roman", "Songti SC", serif',
    lineHeight: "1.85",
    letterSpacing: "0.02em",
    fontWeight: "500"
  },
  song: {
    fontFamily: '"Source Han Serif SC", "Noto Serif SC", "STSong", serif',
    lineHeight: "1.72",
    letterSpacing: "0",
    fontWeight: "400"
  },
  hei: {
    fontFamily: '"Source Han Sans SC", "Noto Sans SC", "Microsoft YaHei", sans-serif',
    lineHeight: "1.68",
    letterSpacing: "0.005em",
    fontWeight: "400"
  },
  wenkai: {
    fontFamily: '"LXGW WenKai", "KaiTi", "Kaiti SC", serif',
    lineHeight: "1.78",
    letterSpacing: "0.01em",
    fontWeight: "400"
  }
};

const PREVIEW_SIZE_OPTIONS = new Set([14, 15, 16, 18]);

let api = null;

async function safeBootstrap() {
  try {
    await bootstrap();
  } catch (error) {
    const message = `初始化失败：${readableError(error)}`;
    if (dom.editorLog) {
      dom.editorLog.innerHTML = "";
      const li = document.createElement("li");
      li.style.color = "#8d2929";
      li.textContent = message;
      dom.editorLog.appendChild(li);
    }
  }
}

async function bootstrap() {
  api = createReportApiClient();
  initPreviewStyleSettings();
  bindEvents();
  renderHeadMeta();
  setBusy(true);
  appendLog("开始读取最新 report.md ...");

  try {
    const content = await withTimeout(
      api.fetchLatestReportMarkdown({ taskId, reportId, reportPath }),
      CONFIG.maxReadReportMs,
      "读取 report.md 超时"
    );
    applyReportContent(content);
    appendLog("报告已加载，可切换到编辑模式修改。", "ok");
  } catch (error) {
    markReportLoadFailed(error);
    logReadFailure("加载失败，已阻止编辑和导出", error);
  } finally {
    setBusy(false);
  }
}

function bindEvents() {
  dom.previewModeBtn.addEventListener("click", () => switchMode("preview"));
  dom.editModeBtn.addEventListener("click", () => switchMode("edit"));
  dom.versionsBtn.addEventListener("click", onToggleVersionsPanel);
  dom.versionsRefreshBtn.addEventListener("click", loadReportVersions);
  dom.versionPreviewCloseBtn.addEventListener("click", closeVersionPreviewModal);
  dom.versionPreviewCancelBtn.addEventListener("click", closeVersionPreviewModal);
  dom.versionPreviewDeleteBtn.addEventListener("click", onDeletePreviewedVersion);
  dom.versionPreviewRestoreBtn.addEventListener("click", onRestorePreviewedVersion);
  dom.versionPreviewModal.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.versionPreviewClose === "true") {
      closeVersionPreviewModal();
    }
  });
  dom.reloadBtn.addEventListener("click", onResetReport);
  dom.saveBtn.addEventListener("click", onSave);
  dom.exportPdfBtn.addEventListener("click", () => onConvert("pdf"));
  dom.exportDocxBtn.addEventListener("click", () => onConvert("docx"));
  dom.editorTextarea.addEventListener("input", onEditorInput);
  dom.editorTextarea.addEventListener("mouseup", syncRewriteSelectionFromEditor);
  dom.editorTextarea.addEventListener("keyup", syncRewriteSelectionFromEditor);
  dom.editorTextarea.addEventListener("select", syncRewriteSelectionFromEditor);
  dom.rewriteInstruction.addEventListener("input", onRewriteInstructionInput);
  dom.rewriteGenerateBtn.addEventListener("click", onGenerateRewriteSuggestion);
  dom.rewriteApplyBtn.addEventListener("click", onApplyRewriteSuggestion);
  if (dom.previewFontSelect) {
    dom.previewFontSelect.addEventListener("change", onPreviewFontChange);
  }
  if (dom.previewSizeSelect) {
    dom.previewSizeSelect.addEventListener("change", onPreviewSizeChange);
  }
  if (dom.previewStyleResetBtn) {
    dom.previewStyleResetBtn.addEventListener("click", onResetPreviewStyle);
  }
}

function switchMode(mode) {
  state.mode = mode;
  const isPreview = mode === "preview";
  dom.previewModeBtn.classList.toggle("active", isPreview);
  dom.editModeBtn.classList.toggle("active", !isPreview);
  dom.previewModeBtn.setAttribute("aria-selected", String(isPreview));
  dom.editModeBtn.setAttribute("aria-selected", String(!isPreview));
  dom.previewPanel.classList.toggle("hidden", !isPreview);
  dom.editPanel.classList.toggle("hidden", isPreview);
  if (isPreview) {
    renderPreview();
  }
}

function renderHeadMeta() {
  const parts = [];
  parts.push(`来源：${api.mode === "mock" ? "Mock" : "Real"}`);
  parts.push(`taskId: ${taskId || "-"}`);
  parts.push(`reportId: ${reportId || "-"}`);
  parts.push(`reportPath: ${reportPath || "(自动探测)"}`);
  if (state.savedAt) {
    parts.push(`最近保存：${state.savedAt}`);
  }
  dom.headMeta.textContent = parts.join(" | ");
}

function renderEditor() {
  dom.editorTextarea.value = state.contentMd;
}

function renderPreview() {
  dom.previewPanel.innerHTML = renderMarkdownStable(state.contentMd);
  renderMathInMarkdown(dom.previewPanel);
  renderMathInTooltips(dom.previewPanel);
}

function onEditorInput() {
  state.contentMd = dom.editorTextarea.value;
  state.dirty = true;
  syncRewriteSelectionFromEditor();
}

function onRewriteInstructionInput() {
  state.rewrite.instruction = dom.rewriteInstruction.value;
  updateRewriteButtons();
}

function syncRewriteSelectionFromEditor() {
  if (!dom.editorTextarea) {
    return;
  }
  const start = dom.editorTextarea.selectionStart;
  const end = dom.editorTextarea.selectionEnd;
  if (start === end) {
    state.rewrite.selection = null;
    renderRewriteSelectionMeta();
    updateRewriteButtons();
    return;
  }

  const text = dom.editorTextarea.value.slice(start, end);
  state.rewrite.selection = { start, end, text };
  renderRewriteSelectionMeta();
  updateRewriteButtons();
}

function renderRewriteSelectionMeta() {
  if (!dom.rewriteSelectionMeta) {
    return;
  }
  const selection = state.rewrite.selection;
  if (!selection) {
    dom.rewriteSelectionMeta.textContent = "当前未选中文本";
    return;
  }
  const len = selection.end - selection.start;
  const preview = selection.text.replace(/\s+/g, " ").slice(0, 80);
  dom.rewriteSelectionMeta.textContent = `已选中 ${len} 字符：${preview}${selection.text.length > 80 ? "..." : ""}`;
}

function updateRewriteButtons() {
  const hasSelection = Boolean(state.rewrite.selection && state.rewrite.selection.text.trim());
  const hasInstruction = Boolean((state.rewrite.instruction || "").trim());
  dom.rewriteGenerateBtn.disabled = !hasSelection || !hasInstruction;
  dom.rewriteApplyBtn.disabled = !(state.rewrite.pendingResult && state.rewrite.selection);
}

async function onGenerateRewriteSuggestion() {
  if (state.loadFailed) {
    appendLog("报告读取失败，禁止 AI 改写。", "error");
    return;
  }
  const selection = state.rewrite.selection;
  const instruction = (state.rewrite.instruction || "").trim();

  if (!selection || !selection.text.trim()) {
    appendLog("请先在编辑框中选中要改写的文本。", "error");
    return;
  }
  if (!instruction) {
    appendLog("请先输入修改意见。", "error");
    return;
  }

  setBusy(true);
  appendLog("正在请求 AI 改写建议...");
  try {
    const data = await api.rewriteSelection({
      taskId,
      reportId,
      reportPath,
      instruction,
      selection
    });

    const rewrittenText = (data && data.rewrittenText ? String(data.rewrittenText) : "").trim();
    if (!rewrittenText) {
      throw new Error("改写结果为空");
    }

    state.rewrite.pendingResult = rewrittenText;
    dom.rewriteResult.value = rewrittenText;
    updateRewriteButtons();
    appendLog("已生成改写建议，可选择应用到当前选区。", "ok");
  } catch (error) {
    appendLog(`生成建议失败：${readableError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

async function onApplyRewriteSuggestion() {
  const selection = state.rewrite.selection;
  const rewrittenText = (state.rewrite.pendingResult || "").trim();
  if (!selection || !rewrittenText) {
    appendLog("暂无可应用的改写建议。", "error");
    return;
  }

  const currentSlice = dom.editorTextarea.value.slice(selection.start, selection.end);
  if (currentSlice !== selection.text) {
    appendLog("选区内容已变化，请重新选中并重新生成建议。", "error");
    return;
  }

  const before = dom.editorTextarea.value.slice(0, selection.start);
  const after = dom.editorTextarea.value.slice(selection.end);
  const merged = `${before}${rewrittenText}${after}`;

  dom.editorTextarea.value = merged;
  state.contentMd = merged;
  state.dirty = true;

  const newEnd = selection.start + rewrittenText.length;
  dom.editorTextarea.focus();
  dom.editorTextarea.setSelectionRange(selection.start, newEnd);

  state.rewrite.selection = {
    start: selection.start,
    end: newEnd,
    text: rewrittenText,
  };
  state.rewrite.pendingResult = "";
  dom.rewriteResult.value = "";
  renderRewriteSelectionMeta();
  updateRewriteButtons();

  setBusy(true);
  try {
    const result = await api.saveReportMarkdown(state.contentMd, { taskId, reportId, reportPath, reason: "rewrite" });
    state.dirty = false;
    state.savedAt = result.savedAt || new Date().toLocaleString();
    renderHeadMeta();
    if (state.versionsVisible) {
      await loadReportVersions({ manageBusy: false });
    }
    appendLog("改写建议已应用并自动保存。", "ok");
  } catch (error) {
    state.dirty = true;
    appendLog(`改写已应用，但自动保存失败：${readableError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

async function onResetReport() {
  if (state.loadFailed) {
    appendLog("报告读取失败，无法重置。请从首页重新打开报告。", "error");
    return;
  }
  if (!window.confirm("确认重置报告吗？将基于后端原始 report.md 覆盖当前编辑副本。")) {
    return;
  }

  setBusy(true);
  appendLog("正在重置报告...");
  try {
    const content = await api.resetReportMarkdown({ taskId, reportId, reportPath });
    applyReportContent(content);
    appendLog("报告已重置为原始版本。", "ok");
  } catch (error) {
    appendLog(`重置失败：${readableError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

function applyReportContent(content) {
  state.loadFailed = false;
  state.contentMd = content;
  state.dirty = false;
  state.rewrite.selection = null;
  state.rewrite.pendingResult = "";
  renderEditor();
  if (dom.rewriteResult) {
    dom.rewriteResult.value = "";
  }
  renderRewriteSelectionMeta();
  updateRewriteButtons();
  renderPreview();
}

function markReportLoadFailed(error) {
  state.loadFailed = true;
  state.contentMd = "";
  state.dirty = false;
  state.rewrite.selection = null;
  state.rewrite.pendingResult = "";
  if (dom.editorTextarea) {
    dom.editorTextarea.value = "";
    dom.editorTextarea.placeholder = "报告读取失败，已禁止编辑和导出。请返回首页重新打开报告或检查后端日志。";
  }
  if (dom.rewriteResult) {
    dom.rewriteResult.value = "";
  }
  if (dom.previewPanel) {
    dom.previewPanel.textContent = "报告读取失败，未加载真实 report.md。已禁止编辑、保存和导出。错误：" + readableError(error);
  }
  renderRewriteSelectionMeta();
  updateRewriteButtons();
}

function logReadFailure(prefix, error) {
  appendLog(`${prefix}：${readableError(error)}`, "error");
  if (api && typeof api.getDebugSummary === "function") {
    appendLog(`读取调试：${api.getDebugSummary()}`, "error");
  }
}

async function onToggleVersionsPanel() {
  state.versionsVisible = !state.versionsVisible;
  dom.versionsPanel.classList.toggle("hidden", !state.versionsVisible);
  dom.versionsBtn.textContent = state.versionsVisible ? "隐藏历史版本" : "历史版本";
  if (state.versionsVisible) {
    await loadReportVersions();
  }
}

async function loadReportVersions(options = {}) {
  const manageBusy = options.manageBusy !== false;
  if (manageBusy) {
    setBusy(true);
  }
  renderVersionsList("正在加载历史版本...");
  try {
    state.versions = await api.listReportVersions({ taskId, reportId, reportPath });
    renderVersionsList();
    appendLog(`已加载 ${state.versions.length} 个历史版本。`, "ok");
  } catch (error) {
    renderVersionsList("历史版本加载失败。");
    appendLog(`历史版本加载失败：${readableError(error)}`, "error");
  } finally {
    if (manageBusy) {
      setBusy(false);
    }
  }
}

function renderVersionsList(message = "") {
  if (message) {
    dom.versionsList.textContent = message;
    return;
  }
  dom.versionsList.innerHTML = "";
  if (!state.versions.length) {
    dom.versionsList.textContent = "暂无历史版本。点击保存修改后会生成版本。";
    return;
  }
  state.versions.forEach((version) => {
    const row = document.createElement("div");
    row.className = "version-item";

    const meta = document.createElement("div");
    meta.className = "version-meta";
    const reasonText = version.reason === "rewrite" ? "AI 改写" : "保存";
    meta.innerHTML = `<strong>${escapeHtml(version.createdAt || version.id)}</strong><span>${reasonText} | ${formatBytes(version.size || 0)}</span>`;

    const actions = document.createElement("div");
    actions.className = "version-actions";
    const previewBtn = document.createElement("button");
    previewBtn.type = "button";
    previewBtn.className = "secondary";
    previewBtn.textContent = "预览";
    previewBtn.addEventListener("click", () => previewReportVersion(version));
    const rollbackBtn = document.createElement("button");
    rollbackBtn.type = "button";
    rollbackBtn.className = "primary";
    rollbackBtn.textContent = "恢复";
    rollbackBtn.addEventListener("click", () => rollbackReportVersion(version));
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "danger";
    deleteBtn.textContent = "删除";
    deleteBtn.addEventListener("click", () => deleteReportVersion(version));
    actions.append(previewBtn, rollbackBtn, deleteBtn);

    row.append(meta, actions);
    dom.versionsList.appendChild(row);
  });
}

async function previewReportVersion(version) {
  setBusy(true);
  appendLog(`正在预览历史版本：${version.id}`);
  try {
    const content = await api.readReportVersion({ taskId, reportId, reportPath, versionId: version.id });
    openVersionPreviewModal(version, content);
    appendLog("已打开历史版本预览窗口。", "ok");
  } catch (error) {
    appendLog(`预览历史版本失败：${readableError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

function openVersionPreviewModal(version, content) {
  state.previewVersion = version;
  state.previewVersionContent = content;
  const reasonText = version.reason === "rewrite" ? "AI 改写" : "保存";
  dom.versionPreviewMeta.textContent = `${version.createdAt || version.id} | ${reasonText} | ${formatBytes(version.size || 0)}`;
  dom.versionPreviewContent.innerHTML = renderMarkdownStable(content);
  renderMathInMarkdown(dom.versionPreviewContent);
  renderMathInTooltips(dom.versionPreviewContent);
  dom.versionPreviewModal.classList.remove("hidden");
  dom.versionPreviewModal.setAttribute("aria-hidden", "false");
}

function closeVersionPreviewModal() {
  state.previewVersion = null;
  state.previewVersionContent = "";
  dom.versionPreviewContent.innerHTML = "";
  dom.versionPreviewModal.classList.add("hidden");
  dom.versionPreviewModal.setAttribute("aria-hidden", "true");
}

async function onRestorePreviewedVersion() {
  if (!state.previewVersion) {
    appendLog("暂无可恢复的预览版本。", "error");
    return;
  }
  await rollbackReportVersion(state.previewVersion);
}

async function onDeletePreviewedVersion() {
  if (!state.previewVersion) {
    appendLog("暂无可删除的预览版本。", "error");
    return;
  }
  await deleteReportVersion(state.previewVersion);
}

async function deleteReportVersion(version) {
  if (!window.confirm(`确认删除历史版本 ${version.createdAt || version.id} 吗？此操作不可恢复。`)) {
    return;
  }
  setBusy(true);
  appendLog(`正在删除历史版本：${version.id}`);
  try {
    await api.deleteReportVersion({ taskId, reportId, reportPath, versionId: version.id });
    if (state.previewVersion && state.previewVersion.id === version.id) {
      closeVersionPreviewModal();
    }
    if (state.versionsVisible) {
      await loadReportVersions({ manageBusy: false });
    }
    appendLog("历史版本已删除。", "ok");
  } catch (error) {
    appendLog(`删除历史版本失败：${readableError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

async function rollbackReportVersion(version) {
  if (!window.confirm(`确认恢复历史版本 ${version.createdAt || version.id} 吗？当前编辑稿会被覆盖。`)) {
    return;
  }
  setBusy(true);
  appendLog(`正在恢复历史版本：${version.id}`);
  try {
    const result = await api.rollbackReportVersion({ taskId, reportId, reportPath, versionId: version.id });
    applyReportContent(result.contentMd || "");
    state.savedAt = result.savedAt || new Date().toLocaleString();
    renderHeadMeta();
    closeVersionPreviewModal();
    appendLog("历史版本已恢复为当前编辑稿。", "ok");
  } catch (error) {
    appendLog(`恢复历史版本失败：${readableError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

function formatBytes(size) {
  if (size < 1024) {
    return `${size} B`;
  }
  return `${(size / 1024).toFixed(1)} KB`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function onSave() {
  if (state.loadFailed) {
    appendLog("报告读取失败，禁止保存。", "error");
    return;
  }
  setBusy(true);
  appendLog("正在保存编辑内容...");
  try {
    const result = await api.saveReportMarkdown(state.contentMd, { taskId, reportId, reportPath, reason: "save" });
    state.dirty = false;
    state.savedAt = result.savedAt || new Date().toLocaleString();
    renderHeadMeta();
    if (state.versionsVisible) {
      await loadReportVersions({ manageBusy: false });
    }
    appendLog("保存成功。", "ok");
  } catch (error) {
    appendLog(`保存失败：${readableError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

async function onConvert(format) {
  if (state.loadFailed) {
    appendLog("报告读取失败，禁止导出。", "error");
    return;
  }
  if (!["pdf", "docx"].includes(format)) {
    return;
  }
  setBusy(true);
  appendLog(`开始转换 ${format.toUpperCase()} ...`);
  try {
    const result = await api.convertReport(format, { taskId, reportId, reportPath, contentMd: state.contentMd });
    if (!result || !result.success) {
      throw new Error(result && result.error ? result.error : `${format.toUpperCase()} 转换未成功`);
    }
    if (result.downloadUrl) {
      await downloadFileFromUrl(result.downloadUrl, result.fileName || `report.${format}`);
      appendLog(`${format.toUpperCase()} 转换成功，已下载到本地。`, "ok");
    } else if (result.fileBlob) {
      triggerDownload(result.fileBlob, result.fileName || `report.${format}`);
      appendLog(`${format.toUpperCase()} 转换成功，已下载文件。`, "ok");
    } else {
      throw new Error(`${format.toUpperCase()} 转换成功但缺少下载结果`);
    }
  } catch (error) {
    appendLog(`转换失败：${readableError(error)}`, "error");
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  const locked = busy || state.loadFailed;
  dom.versionsBtn.disabled = locked;
  dom.versionsRefreshBtn.disabled = locked;
  dom.reloadBtn.disabled = locked;
  dom.saveBtn.disabled = locked;
  dom.exportPdfBtn.disabled = locked;
  dom.exportDocxBtn.disabled = locked;
  if (dom.editModeBtn) {
    dom.editModeBtn.disabled = locked;
  }
  dom.rewriteGenerateBtn.disabled = locked || !state.rewrite.selection || !(state.rewrite.instruction || "").trim();
  dom.rewriteApplyBtn.disabled = locked || !(state.rewrite.pendingResult && state.rewrite.selection);
}

function getDefaultPreviewStyle() {
  return {
    fontPreset: "sans",
    baseSize: 16
  };
}

function initPreviewStyleSettings() {
  state.previewStyle = loadPreviewStyleFromStorage();
  syncPreviewStyleControls();
  applyPreviewStyleToDocument();
}

function loadPreviewStyleFromStorage() {
  const defaults = getDefaultPreviewStyle();
  try {
    const raw = window.localStorage.getItem(CONFIG.previewSettingsStorageKey);
    if (!raw) {
      return defaults;
    }
    const parsed = JSON.parse(raw);
    const fontPreset = PREVIEW_FONT_PRESETS[parsed.fontPreset] ? parsed.fontPreset : defaults.fontPreset;
    const numericSize = Number(parsed.baseSize);
    const baseSize = PREVIEW_SIZE_OPTIONS.has(numericSize) ? numericSize : defaults.baseSize;
    return { fontPreset, baseSize };
  } catch (_err) {
    return defaults;
  }
}

function persistPreviewStyle() {
  try {
    window.localStorage.setItem(CONFIG.previewSettingsStorageKey, JSON.stringify(state.previewStyle));
  } catch (_err) {
    // Ignore storage failures and keep runtime state only.
  }
}

function syncPreviewStyleControls() {
  if (dom.previewFontSelect) {
    dom.previewFontSelect.value = state.previewStyle.fontPreset;
  }
  if (dom.previewSizeSelect) {
    dom.previewSizeSelect.value = String(state.previewStyle.baseSize);
  }
}

function applyPreviewStyleToDocument() {
  const root = document.documentElement;
  const preset = PREVIEW_FONT_PRESETS[state.previewStyle.fontPreset] || PREVIEW_FONT_PRESETS.sans;
  root.style.setProperty("--preview-font-family", preset.fontFamily);
  root.style.setProperty("--preview-base-size", String(state.previewStyle.baseSize));
  root.style.setProperty("--preview-line-height", preset.lineHeight);
  root.style.setProperty("--preview-letter-spacing", preset.letterSpacing);
  root.style.setProperty("--preview-font-weight", preset.fontWeight);
}

function onPreviewFontChange(event) {
  const selected = event.target.value;
  if (!PREVIEW_FONT_PRESETS[selected]) {
    return;
  }
  state.previewStyle.fontPreset = selected;
  applyPreviewStyleToDocument();
  persistPreviewStyle();
  appendLog(`已应用预览字体：${event.target.options[event.target.selectedIndex].text}`, "ok");
}

function onPreviewSizeChange(event) {
  const selected = Number(event.target.value);
  if (!PREVIEW_SIZE_OPTIONS.has(selected)) {
    return;
  }
  state.previewStyle.baseSize = selected;
  applyPreviewStyleToDocument();
  persistPreviewStyle();
  appendLog(`已应用预览字号：${selected}`, "ok");
}

function onResetPreviewStyle() {
  state.previewStyle = getDefaultPreviewStyle();
  syncPreviewStyleControls();
  applyPreviewStyleToDocument();
  persistPreviewStyle();
  appendLog("已重置预览字体与字号。", "ok");
}

function appendLog(message, type = "info") {
  if (!dom.editorLog) {
    return;
  }
  const now = new Date();
  const stamp = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
  const line = `${stamp} ${message}`;
  state.logItems.push(line);
  if (state.logItems.length > CONFIG.maxLogItems) {
    state.logItems.shift();
  }
  dom.editorLog.innerHTML = "";
  state.logItems.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    if (type === "error" && item === line) {
      li.style.color = "#8d2929";
    }
    if (type === "ok" && item === line) {
      li.style.color = "#1e5f46";
    }
    dom.editorLog.appendChild(li);
  });
  dom.editorLog.scrollTop = dom.editorLog.scrollHeight;
}

function createReportApiClient() {
  // 只允许真实读取唯一 reportPath，不再 fallback mock
  return new RealReportApiClient(resolvedApiBaseUrl);
}

class RealReportApiClient {
  constructor(baseUrl) {
    this.mode = "real";
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.lastAttempts = [];
  }

  async fetchLatestReportMarkdown(context) {
    this.lastAttempts = [];
    const payload = {
      taskId: context.taskId || "",
      reportId: context.reportId || "",
      reportPath: context.reportPath || ""
    };
    this.lastAttempts.push(`尝试: ${this.baseUrl}/api/reports/read-md`);
    try {
      const data = await this.requestJson(`${this.baseUrl}/api/reports/read-md`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const text = data.contentMd || "";
      if (text && text.trim()) {
        this.lastAttempts.push(`成功: ${data.reportPath || payload.reportPath}`);
        return text;
      }
      throw new Error("报告内容为空");
    } catch (err) {
      this.lastAttempts.push(`失败: ${payload.reportPath} (${readableError(err)})`);
      throw new Error(`指定 reportPath 读取失败: ${payload.reportPath}`);
    }
  }
// (已移除 fallback 代码块)

  getDebugSummary() {
    if (!this.lastAttempts.length) {
      return "无读取尝试记录";
    }
    return this.lastAttempts.slice(-8).join(" | ");
  }

  async saveReportMarkdown(contentMd, context) {
    const payload = {
      taskId: context.taskId,
      reportId: context.reportId,
      reportPath: context.reportPath,
      reason: context.reason || "save",
      contentMd
    };

    await this.requestJson(`${this.baseUrl}/api/reports/save-md`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    return { savedAt: new Date().toLocaleString() };
  }

  async listReportVersions(context) {
    const url = new URL(`${this.baseUrl}/api/reports/versions`);
    if (context.reportPath) {
      url.searchParams.set("reportPath", context.reportPath);
    }
    if (context.reportId) {
      url.searchParams.set("reportId", context.reportId);
    }
    const data = await this.requestJson(url.toString());
    return Array.isArray(data.versions) ? data.versions : [];
  }

  async readReportVersion(context) {
    const data = await this.requestJson(`${this.baseUrl}/api/reports/versions/read`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        taskId: context.taskId,
        reportId: context.reportId,
        reportPath: context.reportPath,
        versionId: context.versionId,
      })
    });
    return data.contentMd || "";
  }

  async rollbackReportVersion(context) {
    return this.requestJson(`${this.baseUrl}/api/reports/versions/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        taskId: context.taskId,
        reportId: context.reportId,
        reportPath: context.reportPath,
        versionId: context.versionId,
      })
    });
  }

  async deleteReportVersion(context) {
    return this.requestJson(`${this.baseUrl}/api/reports/versions/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        taskId: context.taskId,
        reportId: context.reportId,
        reportPath: context.reportPath,
        versionId: context.versionId,
      })
    });
  }

  async resetReportMarkdown(context) {
    const payload = {
      taskId: context.taskId,
      reportId: context.reportId,
      reportPath: context.reportPath,
    };

    const data = await this.requestJson(`${this.baseUrl}/api/reports/reset-md`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    return data.contentMd || "";
  }

  async convertReport(format, context) {
    const payload = {
      taskId: context.taskId,
      reportId: context.reportId,
      reportPath: context.reportPath,
      contentMd: context.contentMd,
      format
    };

    const data = await this.requestJson(`${this.baseUrl}/api/reports/convert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const rawUrl = data.downloadUrl || data.url || "";
    const downloadUrl = rawUrl
      ? new URL(rawUrl, `${resolvedApiBaseUrl}/`).toString()
      : "";

    return {
      success: Boolean(data.success),
      error: data.error || "",
      downloadUrl,
      fileName: data.fileName || (data.filePath ? String(data.filePath).split("/").pop() : "")
    };
  }

  async rewriteSelection(context) {
    const payload = {
      taskId: context.taskId,
      reportId: context.reportId,
      reportPath: context.reportPath,
      instruction: context.instruction,
      selection: {
        start: context.selection.start,
        end: context.selection.end,
        text: context.selection.text,
      },
    };

    return this.requestJson(`${this.baseUrl}/api/reports/rewrite`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  }

  async requestRaw(url, options = {}) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), CONFIG.requestTimeoutMs);
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal
      });
      if (!response.ok) {
        const text = await response.text();
        let detail = "";
        try {
          const parsed = JSON.parse(text || "{}");
          detail = parsed.detail || parsed.message || "";
        } catch (_err) {
          detail = text || "";
        }
        throw new Error(detail ? `HTTP ${response.status}: ${detail}` : `HTTP ${response.status}`);
      }
      return response;
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  async requestJson(url, options = {}) {
    const response = await this.requestRaw(url, options);
    const type = response.headers.get("content-type") || "";
    if (!type.includes("application/json")) {
      return {};
    }
    return response.json();
  }
}

function triggerDownload(blob, fileName) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

async function downloadFileFromUrl(url, fallbackName) {
  const response = await fetch(url, { method: "GET" });
  if (!response.ok) {
    throw new Error(`下载失败: HTTP ${response.status}`);
  }

  const blob = await response.blob();
  const contentDisposition = response.headers.get("content-disposition") || "";
  const match = contentDisposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
  const fileName = decodeURIComponent((match && (match[1] || match[2])) || fallbackName || "report");
  triggerDownload(blob, fileName);
}

function readableError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

async function withTimeout(promise, timeoutMs, errorMessage) {
  let timeoutId = null;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = window.setTimeout(() => {
      reject(new Error(errorMessage));
    }, timeoutMs);
  });

  try {
    return await Promise.race([promise, timeoutPromise]);
  } finally {
    if (timeoutId) {
      window.clearTimeout(timeoutId);
    }
  }
}

function renderMarkdownStable(rawText) {
  const prepared = normalizeAnnotationSource(rawText);
  const extracted = extractAnnotationTokens(prepared);
  const renderer = createMarkdownRenderer();
  const renderedHtml = renderer.render(extracted.markdown);
  return rehydrateAnnotationTokens(renderedHtml, extracted.tokens);
}

function createMarkdownRenderer() {
  if (typeof window.markdownit === "function") {
    const md = window.markdownit({
      html: false,
      linkify: true,
      typographer: false,
      breaks: false
    });
    if (typeof window.markdownitFootnote === "function") {
      md.use(window.markdownitFootnote);
    }
    return md;
  }

  return {
    render(markdown) {
      return renderMarkdownLite(markdown);
    }
  };
}

function normalizeAnnotationSource(rawText) {
  const normalizeEscapedAnnotationTags = (text) => {
    if (!text.includes("&lt;") && !text.includes("&#60;")) {
      return text;
    }
    const textarea = document.createElement("textarea");
    textarea.innerHTML = text;
    const unescaped = textarea.value;
    if (unescaped.includes("<calculate") || unescaped.includes("<claim")) {
      return unescaped;
    }
    return text;
  };

  const unwrapAnnotationFencedBlocks = (text) =>
    text.replace(/```(?:markdown|md)?\s*\r?\n([\s\S]*?)\r?\n```/gi, (m, inner) => {
      if (inner.includes("<calculate") || inner.includes("<claim")) {
        return String(inner).trim();
      }
      return m;
    });

  const unwrapInlineCodeAnnotationTags = (text) =>
    text
      .replace(/`\s*(<claim\b[\s\S]*?<\/claim>)\s*`/gi, "$1")
      .replace(/`\s*(<calculate\b[\s\S]*?<\/calculate>)\s*`/gi, "$1");

  const normalizeMathFencedBlocks = (text) =>
    text.replace(/```math\s*\r?\n([\s\S]*?)\r?\n```/gi, (_m, inner) => {
      const expr = String(inner || "").trim();
      if (!expr) {
        return "";
      }
      return `$$\n${expr}\n$$`;
    });

  const normalizeFormulaFencedBlocks = (text) =>
    text.replace(
      /(^|\n)([ \t]{0,3})```(?:text|plain)?[ \t]*\r?\n([\s\S]*?)\r?\n[ \t]{0,3}```[ \t]*(?=\n|$)/gi,
      (match, prefix, _indent, inner) => {
        const content = String(inner || "").trim();
        if (!content) {
          return match;
        }

        const looksLikeFormula =
          /[=×÷]/.test(content) ||
          /(?:公式|年费用|建设投资|运维成本|折现率|通过率|网损|成本)/.test(content);
        const looksLikeCode =
          /(^|\n)\s*(?:const|let|var|function|import|from|class|def|return|if|for|while)\b/.test(content) ||
          /[{};]/.test(content);

        if (!looksLikeFormula || looksLikeCode) {
          return match;
        }

        return `${prefix}${content}\n`;
      }
    );

  let text = String(rawText || "");
  text = normalizeEscapedAnnotationTags(text);
  text = normalizeMathFencedBlocks(text);
  text = normalizeFormulaFencedBlocks(text);
  text = unwrapAnnotationFencedBlocks(text);
  text = unwrapInlineCodeAnnotationTags(text);

  return text;
}

function extractAnnotationTokens(markdown) {
  const tokens = [];
  let text = String(markdown || "");

  text = text.replace(/<calculate>([\s\S]*?)<\/calculate>/gi, (_match, contentRaw) => {
    const token = {
      type: "calculate",
      html: renderCalculateHtml(parseCalculateToken(contentRaw))
    };
    const marker = `@@ANNOTATION_CALCULATE_${tokens.length}@@`;
    tokens.push(token);
    return marker;
  });

  text = text.replace(/<claim\s*([^>]*)>([\s\S]*?)<\/claim>/gi, (_match, attrsRaw, innerRaw) => {
    const token = {
      type: "claim",
      html: renderClaimHtml(parseClaimToken(attrsRaw, innerRaw))
    };
    const marker = `@@ANNOTATION_CLAIM_${tokens.length}@@`;
    tokens.push(token);
    return marker;
  });

  return { markdown: text, tokens };
}

function rehydrateAnnotationTokens(html, tokens) {
  let output = String(html || "");
  tokens.forEach((token, index) => {
    const marker = token.type === "calculate"
      ? `@@ANNOTATION_CALCULATE_${index}@@`
      : `@@ANNOTATION_CLAIM_${index}@@`;
    output = output.replaceAll(marker, token.html);
  });
  return output;
}

function formatFormulaForTooltip(formulaStr) {
  let s = String(formulaStr || "").trim();
  if (!s) {
    return "";
  }

  s = s.replace(/\$\$\s*([\s\S]*?)\s*\$\$/g, (_m, expr) => `$${String(expr).trim()}$`);
  s = s.replace(/\\\[\s*([\s\S]*?)\s*\\\]/g, (_m, expr) => `\\(${String(expr).trim()}\\)`);
  s = s.replace(/\r?\n+/g, " ").replace(/\s{2,}/g, " ").trim();

  if (!s.includes("$") && !s.includes("\\(") && !s.includes("\\[")) {
    s = `$${s}$`;
  }

  return `<span class="calc-formula">${escapeHtml(s)}</span>`;
}

function mapCalcKey(rawKey) {
  const calcMap = {
    input: "计算输入",
    input_source: "数据来源",
    formula: "计算公式",
    output: "计算结果"
  };
  const normalized = String(rawKey || "").replaceAll(" ", "_");
  return calcMap[normalized] || rawKey;
}

function parseCalculateToken(contentRaw) {
  const content = String(contentRaw || "").trim();
  const sections = [];
  const sectionRegex = /(input|input_source|input source|formula|output):\s*([\s\S]*?)(?=\s*(?:input|input_source|input source|formula|output):|$)/gi;
  let match = sectionRegex.exec(content);
  while (match) {
    sections.push({ key: String(match[1] || "").trim(), value: String(match[2] || "").trim() });
    match = sectionRegex.exec(content);
  }

  const outputSection = sections.find((item) => /^(output)$/i.test(item.key));
  return {
    displayValue: outputSection && outputSection.value ? outputSection.value : "计算结果",
    sections
  };
}

function renderCalculateHtml(token) {
  const tooltipContent = token.sections.length
    ? token.sections.map((section) => {
        const label = mapCalcKey(section.key);
        const value = /^formula$/i.test(section.key)
          ? formatFormulaForTooltip(section.value)
          : escapeHtml(section.value || "");
        return `<b>${escapeHtml(label)}：</b>${value || "-"}`;
      }).join("<br>")
    : "无详细计算信息";

  return `<span class="custom-tooltip calc-style">${escapeHtml(token.displayValue)}<span class="tooltip-text">${tooltipContent}</span></span>`;
}

function parseClaimToken(attrsRaw, innerRaw) {
  let attrs = String(attrsRaw || "").trim();
  const innerContent = String(innerRaw || "");
  const supTextMatch = innerContent.match(/<sup[^>]*>([\s\S]*?)<\/sup>/i);
  const supTitleMatch = innerContent.match(/<sup[^>]*title="([^"]*)"[^>]*>/i);
  const displayContent = innerContent.replace(/<sup[^>]*>[\s\S]*?<\/sup>/gi, "").trim();
  const markText = supTextMatch ? supTextMatch[1].trim() : "";

  let statusClass = "claim-unknown";
  let statusMark = "";
  if (markText.includes("✓")) {
    statusClass = "claim-verified";
    statusMark = "✓";
  } else if (markText.includes("✗")) {
    statusClass = "claim-mismatch";
    statusMark = "✗";
  } else if (markText.includes("?")) {
    statusClass = "claim-pending";
    statusMark = "?";
  }

  if (supTitleMatch && !/\btitle=/.test(attrs)) {
    attrs = `${attrs} title="${supTitleMatch[1]}"`.trim();
  }

  const attrMatches = [...attrs.matchAll(/(\w+)="([^"]*)"/g)];
  return {
    attrs: attrMatches.map((m) => ({ key: m[1], value: m[2] })),
    displayContent: displayContent || innerContent,
    statusClass,
    statusMark
  };
}

function renderClaimHtml(token) {
  const claimMap = {
    id: "溯源编号",
    source_path: "源文件路径",
    path_to_value: "字段提取路径",
    policy: "匹配策略",
    title: "说明"
  };
  const tooltipContent = token.attrs.length
    ? token.attrs.map((item) => `<b>${escapeHtml(claimMap[item.key] || item.key)}：</b>${escapeHtml(item.value)}`).join("<br>")
    : "无详细溯源参数";
  const visibleClaim = `<span class="${token.statusClass}">${escapeHtml(token.displayContent)}</span><span class="claim-mark ${token.statusClass}">${escapeHtml(token.statusMark)}</span>`;
  return `<span class="custom-tooltip claim-style ${token.statusClass}">${visibleClaim}<span class="tooltip-text">${tooltipContent}</span></span>`;
}

function renderMarkdownLite(markdown) {
  const lines = (markdown || "").split("\n");
  const out = [];
  let inCode = false;
  let inList = false;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    if (/^\s{0,3}```/.test(line)) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      if (!inCode) {
        out.push("<pre><code>");
      } else {
        out.push("</code></pre>");
      }
      inCode = !inCode;
      continue;
    }

    if (inCode) {
      out.push(`${escapeHtml(line)}\n`);
      continue;
    }

    if (line.trim() === "$$") {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }

      const mathLines = [];
      let j = i + 1;
      while (j < lines.length && lines[j].trim() !== "$$") {
        mathLines.push(lines[j]);
        j += 1;
      }

      if (j < lines.length) {
        const expr = escapeHtml(mathLines.join("\n")).trim();
        out.push(`<div class="math-block">$$\n${expr}\n$$</div>`);
        i = j;
        continue;
      }
    }

    const stripped = line.trim();
    if (
      stripped &&
      !line.includes("$") &&
      stripped.includes("=") &&
      (stripped.includes("\\frac") || stripped.includes("\\times")) &&
      !/^(#|[-*]|\||\[\^fn)/.test(stripped)
    ) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      const expr = escapeHtml(stripped);
      out.push(`<div class="math-block">$$\n${expr}\n$$</div>`);
      continue;
    }

    if (isMarkdownTableStart(lines, i)) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      const { html, nextIndex } = renderMarkdownTable(lines, i);
      out.push(html);
      i = nextIndex;
      continue;
    }

    if (line.startsWith("### ")) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      out.push(`<h3>${formatInlineMarkdown(line.slice(4))}</h3>`);
      continue;
    }
    if (line.startsWith("#### ")) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      out.push(`<h4>${formatInlineMarkdown(line.slice(5))}</h4>`);
      continue;
    }
    if (line.startsWith("##### ")) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      out.push(`<h5>${formatInlineMarkdown(line.slice(6))}</h5>`);
      continue;
    }
    if (line.startsWith("###### ")) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      out.push(`<h6>${formatInlineMarkdown(line.slice(7))}</h6>`);
      continue;
    }
    if (line.startsWith("## ")) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      out.push(`<h2>${formatInlineMarkdown(line.slice(3))}</h2>`);
      continue;
    }
    if (line.startsWith("# ")) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      out.push(`<h1>${formatInlineMarkdown(line.slice(2))}</h1>`);
      continue;
    }
    if (/^\s*-\s+/.test(line)) {
      if (!inList) {
        out.push("<ul>");
        inList = true;
      }
      out.push(`<li>${formatInlineMarkdown(line.replace(/^\s*-\s+/, ""))}</li>`);
      continue;
    }

    if (!line.trim()) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      continue;
    }

    if (inList) {
      out.push("</ul>");
      inList = false;
    }

    if (looksLikeHtmlBlock(line)) {
      out.push(line);
      continue;
    }

    out.push(`<p>${formatInlineMarkdown(line)}</p>`);
  }

  if (inList) {
    out.push("</ul>");
  }
  if (inCode) {
    out.push("</code></pre>");
  }

  return out.join("\n");
}

function formatInlineMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function looksLikeHtmlBlock(line) {
  const t = line.trim();
  return /^<\/?(claim|calculate|table|thead|tbody|tr|th|td|sup|span|div|p|ul|ol|li|br)\b/i.test(t);
}

function renderMathInTooltips(container) {
  if (!container) {
    return;
  }

  const tooltipNodes = container.querySelectorAll(".tooltip-text");
  if (!tooltipNodes.length) {
    return;
  }

  if (typeof window.renderMathInElement === "function") {
    try {
      tooltipNodes.forEach((node) => {
        window.renderMathInElement(node, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false },
            { left: "\\(", right: "\\)", display: false },
            { left: "\\[", right: "\\]", display: true }
          ],
          throwOnError: false
        });
      });
    } catch (_err) {
      // Keep raw TeX text when KaTeX rendering fails.
    }
  }
}

function renderMathInMarkdown(container) {
  if (!container) {
    return;
  }

  if (typeof window.renderMathInElement === "function") {
    try {
      window.renderMathInElement(container, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
          { left: "\\[", right: "\\]", display: true }
        ],
        throwOnError: false,
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"]
      });
    } catch (_err) {
      // Keep raw TeX text when KaTeX rendering fails.
    }
  }
}

function isMarkdownTableStart(lines, index) {
  if (index + 1 >= lines.length) {
    return false;
  }
  const header = lines[index];
  const sep = lines[index + 1];
  if (!header.includes("|")) {
    return false;
  }
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(sep);
}

function splitTableRow(line) {
  const raw = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return raw.split("|").map((cell) => cell.trim());
}

function renderMarkdownTable(lines, startIndex) {
  const headerCells = splitTableRow(lines[startIndex]);
  const bodyRows = [];
  let i = startIndex + 2;

  while (i < lines.length) {
    const row = lines[i];
    if (!row.trim()) {
      break;
    }
    if (!row.includes("|")) {
      break;
    }
    if (/^\s*#/.test(row) || /^\s*-\s+/.test(row) || row.startsWith("```")) {
      break;
    }
    bodyRows.push(splitTableRow(row));
    i += 1;
  }

  const html = ["<table>", "<thead>", "<tr>"];
  headerCells.forEach((cell) => html.push(`<th>${formatInlineMarkdown(cell)}</th>`));
  html.push("</tr>", "</thead>", "<tbody>");

  bodyRows.forEach((cells) => {
    html.push("<tr>");
    cells.forEach((cell) => html.push(`<td>${formatInlineMarkdown(cell)}</td>`));
    html.push("</tr>");
  });

  html.push("</tbody>", "</table>");
  return { html: html.join(""), nextIndex: i - 1 };
}


window.__reportEditorBooted = true;
void safeBootstrap();
