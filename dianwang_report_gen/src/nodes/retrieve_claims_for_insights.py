from typing import List, Dict, Any, Optional, Tuple
import os
import re
from loguru import logger
import json
import jieba
import jieba.analyse

from src.graph_state import State
from src.pcn_database import PCNDatabase

# 派生指标 metadata 中必须保留的键
_DERIVED_METADATA_KEYS = frozenset(
    {
        "formula",
        "inputs",
        "calculation_status",
        "calculation_mode",
        "provenance",
        "input_source",
        "source_field",
        "scheme_index",
        "scheme_name",
        "metric_key",
    }
)

_MAX_CONTEXT_CHARS = 500
_MAX_SINGLE_CLAIM_CHARS = 8000


def _parse_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(f"环境变量 {name}={raw!r} 非法，回退默认值 {default}")
        return default
    if value < 1:
        logger.warning(f"环境变量 {name}={value} 小于 1，回退默认值 {default}")
        return default
    return value


def get_claims_per_insight() -> int:
    return _parse_positive_int_env("REPORT_CLAIMS_PER_INSIGHT", 3)


def get_core_claims_per_indicator() -> int:
    return _parse_positive_int_env("REPORT_CORE_CLAIMS_PER_INDICATOR", 3)


def get_max_claims_chars() -> int:
    return _parse_positive_int_env("REPORT_MAX_CLAIMS_CHARS", 60000)


def compact_claim_for_prompt(claim: Dict[str, Any]) -> Dict[str, Any]:
    """压缩单条 claim 供报告 Prompt 使用，不修改数据库原始记录。"""
    if not isinstance(claim, dict):
        return {}

    metadata = claim.get("metadata") if isinstance(claim.get("metadata"), dict) else {}
    compact_meta: Dict[str, Any] = {}
    for key, value in metadata.items():
        if value in (None, "", [], {}):
            continue
        if key in _DERIVED_METADATA_KEYS or key.startswith("derived_"):
            compact_meta[key] = value

    top_level_meta_keys = (
        "source_path",
        "path_to_value",
        "original_type",
    )
    for key in top_level_meta_keys:
        if key in claim and claim.get(key) not in (None, ""):
            if key not in compact_meta:
                compact_meta[key] = claim[key]

    context = claim.get("context") or metadata.get("context")
    if isinstance(context, str) and context:
        if len(context) > _MAX_CONTEXT_CHARS:
            context = context[:_MAX_CONTEXT_CHARS] + "…"

    compact: Dict[str, Any] = {}
    for key in (
        "claim_id",
        "indicator",
        "value",
        "unit",
        "entity",
        "time",
        "policy",
    ):
        if key in claim and claim[key] not in (None, ""):
            compact[key] = claim[key]

    for key in ("source_path", "path_to_value", "original_type"):
        if key in claim and claim.get(key) not in (None, ""):
            compact[key] = claim[key]
        elif key in metadata and metadata.get(key) not in (None, ""):
            compact[key] = metadata[key]

    if isinstance(context, str) and context:
        compact["context"] = context

    if compact_meta:
        compact["metadata"] = compact_meta

    return compact


def claim_dedup_key(claim: Dict[str, Any]) -> Tuple[Any, ...]:
    claim_id = claim.get("claim_id")
    if claim_id not in (None, ""):
        return ("id", str(claim_id))

    metadata = claim.get("metadata") if isinstance(claim.get("metadata"), dict) else {}
    return (
        "composite",
        str(claim.get("indicator", "")),
        str(claim.get("value", "")),
        str(claim.get("unit", "")),
        str(claim.get("entity", "")),
        str(claim.get("source_path") or metadata.get("source_path", "")),
        str(claim.get("path_to_value") or metadata.get("path_to_value", "")),
    )


def _claim_json_size(claim: Dict[str, Any]) -> int:
    return len(json.dumps(claim, ensure_ascii=False))


def _payload_json_size(payload: Dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False))


def deduplicate_claim_buckets(
    buckets: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], int, int]:
    """全局去重；core_metrics 优先保留，洞察重复项不再占用名额。"""
    seen: set = set()
    total_before = 0
    deduped: Dict[str, Dict[str, Any]] = {}

    ordered_keys = []
    if "core_metrics" in buckets:
        ordered_keys.append("core_metrics")
    ordered_keys.extend(sorted(k for k in buckets if k.startswith("insight_")))

    for key in ordered_keys:
        bucket = buckets[key]
        insight_text = bucket.get("insight", "")
        claims = bucket.get("claims") if isinstance(bucket.get("claims"), list) else []
        total_before += len(claims)
        kept: List[Dict[str, Any]] = []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            key_tuple = claim_dedup_key(claim)
            if key_tuple in seen:
                continue
            seen.add(key_tuple)
            kept.append(claim)
        deduped[key] = {"insight": insight_text, "claims": kept}

    total_after = sum(len(b["claims"]) for b in deduped.values())
    return deduped, total_before, total_after


def _ordered_claim_slots(
    buckets: Dict[str, Dict[str, Any]],
) -> List[Tuple[str, int, Dict[str, Any]]]:
    """按优先级返回 (bucket_key, claim_index, compact_claim) 列表。"""
    slots: List[Tuple[str, int, Dict[str, Any]]] = []

    core = buckets.get("core_metrics", {}).get("claims", [])
    for idx, claim in enumerate(core):
        compact = compact_claim_for_prompt(claim)
        if compact:
            slots.append(("core_metrics", idx, compact))

    insight_keys = sorted(k for k in buckets if k.startswith("insight_"))
    # 第一轮：每个洞察至少保留 1 条
    for key in insight_keys:
        claims = buckets[key].get("claims", [])
        if not claims:
            continue
        compact = compact_claim_for_prompt(claims[0])
        if compact:
            slots.append((key, 0, compact))

    # 第二轮：core 剩余 + 各洞察剩余高排名 claim
    for idx in range(1, max((len(buckets.get("core_metrics", {}).get("claims", []))), 0)):
        claim = buckets["core_metrics"]["claims"][idx]
        compact = compact_claim_for_prompt(claim)
        if compact:
            slots.append(("core_metrics", idx, compact))

    for key in insight_keys:
        claims = buckets[key].get("claims", [])
        for idx in range(1, len(claims)):
            compact = compact_claim_for_prompt(claims[idx])
            if compact:
                slots.append((key, idx, compact))

    return slots


def build_retrieved_claims_payload(
    buckets: Dict[str, Dict[str, Any]],
    max_chars: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """构建带长度控制的 retrieved_claims JSON 对象。"""
    max_chars = max_chars if max_chars is not None else get_max_claims_chars()
    deduped, total_before, total_after = deduplicate_claim_buckets(buckets)

    output_buckets: Dict[str, Dict[str, Any]] = {}
    for key, bucket in deduped.items():
        output_buckets[key] = {"insight": bucket.get("insight", ""), "claims": []}

    included = 0
    dropped = 0
    truncated = False
    seen_slot: set = set()

    for bucket_key, claim_idx, compact in _ordered_claim_slots(deduped):
        slot_id = (bucket_key, claim_idx)
        if slot_id in seen_slot:
            continue

        claim_size = _claim_json_size(compact)
        if claim_size > _MAX_SINGLE_CLAIM_CHARS:
            logger.warning(
                f"单条 claim 压缩后仍过大({claim_size} 字符)，已跳过: "
                f"{compact.get('claim_id', '?')} {compact.get('indicator', '')}"
            )
            dropped += 1
            continue

        tentative = dict(output_buckets)
        tentative[bucket_key] = {
            "insight": output_buckets[bucket_key]["insight"],
            "claims": output_buckets[bucket_key]["claims"] + [compact],
        }
        summary = {
            "_retrieval_summary": {
                "total_before_dedup": total_before,
                "total_after_dedup": total_after,
                "total_included": included + 1,
                "total_dropped": dropped,
                "max_chars": max_chars,
                "truncated": truncated,
            }
        }
        tentative_payload = {**tentative, **summary}

        if _payload_json_size(tentative_payload) > max_chars:
            dropped += 1
            truncated = True
            continue

        output_buckets[bucket_key]["claims"].append(compact)
        seen_slot.add(slot_id)
        included += 1

    summary = {
        "total_before_dedup": total_before,
        "total_after_dedup": total_after,
        "total_included": included,
        "total_dropped": max(0, total_after - included),
        "max_chars": max_chars,
        "truncated": truncated or (included < total_after),
    }

    payload = {**output_buckets, "_retrieval_summary": summary}
    logger.info(
        "Claims 检索汇总: "
        f"去重前={total_before}, 去重后={total_after}, "
        f"纳入={included}, 丢弃={summary['total_dropped']}, "
        f"JSON长度={_payload_json_size(payload)}, 上限={max_chars}, "
        f"truncated={summary['truncated']}"
    )
    return payload, summary


def format_retrieved_claims(retrieved_claims_dict: dict) -> str:
    """将检索到的 claims 转换为 JSON 字符串。"""
    return json.dumps(retrieved_claims_dict, ensure_ascii=False)


def build_formatted_retrieved_claims(
    buckets: Dict[str, Dict[str, Any]],
    max_chars: Optional[int] = None,
) -> str:
    payload, _ = build_retrieved_claims_payload(buckets, max_chars=max_chars)
    return format_retrieved_claims(payload)


def ensure_retrieved_claims_within_limit(
    retrieved_claims: str,
    max_chars: Optional[int] = None,
) -> str:
    """对已格式化的 retrieved_claims 做合法 JSON 长度保护。"""
    if not retrieved_claims or not str(retrieved_claims).strip():
        empty_payload = {
            "_retrieval_summary": {
                "total_before_dedup": 0,
                "total_after_dedup": 0,
                "total_included": 0,
                "total_dropped": 0,
                "max_chars": max_chars or get_max_claims_chars(),
                "truncated": False,
            }
        }
        return format_retrieved_claims(empty_payload)

    max_chars = max_chars if max_chars is not None else get_max_claims_chars()
    if len(retrieved_claims) <= max_chars:
        return retrieved_claims

    try:
        data = json.loads(retrieved_claims)
    except json.JSONDecodeError:
        logger.warning("retrieved_claims 不是合法 JSON，将重建为空结果")
        return format_retrieved_claims(
            {
                "_retrieval_summary": {
                    "total_before_dedup": 0,
                    "total_after_dedup": 0,
                    "total_included": 0,
                    "total_dropped": 0,
                    "max_chars": max_chars,
                    "truncated": True,
                }
            }
        )

    summary = data.pop("_retrieval_summary", {})
    buckets = {
        k: v for k, v in data.items() if isinstance(v, dict) and "claims" in v
    }
    reformatted = build_formatted_retrieved_claims(buckets, max_chars=max_chars)
    logger.warning(
        f"retrieved_claims 超限({len(retrieved_claims)} > {max_chars})，"
        f"已重新压缩至 {len(reformatted)} 字符；原 summary={summary}"
    )
    return reformatted


def extract_numeric_values(text: str) -> List[float]:
    """从洞察文本中提取可直接反查 claims.value 的数字。"""
    values: List[float] = []
    seen = set()
    pattern = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
    for match in pattern.finditer(text or ""):
        raw = match.group(0)
        prefix = (text or "")[max(0, match.start() - 2) : match.start()]
        suffix = (text or "")[match.end() : match.end() + 1]
        next_chars = (text or "")[match.end() : match.end() + 4]
        if prefix.endswith("N-") or prefix.endswith("方案") or suffix == "至":
            continue
        if re.match(r"\.\s*\*?", next_chars):
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def retrieve_claims_by_numbers(
    insight: str, db: PCNDatabase, k: int = 3
) -> List[Dict[str, Any]]:
    """FTS 无结果时，按洞察中的数字反查真实 claim_id。"""
    results: List[Dict[str, Any]] = []
    seen_claim_ids = set()

    for value in extract_numeric_values(insight):
        remaining = k - len(results)
        if remaining <= 0:
            break
        for claim in db.search_claims_by_value(value, k=remaining):
            claim_id = claim.get("claim_id")
            if claim_id in seen_claim_ids:
                continue
            seen_claim_ids.add(claim_id)
            results.append(claim)
            if len(results) >= k:
                break

    logger.debug(f"数字兜底检索返回 {len(results)} 条 claims")
    return results


def parse_insights_by_bullet(insights: str) -> List[str]:
    """按列表符号解析洞察文本"""
    lines = insights.split("\n")
    insight_points = []
    current_insight = []

    for line in lines:
        line = line.strip()
        if line.startswith("•") or line.startswith("-") or line.startswith("*"):
            if current_insight:
                insight_points.append(" ".join(current_insight))
            current_insight = [line[1:].strip()]
        elif current_insight:
            current_insight.append(line)

    if current_insight:
        insight_points.append(" ".join(current_insight))

    return insight_points


def build_fts_query_from_insight(insight: str) -> str:
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s]", "", insight)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        return "*"

    has_chinese = bool(re.search(r"[\u4e00-\u9fa5]", cleaned))

    if has_chinese:
        keywords_with_weights = jieba.analyse.extract_tags(
            cleaned,
            topK=15,
            withWeight=True,
            allowPOS=(
                "n",
                "nr",
                "ns",
                "nt",
                "nz",
                "v",
                "vd",
                "vn",
                "a",
                "ad",
                "an",
            ),
        )

        if not keywords_with_weights:
            keywords_with_weights = jieba.analyse.textrank(
                cleaned,
                topK=15,
                withWeight=True,
                allowPOS=(
                    "n",
                    "nr",
                    "ns",
                    "nt",
                    "nz",
                    "v",
                    "vd",
                    "vn",
                    "a",
                    "ad",
                    "an",
                ),
            )

        if keywords_with_weights:
            query_keywords = [f'"{keyword}*"' for keyword, _ in keywords_with_weights]
            query = " OR ".join(query_keywords)
            logger.debug(f"FTS5 查询构建 (jieba): '{insight[:50]}...' -> '{query}'")
            return query

    query = cleaned
    logger.debug(f"FTS5 查询构建 (简单模式): '{insight[:50]}...' -> '{query}'")
    return query


def retrieve_claims_for_insight(
    insight: str, db: PCNDatabase, k: Optional[int] = None
) -> List[Dict[str, Any]]:
    if k is None:
        k = get_claims_per_insight()

    query = build_fts_query_from_insight(insight)
    results = db.search_claims_by_text(query, k=k, use_rank=True)

    if not results:
        results = retrieve_claims_by_numbers(insight, db, k=k)

    logger.debug(f"为洞察检索到 {len(results)} 条 claims")
    return results


CORE_CLAIM_INDICATORS = (
    "construction_cost",
    "operation_cost",
    "lifecycle_cost",
    "annual_cost",
    "annual_energy_loss",
    "annual_network_loss_cost",
    "pf_convergence",
    "n1_pass_rate",
    "weighted_n1_pass_rate",
    "short_circuit_over_limit_count",
    "short_circuit_over_limit_ratio",
    "min_breaker_interrupt_margin_rate",
    "voltage_qualification_rate",
    "voltage_over_limit_severity",
    "node_period_voltage_over_limit_rate",
    "max_line_loading_rate",
    "max_transformer_loading_rate",
    "active_power_loss_rate",
    "critical_section_margin_rate",
    "post_contingency_max_equipment_loading_rate",
    "post_contingency_voltage_over_limit_rate",
    "transient_stability_pass_rate",
    "max_generator_relative_angle_difference",
    "new_line_length",
    "retrofit_line_length",
    "total_contingencies_run",
    "remaining_issues",
    "short_circuit_current",
    "breaker_current",
    "电流比例",
    "实际功率",
)


def retrieve_core_claims(
    db: PCNDatabase, per_indicator: Optional[int] = None
) -> List[Dict[str, Any]]:
    if per_indicator is None:
        per_indicator = get_core_claims_per_indicator()

    results: List[Dict[str, Any]] = []
    seen_claim_ids = set()
    for indicator in CORE_CLAIM_INDICATORS:
        for claim in db.search_claims_by_indicator(indicator, k=per_indicator):
            claim_id = claim.get("claim_id")
            if claim_id in seen_claim_ids:
                continue
            seen_claim_ids.add(claim_id)
            results.append(claim)
    logger.debug(f"固定核心 claims 返回 {len(results)} 条")
    return results


async def retrieve_claims_for_insights(state: State) -> dict:
    """PCN claims 检索节点：为每条洞察检索相关 claims（使用 SQLite FTS5）"""
    logger.info("=== 开始 PCN claims 检索节点 ===")
    insights = state.insights
    pcn_db_path = state.pcn_db_path

    logger.info(f"PCN 数据库路径: {pcn_db_path}")
    logger.info(
        f"检索配置: per_insight={get_claims_per_insight()}, "
        f"per_core_indicator={get_core_claims_per_indicator()}, "
        f"max_chars={get_max_claims_chars()}"
    )

    if not pcn_db_path:
        raise ValueError("PCN 数据库路径未配置")

    if not insights:
        raise ValueError("未找到洞察文本，无法检索 claims")

    if not pcn_db_path.exists():
        raise FileNotFoundError(f"PCN 数据库文件不存在: {pcn_db_path}")

    logger.info("解析洞察文本...")
    insight_points = parse_insights_by_bullet(insights)
    logger.info(f"解析出 {len(insight_points)} 个洞察点")

    if not insight_points:
        insight_points = [insights]

    retrieved_claims_dict: Dict[str, Dict[str, Any]] = {}

    logger.info(f"打开 PCN 数据库: {pcn_db_path}")
    with PCNDatabase(str(pcn_db_path)) as db:
        logger.info(f"开始为 {len(insight_points)} 个洞察检索 claims...")
        per_insight = get_claims_per_insight()
        for i, insight in enumerate(insight_points):
            logger.debug(f"为洞察 {i+1} 检索相关 claims: {insight[:120]}")
            claims = retrieve_claims_for_insight(insight, db, k=per_insight)
            retrieved_claims_dict[f"insight_{i}"] = {
                "insight": insight,
                "claims": claims,
            }
            logger.debug(f"检索到 {len(claims)} 条相关 claims")

        core_claims = retrieve_core_claims(db)
        if core_claims:
            retrieved_claims_dict["core_metrics"] = {
                "insight": (
                    "固定提供给报告生成的核心指标 claims，"
                    "优先用于经济、N-1、短路、潮流等核心数值溯源。"
                ),
                "claims": core_claims,
            }

    formatted_claims = build_formatted_retrieved_claims(retrieved_claims_dict)
    logger.info(f"格式化 retrieved_claims 长度: {len(formatted_claims)} 字符")
    logger.info("=== PCN claims 检索节点完成 ===")
    return {"retrieved_claims": formatted_claims}
