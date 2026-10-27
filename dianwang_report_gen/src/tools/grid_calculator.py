from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import yaml

try:
    from langchain.tools import tool
except Exception:  # pragma: no cover - keeps deterministic helpers importable in light envs.
    def tool(*_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

# 配置文件路径
RULES_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "resources"
    / "compare_rules.yaml"
)

# 仅当 YAML 缺失对应项时使用；全项目经济参数回退只集中定义于此，禁止在其他文件重复写死。
_ECONOMIC_DEFAULT_FALLBACKS = {
    "interest_rate": 0.07,
    "years": 20.0,
    "lifecycle_factor": 1.25,
}


def _load_rules() -> dict[str, Any]:
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_metric_hard_constraint(metric: str) -> dict[str, Any]:
    """读取 compare_rules.yaml 中某指标的 hard_constraint 配置。"""
    try:
        rules = _load_rules()
    except Exception:
        return {}
    metrics = rules.get("metrics") or {}
    metric_rule = metrics.get(metric) or {}
    hard_constraint = metric_rule.get("hard_constraint")
    return hard_constraint if isinstance(hard_constraint, dict) else {}


def get_n1_pass_rate_hard_threshold() -> tuple[float, str]:
    """返回 (N-1硬约束阈值, 来源标识 compare_rules.yaml 或 fallback)。"""
    from loguru import logger

    fallback = 90.0
    hard_constraint = get_metric_hard_constraint("n1_pass_rate")
    if not hard_constraint:
        logger.warning(
            "compare_rules.yaml 中 n1_pass_rate.hard_constraint 缺失，"
            f"使用兼容默认值 {fallback}"
        )
        return fallback, "fallback"
    try:
        threshold = float(hard_constraint.get("threshold", fallback))
    except (TypeError, ValueError):
        logger.warning(
            "n1_pass_rate.hard_constraint.threshold 解析失败，"
            f"使用兼容默认值 {fallback}"
        )
        return fallback, "fallback"
    operator = str(hard_constraint.get("operator") or ">=")
    if operator != ">=":
        logger.warning(
            f"n1_pass_rate.hard_constraint.operator={operator!r} 暂仅支持 '>='，"
            f"仍按 threshold={threshold} 处理"
        )
    return threshold, "compare_rules.yaml"


def resolve_compare_rules_value(path: str) -> Tuple[Optional[float], Optional[str]]:
    """解析 compare_rules 路径并返回值。"""
    raw = (path or "").strip()
    if not raw:
        return None, "compare_rules 路径为空"

    parts = raw.split(".")
    if parts and parts[0].lower() == "compare_rules":
        parts = parts[1:]

    try:
        rules = _load_rules()
    except Exception as exc:
        return None, f"无法读取 compare_rules: {exc}"

    aliases = {"i": "interest_rate", "n": "years"}
    candidates: List[List[str]] = [parts]
    if parts and parts[0] == "annual_cost":
        candidates.append(["metrics", *parts])

    for candidate in candidates:
        node: Any = rules
        ok = True
        for key in candidate:
            if not isinstance(node, dict):
                ok = False
                break
            if key in node:
                node = node[key]
                continue
            alt = aliases.get(key)
            if alt and alt in node:
                node = node[alt]
                continue
            ok = False
            break
        if not ok or isinstance(node, dict):
            continue
        try:
            value = float(node)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value, None

    return None, f"compare_rules 路径不存在: {raw}"


def get_economic_defaults() -> dict[str, float]:
    """从 compare_rules.yaml 读取经济默认参数（唯一配置源）。

    返回：
      - interest_rate: 年费用折现率 i
      - years: 评价年限 n
      - lifecycle_factor: 规划阶段 LCC 简化系数

    YAML 缺失或非法时回退到本模块集中定义的 _ECONOMIC_DEFAULT_FALLBACKS。
    """
    fallbacks = dict(_ECONOMIC_DEFAULT_FALLBACKS)
    try:
        rules = _load_rules()
    except Exception as exc:
        raise ValueError(f"无法读取经济配置 {RULES_PATH}: {exc}") from exc

    defaults = rules.get("defaults") or {}
    annual = defaults.get("annual_cost") or {}
    lifecycle = defaults.get("lifecycle_cost") or {}
    metrics = rules.get("metrics") or {}
    annual_metric_defaults = (metrics.get("annual_cost") or {}).get("default_inputs") or {}
    lifecycle_metric_defaults = (metrics.get("lifecycle_cost") or {}).get("default_inputs") or {}

    def _positive_number(raw: Any, key: str) -> float:
        if raw is None or isinstance(raw, bool):
            return float(fallbacks[key])
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return float(fallbacks[key])
        if key == "years" and value <= 0:
            return float(fallbacks[key])
        if key in {"interest_rate", "lifecycle_factor"} and value < 0:
            return float(fallbacks[key])
        return value

    interest_rate = _positive_number(
        annual.get("interest_rate", annual_metric_defaults.get("interest_rate")),
        "interest_rate",
    )
    years = _positive_number(
        annual.get("years", annual_metric_defaults.get("years")),
        "years",
    )
    lifecycle_factor = _positive_number(
        lifecycle.get("factor", lifecycle_metric_defaults.get("factor")),
        "lifecycle_factor",
    )
    return {
        "interest_rate": interest_rate,
        "years": years,
        "lifecycle_factor": lifecycle_factor,
    }


def _as_float(value: Any, name: str) -> float:
    if value is None:
        raise ValueError(f"missing required input: {name}")
    if isinstance(value, bool):
        raise ValueError(f"input {name} must be numeric, got bool {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"input {name} must be numeric, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"input {name} must be finite, got {value!r}")
    return number


def _require_non_negative(value: float, name: str) -> float:
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


def _lcc_full_input_field_presence(inputs: dict[str, Any]) -> tuple[bool, bool, bool]:
    """完整折现专用字段是否在 inputs 中显式出现（含别名）。"""
    has_cash_flows = "cash_flows" in inputs or "lifecycle_cash_flows" in inputs
    has_discount_rate = "discount_rate" in inputs or "interest_rate" in inputs
    has_evaluation_years = "evaluation_years" in inputs or "years" in inputs
    return has_cash_flows, has_discount_rate, has_evaluation_years


def _resolve_lcc_full_inputs(inputs: dict[str, Any]) -> tuple[Any, Any, Any]:
    """解析完整折现参数字段值（保留原始类型供校验）。"""
    if "cash_flows" in inputs:
        cash_flows = inputs.get("cash_flows")
    elif "lifecycle_cash_flows" in inputs:
        cash_flows = inputs.get("lifecycle_cash_flows")
    else:
        cash_flows = None
    if "discount_rate" in inputs:
        discount_rate = inputs.get("discount_rate")
    elif "interest_rate" in inputs:
        discount_rate = inputs.get("interest_rate")
    else:
        discount_rate = None
    if "evaluation_years" in inputs:
        evaluation_years = inputs.get("evaluation_years")
    elif "years" in inputs:
        evaluation_years = inputs.get("years")
    else:
        evaluation_years = None
    return cash_flows, discount_rate, evaluation_years


def _validate_percentage(value: float, metric_name: str) -> float:
    """校验百分数落在 [0, 100]；不截断、不自动换算小数比例。"""
    if value < 0 or value > 100:
        raise ValueError(
            f"{metric_name}: percentage out of range [0, 100], got {value}"
        )
    return value


def calculate_capital_recovery_factor(interest_rate: Any, years: Any) -> float:
    """资本回收系数 CRF。

    - interest_rate > 0: i(1+i)^n / ((1+i)^n - 1)
    - interest_rate == 0: 1/n
    - interest_rate < 0 或 years <= 0：抛出 ValueError
    - bool 不可作为利率或年限
    """
    rate = _as_float(interest_rate, "interest_rate")
    n = _as_float(years, "years")
    if rate < 0:
        raise ValueError(f"interest_rate must be >= 0, got {rate}")
    if n <= 0:
        raise ValueError(f"years must be > 0, got {n}")
    if rate == 0:
        return 1.0 / n
    compound = (1 + rate) ** n
    return rate * compound / (compound - 1)


def _parse_bool(value: Any, name: str = "is_convergent") -> bool:
    """将布尔/数值/字符串统一解析为 True/False。

    注意：不能使用 bool(\"false\")，因为非空字符串在 Python 中恒为 True。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"input {name} numeric bool must be 0 or 1, got {value!r}")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "是", "收敛"}:
            return True
        if normalized in {"false", "0", "no", "n", "否", "不收敛"}:
            return False
        raise ValueError(f"input {name} cannot parse bool from string {value!r}")
    if value is None:
        raise ValueError(f"missing required input: {name}")
    raise ValueError(f"input {name} must be bool-like, got {value!r}")


def _get(inputs: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in inputs:
            return inputs[name]
    return default


def _normalize_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(inputs)
    aliases = {
        "short_circuit_current": (
            "short_circuit_current",
            "short_circuit_current_kA",
            "short_circuit_current_ka",
            "max_sc_current",
            "max_sc_current_kA",
            "max_sc_current_ka",
            "max_sc_mva",
            "sc_current",
            "fault_current",
        ),
        "breaker_current": (
            "breaker_current",
            "breaker_current_kA",
            "breaker_current_ka",
            "breaker_rating",
            "breaker_rating_kA",
            "breaker_rating_ka",
            "breaker_rating_mva",
            "allowed_current",
            "rated_current",
            "I_allow",
        ),
        "actual_current": (
            "actual_current",
            "current",
            "line_current",
            "max_loading_current",
        ),
        "allowed_current": (
            "allowed_current",
            "rated_current",
            "rating_current",
            "current_limit",
        ),
        "apparent_power": (
            "apparent_power",
            "actual_power",
            "actual_mva",
            "max_loading_mva",
        ),
        "allowed_power": (
            "allowed_power",
            "rated_power",
            "rating_mva",
            "power_limit",
        ),
        "pass_count": (
            "pass_count",
            "passed_count",
            "success_count",
            "n_pass",
            "N_pass",
        ),
        "total_count": (
            "total_count",
            "total_contingencies_run",
            "all_count",
            "n_all",
            "N_all",
        ),
        "check_count": (
            "check_count",
            "total_check_count",
            "node_count",
            "total_node_count",
            "total_buses",  # SCC 报告中的有效校核节点总数
            "effective_check_count",
        ),
        "over_limit_count": (
            "over_limit_count",
            "exceed_count",
            "violation_count",
        ),
        "construction_cost": (
            "construction_cost",
            "cost",
            "amount",
            "construction_cost_value",
        ),
        "operation_cost": (
            "operation_cost",
            "cost_per_year",
            "annual_operation_cost",
            "operation_cost_value",
        ),
        "direct_value": (
            "value",
            "input_value",
            "direct_value",
            "metric_value",
        ),
    }
    for canonical, names in aliases.items():
        if canonical not in normalized:
            value = _get(normalized, *names)
            if value is not None:
                normalized[canonical] = value
    return normalized


def _direct_metric_value(metric: str, inputs: dict[str, Any]) -> Any:
    metric_specific = {
        "construction_cost": ("construction_cost", "cost", "amount"),
        "operation_cost": ("operation_cost", "cost_per_year", "annual_operation_cost"),
        "annual_cost": ("annual_cost", "yearly_cost", "annual_cost_value"),
        "lifecycle_cost": ("lifecycle_cost", "total_lifecycle_cost", "lifecycle_cost_value"),
        "n1_pass_rate": ("n1_pass_rate", "pass_rate", "pass_rate_percent"),
        "weighted_n1_pass_rate": ("weighted_n1_pass_rate", "weighted_pass_rate", "weighted_pass_rate_percent"),
        "line_loading_rate": ("line_loading_rate", "loading_rate", "loading_percent", "max_loading_percent"),
        "transformer_loading_rate": ("transformer_loading_rate", "loading_rate", "loading_percent", "max_loading_percent"),
        "short_circuit_over_limit_count": ("over_limit_count",),
        "voltage_over_limit_count": ("over_limit_count",),
        "voltage_qualification_rate": ("voltage_qualification_rate",),
        "voltage_over_limit_severity": ("voltage_over_limit_severity",),
        "node_period_voltage_over_limit_rate": ("node_period_voltage_over_limit_rate",),
        "max_line_loading_rate": ("max_line_loading_rate",),
        "max_transformer_loading_rate": ("max_transformer_loading_rate",),
        "active_power_loss_rate": ("active_power_loss_rate",),
        "critical_section_margin_rate": ("critical_section_margin_rate",),
        "post_contingency_max_equipment_loading_rate": ("post_contingency_max_equipment_loading_rate",),
        "post_contingency_voltage_over_limit_rate": ("post_contingency_voltage_over_limit_rate",),
        "transient_stability_pass_rate": ("transient_stability_pass_rate",),
        "max_generator_relative_angle_difference": ("max_generator_relative_angle_difference",),
        "new_line_length": ("new_line_length",),
        "retrofit_line_length": ("retrofit_line_length",),
        "annual_energy_loss": ("annual_energy_loss", "annual_energy_loss_mwh"),
        "annual_network_loss_cost": ("annual_network_loss_cost",),
    }
    value = _get(inputs, *(metric_specific.get(metric) or ()))
    if value is not None:
        return value
    return inputs.get("direct_value")


SUPPORTED_METRICS = (
    "pf_convergence",  # 基态潮流收敛性（安全硬约束）
    "construction_cost",  # 建设投资
    "operation_cost",  # 年运行维护费
    "annual_cost",  # 年费用（年金化建设投资 + 年运维费）
    "lifecycle_cost",  # 全寿命周期成本 LCC（规划阶段简化估算）
    "n1_pass_rate",  # N-1 通过率
    "weighted_n1_pass_rate",  # N-1 负荷加权通过率
    "short_circuit_margin",  # 短路裕度（绝对值，kA）
    "min_breaker_interrupt_margin_rate",  # 最小断路器开断裕度率（%），安全硬约束
    "short_circuit_level_percent",
    "short_circuit_over_limit_count",
    "short_circuit_over_limit_ratio",  # 短路越限比例
    "voltage_over_limit_count",
    "voltage_over_limit_ratio",
    "line_loading_rate",
    "transformer_loading_rate",
    # —— 第二批比选指标 ——
    "voltage_qualification_rate",  # 电压合格率（%）
    "voltage_over_limit_severity",  # 电压越限严重度（pu²）
    "node_period_voltage_over_limit_rate",  # 节点—时段电压越限率（%）
    "max_line_loading_rate",  # 最大线路负载率（%）
    "max_transformer_loading_rate",  # 最大主变负载率（%）
    "active_power_loss_rate",  # 有功网损率（%）
    "critical_section_margin_rate",  # 关键断面输送裕度率（%，允许负值）
    "post_contingency_max_equipment_loading_rate",  # 故障后最大设备负载率（%）
    "post_contingency_voltage_over_limit_rate",  # 故障后电压越限率（%）
    "transient_stability_pass_rate",  # 暂态稳定通过率（%）
    "max_generator_relative_angle_difference",  # 最大机组相对功角差（度）
    "new_line_length",  # 新建线路长度（km）
    "retrofit_line_length",  # 改造线路长度（km）
    "annual_energy_loss",  # 年电量损耗（MWh/年）
    "annual_network_loss_cost",  # 年度网损成本（元/年）
)


def _ratio(numerator: float, denominator: float, denominator_name: str) -> float:
    if denominator == 0:
        raise ValueError(f"{denominator_name} must not be zero")
    return numerator / denominator * 100


def _in_band(value: float, band: dict[str, Any]) -> bool:
    minimum = band.get("min")
    maximum = band.get("max")
    if minimum is not None:
        if band.get("inclusive_min", True):
            if value < float(minimum):
                return False
        elif value <= float(minimum):
            return False
    if maximum is not None:
        if band.get("inclusive_max", True):
            if value > float(maximum):
                return False
        elif value >= float(maximum):
            return False
    return True


def _classify(value: float, metric_rule: dict[str, Any]) -> str:
    for band in metric_rule.get("bands") or []:
        if _in_band(value, band):
            return str(band.get("label", ""))

    target = metric_rule.get("target_interval") or {}
    if target:
        minimum = float(target["min"])
        maximum = float(target["max"])
        if minimum <= value <= maximum:
            return "推荐区间"
        if value < minimum:
            return "低于推荐区间"
        return "高于推荐区间"

    return ""


def _count_over_limit(records: list[dict[str, Any]], value_keys: tuple[str, ...], limit_keys: tuple[str, ...]) -> int:
    count = 0
    for record in records:
        value = _get(record, *value_keys)
        limit = _get(record, *limit_keys)
        if value is None or limit is None:
            continue
        if _as_float(value, "record value") > _as_float(limit, "record limit"):
            count += 1
    return count


def _count_voltage_over_limit(records: list[dict[str, Any]], default_min: Any = None, default_max: Any = None) -> int:
    count = 0
    for record in records:
        voltage = _get(record, "voltage", "电压", "voltage_pu")
        if voltage is None:
            continue
        min_voltage = _get(record, "min_voltage", "voltage_min", default=default_min)
        max_voltage = _get(record, "max_voltage", "voltage_max", default=default_max)
        if min_voltage is None or max_voltage is None:
            continue
        voltage_value = _as_float(voltage, "voltage")
        if voltage_value < _as_float(min_voltage, "min_voltage") or voltage_value > _as_float(max_voltage, "max_voltage"):
            count += 1
    return count


def _voltage_limits_from_record(
    record: dict[str, Any],
    default_min: Any = None,
    default_max: Any = None,
) -> tuple[Any, Any]:
    min_voltage = _get(
        record,
        "min_voltage",
        "voltage_min",
        "vmin",
        "Vmin",
        "电压下限",
        default=default_min,
    )
    max_voltage = _get(
        record,
        "max_voltage",
        "voltage_max",
        "vmax",
        "Vmax",
        "电压上限",
        default=default_max,
    )
    return min_voltage, max_voltage


def _try_float(value: Any) -> float | None:
    """尝试解析有限浮点；bool / 非法 / 非有限返回 None（不抛错）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _mutate_agg_counts(
    inputs: dict[str, Any],
    *,
    valid_count: int,
    skipped_incomplete: int,
    skipped_invalid: int,
) -> dict[str, Any]:
    return {
        **inputs,
        "_valid_count": valid_count,
        "_skipped_incomplete": skipped_incomplete,
        "_skipped_invalid": skipped_invalid,
    }


def _extract_line_loading_percent(record: dict[str, Any]) -> float | None:
    """提取单条线路负载率（%）。

    优先级（同时存在时不得混取）：
    1) 电流口径：电流(A)/额定电流(A) 或 actual_current/allowed_current
    2) 视在功率口径：视在功率(MVA)/额定视在功率(MVA) 或 apparent_power/rated
    3) 直接比例：电流比例(%)、loading_percent、视在功率比例(%)
    """
    current = _get(
        record,
        "actual_current",
        "current",
        "电流(A)",
        "电流",
        "line_current",
    )
    allowed_current = _get(
        record,
        "allowed_current",
        "rated_current",
        "额定电流(A)",
        "额定电流",
        "current_limit",
    )
    current_f = _try_float(current)
    allowed_f = _try_float(allowed_current)
    if current_f is not None and allowed_f is not None:
        if allowed_f == 0:
            return None
        return current_f / allowed_f * 100

    apparent = _get(
        record,
        "apparent_power",
        "视在功率(MVA)",
        "视在功率",
        "actual_mva",
    )
    rated = _get(
        record,
        "rated_apparent_power",
        "额定视在功率(MVA)",
        "额定视在功率",
        "allowed_power",
        "rated_power",
        "rated_capacity",
    )
    apparent_f = _try_float(apparent)
    rated_f = _try_float(rated)
    if apparent_f is not None and rated_f is not None:
        if rated_f == 0:
            return None
        return apparent_f / rated_f * 100

    direct = _get(
        record,
        "电流比例(%)",
        "loading_percent",
        "loading_rate",
        "line_loading_rate",
        "视在功率比例(%)",
        "max_loading_percent",
    )
    return _try_float(direct)


def _extract_transformer_loading_percent(record: dict[str, Any]) -> float | None:
    """提取单台主变负载率（%）：视在功率/额定容量，或直接 负载率(%)."""
    apparent = _get(
        record,
        "apparent_power",
        "视在功率(MVA)",
        "视在功率",
        "actual_mva",
    )
    rated = _get(
        record,
        "rated_capacity",
        "额定容量",
        "额定容量(MVA)",
        "rated_power",
        "allowed_power",
    )
    apparent_f = _try_float(apparent)
    rated_f = _try_float(rated)
    if apparent_f is not None and rated_f is not None:
        if rated_f == 0:
            return None
        return apparent_f / rated_f * 100

    direct = _get(
        record,
        "负载率(%)",
        "loading_percent",
        "loading_rate",
        "transformer_loading_rate",
        "max_loading_percent",
    )
    return _try_float(direct)


def _extract_equipment_loading_percent(record: dict[str, Any]) -> float | None:
    """故障后设备：先按线路口径，再按主变口径。"""
    line_loading = _extract_line_loading_percent(record)
    if line_loading is not None:
        return line_loading
    return _extract_transformer_loading_percent(record)


def _max_loading_from_records(
    records: list[Any],
    extractor,
    metric_name: str,
) -> tuple[float, int, int, int]:
    values: list[float] = []
    skipped_incomplete = 0
    skipped_invalid = 0
    for record in records:
        if not isinstance(record, dict):
            skipped_incomplete += 1
            continue
        loading = extractor(record)
        if loading is None:
            probe_keys = (
                "actual_current",
                "current",
                "电流(A)",
                "电流",
                "allowed_current",
                "rated_current",
                "额定电流(A)",
                "apparent_power",
                "视在功率(MVA)",
                "视在功率",
                "rated_capacity",
                "额定容量",
                "额定视在功率(MVA)",
                "电流比例(%)",
                "视在功率比例(%)",
                "负载率(%)",
                "loading_percent",
                "loading_rate",
            )
            if any(_get(record, key) is not None for key in probe_keys):
                skipped_invalid += 1
            else:
                skipped_incomplete += 1
            continue
        values.append(loading)
    if not values:
        raise ValueError(
            f"{metric_name}: 无有效负载率记录"
            f"（skipped_incomplete={skipped_incomplete}, skipped_invalid={skipped_invalid}）"
        )
    return max(values), len(values), skipped_incomplete, skipped_invalid


def _sum_line_lengths(metric: str, inputs: dict[str, Any], direct_value: Any) -> tuple[float, dict[str, Any]]:
    if direct_value is not None:
        return _require_non_negative(_as_float(direct_value, metric), metric), inputs

    items = inputs.get("line_items")
    if items is None:
        items = inputs.get("records")
    if items is None:
        raise ValueError(f"{metric}: missing line_items/records or direct value")
    if not isinstance(items, list):
        raise ValueError(f"{metric}: line_items/records must be a list")

    allow_zero = False
    if "allow_zero" in inputs:
        allow_zero = _parse_bool(inputs.get("allow_zero"), "allow_zero")

    if len(items) == 0:
        if allow_zero:
            updated = _mutate_agg_counts(
                inputs, valid_count=0, skipped_incomplete=0, skipped_invalid=0
            )
            return 0.0, updated
        raise ValueError(f"{metric}: empty line list and allow_zero is not set")

    total = 0.0
    valid_count = 0
    skipped_incomplete = 0
    skipped_invalid = 0
    for item in items:
        if not isinstance(item, dict):
            skipped_incomplete += 1
            continue
        length_raw = _get(
            item,
            "length_km",
            "length",
            "miles",
            "MILES",
            "长度",
            "长度(km)",
            "line_length",
        )
        if length_raw is None:
            skipped_incomplete += 1
            continue
        length = _try_float(length_raw)
        if length is None:
            skipped_invalid += 1
            continue
        total += length
        valid_count += 1

    if valid_count == 0 and not allow_zero:
        raise ValueError(
            f"{metric}: 无有效长度记录"
            f"（skipped_incomplete={skipped_incomplete}, skipped_invalid={skipped_invalid}）"
        )
    updated = _mutate_agg_counts(
        inputs,
        valid_count=valid_count,
        skipped_incomplete=skipped_incomplete,
        skipped_invalid=skipped_invalid,
    )
    return total, updated


def _iter_generator_angle_samples(inputs: dict[str, Any]) -> list[list[float]]:
    """从 records 或 generator_angles 嵌套结构收集每个故障/时刻的功角列表。"""
    samples: list[list[float]] = []
    records = inputs.get("records")
    if isinstance(records, list) and records:
        for record in records:
            if not isinstance(record, dict):
                continue
            angles_raw = record.get("angles")
            if not isinstance(angles_raw, (list, tuple)):
                continue
            angles = [_try_float(a) for a in angles_raw]
            if any(a is None for a in angles) or len(angles) < 2:
                continue
            samples.append([a for a in angles if a is not None])
        return samples

    nested = inputs.get("generator_angles")
    if isinstance(nested, dict):
        for _fault, times in nested.items():
            if isinstance(times, dict):
                for _time, angles_raw in times.items():
                    if not isinstance(angles_raw, (list, tuple)):
                        continue
                    angles = [_try_float(a) for a in angles_raw]
                    if any(a is None for a in angles) or len(angles) < 2:
                        continue
                    samples.append([a for a in angles if a is not None])
            elif isinstance(times, (list, tuple)):
                angles = [_try_float(a) for a in times]
                if any(a is None for a in angles) or len(angles) < 2:
                    continue
                samples.append([a for a in angles if a is not None])
    return samples


def _resolve_metric_formula(
    metric_rule: dict[str, Any], inputs: dict[str, Any]
) -> Any:
    """按 calculation_mode 选择公式；provided 无公式，其余优先 formula_by_mode。"""
    mode = inputs.get("_calculation_mode")
    if mode == "provided":
        return None
    by_mode = metric_rule.get("formula_by_mode") or {}
    if mode and isinstance(by_mode, dict) and mode in by_mode:
        return by_mode.get(mode)
    return metric_rule.get("formula", "") or ""


def _format_calculate_input_pairs(inputs: dict[str, Any]) -> str:
    pairs: list[str] = []
    for key, value in inputs.items():
        if str(key).startswith("_"):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            if math.isfinite(float(value)):
                pairs.append(f"{key}={value}")
            continue
        if isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                continue
            if math.isfinite(number):
                pairs.append(f"{key}={number}")
    return "; ".join(pairs)


def _format_calculate_input_source(inputs: dict[str, Any]) -> str:
    compare_rules_bindings = {
        "interest_rate": "compare_rules.metrics.annual_cost.default_inputs.interest_rate",
        "i": "compare_rules.metrics.annual_cost.default_inputs.interest_rate",
        "years": "compare_rules.metrics.annual_cost.default_inputs.years",
        "n": "compare_rules.metrics.annual_cost.default_inputs.years",
        "rate": "compare_rules.metrics.operation_cost.default_inputs.rate",
        "factor": "compare_rules.metrics.lifecycle_cost.default_inputs.factor",
    }
    claim_bindings = inputs.get("_claim_bindings")
    if not isinstance(claim_bindings, dict):
        claim_bindings = {}

    pairs: list[str] = []
    for key, value in inputs.items():
        if str(key).startswith("_"):
            continue
        if not isinstance(value, (int, float, str)):
            continue
        if key in claim_bindings:
            pairs.append(f"{key}=claim_{claim_bindings[key]}")
        elif key in compare_rules_bindings:
            pairs.append(f"{key}={compare_rules_bindings[key]}")
    return "; ".join(pairs)


def _build_calculate_tag(
    metric_rule: dict[str, Any], inputs: dict[str, Any], value: float
) -> str:
    formula = _resolve_metric_formula(metric_rule, inputs)
    input_pairs = _format_calculate_input_pairs(inputs)
    source_pairs = _format_calculate_input_source(inputs)
    return (
        "<calculate> "
        f"input: {input_pairs}; "
        f"input_source: {source_pairs}; "
        f"formula: {formula if formula is not None else ''}; "
        f"output: {value} "
        "</calculate>"
    )


def calculate_grid_metric(metric: str, inputs: dict[str, Any]) -> dict[str, Any]:
    inputs = _normalize_inputs(inputs)
    if metric not in SUPPORTED_METRICS:
        raise ValueError(
            f"unsupported metric: {metric}. "
            f"supported metrics: {', '.join(SUPPORTED_METRICS)}"
        )
    rules = _load_rules()
    # YAML 规则可选；第二批指标可能尚未写入 compare_rules.yaml。
    metric_rule = (rules.get("metrics") or {}).get(metric) or {}

    direct_value = _direct_metric_value(metric, inputs)

    if metric == "construction_cost":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "construction_cost"),
                "construction_cost",
            )
        else:
            line_items = inputs.get("line_items") or []
            value = sum(
                _require_non_negative(
                    _as_float(item.get("length_km"), "length_km"),
                    "length_km",
                )
                * _require_non_negative(
                    _as_float(item.get("unit_cost_per_km"), "unit_cost_per_km"),
                    "unit_cost_per_km",
                )
                * _require_non_negative(
                    _as_float(item.get("condition_factor", 1), "condition_factor"),
                    "condition_factor",
                )
                for item in line_items
            )
            value = _require_non_negative(float(value), "construction_cost")

    elif metric == "pf_convergence":
        # 基态潮流收敛性：收敛=1，不收敛=0
        is_convergent = inputs.get("is_convergent")
        if is_convergent is None and "direct_value" in inputs:
            is_convergent = inputs.get("direct_value")
        value = 1.0 if _parse_bool(is_convergent, "is_convergent") else 0.0
    elif metric == "min_breaker_interrupt_margin_rate":
        # 最小断路器开断裕度率：必须逐节点配对计算后再取最小值。
        # 禁止用“最大短路电流”与“最大断路器电流”跨节点相减/相除。
        records = inputs.get("records") or []
        margins: list[float] = []
        skipped_zero_breaker = 0
        skipped_incomplete = 0
        for record in records:
            if not isinstance(record, dict):
                skipped_incomplete += 1
                continue
            short_raw = _get(
                record,
                "short_circuit_current_kA",
                "short_circuit_current_ka",
                "short_circuit_current",
            )
            breaker_raw = _get(
                record,
                "breaker_current_kA",
                "breaker_current_ka",
                "breaker_current",
            )
            # 缺任一字段的记录不参与计算
            if short_raw is None or breaker_raw is None:
                skipped_incomplete += 1
                continue
            short_current = _as_float(short_raw, "short_circuit_current_kA")
            breaker_current = _as_float(breaker_raw, "breaker_current_kA")
            if breaker_current == 0:
                skipped_zero_breaker += 1
                continue
            # margin_i = (I_break - I_sc) / I_break * 100%；负值表示短路电流超过开断能力
            margins.append((breaker_current - short_current) / breaker_current * 100)
        if not margins:
            raise ValueError(
                "min_breaker_interrupt_margin_rate: 数据不足，"
                "无同时具备 short_circuit_current_kA 与 breaker_current_kA 的有效记录"
                f"（skipped_incomplete={skipped_incomplete}, skipped_zero_breaker={skipped_zero_breaker}）"
            )
        value = min(margins)
        inputs = {
            **inputs,
            "_margin_count": len(margins),
            "_skipped_incomplete": skipped_incomplete,
            "_skipped_zero_breaker": skipped_zero_breaker,
            "_data_scope_note": (
                "若 records 仅含越限节点，则该最小裕度仅代表越限子集，"
                "真正的方案级最小裕度应基于全部有效校核节点。"
            ),
        }

    elif metric == "operation_cost":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "operation_cost"),
                "operation_cost",
            )
        else:
            rate = _require_non_negative(
                _as_float(
                    inputs.get(
                        "rate",
                        metric_rule.get("default_inputs", {}).get("rate", 0.015),
                    ),
                    "rate",
                ),
                "rate",
            )
            value = (
                _require_non_negative(
                    _as_float(inputs.get("construction_cost"), "construction_cost"),
                    "construction_cost",
                )
                * rate
            )
    elif metric == "annual_cost":
        # 年费用：仅表示年金化费用，禁止与 lifecycle_cost 混用或互为回退。
        # annual_cost = construction_cost * CRF(i,n) + operation_cost
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "annual_cost"),
                "annual_cost",
            )
        else:
            eco = get_economic_defaults()
            construction_cost = _require_non_negative(
                _as_float(inputs.get("construction_cost"), "construction_cost"),
                "construction_cost",
            )
            operation_cost = _require_non_negative(
                _as_float(inputs.get("operation_cost"), "operation_cost"),
                "operation_cost",
            )
            defaults = metric_rule.get("default_inputs", {})
            interest_rate = inputs.get(
                "interest_rate",
                inputs.get("i", defaults.get("interest_rate", eco["interest_rate"])),
            )
            years = inputs.get("years", inputs.get("n", defaults.get("years", eco["years"])))
            factor = calculate_capital_recovery_factor(interest_rate, years)
            value = _require_non_negative(
                construction_cost * factor + operation_cost,
                "annual_cost",
            )
    elif metric == "lifecycle_cost":
        # 全寿命周期成本 LCC：
        # 1) 直接提供 → provided（须非负）
        # 2) 任意完整折现专用字段出现 → 必须三类齐备且有效 → full_calculated
        # 3) 完全未提供完整折现专用字段 → construction_cost * factor（estimated_simplified）
        # 禁止用 annual_cost 作为回退值；部分/错误完整参数禁止回退简化估算。
        has_cash_flows_field, has_discount_field, has_horizon_field = (
            _lcc_full_input_field_presence(inputs)
        )
        has_any_full_input = (
            has_cash_flows_field or has_discount_field or has_horizon_field
        )
        has_complete_full_input = (
            has_cash_flows_field and has_discount_field and has_horizon_field
        )
        cash_flows, discount_rate, evaluation_years = _resolve_lcc_full_inputs(inputs)
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "lifecycle_cost"),
                "lifecycle_cost",
            )
            inputs = {**inputs, "_calculation_mode": "provided"}
        elif has_any_full_input:
            if not has_complete_full_input:
                missing = []
                if not has_cash_flows_field:
                    missing.append("cash_flows")
                if not has_discount_field:
                    missing.append("discount_rate")
                if not has_horizon_field:
                    missing.append("evaluation_years")
                raise ValueError(
                    "lifecycle_cost: incomplete full-calculation inputs, missing "
                    + ", ".join(missing)
                )
            if not isinstance(cash_flows, list):
                raise ValueError(
                    "lifecycle_cost: cash_flows must be a non-empty list, got "
                    f"{type(cash_flows).__name__}"
                )
            if len(cash_flows) == 0:
                raise ValueError(
                    "lifecycle_cost: cash_flows must be a non-empty list"
                )
            rate = _require_non_negative(
                _as_float(discount_rate, "discount_rate"),
                "discount_rate",
            )
            horizon = _require_non_negative(
                _as_float(evaluation_years, "evaluation_years"),
                "evaluation_years",
            )
            if inputs.get("construction_cost") is not None:
                construction = _require_non_negative(
                    _as_float(inputs.get("construction_cost"), "construction_cost"),
                    "construction_cost",
                )
            else:
                construction = 0.0
            npv = construction
            for idx, item in enumerate(cash_flows):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"lifecycle_cost: cash_flows[{idx}] must be an object, "
                        f"got {type(item).__name__}"
                    )
                year_raw = _get(item, "year", "t")
                cost_raw = _get(item, "cost", "amount", "value")
                if year_raw is None or cost_raw is None:
                    raise ValueError(
                        f"lifecycle_cost: cash_flows[{idx}] missing year/cost "
                        "(bad records must not be silently skipped)"
                    )
                year = _as_float(year_raw, f"cash_flows[{idx}].year")
                # 单笔现金流可为负（残值/回收），不做非负强制
                cost = _as_float(cost_raw, f"cash_flows[{idx}].cost")
                if year < 0 or year > horizon:
                    raise ValueError(
                        f"lifecycle_cost: cash_flows[{idx}].year={year} "
                        f"out of evaluation horizon [0, {horizon}]"
                    )
                npv += cost / ((1.0 + rate) ** year)
            value = _require_non_negative(npv, "lifecycle_cost")
            inputs = {
                **inputs,
                "_calculation_mode": "full_calculated",
                "_cash_flow_count": len(cash_flows),
            }
        else:
            eco = get_economic_defaults()
            factor = _require_non_negative(
                _as_float(
                    inputs.get(
                        "factor",
                        metric_rule.get("default_inputs", {}).get(
                            "factor", eco["lifecycle_factor"]
                        ),
                    ),
                    "factor",
                ),
                "factor",
            )
            value = _require_non_negative(
                _require_non_negative(
                    _as_float(inputs.get("construction_cost"), "construction_cost"),
                    "construction_cost",
                )
                * factor,
                "lifecycle_cost",
            )
            inputs = {**inputs, "_calculation_mode": "estimated_simplified"}
    elif metric == "n1_pass_rate":
        # 当前口径：pass_count / total_count * 100%；零分母报错。
        if direct_value is not None:
            value = _validate_percentage(_as_float(direct_value, "n1_pass_rate"), "n1_pass_rate")
        else:
            value = _validate_percentage(
                _ratio(
                    _as_float(inputs.get("pass_count"), "pass_count"),
                    _as_float(inputs.get("total_count"), "total_count"),
                    "total_count",
                ),
                "n1_pass_rate",
            )
    elif metric == "weighted_n1_pass_rate":
        # 必须使用通过故障对应负荷 / 全部故障对应总负荷，不可用故障数量代替。
        if direct_value is not None:
            value = _validate_percentage(
                _as_float(direct_value, "weighted_n1_pass_rate"),
                "weighted_n1_pass_rate",
            )
        else:
            if inputs.get("passed_load") is None or inputs.get("total_load") is None:
                raise ValueError(
                    "weighted_n1_pass_rate: 数据不足，缺少 passed_load / total_load "
                    "（不可用通过故障数量代替负荷权重）"
                )
            passed_load = _as_float(inputs.get("passed_load"), "passed_load")
            total_load = _as_float(inputs.get("total_load"), "total_load")
            if total_load <= 0:
                raise ValueError(
                    f"weighted_n1_pass_rate: total_load must be > 0, got {total_load}"
                )
            if passed_load < 0 or passed_load > total_load:
                raise ValueError(
                    "weighted_n1_pass_rate: require 0 <= passed_load <= total_load, "
                    f"got passed_load={passed_load}, total_load={total_load}"
                )
            value = _validate_percentage(
                passed_load / total_load * 100,
                "weighted_n1_pass_rate",
            )
    elif metric == "short_circuit_margin":
        value = _as_float(inputs.get("breaker_current"), "breaker_current") - _as_float(
            inputs.get("short_circuit_current"), "short_circuit_current"
        )
    elif metric == "short_circuit_level_percent":
        value = _ratio(
            _as_float(inputs.get("short_circuit_current"), "short_circuit_current"),
            _as_float(inputs.get("breaker_current"), "breaker_current"),
            "breaker_current",
        )
    elif metric == "short_circuit_over_limit_count":
        if direct_value is not None:
            value = _as_float(direct_value, "short_circuit_over_limit_count")
        elif inputs.get("over_limit_count") is not None:
            value = _as_float(inputs.get("over_limit_count"), "over_limit_count")
        else:
            value = float(
                _count_over_limit(
                    inputs.get("records") or [],
                    ("short_circuit_current", "current", "I_sc"),
                    ("allowed_current", "breaker_current", "I_allow"),
                )
            )
    elif metric in {"short_circuit_over_limit_ratio", "voltage_over_limit_ratio"}:
        value = _ratio(
            _as_float(inputs.get("over_limit_count"), "over_limit_count"),
            _as_float(inputs.get("check_count", inputs.get("node_count")), "check_count/node_count"),
            "check_count/node_count",
        )
    elif metric == "voltage_over_limit_count":
        if direct_value is not None:
            value = _as_float(direct_value, "voltage_over_limit_count")
        else:
            value = float(
                _count_voltage_over_limit(
                    inputs.get("records") or [],
                    inputs.get("min_voltage"),
                    inputs.get("max_voltage"),
                )
            )
    elif metric == "line_loading_rate":
        if direct_value is not None:
            value = _as_float(direct_value, "line_loading_rate")
        else:
            value = _ratio(
                _as_float(inputs.get("actual_current", inputs.get("apparent_power")), "actual_current/apparent_power"),
                _as_float(inputs.get("allowed_current", inputs.get("allowed_power")), "allowed_current/allowed_power"),
                "allowed_current/allowed_power",
            )
    elif metric == "transformer_loading_rate":
        if direct_value is not None:
            value = _as_float(direct_value, "transformer_loading_rate")
        else:
            value = _ratio(
                _as_float(inputs.get("apparent_power"), "apparent_power"),
                _as_float(inputs.get("rated_capacity"), "rated_capacity"),
                "rated_capacity",
            )
    elif metric == "voltage_qualification_rate":
        if direct_value is not None:
            value = _validate_percentage(
                _as_float(direct_value, "voltage_qualification_rate"),
                "voltage_qualification_rate",
            )
        elif inputs.get("qualified_count") is not None and inputs.get("total_evaluated_count") is not None:
            value = _validate_percentage(
                _ratio(
                    _as_float(inputs.get("qualified_count"), "qualified_count"),
                    _as_float(inputs.get("total_evaluated_count"), "total_evaluated_count"),
                    "total_evaluated_count",
                ),
                "voltage_qualification_rate",
            )
        else:
            records = inputs.get("records") or []
            qualified = 0
            valid_count = 0
            skipped_incomplete = 0
            skipped_invalid = 0
            default_min = inputs.get("min_voltage")
            default_max = inputs.get("max_voltage")
            for record in records:
                if not isinstance(record, dict):
                    skipped_incomplete += 1
                    continue
                voltage_raw = _get(record, "voltage", "电压", "voltage_pu", "V")
                min_raw, max_raw = _voltage_limits_from_record(
                    record, default_min=default_min, default_max=default_max
                )
                if voltage_raw is None or min_raw is None or max_raw is None:
                    skipped_incomplete += 1
                    continue
                voltage = _try_float(voltage_raw)
                vmin = _try_float(min_raw)
                vmax = _try_float(max_raw)
                if voltage is None or vmin is None or vmax is None:
                    skipped_invalid += 1
                    continue
                # 强制走 _as_float，确保有限性校验口径一致
                voltage = _as_float(voltage, "voltage")
                vmin = _as_float(vmin, "min_voltage")
                vmax = _as_float(vmax, "max_voltage")
                valid_count += 1
                if vmin <= voltage <= vmax:
                    qualified += 1
            if valid_count == 0:
                raise ValueError(
                    "voltage_qualification_rate: 无有效电压评价数据"
                    f"（skipped_incomplete={skipped_incomplete}, skipped_invalid={skipped_invalid}）"
                )
            value = _validate_percentage(qualified / valid_count * 100, "voltage_qualification_rate")
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=valid_count,
                skipped_incomplete=skipped_incomplete,
                skipped_invalid=skipped_invalid,
            )
    elif metric == "voltage_over_limit_severity":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "voltage_over_limit_severity"),
                "voltage_over_limit_severity",
            )
        else:
            records = inputs.get("records") or []
            severity = 0.0
            valid_count = 0
            skipped_incomplete = 0
            skipped_invalid = 0
            default_min = inputs.get("min_voltage")
            default_max = inputs.get("max_voltage")
            for record in records:
                if not isinstance(record, dict):
                    skipped_incomplete += 1
                    continue
                voltage_raw = _get(record, "voltage", "电压", "voltage_pu", "V")
                min_raw, max_raw = _voltage_limits_from_record(
                    record, default_min=default_min, default_max=default_max
                )
                if voltage_raw is None or min_raw is None or max_raw is None:
                    skipped_incomplete += 1
                    continue
                voltage = _try_float(voltage_raw)
                vmin = _try_float(min_raw)
                vmax = _try_float(max_raw)
                if voltage is None or vmin is None or vmax is None:
                    skipped_invalid += 1
                    continue
                voltage = _as_float(voltage, "voltage")
                vmin = _as_float(vmin, "min_voltage")
                vmax = _as_float(vmax, "max_voltage")
                deviation = max(vmin - voltage, 0.0, voltage - vmax)
                severity += deviation * deviation
                valid_count += 1
            if valid_count == 0:
                raise ValueError(
                    "voltage_over_limit_severity: 无有效电压记录"
                    f"（skipped_incomplete={skipped_incomplete}, skipped_invalid={skipped_invalid}）"
                )
            value = severity
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=valid_count,
                skipped_incomplete=skipped_incomplete,
                skipped_invalid=skipped_invalid,
            )
    elif metric == "node_period_voltage_over_limit_rate":
        if direct_value is not None:
            value = _validate_percentage(
                _as_float(direct_value, "node_period_voltage_over_limit_rate"),
                "node_period_voltage_over_limit_rate",
            )
        elif (
            _get(inputs, "over_limit_pairs", "over_limit_count") is not None
            and _get(inputs, "total_pairs", "total_count") is not None
        ):
            value = _validate_percentage(
                _ratio(
                    _as_float(
                        _get(inputs, "over_limit_pairs", "over_limit_count"),
                        "over_limit_pairs",
                    ),
                    _as_float(_get(inputs, "total_pairs", "total_count"), "total_pairs"),
                    "total_pairs",
                ),
                "node_period_voltage_over_limit_rate",
            )
        else:
            records = inputs.get("records") or []
            over_limit = 0
            valid_count = 0
            skipped_incomplete = 0
            skipped_invalid = 0
            default_min = inputs.get("min_voltage")
            default_max = inputs.get("max_voltage")
            default_period = inputs.get("period", inputs.get("default_period", 1))
            for record in records:
                if not isinstance(record, dict):
                    skipped_incomplete += 1
                    continue
                node_id = _get(record, "node_id", "bus_id", "bus", "节点", "node")
                period = _get(record, "period", "time", "时段", default=default_period)
                voltage_raw = _get(record, "voltage", "电压", "voltage_pu", "V")
                min_raw, max_raw = _voltage_limits_from_record(
                    record, default_min=default_min, default_max=default_max
                )
                if node_id is None or period is None or voltage_raw is None or min_raw is None or max_raw is None:
                    skipped_incomplete += 1
                    continue
                voltage = _try_float(voltage_raw)
                vmin = _try_float(min_raw)
                vmax = _try_float(max_raw)
                if voltage is None or vmin is None or vmax is None:
                    skipped_invalid += 1
                    continue
                voltage = _as_float(voltage, "voltage")
                vmin = _as_float(vmin, "min_voltage")
                vmax = _as_float(vmax, "max_voltage")
                valid_count += 1
                if voltage < vmin or voltage > vmax:
                    over_limit += 1
            if valid_count == 0:
                raise ValueError(
                    "node_period_voltage_over_limit_rate: 无有效节点—时段电压记录"
                    f"（skipped_incomplete={skipped_incomplete}, skipped_invalid={skipped_invalid}）"
                )
            value = _validate_percentage(over_limit / valid_count * 100, "node_period_voltage_over_limit_rate")
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=valid_count,
                skipped_incomplete=skipped_incomplete,
                skipped_invalid=skipped_invalid,
            )
    elif metric == "max_line_loading_rate":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "max_line_loading_rate"),
                "max_line_loading_rate",
            )
        else:
            records = inputs.get("records") or inputs.get("lines") or []
            if not isinstance(records, list) or not records:
                raise ValueError("max_line_loading_rate: 无有效线路负载率记录")
            value, valid_count, skipped_incomplete, skipped_invalid = _max_loading_from_records(
                records, _extract_line_loading_percent, "max_line_loading_rate"
            )
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=valid_count,
                skipped_incomplete=skipped_incomplete,
                skipped_invalid=skipped_invalid,
            )
    elif metric == "max_transformer_loading_rate":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "max_transformer_loading_rate"),
                "max_transformer_loading_rate",
            )
        else:
            records = inputs.get("records") or inputs.get("transformers") or []
            if not isinstance(records, list) or not records:
                raise ValueError("max_transformer_loading_rate: 无有效主变负载率记录")
            value, valid_count, skipped_incomplete, skipped_invalid = _max_loading_from_records(
                records, _extract_transformer_loading_percent, "max_transformer_loading_rate"
            )
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=valid_count,
                skipped_incomplete=skipped_incomplete,
                skipped_invalid=skipped_invalid,
            )
    elif metric == "active_power_loss_rate":
        if direct_value is not None:
            value = _validate_percentage(
                _as_float(direct_value, "active_power_loss_rate"),
                "active_power_loss_rate",
            )
        else:
            loss = _as_float(
                _get(inputs, "loss_mw", "active_power_loss_mw", "loss", "网损"),
                "loss_mw",
            )
            input_power = _as_float(
                _get(inputs, "input_power_mw", "input_power", "区域输入有功功率"),
                "input_power_mw",
            )
            if input_power <= 0:
                raise ValueError(f"input_power_mw must be > 0, got {input_power}")
            value = _validate_percentage(loss / input_power * 100, "active_power_loss_rate")
    elif metric == "critical_section_margin_rate":
        # 允许负裕度；禁止 _validate_percentage。
        if direct_value is not None:
            value = _as_float(direct_value, "critical_section_margin_rate")
        else:
            sections = inputs.get("sections") or inputs.get("records") or []
            margins: list[float] = []
            skipped_incomplete = 0
            skipped_invalid = 0
            for section in sections:
                if not isinstance(section, dict):
                    skipped_incomplete += 1
                    continue
                limit_raw = _get(section, "limit", "security_limit", "限额", "断面安全限额")
                flow_raw = _get(section, "flow", "power", "输送功率", "实际断面输送功率")
                if limit_raw is None or flow_raw is None:
                    skipped_incomplete += 1
                    continue
                limit = _try_float(limit_raw)
                flow = _try_float(flow_raw)
                if limit is None or flow is None:
                    skipped_invalid += 1
                    continue
                limit = _as_float(limit, "limit")
                flow = _as_float(flow, "flow")
                if limit == 0:
                    skipped_invalid += 1
                    continue
                margins.append((limit - abs(flow)) / limit * 100)
            if not margins:
                raise ValueError(
                    "critical_section_margin_rate: 无有效断面记录"
                    f"（skipped_incomplete={skipped_incomplete}, skipped_invalid={skipped_invalid}）"
                )
            value = min(margins)
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=len(margins),
                skipped_incomplete=skipped_incomplete,
                skipped_invalid=skipped_invalid,
            )
    elif metric == "post_contingency_max_equipment_loading_rate":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "post_contingency_max_equipment_loading_rate"),
                "post_contingency_max_equipment_loading_rate",
            )
        else:
            records = (
                inputs.get("records")
                or inputs.get("equipment_records")
                or []
            )
            lines = inputs.get("lines") or []
            transformers = inputs.get("transformers") or []
            combined: list[Any] = []
            if isinstance(records, list):
                combined.extend(records)
            if isinstance(lines, list):
                combined.extend(lines)
            if isinstance(transformers, list):
                combined.extend(transformers)
            if not combined:
                raise ValueError("post_contingency_max_equipment_loading_rate: 无设备负载率记录")
            value, valid_count, skipped_incomplete, skipped_invalid = _max_loading_from_records(
                combined,
                _extract_equipment_loading_percent,
                "post_contingency_max_equipment_loading_rate",
            )
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=valid_count,
                skipped_incomplete=skipped_incomplete,
                skipped_invalid=skipped_invalid,
            )
    elif metric == "post_contingency_voltage_over_limit_rate":
        if direct_value is not None:
            value = _validate_percentage(
                _as_float(direct_value, "post_contingency_voltage_over_limit_rate"),
                "post_contingency_voltage_over_limit_rate",
            )
        elif (
            _get(inputs, "over_limit_pairs", "over_limit_count") is not None
            and _get(inputs, "total_pairs", "total_count") is not None
        ):
            value = _validate_percentage(
                _ratio(
                    _as_float(
                        _get(inputs, "over_limit_pairs", "over_limit_count"),
                        "over_limit_pairs",
                    ),
                    _as_float(_get(inputs, "total_pairs", "total_count"), "total_pairs"),
                    "total_pairs",
                ),
                "post_contingency_voltage_over_limit_rate",
            )
        else:
            records = inputs.get("records") or []
            over_limit = 0
            valid_count = 0
            skipped_incomplete = 0
            skipped_invalid = 0
            default_min = inputs.get("min_voltage")
            default_max = inputs.get("max_voltage")
            for record in records:
                if not isinstance(record, dict):
                    skipped_incomplete += 1
                    continue
                # 故障—节点组合：需能识别故障与节点（或至少电压+限值）
                fault_id = _get(record, "fault_id", "contingency_id", "fault", "故障")
                node_id = _get(record, "node_id", "bus_id", "bus", "节点", "node")
                voltage_raw = _get(record, "voltage", "电压", "voltage_pu", "V")
                min_raw, max_raw = _voltage_limits_from_record(
                    record, default_min=default_min, default_max=default_max
                )
                if voltage_raw is None or min_raw is None or max_raw is None:
                    skipped_incomplete += 1
                    continue
                if fault_id is None and node_id is None and "contingency" not in record:
                    # 仍允许仅电压校核的扁平记录
                    pass
                voltage = _try_float(voltage_raw)
                vmin = _try_float(min_raw)
                vmax = _try_float(max_raw)
                if voltage is None or vmin is None or vmax is None:
                    skipped_invalid += 1
                    continue
                voltage = _as_float(voltage, "voltage")
                vmin = _as_float(vmin, "min_voltage")
                vmax = _as_float(vmax, "max_voltage")
                valid_count += 1
                if voltage < vmin or voltage > vmax:
                    over_limit += 1
            if valid_count == 0:
                raise ValueError(
                    "post_contingency_voltage_over_limit_rate: 无有效故障—节点电压记录"
                    f"（skipped_incomplete={skipped_incomplete}, skipped_invalid={skipped_invalid}）"
                )
            value = _validate_percentage(
                over_limit / valid_count * 100,
                "post_contingency_voltage_over_limit_rate",
            )
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=valid_count,
                skipped_incomplete=skipped_incomplete,
                skipped_invalid=skipped_invalid,
            )
    elif metric == "transient_stability_pass_rate":
        if direct_value is not None:
            value = _validate_percentage(
                _as_float(direct_value, "transient_stability_pass_rate"),
                "transient_stability_pass_rate",
            )
        else:
            value = _validate_percentage(
                _ratio(
                    _as_float(inputs.get("pass_count"), "pass_count"),
                    _as_float(inputs.get("total_count"), "total_count"),
                    "total_count",
                ),
                "transient_stability_pass_rate",
            )
    elif metric == "max_generator_relative_angle_difference":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "max_generator_relative_angle_difference"),
                "max_generator_relative_angle_difference",
            )
        else:
            samples = _iter_generator_angle_samples(inputs)
            if not samples:
                raise ValueError(
                    "max_generator_relative_angle_difference: 数据不足，"
                    "需要 records=[{fault_id,time,angles:[...]}] 或 generator_angles 嵌套结构，"
                    "且每个样本至少 2 个有效功角"
                )
            diffs = [max(angles) - min(angles) for angles in samples]
            value = max(diffs)
            inputs = _mutate_agg_counts(
                inputs,
                valid_count=len(diffs),
                skipped_incomplete=0,
                skipped_invalid=0,
            )
    elif metric == "new_line_length":
        value, inputs = _sum_line_lengths(metric, inputs, direct_value)
    elif metric == "retrofit_line_length":
        value, inputs = _sum_line_lengths(metric, inputs, direct_value)
    elif metric == "annual_energy_loss":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "annual_energy_loss"),
                "annual_energy_loss",
            )
        else:
            loss_mw = _require_non_negative(
                _as_float(
                    _get(inputs, "loss_mw", "active_power_loss_mw", "网损"),
                    "loss_mw",
                ),
                "loss_mw",
            )
            hours = _require_non_negative(
                _as_float(
                    _get(inputs, "equivalent_hours", "annual_equivalent_hours", "年等效网损小时数"),
                    "equivalent_hours",
                ),
                "equivalent_hours",
            )
            value = loss_mw * hours
    elif metric == "annual_network_loss_cost":
        if direct_value is not None:
            value = _require_non_negative(
                _as_float(direct_value, "annual_network_loss_cost"),
                "annual_network_loss_cost",
            )
        else:
            energy = inputs.get("annual_energy_loss_mwh")
            if energy is None:
                energy = inputs.get("annual_energy_loss")
            if energy is None and inputs.get("loss_mw") is not None and (
                inputs.get("equivalent_hours") is not None
                or inputs.get("annual_equivalent_hours") is not None
            ):
                loss_mw = _require_non_negative(
                    _as_float(_get(inputs, "loss_mw", "active_power_loss_mw"), "loss_mw"),
                    "loss_mw",
                )
                hours = _require_non_negative(
                    _as_float(
                        _get(inputs, "equivalent_hours", "annual_equivalent_hours"),
                        "equivalent_hours",
                    ),
                    "equivalent_hours",
                )
                energy = loss_mw * hours
            energy_mwh = _require_non_negative(
                _as_float(energy, "annual_energy_loss_mwh"),
                "annual_energy_loss_mwh",
            )
            price = _require_non_negative(
                _as_float(
                    _get(inputs, "price_per_mwh", "loss_price", "网损电量经济单价"),
                    "price_per_mwh",
                ),
                "price_per_mwh",
            )
            value = energy_mwh * price
    else:
        raise ValueError(f"metric is defined but not implemented: {metric}")

    value = round(value, int(inputs.get("round_digits", 6)))
    level = _classify(value, metric_rule)
    formula = _resolve_metric_formula(metric_rule, inputs)
    return {
        "metric": metric,
        "label": metric_rule.get("label", metric),
        "value": value,
        "unit": metric_rule.get("unit", ""),
        "level": level,
        "formula": formula,
        "comparison_type": metric_rule.get("comparison_type", ""),
        "direction": metric_rule.get("direction", ""),
        "constraint": bool(metric_rule.get("constraint", False)),
        "inputs": inputs,
        "calculate_tag": _build_calculate_tag(metric_rule, inputs, value),
    }


@tool(
    "grid_calculator",
    description=(
        "Calculate deterministic power-grid comparison metrics from JSON input. "
        "Input JSON must include metric and inputs. It accepts either raw calculation "
        "inputs, such as metric=n1_pass_rate with pass_count=95 and total_count=100, "
        "or a direct already-computed metric value from a summary table, such as "
        "metric=line_loading_rate with max_loading_percent=107.94. "
        f"Supported metrics are: {', '.join(SUPPORTED_METRICS)}. "
        "Returns JSON with value, unit, formula, level, and a calculate_tag."
    ),
)
def grid_calculator(request_json: str) -> str:
    try:
        request = json.loads(request_json)
        explicit_inputs = request.get("inputs") if isinstance(request.get("inputs"), dict) else {}
        top_level_inputs = {
            key: value
            for key, value in request.items()
            if key not in {"metric", "inputs"}
        }
        result = calculate_grid_metric(
            metric=str(request.get("metric", "")),
            inputs={**top_level_inputs, **explicit_inputs},
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"error": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )

