const API_BASE_URL = window.location.origin;
const q = new URLSearchParams(window.location.search);
const taskId = q.get("taskId") || "";
const schemeId = q.get("schemeId") || "";

const dom = {
  headMeta: document.querySelector("#head-meta"),
  summaryText: document.querySelector("#summary-text"),
  scoreNum: document.querySelector("#score-num"),
  scoreBar: document.querySelector("#score-bar"),
  kpi1: document.querySelector("#kpi-1"),
  kpi2: document.querySelector("#kpi-2"),
  kpi3: document.querySelector("#kpi-3"),
  anomalyList: document.querySelector("#anomaly-list"),
  actionList: document.querySelector("#action-list")
};

init();

async function init() {
  if (!taskId || !schemeId) {
    renderFallback("缺少任务或方案标识，暂时无法加载真实方案报告。");
    return;
  }

  try {
    const [scheme, anomalyPayload] = await Promise.all([
      requestJson(`/api/tasks/${encodeURIComponent(taskId)}/schemes/${encodeURIComponent(schemeId)}`),
      requestJson(`/api/tasks/${encodeURIComponent(taskId)}/anomalies`)
    ]);
    renderRealReport(scheme, anomalyPayload);
  } catch (error) {
    renderFallback(`真实方案报告加载失败：${readableError(error)}`);
  }
}

function renderRealReport(scheme, anomalyPayload) {
  const proposal = scheme.proposal || {};
  const modifications = proposal.modifications || [];
  const addedLines = modifications.filter((item) => item.action === "add_line").length;
  const addedBuses = modifications.filter((item) => item.action === "add_bus").length;
  const disabledBranches = modifications.filter((item) => item.action === "disable_branch").length;
  const score = scheme.score !== null && scheme.score !== undefined ? scheme.score : "-";

  dom.headMeta.textContent = `taskId: ${taskId} | schemeId: ${schemeId} | run_${scheme.runNumber || "-"}`;
  dom.summaryText.textContent = scheme.summary || "当前方案未提供摘要。";
  dom.scoreNum.textContent = String(score);
  dom.scoreBar.style.width = score === "-" ? "0%" : `${score}%`;
  dom.kpi1.textContent = `+${addedLines}`;
  dom.kpi2.textContent = `-${disabledBranches}`;
  dom.kpi3.textContent = `${addedBuses}`;

  const anomalies = normalizeAnomalies(anomalyPayload).slice(0, 6);
  dom.anomalyList.innerHTML = "";
  anomalies.forEach((item) => {
    const li = document.createElement("li");
    const sev = item.severity ? `[${item.severity}] ` : "";
    li.textContent = `${sev}${item.title}（${item.location}）`;
    dom.anomalyList.appendChild(li);
  });

  dom.actionList.innerHTML = "";
  buildActionItems(modifications).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    dom.actionList.appendChild(li);
  });
}

function buildActionItems(modifications) {
  if (!modifications.length) {
    return ["当前方案未记录具体改造动作。"];
  }

  return modifications.slice(0, 8).map((item, index) => {
    const params = item.params || {};
    const branch = params.full_branch_data || {};
    const bus = params.full_bus_data || {};
    if (item.action === "add_line") {
      return `${index + 1}. 新增线路：${branch.NAME1 || "未知端点"} -> ${branch.NAME2 || "未知端点"}。`;
    }
    if (item.action === "disable_branch") {
      return `${index + 1}. 停运线路：${branch.NAME1 || "未知端点"} -> ${branch.NAME2 || "未知端点"}。`;
    }
    if (item.action === "add_bus") {
      return `${index + 1}. 新增母线：${bus.NAME || "未知母线"}。`;
    }
    return `${index + 1}. 执行动作：${item.action || "unknown"}。`;
  });
}

function normalizeAnomalies(payload) {
  const list = payload.items || [];
  if (!Array.isArray(list)) {
    return [];
  }
  return list.map((item, idx) => ({
    title: item.title || item.name || item.message || `异常-${idx + 1}`,
    location: item.location || item.line || item.station || "未知位置",
    severity: item.severity || item.level || ""
  }));
}

function renderFallback(message) {
  dom.headMeta.textContent = `taskId: ${taskId || "-"} | schemeId: ${schemeId || "-"}`;
  dom.summaryText.textContent = message;
  dom.scoreNum.textContent = "-";
  dom.scoreBar.style.width = "0%";
  dom.kpi1.textContent = "-";
  dom.kpi2.textContent = "-";
  dom.kpi3.textContent = "-";
  dom.anomalyList.innerHTML = "<li>未加载到异常信息。</li>";
  dom.actionList.innerHTML = "<li>未加载到方案动作。</li>";
}

async function requestJson(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }
  return response.json();
}

function readableError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
