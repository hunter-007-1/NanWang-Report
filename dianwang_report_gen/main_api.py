from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import BaseModel
import yaml

from types import SimpleNamespace

from src.graph_state import State
from src.llm import client_manager
from src.nodes import (
    convert_report,
    data_preprocessing_pcn,
    generate_report,
    insights_generation_node,
    retrieve_claims_for_insights,
    verify_pcn_claims,
)
from src.nodes.convert_report import _latest_report_export_path
from src.nodes.report_quality import format_report_quality_review_message
from src.services.rewrite_service import rewrite_selected_segment
from src.utils.markdown import strip_markdown_fence_noise
from src.utils.modelscope_embeddings import ModelScopeEmbeddings
from src.utils import (
    generate_timestamped_output_directory,
    init_openai_client,
    setup_logger,
)

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))
APP_DIR = Path(__file__).resolve().parent


class CompareReportCreateRequest(BaseModel):
    taskId: str = ""
    inputDir: str = "../powergrid_pipeline/fulfillment_scc"
    outputDir: str = "outputs"
    debug: bool = True
    backgroundContextFile: str = ""


class CompareReportConfirmInsightsRequest(BaseModel):
    insights: str


class SaveReportRequest(BaseModel):
    taskId: str = ""
    reportId: str = ""
    reportPath: str = ""
    contentMd: str
    reason: str = "save"


class ConvertReportRequest(BaseModel):
    taskId: str = ""
    reportId: str = ""
    reportPath: str = ""
    contentMd: str
    format: str


class ReadReportRequest(BaseModel):
    taskId: str = ""
    reportId: str = ""
    reportPath: str = ""


class ResetReportRequest(BaseModel):
    taskId: str = ""
    reportId: str = ""
    reportPath: str = ""


class ReadReportVersionRequest(BaseModel):
    reportId: str = ""
    reportPath: str = ""
    versionId: str


class RewriteSelection(BaseModel):
    start: int
    end: int
    text: str = ""


class RewriteRequest(BaseModel):
    taskId: str = ""
    reportId: str = ""
    reportPath: str = ""
    instruction: str
    selection: RewriteSelection
    parentVersionId: str = ""
    sessionId: str = ""


@dataclass
class CompareReportTask:
    report_id: str
    source_task_id: str = ""
    stage: str = "DATA_PREPROCESSING"
    failed: bool = False
    ready: bool = False
    message: str = ""
    input_dir: Path = APP_DIR / "../powergrid_pipeline/fulfillment_scc"
    output_dir: Path = APP_DIR / "outputs"
    run_output_dir: Optional[Path] = None
    state_data: Dict[str, Any] = field(default_factory=dict)
    insights_draft: str = ""
    insights_confirmed: str = ""
    report_paths: Dict[str, str] = field(default_factory=dict)
    result_file: Optional[Path] = None
    log_file: Optional[Path] = None
    background_context_file: str = ""
    background_context: str = ""


app = FastAPI(title="DianWang Report API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TASKS: Dict[str, CompareReportTask] = {}
TASKS_LOCK = asyncio.Lock()
READY = False
READY_ERROR = ""

# 第5步输入来源为上游 fulfillment_scc/run_*，这里会在 demo_input 下聚合成：
# generation/parsed_proposals.json
# analysis_1..N/pf_report_i.json, n1_report_i.json, scc_report_i.json
# 兼容两种上游输出布局：
# 1. 旧布局：run_*/result/proposal + run_*/test_output_v*/analysis_*
# 2. 扁平布局：run_* 根目录直接包含 selected_proposal_*.json 和 pf/n1/scc 报告


def _load_pipeline_api_config() -> Dict[str, Any]:
    """读取网架规划服务的模型配置，作为报告服务 env 配置的回退来源。"""
    settings_path = APP_DIR.parent / "powergrid_pipeline" / "powergrid_pipeline_v2" / "config" / "settings.yaml"
    if not settings_path.exists():
        return {}

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        api_config = config.get("api") or {}
        return api_config if isinstance(api_config, dict) else {}
    except Exception as exc:
        logger.warning(f"读取网架规划模型配置失败，将仅使用环境变量: {exc}")
        return {}


def _env_value(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _build_default_client_args() -> Dict[str, Any]:
    pipeline_api = _load_pipeline_api_config()
    fallback_api_key = pipeline_api.get("modelscope_api_key")
    fallback_base_url = pipeline_api.get("modelscope_base_url")
    fallback_model = pipeline_api.get("llm_model_name")

    args = {
        "llm": _env_value("LLM_MODEL") or fallback_model,
        "llm_api_key": _env_value("OPENAI_API_KEY") or fallback_api_key,
        "llm_base_url": _env_value("LLM_BASE_URL") or fallback_base_url,
        "llm_temperature": float(_env_value("LLM_TEMPERATURE") or "0.6"),
        "vlm": _env_value("VLM_MODEL") or _env_value("LLM_MODEL") or fallback_model,
        "vlm_api_key": _env_value("VLM_API_KEY") or _env_value("OPENAI_API_KEY") or fallback_api_key,
        "vlm_base_url": _env_value("VLM_BASE_URL") or _env_value("LLM_BASE_URL") or fallback_base_url,
        "vlm_temperature": float(_env_value("VLM_TEMPERATURE") or "0.6"),
        "max_completion_tokens": int(_env_value("MAX_COMPLETION_TOKENS") or "32768"),
        "embedding_model": _env_value("EMBEDDING_MODEL"),
        "embedding_api_key": _env_value("EMBEDDING_API_KEY") or _env_value("OPENAI_API_KEY") or fallback_api_key,
        "embedding_base_url": _env_value("EMBEDDING_BASE_URL"),
    }

    missing = [
        name
        for name, value in {
            "LLM_MODEL": args["llm"],
            "LLM_BASE_URL": args["llm_base_url"],
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "报告模型配置缺失: "
            + ", ".join(missing)
            + "。请在 dianwang_report_gen/.env 中显式配置。"
        )

    return args


def _init_clients_once() -> None:
    global READY, READY_ERROR
    if READY:
        return

    args = _build_default_client_args()

    llm_args = SimpleNamespace(**args.copy())
    vlm_args = SimpleNamespace(**args.copy())

    llm_openai_client, llm_model, _ = init_openai_client(
        args["llm"], args["llm_api_key"], args["llm_base_url"], llm_args, "llm"
    )
    vlm_openai_client, vlm_model, _ = init_openai_client(
        args["vlm"], args["vlm_api_key"], args["vlm_base_url"], vlm_args, "vlm"
    )

    llm_langchain_client = ChatOpenAI(
        model=llm_model,
        api_key=args["llm_api_key"],
        base_url=args["llm_base_url"],
        temperature=args["llm_temperature"],
        max_completion_tokens=args["max_completion_tokens"],
    )

    # 嵌入模型可选：当前报告生成链路的检索走 SQLite FTS5，并未实际调用嵌入
    # API。仅在显式配置 EMBEDDING_MODEL + EMBEDDING_BASE_URL 时才初始化嵌入客户端。
    embedding_configured = bool(args["embedding_model"] and args["embedding_base_url"])
    if embedding_configured:
        embedding_model = ModelScopeEmbeddings(
            model=args["embedding_model"],
            api_key=args["embedding_api_key"] or args["llm_api_key"],
            base_url=args["embedding_base_url"],
        )
        client_manager.setup_embedding_model(
            embedding_model_name_or_path=args["embedding_model"],
            embedding_model=embedding_model,
        )
    else:
        logger.info(
            "未配置 EMBEDDING_MODEL / EMBEDDING_BASE_URL，跳过嵌入客户端初始化 "
            "（当前报告生成链路不依赖嵌入模型）"
        )

    client_manager.setup_llm_openai_client(
        llm_openai_client,
        llm_model,
        args["llm_temperature"],
        args["max_completion_tokens"],
    )
    client_manager.setup_vlm_openai_client(
        vlm_openai_client,
        vlm_model,
        args["vlm_temperature"],
        args["max_completion_tokens"],
    )
    client_manager.setup_langchain_chat_model(llm_langchain_client)

    READY = True
    READY_ERROR = ""


@app.on_event("startup")
async def _startup() -> None:
    global READY_ERROR
    try:
        _init_clients_once()
        logger.info("API 模型客户端初始化完成")
    except Exception as exc:
        READY_ERROR = str(exc)
        logger.exception("API 模型客户端初始化失败")


async def _set_task_stage(report_id: str, stage: str, message: str = "") -> None:
    async with TASKS_LOCK:
        task = TASKS.get(report_id)
        if not task:
            return
        task.stage = stage
        task.message = message


async def _mark_task_failed(report_id: str, message: str) -> None:
    async with TASKS_LOCK:
        task = TASKS.get(report_id)
        if not task:
            return
        task.failed = True
        task.ready = False
        task.stage = "FAILED"
        task.message = message

    await _persist_task_result(report_id)


async def _run_node_in_thread(node_func, state: State) -> Dict[str, Any]:
    """在独立线程执行节点，避免阻塞 FastAPI 主事件循环。"""
    return await asyncio.to_thread(lambda: asyncio.run(node_func(state)))


async def _persist_task_result(report_id: str) -> None:
    """将任务关键状态落盘为 result.json，便于回放和排障。"""
    async with TASKS_LOCK:
        task = TASKS.get(report_id)
        if not task or not task.result_file:
            return

        payload = {
            "report_id": task.report_id,
            "task_id": task.source_task_id,
            "stage": task.stage,
            "failed": task.failed,
            "ready": task.ready,
            "message": task.message,
            "run_output_dir": str(task.run_output_dir) if task.run_output_dir else "",
            "log_file": _to_rel_path(task.log_file) if task.log_file else "",
            "report_paths": task.report_paths,
            "md_tables_str": task.state_data.get("md_tables_str"),
            "first_insights": task.state_data.get("first_insights"),
            "raw_report": task.state_data.get("raw_report"),
            "md_report": task.state_data.get("md_report"),
            "pcn_claims_count": len(task.state_data.get("pcn_claims", {}) or {}),
            "pcn_verification_result": task.state_data.get("pcn_verification_result"),
            "pcn_verification_passed": task.state_data.get("pcn_verification_passed"),
            "pcn_verification_report_path": task.state_data.get("pcn_verification_report_path"),
            "report_quality_result": task.state_data.get("report_quality_result"),
        }

        result_file = task.result_file

    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _setup_task_logger(task: CompareReportTask) -> None:
    """日志策略对齐 main_pcn：控制台 INFO + 文件 DEBUG(out.log)。"""
    if not task.run_output_dir:
        return

    setup_logger(task.run_output_dir, console_level="INFO", file_level="DEBUG")
    task.log_file = task.run_output_dir / "out.log"


def _to_rel_path(path: Path) -> str:
    try:
        return str(path.relative_to(APP_DIR))
    except Exception:
        return str(path)


def _resolve_report_md_path(report_id: str, report_path: str) -> Path:
    """优先按 reportPath 定位 report.md；缺失时回退任务记录。"""
    candidate = (report_path or "").strip()
    if candidate:
        raw = Path(candidate)
        path = raw if raw.is_absolute() else (APP_DIR / raw)
        path = path.resolve()
        outputs_root = (APP_DIR / "outputs").resolve()
        if outputs_root not in path.parents and path != outputs_root:
            raise HTTPException(status_code=400, detail="reportPath 必须位于 outputs 目录内")
        if path.suffix.lower() != ".md":
            raise HTTPException(status_code=400, detail="reportPath 必须指向 .md 文件")
        return path

    if report_id:
        task = TASKS.get(report_id)
        if task and task.report_paths.get("md"):
            return (APP_DIR / task.report_paths["md"]).resolve()

    raise HTTPException(status_code=400, detail="未提供有效 reportPath，且无法从 reportId 定位 report.md")


def _build_user_edit_md_path(original_md_path: Path) -> Path:
    return original_md_path.parent / "report.user.md"


def _build_report_versions_dir(user_md_path: Path) -> Path:
    return user_md_path.parent / "versions"


def _normalize_version_reason(reason: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", (reason or "save").lower()).strip("-")
    return normalized or "save"


def _save_report_version_snapshot(user_md_path: Path, content: str, reason: str) -> Path:
    versions_dir = _build_report_versions_dir(user_md_path)
    versions_dir.mkdir(parents=True, exist_ok=True)
    timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    version_path = versions_dir / f"report.user.{timestamp}.{_normalize_version_reason(reason)}.md"
    version_path.write_text(content, encoding="utf-8")
    return version_path


def _version_path_for_id(user_md_path: Path, version_id: str) -> Path:
    clean_id = Path(version_id).name
    if clean_id != version_id or not clean_id.startswith("report.user.") or not clean_id.endswith(".md"):
        raise HTTPException(status_code=400, detail="versionId 无效")
    versions_dir = _build_report_versions_dir(user_md_path).resolve()
    version_path = (versions_dir / clean_id).resolve()
    if versions_dir not in version_path.parents or not version_path.is_file():
        raise HTTPException(status_code=404, detail="历史版本不存在")
    return version_path


def _version_reason_from_name(path: Path) -> str:
    match = re.match(r"^report\.user\.\d{8}-\d{6}-\d+\.([a-z0-9_-]+)\.md$", path.name)
    return match.group(1) if match else "unknown"


def _list_report_versions(user_md_path: Path) -> List[Dict[str, Any]]:
    versions_dir = _build_report_versions_dir(user_md_path)
    if not versions_dir.exists() or not versions_dir.is_dir():
        return []
    versions = []
    for path in sorted(versions_dir.glob("report.user.*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        versions.append({
            "id": path.name,
            "reason": _version_reason_from_name(path),
            "size": stat.st_size,
            "contentLength": len(path.read_text(encoding="utf-8")),
            "createdAt": __import__("datetime").datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "path": _to_rel_path(path),
        })
    return versions


def _read_report_version(user_md_path: Path, version_id: str) -> str:
    return _version_path_for_id(user_md_path, version_id).read_text(encoding="utf-8")


def _restore_report_version(user_md_path: Path, version_id: str) -> str:
    content = _read_report_version(user_md_path, version_id)
    user_md_path.parent.mkdir(parents=True, exist_ok=True)
    user_md_path.write_text(content, encoding="utf-8")
    return content


def _delete_report_version(user_md_path: Path, version_id: str) -> Path:
    version_path = _version_path_for_id(user_md_path, version_id)
    version_path.unlink()
    return version_path


def _build_download_url(path: Path) -> str:
    rel = _to_rel_path(path)
    return f"/api/reports/download?path={rel}"


def _load_json_file(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_run_number(path: Path) -> int:
    match = re.search(r"run_(\d+)$", path.name)
    return int(match.group(1)) if match else -1


def _list_run_dirs(base_input_dir: Path) -> List[Path]:
    run_dirs = [
        path for path in base_input_dir.iterdir()
        if path.is_dir() and re.fullmatch(r"run_\d+", path.name)
    ]
    return sorted(run_dirs, key=lambda path: (_extract_run_number(path), path.name))


def _select_final_proposal_file(run_dir: Path) -> Optional[tuple[Path, Dict[str, Any]]]:
    ranked: List[tuple[int, int, Path, Dict[str, Any]]] = []

    candidate_files: List[Path] = []
    proposal_dir = run_dir / "result" / "proposal"
    if proposal_dir.exists() and proposal_dir.is_dir():
        candidate_files.extend(sorted(proposal_dir.glob("*.json")))
    else:
        logger.debug(f"{run_dir.name}: 未找到旧版 proposal 目录，尝试扁平输出布局")

    candidate_files.extend(sorted(run_dir.glob("selected_proposal_iter*_scheme*.json")))

    for proposal_path in candidate_files:
        try:
            proposal_data = _load_json_file(proposal_path)
            iteration = int(proposal_data.get("iteration", -1))
            scheme_number = int(proposal_data.get("scheme_number", -1))
            if iteration < 0 or scheme_number < 0 or not isinstance(proposal_data.get("proposal"), dict):
                logger.warning(f"跳过无效 proposal 文件: {proposal_path}")
                continue
            ranked.append((iteration, scheme_number, proposal_path, proposal_data))
        except Exception as exc:
            logger.warning(f"读取 proposal 文件失败 {proposal_path}: {exc}")

    if not ranked:
        logger.warning(f"跳过 {run_dir.name}: 未找到有效的最终方案文件")
        return None

    ranked.sort(key=lambda item: (item[0], item[1], item[2].name))
    _, _, proposal_path, proposal_data = ranked[-1]
    return proposal_path, proposal_data


def _resolve_final_analysis_files(run_dir: Path, iteration: int, scheme_number: int) -> Dict[str, Path]:
    analysis_dir = run_dir / f"test_output_v{iteration}" / f"analysis_{scheme_number}"
    if analysis_dir.exists() and analysis_dir.is_dir():
        return {
            "analysis_dir": analysis_dir,
            "pf": analysis_dir / f"pf_report_{scheme_number}.json",
            "n1": analysis_dir / f"n1_report_{scheme_number}.json",
            "scc": analysis_dir / f"scc_report_{scheme_number}.json",
        }

    flat_files = {
        "analysis_dir": run_dir,
        "pf": run_dir / f"pf_report_{scheme_number}.json",
        "n1": run_dir / f"n1_report_{scheme_number}.json",
        "scc": run_dir / f"scc_report_{scheme_number}.json",
    }
    if all(flat_files[key].exists() for key in ("pf", "n1", "scc")):
        return flat_files

    return {
        "analysis_dir": analysis_dir,
        "pf": analysis_dir / f"pf_report_{scheme_number}.json",
        "n1": analysis_dir / f"n1_report_{scheme_number}.json",
        "scc": analysis_dir / f"scc_report_{scheme_number}.json",
    }


def _copy_if_exists(src: Path, dst: Path, copied_files: List[str], missing_files: List[str], demo_input_dir: Path) -> None:
    if src.exists() and src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied_files.append(str(dst.relative_to(demo_input_dir)))
    else:
        missing_files.append(str(src))


def _stringify_economic_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    return str(value).strip()


def _first_present_economic_value(*values: Any) -> Any:
    """按字段优先级取第一个有效经济值。

    有效：不是 None，且不是空字符串/纯空格。
    数字 0、0.0、字符串 \"0\" 均视为有效，不得因假值而跳过。
    """
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _parse_economic_number(value: Any) -> Optional[float]:
    """解析经济数值并统一换算为元。

    历史案例原始字段（如建造成本估算=240000000）单位为元；
    若文本显式标注万元/亿元则换算为元。
    """
    text = _stringify_economic_value(value)
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    if "亿元" in text:
        return number * 100000000
    if "万元" in text:
        return number * 10000
    # 无单位时按元处理（与历史 JSON 数值口径一致）
    return number


def _format_economic_number(value: float) -> str:
    """格式化内部经济数值（单位：元）。"""
    rounded = round(value, 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}"


def _get_economic_defaults():
    """经济参数唯一来源：compare_rules.yaml（经 grid_calculator.get_economic_defaults）。"""
    from src.tools.grid_calculator import get_economic_defaults

    return get_economic_defaults()


def _calculate_annual_cost(construction_cost: Any, operation_cost: Any) -> str:
    """年费用 = 建设投资 × CRF(i,n) + 年运行维护费。仅表示年费用。"""
    from src.tools.grid_calculator import calculate_capital_recovery_factor

    construction = _parse_economic_number(construction_cost)
    operation = _parse_economic_number(operation_cost)
    if construction is None or operation is None:
        return ""
    eco = _get_economic_defaults()
    try:
        factor = calculate_capital_recovery_factor(eco["interest_rate"], eco["years"])
    except ValueError as exc:
        logger.warning(f"年费用资本回收系数计算失败: {exc}")
        return ""
    return _format_economic_number(construction * factor + operation)


def _economic_values_approximately_equal(left: float, right: float) -> bool:
    """旧版年费用误写识别的数值容差：max(1元, |expected|×1e-6)。"""
    return abs(left - right) <= max(1.0, abs(right) * 1e-6)


def _seed_economic_fields_from_mapping(source: Dict[str, Any]) -> Dict[str, str]:
    """仅抽取原始经济字段文本，不做公式补齐（供旧版迁移前种子写入）。"""
    return {
        "construction_cost": _stringify_economic_value(
            _first_present_economic_value(
                source.get("construction_cost"),
                source.get("construction_cost_estimate"),
                source.get("constructionCostEstimate"),
                source.get("建造成本估算"),
                source.get("建设投资成本"),
                source.get("建设投资"),
                source.get("建设成本"),
            )
        ),
        "operation_cost": _stringify_economic_value(
            _first_present_economic_value(
                source.get("operation_cost"),
                source.get("maintenance_cost_estimate"),
                source.get("maintenanceCostEstimate"),
                source.get("维护成本估算"),
                source.get("年运行维护费"),
                source.get("运维成本"),
                source.get("维护成本"),
            )
        ),
        "annual_cost": _stringify_economic_value(
            _first_present_economic_value(
                source.get("annual_cost"),
                source.get("yearly_cost"),
                source.get("annualCost"),
                source.get("年费用"),
            )
        ),
        "lifecycle_cost": _stringify_economic_value(
            _first_present_economic_value(
                source.get("lifecycle_cost"),
                source.get("total_lifecycle_cost"),
                source.get("lifecycleCost"),
                source.get("全寿命周期成本"),
                source.get("全生命周期成本"),
                source.get("全寿命周期成本LCC"),
            )
        ),
    }


def _migrate_legacy_run_economics(proposal: Dict[str, Any], run_label: str = "") -> bool:
    """仅用于旧版 run 聚合：识别“lifecycle_cost 实际为年费用”的误写并迁移。

    识别依据（必须同时满足）：
    1) annual_cost 不存在；
    2) lifecycle_cost 存在；
    3) construction_cost 与 operation_cost 可解析；
    4) old_lifecycle ≈ expected_annual = C×CRF + O（容差 max(1, |E|×1e-6)）。

    成功后：annual_cost ← 原 lifecycle_cost，清空 lifecycle_cost，再补算 LCC。
    不符合则保留原 lifecycle_cost（可能为真实 LCC）。
    """
    seeded = _seed_economic_fields_from_mapping(proposal)
    if seeded["annual_cost"]:
        return False
    if not seeded["lifecycle_cost"]:
        return False
    construction = _parse_economic_number(seeded["construction_cost"])
    operation = _parse_economic_number(seeded["operation_cost"])
    old_lifecycle = _parse_economic_number(seeded["lifecycle_cost"])
    if construction is None or operation is None or old_lifecycle is None:
        logger.warning(
            f"旧版经济字段迁移跳过（无法解析）: run={run_label}, "
            f"construction={seeded['construction_cost']!r}, "
            f"operation={seeded['operation_cost']!r}, "
            f"lifecycle={seeded['lifecycle_cost']!r}"
        )
        return False

    expected_annual_text = _calculate_annual_cost(
        seeded["construction_cost"], seeded["operation_cost"]
    )
    expected_annual = _parse_economic_number(expected_annual_text)
    if expected_annual is None:
        logger.warning(f"旧版经济字段迁移跳过（无法计算期望年费用）: run={run_label}")
        return False

    if not _economic_values_approximately_equal(old_lifecycle, expected_annual):
        # 可能是真实 LCC，不迁移
        return False

    old_lifecycle_text = seeded["lifecycle_cost"]
    proposal["annual_cost"] = old_lifecycle_text
    proposal.pop("lifecycle_cost", None)

    filled = _economic_fields_from_proposal(proposal)
    for key in ("construction_cost", "operation_cost", "annual_cost", "lifecycle_cost"):
        if filled.get(key):
            proposal[key] = filled[key]

    proposal["_economic_provenance"] = {
        "annual_cost": "migrated",
        "annual_cost_source_field": "legacy.lifecycle_cost",
        "lifecycle_cost": "calculated",
        "lifecycle_cost_source_field": None,
    }

    logger.info(
        f"旧版经济字段迁移: run={run_label}, "
        f"原lifecycle_cost={old_lifecycle_text}, "
        f"迁移后annual_cost={proposal.get('annual_cost')}, "
        f"新补算lifecycle_cost={proposal.get('lifecycle_cost')}"
    )
    return True


def _extract_raw_proposal_economic_seeds(raw_text: str, scheme_number: int) -> Dict[str, str]:
    """从 LLM raw 输出抽取经济种子字段（不做公式补齐）。"""
    _, _, response_text = raw_text.partition("--- RAW RESPONSE FROM LLM ---")
    if not response_text:
        return {}

    for json_block in re.findall(r"```json\s*([\s\S]*?)```", response_text, re.DOTALL):
        try:
            data = json.loads(json_block.strip())
        except json.JSONDecodeError:
            continue

        candidates = []
        if isinstance(data, dict):
            scheme_key = f"方案{scheme_number}"
            if isinstance(data.get(scheme_key), dict):
                candidates.append(data[scheme_key])
            candidates.append(data)

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            seeds = _seed_economic_fields_from_mapping(candidate)
            if any(seeds.values()):
                return seeds

    return {}


def _load_raw_proposal_economic_seeds(run_dir: Path, iteration: int, scheme_number: int) -> Dict[str, str]:
    raw_candidates = [
        run_dir / f"test_output_v{iteration}" / "generation" / "llm_raw_output.txt",
        run_dir / "llm_raw_output.txt",
    ]
    raw_path = next((path for path in raw_candidates if path.exists()), None)
    if raw_path is None:
        return {}
    try:
        return _extract_raw_proposal_economic_seeds(
            raw_path.read_text(encoding="utf-8"), scheme_number
        )
    except Exception as exc:
        logger.warning(f"读取方案经济种子失败 {raw_path}: {exc}")
        return {}


def _calculate_lifecycle_cost(construction_cost: Any) -> str:
    """全寿命周期成本 LCC（规划阶段简化估算）= 建设投资 × factor。

    不是完整折现模型；禁止使用年费用作为回退值。
    """
    construction = _parse_economic_number(construction_cost)
    if construction is None:
        return ""
    eco = _get_economic_defaults()
    return _format_economic_number(construction * eco["lifecycle_factor"])


def _economic_fields_from_proposal(proposal: Dict[str, Any]) -> Dict[str, str]:
    """提取并规范化四类独立经济字段（内部单位：元）。

    annual_cost 与 lifecycle_cost 必须独立，禁止互为回退。
    已提供的真实值只用于补缺场景之外的保留；重算值不得覆盖已有字段。
    不做“annual_cost 缺失 ⇒ lifecycle_cost 必为旧年费用”的猜测迁移。
    """
    economics = {
        "construction_cost": _stringify_economic_value(
            _first_present_economic_value(
                proposal.get("construction_cost"),
                proposal.get("construction_cost_estimate"),
                proposal.get("constructionCostEstimate"),
                proposal.get("建造成本估算"),
                proposal.get("建设投资成本"),
                proposal.get("建设投资"),
                proposal.get("建设成本"),
            )
        ),
        "operation_cost": _stringify_economic_value(
            _first_present_economic_value(
                proposal.get("operation_cost"),
                proposal.get("maintenance_cost_estimate"),
                proposal.get("maintenanceCostEstimate"),
                proposal.get("维护成本估算"),
                proposal.get("年运行维护费"),
                proposal.get("运维成本"),
                proposal.get("维护成本"),
            )
        ),
        # 年费用：只认 annual_cost / 年费用，不从 lifecycle_cost 回退
        "annual_cost": _stringify_economic_value(
            _first_present_economic_value(
                proposal.get("annual_cost"),
                proposal.get("yearly_cost"),
                proposal.get("annualCost"),
                proposal.get("年费用"),
            )
        ),
        # 全寿命周期成本：只认 lifecycle_cost / 全寿命*，不从 annual_cost 回退
        "lifecycle_cost": _stringify_economic_value(
            _first_present_economic_value(
                proposal.get("lifecycle_cost"),
                proposal.get("total_lifecycle_cost"),
                proposal.get("lifecycleCost"),
                proposal.get("全寿命周期成本"),
                proposal.get("全生命周期成本"),
                proposal.get("全寿命周期成本LCC"),
            )
        ),
    }
    # 仅补缺：已有真实值一律保留（含数字 0 / 字符串 "0"）
    if not economics["annual_cost"]:
        economics["annual_cost"] = _calculate_annual_cost(
            economics["construction_cost"],
            economics["operation_cost"],
        )
    if not economics["lifecycle_cost"]:
        economics["lifecycle_cost"] = _calculate_lifecycle_cost(
            economics["construction_cost"],
        )
    return economics


def _extract_raw_proposal_economics(raw_text: str, scheme_number: int) -> Dict[str, str]:
    _, _, response_text = raw_text.partition("--- RAW RESPONSE FROM LLM ---")
    if not response_text:
        return {}

    for json_block in re.findall(r"```json\s*([\s\S]*?)```", response_text, re.DOTALL):
        try:
            data = json.loads(json_block.strip())
        except json.JSONDecodeError:
            continue

        candidates = []
        if isinstance(data, dict):
            scheme_key = f"方案{scheme_number}"
            if isinstance(data.get(scheme_key), dict):
                candidates.append(data[scheme_key])
            candidates.append(data)

        for candidate in candidates:
            economics = _economic_fields_from_proposal(candidate)
            if any(economics.values()):
                return economics

    return {}


def _load_raw_proposal_economics(run_dir: Path, iteration: int, scheme_number: int) -> Dict[str, str]:
    raw_candidates = [
        run_dir / f"test_output_v{iteration}" / "generation" / "llm_raw_output.txt",
        run_dir / "llm_raw_output.txt",
    ]
    raw_path = next((path for path in raw_candidates if path.exists()), None)
    if raw_path is None:
        return {}
    try:
        return _extract_raw_proposal_economics(raw_path.read_text(encoding="utf-8"), scheme_number)
    except Exception as exc:
        logger.warning(f"读取方案经济数据失败 {raw_path}: {exc}")
        return {}


def _merge_proposal_economics(proposal: Dict[str, Any], economics: Dict[str, str]) -> None:
    for key, value in economics.items():
        if value and not _stringify_economic_value(proposal.get(key)):
            proposal[key] = value


def _resolve_path_maybe_relative(path_str: str) -> Optional[Path]:
    """绝对路径直接使用；相对路径相对于报告项目目录（APP_DIR）解析。"""
    raw = (path_str or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = APP_DIR / path
    return path


def _read_background_context_file(path: Path) -> str:
    """读取背景资料；失败时返回空字符串，不抛异常。"""
    try:
        if not path.exists() or not path.is_file():
            logger.warning(f"背景资料文件不存在: {path}")
            return ""
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            logger.warning(f"背景资料文件为空: {path}")
            return ""
        return content
    except Exception as exc:
        logger.warning(f"读取背景资料失败（将按无背景资料继续）: {path}: {exc}")
        return ""


def _looks_like_agent_instruction(content: str) -> bool:
    """识别误当作背景资料的方案生成指令（如 shuifu_background_context.md）。"""
    text = (content or "").strip()
    if not text:
        return False
    markers = (
        "你是一个",
        "生成5个可行",
        "每个方案都需要输出对应的JSON",
        "只需输出删除、修改和新增",
        "请严格遵循以下规则",
    )
    hit = sum(1 for m in markers if m in text)
    return hit >= 2


def _looks_like_engineering_background(content: str) -> bool:
    """识别真正的工程接入点/方案论证背景资料。"""
    text = (content or "").strip()
    if not text:
        return False
    markers = (
        "接入点分析",
        "备用",
        "间隔",
        "接入系统方案",
        "π接",
        "曲靖变",
        "龙海变",
        "鲁西",
        "圭山变",
        "罗平变",
    )
    hit = sum(1 for m in markers if m in text)
    return hit >= 3


def _generation_background_candidates(base_input_dir: Path) -> List[Path]:
    generation_dir = base_input_dir / "generation"
    paths: List[Path] = []
    for name in (
        "background_context.md",
        "reference_document.md",
        "user_input.md",
    ):
        path = generation_dir / name
        if path.exists() and path.is_file():
            paths.append(path)
    return paths


def _find_background_context_source(
    base_input_dir: Path,
    explicit_file: str = "",
) -> Optional[Path]:
    """按优先级查找背景资料文件路径。

    1. 请求 / 任务中的 backgroundContextFile
    2. 环境变量 REPORT_BACKGROUND_CONTEXT_FILE
    3. inputDir/generation/background_context.md
    4. inputDir/generation/reference_document.md
    5. inputDir/generation/user_input.md

    若高优先级文件实际是方案生成指令而非工程背景，且 inputDir 下存在真正的
    background_context.md，则自动回退并打警告。
    """
    candidates: List[str] = []
    if explicit_file and str(explicit_file).strip():
        candidates.append(str(explicit_file).strip())
    env_file = (_env_value("REPORT_BACKGROUND_CONTEXT_FILE") or "").strip()
    if env_file and env_file not in candidates:
        candidates.append(env_file)

    selected: Optional[Path] = None
    for raw in candidates:
        path = _resolve_path_maybe_relative(raw)
        if path is None:
            continue
        if path.exists() and path.is_file():
            selected = path
            break
        logger.warning(f"指定的背景资料文件不存在: {path}")

    if selected is None:
        local_candidates = _generation_background_candidates(base_input_dir)
        return local_candidates[0] if local_candidates else None

    content = _read_background_context_file(selected)
    if content and not _looks_like_agent_instruction(content):
        return selected

    # 误配了方案生成指令时，优先回退到 generation/background_context.md
    for fallback in _generation_background_candidates(base_input_dir):
        if fallback.resolve() == selected.resolve():
            continue
        fallback_content = _read_background_context_file(fallback)
        if _looks_like_engineering_background(fallback_content):
            logger.warning(
                f"指定背景资料疑似方案生成指令而非工程背景: {selected}；"
                f"已自动回退到: {fallback}"
            )
            return fallback

    if content and _looks_like_agent_instruction(content):
        logger.warning(
            f"背景资料疑似方案生成指令，且未找到可用工程背景文件，仍使用: {selected}"
        )
    return selected


def _copy_background_context_to_demo_input(
    base_input_dir: Path,
    demo_input_dir: Path,
    explicit_file: str = "",
) -> str:
    """复制背景资料到 demo_input/generation/background_context.md，返回文本内容。"""
    src = _find_background_context_source(base_input_dir, explicit_file=explicit_file)
    dst = demo_input_dir / "generation" / "background_context.md"
    dst.parent.mkdir(parents=True, exist_ok=True)

    if src is None:
        logger.info("未找到背景资料文件，前置工程分析将按输入不足处理")
        return ""

    content = _read_background_context_file(src)
    if not content:
        logger.info("未找到背景资料文件，前置工程分析将按输入不足处理")
        return ""

    if _looks_like_agent_instruction(content) and not _looks_like_engineering_background(
        content
    ):
        logger.warning(
            f"最终选用的背景资料仍疑似方案生成指令（非工程接入点分析）: {src}；"
            "周边500kV电网接入点分析可能无法完整生成"
        )

    try:
        dst.write_text(content, encoding="utf-8")
        logger.info("背景资料已复制到 demo_input/generation/background_context.md")
        logger.info(f"背景资料来源: {src}")
        logger.info(f"背景资料长度: {len(content)} 字符")
    except Exception as exc:
        logger.warning(f"写入背景资料到 demo_input 失败（将按无背景资料继续）: {exc}")
        return ""
    return content


def _infer_connection_type(modifications: List[Any]) -> str:
    """仅依据 modifications 中可观测的动作推断接线类型，无法判断时明确说明。"""
    actions = []
    for item in modifications:
        if isinstance(item, dict) and item.get("action"):
            actions.append(str(item.get("action")))
    has_disable = any(a == "disable_branch" for a in actions)
    has_add_line = any(a == "add_line" for a in actions)
    has_add_bus = any(a == "add_bus" for a in actions)
    if has_disable and has_add_line:
        return "π接或开断改接（存在 disable_branch + add_line）"
    if has_add_line and has_add_bus and not has_disable:
        return "新建线路加强通道（存在 add_bus + add_line，无 disable_branch）"
    if has_add_line and not has_disable:
        return "新建线路接入（存在 add_line）"
    return "接线类型未明确"


def _build_proposal_description(run_dir: Path, iteration: int, scheme_number: int, proposal: Dict[str, Any]) -> str:
    modifications = proposal.get("modifications", []) if isinstance(proposal, dict) else []
    if not isinstance(modifications, list):
        modifications = []

    added_buses: List[str] = []
    disabled_lines: List[str] = []
    added_lines: List[str] = []

    for item in modifications:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "")
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        if action == "add_bus":
            bus = params.get("full_bus_data") if isinstance(params.get("full_bus_data"), dict) else {}
            name = str(bus.get("NAME", "")).strip()
            if name and name not in added_buses:
                added_buses.append(name)
        elif action == "disable_branch":
            branch = (
                params.get("full_branch_data")
                if isinstance(params.get("full_branch_data"), dict)
                else {}
            )
            name1 = str(branch.get("NAME1", "")).strip()
            name2 = str(branch.get("NAME2", "")).strip()
            ckt = str(branch.get("CKT ID", "")).strip() or "?"
            if name1 or name2:
                disabled_lines.append(f"{name1}-{name2}(CKT={ckt})")
        elif action == "add_line":
            branch = (
                params.get("full_branch_data")
                if isinstance(params.get("full_branch_data"), dict)
                else {}
            )
            name1 = str(branch.get("NAME1", "")).strip()
            name2 = str(branch.get("NAME2", "")).strip()
            ckt = str(branch.get("CKT ID", "")).strip() or "?"
            miles = branch.get("MILES", None)
            line_name = str(branch.get("LINE NAME", "")).strip()
            length_part = ""
            if miles is not None and str(miles).strip() != "":
                length_part = f"，长度={miles} mile"
            label = f"{name1}-{name2}(CKT={ckt}{length_part})"
            if line_name:
                label = f"{line_name}:{label}"
            added_lines.append(label)

    parts = [
        f"来源 {run_dir.name}",
        f"第 {iteration} 轮最终选中",
        f"原候选方案号 {scheme_number}",
        f"共 {len(modifications)} 项改动",
        f"接线类型：{_infer_connection_type(modifications)}",
    ]
    if added_buses:
        parts.append("新增节点：" + "、".join(added_buses))
    if disabled_lines:
        parts.append("删除/开断线路：" + "；".join(disabled_lines))
    if added_lines:
        parts.append("新建线路：" + "；".join(added_lines))

    summary = "，".join(parts)

    economics = _economic_fields_from_proposal(proposal)
    eco = _get_economic_defaults()
    economic_parts = []
    if economics.get("construction_cost"):
        economic_parts.append(f"建设投资：{economics['construction_cost']}元")
    if economics.get("operation_cost"):
        economic_parts.append(f"年运行维护费：{economics['operation_cost']}元/年")
    if economics.get("annual_cost"):
        economic_parts.append(
            f"年费用：{economics['annual_cost']}元/年"
            f"（按n={int(eco['years']) if float(eco['years']).is_integer() else eco['years']}、"
            f"i={eco['interest_rate']:.0%}、"
            "年费用=建设投资×资本回收系数+年运行维护费计算）"
        )
    if economics.get("lifecycle_cost"):
        economic_parts.append(
            f"全寿命周期成本LCC：{economics['lifecycle_cost']}元"
            f"（若由简化公式补齐则为建设投资×{eco['lifecycle_factor']}，非完整折现模型；"
            "已提供真实值时保留原值）"
        )
    if economic_parts:
        summary += "；" + "；".join(economic_parts)
    return summary


def _prepare_demo_input_dir(
    base_input_dir: Path,
    run_output_dir: Path,
    background_context_file: str = "",
) -> Path:
    """将 fulfillment_scc/run_* 聚合为报告工作流可消费的标准输入目录。"""
    demo_input_dir = run_output_dir / "demo_input"
    demo_input_dir.mkdir(parents=True, exist_ok=True)

    copied_files = []
    missing_files = []

    if not base_input_dir.exists() or not base_input_dir.is_dir():
        raise FileNotFoundError(f"比选输入目录不存在: {base_input_dir}")

    aggregated_proposals: List[Dict[str, Any]] = []
    valid_run_count = 0

    for run_dir in _list_run_dirs(base_input_dir):
        selected = _select_final_proposal_file(run_dir)
        if not selected:
            continue

        _, proposal_data = selected
        iteration = int(proposal_data["iteration"])
        scheme_number = int(proposal_data["scheme_number"])
        report_files = _resolve_final_analysis_files(run_dir, iteration, scheme_number)
        analysis_dir = report_files["analysis_dir"]

        if not analysis_dir.exists() or not analysis_dir.is_dir():
            logger.warning(f"跳过 {run_dir.name}: 未找到最终分析目录 {analysis_dir}")
            continue

        aggregated_index = valid_run_count + 1
        proposal = dict(proposal_data["proposal"])
        # 先写入原始经济种子（不做公式补齐），再做旧版误写迁移，最后统一补缺。
        seeds = _seed_economic_fields_from_mapping(proposal)
        if not any(seeds.values()):
            seeds = _load_raw_proposal_economic_seeds(run_dir, iteration, scheme_number)
        _merge_proposal_economics(proposal, seeds)
        _migrate_legacy_run_economics(proposal, run_label=str(run_dir))
        economics = _economic_fields_from_proposal(proposal)
        for key in ("construction_cost", "operation_cost", "annual_cost", "lifecycle_cost"):
            if economics.get(key):
                proposal[key] = economics[key]
        proposal["proposal_name"] = f"方案{aggregated_index}"
        if not str(proposal.get("description", "")).strip():
            proposal["description"] = _build_proposal_description(run_dir, iteration, scheme_number, proposal)
        aggregated_proposals.append(proposal)

        analysis_dst_dir = demo_input_dir / f"analysis_{aggregated_index}"
        _copy_if_exists(
            report_files["pf"],
            analysis_dst_dir / f"pf_report_{aggregated_index}.json",
            copied_files,
            missing_files,
            demo_input_dir,
        )
        _copy_if_exists(
            report_files["n1"],
            analysis_dst_dir / f"n1_report_{aggregated_index}.json",
            copied_files,
            missing_files,
            demo_input_dir,
        )
        _copy_if_exists(
            report_files["scc"],
            analysis_dst_dir / f"scc_report_{aggregated_index}.json",
            copied_files,
            missing_files,
            demo_input_dir,
        )
        valid_run_count += 1

    if not aggregated_proposals:
        raise FileNotFoundError(f"未在 {base_input_dir} 下找到可用于比选报告的有效 run 输出")

    generation_dst = demo_input_dir / "generation" / "parsed_proposals.json"
    generation_dst.parent.mkdir(parents=True, exist_ok=True)
    with open(generation_dst, "w", encoding="utf-8") as f:
        json.dump({"proposals": aggregated_proposals}, f, ensure_ascii=False, indent=2)
    copied_files.append(str(generation_dst.relative_to(demo_input_dir)))

    background_text = _copy_background_context_to_demo_input(
        base_input_dir,
        demo_input_dir,
        explicit_file=background_context_file,
    )
    if background_text:
        copied_files.append("generation/background_context.md")

    logger.info(f"第5步输入目录准备完成: {demo_input_dir}")
    logger.info(f"聚合有效 run 数量: {valid_run_count}")
    logger.info(f"复制有效输入文件 {len(copied_files)} 个")
    if missing_files:
        logger.warning(f"缺失输入文件 {len(missing_files)} 个: {missing_files}")

    return demo_input_dir


async def _run_phase_1(report_id: str) -> None:
    try:
        if not READY:
            await _set_task_stage(report_id, "DATA_PREPROCESSING", "正在初始化报告模型客户端。")
            await asyncio.to_thread(_init_clients_once)
    except Exception as exc:
        logger.exception("模型客户端初始化失败")
        await _mark_task_failed(report_id, f"模型客户端初始化失败: {exc}")
        return

    await _set_task_stage(report_id, "DATA_PREPROCESSING", "开始执行数据预处理。")

    async with TASKS_LOCK:
        task = TASKS.get(report_id)
        if not task:
            return
        run_output_dir = generate_timestamped_output_directory(
            task.output_dir, suffix="compare_pcn"
        )
        task.run_output_dir = run_output_dir
        task.result_file = run_output_dir / "result.json"
        _setup_task_logger(task)
        logger.info(f"第5步输出目录: {run_output_dir}")
        logger.info(f"第5步日志文件: {task.log_file}")

        demo_input_dir = _prepare_demo_input_dir(
            task.input_dir,
            run_output_dir,
            background_context_file=task.background_context_file,
        )

        bg_path = demo_input_dir / "generation" / "background_context.md"
        background_context = ""
        background_context_source = ""
        if bg_path.exists():
            try:
                background_context = bg_path.read_text(encoding="utf-8").strip()
                if background_context:
                    background_context_source = "generation/background_context.md"
                    task.background_context = background_context
            except Exception as exc:
                logger.warning(f"读取 demo_input 背景资料失败: {exc}")

        initial_state = State(
            input_dir=demo_input_dir,
            output_dir=run_output_dir,
            working_dir=run_output_dir / "working_dir",
            report_dir=run_output_dir / "report",
            debug=True,
            background_context=background_context,
            background_context_source=background_context_source,
        )
        task.state_data = dict(initial_state.__dict__)

    try:
        async with TASKS_LOCK:
            task = TASKS.get(report_id)
            if not task:
                return
            state = State(**task.state_data)

        preprocess_updates = await _run_node_in_thread(data_preprocessing_pcn, state)
        state_data = dict(state.__dict__)
        state_data.update(preprocess_updates)

        await _set_task_stage(report_id, "INSIGHTS_GENERATION", "开始执行洞察生成。")
        insights_state = State(**state_data)
        insights_updates = await _run_node_in_thread(
            insights_generation_node, insights_state
        )
        state_data.update(insights_updates)

        async with TASKS_LOCK:
            task = TASKS.get(report_id)
            if not task:
                return
            task.state_data = state_data
            task.insights_draft = str(state_data.get("insights") or "")
            task.stage = "WAIT_INSIGHTS_CONFIRM"
            task.message = "洞察已生成，请确认或编辑后继续。"

        await _persist_task_result(report_id)

    except Exception as exc:
        logger.exception("洞察阶段执行失败")
        await _mark_task_failed(report_id, f"洞察阶段执行失败: {exc}")


async def _run_phase_2(report_id: str) -> None:
    try:
        await _set_task_stage(report_id, "RETRIEVE_CLAIMS", "开始检索洞察关联依据。")

        async with TASKS_LOCK:
            task = TASKS.get(report_id)
            if not task:
                return
            # 后续流程必须使用人工确认后的洞察文本
            task.state_data["insights"] = task.insights_confirmed
            task.state_data["first_insights"] = task.insights_draft
            state = State(**task.state_data)

        retrieved_updates = await _run_node_in_thread(retrieve_claims_for_insights, state)
        state_data = dict(state.__dict__)
        state_data.update(retrieved_updates)

        await _set_task_stage(report_id, "GENERATE_REPORT", "开始生成报告。")
        report_updates = await _run_node_in_thread(generate_report, State(**state_data))
        state_data.update(report_updates)

        await _set_task_stage(report_id, "VERIFY_CLAIMS", "开始校验 PCN 依据。")
        verify_updates = await _run_node_in_thread(
            verify_pcn_claims, State(**state_data)
        )
        state_data.update(verify_updates)

        async with TASKS_LOCK:
            task = TASKS.get(report_id)
            if not task:
                return
            task.state_data = state_data

            report_dir = Path(str(task.state_data.get("report_dir")))
            report_dir.mkdir(parents=True, exist_ok=True)
            md_path = report_dir / "report.md"

            # 生成初稿阶段不再自动 convert，因此在这里显式落盘 report.md
            draft_md = (
                task.state_data.get("md_report")
                or task.state_data.get("raw_report")
                or ""
            )
            md_path.write_text(str(draft_md), encoding="utf-8")

            passed = bool(task.state_data.get("pcn_verification_passed"))
            verify_stats = task.state_data.get("pcn_verification_result") or {}

            from src.nodes.verify_pcn_claims import (
                compute_pcn_verification_passed,
                format_pcn_pass_message,
                format_pcn_review_message,
            )

            pcn_needs_review = not compute_pcn_verification_passed(verify_stats)
            quality_stats = task.state_data.get("report_quality_result") or {}
            quality_needs_review = bool(quality_stats) and not bool(
                quality_stats.get("structure_passed")
            )
            needs_review = pcn_needs_review or quality_needs_review

            task.ready = True
            task.report_paths = {
                "md": _to_rel_path(md_path),
            }
            if not needs_review:
                task.stage = "DRAFT_READY"
                task.message = format_pcn_pass_message(verify_stats)
            else:
                task.stage = "DRAFT_REVIEW_REQUIRED"
                messages = []
                if pcn_needs_review:
                    messages.append(format_pcn_review_message(verify_stats))
                if quality_needs_review:
                    messages.append(format_report_quality_review_message(quality_stats))
                task.message = " ".join(messages)

        await _persist_task_result(report_id)

    except Exception as exc:
        logger.exception("确认后阶段执行失败")
        await _mark_task_failed(report_id, f"确认后阶段执行失败: {exc}")


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"ok": READY, "error": READY_ERROR}


@app.post("/api/compare-reports")
async def create_compare_report(req: CompareReportCreateRequest) -> Dict[str, Any]:
    report_id = f"compare_{uuid.uuid4().hex[:12]}"
    background_context_file = (req.backgroundContextFile or "").strip()
    if not background_context_file:
        background_context_file = (_env_value("REPORT_BACKGROUND_CONTEXT_FILE") or "").strip()

    task = CompareReportTask(
        report_id=report_id,
        source_task_id=req.taskId,
        input_dir=(Path(req.inputDir) if Path(req.inputDir).is_absolute() else (APP_DIR / req.inputDir)),
        output_dir=(Path(req.outputDir) if Path(req.outputDir).is_absolute() else (APP_DIR / req.outputDir)),
        stage="DATA_PREPROCESSING",
        message="任务已创建。",
        background_context_file=background_context_file,
    )

    async with TASKS_LOCK:
        TASKS[report_id] = task

    asyncio.create_task(_run_phase_1(report_id))

    return {
        "reportId": report_id,
        "stage": task.stage,
        "message": task.message,
    }


@app.get("/api/compare-reports/{report_id}")
async def get_compare_report_status(report_id: str) -> Dict[str, Any]:
    async with TASKS_LOCK:
        task = TASKS.get(report_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"比选任务不存在: {report_id}")

        report_path = task.report_paths.get("md", "")
        current_insights = task.insights_draft if task.stage == "WAIT_INSIGHTS_CONFIRM" else ""

        return {
            "reportId": task.report_id,
            "taskId": task.source_task_id,
            "stage": task.stage,
            "failed": task.failed,
            "ready": task.ready,
            "message": task.message,
            "currentInsights": current_insights,
            "reportPath": report_path,
            "reportPaths": task.report_paths,
            "pcnVerificationPassed": task.state_data.get("pcn_verification_passed"),
            "pcnVerificationResult": task.state_data.get("pcn_verification_result"),
            "reportQualityResult": task.state_data.get("report_quality_result"),
        }


@app.get("/api/compare-reports/{report_id}/insights")
async def get_compare_report_insights(report_id: str) -> Dict[str, Any]:
    async with TASKS_LOCK:
        task = TASKS.get(report_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"比选任务不存在: {report_id}")
        if task.stage not in {
            "WAIT_INSIGHTS_CONFIRM",
            "RETRIEVE_CLAIMS",
            "GENERATE_REPORT",
            "VERIFY_CLAIMS",
            "DRAFT_READY",
            "DRAFT_REVIEW_REQUIRED",
        }:
            raise HTTPException(status_code=409, detail="当前阶段尚无可确认洞察")

        return {
            "reportId": task.report_id,
            "stage": task.stage,
            "insights": task.insights_draft,
            "confirmedInsights": task.insights_confirmed,
        }


@app.post("/api/compare-reports/{report_id}/insights/confirm")
async def confirm_compare_report_insights(
    report_id: str, req: CompareReportConfirmInsightsRequest
) -> Dict[str, Any]:
    async with TASKS_LOCK:
        task = TASKS.get(report_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"比选任务不存在: {report_id}")
        if task.stage != "WAIT_INSIGHTS_CONFIRM":
            raise HTTPException(status_code=409, detail=f"当前阶段不允许确认洞察: {task.stage}")

        text = (req.insights or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="洞察内容不能为空")

        task.insights_confirmed = text
        task.stage = "RETRIEVE_CLAIMS"
        task.message = "已确认洞察，继续执行后续步骤。"

    asyncio.create_task(_run_phase_2(report_id))

    return {
        "reportId": report_id,
        "stage": "RETRIEVE_CLAIMS",
        "message": "已接收洞察确认，后续流程开始执行。",
    }


@app.post("/api/reports/save-md")
async def save_report_markdown(req: SaveReportRequest) -> Dict[str, Any]:
    original_md_path = _resolve_report_md_path(req.reportId, req.reportPath)
    user_md_path = _build_user_edit_md_path(original_md_path)
    cleaned_md = strip_markdown_fence_noise(req.contentMd or "")
    user_md_path.parent.mkdir(parents=True, exist_ok=True)
    user_md_path.write_text(cleaned_md, encoding="utf-8")
    version_path = _save_report_version_snapshot(user_md_path, cleaned_md, req.reason)

    # 尝试同步任务状态里的草稿文本，便于后续 result.json 对齐
    if req.reportId:
        async with TASKS_LOCK:
            task = TASKS.get(req.reportId)
            if task is not None:
                task.state_data["md_report"] = cleaned_md
        await _persist_task_result(req.reportId)

    return {
        "ok": True,
        "savedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "reportPath": _to_rel_path(user_md_path),
        "originalReportPath": _to_rel_path(original_md_path),
        "version": {
            "id": version_path.name,
            "reason": _version_reason_from_name(version_path),
            "path": _to_rel_path(version_path),
        },
    }


@app.post("/api/reports/read-md")
async def read_report_markdown(req: ReadReportRequest) -> Dict[str, Any]:
    original_md_path = _resolve_report_md_path(req.reportId, req.reportPath)
    user_md_path = _build_user_edit_md_path(original_md_path)

    target = user_md_path if user_md_path.exists() and user_md_path.is_file() else original_md_path
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"report.md 不存在: {_to_rel_path(target)}")

    raw_content = target.read_text(encoding="utf-8")
    cleaned_content = strip_markdown_fence_noise(raw_content)

    if target == user_md_path and cleaned_content != raw_content:
        user_md_path.write_text(cleaned_content, encoding="utf-8")

    return {
        "ok": True,
        "reportPath": _to_rel_path(target),
        "originalReportPath": _to_rel_path(original_md_path),
        "contentMd": cleaned_content,
    }


@app.post("/api/reports/reset-md")
async def reset_report_markdown(req: ResetReportRequest) -> Dict[str, Any]:
    original_md_path = _resolve_report_md_path(req.reportId, req.reportPath)
    if not original_md_path.exists() or not original_md_path.is_file():
        raise HTTPException(status_code=404, detail=f"原始 report.md 不存在: {_to_rel_path(original_md_path)}")

    user_md_path = _build_user_edit_md_path(original_md_path)
    original_content = original_md_path.read_text(encoding="utf-8")
    cleaned_content = strip_markdown_fence_noise(original_content)
    user_md_path.parent.mkdir(parents=True, exist_ok=True)
    user_md_path.write_text(cleaned_content, encoding="utf-8")

    if req.reportId:
        async with TASKS_LOCK:
            task = TASKS.get(req.reportId)
            if task is not None:
                task.state_data["md_report"] = cleaned_content
        await _persist_task_result(req.reportId)

    return {
        "ok": True,
        "reportPath": _to_rel_path(user_md_path),
        "originalReportPath": _to_rel_path(original_md_path),
        "contentMd": cleaned_content,
        "savedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/reports/versions")
async def list_report_versions(reportPath: str, reportId: str = "") -> Dict[str, Any]:
    original_md_path = _resolve_report_md_path(reportId, reportPath)
    user_md_path = _build_user_edit_md_path(original_md_path)
    return {
        "ok": True,
        "reportPath": _to_rel_path(user_md_path),
        "originalReportPath": _to_rel_path(original_md_path),
        "versions": _list_report_versions(user_md_path),
    }


@app.post("/api/reports/versions/read")
async def read_report_version(req: ReadReportVersionRequest) -> Dict[str, Any]:
    original_md_path = _resolve_report_md_path(req.reportId, req.reportPath)
    user_md_path = _build_user_edit_md_path(original_md_path)
    content = _read_report_version(user_md_path, req.versionId)
    return {
        "ok": True,
        "versionId": req.versionId,
        "contentMd": strip_markdown_fence_noise(content),
    }


@app.post("/api/reports/versions/rollback")
async def rollback_report_version(req: ReadReportVersionRequest) -> Dict[str, Any]:
    original_md_path = _resolve_report_md_path(req.reportId, req.reportPath)
    user_md_path = _build_user_edit_md_path(original_md_path)
    content = strip_markdown_fence_noise(_restore_report_version(user_md_path, req.versionId))

    if req.reportId:
        async with TASKS_LOCK:
            task = TASKS.get(req.reportId)
            if task is not None:
                task.state_data["md_report"] = content
        await _persist_task_result(req.reportId)

    return {
        "ok": True,
        "versionId": req.versionId,
        "reportPath": _to_rel_path(user_md_path),
        "originalReportPath": _to_rel_path(original_md_path),
        "contentMd": content,
        "savedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }


@app.post("/api/reports/versions/delete")
async def delete_report_version(req: ReadReportVersionRequest) -> Dict[str, Any]:
    original_md_path = _resolve_report_md_path(req.reportId, req.reportPath)
    user_md_path = _build_user_edit_md_path(original_md_path)
    deleted_path = _delete_report_version(user_md_path, req.versionId)
    return {
        "ok": True,
        "versionId": req.versionId,
        "deletedPath": _to_rel_path(deleted_path),
        "reportPath": _to_rel_path(user_md_path),
        "originalReportPath": _to_rel_path(original_md_path),
    }


@app.post("/api/reports/rewrite")
async def rewrite_report_selection(req: RewriteRequest) -> Dict[str, Any]:
    instruction = (req.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction 不能为空")
    if len(instruction) > 1200:
        raise HTTPException(status_code=400, detail="instruction 过长，最多 1200 字符")

    original_md_path = _resolve_report_md_path(req.reportId, req.reportPath)
    user_md_path = _build_user_edit_md_path(original_md_path)
    target_path = user_md_path if user_md_path.exists() and user_md_path.is_file() else original_md_path

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail=f"report.md 不存在: {_to_rel_path(target_path)}")

    full_content = strip_markdown_fence_noise(target_path.read_text(encoding="utf-8"))
    start = req.selection.start
    end = req.selection.end

    if start < 0 or end <= start:
        raise HTTPException(status_code=400, detail="selection 范围无效")
    if end > len(full_content):
        raise HTTPException(status_code=400, detail="selection 超出报告内容范围")

    selected = full_content[start:end]
    if len(selected) > 4000:
        raise HTTPException(status_code=400, detail="选中内容过长，最多 4000 字符")

    expected_text = req.selection.text or ""
    if expected_text and expected_text != selected:
        raise HTTPException(status_code=409, detail="选中内容已变化，请重新选中后重试")

    context_window = 600
    left_context = full_content[max(0, start - context_window):start]
    right_context = full_content[end:min(len(full_content), end + context_window)]

    try:
        result = await asyncio.to_thread(
            rewrite_selected_segment,
            selected,
            instruction,
            left_context,
            right_context,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"改写失败: {exc}")

    return {
        "ok": True,
        "rewrittenText": result.rewritten_text,
        "notes": result.notes,
        "selection": {
            "start": start,
            "end": end,
            "text": selected,
        },
        "verification": None,
    }


@app.post("/api/reports/convert")
async def convert_report_from_editor(req: ConvertReportRequest) -> Dict[str, Any]:
    fmt = (req.format or "").lower().strip()
    if fmt not in {"pdf", "docx"}:
        raise HTTPException(status_code=400, detail="format 仅支持 pdf 或 docx")

    original_md_path = _resolve_report_md_path(req.reportId, req.reportPath)
    user_md_path = _build_user_edit_md_path(original_md_path)
    report_dir = original_md_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    # 保留后端生成的原始 report.md，仅将用户编辑内容保存到副本
    md_content = strip_markdown_fence_noise(req.contentMd or "")
    user_md_path.write_text(md_content, encoding="utf-8")

    convert_state = State(
        report_dir=report_dir,
        md_report=md_content,
    )
    updates = await _run_node_in_thread(convert_report, convert_state)

    if fmt == "pdf":
        target = Path(str(updates.get("pdf_report_path", _latest_report_export_path(report_dir, "pdf")))).resolve()
        success = bool(updates.get("pdf_success"))
        error_text = str(updates.get("pdf_error") or "")
    else:
        target = Path(str(updates.get("docx_report_path", _latest_report_export_path(report_dir, "docx")))).resolve()
        success = bool(updates.get("docx_success"))
        error_text = str(updates.get("docx_error") or "")

    if not success:
        detail = f"{fmt.upper()} 导出失败"
        if error_text:
            detail = f"{detail}：{error_text}"
        raise HTTPException(status_code=500, detail=detail)

    if not target.exists():
        raise HTTPException(status_code=500, detail=f"{fmt.upper()} 导出失败，未生成目标文件")

    return {
        "ok": True,
        "format": fmt,
        "success": success,
        "error": error_text,
        "downloadUrl": _build_download_url(target),
        "filePath": _to_rel_path(target),
        "reportPath": _to_rel_path(user_md_path),
        "originalReportPath": _to_rel_path(original_md_path),
        "fileName": target.name,
    }


@app.get("/api/reports/download")
async def download_report_file(path: str) -> FileResponse:
    raw = Path(path)
    resolved = (raw if raw.is_absolute() else (APP_DIR / raw)).resolve()
    outputs_root = (APP_DIR / "outputs").resolve()
    if outputs_root not in resolved.parents and resolved != outputs_root:
        raise HTTPException(status_code=400, detail="仅允许下载 outputs 目录中的文件")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="目标文件不存在")

    media_type = None
    suffix = resolved.suffix.lower()
    if suffix == ".pdf":
        media_type = "application/pdf"
    elif suffix == ".docx":
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return FileResponse(str(resolved), media_type=media_type, filename=resolved.name)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main_api:app", host="0.0.0.0", port=8081, reload=False)
