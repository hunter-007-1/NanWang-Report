"""报告内 <calculate> 标签的安全解析与公式校验。"""

from __future__ import annotations

import ast
import html
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from src.pcn import Claim
from src.tools.grid_calculator import resolve_compare_rules_value

_CALCULATE_TAG_RE = re.compile(r"<calculate>(.*?)</calculate>", re.DOTALL | re.IGNORECASE)
_FIELD_SPLIT_RE = re.compile(
    r"(input_source|input|formula|output)\s*:\s*",
    re.IGNORECASE,
)
_INPUT_SEGMENT_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*$"
)
_VAR_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)\s*$")
_STRICT_CLAIM_REF_RE = re.compile(r"^claim[_\s-]?(\d{6})$", re.IGNORECASE)
_STRICT_COMPARE_RULES_RE = re.compile(r"^compare_rules(?:\.[A-Za-z0-9_]+)+$", re.IGNORECASE)
_OUTPUT_NUMBER_RE = re.compile(
    r"^([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?)$"
)
_NON_FINITE_LITERAL_RE = re.compile(
    r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:(?:[+-]?inf(?:inity)?)|nan)\s*$",
    re.IGNORECASE,
)

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)

_REL_TOL = 1e-4
_ABS_TOL = 1e-6


def _parse_calculate_fields(content: str) -> Dict[str, str]:
    text = (content or "").strip()
    if not text:
        return {}
    parts: Dict[str, str] = {}
    matches = list(_FIELD_SPLIT_RE.finditer(text))
    for idx, match in enumerate(matches):
        key = match.group(1).lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = text[start:end].strip().strip(";,")
        if key in parts and parts[key]:
            parts[key] = f"{parts[key]}; {value}"
        else:
            parts[key] = value
    return parts


def _split_field_segments(field_text: str) -> List[str]:
    if not field_text:
        return []
    normalized = field_text.replace("\n", " ")
    return [segment.strip() for segment in re.split(r"[;,]", normalized) if segment.strip()]


def _parse_input_variables(input_text: str) -> Dict[str, Any]:
    """严格解析 input 字段，返回结构化结果。"""
    result: Dict[str, Any] = {
        "variables": {},
        "invalid_segments": [],
        "duplicate_conflicts": [],
        "warnings": [],
    }
    if not input_text:
        return result

    variables: Dict[str, float] = {}
    for segment in _split_field_segments(input_text):
        if re.match(r"^\s*=", segment):
            result["invalid_segments"].append(segment)
            continue
        if re.match(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*$", segment):
            result["invalid_segments"].append(segment)
            continue
        if _NON_FINITE_LITERAL_RE.match(segment):
            result["invalid_segments"].append(segment)
            continue
        match = _INPUT_SEGMENT_RE.match(segment)
        if not match:
            result["invalid_segments"].append(segment)
            continue
        name = match.group(1)
        try:
            value = float(match.group(2))
        except ValueError:
            result["invalid_segments"].append(segment)
            continue
        if not math.isfinite(value):
            result["invalid_segments"].append(segment)
            continue
        if name in variables:
            if _values_close(variables[name], value):
                result["warnings"].append(f"input 重复变量 {name}，值相同，已去重")
            else:
                result["duplicate_conflicts"].append(name)
            continue
        variables[name] = value

    result["variables"] = variables
    return result


def _validate_thousand_separator(num_str: str) -> bool:
    unsigned = num_str.lstrip("+-")
    if "," not in unsigned:
        return True
    if "." in unsigned:
        int_part, frac_part = unsigned.split(".", 1)
        if frac_part and not frac_part.replace(",", "").isdigit():
            return False
    else:
        int_part = unsigned
    groups = int_part.split(",")
    if len(groups) == 1:
        return True
    if not (1 <= len(groups[0]) <= 3 and groups[0].isdigit()):
        return False
    for group in groups[1:]:
        if len(group) != 3 or not group.isdigit():
            return False
    return True


def _parse_output_number(output_text: str) -> Tuple[Optional[float], Optional[str]]:
    """严格解析 output，必须完整匹配一个有限数值。"""
    if output_text is None:
        return None, "output 为空"
    raw = str(output_text).strip()
    if not raw:
        return None, "output 为空"

    lowered = raw.lower()
    if lowered in {"nan", "infinity", "-infinity", "+infinity", "inf", "-inf", "+inf"}:
        return None, "output 不是有限数值"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", raw):
        return None, "output 格式非法: 不得包含赋值表达式"
    if re.search(r"[\u4e00-\u9fff元]", raw):
        return None, "output 格式非法: 含非数值后缀"

    has_percent = raw.endswith("%")
    numeric_part = raw[:-1].strip() if has_percent else raw
    if not numeric_part or " " in numeric_part:
        return None, "output 不是有限数值"

    if "," in numeric_part:
        match = _OUTPUT_NUMBER_RE.match(numeric_part)
        if not match or not _validate_thousand_separator(match.group(1)):
            return None, "output 千分位格式非法"
    else:
        match = _OUTPUT_NUMBER_RE.match(numeric_part)
        if not match:
            return None, "output 不是有限数值"

    num_str = match.group(1)

    try:
        value = float(num_str.replace(",", ""))
    except ValueError:
        return None, "output 不是有限数值"
    if not math.isfinite(value):
        return None, "output 不是有限数值"
    return value, None


def _parse_strict_claim_ref(ref: str) -> Optional[str]:
    match = _STRICT_CLAIM_REF_RE.match((ref or "").strip())
    return match.group(1) if match else None


def _parse_strict_compare_rules_ref(ref: str) -> Optional[str]:
    text = (ref or "").strip()
    if _STRICT_COMPARE_RULES_RE.match(text):
        return text
    return None


def _validate_source_ref(source_ref: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """返回 (kind, payload, error)。kind 为 claim 或 compare_rules。"""
    ref = (source_ref or "").strip()
    if not ref:
        return None, None, "来源引用为空"

    claim_id = _parse_strict_claim_ref(ref)
    if claim_id:
        return "claim", claim_id, None

    compare_ref = _parse_strict_compare_rules_ref(ref)
    if compare_ref:
        return "compare_rules", compare_ref, None

    if ref.lower().startswith("claim"):
        return None, None, f"无法识别的 Claim 引用: {ref}"
    return None, None, f"无法识别的来源引用: {ref}"


def _parse_variable_source_mappings(input_source: str) -> Dict[str, Any]:
    """严格解析 input_source 字段。"""
    result: Dict[str, Any] = {
        "var_sources": {},
        "bare_claim_ids": [],
        "invalid_segments": [],
        "duplicate_conflicts": [],
        "warnings": [],
    }
    if not input_source:
        return result

    var_sources: Dict[str, str] = {}
    bare_claim_ids: List[str] = []

    for segment in _split_field_segments(input_source):
        var_match = _VAR_ASSIGN_RE.match(segment)
        if var_match:
            var_name = var_match.group(1)
            source_ref = var_match.group(2).strip()
            kind, payload, err = _validate_source_ref(source_ref)
            if kind is None:
                result["invalid_segments"].append(segment if err else source_ref)
                continue
            canonical_ref = f"claim_{payload}" if kind == "claim" else str(payload)
            if var_name in var_sources:
                if var_sources[var_name] == canonical_ref:
                    result["warnings"].append(
                        f"input_source 重复映射 {var_name}={canonical_ref}，已去重"
                    )
                else:
                    result["duplicate_conflicts"].append(var_name)
                continue
            var_sources[var_name] = canonical_ref if kind == "claim" else source_ref
            continue

        claim_id = _parse_strict_claim_ref(segment)
        if claim_id:
            if claim_id not in bare_claim_ids:
                bare_claim_ids.append(claim_id)
            continue

        result["invalid_segments"].append(segment)

    result["var_sources"] = var_sources
    result["bare_claim_ids"] = bare_claim_ids
    return result


def _extract_formula_expression(formula_text: str) -> str:
    text = (formula_text or "").strip()
    if not text:
        return ""
    if "=" in text:
        return text.split("=", 1)[1].strip()
    return text


def normalize_formula_power_syntax(formula_text: str) -> Tuple[str, bool, str]:
    """仅将 formula 表达式中的算术乘方 `^` 规范化为 `**`。"""
    original = formula_text or ""
    if not original or "^" not in original:
        return original, False, ""

    if "=" in original:
        eq_index = original.index("=")
        lhs = original[:eq_index]
        rhs = original[eq_index + 1 :]
        if "^" not in rhs:
            return original, False, ""
        normalized_rhs = re.sub(r"\^", "**", rhs)
        if normalized_rhs == rhs:
            return original, False, ""
        normalized = lhs + "=" + normalized_rhs
    else:
        normalized = re.sub(r"\^", "**", original)
        if normalized == original:
            return original, False, ""

    return normalized, True, original


def _extract_formula_variable_names(expression: str) -> Set[str]:
    expr = (expression or "").strip()
    if not expr:
        return set()
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
    return names


def _values_close(actual: float, expected: float) -> bool:
    if not math.isfinite(actual) or not math.isfinite(expected):
        return False
    if abs(expected) < _ABS_TOL:
        return abs(actual - expected) <= _ABS_TOL
    return abs(actual - expected) <= max(_ABS_TOL, abs(expected) * _REL_TOL)


class _SafeFormulaEvaluator(ast.NodeVisitor):
    """基于 AST 白名单的算术表达式求值器。"""

    def __init__(self, variables: Dict[str, float]):
        self.variables = variables

    def evaluate(self, expression: str) -> float:
        expr = (expression or "").strip()
        if not expr:
            raise ValueError("formula 为空")
        tree = ast.parse(expr, mode="eval")
        return float(self.visit(tree.body))

    def visit(self, node):  # type: ignore[override]
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")
            value = float(node.value)
            if not math.isfinite(value):
                raise ValueError("常量非有限数")
            return value
        if isinstance(node, ast.Name):
            if node.id not in self.variables:
                raise ValueError(f"未知变量: {node.id}")
            value = float(self.variables[node.id])
            if not math.isfinite(value):
                raise ValueError(f"变量 {node.id} 非有限数")
            return value
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ALLOWED_UNARYOPS):
                raise ValueError(f"不支持的一元运算: {type(node.op).__name__}")
            operand = self.visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +operand
            return -operand
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ALLOWED_BINOPS):
                raise ValueError(f"不支持的二元运算: {type(node.op).__name__}")
            left = self.visit(node.left)
            right = self.visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("除数为0")
                return left / right
            if isinstance(node.op, ast.Pow):
                result = left ** right
                if not math.isfinite(result):
                    raise ValueError("幂运算结果非有限数")
                return result
            if isinstance(node.op, ast.Mod):
                if right == 0:
                    raise ValueError("除数为0")
                return left % right
        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


def _evaluate_formula(formula_text: str, variables: Dict[str, float]) -> Tuple[Optional[float], Optional[str], Dict[str, Any]]:
    normalized_formula, formula_normalized, original_formula = normalize_formula_power_syntax(
        formula_text
    )
    meta: Dict[str, Any] = {}
    if formula_normalized:
        meta["formula_normalized"] = True
        meta["original_formula"] = original_formula
    expression = _extract_formula_expression(normalized_formula)
    if not expression:
        return None, "formula 为空", meta
    try:
        result = _SafeFormulaEvaluator(variables).evaluate(expression)
    except SyntaxError as exc:
        return None, f"formula 语法错误: {exc.msg}", meta
    except ValueError as exc:
        return None, str(exc), meta
    except Exception as exc:
        return None, f"formula 无法求值: {exc}", meta
    if not math.isfinite(result):
        return None, "计算结果非有限数", meta
    return result, None, meta


def _resolve_source_ref(source_ref: str) -> Tuple[Optional[str], Optional[str]]:
    kind, payload, err = _validate_source_ref(source_ref)
    if kind is None:
        return None, err or f"无法识别的来源引用: {source_ref}"
    return kind, payload


def _infer_legacy_variable_bindings(
    variables: Dict[str, float],
    formula_vars: Set[str],
    bare_claim_ids: List[str],
    pcn_claims: Dict[str, Claim],
) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    if not formula_vars:
        return {}, None

    if len(bare_claim_ids) != 1:
        return None, "旧格式存在多个 Claim 或无 Claim，无法唯一绑定变量"

    claim_id = bare_claim_ids[0]
    claim = pcn_claims.get(claim_id)
    if claim is None:
        return None, f"引用的 claim 不存在: {claim_id}"

    formula_input_vars = sorted(name for name in formula_vars if name in variables)
    if not formula_input_vars:
        return None, "formula 引用了 input 中未声明的变量"

    claim_value = float(claim.value)
    matching = [
        name
        for name in formula_input_vars
        if _values_close(variables[name], claim_value)
    ]
    if len(formula_input_vars) == 1 and len(matching) == 1:
        return {matching[0]: f"claim_{claim_id}"}, None

    return None, "旧格式无法唯一确定变量与 Claim 的绑定关系"


def _verify_variable_bindings(
    variables: Dict[str, float],
    formula_vars: Set[str],
    var_sources: Dict[str, str],
    pcn_claims: Dict[str, Claim],
) -> Tuple[bool, str, str]:
    if not formula_vars:
        return True, "ok", ""

    for var_name in sorted(formula_vars):
        if var_name not in variables:
            return False, "pending", f"formula 引用了 input 中未声明的变量: {var_name}"

        source_ref = var_sources.get(var_name)
        if not source_ref:
            return False, "pending", f"变量 {var_name} 缺少来源绑定"

        source_kind, payload = _resolve_source_ref(source_ref)
        if source_kind is None:
            return False, "pending", payload or f"变量 {var_name} 来源无法识别"

        if source_kind == "claim":
            claim = pcn_claims.get(str(payload))
            if claim is None:
                return False, "pending", f"变量 {var_name} 引用的 claim 不存在: {payload}"
            if not _values_close(variables[var_name], float(claim.value)):
                return (
                    False,
                    "invalid",
                    f"变量 {var_name} 的值与 claim_{payload} 不一致",
                )
            continue

        expected, err = resolve_compare_rules_value(str(payload))
        if expected is None:
            return False, "pending", err or f"compare_rules 路径不存在: {payload}"
        if not _values_close(variables[var_name], expected):
            return (
                False,
                "invalid",
                f"变量 {var_name} 的值与 compare_rules 来源不一致",
            )

    return True, "ok", ""


def _format_parse_errors(field: str, invalid_segments: List[str], duplicate_conflicts: List[str]) -> str:
    parts: List[str] = []
    if invalid_segments:
        parts.append(f"{field} 含非法片段: {', '.join(invalid_segments[:3])}")
    if duplicate_conflicts:
        parts.append(f"{field} 重复冲突: {', '.join(duplicate_conflicts[:3])}")
    return "; ".join(parts)


def verify_single_calculate(
    fields: Dict[str, str],
    pcn_claims: Dict[str, Claim],
) -> Tuple[str, str, Dict[str, Any]]:
    """验证单个 calculate 字段集，返回 (status, reason, meta)。"""
    meta: Dict[str, Any] = {}
    input_text = fields.get("input", "")
    formula_text = fields.get("formula", "")
    output_text = fields.get("output", "")
    input_source = fields.get("input_source", "")

    if not formula_text or output_text is None or str(output_text).strip() == "":
        return "invalid", "缺少 formula/output 字段", meta

    output_value, output_err = _parse_output_number(output_text)
    if output_value is None:
        return "invalid", output_err or "output 不是有限数值", meta

    input_result = _parse_input_variables(input_text)
    variables: Dict[str, float] = input_result["variables"]
    if input_result["invalid_segments"] or input_result["duplicate_conflicts"]:
        reason = _format_parse_errors(
            "input",
            input_result["invalid_segments"],
            input_result["duplicate_conflicts"],
        )
        return "invalid", reason, meta
    if input_result["warnings"]:
        meta["input_warnings"] = input_result["warnings"]

    normalized_formula, formula_normalized, original_formula = normalize_formula_power_syntax(
        formula_text
    )
    if formula_normalized:
        meta["formula_normalized"] = True
        meta["original_formula"] = original_formula

    formula_vars = _extract_formula_variable_names(_extract_formula_expression(normalized_formula))

    if formula_vars and not input_text.strip():
        return "invalid", "formula 含变量但缺少 input 字段", meta
    if formula_vars and not variables:
        return "invalid", "input 未解析到有效变量", meta

    source_result = _parse_variable_source_mappings(input_source)
    if source_result["invalid_segments"] or source_result["duplicate_conflicts"]:
        reason = _format_parse_errors(
            "input_source",
            source_result["invalid_segments"],
            source_result["duplicate_conflicts"],
        )
        return "invalid", reason, meta
    if source_result["warnings"]:
        meta["input_source_warnings"] = source_result["warnings"]

    var_sources: Dict[str, str] = source_result["var_sources"]
    bare_claim_ids: List[str] = source_result["bare_claim_ids"]

    if formula_vars and not var_sources:
        if not input_source.strip():
            return "pending", "formula 含变量但 input_source 为空", meta
        inferred, infer_reason = _infer_legacy_variable_bindings(
            variables, formula_vars, bare_claim_ids, pcn_claims
        )
        if inferred is None:
            return "pending", infer_reason or "无法推断变量来源", meta
        var_sources = inferred

    binding_ok, binding_status, binding_reason = _verify_variable_bindings(
        variables, formula_vars, var_sources, pcn_claims
    )
    if not binding_ok:
        return binding_status, binding_reason, meta

    computed, eval_reason, eval_meta = _evaluate_formula(normalized_formula, variables)
    if eval_meta.get("formula_normalized") and not meta.get("formula_normalized"):
        meta["formula_normalized"] = True
        meta["original_formula"] = eval_meta.get("original_formula") or original_formula
    if computed is None:
        if eval_reason and any(
            token in eval_reason
            for token in ("不支持", "未知变量", "语法错误", "无法求值")
        ):
            return "pending", eval_reason, meta
        return "invalid", eval_reason or "formula 无法求值", meta

    if _values_close(computed, output_value):
        return "verified", "", meta

    return (
        "mismatched",
        f"计算结果 {computed} 与 output {output_value} 不一致",
        meta,
    )


def _escape_html_attr(text: str) -> str:
    return html.escape(text or "", quote=True)


def verify_calculate_tags_in_report(
    report_content: str,
    pcn_claims: Dict[str, Claim],
) -> Tuple[str, Dict[str, Any]]:
    """验证报告中的 calculate 标签，返回 (report_with_marks, stats)。"""
    stats: Dict[str, Any] = {
        "total_calculates": 0,
        "verified_calculates": 0,
        "mismatched_calculates": 0,
        "pending_calculates": 0,
        "invalid_calculates": 0,
        "calculate_details": [],
    }

    if not report_content:
        return report_content or "", stats

    def replace(match: re.Match) -> str:
        stats["total_calculates"] += 1
        inner = match.group(1)
        fields = _parse_calculate_fields(inner)
        status, reason, detail_meta = verify_single_calculate(fields, pcn_claims or {})

        detail = {"status": status, "reason": reason, "fields": fields, **detail_meta}
        stats["calculate_details"].append(detail)

        if status == "verified":
            stats["verified_calculates"] += 1
            mark = "✓"
            title = "Calculate verified"
        elif status == "mismatched":
            stats["mismatched_calculates"] += 1
            mark = "✗"
            title = reason or "Calculate mismatched"
            logger.warning(f"Calculate 验证失败: {reason}")
        elif status == "pending":
            stats["pending_calculates"] += 1
            mark = "?"
            title = reason or "Calculate pending"
            logger.warning(f"Calculate 待验证: {reason}")
        else:
            stats["invalid_calculates"] += 1
            mark = "!"
            title = reason or "Calculate invalid"
            logger.warning(f"Calculate 无效: {reason}")

        cleaned = re.sub(r'<sup\b[^>]*>.*?</sup>', "", inner, flags=re.DOTALL | re.IGNORECASE)
        safe_title = _escape_html_attr(title)
        return f"<calculate>{cleaned}<sup title=\"{safe_title}\">{mark}</sup></calculate>"

    verified_report = _CALCULATE_TAG_RE.sub(replace, report_content)
    return verified_report, stats
