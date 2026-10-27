"""安全硬约束驱动的推荐结论后处理。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from src.tools.grid_calculator import get_n1_pass_rate_hard_threshold

MISSING = "当前输入不足，未评价"

KEY_SAFETY_METRICS = (
    "pf_convergence",
    "n1_pass_rate",
    "min_breaker_interrupt_margin_rate",
    "short_circuit_over_limit_count",
    "post_contingency_max_equipment_loading_rate",
)

_SAFETY_CONCLUSION_MARKER = "<!-- safety-hard-constraint-conclusion -->"
_SAFETY_MARKER_RE = re.compile(
    r"<!--\s*safety-hard-constraint-conclusion(?:\s+fingerprint=([a-f0-9]+))?\s*-->",
    re.IGNORECASE,
)
_LEGACY_EXTERNAL_FINGERPRINT_RE = re.compile(
    r"<!--\s*safety-hard-constraint-conclusion\s*-->\s*fingerprint=([a-f0-9]+)",
    re.IGNORECASE,
)

_CN_DIGIT_MAP = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_RECOMMEND_NUM_PATTERNS = (
    re.compile(r"本阶段推荐方案\s*(?P<num>\d+)(?!\d)", re.IGNORECASE),
    re.compile(r"最终推荐方案\s*(?P<num>\d+)(?!\d)", re.IGNORECASE),
    re.compile(r"建议优先实施方案\s*(?P<num>\d+)(?!\d)", re.IGNORECASE),
    re.compile(r"推荐方案\s*(?P<num>\d+)(?!\d)", re.IGNORECASE),
)

_RECOMMEND_CN_PATTERNS = (
    re.compile(r"本阶段推荐方案\s*(?P<cn>[一二三四五六七八九十]+)", re.IGNORECASE),
    re.compile(r"最终推荐方案\s*(?P<cn>[一二三四五六七八九十]+)", re.IGNORECASE),
    re.compile(r"建议优先实施方案\s*(?P<cn>[一二三四五六七八九十]+)", re.IGNORECASE),
    re.compile(r"推荐方案\s*(?P<cn>[一二三四五六七八九十]+)", re.IGNORECASE),
)

_QUOTED_NAME_PATTERNS = (
    re.compile(r"(?:推荐|建议优先实施)[“\"](?P<name>[^”\"]+)[”\"]"),
    re.compile(r"(?:最终推荐)[“\"](?P<name>[^”\"]+)[”\"]"),
)

_FORBIDDEN_RECOMMEND_LINE_PATTERNS = (
    re.compile(r"^.*(?:共性短板|共性问题).*(?:不影响|无法作为区分).*$", re.MULTILINE),
    re.compile(r"^.*短路[^\n]{0,20}共性问题[^\n]{0,30}不影响.*$", re.MULTILINE),
)

_COMMON_MISCONCEPTION_REPLACEMENTS = (
    (
        re.compile(r"然而该问题是共性短板，无法作为区分方案优劣的依据。"),
        "该短路开断能力不足属于安全硬约束不满足，即便各方案均存在，仍不得忽略，不得据此直接推荐任一方案实施。",
    ),
    (
        re.compile(r"短路电流超标为共性问题，不影响相对排序[；;]?"),
        "短路电流超标属于安全硬约束问题，不能因共性而忽略；",
    ),
)


def _metric_entry(scheme: Dict[str, Any], key: str) -> Dict[str, Any]:
    metrics = scheme.get("metrics") or {}
    entry = metrics.get(key) or {}
    return entry if isinstance(entry, dict) else {}


def _metric_value(scheme: Dict[str, Any], key: str) -> Optional[float]:
    entry = _metric_entry(scheme, key)
    if entry.get("status") in ("missing_data", "invalid_data", "not_applicable"):
        return None
    value = entry.get("value")
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _metric_is_available(scheme: Dict[str, Any], key: str) -> bool:
    if key == "pf_convergence":
        return _pf_convergence_value(scheme) is not None
    return _metric_value(scheme, key) is not None


def _pf_convergence_value(scheme: Dict[str, Any]) -> Optional[bool]:
    pf = _metric_entry(scheme, "pf_convergence")
    if pf.get("status") in ("missing_data", "invalid_data", "not_applicable"):
        return None
    display = str(pf.get("display_value") or "")
    value = pf.get("value")
    if display in ("是", "否"):
        return display == "是"
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number >= 0.5


def _scheme_label(scheme: Dict[str, Any]) -> str:
    return str(scheme.get("proposal_name") or f"方案{scheme.get('proposal_index', '?')}")


def _parse_chinese_numeral(text: str) -> Optional[int]:
    token = (text or "").strip()
    if not token:
        return None
    if token == "十":
        return 10
    if token.startswith("十") and len(token) == 2 and token[1] in _CN_DIGIT_MAP:
        return 10 + _CN_DIGIT_MAP[token[1]]
    if token.endswith("十") and len(token) == 2 and token[0] in _CN_DIGIT_MAP:
        return _CN_DIGIT_MAP[token[0]] * 10
    if "十" in token and len(token) == 3:
        left, mid, right = token[0], token[1], token[2]
        if mid == "十" and left in _CN_DIGIT_MAP and right in _CN_DIGIT_MAP:
            return _CN_DIGIT_MAP[left] * 10 + _CN_DIGIT_MAP[right]
    if len(token) == 1 and token in _CN_DIGIT_MAP:
        return _CN_DIGIT_MAP[token]
    return None


def evaluate_scheme_hard_constraints(
    scheme: Dict[str, Any],
    *,
    n1_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """返回结构化硬约束评价结果。"""
    threshold = n1_threshold if n1_threshold is not None else get_n1_pass_rate_hard_threshold()[0]
    missing_metrics: List[str] = []
    evaluated_metrics: List[str] = []
    reasons: List[str] = []

    for key in KEY_SAFETY_METRICS:
        if not _metric_is_available(scheme, key):
            missing_metrics.append(key)
            continue
        evaluated_metrics.append(key)

    pf = _pf_convergence_value(scheme)
    if pf is False:
        reasons.append("基态潮流不收敛")

    n1_rate = _metric_value(scheme, "n1_pass_rate")
    if n1_rate is not None and n1_rate < threshold:
        reasons.append(f"N-1通过率低于规则要求（{n1_rate}% < {threshold}%）")

    margin = _metric_value(scheme, "min_breaker_interrupt_margin_rate")
    if margin is not None and margin < 0:
        reasons.append(f"最小断路器开断裕度率为负（{margin}%）")

    over_count = _metric_value(scheme, "short_circuit_over_limit_count")
    if over_count is not None and over_count > 0:
        count_text = int(over_count) if over_count == int(over_count) else over_count
        reasons.append(f"短路越限节点数={count_text}")

    loading = _metric_value(scheme, "post_contingency_max_equipment_loading_rate")
    if loading is not None and loading > 100:
        reasons.append(f"故障后最大设备负载率超过100%（{loading}%）")

    if reasons:
        status = "failed"
    elif missing_metrics:
        status = "not_evaluated"
    else:
        status = "passed"

    return {
        "status": status,
        "reasons": reasons,
        "missing_metrics": missing_metrics,
        "evaluated_metrics": evaluated_metrics,
    }


def analyze_safety_for_recommendation(derived: Dict[str, Any]) -> Dict[str, Any]:
    n1_threshold, rules_source = get_n1_pass_rate_hard_threshold()
    applied_thresholds = {"n1_pass_rate": n1_threshold}

    schemes = derived.get("schemes") if isinstance(derived, dict) else None
    if not isinstance(schemes, list) or not schemes:
        return {
            "has_schemes": False,
            "all_failed": False,
            "any_passed": False,
            "no_proven_safe_scheme": True,
            "failed_schemes": [],
            "passed_schemes": [],
            "not_evaluated_schemes": [],
            "best_economy_among_all": None,
            "best_economy_among_passed": None,
            "applied_thresholds": applied_thresholds,
            "rules_source": rules_source,
        }

    failed: List[Dict[str, Any]] = []
    passed: List[Dict[str, Any]] = []
    not_evaluated: List[Dict[str, Any]] = []

    for scheme in schemes:
        evaluation = evaluate_scheme_hard_constraints(scheme, n1_threshold=n1_threshold)
        item = {
            "label": _scheme_label(scheme),
            "index": scheme.get("proposal_index"),
            "status": evaluation["status"],
            "passed": evaluation["status"] == "passed",
            "reasons": evaluation["reasons"],
            "missing_metrics": evaluation["missing_metrics"],
            "evaluated_metrics": evaluation["evaluated_metrics"],
            "annual_cost": _metric_value(scheme, "annual_cost"),
            "construction_cost": _metric_value(scheme, "construction_cost"),
        }
        if evaluation["status"] == "passed":
            passed.append(item)
        elif evaluation["status"] == "failed":
            failed.append(item)
        else:
            not_evaluated.append(item)

    def _best_econ(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        ranked = [x for x in items if isinstance(x.get("annual_cost"), (int, float))]
        if not ranked:
            ranked = [
                x for x in items if isinstance(x.get("construction_cost"), (int, float))
            ]
            if not ranked:
                return None
            return min(ranked, key=lambda x: float(x["construction_cost"]))
        return min(ranked, key=lambda x: float(x["annual_cost"]))

    all_failed = bool(schemes) and len(failed) == len(schemes)
    no_proven_safe_scheme = len(passed) == 0

    return {
        "has_schemes": True,
        "all_failed": all_failed,
        "any_passed": len(passed) > 0,
        "no_proven_safe_scheme": no_proven_safe_scheme,
        "failed_schemes": failed,
        "passed_schemes": passed,
        "not_evaluated_schemes": not_evaluated,
        "best_economy_among_all": _best_econ(failed + not_evaluated + passed),
        "best_economy_among_passed": _best_econ(passed),
        "applied_thresholds": applied_thresholds,
        "rules_source": rules_source,
    }


def load_derived_metrics_dict(working_dir: Optional[Path]) -> Dict[str, Any]:
    if not working_dir:
        return {}
    path = Path(working_dir) / "derived_metrics.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"读取 derived_metrics.json 失败: {exc}")
        return {}


def _scheme_lookup(analysis: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for bucket in ("passed_schemes", "failed_schemes", "not_evaluated_schemes"):
        for item in analysis.get(bucket) or []:
            label = str(item.get("label") or "")
            if label:
                lookup[label] = item
            index = item.get("index")
            if index is not None:
                lookup[f"方案{index}"] = item
    return lookup


def identify_recommended_schemes(
    report: str, lookup: Dict[str, Dict[str, Any]]
) -> List[str]:
    """从原始报告中识别被推荐的方案 label，保持出现顺序。"""
    found: List[str] = []
    seen: Set[str] = set()

    def _add_label(label: str) -> None:
        if label in lookup and label not in seen:
            found.append(label)
            seen.add(label)

    for pattern in _RECOMMEND_NUM_PATTERNS:
        for match in pattern.finditer(report):
            num = match.group("num")
            if num:
                _add_label(f"方案{num}")

    for pattern in _RECOMMEND_CN_PATTERNS:
        for match in pattern.finditer(report):
            cn = match.group("cn")
            num = _parse_chinese_numeral(cn)
            if num is not None:
                _add_label(f"方案{num}")

    for pattern in _QUOTED_NAME_PATTERNS:
        for match in pattern.finditer(report):
            name = match.group("name").strip()
            if name in lookup:
                _add_label(name)

    for label in lookup:
        if label.startswith("方案"):
            continue
        name_pattern = re.compile(
            rf"(?:推荐|建议优先实施|最终推荐).{{0,12}}{re.escape(label)}"
        )
        if name_pattern.search(report):
            _add_label(label)

    return found


def classify_recommended_schemes(
    recommended: List[str], lookup: Dict[str, Dict[str, Any]]
) -> Dict[str, List[str]]:
    passed_recommended: List[str] = []
    failed_recommended: List[str] = []
    not_evaluated_recommended: List[str] = []

    for label in recommended:
        item = lookup.get(label)
        if not item:
            continue
        status = item.get("status")
        if status == "passed":
            passed_recommended.append(label)
        elif status == "failed":
            failed_recommended.append(label)
        else:
            not_evaluated_recommended.append(label)

    return {
        "passed_recommended": passed_recommended,
        "failed_recommended": failed_recommended,
        "not_evaluated_recommended": not_evaluated_recommended,
    }


def _remove_forbidden_misconception_lines(text: str) -> str:
    cleaned = text
    for pattern in _FORBIDDEN_RECOMMEND_LINE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    for pattern, replacement in _COMMON_MISCONCEPTION_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _index_chinese_variants(index: Any) -> List[str]:
    try:
        num = int(index)
    except (TypeError, ValueError):
        return []
    mapping = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }
    token = mapping.get(num)
    return [token] if token else []


def _recommendation_removal_patterns(item: Dict[str, Any]) -> List[str]:
    patterns: List[str] = []
    num = item.get("index")
    if num is not None:
        patterns.extend(
            [
                rf"^.*本阶段推荐方案\s*{num}(?!\d).*$",
                rf"^.*最终推荐方案\s*{num}(?!\d).*$",
                rf"^.*推荐方案\s*{num}(?!\d).*$",
                rf"^.*建议优先实施方案\s*{num}(?!\d).*$",
            ]
        )
        for cn in _index_chinese_variants(num):
            patterns.extend(
                [
                    rf"^.*本阶段推荐方案\s*{cn}.*$",
                    rf"^.*最终推荐方案\s*{cn}.*$",
                    rf"^.*推荐方案\s*{cn}.*$",
                    rf"^.*建议优先实施方案\s*{cn}.*$",
                ]
            )
    name = item.get("label")
    if name and not str(name).startswith("方案"):
        patterns.append(
            rf"^.*(?:推荐|建议优先实施|最终推荐).*{re.escape(str(name))}.*$"
        )
    return patterns


def _remove_invalid_recommendation_lines(
    text: str,
    labels_to_remove: List[str],
    lookup: Dict[str, Dict[str, Any]],
) -> str:
    cleaned = text
    for label in labels_to_remove:
        item = lookup.get(label) or {}
        for pattern in _recommendation_removal_patterns(item):
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def _build_passed_recommendation_paragraph(best: Dict[str, Any]) -> str:
    label = best.get("label") or "通过安全硬约束的方案"
    return (
        f"根据安全硬约束优先原则，在通过硬约束校核的方案中，"
        f"**{label}** 在经济性排序中领先，可作为本阶段推荐方案。"
        f"该推荐仅基于已证明安全合格的候选方案，未通过硬约束或数据不足方案不得直接推荐实施。"
    )


def _build_failed_correction_note(
    item: Dict[str, Any], best_passed: Dict[str, Any]
) -> str:
    label = item.get("label") or "原推荐方案"
    reasons = "、".join(item.get("reasons") or []) or "安全硬约束不满足"
    passed_label = best_passed.get("label") or "通过硬约束的方案"
    return (
        f"原推荐 **{label}** 未通过安全硬约束校核（{reasons}），已取消直接推荐。"
        f"在已通过硬约束的方案中，**{passed_label}** 经济性相对最优，可作为本阶段推荐方案。"
    )


def _build_not_evaluated_correction_note(
    item: Dict[str, Any], best_passed: Dict[str, Any]
) -> str:
    label = item.get("label") or "原推荐方案"
    missing = "、".join(item.get("missing_metrics") or []) or "关键安全指标"
    passed_label = best_passed.get("label") or "通过硬约束的方案"
    return (
        f"原推荐 **{label}** 因安全指标数据不足（缺失：{missing}），"
        f"仅可称为**待补充数据方案**，已取消直接推荐。"
        f"在已通过硬约束的方案中，**{passed_label}** 经济性相对最优，可作为本阶段推荐方案。"
    )


def _build_no_proven_safe_paragraph(analysis: Dict[str, Any]) -> str:
    failed = analysis.get("failed_schemes") or []
    not_evaluated = analysis.get("not_evaluated_schemes") or []
    best = analysis.get("best_economy_among_all") or {}
    best_label = best.get("label") or "经济性排序领先方案"

    uniq_reasons: List[str] = []
    for item in failed:
        for reason in item.get("reasons") or []:
            if reason not in uniq_reasons:
                uniq_reasons.append(reason)
    reason_text = "、".join(uniq_reasons[:6]) if uniq_reasons else "安全硬约束不满足"

    parts = [
        "根据安全硬约束优先原则，**当前没有可直接推荐实施的方案**。"
    ]
    if failed:
        parts.append(
            f"共有 {len(failed)} 个方案存在明确硬约束失败（主要包括：{reason_text}），"
            f"仅可称为**整改后的经济优先候选**，须整改后重新仿真与校核，"
            f"不得称为最终推荐方案，亦不得建议直接实施。"
        )
    if not_evaluated:
        parts.append(
            f"另有 {len(not_evaluated)} 个方案因关键安全指标数据不足，"
            f"仅可称为**待补充数据方案**，须补充仿真数据后再进行安全校核。"
        )
    if best_label:
        parts.append(
            f"在经济性排序中，{best_label} 相对领先，"
            f"但在安全硬约束未证明合格前，不得作为可直接实施的最终推荐。"
        )
    return "".join(parts)


def _build_safety_conclusion(
    analysis: Dict[str, Any],
    classified: Dict[str, List[str]],
) -> Optional[str]:
    if not analysis.get("has_schemes"):
        return None

    lookup = _scheme_lookup(analysis)
    passed_recommended = classified.get("passed_recommended") or []
    failed_recommended = classified.get("failed_recommended") or []
    not_evaluated_recommended = classified.get("not_evaluated_recommended") or []
    invalid_recommended = failed_recommended + not_evaluated_recommended

    if analysis.get("any_passed"):
        best_passed = analysis.get("best_economy_among_passed") or {}
        notes: List[str] = []

        for label in failed_recommended:
            item = lookup.get(label)
            if item and best_passed:
                notes.append(_build_failed_correction_note(item, best_passed))

        for label in not_evaluated_recommended:
            item = lookup.get(label)
            if item and best_passed:
                notes.append(_build_not_evaluated_correction_note(item, best_passed))

        if notes:
            return "\n\n".join(notes)

        if passed_recommended and not invalid_recommended:
            return None

        if best_passed and (invalid_recommended or not passed_recommended):
            return _build_passed_recommendation_paragraph(best_passed)

        return None

    if analysis.get("no_proven_safe_scheme"):
        return _build_no_proven_safe_paragraph(analysis)

    return None


def _safety_analysis_fingerprint(analysis: Dict[str, Any]) -> str:
    schemes_payload: List[Dict[str, Any]] = []
    for bucket in ("passed_schemes", "failed_schemes", "not_evaluated_schemes"):
        for item in analysis.get(bucket) or []:
            schemes_payload.append(
                {
                    "index": item.get("index"),
                    "label": item.get("label"),
                    "status": item.get("status"),
                    "reasons": item.get("reasons") or [],
                    "missing_metrics": item.get("missing_metrics") or [],
                }
            )
    schemes_payload.sort(key=lambda x: (x.get("index") is None, x.get("index"), x.get("label")))

    best = analysis.get("best_economy_among_passed") or {}
    payload = {
        "has_schemes": analysis.get("has_schemes"),
        "any_passed": analysis.get("any_passed"),
        "no_proven_safe_scheme": analysis.get("no_proven_safe_scheme"),
        "schemes": schemes_payload,
        "best_passed_index": best.get("index"),
        "best_passed_label": best.get("label"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def _strip_safety_marker_block(report: str) -> str:
    if not report:
        return report or ""
    return _safety_marker_block_pattern().sub("", report, count=1).strip()


def _extract_existing_fingerprint(report: str) -> Optional[str]:
    match = _SAFETY_MARKER_RE.search(report or "")
    if match and match.group(1):
        return match.group(1)
    legacy = _LEGACY_EXTERNAL_FINGERPRINT_RE.search(report or "")
    if legacy:
        return legacy.group(1)
    if match:
        return ""
    return None


def _safety_marker_line(fingerprint: Optional[str] = None) -> str:
    if fingerprint:
        return f"<!-- safety-hard-constraint-conclusion fingerprint={fingerprint} -->"
    return _SAFETY_CONCLUSION_MARKER


def _safety_marker_block_pattern() -> re.Pattern[str]:
    return re.compile(
        r"<!--\s*safety-hard-constraint-conclusion(?:\s+fingerprint=[a-f0-9]+)?\s*-->"
        r"(?:\s*fingerprint=[a-f0-9]+)?\s*\n[\s\S]*?(?=\n####\s|\n##\s|\Z)",
        re.MULTILINE | re.IGNORECASE,
    )


def _extract_safety_conclusion_paragraph(report: str) -> Optional[str]:
    match = _safety_marker_block_pattern().search(report or "")
    if not match:
        return None
    lines = match.group(0).splitlines()
    body: List[str] = []
    for line in lines[1:]:
        if re.match(r"^\s*fingerprint=", line, re.IGNORECASE):
            continue
        body.append(line)
    paragraph = "\n".join(body).strip()
    return paragraph or None


def _find_recommendation_section_span(text: str) -> Optional[Tuple[int, int]]:
    match = re.search(
        r"(####\s*综合比较(?:推荐方案|与结论)\s*\n)([\s\S]*?)(?=\n####\s|\n##\s|\Z)",
        text,
    )
    if not match:
        return None
    return match.start(2), match.end(2)


def _insert_or_replace_safety_conclusion(
    text: str, paragraph: str, fingerprint: str
) -> str:
    marker_block = f"{_safety_marker_line(fingerprint)}\n{paragraph}\n"
    block_pattern = _safety_marker_block_pattern()
    if block_pattern.search(text):
        return block_pattern.sub(marker_block.rstrip(), text, count=1)

    span = _find_recommendation_section_span(text)
    if span is not None:
        start, end = span
        body = text[start:end].rstrip()
        new_body = f"{body}\n\n{marker_block}".rstrip()
        return text[:start] + new_body + text[end:]

    if not re.search(r"####\s*综合比较(?:推荐方案|与结论)", text):
        return text.rstrip() + "\n\n#### 综合比较推荐方案\n\n" + marker_block
    return text


def enforce_safety_recommendation(report: str, analysis: Dict[str, Any]) -> str:
    """校验并修正报告中的推荐结论，使其与安全硬约束评价一致。"""
    if not report or not analysis.get("has_schemes"):
        return report

    fingerprint = _safety_analysis_fingerprint(analysis)
    existing_fp = _extract_existing_fingerprint(report)
    if existing_fp == fingerprint:
        return report
    if existing_fp == "":
        preserved = _extract_safety_conclusion_paragraph(report)
        if preserved:
            return _insert_or_replace_safety_conclusion(report, preserved, fingerprint)

    lookup = _scheme_lookup(analysis)
    scan_report = _strip_safety_marker_block(report)

    original_recommended = identify_recommended_schemes(scan_report, lookup)
    classified = classify_recommended_schemes(original_recommended, lookup)

    invalid_labels = (
        classified.get("failed_recommended") or []
    ) + (classified.get("not_evaluated_recommended") or [])

    text = report if existing_fp is None else scan_report
    span = _find_recommendation_section_span(text)
    if span is not None:
        start, end = span
        section_body = text[start:end]
        section_body = _remove_forbidden_misconception_lines(section_body)
        section_body = _remove_invalid_recommendation_lines(
            section_body, invalid_labels, lookup
        )
        text = text[:start] + section_body + text[end:]
    else:
        text = _remove_forbidden_misconception_lines(text)
        text = _remove_invalid_recommendation_lines(text, invalid_labels, lookup)

    conclusion = _build_safety_conclusion(analysis, classified)
    if conclusion:
        text = _insert_or_replace_safety_conclusion(text, conclusion, fingerprint)
    elif existing_fp is not None and existing_fp != fingerprint:
        text = _strip_safety_marker_block(text)

    logger.info(
        "已执行安全硬约束推荐后处理："
        f"passed={len(analysis.get('passed_schemes') or [])}, "
        f"failed={len(analysis.get('failed_schemes') or [])}, "
        f"not_evaluated={len(analysis.get('not_evaluated_schemes') or [])}, "
        f"original_recommended={original_recommended}, fingerprint={fingerprint}"
    )
    return text
