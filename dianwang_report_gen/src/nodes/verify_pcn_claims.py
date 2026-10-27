import re
from typing import Dict, Any, Tuple
from loguru import logger

from src.graph_state import State
from src.pcn import Claim, VerificationPolicy, VerificationResult, verify_claim
from src.nodes.normalize_claim_tags import normalize_claim_tags_in_report
from src.nodes.verify_calculate_tags import verify_calculate_tags_in_report


def compute_pcn_verification_passed(stats: Dict[str, Any]) -> bool:
    """判断 PCN 验证是否全部通过（含 Claim、Calculate 与 stripped 条件）。"""
    if not stats:
        return False

    claims_ok = (
        int(stats.get("total_claims") or 0) > 0
        and int(stats.get("verified_claims") or 0) == int(stats.get("total_claims") or 0)
        and int(stats.get("mismatched_claims") or 0) == 0
        and int(stats.get("not_found_claims") or 0) == 0
        and int(stats.get("pending_claims") or 0) == 0
        and int(stats.get("stripped_claims") or 0) == 0
    )

    total_calculates = int(stats.get("total_calculates") or 0)
    if total_calculates == 0:
        calculates_ok = True
    else:
        calculates_ok = (
            int(stats.get("verified_calculates") or 0) == total_calculates
            and int(stats.get("mismatched_calculates") or 0) == 0
            and int(stats.get("pending_calculates") or 0) == 0
            and int(stats.get("invalid_calculates") or 0) == 0
        )

    return claims_ok and calculates_ok


def format_pcn_review_message(verify_stats: Dict[str, Any]) -> str:
    """生成人工复核状态消息（Claim + Calculate 统计各出现一次）。"""
    total_claims = int(verify_stats.get("total_claims") or 0)
    verified = int(verify_stats.get("verified_claims") or 0)
    mismatched = int(verify_stats.get("mismatched_claims") or 0)
    not_found = int(verify_stats.get("not_found_claims") or 0)
    stripped = int(verify_stats.get("stripped_claims") or 0)

    total_calculates = int(verify_stats.get("total_calculates") or 0)
    verified_cal = int(verify_stats.get("verified_calculates") or 0)
    mismatched_cal = int(verify_stats.get("mismatched_calculates") or 0)
    pending_cal = int(verify_stats.get("pending_calculates") or 0)
    invalid_cal = int(verify_stats.get("invalid_calculates") or 0)

    return (
        "报告已生成，但数值溯源校验未通过，需要人工复核"
        f"（Claim总数{total_claims}，通过{verified}，不匹配{mismatched}，"
        f"未找到{not_found}，移除标签{stripped}；"
        f"Calculate总数{total_calculates}，通过{verified_cal}，"
        f"不匹配{mismatched_cal}，待验证{pending_cal}，格式错误{invalid_cal}）。"
        "草稿可打开，但不属于可直接交付版本。"
    )


def format_pcn_pass_message(verify_stats: Dict[str, Any]) -> str:
    verified = int(verify_stats.get("verified_claims") or 0)
    total_claims = int(verify_stats.get("total_claims") or 0)
    return (
        f"比选报告初稿已生成，PCN 核验通过（通过 {verified}/{total_claims}），"
        "可在编辑器中修改并导出。"
    )


def _empty_pcn_stats() -> Dict[str, Any]:
    return {
        "total_claims": 0,
        "verified_claims": 0,
        "mismatched_claims": 0,
        "not_found_claims": 0,
        "pending_claims": 0,
        "stripped_claims": 0,
        "rewritten_claims": 0,
        "converted_to_calculate": 0,
        "total_calculates": 0,
        "verified_calculates": 0,
        "mismatched_calculates": 0,
        "pending_calculates": 0,
        "invalid_calculates": 0,
    }


async def verify_pcn_claims(state: State) -> dict:
    """
    PCN claims 验证节点：验证报告中的 claim 标签数值是否与数据库中的值匹配

    支持多种验证策略：
    - exact: 精确匹配
    - round{d}: 四舍五入到d位小数
    - alias: 别名等价（单位换算）
    - tolerance(δ,ρ): 容差匹配
    - 组合策略: round1|alias|tolerance(0.1,0.05)

    输入状态：
        - raw_report: 原始报告内容（包含 <claim> 标签）
        - pcn_claims: PCN claims 字典 {claim_id: Claim}

    输出状态：
        - md_report: Markdown 格式的验证报告（使用 HTML 样式上标）
        - pdf_report_content: PDF 格式的验证报告内容（使用 LaTeX 彩色符号）
        - docx_report_content: DOCX 格式的验证报告内容（使用 HTML 样式）
        - pcn_verification_result: 验证统计信息
        - pcn_verification_passed: 是否全部验证通过
    """
    logger.info("=== 开始 PCN claims 验证节点 ===")

    raw_report = state.raw_report
    pcn_claims = state.pcn_claims

    if not raw_report:
        raise ValueError("未找到原始报告内容")

    if not pcn_claims:
        logger.warning("未找到 PCN claims 数据，跳过验证")
        return {
            "raw_report": raw_report,
            "md_report": raw_report,
            "pdf_report_content": raw_report,
            "docx_report_content": raw_report,
            "pcn_verification_result": _empty_pcn_stats(),
            "pcn_verification_passed": False,
        }

    logger.info(f"报告内容长度: {len(raw_report)} 字符")
    logger.info(f"可用 claims 数量: {len(pcn_claims)}")

    normalized_report, normalize_stats = normalize_claim_tags_in_report(
        raw_report, pcn_claims
    )
    if normalize_stats.get("rewritten") or normalize_stats.get("converted_to_calculate") or normalize_stats.get("stripped"):
        logger.info(f"claim 规范化统计: {normalize_stats}")

    md_report, pdf_report, docx_report, stats = verify_pcn_claims_in_report(
        normalized_report, pcn_claims
    )

    md_report, calc_stats = verify_calculate_tags_in_report(md_report, pcn_claims)
    pdf_report, _ = verify_calculate_tags_in_report(pdf_report, pcn_claims)
    docx_report, _ = verify_calculate_tags_in_report(docx_report, pcn_claims)
    stats.update(calc_stats)

    stats["stripped_claims"] = int(normalize_stats.get("stripped") or 0)
    stats["rewritten_claims"] = int(normalize_stats.get("rewritten") or 0)
    stats["converted_to_calculate"] = int(normalize_stats.get("converted_to_calculate") or 0)
    stats["claim_normalize"] = normalize_stats

    logger.info("验证完成:")
    logger.info(f"  总 claims 数: {stats['total_claims']}")
    logger.info(f"  验证通过: {stats['verified_claims']}")
    logger.info(f"  策略匹配: {stats.get('strategy_matches', {})}")
    logger.info(f"  待验证 claims: {stats['pending_claims']}")
    logger.info(f"  未找到: {stats['not_found_claims']}")
    logger.info(f"  数值不匹配: {stats['mismatched_claims']}")
    logger.info(f"  移除标签: {stats['stripped_claims']}")
    logger.info(f"  总 calculates 数: {stats.get('total_calculates', 0)}")
    logger.info(f"  calculate 通过: {stats.get('verified_calculates', 0)}")
    logger.info(f"  calculate 不匹配: {stats.get('mismatched_calculates', 0)}")
    logger.info(f"  calculate 待验证: {stats.get('pending_calculates', 0)}")
    logger.info(f"  calculate 无效: {stats.get('invalid_calculates', 0)}")

    all_verified = compute_pcn_verification_passed(stats)

    if all_verified:
        logger.info("✓ 所有 claims 与 calculates 验证通过")
    else:
        logger.warning("✗ 部分或全部 claims/calculates 验证失败")

    logger.info("=== PCN claims 验证节点完成 ===")

    return {
        "raw_report": normalized_report,
        "md_report": md_report,
        "pdf_report_content": pdf_report,
        "docx_report_content": docx_report,
        "pcn_verification_result": stats,
        "pcn_verification_passed": all_verified,
    }


def extract_policy_from_tag(tag_attrs: str) -> VerificationPolicy:
    """
    从 claim 标签属性中提取验证策略

    Args:
        tag_attrs: 标签属性字符串，如 'id="001" policy="round1"'

    Returns:
        VerificationPolicy 实例
    """
    policy_match = re.search(r'policy="([^"]*)"', tag_attrs)
    if policy_match:
        policy_str = policy_match.group(1)
        return VerificationPolicy.from_string(policy_str)

    return VerificationPolicy.from_string("exact")


def verify_pcn_claims_in_report(
    report_content: str, pcn_claims: Dict[str, Claim]
) -> Tuple[str, str, str, Dict[str, Any]]:
    """
    验证报告中的 PCN claims，添加验证标记

    支持多种验证策略，策略从 claim 标签的 policy 属性读取。

    生成三种格式的报告：
    1. Markdown/HTML 格式：使用 HTML 样式上标 <sup style="color: ...">
    2. PDF 格式：使用 LaTeX 彩色符号 $\textcolor{...}{...}$
    3. DOCX 格式：使用 HTML 样式（与 Markdown 相同）

    Args:
        report_content: 报告内容
        pcn_claims: PCN claims 字典 {claim_id: Claim}

    Returns:
        (md_report, pdf_report, docx_report, verification_stats)
    """
    verification_stats = {
        "total_claims": 0,
        "verified_claims": 0,
        "pending_claims": 0,
        "not_found_claims": 0,
        "mismatched_claims": 0,
        "stripped_claims": 0,
        "rewritten_claims": 0,
        "converted_to_calculate": 0,
        "total_calculates": 0,
        "verified_calculates": 0,
        "mismatched_calculates": 0,
        "pending_calculates": 0,
        "invalid_calculates": 0,
        "strategy_matches": {},
    }

    md_report_lines = []
    pdf_report_lines = []
    docx_report_lines = []

    parts = re.split(
        r'(<claim\s+[^>]*>.*?</claim>)', report_content, flags=re.DOTALL
    )

    for part in parts:
        claim_match = re.match(r'<claim\s+([^>]*)>(.*?)</claim>', part, re.DOTALL)

        if not claim_match:
            md_report_lines.append(part)
            pdf_report_lines.append(part)
            docx_report_lines.append(part)
            continue

        tag_attrs = claim_match.group(1)
        inner_text = claim_match.group(2).strip()

        claim_id_match = re.search(r'id="([^"]+)"', tag_attrs)
        if not claim_id_match:
            md_report_lines.append(part)
            pdf_report_lines.append(part)
            docx_report_lines.append(part)
            continue

        claim_id = claim_id_match.group(1)
        verification_stats["total_claims"] += 1

        clean_inner = re.sub(
            r'<span class="verified-mark".*?>.*?</span>', "", inner_text
        )
        clean_inner = re.sub(
            r'<span class="verify-pending".*?>.*?</span>', "", clean_inner
        )
        clean_inner = re.sub(
            r'<span class="verify-not-found".*?>.*?</span>', "", clean_inner
        )
        clean_inner = clean_inner.strip()

        claim = pcn_claims.get(claim_id)
        if not claim:
            logger.warning(f"未找到 claim_id: {claim_id}")
            verification_stats["not_found_claims"] += 1

            md_suffix = '<sup style="color: #ffaa00;" title="Claim not found in database">?</sup>'
            md_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}{md_suffix}</claim>'
            )

            pdf_suffix = r"$\textcolor{orange}{\textbf{?}}$"
            pdf_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}<sup title="Claim not found in database">{pdf_suffix}</sup></claim>'
            )

            docx_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}{md_suffix}</claim>'
            )
            continue

        if claim.policy is not None:
            policy = claim.policy
        else:
            policy = extract_policy_from_tag(tag_attrs)

        result, detail = verify_claim(
            text_value=clean_inner,
            reference_value=claim.value,
            policy=policy,
            surrounding_text=clean_inner,
        )

        policy_str = policy.to_string()
        if result == VerificationResult.VERIFIED:
            verification_stats["strategy_matches"][policy_str] = \
                verification_stats["strategy_matches"].get(policy_str, 0) + 1

        if result == VerificationResult.VERIFIED:
            verification_stats["verified_claims"] += 1
            logger.debug(f"✓ Claim {claim_id} 验证通过: {clean_inner} ~ {claim.value} ({detail})")

            title_info = f"Verified: {claim.value}"
            if policy_str != "exact":
                title_info += f" | Policy: {policy_str}"

            md_suffix = f'<sup style="color: #00ff00;" title="{title_info}">✓</sup>'
            md_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}{md_suffix}</claim>'
            )

            pdf_suffix = r"$\textcolor{green}{\textbf{\surd}}$"
            pdf_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}<sup title="{title_info}">{pdf_suffix}</sup></claim>'
            )

            docx_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}{md_suffix}</claim>'
            )

        else:
            verification_stats["mismatched_claims"] += 1
            verification_stats["pending_claims"] += 1
            logger.warning(
                f"✗ Claim {claim_id} 验证失败: 报告中='{clean_inner}', "
                f"数据库中='{claim.value}', 策略='{policy_str}', 原因='{detail}'"
            )

            error_info = f"Expected: {claim.value}"
            if detail:
                error_info += f" | {detail}"

            md_suffix = (
                f'<sup style="color: #ff0000;" title="{error_info}">✗</sup>'
            )
            md_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}{md_suffix}</claim>'
            )

            pdf_suffix = r"$\textcolor{red}{\textbf{\times}}$"
            pdf_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}<sup title="{error_info}">{pdf_suffix}</sup></claim>'
            )

            docx_report_lines.append(
                f'<claim {tag_attrs}>{clean_inner}{md_suffix}</claim>'
            )

    md_report = "".join(md_report_lines)
    pdf_report = "".join(pdf_report_lines)
    docx_report = "".join(docx_report_lines)

    return md_report, pdf_report, docx_report, verification_stats
