# -*- coding: utf-8 -*-
"""第二批比选指标：字段别名集中管理 + 从 PF/N-1/方案 JSON 提取。

原则：缺字段≠空列表；问题子集不得冒充全网比例/最大值；0 为合法值。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

# ---------------------------------------------------------------------------
# 集中字段别名（禁止在业务函数中散落复制）
# ---------------------------------------------------------------------------

FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "voltage": ("voltage_pu", "voltage", "标幺电压(pu)", "V", "V_pu"),
    "voltage_min": ("min_voltage", "voltage_min", "Vmin", "vmin", "电压下限"),
    "voltage_max": ("max_voltage", "voltage_max", "Vmax", "vmax", "电压上限"),
    "node_id": ("node_id", "bus_name", "bus_id", "节点", "NAME"),
    "period": ("period", "time", "hour", "时段", "time_index"),
    "loss_mw": ("loss_mw", "active_power_loss_mw", "损耗_MW", "P_loss", "network_loss_mw"),
    "input_power_mw": (
        "input_power_mw",
        "input_active_power_mw",
        "总发电_MW",
        "P_in",
        "region_input_mw",
    ),
    "section_limit": ("limit", "limit_mw", "security_limit", "断面限额", "P_limit"),
    "section_flow": ("flow", "flow_mw", "actual_flow", "实际输送功率", "P_flow"),
    "card_type": ("卡片类型", "card_type", "equipment_type", "type"),
    "length": ("length_km", "length", "MILES", "miles", "长度", "长度_km"),
    "equivalent_hours": (
        "equivalent_hours",
        "equivalent_loss_hours",
        "年等效网损小时数",
        "loss_hours",
    ),
    "price_per_mwh": (
        "price_per_mwh",
        "loss_energy_price",
        "网损电价",
        "energy_price",
    ),
}

RETROFIT_ACTIONS = frozenset(
    {
        "retrofit_line",
        "upgrade_line",
        "replace_conductor",
        "reconductor",
        "relocate_line",
        "改造线路",
        "增容",
        "更换导线",
        "改接",
        "迁改",
    }
)


def _first_key(data: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def get_aliased(data: Optional[Dict[str, Any]], alias_group: str) -> Any:
    if not isinstance(data, dict):
        return None
    return _first_key(data, *FIELD_ALIASES.get(alias_group, ()))


def _finite_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _coverage(
    *,
    scope: str,
    valid_count: int = 0,
    skipped_count: int = 0,
    denominator_source: Optional[str] = None,
    notes: str = "",
) -> Dict[str, Any]:
    return {
        "scope": scope,  # full_set | issue_subset | scheme_summary | proposal_modifications | missing
        "valid_count": valid_count,
        "skipped_count": skipped_count,
        "denominator_source": denominator_source,
        "notes": notes,
    }


def _missing_result(
    missing_fields: List[str],
    input_source: str,
    *,
    coverage: Optional[Dict[str, Any]] = None,
    notes: str = "",
) -> Dict[str, Any]:
    return {
        "value": None,
        "status": "missing_data",
        "missing_fields": missing_fields,
        "input_source": input_source,
        "inputs": {},
        "provenance": "missing",
        "calculation_mode": "missing",
        "coverage": coverage
        or _coverage(scope="missing", notes=notes or "源数据不足"),
    }


def _ok_result(
    value: float,
    *,
    inputs: Dict[str, Any],
    input_source: str,
    provenance: str = "calculated",
    calculation_mode: str = "formula",
    coverage: Optional[Dict[str, Any]] = None,
    unit: Optional[str] = None,
) -> Dict[str, Any]:
    result = {
        "value": value,
        "status": "ok",
        "missing_fields": [],
        "input_source": input_source,
        "inputs": inputs,
        "provenance": provenance,
        "calculation_mode": calculation_mode,
        "coverage": coverage or _coverage(scope="full_set"),
    }
    if unit is not None:
        result["unit"] = unit
    return result


def _invalid_result(
    invalid_fields: List[str],
    input_source: str,
    *,
    coverage: Optional[Dict[str, Any]] = None,
    notes: str = "",
    inputs: Optional[Dict[str, Any]] = None,
    unit: Optional[str] = None,
) -> Dict[str, Any]:
    result = {
        "value": None,
        "status": "invalid_data",
        "missing_fields": [],
        "invalid_fields": invalid_fields,
        "input_source": input_source,
        "inputs": inputs or {},
        "provenance": "invalid",
        "calculation_mode": "invalid",
        "coverage": coverage
        or _coverage(scope="missing", notes=notes or "输入无效"),
    }
    if unit is not None:
        result["unit"] = unit
    return result


def _first_present(*values: Any) -> Any:
    """取第一个有效值；保留数字 0 / 0.0 / \"0\"，跳过 None 与空白字符串。"""
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _scheme_level_raw(
    data: Dict[str, Any], *keys: str
) -> Tuple[Any, Optional[str]]:
    """返回第一个存在键的原始值（含 0）；键均不存在时返回 (None, None)。"""
    if not isinstance(data, dict):
        return None, None
    for key in keys:
        if key in data:
            return data.get(key), key
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    for key in keys:
        if key in analysis:
            return analysis.get(key), key
    return None, None


def _validate_direct_metric(
    metric_name: str,
    raw_value: Any,
    source: str,
    *,
    field_name: str,
) -> Dict[str, Any]:
    """方案级直接值必须经 Calculator 校验；非法值不截断、不静默接受。"""
    from src.tools.grid_calculator import calculate_grid_metric

    if raw_value is None:
        return _missing_result(
            [field_name],
            source,
            notes=f"{field_name} 为 null",
            coverage=_coverage(
                scope="scheme_summary",
                notes=f"直接值缺失: {field_name}=null",
            ),
        )
    if isinstance(raw_value, bool):
        return {
            "value": None,
            "status": "invalid_data",
            "missing_fields": [],
            "invalid_fields": [field_name],
            "input_source": source,
            "inputs": {field_name: raw_value},
            "provenance": "invalid",
            "calculation_mode": "direct",
            "coverage": _coverage(
                scope="scheme_summary",
                notes=f"直接值非法(bool): {field_name}={raw_value!r}",
            ),
        }
    try:
        result = calculate_grid_metric(metric_name, {metric_name: raw_value})
        return _ok_result(
            float(result["value"]),
            inputs={metric_name: raw_value},
            input_source=source,
            provenance="provided",
            calculation_mode="direct",
            coverage=_coverage(scope="scheme_summary", valid_count=1),
        )
    except (TypeError, ValueError) as exc:
        return {
            "value": None,
            "status": "invalid_data",
            "missing_fields": [],
            "invalid_fields": [field_name],
            "input_source": source,
            "inputs": {field_name: raw_value},
            "provenance": "invalid",
            "calculation_mode": "direct",
            "coverage": _coverage(
                scope="scheme_summary",
                notes=f"直接值未通过Calculator校验: {exc}",
            ),
        }


def _get_list_field(container: Dict[str, Any], *keys: str) -> Tuple[Optional[List[Any]], Optional[str]]:
    """区分缺失 / null / 非列表 / 明确列表。"""
    for key in keys:
        if key not in container:
            continue
        raw = container[key]
        if raw is None:
            return None, key
        if not isinstance(raw, list):
            return None, key
        return raw, key
    return None, None


def classify_equipment_record(record: Dict[str, Any]) -> str:
    """按卡片类型区分线路/主变；无法识别返回 unknown。"""
    card = str(get_aliased(record, "card_type") or "").strip().upper()
    if card in {"L", "LINE", "线路"}:
        return "line"
    if card in {"T", "TRANSFORMER", "主变", "变压器", "X"}:
        return "transformer"
    if record.get("额定容量(MVA)") is not None or record.get("rated_capacity") is not None:
        if record.get("电流(A)") is None and record.get("额定电流(A)") is None:
            return "transformer"
    if record.get("额定电流(A)") is not None or record.get("allowed_current") is not None:
        return "line"
    return "unknown"



def _scheme_level_float(data: Dict[str, Any], *keys: str) -> Optional[float]:
    """读取方案级有限浮点；键缺失返回 None。零值保留。"""
    raw, field = _scheme_level_raw(data, *keys)
    if field is None:
        return None
    return _finite_float(raw)

# ---------------------------------------------------------------------------
# 各指标提取
# ---------------------------------------------------------------------------

def extract_voltage_qualification(pf_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(
        pf_data, "voltage_qualification_rate", "voltage_pass_rate"
    )
    if field is not None:
        return _validate_direct_metric(
            "voltage_qualification_rate", raw, source, field_name=field
        )

    analysis = pf_data.get("analysis") if isinstance(pf_data.get("analysis"), dict) else {}
    records, key = _get_list_field(
        analysis,
        "bus_voltages",
        "voltage_results",
        "all_bus_voltages",
        "evaluated_buses",
    )
    if records is None:
        # voltage_abnormal_nodes 仅为问题子集，不可伪造合格率
        return _missing_result(
            [
                "analysis.bus_voltages",
                "analysis.voltage_results",
                "voltage_qualification_rate",
            ],
            source,
            notes="缺少全量电压评价节点；voltage_abnormal_nodes 仅为问题子集",
        )
    try:
        result = calculate_grid_metric("voltage_qualification_rate", {"records": records})
        return _ok_result(
            float(result["value"]),
            inputs={"record_count": len(records), "source_field": key},
            input_source=source,
            coverage=_coverage(
                scope="full_set",
                valid_count=int(result["inputs"].get("_valid_count") or 0),
                skipped_count=int(result["inputs"].get("_skipped_incomplete") or 0)
                + int(result["inputs"].get("_skipped_invalid") or 0),
                denominator_source=key,
            ),
        )
    except ValueError as exc:
        logger.warning(f"voltage_qualification_rate: {exc}")
        return _missing_result([key or "records"], source, notes=str(exc))


def extract_voltage_severity(pf_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(pf_data, "voltage_over_limit_severity")
    if field is not None:
        return _validate_direct_metric(
            "voltage_over_limit_severity", raw, source, field_name=field
        )
    analysis = pf_data.get("analysis") if isinstance(pf_data.get("analysis"), dict) else {}
    records, key = _get_list_field(
        analysis, "bus_voltages", "voltage_results", "all_bus_voltages", "voltage_abnormal_nodes"
    )
    # 仅 abnormal 时：可作为越限子集严重度，但需标注 issue_subset
    if records is None:
        return _missing_result(
            ["analysis.bus_voltages", "voltage_over_limit_severity"],
            source,
        )
    scope = "issue_subset" if key == "voltage_abnormal_nodes" else "full_set"
    # 问题子集的严重度仍可计算（求和只针对越限节点），但必须标明 scope
    try:
        result = calculate_grid_metric("voltage_over_limit_severity", {"records": records})
        return _ok_result(
            float(result["value"]),
            inputs={"record_count": len(records), "source_field": key},
            input_source=source,
            coverage=_coverage(
                scope=scope,
                valid_count=int(result["inputs"].get("_valid_count") or 0),
                skipped_count=int(result["inputs"].get("_skipped_incomplete") or 0),
                denominator_source=key,
                notes="若 scope=issue_subset，仅基于异常节点集合",
            ),
        )
    except ValueError as exc:
        return _missing_result([key or "records"], source, notes=str(exc))


def extract_node_period_voltage_rate(pf_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(pf_data, "node_period_voltage_over_limit_rate")
    if field is not None:
        return _validate_direct_metric(
            "node_period_voltage_over_limit_rate", raw, source, field_name=field
        )
    analysis = pf_data.get("analysis") if isinstance(pf_data.get("analysis"), dict) else {}
    records, key = _get_list_field(
        analysis, "node_period_voltages", "bus_period_voltages", "voltage_time_series"
    )
    if records is None:
        return _missing_result(
            [
                "analysis.node_period_voltages",
                "node_period_voltage_over_limit_rate",
            ],
            source,
            notes="缺少节点—时段电压明细",
        )
    try:
        result = calculate_grid_metric(
            "node_period_voltage_over_limit_rate", {"records": records}
        )
        return _ok_result(
            float(result["value"]),
            inputs={"record_count": len(records), "source_field": key},
            input_source=source,
            coverage=_coverage(
                scope="full_set",
                valid_count=int(result["inputs"].get("_valid_count") or 0),
                denominator_source=key,
            ),
        )
    except ValueError as exc:
        return _missing_result([key or "records"], source, notes=str(exc))


def extract_max_line_loading(pf_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(
        pf_data, "max_line_loading_rate", "max_line_loading_percent"
    )
    if field is not None:
        return _validate_direct_metric(
            "max_line_loading_rate", raw, source, field_name=field
        )
    analysis = pf_data.get("analysis") if isinstance(pf_data.get("analysis"), dict) else {}
    records, key = _get_list_field(
        analysis, "line_loadings", "all_line_results", "line_results", "branch_loadings"
    )
    if records is not None:
        try:
            result = calculate_grid_metric("max_line_loading_rate", {"records": records})
            return _ok_result(
                float(result["value"]),
                inputs={"record_count": len(records), "source_field": key},
                input_source=source,
                coverage=_coverage(
                    scope="full_set",
                    valid_count=int(result["inputs"].get("_valid_count") or 0),
                    denominator_source=key,
                ),
            )
        except ValueError as exc:
            return _missing_result([key or "records"], source, notes=str(exc))

    # overloaded_lines 非空也不可冒充全网最大负载率
    overloaded, ol_key = _get_list_field(analysis, "overloaded_lines")
    if overloaded is not None:
        return _missing_result(
            ["analysis.line_loadings", "analysis.all_line_results"],
            source,
            coverage=_coverage(
                scope="issue_subset",
                valid_count=len(overloaded),
                notes="仅有 overloaded_lines 问题子集，不能作为全网最大线路负载率",
            ),
        )
    return _missing_result(
        ["analysis.line_loadings", "max_line_loading_rate"],
        source,
    )


def extract_max_transformer_loading(pf_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(
        pf_data, "max_transformer_loading_rate", "max_transformer_loading_percent"
    )
    if field is not None:
        return _validate_direct_metric(
            "max_transformer_loading_rate", raw, source, field_name=field
        )
    analysis = pf_data.get("analysis") if isinstance(pf_data.get("analysis"), dict) else {}
    records, key = _get_list_field(
        analysis,
        "transformer_loadings",
        "all_transformer_results",
        "transformer_results",
    )
    if records is not None:
        try:
            result = calculate_grid_metric(
                "max_transformer_loading_rate", {"records": records}
            )
            return _ok_result(
                float(result["value"]),
                inputs={"record_count": len(records), "source_field": key},
                input_source=source,
                coverage=_coverage(
                    scope="full_set",
                    valid_count=int(result["inputs"].get("_valid_count") or 0),
                    denominator_source=key,
                ),
            )
        except ValueError as exc:
            return _missing_result([key or "records"], source, notes=str(exc))
    return _missing_result(
        ["analysis.transformer_loadings", "max_transformer_loading_rate"],
        source,
        notes="overloaded_transformers 仅为问题子集，不能冒充全网最大主变负载率",
    )


def extract_active_power_loss_rate(pf_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(pf_data, "active_power_loss_rate", "loss_rate")
    if field is not None:
        return _validate_direct_metric(
            "active_power_loss_rate", raw, source, field_name=field
        )
    analysis = pf_data.get("analysis") if isinstance(pf_data.get("analysis"), dict) else {}
    power = analysis.get("power_summary") if isinstance(analysis.get("power_summary"), dict) else {}
    loss = get_aliased(power, "loss_mw")
    if loss is None:
        loss = get_aliased(analysis, "loss_mw")
    inp = get_aliased(power, "input_power_mw")
    if inp is None:
        inp = get_aliased(analysis, "input_power_mw")
    loss_f = _finite_float(loss)
    inp_f = _finite_float(inp)
    if loss_f is None or inp_f is None:
        return _missing_result(
            ["analysis.power_summary.损耗_MW", "analysis.power_summary.总发电_MW"],
            source,
        )
    try:
        result = calculate_grid_metric(
            "active_power_loss_rate",
            {"loss_mw": loss_f, "input_power_mw": inp_f},
        )
        return _ok_result(
            float(result["value"]),
            inputs={"loss_mw": loss_f, "input_power_mw": inp_f},
            input_source=source,
            coverage=_coverage(scope="scheme_summary", valid_count=1, denominator_source="input_power_mw"),
        )
    except ValueError as exc:
        return _missing_result(["input_power_mw"], source, notes=str(exc))


def extract_critical_section_margin(pf_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(pf_data, "critical_section_margin_rate")
    if field is not None:
        return _validate_direct_metric(
            "critical_section_margin_rate", raw, source, field_name=field
        )
    analysis = pf_data.get("analysis") if isinstance(pf_data.get("analysis"), dict) else {}
    sections, key = _get_list_field(
        analysis, "critical_sections", "sections", "section_flows"
    )
    if sections is None:
        return _missing_result(
            ["analysis.critical_sections", "critical_section_margin_rate"],
            source,
        )
    try:
        result = calculate_grid_metric(
            "critical_section_margin_rate", {"sections": sections}
        )
        return _ok_result(
            float(result["value"]),
            inputs={"section_count": len(sections), "source_field": key},
            input_source=source,
            coverage=_coverage(
                scope="full_set",
                valid_count=int(result["inputs"].get("_valid_count") or 0),
                denominator_source=key,
            ),
        )
    except ValueError as exc:
        return _missing_result([key or "sections"], source, notes=str(exc))


def _iter_n1_equipment_records(n1_data: Dict[str, Any]) -> Tuple[Optional[List[Dict[str, Any]]], Dict[str, Any]]:
    """收集 N-1 下设备负载记录；仅当存在全量故障设备结果时返回 usable=full。"""
    meta = {"scope": "missing", "contingency_count": 0, "equipment_count": 0}
    if "post_contingency_equipment_loadings" in n1_data:
        raw = n1_data.get("post_contingency_equipment_loadings")
        if isinstance(raw, list):
            meta = {"scope": "full_set", "contingency_count": None, "equipment_count": len(raw)}
            return [x for x in raw if isinstance(x, dict)], meta
    if "all_contingency_results" in n1_data and isinstance(n1_data["all_contingency_results"], list):
        full_records: List[Dict[str, Any]] = []
        overloaded_only: List[Dict[str, Any]] = []
        has_full_loading_lists = False
        for item in n1_data["all_contingency_results"]:
            if not isinstance(item, dict):
                continue
            analysis = ((item.get("result") or {}).get("analysis") or {})
            if not isinstance(analysis, dict):
                analysis = {}
            # 仅 line_loadings / transformer_loadings 可代表全量设备负载
            for key in ("line_loadings", "transformer_loadings"):
                if key not in analysis:
                    continue
                raw_list = analysis.get(key)
                if not isinstance(raw_list, list):
                    continue
                has_full_loading_lists = True
                for rec in raw_list:
                    if isinstance(rec, dict):
                        full_records.append(rec)
            for key in ("overloaded_lines", "overloaded_transformers"):
                raw_list = analysis.get(key)
                if not isinstance(raw_list, list):
                    continue
                for rec in raw_list:
                    if isinstance(rec, dict):
                        overloaded_only.append(rec)
        contingency_count = len(n1_data["all_contingency_results"])
        if has_full_loading_lists:
            meta = {
                "scope": "full_set",
                "contingency_count": contingency_count,
                "equipment_count": len(full_records),
            }
            return full_records, meta
        # all_contingency_results 仅有过载子集时，不得标成 full_set 冒充全网最大负载
        if overloaded_only:
            meta = {
                "scope": "issue_subset",
                "contingency_count": contingency_count,
                "equipment_count": len(overloaded_only),
                "notes": "all_contingency_results 仅含 overloaded_*，无全量 line/transformer_loadings",
            }
            return overloaded_only, meta
        meta = {
            "scope": "full_set",
            "contingency_count": contingency_count,
            "equipment_count": 0,
        }
        return [], meta

    # 仅有问题故障：不足以代表“全部 N-1 故障下最大负载率”
    issues = n1_data.get("contingencies_with_issues")
    if isinstance(issues, list):
        records = []
        for item in issues:
            if not isinstance(item, dict):
                continue
            analysis = ((item.get("result") or {}).get("analysis") or {})
            for rec in (analysis.get("overloaded_lines") or []):
                if isinstance(rec, dict):
                    records.append(rec)
            for rec in (analysis.get("overloaded_transformers") or []):
                if isinstance(rec, dict):
                    records.append(rec)
        meta = {
            "scope": "issue_subset",
            "contingency_count": len(issues),
            "equipment_count": len(records),
            "total_contingencies_run": n1_data.get("total_contingencies_run"),
        }
        return records, meta
    return None, meta


def extract_post_contingency_max_loading(n1_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(n1_data, "post_contingency_max_equipment_loading_rate")
    if field is not None:
        return _validate_direct_metric(
            "post_contingency_max_equipment_loading_rate", raw, source, field_name=field
        )
    records, meta = _iter_n1_equipment_records(n1_data)
    if records is None:
        return _missing_result(
            [
                "post_contingency_equipment_loadings",
                "all_contingency_results",
            ],
            source,
        )
    if meta.get("scope") == "issue_subset":
        return _missing_result(
            ["all_contingency_results.line_loadings", "post_contingency_equipment_loadings"],
            source,
            coverage=_coverage(
                scope="issue_subset",
                valid_count=len(records),
                notes=(
                    str(meta.get("notes") or "")
                    or (
                        "仅有过载设备子集（contingencies_with_issues 或 "
                        "all_contingency_results.overloaded_*），"
                        "不能代表全部 N-1 故障后最大设备负载率"
                    )
                ),
            ),
        )
    try:
        result = calculate_grid_metric(
            "post_contingency_max_equipment_loading_rate", {"records": records}
        )
        return _ok_result(
            float(result["value"]),
            inputs={"record_count": len(records)},
            input_source=source,
            coverage=_coverage(
                scope="full_set",
                valid_count=int(result["inputs"].get("_valid_count") or 0),
                notes=str(meta),
            ),
        )
    except ValueError as exc:
        return _missing_result(["records"], source, notes=str(exc))


def extract_post_contingency_voltage_rate(n1_data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(n1_data, "post_contingency_voltage_over_limit_rate")
    if field is not None:
        return _validate_direct_metric(
            "post_contingency_voltage_over_limit_rate", raw, source, field_name=field
        )
    records, key = _get_list_field(
        n1_data,
        "post_contingency_voltages",
        "fault_node_voltages",
        "all_contingency_voltage_results",
    )
    if records is None:
        return _missing_result(
            [
                "post_contingency_voltages",
                "fault_node_voltages",
                "post_contingency_voltage_over_limit_rate",
            ],
            source,
        )
    try:
        result = calculate_grid_metric(
            "post_contingency_voltage_over_limit_rate", {"records": records}
        )
        return _ok_result(
            float(result["value"]),
            inputs={"record_count": len(records), "source_field": key},
            input_source=source,
            coverage=_coverage(
                scope="full_set",
                valid_count=int(result["inputs"].get("_valid_count") or 0),
                denominator_source=key,
            ),
        )
    except ValueError as exc:
        return _missing_result([key or "records"], source, notes=str(exc))


def extract_transient_pass_rate(data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    # data 可为独立 transient 报告或嵌在 pf/n1
    raw, field = _scheme_level_raw(data, "transient_stability_pass_rate")
    if field is not None:
        return _validate_direct_metric(
            "transient_stability_pass_rate", raw, source, field_name=field
        )
    pass_count = _scheme_level_float(data, "transient_pass_count", "stable_fault_count")
    total = _scheme_level_float(
        data, "transient_total_count", "total_transient_faults", "total_faults"
    )
    if pass_count is not None and total is not None:
        try:
            result = calculate_grid_metric(
                "transient_stability_pass_rate",
                {"pass_count": pass_count, "total_count": total},
            )
            return _ok_result(
                float(result["value"]),
                inputs={"pass_count": pass_count, "total_count": total},
                input_source=source,
                coverage=_coverage(scope="scheme_summary", denominator_source="total_count"),
            )
        except ValueError as exc:
            return _missing_result(["total_count"], source, notes=str(exc))

    records, key = _get_list_field(
        data, "transient_faults", "transient_results", "stability_results"
    )
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    if records is None:
        records, key = _get_list_field(
            analysis, "transient_faults", "transient_results", "stability_results"
        )
    if records is None:
        return _missing_result(
            [
                "transient_stability_pass_rate",
                "transient_faults",
                "stable_fault_count",
            ],
            source,
            notes="历史案例通常无暂态稳定输出",
        )
    try:
        result = calculate_grid_metric(
            "transient_stability_pass_rate", {"records": records}
        )
        return _ok_result(
            float(result["value"]),
            inputs={"record_count": len(records), "source_field": key},
            input_source=source,
            coverage=_coverage(scope="full_set", denominator_source=key),
        )
    except ValueError as exc:
        return _missing_result([key or "records"], source, notes=str(exc))


def extract_max_angle_difference(data: Dict[str, Any], source: str) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    raw, field = _scheme_level_raw(data, "max_generator_relative_angle_difference")
    if field is not None:
        return _validate_direct_metric(
            "max_generator_relative_angle_difference", raw, source, field_name=field
        )
    records, key = _get_list_field(
        data,
        "generator_angle_records",
        "angle_time_series",
        "transient_angle_results",
    )
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    if records is None:
        records, key = _get_list_field(
            analysis,
            "generator_angle_records",
            "angle_time_series",
            "transient_angle_results",
        )
    if records is None:
        return _missing_result(
            [
                "generator_angle_records",
                "max_generator_relative_angle_difference",
            ],
            source,
        )
    try:
        result = calculate_grid_metric(
            "max_generator_relative_angle_difference", {"records": records}
        )
        return _ok_result(
            float(result["value"]),
            inputs={"record_count": len(records), "source_field": key},
            input_source=source,
            coverage=_coverage(scope="full_set", denominator_source=key),
        )
    except ValueError as exc:
        return _missing_result([key or "records"], source, notes=str(exc))


ADD_LINE_ACTIONS = frozenset({"add_line", "新建线路", "add_branch"})


def _length_from_branch(branch: Dict[str, Any]) -> Tuple[Optional[float], Dict[str, Any]]:
    """解析支路长度；meta.unit 为 km / mile / unknown，不做英里→公里换算。"""
    meta: Dict[str, Any] = {
        "original_field": None,
        "conversion": "none",
        "unit": None,
    }
    for key in ("length_km", "长度_km"):
        if key in branch and branch[key] is not None:
            value = _finite_float(branch[key])
            if value is not None:
                meta["original_field"] = key
                meta["conversion"] = "already_km"
                meta["unit"] = "km"
                return value, meta
    for key in ("MILES", "miles"):
        if key in branch and branch[key] is not None:
            value = _finite_float(branch[key])
            if value is not None:
                meta["original_field"] = key
                meta["conversion"] = "no_mile_to_km_without_basis"
                meta["unit"] = "mile"
                meta["note"] = "BPA MILES/miles 字段原样计入，未做英里→公里换算"
                return value, meta
    # 普通 length 无明确单位，不得擅自认定为 km
    if "length" in branch and branch["length"] is not None:
        value = _finite_float(branch["length"])
        if value is not None:
            meta["original_field"] = "length"
            meta["conversion"] = "none"
            meta["unit"] = "unknown"
            return value, meta
    return None, meta


def _length_from_modification(mod: Dict[str, Any]) -> Tuple[Optional[float], Dict[str, Any]]:
    """从单条 modification 解析长度；缺字段返回 (None, meta)，不静默当成 0。"""
    params = mod.get("params") if isinstance(mod.get("params"), dict) else {}
    if "full_branch_data" in params:
        branch = params.get("full_branch_data")
        if branch is None:
            return None, {"reason": "full_branch_data_null", "unit": None}
        if not isinstance(branch, dict):
            return None, {"reason": "full_branch_data_invalid_type", "unit": None}
        length, meta = _length_from_branch(branch)
        if length is not None:
            return length, meta
    if "length_km" in mod and mod.get("length_km") is not None:
        value = _finite_float(mod.get("length_km"))
        if value is not None:
            return value, {
                "original_field": "mod.length_km",
                "conversion": "already_km",
                "unit": "km",
            }
    if "length" in mod and mod.get("length") is not None:
        value = _finite_float(mod.get("length"))
        if value is not None:
            return value, {
                "original_field": "mod.length",
                "conversion": "none",
                "unit": "unknown",
            }
    return None, {"reason": "missing_length", "unit": None}


def _sum_homogeneous_lengths(
    metric_name: str,
    items: List[Dict[str, Any]],
    metas: List[Dict[str, Any]],
    source: str,
) -> Dict[str, Any]:
    """仅在单位一致时可求和；km/mile 混合则 invalid_data。"""
    from src.tools.grid_calculator import calculate_grid_metric

    units = {(meta or {}).get("unit") or "unknown" for meta in metas}
    if len(units) > 1:
        return _invalid_result(
            ["length_unit"],
            source,
            inputs={"line_items": items, "length_meta": metas, "units": sorted(units)},
            coverage=_coverage(
                scope="proposal_modifications",
                valid_count=len(items),
                notes="存在混合单位，缺少统一换算依据",
            ),
            notes="存在混合单位，缺少统一换算依据",
            unit="",
        )
    unit = next(iter(units)) if units else "unknown"
    try:
        result = calculate_grid_metric(metric_name, {"line_items": items})
    except ValueError as exc:
        return _missing_result(["line_items"], source, notes=str(exc))

    if unit == "mile":
        notes = "按原始 MILES 求和，未进行英里到公里换算"
    elif unit == "km":
        notes = "全部长度为 km，直接求和"
    else:
        notes = "长度单位不明确(unknown)，原样求和且不标注为 km"

    return _ok_result(
        float(result["value"]),
        inputs={"line_items": items, "length_meta": metas},
        input_source=source,
        unit=unit,
        coverage=_coverage(
            scope="proposal_modifications",
            valid_count=len(items),
            notes=notes,
        ),
    )


def extract_new_line_length(proposal: Dict[str, Any], source: str) -> Dict[str, Any]:
    if "new_line_length" in proposal:
        result = _validate_direct_metric(
            "new_line_length", proposal.get("new_line_length"), source, field_name="new_line_length"
        )
        if result.get("status") == "ok" and "unit" not in result:
            result = {**result, "unit": "km"}
        return result
    modifications = proposal.get("modifications")
    if "modifications" not in proposal:
        return _missing_result(["modifications", "new_line_length"], source)
    if modifications is None or not isinstance(modifications, list):
        return _missing_result(["modifications"], source, notes="modifications 类型无效")

    items: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    add_count = 0
    incomplete = 0
    for mod in modifications:
        if not isinstance(mod, dict):
            continue
        action = str(mod.get("action") or "").strip()
        if action not in ADD_LINE_ACTIONS:
            continue
        add_count += 1
        length, meta = _length_from_modification(mod)
        if length is None:
            incomplete += 1
            continue
        items.append({"length": length})
        metas.append(meta)

    if add_count == 0:
        return _ok_result(
            0.0,
            inputs={"line_items": [], "modification_count": len(modifications)},
            input_source=source,
            provenance="calculated",
            calculation_mode="sum_explicit_empty",
            unit="km",
            coverage=_coverage(
                scope="proposal_modifications",
                valid_count=0,
                notes="无 add_line 动作，新建线路长度计 0",
            ),
        )
    if incomplete > 0:
        return _missing_result(
            ["params.full_branch_data.length_km", "params.full_branch_data.MILES", "length_km"],
            source,
            coverage=_coverage(
                scope="proposal_modifications",
                valid_count=len(items),
                skipped_count=incomplete,
                notes=(
                    f"存在 {add_count} 条 add_line，其中 {incomplete} 条缺少可用长度；"
                    "禁止对已知部分求和冒充完整新建长度"
                ),
            ),
            notes="存在 add_line 但部分或全部缺少可用长度字段",
        )
    return _sum_homogeneous_lengths("new_line_length", items, metas, source)


def extract_retrofit_line_length(proposal: Dict[str, Any], source: str) -> Dict[str, Any]:
    if "retrofit_line_length" in proposal:
        result = _validate_direct_metric(
            "retrofit_line_length",
            proposal.get("retrofit_line_length"),
            source,
            field_name="retrofit_line_length",
        )
        if result.get("status") == "ok" and "unit" not in result:
            result = {**result, "unit": "km"}
        return result
    if "modifications" not in proposal:
        return _missing_result(["modifications", "retrofit_line_length"], source)
    modifications = proposal.get("modifications")
    if modifications is None or not isinstance(modifications, list):
        return _missing_result(["modifications"], source)

    items: List[Dict[str, Any]] = []
    metas: List[Dict[str, Any]] = []
    retrofit_count = 0
    incomplete = 0
    for mod in modifications:
        if not isinstance(mod, dict):
            continue
        action = str(mod.get("action") or "").strip()
        # 禁止把 disable_branch+add_line 自动当成改造
        if action not in RETROFIT_ACTIONS and not mod.get("is_retrofit"):
            continue
        retrofit_count += 1
        length, meta = _length_from_modification(mod)
        if length is None:
            incomplete += 1
            continue
        items.append({"length": length})
        metas.append(meta)

    if retrofit_count == 0:
        # 无明确改造动作 → 0（不是把 disable+add 算进去）
        return _ok_result(
            0.0,
            inputs={"line_items": [], "note": "no_explicit_retrofit_actions"},
            input_source=source,
            provenance="calculated",
            calculation_mode="sum_explicit_empty",
            unit="km",
            coverage=_coverage(
                scope="proposal_modifications",
                valid_count=0,
                notes="无明确改造动作；disable_branch+add_line 未计入改造长度",
            ),
        )
    if incomplete > 0:
        return _missing_result(
            ["params.full_branch_data.length_km", "params.full_branch_data.MILES", "length_km"],
            source,
            coverage=_coverage(
                scope="proposal_modifications",
                valid_count=len(items),
                skipped_count=incomplete,
                notes=(
                    f"存在 {retrofit_count} 条明确改造动作，其中 {incomplete} 条缺少可用长度；"
                    "禁止对已知部分求和或记 0 冒充完整改造长度"
                ),
            ),
            notes="存在明确改造动作但部分或全部缺少可用长度字段",
        )
    return _sum_homogeneous_lengths("retrofit_line_length", items, metas, source)
def _loss_defaults() -> Dict[str, Any]:
    from src.tools.grid_calculator import _load_rules

    defaults = ((_load_rules().get("defaults") or {}).get("network_loss") or {})
    return defaults


def extract_annual_energy_loss(pf_data: Dict[str, Any], source: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    extra = extra or {}
    raw, field = _scheme_level_raw(pf_data, "annual_energy_loss")
    if field is not None:
        return _validate_direct_metric(
            "annual_energy_loss", raw, source, field_name=field
        )
    analysis = pf_data.get("analysis") if isinstance(pf_data.get("analysis"), dict) else {}
    power = analysis.get("power_summary") if isinstance(analysis.get("power_summary"), dict) else {}
    loss = _finite_float(
        _first_present(
            get_aliased(power, "loss_mw"),
            get_aliased(analysis, "loss_mw"),
            extra.get("loss_mw"),
        )
    )
    hours = _finite_float(
        _first_present(
            extra.get("equivalent_hours"),
            pf_data.get("equivalent_loss_hours"),
            _loss_defaults().get("equivalent_hours"),
        )
    )
    if loss is None or hours is None:
        return _missing_result(
            ["analysis.power_summary.损耗_MW", "equivalent_loss_hours"],
            source,
            notes="年等效网损小时数必须显式提供，不虚构",
        )
    try:
        result = calculate_grid_metric(
            "annual_energy_loss", {"loss_mw": loss, "equivalent_hours": hours}
        )
        return _ok_result(
            float(result["value"]),
            inputs={"loss_mw": loss, "equivalent_hours": hours},
            input_source=source,
            coverage=_coverage(scope="scheme_summary", valid_count=1),
        )
    except ValueError as exc:
        return _missing_result(["equivalent_hours"], source, notes=str(exc))


def extract_annual_network_loss_cost(
    energy_loss_result: Dict[str, Any],
    pf_data: Dict[str, Any],
    source: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from src.tools.grid_calculator import calculate_grid_metric

    extra = extra or {}
    raw, field = _scheme_level_raw(pf_data, "annual_network_loss_cost")
    if field is not None:
        return _validate_direct_metric(
            "annual_network_loss_cost", raw, source, field_name=field
        )
    energy = energy_loss_result.get("value")
    price = _finite_float(
        _first_present(
            extra.get("price_per_mwh"),
            pf_data.get("loss_energy_price"),
            _loss_defaults().get("price_per_mwh"),
        )
    )
    if energy is None or price is None:
        return _missing_result(
            ["annual_energy_loss", "price_per_mwh"],
            source,
            notes="网损电价必须显式提供，不虚构",
        )
    try:
        result = calculate_grid_metric(
            "annual_network_loss_cost",
            {"annual_energy_loss_mwh": energy, "price_per_mwh": price},
        )
        return _ok_result(
            float(result["value"]),
            inputs={"annual_energy_loss_mwh": energy, "price_per_mwh": price},
            input_source=source,
            coverage=_coverage(scope="scheme_summary", valid_count=1),
        )
    except ValueError as exc:
        return _missing_result(["price_per_mwh"], source, notes=str(exc))


def collect_second_batch_metrics(
    *,
    pf_data: Dict[str, Any],
    n1_data: Dict[str, Any],
    proposal_raw: Dict[str, Any],
    pf_source: str,
    n1_source: str,
    proposal_source: str,
    transient_data: Optional[Dict[str, Any]] = None,
    transient_source: str = "",
) -> Dict[str, Dict[str, Any]]:
    """返回 metric_name -> 提取结果字典。"""
    transient_data = transient_data or {}
    energy = extract_annual_energy_loss(pf_data, pf_source)
    return {
        "voltage_qualification_rate": extract_voltage_qualification(pf_data, pf_source),
        "voltage_over_limit_severity": extract_voltage_severity(pf_data, pf_source),
        "node_period_voltage_over_limit_rate": extract_node_period_voltage_rate(
            pf_data, pf_source
        ),
        "max_line_loading_rate": extract_max_line_loading(pf_data, pf_source),
        "max_transformer_loading_rate": extract_max_transformer_loading(
            pf_data, pf_source
        ),
        "active_power_loss_rate": extract_active_power_loss_rate(pf_data, pf_source),
        "critical_section_margin_rate": extract_critical_section_margin(
            pf_data, pf_source
        ),
        "post_contingency_max_equipment_loading_rate": extract_post_contingency_max_loading(
            n1_data, n1_source
        ),
        "post_contingency_voltage_over_limit_rate": extract_post_contingency_voltage_rate(
            n1_data, n1_source
        ),
        "transient_stability_pass_rate": extract_transient_pass_rate(
            transient_data or pf_data, transient_source or pf_source
        ),
        "max_generator_relative_angle_difference": extract_max_angle_difference(
            transient_data or pf_data, transient_source or pf_source
        ),
        "new_line_length": extract_new_line_length(proposal_raw, proposal_source),
        "retrofit_line_length": extract_retrofit_line_length(
            proposal_raw, proposal_source
        ),
        "annual_energy_loss": energy,
        "annual_network_loss_cost": extract_annual_network_loss_cost(
            energy, pf_data, pf_source
        ),
    }
