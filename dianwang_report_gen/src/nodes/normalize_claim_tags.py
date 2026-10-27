"""报告生成后 claim 标签规范化：纠正错配 id/path/value，处理元→亿元误绑。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.pcn import Claim, VerificationPolicy, VerificationResult, verify_claim

_CLAIM_TAG_RE = re.compile(r"<claim\s+([^>]*)>(.*?)</claim>", re.DOTALL | re.IGNORECASE)

_YUAN_COST_INDICATORS = frozenset(
    {
        "construction_cost",
        "operation_cost",
        "annual_cost",
        "lifecycle_cost",
    }
)

_ATTR_RE = {
    "id": re.compile(r'\bid\s*=\s*"([^"]*)"', re.IGNORECASE),
    "source_path": re.compile(r'\bsource_path\s*=\s*"([^"]*)"', re.IGNORECASE),
    "path_to_value": re.compile(r'\bpath_to_value\s*=\s*"([^"]*)"', re.IGNORECASE),
    "policy": re.compile(r'\bpolicy\s*=\s*"([^"]*)"', re.IGNORECASE),
}


def _strip_verify_marks(text: str) -> str:
    cleaned = re.sub(r"<sup\b[^>]*>.*?</sup>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<span class="verified-mark"[^>]*>.*?</span>', "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<span class="verify-pending"[^>]*>.*?</span>', "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<span class="verify-not-found"[^>]*>.*?</span>', "", cleaned, flags=re.DOTALL)
    return cleaned.strip()


def _parse_display_number(text: str) -> Optional[float]:
    cleaned = _strip_verify_marks(text)
    cleaned = cleaned.replace(",", "").replace("%", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _format_raw_value(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    text = f"{number:.10f}".rstrip("0").rstrip(".")
    return text or "0"


def _claim_meta(claim: Claim) -> Dict[str, Any]:
    return claim.metadata if isinstance(claim.metadata, dict) else {}


def _claim_path(claim: Claim) -> str:
    meta = _claim_meta(claim)
    return str(meta.get("path_to_value") or "")


def _claim_source(claim: Claim) -> str:
    meta = _claim_meta(claim)
    return str(meta.get("source_path") or "")


def _claim_unit(claim: Claim) -> str:
    return str(claim.unit or "")


def _claim_indicator(claim: Claim) -> str:
    return str(claim.indicator or "")


def _norm_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lower()


def _values_compatible(display: float, expected: float, policy: VerificationPolicy) -> bool:
    result, _ = verify_claim(
        text_value=str(display),
        reference_value=expected,
        policy=policy,
        surrounding_text=str(display),
    )
    return result == VerificationResult.VERIFIED


def _is_yi_yuan_display(display: float, expected_yuan: float, rel_tol: float = 1e-4) -> bool:
    if expected_yuan == 0:
        return abs(display) < 1e-12
    scaled = display * 100000000.0
    return abs(scaled - expected_yuan) <= max(abs(expected_yuan) * rel_tol, 1e-6)


def _is_wan_yuan_display(display: float, expected_yuan: float, rel_tol: float = 1e-4) -> bool:
    if expected_yuan == 0:
        return abs(display) < 1e-12
    scaled = display * 10000.0
    return abs(scaled - expected_yuan) <= max(abs(expected_yuan) * rel_tol, 1e-6)


def _policy_of(claim: Claim, tag_policy: str) -> VerificationPolicy:
    if claim.policy is not None:
        return claim.policy
    if tag_policy:
        return VerificationPolicy.from_string(tag_policy)
    return VerificationPolicy.from_string("exact")


def _build_claim_tag(claim: Claim, display_value: Optional[str] = None) -> str:
    meta = _claim_meta(claim)
    source_path = meta.get("source_path", "")
    path_to_value = meta.get("path_to_value", "")
    policy = claim.get_policy_string() if claim.policy else "exact"
    value_text = display_value if display_value is not None else _format_raw_value(claim.value)
    return (
        f'<claim id="{claim.claim_id}" source_path="{source_path}" '
        f'path_to_value="{path_to_value}" policy="{policy}">{value_text}</claim>'
    )


def _build_unit_convert_calculate(
    claim: Claim,
    display_yi: float,
    *,
    scale: int,
    output_unit_name: str,
) -> str:
    indicator = _claim_indicator(claim) or "cost"
    raw = _format_raw_value(claim.value)
    out = _format_raw_value(display_yi)
    var_yuan = f"{indicator}_yuan"
    var_out = f"{indicator}_{output_unit_name}"
    return (
        "<calculate> "
        f"input: {var_yuan}={raw}; "
        f"input_source: {var_yuan}=claim_{claim.claim_id}; "
        f"formula: {var_out} = {var_yuan} / {scale}; "
        f"output: {out} "
        "</calculate>"
    )


def _index_claims(
    pcn_claims: Dict[str, Claim],
) -> Tuple[Dict[str, Claim], Dict[str, List[Claim]]]:
    by_id: Dict[str, Claim] = {}
    by_path: Dict[str, List[Claim]] = {}
    for key, claim in (pcn_claims or {}).items():
        if not isinstance(claim, Claim):
            continue
        cid = str(claim.claim_id or key)
        by_id[cid] = claim
        path_key = _norm_path(_claim_path(claim))
        if path_key:
            by_path.setdefault(path_key, []).append(claim)
    return by_id, by_path


def _find_by_path_and_value(
    by_path: Dict[str, List[Claim]],
    path_to_value: str,
    display_value: Optional[float],
) -> Optional[Claim]:
    candidates = by_path.get(_norm_path(path_to_value), [])
    if not candidates:
        return None
    if display_value is None:
        return candidates[0] if len(candidates) == 1 else None
    matched = [
        c
        for c in candidates
        if _values_compatible(display_value, float(c.value), VerificationPolicy.from_string("exact"))
        or _values_compatible(
            display_value, float(c.value), VerificationPolicy.from_string("round(6)")
        )
    ]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        # 优先指标名与 path 一致者
        path_lower = path_to_value.lower()
        tighter = [c for c in matched if c.indicator and c.indicator in path_lower]
        if len(tighter) == 1:
            return tighter[0]
    return None


def _attrs_from_tag(tag_attrs: str) -> Dict[str, str]:
    result = {}
    for key, pattern in _ATTR_RE.items():
        match = pattern.search(tag_attrs or "")
        result[key] = match.group(1) if match else ""
    return result


def normalize_claim_tags_in_report(
    report_content: str,
    pcn_claims: Dict[str, Claim],
) -> Tuple[str, Dict[str, Any]]:
    """规范化报告中的 claim 标签，返回 (新报告, 统计)。"""
    if not report_content:
        return report_content or "", {
            "total_tags": 0,
            "rewritten": 0,
            "converted_to_calculate": 0,
            "stripped": 0,
            "unchanged": 0,
            "warnings": [],
        }

    by_id, by_path = _index_claims(pcn_claims)
    stats: Dict[str, Any] = {
        "total_tags": 0,
        "rewritten": 0,
        "converted_to_calculate": 0,
        "stripped": 0,
        "unchanged": 0,
        "warnings": [],
    }

    def replace(match: re.Match) -> str:
        stats["total_tags"] += 1
        tag_attrs = match.group(1)
        inner = match.group(2)
        attrs = _attrs_from_tag(tag_attrs)
        claim_id = attrs.get("id", "")
        path_to_value = attrs.get("path_to_value", "")
        source_path = attrs.get("source_path", "")
        tag_policy = attrs.get("policy", "") or "exact"
        display_raw = _strip_verify_marks(inner)
        display_num = _parse_display_number(display_raw)

        claim = by_id.get(claim_id)
        resolved: Optional[Claim] = None
        action = "keep"

        if claim is not None:
            policy = _policy_of(claim, tag_policy)
            path_ok = (not path_to_value) or (
                _norm_path(path_to_value) == _norm_path(_claim_path(claim))
            )
            source_ok = (not source_path) or (
                _norm_path(source_path) == _norm_path(_claim_source(claim))
            )
            value_ok = display_num is None or _values_compatible(
                display_num, float(claim.value), policy
            )

            if path_ok and source_ok and value_ok:
                # 属性以数据库为准整体重写，避免模型拼接
                rebuilt = _build_claim_tag(claim, display_value=display_raw or _format_raw_value(claim.value))
                if rebuilt != match.group(0):
                    stats["rewritten"] += 1
                    action = "sync_attrs"
                else:
                    stats["unchanged"] += 1
                    action = "unchanged"
                logger.debug(f"claim normalize [{action}] id={claim_id}")
                return rebuilt

            # 元→亿元误绑：标签数值是亿元，claim 是元
            if display_num is not None and _is_yi_yuan_display(display_num, float(claim.value)):
                if (
                    _claim_indicator(claim) in _YUAN_COST_INDICATORS
                    or "cost" in _claim_indicator(claim)
                    or "元" in _claim_unit(claim)
                ):
                    stats["converted_to_calculate"] += 1
                    warning = (
                        f"claim {claim_id} 显示亿元数值 {display_num}，"
                        f"已改为 /100000000 的 calculate（原始值 {claim.value} 元）"
                    )
                    stats["warnings"].append(warning)
                    logger.warning(warning)
                    return _build_unit_convert_calculate(
                        claim, display_num, scale=100000000, output_unit_name="yi_yuan"
                    )

            if display_num is not None and _is_wan_yuan_display(display_num, float(claim.value)):
                if _claim_indicator(claim) in _YUAN_COST_INDICATORS or "元" in _claim_unit(claim):
                    stats["converted_to_calculate"] += 1
                    warning = (
                        f"claim {claim_id} 显示万元数值 {display_num}，"
                        f"已改为 /10000 的 calculate（原始值 {claim.value} 元）"
                    )
                    stats["warnings"].append(warning)
                    logger.warning(warning)
                    return _build_unit_convert_calculate(
                        claim, display_num, scale=10000, output_unit_name="wan_yuan"
                    )

            # path 指向正确指标但 id 错了：按 path + 显示值找正确 claim
            if path_to_value:
                resolved = _find_by_path_and_value(by_path, path_to_value, display_num)
                if resolved is not None and resolved.claim_id != claim_id:
                    stats["rewritten"] += 1
                    warning = (
                        f"claim_id={claim_id} 与 path/value 不一致，"
                        f"已替换为 {resolved.claim_id}（path={path_to_value}）"
                    )
                    stats["warnings"].append(warning)
                    logger.warning(warning)
                    return _build_claim_tag(
                        resolved,
                        display_value=_format_raw_value(resolved.value),
                    )

            # id 正确但显示值错误：恢复为原始 claim 值
            if path_ok and source_ok and display_num is not None and not value_ok:
                stats["rewritten"] += 1
                warning = (
                    f"claim {claim_id} 显示值 {display_raw} 与数据库值 {claim.value} 不一致，"
                    "已恢复为原始值"
                )
                stats["warnings"].append(warning)
                logger.warning(warning)
                return _build_claim_tag(claim)

        # claim_id 不存在或无法自愈：按 path+value 查找
        if path_to_value:
            resolved = _find_by_path_and_value(by_path, path_to_value, display_num)
            if resolved is not None:
                stats["rewritten"] += 1
                warning = (
                    f"无法用 claim_id={claim_id!r} 定位证据，"
                    f"已按 path_to_value 替换为 {resolved.claim_id}"
                )
                stats["warnings"].append(warning)
                logger.warning(warning)
                return _build_claim_tag(
                    resolved,
                    display_value=_format_raw_value(resolved.value),
                )

        # 无法唯一定位：去掉标签，保留数字
        stats["stripped"] += 1
        warning = (
            f"无法规范 claim_id={claim_id!r} path={path_to_value!r} value={display_raw!r}，"
            "已移除 claim 标签"
        )
        stats["warnings"].append(warning)
        logger.warning(warning)
        return display_raw

    normalized = _CLAIM_TAG_RE.sub(replace, report_content)
    logger.info(
        "claim 标签规范化完成: "
        f"total={stats['total_tags']}, rewritten={stats['rewritten']}, "
        f"to_calculate={stats['converted_to_calculate']}, "
        f"stripped={stats['stripped']}, unchanged={stats['unchanged']}"
    )
    return normalized, stats
