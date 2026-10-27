const CONFIG = {
  apiBaseUrl: "",
  compareApiBaseUrl: "",
  reportBaseUrl: "./report.html",
  compareReportEditorUrl: "./report_editor.html",
  outputsIndexPath: "/outputs/",
  pollIntervalMs: 2000,
  requestTimeoutMs: 600000,  // 10分钟超时
  useMockBackend: true,
  useRealBackendForCompare: true,
  compareReportInputDir: "",
  maxLogItems: 40
};

const STAGES = [
  { key: "SUBMITTED", label: "任务已提交" },
  { key: "SIMULATING", label: "网架仿真中" },
  { key: "ANOMALY_DONE", label: "异常定位完成" },
  { key: "PLANNING", label: "规划方案生成中" },
  { key: "ENOUGH", label: "已生成满足数量方案" },
  { key: "COMPLETED", label: "任务完成" }
];

const STAGE_INDEX = STAGES.reduce((acc, item, idx) => {
  acc[item.key] = idx;
  return acc;
}, {});

const COMPARE_REPORT_STAGES = [
  { key: "DATA_PREPROCESSING", label: "数据预处理" },
  { key: "INSIGHTS_GENERATION", label: "洞察生成" },
  { key: "WAIT_INSIGHTS_CONFIRM", label: "洞察待确认" },
  { key: "RETRIEVE_CLAIMS", label: "检索洞察关联依据" },
  { key: "GENERATE_REPORT", label: "生成报告" },
  { key: "VERIFY_CLAIMS", label: "校验 PCN 依据" },
  { key: "DRAFT_READY", label: "初稿就绪" }
];

const COMPARE_STAGE_INDEX = COMPARE_REPORT_STAGES.reduce((acc, item, idx) => {
  acc[item.key] = idx;
  return acc;
}, {});
// PCN 失败时的终态与初稿就绪同进度位，但状态文案不同
COMPARE_STAGE_INDEX.DRAFT_REVIEW_REQUIRED = COMPARE_STAGE_INDEX.DRAFT_READY;

const state = {
  taskId: "",
  fileId: "",
  resultRoot: "",
  targetCount: 0,
  generatedCount: 0,
  currentStage: "",
  failed: false,
  anomaliesLoaded: false,
  anomalyLoading: false,
  logItems: [],
  anomalies: [],
  anomalyReports: [],
  schemes: [],
  compareReportId: "",
  compareReportStage: "",
  compareReportFailed: false,
  compareReportRunning: false,
  compareReportReady: false,
  comparePcnVerificationPassed: null,
  compareReportMessage: "",
  compareLogItems: [],
  compareReportPath: "",
  compareReportPaths: {},
  compareInsightsDraft: "",
  compareInsightsOriginal: "",
  compareInsightsEditing: false
};

const REPORT_ORDER = ["pf_report_1.json", "n1_report_1.json", "scc_report_1.json"];
const DEFAULT_SITE_ROLE = "load_substation";
const DEFAULT_RADIAL_CIRCUIT_COUNTS = ["1"];
const DEFAULT_SELECTED_WIRING_MODES = [
  "radial",
  "ring",
  "mesh",
  "pi",
  "back_to_back_dc",
  "dc_networking",
  "flexible_ac",
  "reinforcement"
];

const PROMPT_DEFAULT_FALLBACKS = {
  shuifu: {
    connectionMode: "",
    requirements:
      "每个方案都需要输出对应的JSON数据\n" +
      "    - 注意：格式需要仿照当前网架结构的JSON数据，并标注对应方案几\n" +
      "    - 每个方案都需要加入“滇水富51”节点的JSON数据，对应的数据卡类型是“B”，对应的有功负荷（LOAD_P）为0\n" +
      "    - 只需输出删除、修改和新增的部份。\n" +
      "    - 需要指明每个数据卡对应的操作是什么。\n" +
      "    - 注意！L卡中“MILES”字段需要正确反映完整线路（新建线路+保留线路）的长度。\n" +
      "    - 每生成一个方案的JSON数据，都需要完整详细的文字说明和经济性分析（建设成本和维护成本）。",
    formulas:
      "(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；\n" +
      "(2)电阻的计算方式：电阻=线路长度*0.000095*1.2；"
  },
  yuezhou: {
    connectionMode: "",
    requirements:
      "每个方案都需要输出对应的JSON数据\n" +
      "    - 注意：格式需要仿照当前网架结构的JSON数据，并标注对应方案几\n" +
      "    - 每个方案都需要加入“滇越州51”节点的JSON数据，对应的数据卡类型是“B”，对应的有功负荷（LOAD_P）为119\n" +
      "    - 只需输出删除、修改和新增的部份。\n" +
      "    - 需要指明每个数据卡对应的操作是什么。\n" +
      "    - 注意！L卡中“MILES”字段需要正确反映完整线路（新建线路+保留线路）的长度。\n" +
      "    - 每生成一个方案的JSON数据，都需要完整详细的文字说明和经济性分析（建设成本和维护成本）。",
    formulas:
      "(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；\n" +
      "(2)电阻的计算方式：电阻=线路长度*0.000095*1.2；"
  },
  generic: {
    connectionMode: "",
    requirements:
      "每个方案都需要输出对应的JSON数据\n" +
      "    - 注意：格式需要仿照当前网架结构的JSON数据，并标注对应方案几\n" +
      "    - 每个方案都需要加入“bus0”节点的JSON数据，对应的数据卡类型是“B”，对应的有功负荷（LOAD_P）为0\n" +
      "    - 只需输出删除、修改和新增的部份。\n" +
      "    - 需要指明每个数据卡对应的操作是什么。\n" +
      "    - 注意！L卡中“MILES”字段需要正确反映完整线路（新建线路+保留线路）的长度。\n" +
      "    - 每生成一个方案的JSON数据，都需要完整详细的文字说明和经济性分析（建设成本和维护成本）。",
    formulas:
      "(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；\n" +
      "(2)电阻的计算方式：电阻=线路长度*0.000095*1.2；"
  }
};

const dom = {
  taskForm: document.querySelector("#task-form"),
  fileInput: document.querySelector("#file-input"),
  countInput: document.querySelector("#count-input"),
  caseSelect: document.querySelector("#case-select"),
  transientAnalysisInput: document.querySelector("#transient-analysis-input"),
  siteRoleInputs: Array.from(document.querySelectorAll('input[name="site-role"]')),
  radialCircuitCountInputs: Array.from(document.querySelectorAll('input[name="radial-circuit-count"]')),
  wiringModeInputs: Array.from(document.querySelectorAll('input[name="wiring-mode"]')),
  wiringModeParentInputs: Array.from(document.querySelectorAll('input[name="wiring-mode-parent"]')),
  customWiringModeInput: document.querySelector("#custom-wiring-mode-input"),
  requirementsInput: document.querySelector("#requirements-input"),
  requirementsExtraInput: document.querySelector("#requirements-extra-input"),
  formulasInput: document.querySelector("#formulas-input"),
  submitBtn: document.querySelector("#submit-btn"),
  stageTrack: document.querySelector("#stage-track"),
  taskId: document.querySelector("#task-id"),
  currentStatus: document.querySelector("#current-status"),
  generatedCount: document.querySelector("#generated-count"),
  runtimeLog: document.querySelector("#runtime-log"),
  generateCompareReportBtn: document.querySelector("#generate-compare-report-btn"),
  openCompareReportBtn: document.querySelector("#open-compare-report-btn"),
  compareStageTrack: document.querySelector("#compare-stage-track"),
  compareReportId: document.querySelector("#compare-report-id"),
  compareReportStatus: document.querySelector("#compare-report-status"),
  compareSchemeCount: document.querySelector("#compare-scheme-count"),
  comparePcnReviewBanner: document.querySelector("#compare-pcn-review-banner"),
  compareRuntimeLog: document.querySelector("#compare-runtime-log"),
  compareInsightsPanel: document.querySelector("#compare-insights-panel"),
  compareInsightsText: document.querySelector("#compare-insights-text"),
  editInsightsBtn: document.querySelector("#edit-insights-btn"),
  resetInsightsBtn: document.querySelector("#reset-insights-btn"),
  confirmInsightsBtn: document.querySelector("#confirm-insights-btn"),
  bootIndicator: document.querySelector("#boot-indicator"),
  anomalyPlaceholder: document.querySelector("#anomaly-placeholder"),
  anomalyContent: document.querySelector("#anomaly-content"),
  resultPlaceholder: document.querySelector("#result-placeholder"),
  resultContent: document.querySelector("#result-content"),
  anomalyList: document.querySelector("#anomaly-list"),
  schemeList: document.querySelector("#scheme-list"),
  topologyModal: document.querySelector("#topology-modal"),
  topologyTitle: document.querySelector("#topology-title"),
  closeModal: document.querySelector("#close-modal"),
  zoomIn: document.querySelector("#zoom-in"),
  zoomOut: document.querySelector("#zoom-out"),
  resetView: document.querySelector("#reset-view"),
  nodeInfoText: document.querySelector("#node-info-text"),
  topologyCanvas: document.querySelector("#topology-canvas")
};

let pollTimer = null;
let pollInFlight = false;
let comparePollTimer = null;
let comparePollInFlight = false;
let topologyViewer = null;
let api = null;
let compareApi = null;
let compareRunToken = 0;

function getDefaultApiBaseUrl() {
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    if (window.location.port === "5173") {
      return "http://127.0.0.1:8080";
    }
    return window.location.origin;
  }
  return "http://127.0.0.1:8080";
}

function resolveBaseUrl(defaultUrl, queryKey) {
  const value = new URLSearchParams(window.location.search).get(queryKey);
  const resolved = value || defaultUrl;
  return resolved ? resolved.replace(/\/+$/, "") : "";
}

function init() {
  api = createApiClient();
  compareApi = createCompareApiClient();
  topologyViewer = new TopologyViewer(dom.topologyCanvas);
  renderStageTrack("", false, 0, 0);
  renderCompareReportStageTrack("", false);
  renderAnomalySection();
  syncTaskMeta();
  syncCompareReportMeta();
  syncCompareReportButtonState();
  syncCompareInsightsPanel();
  bindEvents();
  loadPromptDefaults(dom.caseSelect ? dom.caseSelect.value : "shuifu");
  setBootIndicator("ok", "前端脚本已加载");
  appendLog(api.mode === "mock" ? "当前运行模式：Mock 后端（可通过 ?mock=0 切换真实接口）。" : "当前运行模式：真实后端接口。");
  appendCompareLog(compareApi.mode === "mock" ? "比选报告当前运行模式：Mock 后端。" : "比选报告当前运行模式：真实后端接口。");
}

function bindEvents() {
  dom.taskForm.addEventListener("submit", onSubmitTask);
  if (dom.caseSelect) {
    dom.caseSelect.addEventListener("change", () => loadPromptDefaults(dom.caseSelect.value));
  }
  dom.wiringModeParentInputs.forEach((input) => {
    input.addEventListener("change", () => onWiringParentChange(input));
  });
  dom.wiringModeInputs.forEach((input) => {
    input.addEventListener("change", () => {
      syncWiringParentStates();
      syncRadialCircuitState();
    });
  });
  dom.radialCircuitCountInputs.forEach((input) => {
    input.addEventListener("change", syncRadialCircuitState);
  });
  dom.generateCompareReportBtn.addEventListener("click", onGenerateCompareReport);
  dom.openCompareReportBtn.addEventListener("click", onOpenCompareReport);
  dom.editInsightsBtn.addEventListener("click", onEditInsights);
  dom.resetInsightsBtn.addEventListener("click", onResetInsights);
  dom.confirmInsightsBtn.addEventListener("click", onConfirmInsights);
  dom.closeModal.addEventListener("click", closeTopologyModal);
  dom.topologyModal.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.close === "true") {
      closeTopologyModal();
    }
  });
  dom.zoomIn.addEventListener("click", () => topologyViewer.zoomBy(1.15));
  dom.zoomOut.addEventListener("click", () => topologyViewer.zoomBy(0.87));
  dom.resetView.addEventListener("click", () => topologyViewer.fitToView());
}

async function onSubmitTask(event) {
  event.preventDefault();
  let files = dom.fileInput && dom.fileInput.files ? Array.from(dom.fileInput.files) : [];
  const targetCount = Number(dom.countInput.value);
  const caseType = dom.caseSelect ? dom.caseSelect.value : "shuifu";
  const promptOverrides = getPromptOverrides();
  const enableTransientAnalysis = Boolean(dom.transientAnalysisInput && dom.transientAnalysisInput.checked);

  if (!files.length) {
    if (api && api.mode === "mock") {
      files = [new File(["mock demo payload"], "mock-demo.txt", { type: "text/plain" })];
      appendLog("未选择文件夹，Mock 模式自动使用内置演示文件。");
    } else {
      alert("请先选择原始文件夹。");
      return;
    }
  }
  if (!Number.isInteger(targetCount) || targetCount <= 0) {
    alert("目标方案数 n 需要是大于 0 的整数。");
    return;
  }

  resetTaskState(targetCount);
  setFormDisabled(true);
  appendLog("开始上传原始文件夹...");

  try {
    const uploadResult = await api.uploadFiles(files);
    state.fileId = uploadResult.fileId || uploadResult.id || "";
    const savedCount = Array.isArray(uploadResult.saved) ? uploadResult.saved.length : files.length;
    appendLog(`文件夹上传成功，已保存 ${savedCount} 个文件到 data_test，fileId=${state.fileId || "N/A"}`);
    if (!uploadResult.baseModelPath) {
      throw new Error("上传目录中未识别到 .dat 基础模型文件。");
    }

    const createResult = await api.createTask(uploadResult.baseModelPath, targetCount, caseType, promptOverrides, enableTransientAnalysis);
    state.taskId = createResult.taskId || createResult.id || "";
    state.resultRoot = createResult.resultRoot || "";
    state.currentStage = "SUBMITTED";
    appendLog(`任务创建成功，taskId=${state.taskId}，案例=${caseType}，暂态分析=${enableTransientAnalysis ? "启用" : "不启用"}`);
    syncTaskMeta();
    renderStageTrack(state.currentStage, false, state.generatedCount, state.targetCount);
    startPolling();
  } catch (error) {
    state.failed = true;
    appendLog(`任务启动失败：${readableError(error)}`);
    renderStageTrack("SUBMITTED", true, state.generatedCount, state.targetCount);
    syncTaskMeta();
    setFormDisabled(false);
  }
}

function resetTaskState(targetCount) {
  compareRunToken += 1;
  stopPolling();
  stopComparePolling();
  state.taskId = "";
  state.fileId = "";
  state.resultRoot = "";
  state.targetCount = targetCount;
  state.generatedCount = 0;
  state.currentStage = "";
  state.failed = false;
  state.anomaliesLoaded = false;
  state.anomalyLoading = false;
  state.logItems = [];
  state.anomalies = [];
  state.anomalyReports = [];
  state.schemes = [];
  state.compareReportId = "";
  state.compareReportStage = "";
  state.compareReportFailed = false;
  state.compareReportRunning = false;
  state.compareReportReady = false;
  state.compareLogItems = [];
  state.compareReportPath = "";
  state.compareReportPaths = {};
  state.compareInsightsDraft = "";
  state.compareInsightsOriginal = "";
  state.compareInsightsEditing = false;
  dom.runtimeLog.innerHTML = "";
  dom.compareRuntimeLog.innerHTML = "";
  dom.anomalyList.innerHTML = "";
  dom.schemeList.innerHTML = "";
  dom.resultPlaceholder.classList.remove("hidden");
  dom.resultContent.classList.add("hidden");
  dom.nodeInfoText.textContent = "绿色实线表示新增线路\n红色虚线表示删除线路";
  renderAnomalySection();
  syncTaskMeta();
  renderStageTrack("", false, 0, targetCount);
  renderCompareReportStageTrack("", false);
  syncCompareReportMeta();
  appendCompareLog("等待方案完成后可启动比选报告。");
  syncCompareInsightsPanel();
  syncCompareReportButtonState();
}

function setFormDisabled(disabled) {
  dom.fileInput.disabled = disabled;
  dom.countInput.disabled = disabled;
  if (dom.caseSelect) {
    dom.caseSelect.disabled = disabled;
  }
  if (dom.transientAnalysisInput) {
    dom.transientAnalysisInput.disabled = disabled;
  }
  dom.siteRoleInputs.forEach((input) => {
    input.disabled = disabled;
  });
  dom.radialCircuitCountInputs.forEach((input) => {
    input.disabled = disabled || !isRadialModeSelected();
  });
  dom.wiringModeInputs.forEach((input) => {
    input.disabled = disabled;
  });
  dom.wiringModeParentInputs.forEach((input) => {
    input.disabled = disabled;
  });
  if (dom.customWiringModeInput) {
    dom.customWiringModeInput.disabled = disabled;
  }
  if (dom.requirementsInput) {
    dom.requirementsInput.disabled = disabled;
  }
  if (dom.requirementsExtraInput) {
    dom.requirementsExtraInput.disabled = disabled;
  }
  if (dom.formulasInput) {
    dom.formulasInput.disabled = disabled;
  }
  dom.submitBtn.disabled = disabled;
  syncCompareReportButtonState();
}

async function loadPromptDefaults(caseType) {
  setPromptInputs(getFallbackPromptDefaults(caseType));
  if (!api || !api.getPromptDefaults) {
    return;
  }
  try {
    const defaults = await api.getPromptDefaults(caseType);
    setPromptInputs(defaults);
    appendLog(`已加载 ${caseType} 案例的 Prompt 默认内容。`);
  } catch (error) {
    appendLog(`Prompt 默认内容接口加载失败，已使用前端内置默认内容：${readableError(error)}`);
  }
}

function getFallbackPromptDefaults(caseType) {
  return PROMPT_DEFAULT_FALLBACKS[caseType] || PROMPT_DEFAULT_FALLBACKS.shuifu;
}

function setPromptInputs(defaults = {}) {
  setSiteRole(defaults.siteRole || DEFAULT_SITE_ROLE);
  setRadialCircuitCounts(defaults.radialCircuitCounts || DEFAULT_RADIAL_CIRCUIT_COUNTS);
  const selectedModes = Array.isArray(defaults.selectedWiringModes) && defaults.selectedWiringModes.length
    ? defaults.selectedWiringModes
    : DEFAULT_SELECTED_WIRING_MODES;
  setSelectedWiringModes(selectedModes);
  if (dom.customWiringModeInput) {
    dom.customWiringModeInput.value = defaults.customWiringMode || "";
  }
  if (dom.requirementsInput) {
    dom.requirementsInput.value = defaults.requirements || "";
  }
  if (dom.requirementsExtraInput) {
    dom.requirementsExtraInput.value = "";
  }
  if (dom.formulasInput) {
    dom.formulasInput.value = defaults.formulas || "";
  }
}

function setSiteRole(siteRole) {
  const value = siteRole || DEFAULT_SITE_ROLE;
  dom.siteRoleInputs.forEach((input) => {
    input.checked = input.value === value;
  });
}

function getSelectedSiteRole() {
  const selected = dom.siteRoleInputs.find((input) => input.checked);
  return selected ? selected.value : DEFAULT_SITE_ROLE;
}

function setRadialCircuitCounts(counts) {
  const selected = new Set((Array.isArray(counts) && counts.length ? counts : DEFAULT_RADIAL_CIRCUIT_COUNTS).map(String));
  dom.radialCircuitCountInputs.forEach((input) => {
    input.checked = selected.has(input.value);
  });
  syncRadialCircuitState();
}

function getSelectedRadialCircuitCounts() {
  return dom.radialCircuitCountInputs
    .filter((input) => input.checked)
    .map((input) => input.value);
}

function isRadialModeSelected() {
  return dom.wiringModeInputs.some((input) => input.value === "radial" && input.checked);
}

function syncRadialCircuitState() {
  const radialSelected = isRadialModeSelected();
  if (radialSelected && !dom.radialCircuitCountInputs.some((input) => input.checked)) {
    const fallback = dom.radialCircuitCountInputs.find((input) => input.value === DEFAULT_RADIAL_CIRCUIT_COUNTS[0]);
    if (fallback) {
      fallback.checked = true;
    }
  }
  dom.radialCircuitCountInputs.forEach((input) => {
    input.disabled = !radialSelected;
  });
}

function setSelectedWiringModes(selectedModes) {
  const selected = new Set(selectedModes);
  dom.wiringModeInputs.forEach((input) => {
    input.checked = selected.has(input.value);
  });
  syncWiringParentStates();
  syncRadialCircuitState();
}

function getSelectedWiringModes() {
  return dom.wiringModeInputs
    .filter((input) => input.checked)
    .map((input) => input.value);
}

function onWiringParentChange(parentInput) {
  const children = dom.wiringModeInputs.filter((input) => input.dataset.parent === parentInput.value);
  children.forEach((input) => {
    input.checked = parentInput.checked;
  });
  syncWiringParentStates();
}

function syncWiringParentStates() {
  dom.wiringModeParentInputs.forEach((parentInput) => {
    const children = dom.wiringModeInputs.filter((input) => input.dataset.parent === parentInput.value);
    const checkedCount = children.filter((input) => input.checked).length;
    parentInput.checked = children.length > 0 && checkedCount === children.length;
    parentInput.indeterminate = checkedCount > 0 && checkedCount < children.length;
  });
}

function getPromptOverrides() {
  return {
    siteRole: getSelectedSiteRole(),
    selectedWiringModes: getSelectedWiringModes(),
    radialCircuitCounts: getSelectedRadialCircuitCounts(),
    customWiringMode: dom.customWiringModeInput ? dom.customWiringModeInput.value.trim() : "",
    requirementsExtra: dom.requirementsExtraInput ? dom.requirementsExtraInput.value.trim() : "",
    formulas: dom.formulasInput ? dom.formulasInput.value.trim() : ""
  };
}

function startPolling() {
  stopPolling();
  tickTaskStatus();
  pollTimer = window.setInterval(tickTaskStatus, CONFIG.pollIntervalMs);
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function tickTaskStatus() {
  if (pollInFlight || !state.taskId) {
    return;
  }
  pollInFlight = true;

  try {
    const payload = await api.getTaskStatus(state.taskId);
    const normalized = normalizeStatus(payload, state.targetCount);
    state.currentStage = normalized.stage;
    state.generatedCount = normalized.generatedCount;
    state.failed = normalized.failed;
    state.resultRoot = payload.resultRoot || state.resultRoot;

    if (normalized.message) {
      appendLog(normalized.message);
    }

    syncTaskMeta();
    renderStageTrack(state.currentStage, state.failed, state.generatedCount, state.targetCount);
    renderAnomalySection();

    if (normalized.failed) {
      appendLog("任务失败，停止轮询。");
      stopPolling();
      setFormDisabled(false);
      return;
    }

    if (hasReachedStage(state.currentStage, "ANOMALY_DONE")) {
      await ensureAnomaliesLoaded();
    }

    const enoughSchemes = state.targetCount > 0 && normalized.generatedCount >= state.targetCount;
    if (normalized.completed || enoughSchemes) {
      stopPolling();
      if (!normalized.completed) {
        appendLog(`已达到目标方案数 ${state.targetCount}，按 Demo 规则结束任务。`);
      }
      state.currentStage = "COMPLETED";
      syncTaskMeta();
      renderStageTrack(state.currentStage, false, state.generatedCount, state.targetCount);
      appendLog("任务已完成，开始拉取异常与方案结果...");
      await fetchFinalResults();
      appendLog("结果加载完成，可查看拓扑图和报告入口。");
      setFormDisabled(false);
    }
  } catch (error) {
    appendLog(`轮询异常：${readableError(error)}`);
  } finally {
    pollInFlight = false;
  }
}

async function fetchFinalResults() {
  if (!state.anomaliesLoaded) {
    await ensureAnomaliesLoaded();
  }
  const schemePayload = await api.getSchemes(state.taskId, state.targetCount);
  state.schemes = normalizeSchemes(schemePayload).slice(0, state.targetCount);
  renderResults();
  syncCompareReportButtonState();
  syncCompareReportMeta();
}

function renderResults() {
  dom.resultPlaceholder.classList.add("hidden");
  dom.resultContent.classList.remove("hidden");

  dom.schemeList.innerHTML = "";
  if (!state.schemes.length) {
    const empty = document.createElement("p");
    empty.textContent = "暂无满足要求的方案。";
    dom.schemeList.appendChild(empty);
    return;
  }

  state.schemes.forEach((scheme, idx) => {
    const card = document.createElement("article");
    card.className = "scheme-card";

    const title = document.createElement("h4");
    title.className = "scheme-title";
    title.textContent = `方案 ${idx + 1}`;
    card.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "scheme-meta";
    const scoreText = scheme.score !== null && scheme.score !== undefined ? ` | 评分：${scheme.score}` : "";
    const iterationCountText =
      scheme.iterationCount !== null && scheme.iterationCount !== undefined ? ` | 迭代${scheme.iterationCount}次` : "";
    meta.textContent = `方案标识：${scheme.id}${iterationCountText}${scoreText}`;
    card.appendChild(meta);

    const desc = document.createElement("p");
    desc.className = "scheme-meta";
    desc.textContent = scheme.summary || "无方案说明。";
    card.appendChild(desc);

    const actions = document.createElement("div");
    actions.className = "scheme-actions";

    const topoBtn = document.createElement("button");
    topoBtn.type = "button";
    topoBtn.textContent = "查看拓扑图";
    topoBtn.addEventListener("click", () => openTopology(scheme));
    actions.appendChild(topoBtn);

    card.appendChild(actions);
    dom.schemeList.appendChild(card);
  });

  syncCompareReportButtonState();
  syncCompareReportMeta();
}

function canGenerateCompareReport() {
  const inCompareFlow = Boolean(state.compareReportId) && !state.compareReportReady && !state.compareReportFailed;
  const hasCompletedPlanningResult = Boolean(state.taskId) && Boolean(state.resultRoot) && state.schemes.length > 0;
  return (hasCompletedPlanningResult || isLocalCompareReportInputOverrideEnabled()) && !state.failed && !inCompareFlow;
}

function isLocalCompareReportInputOverrideEnabled() {
  const value = new URLSearchParams(window.location.search).get("reportInputOverride");
  return value === "1" || value === "true";
}

function syncCompareReportButtonState() {
  if (!dom.generateCompareReportBtn || !dom.openCompareReportBtn) {
    return;
  }
  const enabled = canGenerateCompareReport();
  dom.generateCompareReportBtn.disabled = !enabled;
  dom.openCompareReportBtn.disabled = !state.compareReportReady;
  if (state.compareReportStage === "WAIT_INSIGHTS_CONFIRM") {
    dom.generateCompareReportBtn.textContent = "等待洞察确认";
  } else if (state.compareReportRunning) {
    dom.generateCompareReportBtn.textContent = "比选报告生成中...";
  } else if (!canGenerateCompareReport()) {
    dom.generateCompareReportBtn.textContent = "等待规划任务完成";
  } else {
    dom.generateCompareReportBtn.textContent = "生成比选报告";
  }
}

async function onOpenCompareReport() {
  if (!state.compareReportReady) {
    return;
  }

  const btn = dom.openCompareReportBtn;
  const previousText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "定位报告中...";

  const reportPath = state.compareReportPath || (state.compareReportPaths && state.compareReportPaths.md) || "";
  if (!reportPath) {
    appendCompareLog("未找到可用报告路径，请等待任务完成后重试。");
    btn.textContent = previousText;
    syncCompareReportButtonState();
    return;
  }

  const url = buildCompareReportEditorUrl(reportPath);
  appendCompareLog(`已打开报告：${reportPath}`);
  window.open(url, "_blank", "noopener,noreferrer");

  btn.textContent = previousText;
  syncCompareReportButtonState();
}

function buildCompareReportEditorUrl(reportPath = "") {
  const url = new URL(CONFIG.compareReportEditorUrl, window.location.href);
  url.searchParams.set("editorV", "20260402_5");
  const currentQuery = new URLSearchParams(window.location.search);
  const mock = currentQuery.get("mock");
  if (state.taskId) {
    url.searchParams.set("taskId", state.taskId);
  }
  if (state.compareReportId) {
    url.searchParams.set("reportId", state.compareReportId);
  }
  if (reportPath) {
    url.searchParams.set("reportPath", reportPath);
  }
  if (mock !== null) {
    url.searchParams.set("mock", mock);
  }
  return url.toString();
}

function syncCompareReportMeta() {
  if (!dom.compareReportId || !dom.compareReportStatus || !dom.compareSchemeCount) {
    return;
  }
  dom.compareReportId.textContent = state.compareReportId || "-";
  dom.compareReportStatus.textContent = compareStageText(state.compareReportStage, state.compareReportFailed);
  dom.compareSchemeCount.textContent = String(state.schemes.length || 0);
  syncComparePcnReviewBanner();
}

function syncComparePcnReviewBanner() {
  const banner = dom.comparePcnReviewBanner;
  if (!banner) {
    return;
  }
  const needsReview =
    state.compareReportStage === "DRAFT_REVIEW_REQUIRED" ||
    (state.compareReportReady && state.comparePcnVerificationPassed === false);
  if (!needsReview) {
    banner.classList.add("hidden");
    banner.textContent = "";
    return;
  }
  banner.classList.remove("hidden");
  banner.textContent =
    "当前报告存在数值溯源问题，需要人工复核，不属于可直接交付版本。";
}

function compareStageText(stage, failed) {
  if (failed) {
    return "报告生成失败";
  }
  if (!stage) {
    return "等待方案生成完成";
  }
  if (stage === "DRAFT_REVIEW_REQUIRED") {
    return "待人工复核（PCN 核验未通过）";
  }
  const found = COMPARE_REPORT_STAGES.find((item) => item.key === stage);
  return found ? found.label : stage;
}

function renderCompareReportStageTrack(stage, failed) {
  renderGenericStageTrack(dom.compareStageTrack, COMPARE_REPORT_STAGES, COMPARE_STAGE_INDEX, stage, failed);
}

function renderGenericStageTrack(container, stages, stageIndexMap, stage, failed) {
  if (!container) {
    return;
  }
  const currentIndex = Object.prototype.hasOwnProperty.call(stageIndexMap, stage) ? stageIndexMap[stage] : -1;
  container.style.gridTemplateColumns = `repeat(${stages.length}, minmax(0, 1fr))`;
  container.innerHTML = "";

  stages.forEach((item, idx) => {
    const card = document.createElement("div");
    card.className = "stage";
    if (failed && idx === currentIndex) {
      card.classList.add("failed");
    } else if (idx < currentIndex) {
      card.classList.add("done");
    } else if (idx === currentIndex) {
      card.classList.add("active");
    }
    card.innerHTML = `<div class="dot"></div><p>${item.label}</p>`;
    container.appendChild(card);
  });
}

function appendCompareLog(message) {
  if (!dom.compareRuntimeLog) {
    return;
  }
  const now = new Date();
  const stamp = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
  const line = `${stamp} ${message}`;
  const last = state.compareLogItems[state.compareLogItems.length - 1];
  if (line === last) {
    return;
  }

  state.compareLogItems.push(line);
  if (state.compareLogItems.length > CONFIG.maxLogItems) {
    state.compareLogItems.shift();
  }

  dom.compareRuntimeLog.innerHTML = "";
  state.compareLogItems.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    dom.compareRuntimeLog.appendChild(li);
  });
  dom.compareRuntimeLog.scrollTop = dom.compareRuntimeLog.scrollHeight;
}

async function onGenerateCompareReport() {
  if (!canGenerateCompareReport()) {
    return;
  }

  const myToken = ++compareRunToken;
  stopComparePolling();
  state.compareReportRunning = true;
  state.compareReportFailed = false;
  state.compareReportReady = false;
  state.compareReportId = "";
  state.compareReportStage = "DATA_PREPROCESSING";
  state.compareLogItems = [];
  state.compareReportPath = "";
  state.compareReportPaths = {};
  state.compareInsightsDraft = "";
  state.compareInsightsOriginal = "";
  state.compareInsightsEditing = false;

  renderCompareReportStageTrack(state.compareReportStage, false);
  syncCompareReportMeta();
  syncCompareInsightsPanel();
  syncCompareReportButtonState();
  appendCompareLog("开始调用后端：创建比选报告任务。");

  try {
    const useReportOverride = isLocalCompareReportInputOverrideEnabled();
    const reportInputDir = CONFIG.compareReportInputDir || "";

    const payload = await compareApi.createCompareReport({
      taskId: useReportOverride ? "" : state.taskId,
      inputDir: useReportOverride ? reportInputDir : state.resultRoot,
      useReportInputOverride: useReportOverride,
      outputDir: "outputs"
    });

    if (myToken !== compareRunToken) {
      return;
    }

    state.compareReportId = payload.reportId || "";
    state.compareReportStage = payload.stage || "DATA_PREPROCESSING";
    appendCompareLog(payload.message || "比选任务已创建，等待后端执行。");
    syncCompareReportMeta();
    renderCompareReportStageTrack(state.compareReportStage, false);
    startComparePolling(myToken);
  } catch (error) {
    state.compareReportFailed = true;
    appendCompareLog(`比选报告生成失败：${readableError(error)}`);
    renderCompareReportStageTrack(state.compareReportStage, true);
  } finally {
    if (myToken === compareRunToken && state.compareReportFailed) {
      state.compareReportRunning = false;
      syncCompareReportMeta();
      syncCompareReportButtonState();
      syncCompareInsightsPanel();
    }
  }
}

function startComparePolling(runToken) {
  stopComparePolling();
  tickCompareStatus(runToken);
  comparePollTimer = window.setInterval(() => tickCompareStatus(runToken), CONFIG.pollIntervalMs);
}

function stopComparePolling() {
  if (comparePollTimer) {
    window.clearInterval(comparePollTimer);
    comparePollTimer = null;
  }
}

async function tickCompareStatus(runToken) {
  if (runToken !== compareRunToken || !state.compareReportId || comparePollInFlight) {
    return;
  }

  comparePollInFlight = true;
  try {
    const payload = await compareApi.getCompareReportStatus(state.compareReportId);
    if (runToken !== compareRunToken) {
      return;
    }

    state.compareReportStage = payload.stage || state.compareReportStage;
    state.compareReportFailed = Boolean(payload.failed);
    state.compareReportReady = Boolean(payload.ready);
    state.compareReportPath = payload.reportPath || state.compareReportPath;
    state.compareReportPaths = payload.reportPaths || state.compareReportPaths;
    if (Object.prototype.hasOwnProperty.call(payload, "pcnVerificationPassed")) {
      state.comparePcnVerificationPassed = payload.pcnVerificationPassed;
    }
    if (payload.message) {
      state.compareReportMessage = payload.message;
      appendCompareLog(payload.message);
    }

    if (state.compareReportStage === "WAIT_INSIGHTS_CONFIRM") {
      if (!state.compareInsightsOriginal) {
        const text = payload.currentInsights || "";
        state.compareInsightsOriginal = text;
        state.compareInsightsDraft = text;
        appendCompareLog("洞察已生成，请点击“编辑洞察”修改后确认继续。");
      }
      state.compareReportRunning = false;
      stopComparePolling();
    }

    if (state.compareReportReady) {
      stopComparePolling();
      state.compareReportRunning = false;
      appendCompareLog("比选报告已完成，可点击“查看报告”。");
      appendLog(`比选报告已完成，reportId=${state.compareReportId}`);
    }

    if (state.compareReportFailed) {
      stopComparePolling();
      state.compareReportRunning = false;
      appendCompareLog("后端执行失败，请检查日志并重试。");
    }

    renderCompareReportStageTrack(state.compareReportStage, state.compareReportFailed);
    syncCompareReportMeta();
    syncCompareReportButtonState();
    syncCompareInsightsPanel();
  } catch (error) {
    appendCompareLog(`查询比选状态失败：${readableError(error)}`);
  } finally {
    comparePollInFlight = false;
  }
}

function onEditInsights() {
  if (state.compareReportStage !== "WAIT_INSIGHTS_CONFIRM") {
    return;
  }
  state.compareInsightsEditing = true;
  syncCompareInsightsPanel();
  dom.compareInsightsText.focus();
}

function onResetInsights() {
  state.compareInsightsDraft = state.compareInsightsOriginal;
  dom.compareInsightsText.value = state.compareInsightsDraft;
}

async function onConfirmInsights() {
  if (state.compareReportStage !== "WAIT_INSIGHTS_CONFIRM" || !state.compareReportId) {
    return;
  }

  const text = (dom.compareInsightsText.value || "").trim();
  if (!text) {
    alert("洞察内容不能为空。");
    return;
  }

  state.compareInsightsDraft = text;
  state.compareReportRunning = true;
  syncCompareReportButtonState();
  appendCompareLog("正在提交确认后的洞察，后续流程即将继续...");

  try {
    const payload = await compareApi.confirmCompareReportInsights(state.compareReportId, text);
    state.compareReportStage = payload.stage || "RETRIEVE_CLAIMS";
    state.compareInsightsEditing = false;
    appendCompareLog(payload.message || "洞察确认成功，开始执行后续步骤。");
    renderCompareReportStageTrack(state.compareReportStage, false);
    syncCompareReportMeta();
    syncCompareInsightsPanel();
    startComparePolling(compareRunToken);
  } catch (error) {
    state.compareReportRunning = false;
    appendCompareLog(`洞察确认失败：${readableError(error)}`);
    syncCompareReportButtonState();
  }
}

function syncCompareInsightsPanel() {
  if (!dom.compareInsightsPanel || !dom.compareInsightsText) {
    return;
  }

  const visible = state.compareReportStage === "WAIT_INSIGHTS_CONFIRM";
  dom.compareInsightsPanel.classList.toggle("hidden", !visible);
  if (!visible) {
    return;
  }

  dom.compareInsightsText.value = state.compareInsightsDraft || state.compareInsightsOriginal || "";
  dom.compareInsightsText.readOnly = !state.compareInsightsEditing;
  dom.editInsightsBtn.disabled = state.compareInsightsEditing;
  dom.resetInsightsBtn.disabled = state.compareReportRunning;
  dom.confirmInsightsBtn.disabled = state.compareReportRunning;
}

async function ensureAnomaliesLoaded() {
  if (state.anomaliesLoaded || state.anomalyLoading || !state.taskId || state.failed) {
    return;
  }

  state.anomalyLoading = true;
  renderAnomalySection();
  appendLog("异常定位完成，开始拉取故障报告...");

  try {
    const anomalyPayload = await api.getAnomalies(state.taskId);
    state.anomalies = normalizeAnomalies(anomalyPayload);
    state.anomalyReports = normalizeAnomalyReports(anomalyPayload);
    state.anomaliesLoaded = true;
    appendLog(`故障报告已就绪，识别异常 ${state.anomalies.length} 条，并加载 3 份分析报告。`);
  } catch (error) {
    appendLog(`故障报告加载失败：${readableError(error)}`);
  } finally {
    state.anomalyLoading = false;
    renderAnomalySection();
  }
}

function renderAnomalySection() {
  if (!dom.anomalyPlaceholder || !dom.anomalyContent || !dom.anomalyList) {
    return;
  }

  if (!state.anomaliesLoaded) {
    dom.anomalyPlaceholder.classList.remove("hidden");
    dom.anomalyContent.classList.add("hidden");
    if (!state.taskId) {
      dom.anomalyPlaceholder.textContent = "原始文件提交后，完成异常定位即可在此查看故障报告。";
    } else if (state.anomalyLoading) {
      dom.anomalyPlaceholder.textContent = "异常定位已完成，正在生成故障报告...";
    } else if (hasReachedStage(state.currentStage, "ANOMALY_DONE")) {
      dom.anomalyPlaceholder.textContent = "故障报告即将就绪，请稍候...";
    } else {
      dom.anomalyPlaceholder.textContent = "网架仿真与异常定位进行中，完成后将在此展示故障报告。";
    }
    return;
  }

  dom.anomalyPlaceholder.classList.add("hidden");
  dom.anomalyContent.classList.remove("hidden");
  dom.anomalyList.innerHTML = "";

  if (!state.anomalies.length) {
    const li = document.createElement("li");
    li.textContent = "未识别到异常。";
    dom.anomalyList.appendChild(li);
    return;
  }

  if (state.anomalyReports.length) {
    state.anomalyReports.forEach((report) => {
      const li = document.createElement("li");
      li.className = "anomaly-report-item";

      const title = document.createElement("h3");
      title.textContent = report.title;
      li.appendChild(title);

      const meta = document.createElement("p");
      meta.textContent = report.summary;
      li.appendChild(meta);

      const details = buildAnomalyNarrative(report.fileName, report.content);
      details.forEach((line) => {
        const paragraph = document.createElement("p");
        paragraph.textContent = line;
        li.appendChild(paragraph);
      });

      dom.anomalyList.appendChild(li);
    });
    return;
  }

  state.anomalies.forEach((item, index) => {
    const li = document.createElement("li");
    const sev = item.severity ? `[${item.severity}] ` : "";
    li.textContent = `${index + 1}. ${sev}${item.title}（${item.location}）`;
    dom.anomalyList.appendChild(li);
  });
}

async function openTopology(scheme) {
  try {
    appendLog(`加载拓扑图：${scheme.id}`);
    const topologyPayload = await api.getTopology(state.taskId, scheme.id);
    const topology = normalizeTopology(topologyPayload);
    dom.topologyTitle.textContent = `方案拓扑图 - ${scheme.id}`;
    dom.nodeInfoText.textContent = "绿色实线表示新增线路\n红色虚线表示删除线路";
    dom.topologyModal.classList.remove("hidden");
    dom.topologyModal.setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(() => {
      topologyViewer.resize();
      topologyViewer.setData(topology);
    });
  } catch (error) {
    appendLog(`拓扑图加载失败：${readableError(error)}`);
    alert("拓扑图加载失败，请检查后端接口。");
  }
}

function closeTopologyModal() {
  dom.topologyModal.classList.add("hidden");
  dom.topologyModal.setAttribute("aria-hidden", "true");
}

function renderStageTrack(stage, failed, generatedCount, targetCount) {
  const visualStage = getVisualStage(stage, generatedCount, targetCount);
  const currentIndex = Object.prototype.hasOwnProperty.call(STAGE_INDEX, visualStage) ? STAGE_INDEX[visualStage] : -1;
  dom.stageTrack.innerHTML = "";

  STAGES.forEach((item, idx) => {
    const card = document.createElement("div");
    card.className = "stage";
    if (failed && idx === currentIndex) {
      card.classList.add("failed");
    } else if (idx < currentIndex) {
      card.classList.add("done");
    } else if (idx === currentIndex) {
      card.classList.add("active");
    }
    card.innerHTML = `<div class="dot"></div><p>${item.label}</p>`;
    dom.stageTrack.appendChild(card);
  });
}

function getVisualStage(stage, generatedCount, targetCount) {
  if (!stage) {
    return "";
  }
  if (stage === "COMPLETED") {
    return "COMPLETED";
  }
  if (generatedCount >= targetCount && targetCount > 0) {
    return "ENOUGH";
  }
  return stage;
}

function hasReachedStage(currentStage, targetStage) {
  if (!currentStage || !targetStage) {
    return false;
  }
  const currentIdx = STAGE_INDEX[currentStage];
  const targetIdx = STAGE_INDEX[targetStage];
  if (currentIdx === undefined || targetIdx === undefined) {
    return false;
  }
  return currentIdx >= targetIdx;
}

function syncTaskMeta() {
  dom.taskId.textContent = state.taskId || "-";
  dom.currentStatus.textContent = stageText(state.currentStage, state.failed);
  dom.generatedCount.textContent = `${state.generatedCount} / ${state.targetCount || 0}`;
}

function stageText(stage, failed) {
  if (failed) {
    return "任务失败";
  }
  if (!stage) {
    return "未开始";
  }
  const found = STAGES.find((item) => item.key === stage);
  return found ? found.label : stage;
}

function appendLog(message) {
  const now = new Date();
  const stamp = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
  const line = `${stamp} ${message}`;
  const last = state.logItems[state.logItems.length - 1];
  if (line === last) {
    return;
  }

  state.logItems.push(line);
  if (state.logItems.length > CONFIG.maxLogItems) {
    state.logItems.shift();
  }
  dom.runtimeLog.innerHTML = "";
  state.logItems.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    dom.runtimeLog.appendChild(li);
  });
  dom.runtimeLog.scrollTop = dom.runtimeLog.scrollHeight;
}

function normalizeStatus(payload, defaultTarget) {
  const raw = String(
    payload.status ||
      (payload.progress && payload.progress.stage) ||
      payload.stage ||
      payload.taskStatus ||
      "SUBMITTED"
  ).toUpperCase();
  let stage = "SUBMITTED";

  if (raw.includes("FAIL") || raw.includes("ERROR")) {
    stage = "SUBMITTED";
  } else if (raw.includes("SIM")) {
    stage = "SIMULATING";
  } else if (raw.includes("ANOMALY") || raw.includes("LOCAT")) {
    stage = "ANOMALY_DONE";
  } else if (raw.includes("PLAN") || raw.includes("GENERAT") || raw.includes("ITERAT")) {
    stage = "PLANNING";
  } else if (raw.includes("DONE") || raw.includes("COMPLETE") || raw.includes("SUCCESS")) {
    stage = "COMPLETED";
  }

  const generatedValue =
    payload.generatedSchemeCount !== undefined
      ? payload.generatedSchemeCount
      : payload.generatedCount !== undefined
        ? payload.generatedCount
        : payload.schemeCount !== undefined
          ? payload.schemeCount
          : payload.availableSchemes;
  const targetValue = payload.targetSchemeCount !== undefined ? payload.targetSchemeCount : payload.targetCount;
  const generatedCount = toNumber(generatedValue, 0);
  const targetCount = toNumber(targetValue, defaultTarget);
  const message = payload.message || payload.progressMessage || payload.detail || "";
  const failed = raw.includes("FAIL") || raw.includes("ERROR");
  const completed = stage === "COMPLETED";

  return {
    stage,
    generatedCount,
    targetCount,
    message: String(message || ""),
    failed,
    completed
  };
}

function normalizeAnomalies(payload) {
  const list = payload.items || payload.data || payload.anomalies || [];
  if (!Array.isArray(list)) {
    return [];
  }
  return list.map((item, idx) => ({
    title: item.title || item.name || item.message || `异常-${idx + 1}`,
    location: item.location || item.line || item.station || "未知位置",
    severity: item.severity || item.level || ""
  }));
}

function normalizeSchemes(payload) {
  const list = payload.items || payload.data || payload.schemes || [];
  if (!Array.isArray(list)) {
    return [];
  }
  return list.map((item, idx) => ({
    id: String(item.schemeId || item.id || item.code || `SCHEME-${idx + 1}`),
    name: item.name || `候选方案 ${idx + 1}`,
    summary: item.summary || item.description || "",
    score: item.score !== undefined && item.score !== null ? item.score : item.rankScore !== undefined ? item.rankScore : null,
    iteration: item.iteration !== undefined ? item.iteration : null,
    schemeNumber: item.schemeNumber !== undefined ? item.schemeNumber : null,
    runNumber: item.runNumber !== undefined ? item.runNumber : null,
    iterationCount: item.iterationCount !== undefined ? item.iterationCount : null
  }));
}

function normalizeAnomalyReports(payload) {
  const reports = payload.reports || {};
  const files = payload.files || [];
  const fileMap = files.reduce((acc, item) => {
    acc[item.name] = item;
    return acc;
  }, {});

  return Object.entries(reports).map(([fileName, content]) => ({
    fileName,
    title: fileMap[fileName] && fileMap[fileName].title ? fileMap[fileName].title : fileName,
    summary: buildAnomalyReportSummary(fileName, content),
    content
  })).sort((a, b) => {
    const aIndex = REPORT_ORDER.indexOf(a.fileName);
    const bIndex = REPORT_ORDER.indexOf(b.fileName);
    return (aIndex === -1 ? Number.MAX_SAFE_INTEGER : aIndex) - (bIndex === -1 ? Number.MAX_SAFE_INTEGER : bIndex);
  });
}

function buildAnomalyReportSummary(fileName, content) {
  if (fileName === "pf_report_1.json") {
    const analysis = content.analysis || {};
    const overloadedCount = Array.isArray(analysis.overloaded_lines) ? analysis.overloaded_lines.length : 0;
    return `潮流计算${analysis.is_convergent ? "已收敛" : "未收敛"}，过载线路 ${overloadedCount} 条。`;
  }
  if (fileName === "n1_report_1.json") {
    const count = Array.isArray(content.contingencies_with_issues) ? content.contingencies_with_issues.length : 0;
    return `共执行 ${content.total_contingencies_run || 0} 个故障场景，发现异常 ${count} 个。`;
  }
  if (fileName === "scc_report_1.json") {
    const analysis = content.analysis || {};
    const count = Array.isArray(analysis.contingencies_with_issues) ? analysis.contingencies_with_issues.length : 0;
    return `短路分析母线 ${analysis.total_buses || 0} 个，超限 ${count} 个，阈值 ${analysis.threshold_kA || "-"} kA。`;
  }
  return "分析报告内容如下。";
}

function buildAnomalyNarrative(fileName, content) {
  if (fileName === "pf_report_1.json") {
    return buildPowerFlowNarrative(content);
  }
  if (fileName === "n1_report_1.json") {
    return buildN1Narrative(content);
  }
  if (fileName === "scc_report_1.json") {
    return buildSccNarrative(content);
  }
  return ["报告已生成。"];
}

function buildPowerFlowNarrative(content) {
  const analysis = content.analysis || {};
  const overloadedLines = Array.isArray(analysis.overloaded_lines) ? analysis.overloaded_lines : [];
  const balanceSummary = Array.isArray(analysis.balance_summary) ? analysis.balance_summary : [];
  const lines = [];

  lines.push(
    analysis.is_convergent
      ? `本次潮流仿真基于 ${content.input_dat || "基础模型"} 完成计算，结果显示系统已经收敛。`
      : `本次潮流仿真基于 ${content.input_dat || "基础模型"} 完成计算，结果显示系统暂未收敛。`
  );

  lines.push(
    overloadedLines.length
      ? `共识别到 ${overloadedLines.length} 条过载线路，建议结合后续规划方案重点治理这些断面。`
      : "当前潮流结果中未发现过载线路，说明基础潮流分布整体稳定。"
  );

  if (balanceSummary.length) {
    const first = balanceSummary[0];
    lines.push(`系统平衡主要由 ${first.平衡机 || "未知平衡机"} 承担，当前实际功率约为 ${first.实际功率 || "-"}。`);
  }

  return lines;
}

function buildN1Narrative(content) {
  const issues = Array.isArray(content.contingencies_with_issues) ? content.contingencies_with_issues : [];
  const lines = [];
  const threshold = extractN1Threshold(issues);

  lines.push(
    `本次 N-1 校核共执行 ${content.total_contingencies_run || 0} 个故障场景，`
    + `按 ${threshold}% 的线路负载阈值进行判定，最终发现 ${issues.length} 个存在问题的场景。`
  );

  if (!issues.length) {
    lines.push("所有已校核场景均未发现明显越限问题，当前 N-1 表现较好。");
    return lines;
  }

  if (content.remaining_issues !== undefined) {
    lines.push(`综合统计后，当前仍有 ${content.remaining_issues} 个 N-1 问题需要在后续方案中继续消减。`);
  }

  issues.forEach((item, issueIndex) => {
    const overloaded = ((((item.result || {}).analysis || {}).overloaded_lines) || []);
    lines.push(`场景 ${issueIndex + 1}：${item.contingency_branch_uid || "未知断面"}。`);
    if (!overloaded.length) {
      lines.push("该场景未返回具体过载线路明细。");
      return;
    }
    overloaded.forEach((line, lineIndex) => {
      lines.push(
        `过载线路 ${lineIndex + 1}：${line["线路端点1"] || "未知端点"} - ${line["线路端点2"] || "未知端点"}，`
        + `${line["问题描述"] || "存在过载"}；电流 ${line["电流(A)"] || "-"} A，`
        + `额定电流 ${line["额定电流(A)"] || "-"} A，电流比例 ${line["电流比例(%)"] || "-"}%；`
        + `视在功率 ${line["视在功率(MVA)"] || "-"} MVA，额定视在功率 ${line["额定视在功率(MVA)"] || "-"} MVA，`
        + `视在功率比例 ${line["视在功率比例(%)"] || "-"}%；功率因数 ${line["功率因数"] || "-"}，`
        + `角度 ${line["角度(度)"] || "-"} 度。`
      );
    });
  });

  return lines;
}

function buildSccNarrative(content) {
  const analysis = content.analysis || {};
  const issues = Array.isArray(analysis.contingencies_with_issues) ? analysis.contingencies_with_issues : [];
  const lines = [];

  lines.push(
    `本次短路电流分析共检查 ${analysis.total_buses || 0} 个母线，判定阈值为 ${analysis.threshold_kA || "-"} kA，识别出 ${issues.length} 个超限点。`
  );

  if (!issues.length) {
    lines.push("当前短路电流水平整体处于可接受范围内，未发现需要重点处理的超限母线。");
    return lines;
  }

  issues.forEach((item, index) => {
    lines.push(
      `节点 ${index + 1}：${item.bus_name || "未知母线"}，电压等级 ${item.voltage_kV || "-"} kV，`
      + `类型 ${item.bus_type || "-"}，故障类型 ${item.fault_type || "-"}；`
      + `开断电流 ${item.breaker_current_kA || "-"} kA，短路电流 ${item.short_circuit_current_kA || "-"} kA，`
      + `短路容量 ${item.short_circuit_capacity_MVA || "-"} MVA；`
      + `r1=${item.r1 || "-"}，x1=${item.x1 || "-"}，r2=${item.r2 || "-"}，x2=${item.x2 || "-"}，`
      + `r0=${item.r0 || "-"}，x0=${item.x0 || "-"}，分区 ${item.partition || "-"}。`
    );
  });

  return lines;
}

function extractN1Threshold(issues) {
  for (const item of issues) {
    const overloaded = ((((item.result || {}).analysis || {}).overloaded_lines) || []);
    for (const line of overloaded) {
      const description = String(line["问题描述"] || "");
      const match = description.match(/额定值(\d+(?:\.\d+)?)%/);
      if (match) {
        return match[1];
      }
    }
  }
  return "80.0";
}

function normalizeTopology(payload) {
  const data = payload && payload.data ? payload.data : {};
  const nodes = payload.nodes || payload.vertexes || data.nodes || [];
  const edges = payload.edges || payload.links || data.edges || [];
  return {
    nodes: Array.isArray(nodes) ? nodes : [],
    edges: Array.isArray(edges) ? edges : []
  };
}

function toNumber(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function readableError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function setBootIndicator(type, text) {
  if (!dom.bootIndicator) {
    return;
  }
  dom.bootIndicator.textContent = text;
  dom.bootIndicator.classList.remove("ok", "error");
  if (type === "ok") {
    dom.bootIndicator.classList.add("ok");
  }
  if (type === "error") {
    dom.bootIndicator.classList.add("error");
  }
}

window.addEventListener("error", (event) => {
  const message = event && event.message ? event.message : "未知脚本错误";
  setBootIndicator("error", `脚本异常：${message}`);
});

function createApiClient() {
  const query = new URLSearchParams(window.location.search);
  const mockOverride = query.get("mock");
  const useMock = mockOverride === null ? CONFIG.useMockBackend : mockOverride !== "0";
  if (useMock) {
    return new MockApiClient();
  }
  return new RealApiClient(resolveBaseUrl(CONFIG.apiBaseUrl || getDefaultApiBaseUrl(), "apiBaseUrl"));
}

function createCompareApiClient() {
  const query = new URLSearchParams(window.location.search);
  const compareRealOverride = query.get("compareReal");
  const useReal = compareRealOverride === null ? CONFIG.useRealBackendForCompare : compareRealOverride !== "0";
  if (useReal) {
    return new RealApiClient(resolveBaseUrl(CONFIG.compareApiBaseUrl || getDefaultApiBaseUrl(), "compareApiBaseUrl"));
  }
  return new MockApiClient();
}

class RealApiClient {
  constructor(baseUrl) {
    this.mode = "real";
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  async uploadFiles(files) {
    const form = new FormData();
    files.forEach((file) => {
      form.append("file", file);
      form.append("relativePath", file.webkitRelativePath || file.name);
    });
    return this.request("/api/files/upload", {
      method: "POST",
      body: form
    });
  }

  async getPromptDefaults(caseType = "shuifu") {
    const params = new URLSearchParams({ caseType });
    return this.request(`/api/prompt-defaults?${params.toString()}`);
  }

  async createTask(baseModelPath, targetCount, caseType = "shuifu", promptOverrides = {}, enableTransientAnalysis = false) {
    return this.request("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        baseModelPath,
        targetSchemeCount: targetCount,
        caseType,
        enableTransientAnalysis,
        promptOverrides,
        siteRole: promptOverrides.siteRole || DEFAULT_SITE_ROLE,
        selectedWiringModes: promptOverrides.selectedWiringModes || [],
        radialCircuitCounts: promptOverrides.radialCircuitCounts || DEFAULT_RADIAL_CIRCUIT_COUNTS,
        customWiringMode: promptOverrides.customWiringMode || "",
        requirementsExtra: promptOverrides.requirementsExtra || "",
        formulas: promptOverrides.formulas || ""
      }),
      headers: { "Content-Type": "application/json" }
    });
  }

  async getTaskStatus(taskId) {
    return this.request(`/api/tasks/${encodeURIComponent(taskId)}/status`);
  }

  async getAnomalies(taskId) {
    return this.request(`/api/tasks/${encodeURIComponent(taskId)}/anomalies`);
  }

  async getSchemes(taskId, limit) {
    const params = new URLSearchParams({ limit: String(limit) });
    return this.request(`/api/tasks/${encodeURIComponent(taskId)}/schemes?${params.toString()}`);
  }

  async getTopology(taskId, schemeId) {
    return this.request(
      `/api/tasks/${encodeURIComponent(taskId)}/schemes/${encodeURIComponent(schemeId)}/topology`
    );
  }

  async getScheme(taskId, schemeId) {
    return this.request(`/api/tasks/${encodeURIComponent(taskId)}/schemes/${encodeURIComponent(schemeId)}`);
  }

  async createCompareReport(payload) {
    return this.request("/api/compare-reports", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" }
    });
  }

  async getCompareReportStatus(reportId) {
    return this.request(`/api/compare-reports/${encodeURIComponent(reportId)}`);
  }

  async confirmCompareReportInsights(reportId, insights) {
    return this.request(`/api/compare-reports/${encodeURIComponent(reportId)}/insights/confirm`, {
      method: "POST",
      body: JSON.stringify({ insights }),
      headers: { "Content-Type": "application/json" }
    });
  }

  async request(path, options = {}) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), CONFIG.requestTimeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        signal: controller.signal
      });
      const type = response.headers.get("content-type") || "";
      if (!response.ok) {
        let detail = "";
        try {
          if (type.includes("application/json")) {
            const payload = await response.json();
            detail = payload.detail || payload.error || payload.message || "";
          } else {
            detail = await response.text();
          }
        } catch (parseError) {
          detail = "";
        }
        const suffix = detail ? "：" + detail : "";
        throw new Error("HTTP " + response.status + " " + response.statusText + suffix);
      }
      if (type.includes("application/json")) {
        return response.json();
      }
      return {};
    } finally {
      window.clearTimeout(timeoutId);
    }
  }
}

class MockApiClient {
  constructor() {
    this.mode = "mock";
    this.tasks = new Map();
    this.compareReports = new Map();
  }

  async uploadFiles(files) {
    await sleep(500);
    const mockBaseModelPath = `/mock/data_test/${files[0]?.name || "mock-demo.dat"}`;
    return {
      fileId: `file_${Date.now()}`,
      saved: files.map((file) => file.webkitRelativePath || file.name),
      baseModelPath: mockBaseModelPath
    };
  }

  async getPromptDefaults(caseType = "shuifu") {
    await sleep(120);
    return getFallbackPromptDefaults(caseType);
  }

  async createTask(baseModelPath, targetCount, caseType = "shuifu", promptOverrides = {}, enableTransientAnalysis = false) {
    await sleep(400);
    const taskId = `task_${Date.now()}`;
    const anomalies = createMockAnomalies();
    const schemes = createMockSchemes(targetCount);
    this.tasks.set(taskId, {
      baseModelPath,
      caseType,
      enableTransientAnalysis,
      promptOverrides,
      targetCount,
      startedAt: Date.now(),
      anomalies,
      schemes
    });
    return { taskId, caseType, resultRoot: `/mock/fulfillment_scc/${taskId}` };
  }

  async getTaskStatus(taskId) {
    await sleep(350);
    const task = this.tasks.get(taskId);
    if (!task) {
      throw new Error(`任务不存在: ${taskId}`);
    }
    const elapsed = (Date.now() - task.startedAt) / 1000;
    const target = task.targetCount;
    let status = "SUBMITTED";
    let generated = 0;
    let message = "任务已提交，等待调度。";

    if (elapsed < 2) {
      status = "SUBMITTED";
      message = "任务已提交，正在准备计算资源。";
    } else if (elapsed < 6) {
      status = "SIMULATING";
      message = "正在执行网架仿真计算。";
    } else if (elapsed < 9) {
      status = "ANOMALY_DONE";
      message = "异常定位已完成，准备生成规划方案。";
    } else if (elapsed < 16) {
      status = "PLANNING";
      generated = Math.min(target, Math.max(1, Math.floor((elapsed - 8) / 1.7)));
      message = `规划方案生成中，当前已得到 ${generated} 个候选可用方案。`;
    } else {
      status = "COMPLETED";
      generated = target;
      message = `任务完成，已生成 ${target} 个满足要求的方案。`;
    }

    return {
      taskId,
      status,
      generatedSchemeCount: generated,
      targetSchemeCount: target,
      message
    };
  }

  async getAnomalies(taskId) {
    await sleep(300);
    const task = this.tasks.get(taskId);
    if (!task) {
      throw new Error(`任务不存在: ${taskId}`);
    }
    return { items: task.anomalies };
  }

  async getSchemes(taskId, limit) {
    await sleep(350);
    const task = this.tasks.get(taskId);
    if (!task) {
      throw new Error(`任务不存在: ${taskId}`);
    }
    return { items: task.schemes.slice(0, limit) };
  }

  async getTopology(taskId, schemeId) {
    await sleep(260);
    const task = this.tasks.get(taskId);
    if (!task) {
      throw new Error(`任务不存在: ${taskId}`);
    }
    const target = task.schemes.find((item) => item.schemeId === schemeId);
    if (!target) {
      throw new Error(`方案不存在: ${schemeId}`);
    }
    return target.topology;
  }

  async getScheme(taskId, schemeId) {
    await sleep(200);
    const task = this.tasks.get(taskId);
    if (!task) {
      throw new Error(`任务不存在: ${taskId}`);
    }
    const target = task.schemes.find((item) => item.schemeId === schemeId);
    if (!target) {
      throw new Error(`方案不存在: ${schemeId}`);
    }
    return target;
  }

  async createCompareReport(payload) {
    await sleep(260);
    const reportId = `compare_${Date.now()}`;
    this.compareReports.set(reportId, {
      reportId,
      taskId: payload.taskId || "",
      createdAt: Date.now(),
      confirmedAt: 0,
      failed: false,
      ready: false,
      insights: [
        "- 方案一在综合年费用上最低，适合作为优先推荐方案。",
        "- 方案三在潮流安全裕度上更稳健，但成本高于方案一。",
        "- 短路电流节点存在超限风险，建议在最终方案中补充设备升级措施。"
      ].join("\n"),
      reportPath: "outputs/mock_compare_pcn/report/report.md"
    });
    return { reportId, stage: "DATA_PREPROCESSING", message: "Mock：比选任务已创建。" };
  }

  async getCompareReportStatus(reportId) {
    await sleep(220);
    const report = this.compareReports.get(reportId);
    if (!report) {
      throw new Error(`比选报告不存在: ${reportId}`);
    }

    const elapsed = (Date.now() - report.createdAt) / 1000;
    let stage = "DATA_PREPROCESSING";
    let message = "Mock：数据预处理中。";

    if (report.confirmedAt <= 0) {
      if (elapsed > 1.5) {
        stage = "INSIGHTS_GENERATION";
        message = "Mock：洞察生成中。";
      }
      if (elapsed > 3.0) {
        stage = "WAIT_INSIGHTS_CONFIRM";
        message = "Mock：洞察已生成，请确认。";
      }
      return {
        reportId,
        stage,
        failed: false,
        ready: false,
        message,
        currentInsights: stage === "WAIT_INSIGHTS_CONFIRM" ? report.insights : "",
        reportPath: "",
        reportPaths: {}
      };
    }

    const afterConfirm = (Date.now() - report.confirmedAt) / 1000;
    if (afterConfirm < 1.0) {
      stage = "RETRIEVE_CLAIMS";
      message = "Mock：检索洞察依据。";
    } else if (afterConfirm < 2.0) {
      stage = "GENERATE_REPORT";
      message = "Mock：报告生成中。";
    } else if (afterConfirm < 3.0) {
      stage = "VERIFY_CLAIMS";
      message = "Mock：PCN 依据校验中。";
    } else {
      stage = "DRAFT_READY";
      message = "Mock：初稿已就绪，可在编辑器中导出。";
      report.ready = true;
    }

    return {
      reportId,
      stage,
      failed: report.failed,
      ready: report.ready,
      message,
      currentInsights: "",
      reportPath: report.ready ? report.reportPath : "",
      reportPaths: report.ready
        ? {
            md: report.reportPath,
            docx: report.reportPath.replace(/\.md$/, ".docx"),
            pdf: report.reportPath.replace(/\.md$/, ".pdf")
          }
        : {}
    };
  }

  async confirmCompareReportInsights(reportId, insights) {
    await sleep(180);
    const report = this.compareReports.get(reportId);
    if (!report) {
      throw new Error(`比选报告不存在: ${reportId}`);
    }
    if (!insights || !String(insights).trim()) {
      throw new Error("洞察内容不能为空。");
    }
    report.insights = String(insights).trim();
    report.confirmedAt = Date.now();
    return {
      reportId,
      stage: "RETRIEVE_CLAIMS",
      message: "Mock：已确认洞察，开始后续流程。"
    };
  }
}

function createMockAnomalies() {
  return [
    { severity: "高", title: "线路过载", location: "110kV 东城线-12" },
    { severity: "中", title: "电压越限", location: "35kV 河湾站母线" },
    { severity: "中", title: "N-1 校核不通过", location: "220kV 北环变-2号主变" }
  ];
}

function createMockSchemes(targetCount) {
  const schemes = [];
  for (let i = 1; i <= targetCount; i += 1) {
    schemes.push({
      schemeId: `SCH-${String(i).padStart(2, "0")}`,
      name: `规划方案 ${i}`,
      summary: `建议新增联络线 ${i} 回，优化主变负荷分配，并进行分段开关调整。`,
      score: (90 - i * 2 + Math.random() * 4).toFixed(1),
      topology: createMockTopology(i)
    });
  }
  return schemes;
}

function createMockTopology(seed) {
  const rand = seeded(seed * 19 + 7);
  const nodeCount = 16 + seed * 2;
  const radius = 260 + seed * 8;
  const nodes = [];
  for (let i = 0; i < nodeCount; i += 1) {
    const angle = (Math.PI * 2 * i) / nodeCount;
    const jitter = (rand() - 0.5) * 120;
    const x = Math.cos(angle) * radius + jitter;
    const y = Math.sin(angle) * radius + (rand() - 0.5) * 110;
    nodes.push({
      id: `N${i + 1}`,
      label: `站点-${i + 1}`,
      type: i % 4 === 0 ? "变电站" : "负荷节点",
      voltage: i % 3 === 0 ? "220kV" : i % 2 === 0 ? "110kV" : "35kV",
      x,
      y
    });
  }

  const edges = [];
  for (let i = 0; i < nodeCount; i += 1) {
    const a = nodes[i];
    const b = nodes[(i + 1) % nodeCount];
    edges.push({
      source: a.id,
      target: b.id,
      loading: +(0.35 + rand() * 0.6).toFixed(2)
    });
    if (i % 3 === 0) {
      const c = nodes[(i + 4) % nodeCount];
      edges.push({
        source: a.id,
        target: c.id,
        loading: +(0.2 + rand() * 0.7).toFixed(2)
      });
    }
  }

  return { nodes, edges };
}

function seeded(seed) {
  let value = seed;
  return () => {
    value = (value * 9301 + 49297) % 233280;
    return value / 233280;
  };
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

class TopologyViewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.nodes = [];
    this.edges = [];
    this.nodeMap = new Map();
    this.dragging = false;
    this.lastPoint = null;
    this.selectedNodeId = "";
    this.scale = 1;
    this.offsetX = 0;
    this.offsetY = 0;
    this.dpr = window.devicePixelRatio || 1;

    this.resize = this.resize.bind(this);
    this.handleWheel = this.handleWheel.bind(this);
    this.handleDown = this.handleDown.bind(this);
    this.handleMove = this.handleMove.bind(this);
    this.handleUp = this.handleUp.bind(this);

    this.bindEvents();
    this.resize();
  }

  bindEvents() {
    window.addEventListener("resize", this.resize);
    this.canvas.addEventListener("wheel", this.handleWheel, { passive: false });
    this.canvas.addEventListener("mousedown", this.handleDown);
    window.addEventListener("mousemove", this.handleMove);
    window.addEventListener("mouseup", this.handleUp);
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.max(1, Math.floor(rect.width * this.dpr));
    this.canvas.height = Math.max(1, Math.floor(rect.height * this.dpr));
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.draw();
  }

  setData(data) {
    this.nodes = Array.isArray(data.nodes) ? [...data.nodes] : [];
    this.edges = Array.isArray(data.edges) ? [...data.edges] : [];
    this.nodeMap = new Map();
    this.nodes.forEach((node, index) => {
      const id = String(node.id || `N${index + 1}`);
      node.id = id;
      node.label = node.label || id;
      if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) {
        const angle = (Math.PI * 2 * index) / Math.max(this.nodes.length, 1);
        node.x = Math.cos(angle) * 220;
        node.y = Math.sin(angle) * 220;
      }
      this.nodeMap.set(id, node);
    });
    this.selectedNodeId = "";
    this.fitToView();
  }

  fitToView() {
    if (!this.nodes.length) {
      this.scale = 1;
      this.offsetX = 0;
      this.offsetY = 0;
      this.draw();
      return;
    }

    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;

    this.nodes.forEach((node) => {
      minX = Math.min(minX, node.x);
      minY = Math.min(minY, node.y);
      maxX = Math.max(maxX, node.x);
      maxY = Math.max(maxY, node.y);
    });

    const width = maxX - minX || 1;
    const height = maxY - minY || 1;
    const rect = this.canvas.getBoundingClientRect();
    const margin = 70;
    const sx = (rect.width - margin * 2) / width;
    const sy = (rect.height - margin * 2) / height;
    this.scale = Math.max(0.25, Math.min(2.8, Math.min(sx, sy)));
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    this.offsetX = rect.width / 2 - centerX * this.scale;
    this.offsetY = rect.height / 2 - centerY * this.scale;
    this.draw();
  }

  zoomBy(factor) {
    const rect = this.canvas.getBoundingClientRect();
    this.zoomAt(factor, rect.width / 2, rect.height / 2);
  }

  zoomAt(factor, sx, sy) {
    const before = this.screenToWorld(sx, sy);
    this.scale = Math.max(0.2, Math.min(3.5, this.scale * factor));
    const after = this.worldToScreen(before.x, before.y);
    this.offsetX += sx - after.x;
    this.offsetY += sy - after.y;
    this.draw();
  }

  handleWheel(event) {
    event.preventDefault();
    const rect = this.canvas.getBoundingClientRect();
    const sx = event.clientX - rect.left;
    const sy = event.clientY - rect.top;
    const factor = event.deltaY < 0 ? 1.1 : 0.91;
    this.zoomAt(factor, sx, sy);
  }

  handleDown(event) {
    this.dragging = true;
    this.lastPoint = { x: event.clientX, y: event.clientY };
    this.canvas.classList.add("dragging");
  }

  handleMove(event) {
    if (!this.dragging || !this.lastPoint) {
      return;
    }
    const dx = event.clientX - this.lastPoint.x;
    const dy = event.clientY - this.lastPoint.y;
    this.lastPoint = { x: event.clientX, y: event.clientY };
    this.offsetX += dx;
    this.offsetY += dy;
    this.draw();
  }

  handleUp() {
    this.dragging = false;
    this.lastPoint = null;
    this.canvas.classList.remove("dragging");
  }

  worldToScreen(x, y) {
    return {
      x: x * this.scale + this.offsetX,
      y: y * this.scale + this.offsetY
    };
  }

  screenToWorld(x, y) {
    return {
      x: (x - this.offsetX) / this.scale,
      y: (y - this.offsetY) / this.scale
    };
  }

  draw() {
    const rect = this.canvas.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    this.ctx.clearRect(0, 0, width, height);
    this.drawGrid(width, height);
    this.drawEdges();
    this.drawNodes();
  }

  drawGrid(width, height) {
    const step = 56;
    this.ctx.save();
    this.ctx.strokeStyle = "rgba(22, 90, 62, 0.08)";
    this.ctx.lineWidth = 1;
    for (let x = 0; x <= width; x += step) {
      this.ctx.beginPath();
      this.ctx.moveTo(x, 0);
      this.ctx.lineTo(x, height);
      this.ctx.stroke();
    }
    for (let y = 0; y <= height; y += step) {
      this.ctx.beginPath();
      this.ctx.moveTo(0, y);
      this.ctx.lineTo(width, y);
      this.ctx.stroke();
    }
    this.ctx.restore();
  }

  drawEdges() {
    this.ctx.save();
    this.edges.forEach((edge) => {
      const source = this.nodeMap.get(String(edge.source));
      const target = this.nodeMap.get(String(edge.target));
      if (!source || !target) {
        return;
      }
      const a = this.worldToScreen(source.x, source.y);
      const b = this.worldToScreen(target.x, target.y);
      const edgeType = String(edge.type || "");
      const isRemoved = edgeType.includes("停运") || edgeType.includes("删除");
      this.ctx.strokeStyle = isRemoved ? "rgba(203, 62, 43, 0.82)" : "rgba(19, 138, 97, 0.82)";
      this.ctx.lineWidth = isRemoved ? 2.2 : 2.6;
      this.ctx.setLineDash(isRemoved ? [9, 6] : []);
      this.ctx.beginPath();
      this.ctx.moveTo(a.x, a.y);
      this.ctx.lineTo(b.x, b.y);
      this.ctx.stroke();

      const circuitCount = toNumber(edge.circuitCount, 1);
      const labelPrefix = isRemoved ? "删除" : "新增";
      const labelText = `${labelPrefix} ${circuitCount}回`;
      const midX = (a.x + b.x) / 2;
      const midY = (a.y + b.y) / 2;
      const offsetX = b.y >= a.y ? 10 : -42;
      const offsetY = b.x >= a.x ? -8 : 16;

      this.ctx.save();
      this.ctx.setLineDash([]);
      this.ctx.font = "11px Manrope, Noto Sans SC, sans-serif";
      const textWidth = this.ctx.measureText(labelText).width;
      const boxX = midX + offsetX - 5;
      const boxY = midY + offsetY - 12;
      this.ctx.fillStyle = "rgba(255, 255, 255, 0.88)";
      this.ctx.fillRect(boxX, boxY, textWidth + 10, 18);
      this.ctx.fillStyle = isRemoved ? "rgba(135, 38, 26, 0.96)" : "rgba(18, 101, 71, 0.96)";
      this.ctx.fillText(labelText, midX + offsetX, midY + offsetY);
      this.ctx.restore();
    });
    this.ctx.setLineDash([]);
    this.ctx.restore();
  }

  drawNodes() {
    this.nodes.forEach((node) => {
      const pos = this.worldToScreen(node.x, node.y);
      const selected = node.id === this.selectedNodeId;
      this.ctx.beginPath();
      this.ctx.fillStyle = selected ? "#f5862f" : node.type === "变电站" ? "#0c8f62" : "#137f98";
      this.ctx.arc(pos.x, pos.y, selected ? 8 : 6.3, 0, Math.PI * 2);
      this.ctx.fill();

      this.ctx.font = "12px Manrope, Noto Sans SC, sans-serif";
      this.ctx.fillStyle = "#22453a";
      this.ctx.fillText(node.label, pos.x + 9, pos.y - 9);
    });
  }
}

bootstrap();

function bootstrap() {
  try {
    init();
  } catch (error) {
    setBootIndicator("error", "脚本初始化失败：" + readableError(error));
  }
}
