import argparse
import json
import math
import os
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


DEFAULT_INPUT_ROOT = os.environ.get(
    "POWERGRID_RUNS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "powergrid_pipeline", "fulfillment_scc"),
)
DEFAULT_OUTPUT_DIR = os.path.join(DEFAULT_INPUT_ROOT, "topology_plots")
DEFAULT_TARGET_RUN = "run_4"
DEFAULT_TARGET_SCHEME_NUMBERS = (2, 9)

ACTION_LABELS = {
    "add_line": "新增线路",
    "add_bus": "新增母线",
    "disable_branch": "停运线路",
    "remove_line": "拆除线路",
    "split_bus": "母线拆分",
}

CHINESE_FONT_ENV_VARS = ("PLOT_SCHEME_FONT", "CHINESE_FONT_PATH", "MATPLOTLIB_CHINESE_FONT")
CHINESE_FONT_NAMES = (
    "SimHei",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Noto Sans CJK",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "PingFang SC",
    "Heiti SC",
    "Songti SC",
    "AR PL UMing CN",
    "AR PL UKai CN",
)
CHINESE_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf",
    "/usr/share/fonts/adobe-source-han-sans/SourceHanSansSC-Regular.otf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_chinese_font_path() -> Optional[str]:
    for env_var in CHINESE_FONT_ENV_VARS:
        font_path = os.environ.get(env_var)
        if font_path and os.path.exists(font_path):
            return font_path

    for font_path in CHINESE_FONT_PATHS:
        if os.path.exists(font_path):
            return font_path

    try:
        system_fonts = font_manager.findSystemFonts(fontext="ttf") + font_manager.findSystemFonts(fontext="otf")
    except Exception:
        system_fonts = []

    wanted_tokens = (
        "noto sans cjk",
        "sourcehan",
        "source han",
        "simhei",
        "simsun",
        "msyh",
        "microsoft yahei",
        "wenquanyi",
        "wqy",
        "pingfang",
        "heiti",
        "songti",
    )
    for font_path in system_fonts:
        lowered = font_path.lower()
        if any(token in lowered for token in wanted_tokens):
            return font_path

    return None


def configure_chinese_font() -> FontProperties:
    font_path = find_chinese_font_path()
    if font_path:
        font_manager.fontManager.addfont(font_path)
        font_prop = FontProperties(fname=font_path)
        plt.rcParams["font.sans-serif"] = [font_prop.get_name(), *CHINESE_FONT_NAMES, "DejaVu Sans"]
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["axes.unicode_minus"] = False
        return font_prop

    plt.rcParams["axes.unicode_minus"] = False
    raise RuntimeError(
        "没有找到可用中文字体，matplotlib 无法正确显示中文。请安装 Noto Sans CJK / Source Han Sans / 文泉驿，"
        "或把中文字体路径写到环境变量 PLOT_SCHEME_FONT 后再运行，例如：\n"
        "PLOT_SCHEME_FONT=/path/to/NotoSansCJK-Regular.ttc python plot_scheme_topology.py"
    )


def build_topology_from_proposal(
    proposal: Dict[str, Any],
    iteration: Optional[int] = None,
    scheme_number: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """从单个方案 proposal 中提取拓扑图节点和边。

    这段逻辑来自 bridge_server.py 的 build_topology_from_proposal：
    读取 proposal["modifications"] 里的 full_bus_data/full_branch_data，
    转成前端拓扑图使用的 nodes/edges。
    """
    proposal_name = proposal.get("proposal_name") or "未命名方案"
    modifications = proposal.get("modifications", []) or []
    node_map: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    def ensure_node(name: Any, node_type: str = "电网节点", voltage: Any = "未知") -> None:
        name = str(name or "").strip()
        if not name:
            return
        if name not in node_map:
            node_map[name] = {
                "id": name,
                "label": name,
                "type": node_type,
                "voltage": voltage if voltage not in (None, "") else "未知",
            }
        elif node_type == "新增母线":
            node_map[name]["type"] = node_type
            node_map[name]["voltage"] = voltage if voltage not in (None, "") else node_map[name].get("voltage", "未知")

    def normalize_branch_data(params: Dict[str, Any]) -> Dict[str, Any]:
        branch_data = params.get("full_branch_data", {}) or {}
        if branch_data:
            return branch_data

        name1 = params.get("name1") or params.get("NAME1")
        name2 = params.get("name2") or params.get("NAME2")
        if not name1 or not name2:
            return {}

        return {
            "NAME1": name1,
            "NAME2": name2,
            "BASE1": params.get("base1") or params.get("BASE1"),
            "BASE2": params.get("base2") or params.get("BASE2"),
            "CKT ID": params.get("ckt") or params.get("CKT ID"),
            "LINE NAME": params.get("line_name") or params.get("LINE NAME"),
        }

    def normalize_bus_data(params: Dict[str, Any]) -> Dict[str, Any]:
        bus_data = params.get("full_bus_data", {}) or {}
        if bus_data:
            return bus_data

        name = params.get("bus_name") or params.get("name") or params.get("NAME")
        if not name:
            return {}

        return {
            "NAME": name,
            "BASE": params.get("base") or params.get("BASE"),
        }

    for item in modifications:
        action = item.get("action", "")
        params = item.get("params", {}) or {}
        branch_data = normalize_branch_data(params)
        bus_data = normalize_bus_data(params)

        if bus_data:
            ensure_node(bus_data.get("NAME"), "新增母线", bus_data.get("BASE"))

        if branch_data:
            source = str(branch_data.get("NAME1", "")).strip()
            target = str(branch_data.get("NAME2", "")).strip()
            ensure_node(source, voltage=branch_data.get("BASE1"))
            ensure_node(target, voltage=branch_data.get("BASE2"))
            if source and target:
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "type": ACTION_LABELS.get(action, action or "线路"),
                        "action": action,
                        "ckt_id": branch_data.get("CKT ID"),
                        "line_name": branch_data.get("LINE NAME"),
                        "proposalName": proposal_name,
                        "iteration": iteration,
                        "schemeNumber": scheme_number,
                    }
                )

    return {"nodes": list(node_map.values()), "edges": edges}


def select_proposal_from_file(path: str, scheme_number: Optional[int] = None) -> Tuple[Dict[str, Any], Optional[int], Optional[int]]:
    """读取 selected_proposal*.json 或 parsed_proposals.json。"""
    payload = load_json(path)

    if "proposal" in payload:
        return payload["proposal"], payload.get("iteration"), payload.get("scheme_number")

    proposals = payload.get("proposals")
    if isinstance(proposals, list):
        if not proposals:
            raise ValueError(f"方案列表为空: {path}")
        if scheme_number is None:
            scheme_number = 1

        expected_name = f"方案{scheme_number}"
        for proposal in proposals:
            if str(proposal.get("proposal_name", "")).strip() == expected_name:
                return proposal, None, scheme_number

        index = scheme_number - 1
        if 0 <= index < len(proposals):
            proposal = proposals[index]
            proposal_name = str(proposal.get("proposal_name", "")).strip()
            if not proposal_name:
                return proposal, None, scheme_number
            raise ValueError(
                f"在 {path} 中没有找到 {expected_name}；第 {scheme_number} 个 JSON 块是 {proposal_name}，"
                "为避免画错方案已停止。"
            )
        raise IndexError(f"方案编号超出范围: {scheme_number}，文件中共有 {len(proposals)} 个方案")

    raise ValueError(f"无法识别方案文件格式: {path}")


def find_selected_proposals(path: str) -> List[str]:
    if os.path.isfile(path):
        return [path]

    candidates: List[str] = []
    for root, _, files in os.walk(path):
        for name in files:
            if name.endswith(".json") and (
                name.startswith("selected_proposal") or name == "parsed_proposals.json"
            ):
                candidates.append(os.path.join(root, name))
    return sorted(candidates)


def extract_run_number(path: str) -> int:
    name = os.path.basename(os.path.normpath(path))
    if not name.startswith("run_"):
        return 0
    try:
        return int(name.split("_", 1)[1])
    except ValueError:
        return 0


def find_run_dirs(root: str) -> List[str]:
    if not os.path.isdir(root):
        raise FileNotFoundError(f"固定输入目录不存在: {root}")

    run_dirs = [
        os.path.join(root, name)
        for name in os.listdir(root)
        if name.startswith("run_") and os.path.isdir(os.path.join(root, name))
    ]
    return sorted(run_dirs, key=extract_run_number)


def extract_scheme_number_from_name(name: str) -> Optional[int]:
    match = re.fullmatch(r"analysis_(\d+)", name)
    if not match:
        return None
    return int(match.group(1))


def find_analysis_scheme_numbers(test_output_dir: str) -> List[int]:
    if not os.path.isdir(test_output_dir):
        return []

    scheme_numbers = []
    for name in os.listdir(test_output_dir):
        full_path = os.path.join(test_output_dir, name)
        scheme_number = extract_scheme_number_from_name(name)
        if scheme_number is not None and os.path.isdir(full_path):
            scheme_numbers.append(scheme_number)
    return sorted(set(scheme_numbers))


def proposal_name_to_scheme_number(proposal: Dict[str, Any]) -> Optional[int]:
    name = str(proposal.get("proposal_name", "")).strip()
    match = re.fullmatch(r"方案(\d+)", name)
    if not match:
        return None
    return int(match.group(1))


def find_parsed_proposal_files(run_dir: str) -> List[str]:
    matches = []
    for root, _, files in os.walk(run_dir):
        if os.path.basename(root) != "generation":
            continue
        if "parsed_proposals.json" in files:
            matches.append(os.path.join(root, "parsed_proposals.json"))
    return sorted(matches)


def test_output_dir_from_parsed_proposals(path: str) -> str:
    return os.path.dirname(os.path.dirname(path))


def scheme_numbers_from_parsed_proposals(path: str) -> List[int]:
    payload = load_json(path)
    proposals = payload.get("proposals")
    if not isinstance(proposals, list):
        return []

    named_numbers = [
        scheme_number
        for scheme_number in (proposal_name_to_scheme_number(proposal) for proposal in proposals)
        if scheme_number is not None
    ]
    if named_numbers:
        return sorted(set(named_numbers))
    return list(range(1, len(proposals) + 1))


def merge_topologies(topologies: Iterable[Dict[str, List[Dict[str, Any]]]]) -> Dict[str, List[Dict[str, Any]]]:
    node_map: Dict[str, Dict[str, Any]] = {}
    edge_groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    circuit_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)

    def normalized_edge_key(edge: Dict[str, Any]) -> Tuple[str, str, str]:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        ordered = tuple(sorted([source, target]))
        return ordered[0], ordered[1], str(edge.get("type", ""))

    for topology in topologies:
        for node in topology.get("nodes", []):
            node_map[node["id"]] = node
        for edge in topology.get("edges", []):
            key = normalized_edge_key(edge)
            circuit_counts[key] += 1
            edge_groups.setdefault(key, edge.copy())

    edges = []
    for key, edge in edge_groups.items():
        edge["circuitCount"] = circuit_counts[key]
        edges.append(edge)

    return {"nodes": list(node_map.values()), "edges": edges}


def build_adjacency(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, set]:
    adjacency = {node["id"]: set() for node in nodes}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)
    return adjacency


def topology_layout(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
    """生成接近前端拓扑图的布局：高连接度/新增母线靠中，其余节点向外展开。"""
    count = max(len(nodes), 1)
    adjacency = build_adjacency(nodes, edges)
    center_id = max(nodes, key=lambda node: (len(adjacency.get(node["id"], [])), node.get("type") == "新增母线"))["id"]
    radius = max(4.0, count * 0.85)
    positions: Dict[str, Tuple[float, float]] = {center_id: (0.0, 0.0)}

    others = [node for node in nodes if node["id"] != center_id]
    for index, node in enumerate(others):
        angle = 2 * math.pi * index / max(len(others), 1)
        # 轻微扰动，避免多条斜线/标签完全重叠，同时保持确定性。
        jitter = ((sum(ord(ch) for ch in node["id"]) % 17) - 8) / 20
        positions[node["id"]] = (
            (radius + jitter) * math.cos(angle),
            (radius * 0.72 - jitter) * math.sin(angle),
        )

    area = max(1.0, (2 * radius) ** 2)
    spring_length = math.sqrt(area / count) * 0.9
    temperature = radius * 0.08

    fixed = {center_id} if len(adjacency.get(center_id, [])) >= 3 else set()
    for _ in range(180):
        disp = {node["id"]: [0.0, 0.0] for node in nodes}

        for i, node_a in enumerate(nodes):
            id_a = node_a["id"]
            x_a, y_a = positions[id_a]
            for node_b in nodes[i + 1:]:
                id_b = node_b["id"]
                x_b, y_b = positions[id_b]
                dx = x_a - x_b
                dy = y_a - y_b
                distance = math.hypot(dx, dy) or 0.01
                force = spring_length * spring_length / distance
                fx = dx / distance * force
                fy = dy / distance * force
                disp[id_a][0] += fx
                disp[id_a][1] += fy
                disp[id_b][0] -= fx
                disp[id_b][1] -= fy

        for edge in edges:
            source = edge.get("source")
            target = edge.get("target")
            if source not in positions or target not in positions:
                continue
            x_s, y_s = positions[source]
            x_t, y_t = positions[target]
            dx = x_s - x_t
            dy = y_s - y_t
            distance = math.hypot(dx, dy) or 0.01
            force = distance * distance / spring_length
            fx = dx / distance * force
            fy = dy / distance * force
            disp[source][0] -= fx
            disp[source][1] -= fy
            disp[target][0] += fx
            disp[target][1] += fy

        for node in nodes:
            node_id = node["id"]
            if node_id in fixed:
                continue
            dx, dy = disp[node_id]
            length = math.hypot(dx, dy) or 0.01
            step = min(length, temperature)
            x, y = positions[node_id]
            positions[node_id] = (x + dx / length * step, y + dy / length * step)
        temperature *= 0.985

    return positions


def edge_style(edge: Dict[str, Any]) -> Dict[str, Any]:
    action = edge.get("action")
    edge_type = edge.get("type", "")
    if action == "add_line" or edge_type == "新增线路":
        return {"color": "#1B7F3A", "linestyle": "-", "linewidth": 2.4}
    if action in {"disable_branch", "remove_line"} or edge_type in {"停运线路", "拆除线路"}:
        return {"color": "#B42318", "linestyle": "--", "linewidth": 2.2}
    return {"color": "#5B6472", "linestyle": "-", "linewidth": 1.8}


def draw_topology(topology: Dict[str, List[Dict[str, Any]]], output_path: str, title: str) -> None:
    nodes = topology.get("nodes", [])
    edges = topology.get("edges", [])
    if not nodes:
        raise ValueError("拓扑中没有节点，无法绘图。请确认方案里包含 full_branch_data 或 full_bus_data。")

    font_prop = configure_chinese_font()

    positions = topology_layout(nodes, edges)
    fig, ax = plt.subplots(figsize=(20, 14))
    fig.patch.set_facecolor("#f7faf8")
    ax.set_facecolor("#f7faf8")
    ax.set_title(title, fontproperties=font_prop, fontsize=14)
    ax.set_aspect("equal")
    ax.grid(True, color="#165a3e", alpha=0.08, linewidth=1)

    xs = [point[0] for point in positions.values()]
    ys = [point[1] for point in positions.values()]
    pad_x = max(2.0, (max(xs) - min(xs) or 1) * 0.12)
    pad_y = max(2.0, (max(ys) - min(ys) or 1) * 0.16)
    ax.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
    ax.set_ylim(min(ys) - pad_y, max(ys) + pad_y)
    ax.tick_params(labelbottom=False, labelleft=False, length=0)

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source not in positions or target not in positions:
            continue
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        is_removed = edge.get("type") in {"停运线路", "拆除线路"} or edge.get("action") in {"disable_branch", "remove_line"}
        line_color = "#d84a3a" if is_removed else "#168a61"
        ax.plot(
            [x1, x2],
            [y1, y2],
            color=line_color,
            linestyle="--" if is_removed else "-",
            linewidth=2.6 if not is_removed else 2.2,
            alpha=0.82,
            zorder=1,
        )

        circuit_count = int(edge.get("circuitCount") or 1)
        label = f"{'删除' if is_removed else '新增'} {circuit_count}回"
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        offset_x = 0.18 if y2 >= y1 else -0.75
        offset_y = -0.16 if x2 >= x1 else 0.28
        ax.text(
            mid_x + offset_x,
            mid_y + offset_y,
            label,
            fontsize=9,
            fontproperties=font_prop,
            color="#87261a" if is_removed else "#126547",
            ha="center",
            va="center",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 1.5},
            zorder=4,
        )

    for node in nodes:
        node_id = node["id"]
        x, y = positions[node_id]
        is_new_bus = node.get("type") == "新增母线"
        face_color = "#f5862f" if is_new_bus else "#137f98"
        ax.scatter([x], [y], s=180 if is_new_bus else 160, color=face_color, edgecolors="none", zorder=2)

        label = node.get("label") or node_id
        ax.text(
            x + 0.13,
            y + 0.13,
            label,
            fontsize=10,
            fontproperties=font_prop,
            color="#22453a",
            ha="center",
            va="center",
            zorder=3,
        )

    legend_items = [
        Line2D([0], [0], color="#168a61", linewidth=4, label="新增线路（实线）"),
        Line2D([0], [0], color="#d84a3a", linewidth=4, linestyle="--", label="删除/停运线路（虚线）"),
        Patch(facecolor="#0c8f62", label="变电站节点"),
        Patch(facecolor="#137f98", label="电网节点"),
        Patch(facecolor="#f5862f", label="新增母线"),
    ]
    ax.legend(handles=legend_items, loc="upper left", frameon=True, prop=font_prop)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def write_topology_json(topology: Dict[str, List[Dict[str, Any]]], output_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(topology, f, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="针对某个电网规划方案绘制方案拓扑图。")
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="selected_proposal*.json、parsed_proposals.json，或包含这些文件的目录。",
    )
    parser.add_argument(
        "--scheme-number",
        type=int,
        default=None,
        help="当输入是 parsed_proposals.json 时，指定要绘制第几个方案；默认 1。",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="单个方案模式下的拓扑图输出路径；默认 scheme_topology.png。",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"固定目录批量模式的输出目录，默认 {DEFAULT_OUTPUT_DIR}。",
    )
    parser.add_argument(
        "--topology-json",
        default=None,
        help="可选：同时导出 nodes/edges 拓扑JSON。",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="当输入是目录时，合并目录下所有 selected_proposal*.json 的拓扑。",
    )
    return parser.parse_args()


def build_topology_from_files(proposal_files: List[str], scheme_number: Optional[int] = None) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    topologies = []
    title_parts = []
    for path in proposal_files:
        proposal, iteration, selected_scheme_number = select_proposal_from_file(path, scheme_number)
        topologies.append(build_topology_from_proposal(proposal, iteration, selected_scheme_number))
        title_parts.append(
            f"iter={iteration if iteration is not None else '-'}, "
            f"scheme={selected_scheme_number if selected_scheme_number is not None else '-'}"
        )
    return merge_topologies(topologies), title_parts


def draw_all_runs(root: str = DEFAULT_INPUT_ROOT, output_dir: str = DEFAULT_OUTPUT_DIR) -> None:
    run_dirs = find_run_dirs(root)
    if not run_dirs:
        raise FileNotFoundError(f"没有在固定输入目录下找到 run_* 目录: {root}")
    run_dirs = [run_dir for run_dir in run_dirs if os.path.basename(run_dir) == DEFAULT_TARGET_RUN]
    if not run_dirs:
        raise FileNotFoundError(f"没有在固定输入目录下找到 {DEFAULT_TARGET_RUN}: {root}")

    os.makedirs(output_dir, exist_ok=True)
    generated = []
    skipped = []

    for run_dir in run_dirs:
        run_name = os.path.basename(run_dir)
        parsed_files = find_parsed_proposal_files(run_dir)
        if not parsed_files:
            skipped.append(f"{run_name}: 没有找到 generation/parsed_proposals.json")
            continue

        for parsed_file in parsed_files:
            test_output_dir = test_output_dir_from_parsed_proposals(parsed_file)
            test_output_name = os.path.basename(test_output_dir)
            scheme_numbers = list(DEFAULT_TARGET_SCHEME_NUMBERS)

            for scheme_number in scheme_numbers:
                try:
                    proposal, iteration, selected_scheme_number = select_proposal_from_file(parsed_file, scheme_number)
                    topology = build_topology_from_proposal(proposal, iteration, selected_scheme_number)
                except Exception as exc:
                    skipped.append(f"{run_name}/{test_output_name}/方案{scheme_number}: {exc}")
                    continue

                output_stem = f"{run_name}_{test_output_name}_scheme_{scheme_number}"
                output_png = os.path.join(output_dir, f"{output_stem}_topology.png")
                output_json = os.path.join(output_dir, f"{output_stem}_topology.json")
                title = f"{run_name} {test_output_name} 方案{scheme_number} 拓扑图"
                draw_topology(topology, output_png, title)
                write_topology_json(topology, output_json)
                generated.append(
                    (
                        f"{run_name}/{test_output_name}/方案{scheme_number}",
                        output_png,
                        output_json,
                        len(topology.get("nodes", [])),
                        len(topology.get("edges", [])),
                    )
                )

    if not generated:
        details = "\n".join(f"- {item}" for item in skipped)
        raise FileNotFoundError(f"没有生成任何拓扑图，请检查方案文件: {root}\n{details}")

    print(f"固定输入目录: {root}")
    print(f"输出目录: {output_dir}")
    for scheme_label, output_png, output_json, node_count, edge_count in generated:
        print(f"- {scheme_label}: {node_count} 个节点, {edge_count} 条边")
        print(f"  PNG: {output_png}")
        print(f"  JSON: {output_json}")
    if skipped:
        print("跳过项:")
        for item in skipped:
            print(f"- {item}")


def main() -> None:
    args = parse_args()
    if args.input is None:
        draw_all_runs(DEFAULT_INPUT_ROOT, args.output_dir)
        return

    proposal_files = find_selected_proposals(args.input)
    if not proposal_files:
        raise FileNotFoundError(f"没有找到方案文件: {args.input}")

    if os.path.isdir(args.input) and not args.merge:
        proposal_files = [proposal_files[-1]]

    topology, title_parts = build_topology_from_files(proposal_files, args.scheme_number)
    title = "电网拓扑图"
    output = args.output or "scheme_topology.png"
    draw_topology(topology, output, title)

    if args.topology_json:
        write_topology_json(topology, args.topology_json)

    print(f"已绘制拓扑图: {output}")
    print(f"节点数: {len(topology.get('nodes', []))}, 边数: {len(topology.get('edges', []))}")
    if args.topology_json:
        print(f"已导出拓扑JSON: {args.topology_json}")


if __name__ == "__main__":
    main()
