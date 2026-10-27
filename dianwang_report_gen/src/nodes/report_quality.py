"""报告结构、核心表格、确定性图表与润色保护。

本模块只消费已有报告文本和 ``derived_metrics.json``，不计算、修改或补造指标。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger


CORE_TABLE_HEADINGS = (
    "方案比选安全硬约束汇总表",
    "方案比选技术性能与工程实施性汇总表",
    "方案比选经济性汇总表",
)

REQUIRED_REPORT_SECTIONS = (
    "报告摘要",
    "周边500kV电网接入点分析",
    "接入系统方案拟定",
    "比选原则与数据完整性",
    "安全硬约束校核",
    "技术性能比较",
    "经济性与全寿命周期比较",
    "工程实施与风险分析",
    "综合比较与结论",
)

CORE_TABLES_START = "<!-- core-summary-tables:start -->"
CORE_TABLES_END = "<!-- core-summary-tables:end -->"
STANDARD_CHARTS_START = "<!-- standard-report-charts:start -->"
STANDARD_CHARTS_END = "<!-- standard-report-charts:end -->"


def _extract_markdown_section(markdown: str, heading: str) -> str:
    """提取指定 Markdown 标题及其正文，直到同级或更高级标题。"""

    pattern = re.compile(
        rf"(?m)^(?P<marks>#{{1,6}})[ \t]+{re.escape(heading)}[ \t]*$"
    )
    match = pattern.search(markdown or "")
    if not match:
        return ""

    level = len(match.group("marks"))
    next_heading = re.compile(rf"(?m)^#{{1,{level}}}[ \t]+.+$")
    following = next_heading.search(markdown, match.end())
    end = following.start() if following else len(markdown)
    return markdown[match.start() : end].strip()


def _demote_section_heading(section: str, heading: str) -> str:
    lines = section.splitlines()
    if lines:
        lines[0] = f"###### {heading}"
    return "\n".join(lines).strip()


def _section_has_markdown_table(section: str) -> bool:
    lines = (section or "").splitlines()
    for index in range(len(lines) - 1):
        header = lines[index].strip()
        separator = lines[index + 1].strip()
        if not (header.startswith("|") and header.endswith("|")):
            continue
        if separator.startswith("|") and separator.endswith("|") and "---" in separator:
            return True
    return False


def ensure_core_summary_tables(report: str, data_tables: str) -> tuple[str, list[str]]:
    """把预处理阶段已有的三张核心汇总表稳定插入报告。

    已存在同名表时不重复；缺失的源表也不会伪造。
    """

    report = report or ""
    if CORE_TABLES_START in report:
        return report, []

    missing_sections: list[str] = []
    inserted_titles: list[str] = []
    for heading in CORE_TABLE_HEADINGS:
        existing = _extract_markdown_section(report, heading)
        if _section_has_markdown_table(existing):
            continue
        section = _extract_markdown_section(data_tables or "", heading)
        if not section:
            missing_sections.append(heading)
            continue
        inserted_titles.append(heading)
        missing_sections.append(_demote_section_heading(section, heading))

    table_blocks = [item for item in missing_sections if item.startswith("###### ")]
    source_missing = [item for item in missing_sections if not item.startswith("###### ")]
    if not table_blocks:
        return report, source_missing

    block = (
        "\n\n"
        + CORE_TABLES_START
        + "\n##### 核心指标汇总\n\n"
        + "以下汇总表由预处理阶段的既有指标结果直接生成，正文分析不得改变其数值、单位和缺失状态。\n\n"
        + "\n\n".join(table_blocks)
        + "\n"
        + CORE_TABLES_END
        + "\n"
    )

    anchors = (
        r"(?m)^####[ \t]+综合比较与结论[ \t]*$",
        r"(?m)^####[ \t]+综合比较推荐方案[ \t]*$",
    )
    insertion_at = -1
    for anchor in anchors:
        match = re.search(anchor, report)
        if match:
            insertion_at = match.start()
            break

    if insertion_at >= 0:
        report = report[:insertion_at].rstrip() + block + "\n" + report[insertion_at:].lstrip()
    else:
        report = report.rstrip() + block

    logger.info("已程序化补入核心汇总表: {}", ", ".join(inserted_titles))
    return report, source_missing


def _metric_series(derived: dict[str, Any], metric_key: str) -> tuple[list[str], list[float]]:
    labels: list[str] = []
    values: list[float] = []
    for index, scheme in enumerate(derived.get("schemes") or [], start=1):
        metric = (scheme.get("metrics") or {}).get(metric_key) or {}
        if metric.get("status") != "ok":
            continue
        value = metric.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        labels.append(str(scheme.get("proposal_name") or f"方案{index}"))
        values.append(float(value))
    return labels, values


def generate_standard_metric_chart(
    derived: dict[str, Any], report_dir: str | Path
) -> str:
    """用已有指标生成固定的三联对比图，返回 Markdown；数据不足时返回空串。"""

    series = []
    specifications = (
        ("n1_pass_rate", "N-1通过率", "%", 1.0, 100.0),
        (
            "min_breaker_interrupt_margin_rate",
            "最小断路器开断裕度率",
            "%",
            1.0,
            0.0,
        ),
        ("annual_cost", "年费用", "百万元/年", 1_000_000.0, None),
    )
    for metric_key, title, unit, scale, threshold in specifications:
        labels, values = _metric_series(derived or {}, metric_key)
        if labels:
            series.append((title, unit, labels, [value / scale for value in values], threshold))

    if not series:
        return ""

    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - 环境依赖失败仅降级为无图
        logger.warning("确定性图表生成已跳过，matplotlib 不可用: {}", exc)
        return ""

    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    figure, axes = plt.subplots(
        1,
        len(series),
        figsize=(5.2 * len(series), 4.6),
        constrained_layout=True,
    )
    if len(series) == 1:
        axes = [axes]

    palette = "#167C80"
    for axis, (title, unit, labels, values, threshold) in zip(axes, series):
        bars = axis.bar(labels, values, color=palette, width=0.62)
        axis.set_title(title, fontsize=12, fontweight="bold")
        axis.set_ylabel(unit)
        axis.grid(axis="y", color="#D9E2E3", linewidth=0.8, alpha=0.85)
        axis.set_axisbelow(True)
        axis.tick_params(axis="x", rotation=25)
        if threshold is not None:
            axis.axhline(
                threshold,
                color="#C0392B",
                linestyle="--",
                linewidth=1.2,
                label=f"判定线 {threshold:g}{unit}",
            )
            axis.legend(frameon=False, fontsize=8)
        for bar, value in zip(bars, values):
            axis.annotate(
                f"{value:,.2f}",
                xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 3 if value >= 0 else -12),
                textcoords="offset points",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=8,
            )

    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = "standard_metric_comparison.png"
    output_path = output_dir / filename
    figure.suptitle("候选方案核心指标对比", fontsize=14, fontweight="bold")
    figure.savefig(output_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)

    logger.info("已生成确定性核心指标图表: {}", output_path)
    return (
        f"![候选方案核心指标对比]({filename})\n\n"
        "图中仅展示 derived_metrics.json 中状态为 ok 的既有指标；未评价项不参与绘图。"
    )


def ensure_standard_chart_section(report: str, chart_markdown: str) -> str:
    if not chart_markdown or STANDARD_CHARTS_START in (report or ""):
        return report

    block = (
        "\n\n"
        + STANDARD_CHARTS_START
        + "\n##### 核心指标图示\n\n"
        + chart_markdown.strip()
        + "\n"
        + STANDARD_CHARTS_END
        + "\n"
    )
    anchor = re.search(r"(?m)^####[ \t]+综合比较(?:与结论|推荐方案)[ \t]*$", report)
    if anchor:
        return report[: anchor.start()].rstrip() + block + "\n" + report[anchor.start() :].lstrip()
    return report.rstrip() + block


def protect_verifiable_blocks(report: str) -> tuple[str, dict[str, str]]:
    """润色前保护 Claim、Calculate、表格、图片和程序插入块。"""

    patterns = (
        re.compile(r"<(?:claim|calculate)\b[^>]*>.*?</(?:claim|calculate)>", re.I | re.S),
        re.compile(r"(?m)(?:^[ \t]*\|.*\|[ \t]*\r?\n){2,}"),
        re.compile(r"!\[[^\]]*\]\([^\r\n)]+\)"),
    )
    matches = []
    occupied: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in pattern.finditer(report or ""):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in occupied):
                continue
            occupied.append(span)
            matches.append((span[0], span[1], match.group(0)))

    matches.sort(key=lambda item: item[0])
    blocks: dict[str, str] = {}
    chunks = []
    cursor = 0
    for index, (start, end, content) in enumerate(matches):
        token = f"<!-- REPORT_PROTECTED_BLOCK_{index:04d} -->"
        chunks.append(report[cursor:start])
        chunks.append(token)
        blocks[token] = content
        cursor = end
    chunks.append(report[cursor:])
    return "".join(chunks), blocks


def restore_verifiable_blocks(
    optimized_report: str, blocks: dict[str, str]
) -> tuple[str, bool]:
    restored = optimized_report or ""
    for token, content in blocks.items():
        if restored.count(token) != 1:
            return optimized_report, False
        restored = restored.replace(token, content)
    return restored, True


def assess_report_structure(report: str) -> dict[str, Any]:
    text = report or ""
    missing_sections = [title for title in REQUIRED_REPORT_SECTIONS if title not in text]
    missing_core_tables = [
        title
        for title in CORE_TABLE_HEADINGS
        if not _section_has_markdown_table(_extract_markdown_section(text, title))
    ]
    return {
        "required_sections": len(REQUIRED_REPORT_SECTIONS),
        "missing_sections": missing_sections,
        "core_tables": len(CORE_TABLE_HEADINGS),
        "missing_core_tables": missing_core_tables,
        "image_count": len(re.findall(r"!\[[^\]]*\]\([^)]+\)", text)),
        "claim_count": len(re.findall(r"<claim\b", text, flags=re.I)),
        "calculate_count": len(re.findall(r"<calculate\b", text, flags=re.I)),
        "structure_passed": not missing_sections and not missing_core_tables,
    }


def format_report_quality_review_message(quality: dict[str, Any]) -> str:
    """把结构检查结果转换成面向使用者的简短复核提示。"""

    missing_sections = quality.get("missing_sections") or []
    missing_tables = quality.get("missing_core_tables") or []
    details: list[str] = []
    if missing_sections:
        details.append("缺少章节：" + "、".join(str(item) for item in missing_sections))
    if missing_tables:
        details.append("缺少核心表：" + "、".join(str(item) for item in missing_tables))
    if not details:
        details.append("结构检查未通过，请检查报告完整性")
    return "报告已生成，但结构质量检查需要人工复核（" + "；".join(details) + "）。"
