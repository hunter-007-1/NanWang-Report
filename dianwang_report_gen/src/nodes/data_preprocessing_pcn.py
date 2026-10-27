import re
import copy
import json
import math
import faiss
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple
from loguru import logger
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_community.docstore.in_memory import InMemoryDocstore

from src.graph_state import State
from src.utils import load_json
from src.pcn import Claim
from src.pcn_database import PCNDatabase
from src.llm import client_manager


async def data_preprocessing_pcn(state: State) -> dict:
    logger.info("=== 开始 PCN 数据预处理节点 ===")
    input_dir = state.input_dir
    output_dir = state.output_dir
    working_dir = state.working_dir

    # 确保 working_dir 存在
    working_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"输入目录: {input_dir}")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"工作目录: {working_dir}")

    background_context = ""
    background_context_source = ""
    try:
        bg_path = Path(input_dir) / "generation" / "background_context.md"
        if bg_path.exists() and bg_path.is_file():
            content = bg_path.read_text(encoding="utf-8").strip()
            if content:
                background_context = content
                background_context_source = "generation/background_context.md"
                logger.info(
                    f"已读取工程背景资料: {background_context_source} "
                    f"（{len(background_context)} 字符）"
                )
            else:
                logger.warning("背景资料文件为空，前置工程分析将按输入不足处理")
        else:
            logger.info("未找到背景资料文件，前置工程分析将按输入不足处理")
    except Exception as exc:
        logger.warning(f"读取背景资料失败，将按无背景资料继续: {exc}")

    # 步骤1: 尝试过滤数据（如果数据结构符合预期）
    data_filtered = filter_data(input_dir, working_dir)

    # 步骤1.5: 先生成派生指标（必须在 claims 提取之前，否则无法进入证据库）
    logger.info("生成 derived_metrics.json（第一批派生比选指标）...")
    build_derived_metrics(working_dir)

    # 步骤2: 从数据中提取 claims
    logger.info(f"\n步骤 2/4: 提取 PCN claims...")
    json_files = list(working_dir.rglob("*.json"))
    logger.info(f"找到 {len(json_files)} 个 JSON 文件")
    logger.debug(
        f"JSON 文件列表: {[str(f.relative_to(working_dir)) for f in json_files]}"
    )

    claims_list = []
    claim_counter = [0]
    logger.info("开始递归提取 claims...")

    for json_file in json_files:
        relative_path = str(json_file.relative_to(working_dir))
        logger.debug(f"处理文件: {relative_path}")

        try:
            data = load_json(str(json_file))
            if data is None:
                continue

            # 派生指标使用专用提取，避免 metrics.value → indicator="value"
            if json_file.name == "derived_metrics.json":
                extract_derived_metric_claims(
                    data, relative_path, claims_list, claim_counter
                )
                continue

            extract_claims_recursive(
                data, relative_path, [], claims_list, claim_counter
            )

        except Exception as e:
            logger.error(f"处理文件失败 {relative_path}: {e}")
            continue

    logger.info(f"✓ 总共提取 {len(claims_list)} 个 claims")

    # 步骤3: 去重
    logger.info(f"\n步骤 3/4: Claims 去重...")
    original_count = len(claims_list)
    claims_list = deduplicate_claims(claims_list)
    deduplicate_count = original_count - len(claims_list)
    logger.info(
        f"去重完成：原始 {original_count} 个，去重 {deduplicate_count} 个，保留 {len(claims_list)} 个"
    )

    # 步骤4: 创建 SQLite FTS5 数据库
    logger.info(f"\n步骤 4/4: 创建 SQLite FTS5 数据库...")

    db_path = output_dir / "pcn_claims.db"

    with PCNDatabase(str(db_path)) as db:
        # 初始化表结构
        db.init_schema()

        # 批量插入 claims
        db.insert_claims_batch(claims_list, batch_size=100)

        # 获取统计信息
        stats = db.get_statistics()
        logger.info(f"数据库统计: {stats['total_claims']} 个 claims")
        logger.info(f"按指标类型: {list(stats['by_indicator'].keys())[:5]}")

    logger.info(f"PCN claims 数据库创建完成: {db_path}")

    claims_dict = {claim.claim_id: claim for claim in claims_list}
    logger.info(f"Claims 字典键数量: {len(claims_dict)}")

    claims_by_field = {}
    for claim in claims_list:
        field = claim.indicator
        if field not in claims_by_field:
            claims_by_field[field] = []
        claims_by_field[field].append(claim)
    logger.info(f"按指标分组完成，共 {len(claims_by_field)} 种指标")

    # 生成数据表格
    logger.info("生成过滤后数据的 markdown 表格...")
    md_tables_str = convert_filtered_data_to_markdown_tables(working_dir)
    md_tables_file = working_dir / "data_tables.md"
    md_tables_file.write_text(md_tables_str, encoding="utf-8")
    logger.info(f"数据表格已保存到 {md_tables_file}")

    logger.info("保存 claims JSON 文件...")
    claims_file = working_dir / "pcn_claims.json"
    claims_serializable = [
        {
            "claim_id": c.claim_id,
            "indicator": c.indicator,
            "value": c.value,
            "metadata": c.metadata,
        }
        for c in claims_list
    ]
    claims_file.write_text(
        json.dumps(claims_serializable, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"Claims 已保存到 {claims_file}")
    logger.info(f"JSON 序列化对象数量: {len(claims_serializable)}")

    logger.info(f"Claims 统计:")
    logger.info(f"  总数: {len(claims_list)}")
    logger.info(
        f"  按指标类型: {[(k, len(v)) for k, v in sorted(claims_by_field.items())]}"
    )
    logger.info(f"  数据是否被过滤: {'是' if data_filtered else '否'}")

    logger.info("\n=== PCN claim 挖掘完成 ===")

    return {
        "pcn_claims": claims_dict,
        "pcn_claim_index": claims_by_field,
        "md_tables_str": md_tables_str,
        "pcn_db_path": db_path,
        "data_filtered": data_filtered,
        "background_context": background_context,
        "background_context_source": background_context_source,
    }


# ============================================================================
# 数据过滤配置
# ============================================================================

FIELD_FILTERS = {
    # parsed_proposals.json 保留字段
    "parsed_proposals": {
        "keep": ["proposals"],
        "nested": {
            "proposals": {
                "keep": [
                    "proposal_name",
                    "description",
                    "construction_cost",
                    "operation_cost",
                    "annual_cost",  # 年费用（与 lifecycle_cost 独立）
                    "lifecycle_cost",  # 全寿命周期成本 LCC（与 annual_cost 独立）
                    "_economic_provenance",  # 内部：provided/calculated/migrated
                    # 完整折现 LCC 参数（缺一则不得冒充 full_calculated）
                    "cash_flows",
                    "lifecycle_cash_flows",
                    "discount_rate",
                    "evaluation_years",
                    "interest_rate",
                    "years",
                    "modifications",
                    "new_line_length",
                    "retrofit_line_length",
                    "grid_data",
                ],
                "nested": {
                    "modifications": {
                        "keep": ["action", "is_retrofit", "length_km", "length", "params"],
                        "nested": {
                            "params": {
                                "keep": ["full_branch_data"],
                                "nested": {
                                    "full_branch_data": {
                                        "keep": [
                                            "TYPE",
                                            "NAME1",
                                            "NAME2",
                                            "BASE1",
                                            "BASE2",
                                            "CKT ID",
                                            "MILES",
                                            "miles",
                                            "length_km",
                                            "长度_km",
                                            "length",
                                            "LINE NAME",
                                            "TOTAL CURRENT RATE AMP",
                                        ]
                                    }
                                },
                            }
                        },
                    },
                    "grid_data": {
                        "keep": ["buses", "branches"],
                        "nested": {
                            "buses": {
                                "keep": [
                                    "TYPE",
                                    "NAME",
                                    "BASE",
                                    "ZONE",
                                    "LOAD_P",
                                    "LOAD_Q",
                                    "GEN_P_MAX",
                                    "GEN_P",
                                    "VMAX",
                                    "VMIN",
                                ]
                            },
                            "branches": {
                                "keep": [
                                    "TYPE",
                                    "NAME1",
                                    "NAME2",
                                    "BASE1",
                                    "BASE2",
                                    "CKT ID",
                                    "TOTAL CURRENT RATE AMP",
                                    "R",
                                    "X",
                                    "B",
                                    "MILES",
                                    "LINE NAME",
                                ]
                            },
                        },
                    }
                },
            }
        },
    },
    # pf_report_N.json 保留字段
    "pf_report": {
        "keep": ["proposal_index", "analysis"],
        "nested": {
            "analysis": {
                "keep": [
                    "is_convergent",
                    "overloaded_lines",
                    "overloaded_transformers",
                    "voltage_abnormal_nodes",
                    "power_summary",
                    "balance_summary",
                    "bus_voltages",
                    "voltage_results",
                    "all_bus_voltages",
                    "evaluated_buses",
                    "node_period_voltages",
                    "bus_period_voltages",
                    "voltage_time_series",
                    "line_loadings",
                    "all_line_results",
                    "line_results",
                    "branch_loadings",
                    "transformer_loadings",
                    "all_transformer_results",
                    "transformer_results",
                    "critical_sections",
                    "sections",
                    "section_flows",
                    "voltage_qualification_rate",
                    "voltage_over_limit_severity",
                    "node_period_voltage_over_limit_rate",
                    "max_line_loading_rate",
                    "max_transformer_loading_rate",
                    "active_power_loss_rate",
                    "critical_section_margin_rate",
                    "active_power_loss_mw",
                    "input_active_power_mw",
                ],
                "nested": {
                    "overloaded_lines": {
                        "keep": [
                            "问题描述",
                            "卡片类型",
                            "线路端点1",
                            "线路端点2",
                            "电流(A)",
                            "额定电流(A)",
                            "电流比例(%)",
                            "视在功率(MVA)",
                            "视在功率比例(%)",
                        ]
                    },
                    "overloaded_transformers": {
                        "keep": [
                            "问题描述",
                            "名称",
                            "负载率(%)",
                            "视在功率(MVA)",
                            "额定容量(MVA)",
                        ]
                    },
                    "voltage_abnormal_nodes": {
                        "keep": [
                            "问题描述",
                            "分区",
                            "节点",
                            "类型",
                            "电压(kV)",
                            "标幺电压(pu)",
                            "越界电压值(pu)",
                        ]
                    },
                    "power_summary": {"keep": ["损耗_MW", "总负荷_MW", "总发电_MW"]},
                    "balance_summary": {"keep": ["区域", "平衡机", "实际功率"]},
                },
            }
        },
    },
    # n1_report_N.json 保留字段
    # 说明：当前历史案例 contingencies_with_issues 主要为问题故障列表；
    # 若未来提供负荷相关字段，一并保留以便计算加权通过率。
    "n1_report": {
        "keep": [
            "total_contingencies_run",
            "contingencies_with_issues",
            "passed_load",
            "total_load",
            "weighted_n1_pass_rate",
            "weighted_n1_mode",
            "post_contingency_equipment_loadings",
            "all_contingency_results",
            "post_contingency_voltages",
            "fault_node_voltages",
            "all_contingency_voltage_results",
            "post_contingency_max_equipment_loading_rate",
            "post_contingency_voltage_over_limit_rate",
        ],
        "nested": {
            "contingencies_with_issues": {
                "keep": [
                    "contingency_branch_uid",
                    "result",
                    "load_mw",
                    "associated_load_mw",
                    "lost_load_mw",
                    "transferred_load_mw",
                    "passed_load_mw",
                ],
                "nested": {
                    "result": {
                        "keep": ["analysis"],
                        "nested": {
                            "analysis": {
                                "keep": [
                                    "is_convergent",
                                    "overloaded_lines",
                                    "overloaded_transformers",
                                ],
                                "nested": {
                                    "overloaded_lines": {
                                        "keep": [
                                            "问题描述",
                                            "卡片类型",
                                            "线路端点1",
                                            "线路端点2",
                                            "电流(A)",
                                            "额定电流(A)",
                                            "电流比例(%)",
                                            "视在功率(MVA)",
                                            "额定视在功率(MVA)",
                                            "视在功率比例(%)",
                                            "负载率(%)",
                                        ]
                                    },
                                    "overloaded_transformers": {
                                        "keep": [
                                            "问题描述",
                                            "卡片类型",
                                            "名称",
                                            "负载率(%)",
                                            "视在功率(MVA)",
                                            "额定容量(MVA)",
                                        ]
                                    },
                                },
                            }
                        },
                    }
                },
            }
        },
    },
    # scc_report_N.json 保留字段
    # total_buses/check_count/effective_check_count 为有效校核分母候选；
    # node_id 等备用节点标识用于唯一越限节点去重。
    "scc_report": {
        "keep": ["analysis"],
        "nested": {
            "analysis": {
                "keep": [
                    "total_buses",
                    "check_count",
                    "effective_check_count",
                    "exceeding_buses",
                    "contingencies_with_issues",
                    "threshold_kA",
                    "remaining_issues",
                ],
                "nested": {
                    "exceeding_buses": {
                        "keep": [
                            "bus_name",
                            "node_id",
                            "bus_id",
                            "node_name",
                            "节点",
                            "short_circuit_current_kA",
                            "breaker_current_kA",
                            "voltage_kV",
                            "fault_type",
                            "partition",
                        ]
                    },
                    "contingencies_with_issues": {
                        "keep": [
                            "bus_name",
                            "node_id",
                            "bus_id",
                            "node_name",
                            "节点",
                            "short_circuit_current_kA",
                            "breaker_current_kA",
                            "voltage_kV",
                            "fault_type",
                            "partition",
                        ]
                    }
                },
            }
        },
    },
}


def list_analysis_indices(root_dir: Path) -> List[int]:
    indices = []
    for path in root_dir.iterdir():
        if not path.is_dir():
            continue
        match = re.fullmatch(r"analysis_(\d+)", path.name)
        if match:
            indices.append(int(match.group(1)))
    return sorted(indices)


# ============================================================================
# 数据过滤函数
# ============================================================================


def filter_dict_by_config(
    data: Any, filter_config: Dict, is_list_item: bool = False
) -> Any:
    """
    根据配置过滤字典数据

    Args:
        data: 原始数据（字典、列表或基本类型）
        filter_config: 过滤配置
        is_list_item: 是否为数组项（用于递归处理）

    Returns:
        过滤后的数据
    """
    # 处理 null 值
    if data is None:
        return None
    # 处理基本类型（直接返回）
    elif not isinstance(data, (dict, list)):
        return data
    # 处理字典
    elif isinstance(data, dict):
        result = {}

        # 如果有 keep 配置，只保留指定字段
        if "keep" in filter_config:
            for key in filter_config["keep"]:
                if key in data:
                    result[key] = data[key]
        else:
            # 没有 keep 配置，保留所有字段
            result = copy.deepcopy(data)

        # 递归处理嵌套结构
        if "nested" in filter_config:
            for nested_key, nested_config in filter_config["nested"].items():
                if nested_key in result:
                    nested_data = result[nested_key]

                    # 处理数组中的每一项
                    if isinstance(nested_data, list):
                        result[nested_key] = [
                            filter_dict_by_config(
                                item, nested_config, is_list_item=True
                            )
                            for item in nested_data
                        ]
                    # 处理嵌套字典
                    elif isinstance(nested_data, dict):
                        result[nested_key] = filter_dict_by_config(
                            nested_data, nested_config
                        )

        return result
    # 处理列表
    elif isinstance(data, list):
        if is_list_item:
            # 数组项使用父级配置继续过滤
            # 暂时不过滤，直接返回
            return data
        else:
            # 顶层列表，逐项处理
            return [
                filter_dict_by_config(item, filter_config, is_list_item=True)
                for item in data
            ]
    else:
        # 理论上不应该到达这里
        return data


def save_json_file(data: Any, output_file: Path) -> None:
    """保存JSON文件，确保使用UTF-8编码"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def filter_parsed_proposals_file(input_file: Path, output_file: Path) -> None:
    """过滤 parsed_proposals.json"""
    logger.info(f"📄 处理方案数据: {input_file}")

    data = json.loads(input_file.read_text(encoding="utf-8"))
    filtered_data = filter_dict_by_config(data, FIELD_FILTERS["parsed_proposals"])

    # 统计信息
    original_buses = sum(
        len(p.get("grid_data", {}).get("buses", [])) for p in data.get("proposals", [])
    )
    filtered_buses = sum(
        len(p.get("grid_data", {}).get("buses", []))
        for p in filtered_data.get("proposals", [])
    )
    original_branches = sum(
        len(p.get("grid_data", {}).get("branches", []))
        for p in data.get("proposals", [])
    )
    filtered_branches = sum(
        len(p.get("grid_data", {}).get("branches", []))
        for p in filtered_data.get("proposals", [])
    )

    logger.info(f"  ✓ 节点: {original_buses} → {filtered_buses}")
    logger.info(f"  ✓ 线路: {original_branches} → {filtered_branches}")

    # 保存
    save_json_file(filtered_data, output_file)
    logger.info(f"  ✓ 保存到: {output_file}")


def filter_pf_report_file(input_file: Path, output_file: Path) -> None:
    """过滤 pf_report_N.json"""
    logger.info(f"📄 处理潮流分析报告: {input_file}")

    data = json.loads(input_file.read_text(encoding="utf-8"))
    filtered_data = filter_dict_by_config(data, FIELD_FILTERS["pf_report"])

    # 统计
    analysis = data.get("analysis", {})
    filtered_analysis = filtered_data.get("analysis", {})
    logger.info(f"  ✓ 原始字段数: {len(analysis)}")
    logger.info(f"  ✓ 保留字段数: {len(filtered_analysis)}")

    # 保存
    save_json_file(filtered_data, output_file)
    logger.info(f"  ✓ 保存到: {output_file}")


def filter_n1_report_file(input_file: Path, output_file: Path) -> None:
    """过滤 n1_report_N.json"""
    logger.info(f"📄 处理N-1安全分析报告: {input_file}")

    data = json.loads(input_file.read_text(encoding="utf-8"))
    filtered_data = filter_dict_by_config(data, FIELD_FILTERS["n1_report"])

    # 统计
    total = data.get("total_contingencies_run", 0)
    issues = len(data.get("contingencies_with_issues", []))
    logger.info(f"  ✓ 总故障数: {total}")
    logger.info(f"  ✓ 故障记录数: {issues}")

    # 保存
    save_json_file(filtered_data, output_file)
    logger.info(f"  ✓ 保存到: {output_file}")


def filter_scc_report_file(input_file: Path, output_file: Path) -> None:
    """过滤 scc_report_N.json"""
    logger.info(f"📄 处理短路电流分析报告: {input_file}")

    data = json.loads(input_file.read_text(encoding="utf-8"))
    filtered_data = filter_dict_by_config(data, FIELD_FILTERS["scc_report"])

    # 统计
    analysis = data.get("analysis", {})
    filtered_analysis = filtered_data.get("analysis", {})
    exceeding = len(analysis.get("exceeding_buses", []) or analysis.get("contingencies_with_issues", []))
    logger.info(f"  ✓ 超标节点数: {exceeding}")
    logger.info(f"  ✓ 原始字段数: {len(analysis)}")
    logger.info(f"  ✓ 保留字段数: {len(filtered_analysis)}")

    # 保存
    save_json_file(filtered_data, output_file)
    logger.info(f"  ✓ 保存到: {output_file}")


def filter_data(input_dir: Path, working_dir: Path) -> bool:
    """
    过滤所有数据文件到工作目录

    Args:
        input_dir: 输入目录
        working_dir: 工作目录

    Returns:
        bool: 是否进行了数据过滤（总是返回 True）
    """
    logger.info("步骤 1/4: 尝试过滤原始数据...")

    # 创建输出目录
    working_dir.mkdir(parents=True, exist_ok=True)

    # 1. 过滤方案数据
    proposals_file = input_dir / "generation" / "parsed_proposals.json"
    if proposals_file.exists():
        filter_parsed_proposals_file(
            proposals_file, working_dir / "parsed_proposals.json"
        )
    else:
        logger.warning(f"⚠️  未找到: {proposals_file}")

    # 2. 过滤各方案的分析报告
    for i in list_analysis_indices(input_dir):
        analysis_dir = input_dir / f"analysis_{i}"
        if not analysis_dir.exists():
            logger.warning(f"⚠️  未找到分析目录: {analysis_dir}")
            continue

        logger.info(f"--- 处理方案 {i} ---")

        # 潮流分析报告
        pf_file = analysis_dir / f"pf_report_{i}.json"
        if pf_file.exists():
            filter_pf_report_file(
                pf_file, working_dir / f"analysis_{i}" / f"pf_report_{i}.json"
            )

        # N-1安全分析报告
        n1_file = analysis_dir / f"n1_report_{i}.json"
        if n1_file.exists():
            filter_n1_report_file(
                n1_file, working_dir / f"analysis_{i}" / f"n1_report_{i}.json"
            )

        # 短路电流分析报告
        scc_file = analysis_dir / f"scc_report_{i}.json"
        if scc_file.exists():
            filter_scc_report_file(
                scc_file, working_dir / f"analysis_{i}" / f"scc_report_{i}.json"
            )

    logger.info("=" * 60)
    logger.info("✓ 数据过滤完成！")
    logger.info(f"输出目录: {working_dir}")
    logger.info("=" * 60)
    logger.info(f"将从过滤后的数据提取 claims: {working_dir}")

    return True


def convert_filtered_data_to_markdown_tables(working_dir: Path) -> str:
    """
    将过滤后的 JSON 数据转换为 markdown 表格

    Args:
        working_dir: 工作目录，包含过滤后的 JSON 文件

    Returns:
        str: 所有表格的 markdown 字符串
    """
    md_sections = []

    # 1. 处理方案数据
    proposals_file = working_dir / "parsed_proposals.json"
    if proposals_file.exists():
        logger.info("转换方案数据到 markdown 表格...")
        data = json.loads(proposals_file.read_text(encoding="utf-8"))
        md_sections.append(convert_proposals_to_md(data))

    summary_md = convert_core_comparison_summary_to_md(working_dir)
    if summary_md:
        md_sections.append(summary_md)

    # 2. 处理各方案的分析报告
    for i in list_analysis_indices(working_dir):
        analysis_dir = working_dir / f"analysis_{i}"
        if not analysis_dir.exists():
            continue

        # 潮流分析报告
        pf_file = analysis_dir / f"pf_report_{i}.json"
        if pf_file.exists():
            logger.info(f"转换方案 {i} 潮流分析数据到 markdown 表格...")
            data = json.loads(pf_file.read_text(encoding="utf-8"))
            md_sections.append(f"\n## 方案 {i} - 潮流分析\n")
            md_sections.append(convert_pf_to_md(data))

        # N-1安全分析报告
        n1_file = analysis_dir / f"n1_report_{i}.json"
        if n1_file.exists():
            logger.info(f"转换方案 {i} N-1 分析数据到 markdown 表格...")
            data = json.loads(n1_file.read_text(encoding="utf-8"))
            md_sections.append(convert_nx_to_md(data, n=1))

        # 短路电流分析报告
        scc_file = analysis_dir / f"scc_report_{i}.json"
        if scc_file.exists():
            logger.info(f"转换方案 {i} 短路电流分析数据到 markdown 表格...")
            data = json.loads(scc_file.read_text(encoding="utf-8"))
            md_sections.append(convert_scc_to_md(data))

    return "\n".join(md_sections)


def _metric_rule_formula(
    metric_name: str, calculation_mode: Optional[str] = None
) -> Any:
    from src.tools.grid_calculator import _load_rules

    rules = _load_rules()
    metric = (rules.get("metrics") or {}).get(metric_name) or {}
    by_mode = metric.get("formula_by_mode") or {}
    if calculation_mode and isinstance(by_mode, dict) and calculation_mode in by_mode:
        return by_mode.get(calculation_mode)
    return metric.get("formula") or ""


def _metric_rule_unit(metric_name: str) -> str:
    from src.tools.grid_calculator import _load_rules

    rules = _load_rules()
    return str(((rules.get("metrics") or {}).get(metric_name) or {}).get("unit") or "")


def _derived_metric_entry(
    *,
    value: Any,
    unit: str,
    formula: Any = None,
    inputs: Optional[Dict[str, Any]] = None,
    input_source: str = "",
    display_value: Any = None,
    missing_fields: Optional[List[str]] = None,
    provenance: Optional[str] = None,
    source_field: Optional[str] = None,
    status: Optional[str] = None,
    calculation_mode: Optional[str] = None,
    coverage: Optional[Dict[str, Any]] = None,
    invalid_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """构造派生指标条目；缺数时 value=null 且默认 status=missing_data。"""
    if value is None:
        resolved_status = status or "missing_data"
        default_display = (
            NOT_APPLICABLE_TEXT
            if resolved_status == "not_applicable"
            else MISSING_DATA_TEXT
        )
        entry: Dict[str, Any] = {
            "value": None,
            "display_value": display_value if display_value is not None else default_display,
            "unit": unit,
            "formula": formula,
            "inputs": inputs or {},
            "input_source": input_source,
            "status": resolved_status,
            "missing_fields": missing_fields or [],
        }
        if invalid_fields:
            entry["invalid_fields"] = list(invalid_fields)
    else:
        entry = {
            "value": value,
            "unit": unit,
            "formula": formula,
            "inputs": inputs or {},
            "input_source": input_source,
            "status": status or "ok",
        }
        if display_value is not None:
            entry["display_value"] = display_value
    if provenance is not None:
        entry["provenance"] = provenance
    if source_field is not None:
        entry["source_field"] = source_field
    if calculation_mode is not None:
        entry["calculation_mode"] = calculation_mode
    if coverage is not None:
        entry["coverage"] = coverage
    return entry


def _entry_from_adapter(
    metric_name: str,
    adapter_result: Dict[str, Any],
) -> Dict[str, Any]:
    """将 second_batch_adapters 结果转为 derived_metrics 条目。"""
    status = adapter_result.get("status") or "missing_data"
    value = adapter_result.get("value")
    # 适配器明确返回 unit（含 ""）时保留；未设置时才回退规则默认单位
    if "unit" in adapter_result:
        unit = adapter_result.get("unit")
        if unit is None:
            unit = ""
        else:
            unit = str(unit)
    else:
        unit = _metric_rule_unit(metric_name)
    return _derived_metric_entry(
        value=value,
        unit=unit,
        formula=_metric_rule_formula(metric_name),
        inputs=adapter_result.get("inputs") or {},
        input_source=adapter_result.get("input_source") or "",
        missing_fields=adapter_result.get("missing_fields") or [],
        invalid_fields=adapter_result.get("invalid_fields") or [],
        provenance=adapter_result.get("provenance"),
        status=status,
        calculation_mode=adapter_result.get("calculation_mode"),
        coverage=adapter_result.get("coverage"),
        display_value=(
            NOT_APPLICABLE_TEXT
            if status == "not_applicable"
            else (None if value is not None else MISSING_DATA_TEXT)
        ),
    )


def build_derived_metrics(working_dir: Path) -> Dict[str, Any]:
    """统一计算第一批派生比选指标，写入 working_dir/derived_metrics.json。

    汇总表与 claims 均应复用本结果，避免多套公式。
    """
    indices = list_analysis_indices(working_dir)
    proposal_meta = load_proposal_metadata(working_dir / "parsed_proposals.json")
    schemes: List[Dict[str, Any]] = []

    for index in indices:
        analysis_dir = working_dir / f"analysis_{index}"
        pf_rel = f"analysis_{index}/pf_report_{index}.json"
        n1_rel = f"analysis_{index}/n1_report_{index}.json"
        scc_rel = f"analysis_{index}/scc_report_{index}.json"
        proposal_rel = "parsed_proposals.json"

        n1_data = load_json_file(analysis_dir / f"n1_report_{index}.json")
        scc_data = load_json_file(analysis_dir / f"scc_report_{index}.json")
        pf_data = load_json_file(analysis_dir / f"pf_report_{index}.json")
        proposal = proposal_meta.get(index, {})
        scheme_name = proposal.get("name") or f"方案{index}"

        total, issues, pass_rate, _band, _max_ol, weighted_pass_rate = summarize_n1(n1_data)
        analysis = (scc_data.get("analysis") or {}) if scc_data else {}
        scc_issue_info = get_scc_issue_records(analysis)
        scc_records = scc_issue_info["records"]
        (
            scc_count,
            over_limit_ratio,
            min_margin_rate,
            _max_i,
            _max_b,
        ) = summarize_scc(scc_data, scheme_label=scheme_name)

        is_convergent_raw = (pf_data.get("analysis") or {}).get("is_convergent")
        pf_display = format_pf_convergence(is_convergent_raw)
        pf_value = None
        pf_missing: List[str] = []
        if is_convergent_raw is None:
            pf_missing = ["analysis.is_convergent"]
        else:
            try:
                from src.tools.grid_calculator import calculate_grid_metric

                pf_value = float(
                    calculate_grid_metric(
                        "pf_convergence", {"is_convergent": is_convergent_raw}
                    )["value"]
                )
            except ValueError:
                pf_missing = ["analysis.is_convergent"]

        pass_count = None
        if isinstance(total, (int, float)) and not isinstance(total, bool) and issues is not None:
            pass_count = total - issues

        n1_pass_missing: List[str] = []
        if pass_rate is None:
            total_ok = (
                isinstance(total, (int, float))
                and not isinstance(total, bool)
                and total > 0
            )
            if not total_ok:
                n1_pass_missing.append("total_contingencies_run")
            if "contingencies_with_issues" not in n1_data:
                n1_pass_missing.append("contingencies_with_issues")
            elif not isinstance(n1_data.get("contingencies_with_issues"), list):
                n1_pass_missing.append("contingencies_with_issues")
            elif (
                total_ok
                and issues is not None
                and issues > total
            ):
                n1_pass_missing.extend(
                    ["total_contingencies_run", "contingencies_with_issues"]
                )
            if not n1_pass_missing:
                n1_pass_missing = ["total_contingencies_run", "contingencies_with_issues"]

        scc_issue_missing = [
            "analysis.exceeding_buses",
            "analysis.contingencies_with_issues",
        ]
        scc_denom_missing = [
            "analysis.effective_check_count",
            "analysis.check_count",
            "analysis.total_buses",
        ]

        def _economic_derived(
            metric_name: str,
            value: Any,
            provenance: str,
            source_field: Any,
        ) -> Dict[str, Any]:
            if provenance == "invalid":
                inv_key = f"{metric_name}_invalid_fields"
                err_key = f"{metric_name}_validation_error"
                invalid_fields = proposal.get(inv_key) or [metric_name]
                err = proposal.get(err_key)
                if metric_name == "lifecycle_cost" and not err:
                    err = proposal.get("lifecycle_validation_error")
                inputs: Dict[str, Any] = {}
                if err:
                    inputs["validation_error"] = err
                if metric_name == "lifecycle_cost":
                    inputs["lifecycle_full_input_supplied"] = proposal.get(
                        "lifecycle_full_input_supplied"
                    )
                    inputs["lifecycle_full_input_any"] = proposal.get(
                        "lifecycle_full_input_any"
                    )
                    inputs["lifecycle_full_input_invalid"] = proposal.get(
                        "lifecycle_full_input_invalid"
                    )
                return _derived_metric_entry(
                    value=None,
                    unit=_metric_rule_unit(metric_name),
                    formula=None,
                    inputs=inputs,
                    input_source=proposal_rel,
                    provenance="invalid",
                    source_field=source_field,
                    status="invalid_data",
                    calculation_mode="invalid",
                    missing_fields=[],
                    invalid_fields=list(invalid_fields),
                )
            if provenance == "provided":
                return _derived_metric_entry(
                    value=value,
                    unit=_metric_rule_unit(metric_name),
                    formula=None,
                    inputs={metric_name: value},
                    input_source=proposal_rel,
                    provenance=provenance,
                    source_field=source_field,
                    calculation_mode="provided",
                    missing_fields=[] if value is not None else [metric_name],
                )
            if provenance == "migrated":
                return _derived_metric_entry(
                    value=value,
                    unit=_metric_rule_unit(metric_name),
                    formula=None,
                    inputs={"legacy_lifecycle_cost": value},
                    input_source=str(source_field or "legacy.lifecycle_cost"),
                    provenance=provenance,
                    source_field=source_field or "legacy.lifecycle_cost",
                    calculation_mode="migrated",
                    missing_fields=[] if value is not None else [metric_name],
                )
            if provenance == "extracted_from_description":
                return _derived_metric_entry(
                    value=value,
                    unit=_metric_rule_unit(metric_name),
                    formula=None,
                    inputs={metric_name: value},
                    input_source="parsed_proposals.json#description",
                    provenance=provenance,
                    source_field=source_field or "description",
                    calculation_mode="extracted_from_description",
                    missing_fields=[] if value is not None else [metric_name],
                )
            if provenance == "calculated":
                calc_mode = (
                    "estimated_simplified"
                    if metric_name == "lifecycle_cost"
                    else "formula"
                )
                if metric_name == "annual_cost":
                    inputs = {
                        "construction_cost": proposal.get("construction_cost_yuan"),
                        "operation_cost": proposal.get("operation_cost_yuan"),
                        "interest_rate": proposal.get("interest_rate"),
                        "years": proposal.get("years"),
                    }
                    missing = (
                        []
                        if value is not None
                        else ["construction_cost", "operation_cost"]
                    )
                elif metric_name == "lifecycle_cost":
                    calc_mode = (
                        proposal.get("lifecycle_calculation_mode")
                        or "estimated_simplified"
                    )
                    if calc_mode == "full_calculated":
                        cash_flows = proposal.get("lifecycle_cash_flows") or []
                        inputs = {
                            "construction_cost": proposal.get("construction_cost_yuan"),
                            "cash_flows": cash_flows,
                            "discount_rate": proposal.get("discount_rate"),
                            "evaluation_years": proposal.get("evaluation_years"),
                            "cash_flow_count": len(cash_flows)
                            if isinstance(cash_flows, list)
                            else 0,
                        }
                        missing = (
                            []
                            if value is not None
                            else [
                                "cash_flows",
                                "discount_rate",
                                "evaluation_years",
                            ]
                        )
                    else:
                        inputs = {
                            "construction_cost": proposal.get("construction_cost_yuan"),
                            "factor": proposal.get("lifecycle_factor"),
                        }
                        missing = [] if value is not None else ["construction_cost"]
                else:
                    inputs = {metric_name: value}
                    missing = [] if value is not None else [metric_name]
                return _derived_metric_entry(
                    value=value,
                    unit=_metric_rule_unit(metric_name),
                    formula=_metric_rule_formula(metric_name, calc_mode),
                    inputs=inputs,
                    input_source=proposal_rel,
                    provenance=provenance,
                    source_field=source_field,
                    calculation_mode=calc_mode,
                    missing_fields=missing,
                )
            return _derived_metric_entry(
                value=None,
                unit=_metric_rule_unit(metric_name),
                formula=None,
                inputs={},
                input_source=proposal_rel,
                provenance="missing",
                source_field=source_field,
                calculation_mode="missing",
                missing_fields=[metric_name],
            )

        min_margin_status = None
        min_margin_missing: List[str] = []
        if scc_records is None:
            min_margin_missing = list(scc_issue_missing)
        elif len(scc_records) == 0:
            min_margin_status = "not_applicable"
            min_margin_missing = []
        elif min_margin_rate is None:
            min_margin_missing = [
                "short_circuit_current_kA",
                "breaker_current_kA",
            ]

        ratio_missing: List[str] = []
        if over_limit_ratio is None:
            if scc_records is None:
                ratio_missing = list(scc_issue_missing)
            else:
                ratio_missing = list(scc_denom_missing)

        metrics = {
            "pf_convergence": _derived_metric_entry(
                value=pf_value,
                display_value=pf_display,
                unit=_metric_rule_unit("pf_convergence"),
                formula=_metric_rule_formula("pf_convergence"),
                inputs={"is_convergent": is_convergent_raw},
                input_source=pf_rel,
                missing_fields=pf_missing,
            ),
            "n1_pass_rate": _derived_metric_entry(
                value=pass_rate,
                unit=_metric_rule_unit("n1_pass_rate"),
                formula=_metric_rule_formula("n1_pass_rate"),
                inputs={
                    "pass_count": pass_count,
                    "total_count": total,
                    "issue_count": issues,
                },
                input_source=n1_rel,
                missing_fields=n1_pass_missing if pass_rate is None else [],
            ),
            "weighted_n1_pass_rate": _derived_metric_entry(
                value=weighted_pass_rate,
                unit=_metric_rule_unit("weighted_n1_pass_rate"),
                formula=_metric_rule_formula("weighted_n1_pass_rate"),
                inputs={
                    "weighted_n1_pass_rate": n1_data.get("weighted_n1_pass_rate"),
                    "passed_load": n1_data.get("passed_load"),
                    "total_load": n1_data.get("total_load"),
                    "weighted_n1_mode": n1_data.get("weighted_n1_mode"),
                },
                input_source=n1_rel,
                missing_fields=(
                    []
                    if weighted_pass_rate is not None
                    else ["passed_load", "total_load", "weighted_n1_pass_rate"]
                ),
            ),
            "short_circuit_over_limit_count": _derived_metric_entry(
                value=scc_count,
                unit=_metric_rule_unit("short_circuit_over_limit_count"),
                formula="count(unique over-limit nodes)",
                inputs={
                    "unique_over_limit_node_count": scc_count,
                    "source_field": scc_issue_info.get("source_field"),
                    "record_count": (
                        len(scc_records) if isinstance(scc_records, list) else None
                    ),
                },
                input_source=scc_rel,
                missing_fields=(
                    [] if scc_count is not None else list(scc_issue_missing)
                ),
            ),
            "short_circuit_over_limit_ratio": _derived_metric_entry(
                value=over_limit_ratio,
                unit=_metric_rule_unit("short_circuit_over_limit_ratio"),
                formula=_metric_rule_formula("short_circuit_over_limit_ratio"),
                inputs={
                    "over_limit_count": scc_count,
                    "check_count": get_scc_effective_check_count(analysis),
                },
                input_source=scc_rel,
                missing_fields=ratio_missing if over_limit_ratio is None else [],
            ),
            "min_breaker_interrupt_margin_rate": _derived_metric_entry(
                value=min_margin_rate,
                unit=_metric_rule_unit("min_breaker_interrupt_margin_rate"),
                formula=_metric_rule_formula("min_breaker_interrupt_margin_rate"),
                inputs={
                    "record_count": (
                        len(scc_records) if isinstance(scc_records, list) else None
                    ),
                    "source_field": scc_issue_info.get("source_field"),
                },
                input_source=scc_rel,
                missing_fields=min_margin_missing,
                status=min_margin_status,
            ),
            "construction_cost": _economic_derived(
                "construction_cost",
                proposal.get("construction_cost_yuan"),
                proposal.get("construction_cost_provenance") or "missing",
                proposal.get("construction_cost_source_field"),
            ),
            "operation_cost": _economic_derived(
                "operation_cost",
                proposal.get("operation_cost_yuan"),
                proposal.get("operation_cost_provenance") or "missing",
                proposal.get("operation_cost_source_field"),
            ),
            "annual_cost": _economic_derived(
                "annual_cost",
                proposal.get("annual_cost_yuan"),
                proposal.get("annual_cost_provenance") or "missing",
                proposal.get("annual_cost_source_field"),
            ),
            "lifecycle_cost": _economic_derived(
                "lifecycle_cost",
                proposal.get("lifecycle_cost_yuan"),
                proposal.get("lifecycle_cost_provenance") or "missing",
                proposal.get("lifecycle_cost_source_field"),
            ),
            # 汇总辅助：N-1 计数（非独立比选核心，供表头展示）
            "n1_total_contingencies": _derived_metric_entry(
                value=total if isinstance(total, (int, float)) and not isinstance(total, bool) else None,
                unit="次",
                formula="total_contingencies_run",
                inputs={"total_contingencies_run": total},
                input_source=n1_rel,
                missing_fields=[] if total is not None else ["total_contingencies_run"],
            ),
            "n1_issue_contingencies": _derived_metric_entry(
                value=issues,
                unit="次",
                formula="len(contingencies_with_issues)",
                inputs={"issue_count": issues},
                input_source=n1_rel,
                missing_fields=(
                    [] if issues is not None else ["contingencies_with_issues"]
                ),
            ),
        }

        # 第二批指标：从 PF/N-1/方案 modifications / 可选暂态报告提取
        from src.nodes.second_batch_adapters import collect_second_batch_metrics

        proposals_raw = load_json_file(working_dir / "parsed_proposals.json")
        proposal_list = proposals_raw.get("proposals") or []
        proposal_raw = (
            proposal_list[index - 1]
            if 0 <= index - 1 < len(proposal_list)
            and isinstance(proposal_list[index - 1], dict)
            else {}
        )
        transient_path = analysis_dir / f"transient_report_{index}.json"
        transient_data = load_json_file(transient_path) if transient_path.exists() else {}
        transient_rel = (
            f"analysis_{index}/transient_report_{index}.json"
            if transient_path.exists()
            else pf_rel
        )
        second_batch = collect_second_batch_metrics(
            pf_data=pf_data,
            n1_data=n1_data,
            proposal_raw=proposal_raw,
            pf_source=pf_rel,
            n1_source=n1_rel,
            proposal_source=proposal_rel,
            transient_data=transient_data,
            transient_source=transient_rel,
        )
        for metric_name, adapter_result in second_batch.items():
            metrics[metric_name] = _entry_from_adapter(metric_name, adapter_result)

        schemes.append(
            {
                "proposal_index": index,
                "proposal_name": scheme_name,
                "metrics": metrics,
            }
        )

    payload = {"schemes": schemes}
    out_path = working_dir / "derived_metrics.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"derived_metrics.json 已写入: {out_path}")
    return payload


def load_derived_metrics(working_dir: Path) -> Dict[str, Any]:
    path = working_dir / "derived_metrics.json"
    if path.exists():
        return load_json_file(path)
    return build_derived_metrics(working_dir)


def _lifecycle_factor_for_note() -> str:
    from src.tools.grid_calculator import get_economic_defaults

    factor = get_economic_defaults()["lifecycle_factor"]
    text = f"{factor:.4f}".rstrip("0").rstrip(".")
    return text or str(factor)


def _normalize_length_unit_for_summary(unit: Any) -> str:
    """汇总表用单位归一：km / mile / unknown。"""
    if unit is None:
        return "unknown"
    text = str(unit).strip().lower()
    if not text or text == "unknown":
        return "unknown"
    if text == "km":
        return "km"
    if text in {"mile", "miles"}:
        return "mile"
    return "unknown"


def _format_length_summary_cell(value_text: str, unit: Any) -> str:
    normalized = _normalize_length_unit_for_summary(unit)
    if normalized == "km":
        return f"{value_text} km"
    if normalized == "mile":
        return f"{value_text} mile"
    return f"{value_text}（单位未知）"


def _collect_ok_length_units(schemes: List[Dict[str, Any]], metric_key: str) -> set:
    units: set = set()
    for scheme in schemes:
        entry = ((scheme.get("metrics") or {}).get(metric_key) or {})
        if entry.get("status") != "ok" or entry.get("value") is None:
            continue
        units.add(_normalize_length_unit_for_summary(entry.get("unit")))
    return units


def _length_unit_cross_scheme_warning(metric_key: str, units: set) -> Optional[str]:
    if not units:
        return None
    if units == {"km"} or units == {"mile"}:
        return None
    label = "新建线路长度" if metric_key == "new_line_length" else "改造线路长度"
    return (
        f"> 警告：{label}单位未统一或存在未知单位，"
        "当前数值仅展示原始数据，不参与方案间横向大小排序。"
    )


def convert_core_comparison_summary_to_md(working_dir: Path) -> str:
    """生成方案比选核心指标汇总表（安全硬约束 / 技术性能与工程 / 经济性）。

    只读取 derived_metrics.json，不在此重新计算。
    """
    derived = load_derived_metrics(working_dir)
    schemes = derived.get("schemes") or []
    if not schemes:
        return ""

    def _cell(metrics: Dict[str, Any], key: str, *, economic: bool = False) -> str:
        entry = metrics.get(key) or {}
        status = entry.get("status")
        if status == "not_applicable":
            return NOT_APPLICABLE_TEXT
        if status in ("missing_data", "invalid_data") or entry.get("value") is None:
            return str(entry.get("display_value") or MISSING_DATA_TEXT)
        if key == "pf_convergence" and "display_value" in entry:
            return str(entry.get("display_value"))
        if economic:
            return format_economic_display_yuan(entry.get("value"))
        text = format_summary_value(entry.get("value"))
        if key in ("new_line_length", "retrofit_line_length"):
            return _format_length_summary_cell(text, entry.get("unit"))
        return text

    safety_keys = [
        ("pf_convergence", "基态潮流收敛性"),
        ("n1_pass_rate", "N-1通过率(%)"),
        ("weighted_n1_pass_rate", "N-1负荷加权通过率(%)"),
        ("short_circuit_over_limit_count", "短路越限节点数"),
        ("short_circuit_over_limit_ratio", "短路越限比例(%)"),
        ("min_breaker_interrupt_margin_rate", "最小断路器开断裕度率(%)"),
        ("critical_section_margin_rate", "关键断面输送裕度率(%)"),
        ("post_contingency_max_equipment_loading_rate", "故障后最大设备负载率(%)"),
        ("post_contingency_voltage_over_limit_rate", "故障后电压越限率(%)"),
        ("transient_stability_pass_rate", "暂态稳定通过率(%)"),
        ("max_generator_relative_angle_difference", "最大机组相对功角差(度)"),
    ]
    tech_keys = [
        ("voltage_qualification_rate", "电压合格率(%)"),
        ("voltage_over_limit_severity", "电压越限严重度(pu²)"),
        ("node_period_voltage_over_limit_rate", "节点—时段电压越限率(%)"),
        ("max_line_loading_rate", "最大线路负载率(%)"),
        ("max_transformer_loading_rate", "最大主变负载率(%)"),
        ("active_power_loss_rate", "有功网损率(%)"),
        ("new_line_length", "新建线路长度"),
        ("retrofit_line_length", "改造线路长度"),
    ]
    econ_keys = [
        ("construction_cost", "建设投资(元)"),
        ("operation_cost", "年运行维护费(元/年)"),
        ("annual_cost", "年费用(元/年)"),
        ("lifecycle_cost", "全寿命周期成本LCC(元)"),
        ("annual_energy_loss", "年电量损耗(MWh/年)"),
        ("annual_network_loss_cost", "年度网损成本(元/年)"),
    ]

    def _table(title: str, keys: List[tuple], *, economic_set: Optional[set] = None) -> List[str]:
        economic_set = economic_set or set()
        lines = [f"### {title}\n"]
        header = ["方案"] + [label for _, label in keys]
        align = [":-----"] + [
            "---------------:" if k in economic_set or k.endswith("_rate") or "cost" in k or "length" in k or "loss" in k or "severity" in k or "difference" in k or "count" in k
            else "------------:"
            for k, _ in keys
        ]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(align) + " |")
        for scheme in schemes:
            metrics = scheme.get("metrics") or {}
            name = scheme.get("proposal_name") or f"方案{scheme.get('proposal_index')}"
            row = [name]
            for key, _label in keys:
                row.append(
                    _cell(
                        metrics,
                        key,
                        economic=key in {"construction_cost", "operation_cost", "annual_cost", "lifecycle_cost"},
                    )
                )
            lines.append("| " + " | ".join(row) + " |")
        return lines

    md_lines: List[str] = []
    md_lines.extend(_table("方案比选安全硬约束汇总表", safety_keys))
    md_lines.append("")
    md_lines.extend(_table("方案比选技术性能与工程实施性汇总表", tech_keys))
    for metric_key in ("new_line_length", "retrofit_line_length"):
        warning = _length_unit_cross_scheme_warning(
            metric_key, _collect_ok_length_units(schemes, metric_key)
        )
        if warning:
            md_lines.append("")
            md_lines.append(warning)
    md_lines.append("")
    md_lines.extend(
        _table(
            "方案比选经济性汇总表",
            econ_keys,
            economic_set={
                "construction_cost",
                "operation_cost",
                "annual_cost",
                "lifecycle_cost",
                "annual_network_loss_cost",
            },
        )
    )

    md_lines.append(
        "\n> 说明：缺数显示“当前输入不足，未评价”；不适用显示“不适用”。"
        "安全硬约束不通过的方案，不得仅因成本较低被描述为综合最优。"
        "经济指标内部单位与汇总表显示单位均为元（网损成本除外已标明）；"
        "若正文需要亿元展示，必须用 calculate 做 元/100000000 换算，禁止把亿元数值直接绑到元 claim；"
        "经济成本不得为负，负成本不参与比选。"
        f"LCC：provided 保留原值；estimated_simplified 为建设投资×{_lifecycle_factor_for_note()}（仅当未提供完整折现参数时）；"
        "full_calculated 须全部现金流与折现参数有效，discount_rate≥0；"
        "完整参数已提供但内容无效时返回 invalid_data，禁止回退简化估算。"
        "新建/改造线路长度单元格带实际单位（km / mile / 单位未知）；"
        "跨方案单位不统一或未知时禁止横向大小排序，且不得擅自将 mile 换算为 km。"
        "问题子集（如 overloaded_lines）不得冒充全网最大负载率或合格率。"
        "全部方案均不满足安全硬约束时，不得给出可直接实施的最终推荐，仅可给出整改后的经济优先候选方案。"
    )
    return "\n".join(md_lines)


def extract_derived_metric_claims(
    data: Dict[str, Any],
    file_path: str,
    claims_list: List[Claim],
    claim_counter: List[int],
) -> None:
    """从 derived_metrics.json 提取派生指标 claims。

    仅对 status=ok 且 value 非 null 的指标生成数值 claim；
    indicator 使用真实指标名，绝不用 “value”。
    """
    schemes = data.get("schemes") or []
    for scheme_idx, scheme in enumerate(schemes):
        if not isinstance(scheme, dict):
            continue
        proposal_index = scheme.get("proposal_index")
        proposal_name = scheme.get("proposal_name")
        metrics = scheme.get("metrics") or {}
        for metric_name, entry in metrics.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("status") in ("missing_data", "not_applicable", "invalid_data") or entry.get("value") is None:
                continue
            # 辅助计数字段也允许进入 claims，便于核对；仅有限数值可入库
            value = entry.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not math.isfinite(float(value)):
                logger.warning(
                    f"派生指标 {metric_name} 的 value={value!r} 非有限数，跳过 Claim"
                )
                continue
            claim_counter[0] += 1
            claim_id = f"{claim_counter[0]:06d}"
            path_to_value = f"schemes[{scheme_idx}].metrics.{metric_name}.value"
            claims_list.append(
                Claim(
                    claim_id=claim_id,
                    indicator=str(metric_name),
                    value=value,
                    unit=entry.get("unit") or None,
                    metadata={
                        "source_path": file_path,
                        "path_to_value": path_to_value,
                        "original_type": "derived",
                        "original_field_name": metric_name,
                        "proposal_index": proposal_index,
                        "proposal_name": proposal_name,
                        "metric_name": metric_name,
                        "formula": entry.get("formula"),
                        "inputs": entry.get("inputs"),
                        "input_source": entry.get("input_source"),
                        "status": entry.get("status"),
                        "provenance": entry.get("provenance"),
                        "source_field": entry.get("source_field"),
                        "calculation_mode": entry.get("calculation_mode"),
                        "coverage": entry.get("coverage"),
                    },
                )
            )


def load_json_file(path: Path) -> Dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def first_text_value(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


MISSING_DATA_TEXT = "当前输入不足，未评价"
NOT_APPLICABLE_TEXT = "不适用"


def format_summary_value(value) -> str:
    """汇总表单元格格式化：None 显示“数据不足”，不显示虚构 0。"""
    if value is None:
        return MISSING_DATA_TEXT
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def format_pf_convergence(is_convergent: Any) -> str:
    """基态潮流收敛性显示为“是/否”；无法解析时显示数据不足。"""
    if is_convergent is None:
        return MISSING_DATA_TEXT
    try:
        from src.tools.grid_calculator import _parse_bool

        return "是" if _parse_bool(is_convergent, "is_convergent") else "否"
    except Exception:
        return MISSING_DATA_TEXT


def parse_yuan_number(value: Any) -> Optional[float]:
    """将经济字段解析为元。无单位时按元；显式万元/亿元则换算。布尔值不视为数字。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            logger.warning(f"经济数值非有限数，视为缺失: {value!r}")
            return None
        return number
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    if not math.isfinite(number):
        logger.warning(f"经济数值非有限数，视为缺失: {value!r}")
        return None
    if "亿元" in text:
        return number * 100000000
    if "万元" in text:
        return number * 10000
    return number


def format_economic_display_yi(value_yuan: Any) -> str:
    """内部元 → 亿元（仅兼容旧调用；汇总表默认改用元）。"""
    if value_yuan is None:
        return MISSING_DATA_TEXT
    try:
        yuan = float(value_yuan)
    except (TypeError, ValueError):
        return MISSING_DATA_TEXT
    yi = yuan / 100000000
    text = f"{yi:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def format_economic_display_yuan(value_yuan: Any) -> str:
    """统一经济显示格式化：汇总表与 claim 一致，直接显示元。"""
    if value_yuan is None:
        return MISSING_DATA_TEXT
    try:
        yuan = float(value_yuan)
    except (TypeError, ValueError):
        return MISSING_DATA_TEXT
    if not math.isfinite(yuan):
        return MISSING_DATA_TEXT
    if abs(yuan - round(yuan)) < 1e-6:
        return str(int(round(yuan)))
    text = f"{yuan:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def load_proposal_metadata(path: Path) -> Dict[int, Dict[str, Any]]:
    """读取方案经济字段并规范为独立的年费用 / LCC。

    - annual_cost 只读 annual_cost / “年费用”，不从 lifecycle_cost 回退；
    - lifecycle_cost 只读 lifecycle_cost / “全寿命周期成本”，不从 annual_cost 回退；
    - 已提供的真实值一律保留；重算只用于补缺；
    - 每个字段记录 provenance：provided / calculated / migrated / extracted_from_description / missing。
    """
    from src.tools.grid_calculator import calculate_grid_metric, get_economic_defaults

    data = load_json_file(path)
    metadata: Dict[int, Dict[str, Any]] = {}
    defaults = get_economic_defaults()

    for index, proposal in enumerate(data.get("proposals", []) or [], start=1):
        description = str(proposal.get("description") or "")
        economic_prov = proposal.get("_economic_provenance") or {}
        if not isinstance(economic_prov, dict):
            economic_prov = {}

        construction_field = first_text_value(
            proposal.get("construction_cost"),
            proposal.get("construction_cost_estimate"),
        )
        construction_desc = (
            ""
            if construction_field
            else extract_cost_field(
                description,
                ["建设投资成本", "建设投资", "建设成本", "投资成本", "建造成本估算"],
            )
        )
        construction_text = construction_field or construction_desc
        if construction_field:
            construction_provenance = "provided"
            construction_source_field = (
                "construction_cost"
                if proposal.get("construction_cost") not in (None, "")
                else "construction_cost_estimate"
            )
        elif construction_desc:
            construction_provenance = "extracted_from_description"
            construction_source_field = "description"
        else:
            construction_provenance = "missing"
            construction_source_field = None

        operation_field = first_text_value(
            proposal.get("operation_cost"),
            proposal.get("maintenance_cost_estimate"),
        )
        operation_desc = (
            ""
            if operation_field
            else extract_cost_field(
                description,
                ["年运行维护费", "运维成本", "运行维护成本", "维护成本", "维护成本估算"],
            )
        )
        operation_text = operation_field or operation_desc
        if operation_field:
            operation_provenance = "provided"
            operation_source_field = (
                "operation_cost"
                if proposal.get("operation_cost") not in (None, "")
                else "maintenance_cost_estimate"
            )
        elif operation_desc:
            operation_provenance = "extracted_from_description"
            operation_source_field = "description"
        else:
            operation_provenance = "missing"
            operation_source_field = None

        annual_field = first_text_value(proposal.get("annual_cost"))
        annual_desc = (
            "" if annual_field else extract_cost_field(description, ["年费用"])
        )
        stored_annual_text = annual_field or annual_desc

        lifecycle_field = first_text_value(proposal.get("lifecycle_cost"))
        lifecycle_desc = (
            ""
            if lifecycle_field
            else extract_cost_field(
                description, ["全寿命周期成本LCC", "全寿命周期成本", "全生命周期成本"]
            )
        )
        stored_lifecycle_text = lifecycle_field or lifecycle_desc

        construction_yuan = parse_yuan_number(construction_text)
        operation_yuan = parse_yuan_number(operation_text)
        annual_yuan = parse_yuan_number(stored_annual_text)
        lifecycle_yuan = parse_yuan_number(stored_lifecycle_text)

        construction_invalid_fields: List[str] = []
        operation_invalid_fields: List[str] = []
        annual_invalid_fields: List[str] = []
        lifecycle_invalid_fields: List[str] = []
        construction_validation_error = None
        operation_validation_error = None
        annual_validation_error = None
        lifecycle_validation_error = None

        def _invalidate_negative(
            value: Optional[float], field_name: str
        ) -> Tuple[Optional[float], bool, Optional[str]]:
            if value is not None and value < 0:
                return (
                    None,
                    True,
                    f"{field_name} must be >= 0, got {value}",
                )
            return value, False, None

        construction_yuan, construction_neg, construction_validation_error = (
            _invalidate_negative(construction_yuan, "construction_cost")
        )
        operation_yuan, operation_neg, operation_validation_error = _invalidate_negative(
            operation_yuan, "operation_cost"
        )
        annual_yuan, annual_neg, annual_validation_error = _invalidate_negative(
            annual_yuan, "annual_cost"
        )
        lifecycle_yuan, lifecycle_neg, lifecycle_validation_error = _invalidate_negative(
            lifecycle_yuan, "lifecycle_cost"
        )

        annual_provenance = economic_prov.get("annual_cost")
        annual_source_field = economic_prov.get("annual_cost_source_field")
        if annual_provenance not in (
            "provided",
            "calculated",
            "migrated",
            "extracted_from_description",
            "missing",
            "invalid",
        ):
            if annual_field and not annual_neg:
                annual_provenance = "provided"
                annual_source_field = "annual_cost"
            elif annual_desc and not annual_neg:
                annual_provenance = "extracted_from_description"
                annual_source_field = "description"
            elif construction_yuan is not None and operation_yuan is not None:
                annual_provenance = None  # will calculate
            else:
                annual_provenance = "missing"
                annual_source_field = None
        if annual_neg:
            annual_provenance = "invalid"
            annual_invalid_fields = ["annual_cost"]
            annual_source_field = annual_source_field or "annual_cost"

        lifecycle_provenance = economic_prov.get("lifecycle_cost")
        lifecycle_source_field = economic_prov.get("lifecycle_cost_source_field")
        if lifecycle_provenance not in (
            "provided",
            "calculated",
            "migrated",
            "extracted_from_description",
            "missing",
            "invalid",
        ):
            if lifecycle_field and not lifecycle_neg:
                lifecycle_provenance = "provided"
                lifecycle_source_field = "lifecycle_cost"
            elif lifecycle_desc and not lifecycle_neg:
                lifecycle_provenance = "extracted_from_description"
                lifecycle_source_field = "description"
            elif construction_yuan is not None:
                lifecycle_provenance = None
            else:
                lifecycle_provenance = "missing"
                lifecycle_source_field = None
        if lifecycle_neg:
            lifecycle_provenance = "invalid"
            lifecycle_invalid_fields = ["lifecycle_cost"]
            lifecycle_source_field = lifecycle_source_field or "lifecycle_cost"

        if construction_neg:
            construction_provenance = "invalid"
            construction_invalid_fields = ["construction_cost"]
        if operation_neg:
            operation_provenance = "invalid"
            operation_invalid_fields = ["operation_cost"]

        # 仅补缺：不得用重算值覆盖已提供的真实字段
        if (
            annual_yuan is None
            and annual_provenance != "invalid"
            and construction_yuan is not None
            and operation_yuan is not None
        ):
            try:
                annual_yuan = float(
                    calculate_grid_metric(
                        "annual_cost",
                        {
                            "construction_cost": construction_yuan,
                            "operation_cost": operation_yuan,
                        },
                    )["value"]
                )
                annual_provenance = "calculated"
                annual_source_field = None
            except ValueError as exc:
                logger.warning(f"方案{index}年费用补算失败: {exc}")
                annual_provenance = "missing"
        elif annual_provenance is None and annual_yuan is not None:
            annual_provenance = "provided"
            annual_source_field = annual_source_field or "annual_cost"

        # 完整折现 LCC 参数：保留字段出现信息与原始值，供 Calculator 校验
        has_cash_flows_field = (
            "cash_flows" in proposal or "lifecycle_cash_flows" in proposal
        )
        if "cash_flows" in proposal:
            cash_flows_raw = proposal.get("cash_flows")
        elif "lifecycle_cash_flows" in proposal:
            cash_flows_raw = proposal.get("lifecycle_cash_flows")
        else:
            cash_flows_raw = None
        has_discount_field = (
            "discount_rate" in proposal or "interest_rate" in proposal
        )
        if "discount_rate" in proposal:
            discount_rate_raw = proposal.get("discount_rate")
        elif "interest_rate" in proposal:
            discount_rate_raw = proposal.get("interest_rate")
        else:
            discount_rate_raw = None
        has_horizon_field = "evaluation_years" in proposal or "years" in proposal
        if "evaluation_years" in proposal:
            evaluation_years_raw = proposal.get("evaluation_years")
        elif "years" in proposal:
            evaluation_years_raw = proposal.get("years")
        else:
            evaluation_years_raw = None
        # 任意完整折现专用字段出现即视为完整折现意图
        lifecycle_full_input_any = (
            has_cash_flows_field or has_discount_field or has_horizon_field
        )
        lifecycle_full_input_supplied = (
            has_cash_flows_field and has_discount_field and has_horizon_field
        )
        lifecycle_full_input_invalid = False
        lifecycle_calculation_mode = None
        if lifecycle_neg:
            lifecycle_calculation_mode = "invalid"

        def _infer_lcc_invalid_fields(message: str) -> List[str]:
            found: List[str] = []
            for name in (
                "discount_rate",
                "evaluation_years",
                "cash_flows",
                "construction_cost",
                "lifecycle_cost",
                "factor",
            ):
                if name in message:
                    found.append(name)
            return found or ["cash_flows"]

        if (
            lifecycle_yuan is None
            and lifecycle_provenance != "invalid"
            and lifecycle_full_input_any
        ):
            if construction_neg:
                lifecycle_full_input_invalid = True
                lifecycle_validation_error = (
                    construction_validation_error
                    or "construction_cost invalid for full LCC"
                )
                lifecycle_provenance = "invalid"
                lifecycle_calculation_mode = "invalid"
                lifecycle_invalid_fields = ["construction_cost", "cash_flows"]
            else:
                lcc_inputs: Dict[str, Any] = {}
                if has_cash_flows_field:
                    if "cash_flows" in proposal:
                        lcc_inputs["cash_flows"] = proposal.get("cash_flows")
                    else:
                        lcc_inputs["lifecycle_cash_flows"] = proposal.get(
                            "lifecycle_cash_flows"
                        )
                if has_discount_field:
                    if "discount_rate" in proposal:
                        lcc_inputs["discount_rate"] = proposal.get("discount_rate")
                    else:
                        lcc_inputs["interest_rate"] = proposal.get("interest_rate")
                if has_horizon_field:
                    if "evaluation_years" in proposal:
                        lcc_inputs["evaluation_years"] = proposal.get(
                            "evaluation_years"
                        )
                    else:
                        lcc_inputs["years"] = proposal.get("years")
                if construction_yuan is not None:
                    lcc_inputs["construction_cost"] = construction_yuan
                try:
                    full_result = calculate_grid_metric(
                        "lifecycle_cost",
                        lcc_inputs,
                    )
                    lifecycle_yuan = float(full_result["value"])
                    lifecycle_provenance = "calculated"
                    lifecycle_source_field = None
                    lifecycle_calculation_mode = str(
                        (full_result.get("inputs") or {}).get(
                            "_calculation_mode", "full_calculated"
                        )
                    )
                except ValueError as exc:
                    logger.warning(
                        f"方案{index}完整LCC参数无效，不回退简化估算: {exc}"
                    )
                    lifecycle_full_input_invalid = True
                    lifecycle_validation_error = str(exc)
                    lifecycle_provenance = "invalid"
                    lifecycle_calculation_mode = "invalid"
                    lifecycle_invalid_fields = _infer_lcc_invalid_fields(str(exc))
                    lifecycle_yuan = None

        if (
            lifecycle_yuan is None
            and construction_yuan is not None
            and not lifecycle_full_input_any
            and not lifecycle_full_input_invalid
            and lifecycle_provenance != "invalid"
        ):
            try:
                est_result = calculate_grid_metric(
                    "lifecycle_cost",
                    {"construction_cost": construction_yuan},
                )
                lifecycle_yuan = float(est_result["value"])
                lifecycle_provenance = "calculated"
                lifecycle_source_field = None
                lifecycle_calculation_mode = str(
                    (est_result.get("inputs") or {}).get(
                        "_calculation_mode", "estimated_simplified"
                    )
                )
            except ValueError as exc:
                logger.warning(f"方案{index}LCC补算失败: {exc}")
                lifecycle_provenance = "invalid"
                lifecycle_calculation_mode = "invalid"
                lifecycle_validation_error = str(exc)
                lifecycle_invalid_fields = _infer_lcc_invalid_fields(str(exc))
        elif lifecycle_provenance is None and lifecycle_yuan is not None:
            lifecycle_provenance = "provided"
            lifecycle_source_field = lifecycle_source_field or "lifecycle_cost"
            lifecycle_calculation_mode = "provided"
        elif lifecycle_provenance == "provided":
            lifecycle_calculation_mode = "provided"
        elif lifecycle_provenance == "migrated":
            lifecycle_calculation_mode = "migrated"
        elif lifecycle_provenance == "invalid":
            lifecycle_calculation_mode = "invalid"
        elif lifecycle_provenance == "calculated" and lifecycle_calculation_mode is None:
            lifecycle_calculation_mode = (
                "full_calculated"
                if lifecycle_full_input_supplied and not lifecycle_full_input_invalid
                else "estimated_simplified"
            )

        if annual_yuan is None and annual_provenance not in ("migrated", "invalid"):
            annual_provenance = annual_provenance or "missing"
        if lifecycle_yuan is None and lifecycle_provenance != "invalid":
            lifecycle_provenance = lifecycle_provenance or "missing"
        if construction_yuan is None and construction_provenance != "invalid":
            construction_provenance = construction_provenance or "missing"
        if operation_yuan is None and operation_provenance != "invalid":
            operation_provenance = operation_provenance or "missing"

        metadata[index] = {
            "name": proposal.get("proposal_name") or f"方案{index}",
            "construction_cost": construction_text,
            "operation_cost": operation_text,
            "annual_cost": stored_annual_text,
            "lifecycle_cost": stored_lifecycle_text,
            "construction_cost_yuan": construction_yuan,
            "operation_cost_yuan": operation_yuan,
            "annual_cost_yuan": annual_yuan,
            "lifecycle_cost_yuan": lifecycle_yuan,
            "construction_cost_provenance": construction_provenance,
            "construction_cost_source_field": construction_source_field,
            "operation_cost_provenance": operation_provenance,
            "operation_cost_source_field": operation_source_field,
            "annual_cost_provenance": annual_provenance or "missing",
            "annual_cost_source_field": annual_source_field,
            "lifecycle_cost_provenance": lifecycle_provenance or "missing",
            "lifecycle_cost_source_field": lifecycle_source_field,
            "lifecycle_calculation_mode": lifecycle_calculation_mode,
            "lifecycle_cash_flows": cash_flows_raw,
            "discount_rate": discount_rate_raw,
            "evaluation_years": evaluation_years_raw,
            "lifecycle_validation_error": lifecycle_validation_error,
            "lifecycle_invalid_fields": lifecycle_invalid_fields,
            "lifecycle_full_input_any": lifecycle_full_input_any,
            "lifecycle_full_input_supplied": lifecycle_full_input_supplied,
            "lifecycle_full_input_invalid": lifecycle_full_input_invalid,
            "construction_cost_validation_error": construction_validation_error,
            "construction_cost_invalid_fields": construction_invalid_fields,
            "operation_cost_validation_error": operation_validation_error,
            "operation_cost_invalid_fields": operation_invalid_fields,
            "annual_cost_validation_error": annual_validation_error,
            "annual_cost_invalid_fields": annual_invalid_fields,
            "interest_rate": defaults["interest_rate"],
            "years": defaults["years"],
            "lifecycle_factor": defaults["lifecycle_factor"],
        }
    return metadata


def extract_cost_field(text: str, labels: List[str]) -> str:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[：:]\s*([^，,；;\n]+)", text)
        if match:
            return match.group(1).strip()
    return ""


def summarize_n1(data: Dict) -> tuple:
    """汇总 N-1 指标。

    当前通过率口径：
    pass_count = total_contingencies_run - len(contingencies_with_issues)
    n1_pass_rate = pass_count / total_contingencies_run * 100%

    关键区分字段缺失与明确空列表：
    - contingencies_with_issues 缺失/null/非列表 → issues=None，不得按 0 问题故障计算 100%；
    - contingencies_with_issues=[] → issues=0，在 total>0 时可得到 100%。
    """
    from src.tools.grid_calculator import calculate_grid_metric

    if not data:
        return None, None, None, "", None, None

    total = data.get("total_contingencies_run")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        total_for_calc = None
    else:
        total_for_calc = float(total)
        if not math.isfinite(total_for_calc):
            logger.warning(f"N-1: total_contingencies_run={total!r} 非有限数")
            total_for_calc = None

    if "contingencies_with_issues" not in data:
        logger.warning("N-1: contingencies_with_issues 字段不存在")
        issues_list = None
        issues = None
    else:
        raw_issues = data["contingencies_with_issues"]
        if raw_issues is None:
            logger.warning("N-1: contingencies_with_issues 为 null")
            issues_list = None
            issues = None
        elif not isinstance(raw_issues, list):
            logger.warning(
                f"N-1: contingencies_with_issues 类型错误，期望 list，实际 {type(raw_issues).__name__}"
            )
            issues_list = None
            issues = None
        else:
            issues_list = raw_issues
            issues = len(raw_issues)

    pass_rate = None
    can_compute = (
        total_for_calc is not None
        and total_for_calc > 0
        and issues is not None
        and issues_list is not None
    )
    if can_compute:
        if issues > total_for_calc:
            logger.warning(
                f"N-1: 问题故障数 {issues} 大于总数 {total_for_calc}，视为数据异常，不计算通过率"
            )
            pass_rate = None
        else:
            try:
                pass_rate = float(
                    calculate_grid_metric(
                        "n1_pass_rate",
                        {"pass_count": total_for_calc - issues, "total_count": total_for_calc},
                    )["value"]
                )
                pass_rate = round(pass_rate, 2)
            except ValueError as exc:
                logger.warning(f"N-1通过率计算失败: {exc}")
                pass_rate = None

    max_overload = (
        max_numeric_value_from_n1_issues(issues_list) if isinstance(issues_list, list) else None
    )
    weighted_pass_rate = summarize_weighted_n1_pass_rate(data)
    return total, issues, pass_rate, n1_pass_rate_band(pass_rate), max_overload, weighted_pass_rate


def parse_weighted_n1_direct_percent(value: Any) -> Optional[float]:
    """校验直接给出的加权通过率百分数。

    仅接受 [0, 100] 百分数口径。对 (0, 1) 开区间内的小数不自动×100，返回 None。
    NaN / ±Infinity 视为无效。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        logger.warning(
            f"weighted_n1_pass_rate: 值 {value!r} 非有限数（NaN/Infinity），视为数据不足"
        )
        return None
    if 0.0 < number < 1.0:
        logger.warning(
            "weighted_n1_pass_rate: 值 "
            f"{number!r} 落在 (0,1)，无法确认是百分数还是小数比例；不自动换算，视为数据不足"
        )
        return None
    if number < 0.0 or number > 100.0:
        logger.warning(
            f"weighted_n1_pass_rate: 值 {number!r} 超出 [0,100] 百分数范围，视为数据不足"
        )
        return None
    return number


def summarize_weighted_n1_pass_rate(data: Dict) -> Optional[float]:
    """计算 N-1 负荷加权通过率；口径不完整时返回 None。

    优先级（不根据模糊字段名猜测）：
    1) 顶层 weighted_n1_pass_rate（百分数 0~100）
    2) 顶层 passed_load / total_load
    3) 仅当显式声明 weighted_n1_mode == \"lost_load\"，且问题故障均有 lost_load_mw、
       同时提供 total_load 时：passed_load = total_load - sum(lost_load_mw)
       （假设 total_load 与 lost_load_mw 为同一统计口径的全部故障对应总负荷）
    以下字段暂不自动参与计算（上游语义未确认）：
    load_mw / associated_load_mw / transferred_load_mw / passed_load_mw
    """
    from src.tools.grid_calculator import calculate_grid_metric

    if not data:
        return None

    direct = parse_weighted_n1_direct_percent(data.get("weighted_n1_pass_rate"))
    if direct is not None:
        return round(direct, 2)

    if data.get("passed_load") is not None and data.get("total_load") is not None:
        try:
            return round(
                float(
                    calculate_grid_metric(
                        "weighted_n1_pass_rate",
                        {
                            "passed_load": data.get("passed_load"),
                            "total_load": data.get("total_load"),
                        },
                    )["value"]
                ),
                2,
            )
        except ValueError as exc:
            logger.warning(f"N-1负荷加权通过率(passed_load/total_load)计算失败: {exc}")
            return None

    # 禁止把 passed_load_mw 等模糊字段从 total_load 中乱减
    if data.get("weighted_n1_mode") == "lost_load":
        issues_list = data.get("contingencies_with_issues") or []
        total_load = data.get("total_load")
        if not isinstance(issues_list, list) or total_load is None:
            return None
        lost_loads = []
        for item in issues_list:
            if not isinstance(item, dict) or item.get("lost_load_mw") is None:
                logger.warning(
                    "weighted_n1_pass_rate(lost_load模式): 存在故障缺少 lost_load_mw，无法计算"
                )
                return None
            try:
                lost_loads.append(float(item["lost_load_mw"]))
            except (TypeError, ValueError):
                return None
        try:
            passed_load = float(total_load) - sum(lost_loads)
            return round(
                float(
                    calculate_grid_metric(
                        "weighted_n1_pass_rate",
                        {"passed_load": passed_load, "total_load": total_load},
                    )["value"]
                ),
                2,
            )
        except ValueError as exc:
            logger.warning(f"N-1负荷加权通过率(lost_load模式)计算失败: {exc}")
            return None

    return None


def max_numeric_value_from_n1_issues(issues_list: List[Dict]) -> Optional[float]:
    values = []
    for item in issues_list:
        analysis = ((item.get("result") or {}).get("analysis") or {})
        for line in analysis.get("overloaded_lines") or []:
            value = line.get("电流比例(%)") or line.get("视在功率比例(%)")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                number = float(value)
                if math.isfinite(number):
                    values.append(number)
    return max(values) if values else None


def n1_pass_rate_band(pass_rate: Optional[float]) -> str:
    if pass_rate is None:
        return ""
    if pass_rate == 100:
        return "100%"
    if pass_rate > 95:
        return ">95%且<100%"
    if pass_rate >= 90:
        return "90%-95%"
    return "<90%"


def extract_scc_node_key(record: Any, index: int) -> str:
    """提取短路越限记录的节点唯一标识。

    优先 bus_name；空名称不合并。依次尝试 node_id / bus_id / node_name / 节点。
    皆无时用记录索引，避免无标识记录被错误合并成 1 个节点。
    """
    if not isinstance(record, dict):
        return f"__record_index_{index}"
    for key in ("bus_name", "node_id", "bus_id", "node_name", "节点"):
        raw = record.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return f"{key}:{text}"
    return f"__record_index_{index}"


def count_unique_scc_over_limit_nodes(issues: List[Any]) -> int:
    """按节点标识统计唯一短路越限节点数。"""
    if not isinstance(issues, list):
        return 0
    keys = {extract_scc_node_key(item, idx) for idx, item in enumerate(issues)}
    return len(keys)


def get_scc_effective_check_count(analysis: Dict[str, Any]) -> Optional[float]:
    """读取短路有效校核节点总数。

    优先级：effective_check_count > check_count > total_buses。
    必须为正有限数；布尔值、NaN、Infinity 不视为有效分母。
    """
    if not isinstance(analysis, dict):
        return None
    for key in ("effective_check_count", "check_count", "total_buses"):
        raw = analysis.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            logger.warning(f"短路校核分母字段 {key}={raw!r} 无法解析为数字")
            continue
        if not math.isfinite(value):
            logger.warning(f"短路校核分母字段 {key}={raw!r} 非有限数，忽略")
            continue
        if value > 0:
            return value
        logger.warning(f"短路校核分母字段 {key}={value} 非正数，忽略")
    return None


def get_scc_issue_records(analysis: Any) -> Dict[str, Any]:
    """读取 SCC 问题节点记录，区分字段缺失与明确空列表。

    优先级：
    1) exceeding_buses 键存在且为 list（含 []）→ 采用，空列表不回退；
    2) 否则 contingencies_with_issues 键存在且为 list → 采用；
    3) 两者缺失 / null / 非列表 → records=None, status=missing_data。
    """
    if not isinstance(analysis, dict):
        return {"records": None, "source_field": None, "status": "missing_data"}

    if "exceeding_buses" in analysis:
        raw = analysis["exceeding_buses"]
        if isinstance(raw, list):
            return {
                "records": raw,
                "source_field": "exceeding_buses",
                "status": "ok",
            }
        logger.warning(
            f"SCC: exceeding_buses 存在但类型无效（{type(raw).__name__}），视为数据不足"
        )
        return {
            "records": None,
            "source_field": "exceeding_buses",
            "status": "missing_data",
        }

    if "contingencies_with_issues" in analysis:
        raw = analysis["contingencies_with_issues"]
        if isinstance(raw, list):
            return {
                "records": raw,
                "source_field": "contingencies_with_issues",
                "status": "ok",
            }
        logger.warning(
            f"SCC: contingencies_with_issues 存在但类型无效（{type(raw).__name__}），视为数据不足"
        )
        return {
            "records": None,
            "source_field": "contingencies_with_issues",
            "status": "missing_data",
        }

    logger.warning(
        "SCC: exceeding_buses 与 contingencies_with_issues 均不存在，无法统计越限节点"
    )
    return {"records": None, "source_field": None, "status": "missing_data"}


def summarize_scc(data: Dict, scheme_label: str = "") -> tuple:
    """汇总短路指标。

    返回：
    - 短路越限节点数（按节点标识去重；字段缺失时为 None，明确空列表时为 0）
    - 短路越限比例(%)：unique_over_limit_node_count / effective_check_count
    - 最小断路器开断裕度率(%)：对有效配对记录取最小值；空列表为 None（not_applicable）
    - 最大短路电流 / 最大断路器电流（辅助）
    """
    from src.tools.grid_calculator import calculate_grid_metric

    if not data:
        return None, None, None, None, None

    analysis = data.get("analysis") or {}
    issue_info = get_scc_issue_records(analysis)
    issues = issue_info["records"]

    if issues is None:
        return None, None, None, None, None

    scc_count = count_unique_scc_over_limit_nodes(issues)
    check_count = get_scc_effective_check_count(analysis)

    over_limit_ratio = None
    if check_count is not None:
        if check_count < scc_count:
            logger.warning(
                f"{scheme_label or 'SCC'}短路越限比例: 分母 {check_count} 小于唯一越限节点数 "
                f"{scc_count}，视为数据异常，不计算比例"
            )
        else:
            try:
                over_limit_ratio = round(
                    float(
                        calculate_grid_metric(
                            "short_circuit_over_limit_ratio",
                            {"over_limit_count": scc_count, "check_count": check_count},
                        )["value"]
                    ),
                    2,
                )
            except ValueError as exc:
                logger.warning(f"{scheme_label or 'SCC'}短路越限比例计算失败: {exc}")
                over_limit_ratio = None

    min_margin_rate = None
    if issues:
        try:
            min_margin_rate = round(
                float(
                    calculate_grid_metric(
                        "min_breaker_interrupt_margin_rate",
                        {"records": issues},
                    )["value"]
                ),
                2,
            )
        except ValueError as exc:
            logger.warning(f"{scheme_label or 'SCC'}最小断路器开断裕度率: {exc}")
            min_margin_rate = None

    currents = [
        float(item.get("short_circuit_current_kA"))
        for item in issues
        if isinstance(item, dict)
        and isinstance(item.get("short_circuit_current_kA"), (int, float))
        and not isinstance(item.get("short_circuit_current_kA"), bool)
        and math.isfinite(float(item.get("short_circuit_current_kA")))
    ]
    breakers = [
        float(item.get("breaker_current_kA"))
        for item in issues
        if isinstance(item, dict)
        and isinstance(item.get("breaker_current_kA"), (int, float))
        and not isinstance(item.get("breaker_current_kA"), bool)
        and math.isfinite(float(item.get("breaker_current_kA")))
    ]
    return (
        scc_count,
        over_limit_ratio,
        min_margin_rate,
        (max(currents) if currents else None),
        (max(breakers) if breakers else None),
    )


def convert_proposals_to_md(data: Dict) -> str:
    """将 parsed_proposals.json 转换为 markdown 表格"""
    md_lines = ["### 接入方案表\n"]
    md_lines.append("| 方案 | 描述 |")
    md_lines.append("|:-----|:------|")
    for proposal in data.get("proposals", []) or []:
        name = proposal.get("proposal_name", "")
        description = str(proposal.get("description") or "").replace("\n", "<br>")
        md_lines.append(f"| {name} | {description} |")
    return "\n".join(md_lines)


def convert_nx_to_md(data: Dict, n=1) -> str:
    """将 N-1 分析结果转换为 markdown 表格"""
    md_lines = [f"### N-{n} 安全校验结果表\n"]
    md_lines.append(
        "| 预想故障 | 线路端点1 | 线路端点2 | 电流(A) | 额定电流(A) | 电流比例(%) | 视在功率(MVA) | 额定视在功率(MVA) | 视在功率比例(%) |"
    )
    md_lines.append(
        "|:---------|:---------|:---------|--------:|------------:|-----------:|-------------:|-----------------:|---------------:|"
    )

    for item in data.get("contingencies_with_issues", []) or []:
        contingency = item.get("contingency_branch_uid", "未知")
        result = item.get("result") or {}
        analysis = result.get("analysis") or {}
        overloaded_lines = analysis.get("overloaded_lines") or []

        if not overloaded_lines:
            continue

        for line in overloaded_lines:
            node1 = line.get("线路端点1", "")
            node2 = line.get("线路端点2", "")
            current = line.get("电流(A)", "")
            rated_current = line.get("额定电流(A)", "")
            current_pct = line.get("电流比例(%)", "")
            mva = line.get("视在功率(MVA)", "")
            rated_mva = line.get("额定视在功率(MVA)", "")
            mva_pct = line.get("视在功率比例(%)", "")

            md_lines.append(
                f"| {contingency} | {node1} | {node2} | {current} | {rated_current} | "
                f"{current_pct} | {mva} | {rated_mva} | {mva_pct} |"
            )
    md_lines.append("\n")
    return "\n".join(md_lines)


def convert_pf_to_md(data: Dict) -> str:
    """将潮流分析结果转换为 markdown 表格"""
    md_lines = ["#### 越限线路"]
    md_lines.append(
        "| 线路端点1 | 线路端点2 | 电流(A) | 额定电流(A) | 电流比例(%) | 视在功率(MVA) | 额定视在功率(MVA) | 视在功率比例(%) |"
    )
    md_lines.append(
        "|:---------|:---------|--------:|------------:|-----------:|-------------:|-----------------:|---------------:|"
    )

    analysis = data.get("analysis") or {}
    overloaded_lines = analysis.get("overloaded_lines") or []

    for line in overloaded_lines:
        node1 = line.get("线路端点1", "")
        node2 = line.get("线路端点2", "")
        current = line.get("电流(A)", "")
        rated_current = line.get("额定电流(A)", "")
        current_pct = line.get("电流比例(%)", "")
        mva = line.get("视在功率(MVA)", "")
        rated_mva = line.get("额定视在功率(MVA)", "")
        mva_pct = line.get("视在功率比例(%)", "")

        md_lines.append(
            f"| {node1} | {node2} | {current} | {rated_current} | "
            f"{current_pct} | {mva} | {rated_mva} | {mva_pct} |"
        )

    # 功率汇总表
    md_lines.append("\n#### 系统功率汇总")
    md_lines.append("| 损耗_MW | 总负荷_MW | 总发电_MW |")
    md_lines.append("|--------:|--------:|---------:|")

    power_summary = analysis.get("power_summary") or []
    for summary in power_summary:
        loss_mw = summary.get("损耗_MW", "")
        load_mw = summary.get("总负荷_MW", "")
        gen_mw = summary.get("总发电_MW", "")

        md_lines.append(f"| {loss_mw} | {load_mw} | {gen_mw} |")

    if not power_summary:
        balance_summary = analysis.get("balance_summary") or []
        for summary in balance_summary:
            region = summary.get("区域", "")
            generator = summary.get("平衡机", "")
            actual_power = summary.get("实际功率", "")
            md_lines.append(f"| 区域={region} | 平衡机={generator} | 实际功率={actual_power} |")
    md_lines.append("\n")
    return "\n".join(md_lines)


def convert_scc_to_md(data: Dict) -> str:
    """将短路电流分析结果转换为 markdown 表格"""
    md_lines = ["### 短路电流分析结果表\n"]
    md_lines.append(
        "| 节点 | 短路电流(kA) | 断路器电流(kA) | 电压(kV) | 故障类型 | 分区 |"
    )
    md_lines.append(
        "|:-----|------------:|--------------:|---------:|:--------|:-----|"
    )

    analysis = data.get("analysis", {})
    exceeding_buses = analysis.get("exceeding_buses", []) or analysis.get("contingencies_with_issues", [])

    for bus in exceeding_buses:
        bus_name = bus.get("bus_name", "")
        short_circuit_current = bus.get("short_circuit_current_kA", "")
        breaker_current = bus.get("breaker_current_kA", "")
        voltage = bus.get("voltage_kV", "")
        fault_type = bus.get("fault_type", "")
        partition = bus.get("partition", "")

        md_lines.append(
            f"| {bus_name} | {short_circuit_current} | {breaker_current} | "
            f"{voltage} | {fault_type} | {partition} |"
        )

    return "\n".join(md_lines)


def contains_numbers(text: str) -> bool:
    """检查字符串是否包含数值"""
    return bool(re.search(r"\d+\.?\d*", text))


DESCRIPTION_NUMERIC_FIELDS = (
    ("construction_cost", ("建设投资成本", "建设投资", "建设成本", "投资成本", "建造成本估算")),
    ("operation_cost", ("年运行维护费", "运维成本", "运行维护成本", "维护成本", "维护成本估算")),
    ("annual_cost", ("年费用",)),
    ("lifecycle_cost", ("全寿命周期成本LCC", "全寿命周期成本", "全生命周期成本")),
)


def extract_labeled_numbers_from_description(
    text: str,
    file_path: str,
    path_to_value: str,
    claims_list: List[Claim],
    claim_counter: List[int],
) -> None:
    for indicator, labels in DESCRIPTION_NUMERIC_FIELDS:
        value_text = extract_cost_field(text, list(labels))
        if not value_text:
            continue
        match = re.search(r"-?\d[\d,]*(?:\.\d+)?", value_text)
        if not match:
            continue
        raw_value = match.group(0).replace(",", "")
        value = float(raw_value) if "." in raw_value else int(raw_value)
        claim_counter[0] += 1
        claims_list.append(
            create_claim_from_string(
                claim_counter[0],
                value,
                text,
                indicator,
                file_path,
                path_to_value,
            )
        )


def extract_numbers_from_string(
    text: str,
    field_name: str,
    file_path: str,
    path_to_value: str,
    claims_list: List[Claim],
    claim_counter: List[int],
) -> None:
    """
    从字符串中提取所有数值并构造 claims

    示例输入: "建设成本：新建线路27.8km×200万元/km=5560万元"
    生成: 3个独立的 claims
    """
    matches = re.finditer(r"(\d+\.?\d*)", text)

    for match in matches:
        value_str = match.group(1)
        value = float(value_str) if "." in value_str else int(value_str)

        claim_counter[0] += 1

        claim = create_claim_from_string(
            claim_counter[0], value, text, field_name, file_path, path_to_value
        )
        claims_list.append(claim)


def get_claim_key(claim: Claim) -> tuple:
    """
    生成 claim 的哈希键，用于去重

    Args:
        claim: Claim 对象

    Returns:
        可哈希的元组 (indicator, value, metadata_tuple)
    """
    # 将 metadata 转换为可哈希的形式
    metadata_tuple = (
        claim.metadata.get("source_path", ""),
        claim.metadata.get("path_to_value", ""),
        claim.metadata.get("original_type", ""),
    )
    return (claim.indicator, claim.value, metadata_tuple)


def deduplicate_claims(claims_list: List[Claim]) -> List[Claim]:
    """
    去除重复的 claims

    去重条件：value、indicator、metadata 完全相同

    Args:
        claims_list: claims 列表

    Returns:
        去重后的 claims 列表
    """
    seen_keys = set()
    unique_claims = []

    for claim in claims_list:
        claim_key = get_claim_key(claim)
        if claim_key not in seen_keys:
            seen_keys.add(claim_key)
            unique_claims.append(claim)
        else:
            logger.debug(
                f"发现重复 claim，已过滤: {claim.claim_id} ({claim.indicator}={claim.value})"
            )

    return unique_claims


def claims_to_documents(claims_list: List[Claim]) -> List[Document]:
    """将 claims 转换为 Document 对象用于向量化"""
    documents = []
    for claim in claims_list:
        context = claim.metadata.get("context", "")
        page_content = f"{claim.indicator}: {claim.value}"
        if context:
            page_content += f" - {context}"

        doc = Document(
            page_content=page_content,
            metadata={
                "claim_id": claim.claim_id,
                "indicator": claim.indicator,
                "value": str(claim.value),
                "source_path": claim.metadata.get("source_path"),
                "path_to_value": claim.metadata.get("path_to_value"),
            },
        )
        documents.append(doc)
    return documents


def create_pcn_vector_store(documents: List[Document]) -> FAISS:
    """创建 PCN claims 的 FAISS 向量存储"""
    embedding_model, _ = client_manager.get_embedding_model()

    embedding_dim = len(embedding_model.embed_query("hello"))
    index = faiss.IndexFlatL2(embedding_dim)
    vector_store = FAISS(
        embedding_function=embedding_model,
        index=index,
        docstore=InMemoryDocstore(),
        index_to_docstore_id={},
    )

    batch_size = 1
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        vector_store.add_documents(batch)
        logger.debug(
            f"已向量化 {min(i + batch_size, len(documents))}/{len(documents)} 个 claims"
        )

    return vector_store


def extract_unit_from_field_name(field_name: str) -> tuple[str, Optional[str]]:
    """
    从字段名中提取指标名和单位

    Args:
        field_name: 字段名，如 "损耗_MW", "电压_kV", "current_A"

    Returns:
        (指标名, 单位) 元组，如果没有单位则单位部分为 None
    """
    # 常见的单位模式
    unit_patterns = [
        r'_(MW|MVA|kV|kA|A|V|W|Ω|ohm|Hz|%|pu)$',  # 下划线分隔
        r'\((MW|MVA|kV|kA|A|V|W|Ω|ohm|Hz|%|pu)\)$',  # 括号包围
    ]

    for pattern in unit_patterns:
        match = re.search(pattern, field_name, re.IGNORECASE)
        if match:
            unit = match.group(1)
            # 移除单位部分得到指标名
            indicator = re.sub(pattern, '', field_name, flags=re.IGNORECASE)
            return indicator, unit

    return field_name, None


def create_claim_from_number(
    claim_num: int,
    value: float,
    field_name: str,
    file_path: str,
    path_to_value: str,
) -> Claim:
    """从数值型数据创建 claim"""
    claim_id = f"{claim_num:06d}"

    # 提取指标名和单位
    indicator, unit = extract_unit_from_field_name(field_name)

    return Claim(
        claim_id=claim_id,
        indicator=indicator,
        value=value,
        unit=unit,
        metadata={
            "source_path": file_path,
            "path_to_value": path_to_value,
            "original_type": "number",
            "original_field_name": field_name,
        },
    )


def create_claim_from_string(
    claim_num: int,
    value: float,
    original_text: str,
    field_name: str,
    file_path: str,
    path_to_value: str,
) -> Claim:
    """从字符串中的数值创建 claim"""
    claim_id = f"{claim_num:06d}"

    # 提取指标名和单位
    indicator, unit = extract_unit_from_field_name(field_name)

    return Claim(
        claim_id=claim_id,
        indicator=indicator,
        value=value,
        unit=unit,
        metadata={
            "source_path": file_path,
            "path_to_value": path_to_value,
            "original_type": "string",
            "context": original_text,
            "original_field_name": field_name,
        },
    )


def extract_claims_recursive(
    data: Any,
    file_path: str,
    path_to_value: str,
    claims_list: List[Claim],
    claim_counter: List[int],
) -> None:
    """
    递归遍历 JSON 数据并提取 claims

    Args:
        data: 当前处理的数据
        file_path: 文件相对路径
        path_to_value: 当前在 JSON 结构中的路径（点分隔字符串格式，如 "analysis.power_summary[0].损耗_MW"）
        claims_list: 累积的 claims 列表
        claim_counter: 全局 claim 计数器 [count]
    """
    if isinstance(data, dict):
        for key, value in data.items():
            # 构建新的路径：当前路径 + ".key" 或直接 "key"（如果是根路径）
            new_path = f"{path_to_value}.{key}" if path_to_value else key
            extract_claims_recursive(
                value, file_path, new_path, claims_list, claim_counter
            )

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            # 数组元素路径：使用 [index] 格式
            new_path = f"{path_to_value}[{idx}]"
            extract_claims_recursive(
                item, file_path, new_path, claims_list, claim_counter
            )

    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        claim_counter[0] += 1
        # 提取字段名（路径的最后一部分）
        field_name = path_to_value.split(".")[-1] if path_to_value else "unknown"
        # 移除可能的数组索引部分，获取实际的字段名
        if "[" in field_name:
            field_name = field_name.split("[")[0]

        claim = create_claim_from_number(
            claim_counter[0], data, field_name, file_path, path_to_value
        )
        claims_list.append(claim)

    elif isinstance(data, str):
        if contains_numbers(data):
            field_name = path_to_value.split(".")[-1] if path_to_value else "unknown"
            # 移除可能的数组索引部分
            if "[" in field_name:
                field_name = field_name.split("[")[0]

            if field_name == "description":
                extract_labeled_numbers_from_description(
                    data, file_path, path_to_value, claims_list, claim_counter
                )
            else:
                extract_numbers_from_string(
                    data, field_name, file_path, path_to_value, claims_list, claim_counter
                )
