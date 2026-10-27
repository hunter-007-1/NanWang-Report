import sys
import os


def _bootstrap_local_runtime():
    """使用项目虚拟环境、UTF-8 模式和本机 MiKTeX 启动服务。"""
    script_path = os.path.abspath(__file__)
    workspace_root = os.path.abspath(os.path.join(os.path.dirname(script_path), ".."))
    venv_dir = os.path.join(workspace_root, ".venv")
    venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    venv_scripts = os.path.join(venv_dir, "Scripts")
    miktex_bin = os.environ.get("MIKTEX_BIN", "")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["VIRTUAL_ENV"] = venv_dir

    path_items = [venv_scripts]
    if miktex_bin and os.path.isdir(miktex_bin):
        path_items.append(miktex_bin)
    env["PATH"] = os.pathsep.join(path_items + [env.get("PATH", "")])

    using_project_venv = (
        os.path.normcase(os.path.abspath(sys.executable))
        == os.path.normcase(os.path.abspath(venv_python))
    )
    if os.path.isfile(venv_python) and (
        not using_project_venv or sys.flags.utf8_mode != 1
    ):
        os.execve(
            venv_python,
            [venv_python, "-X", "utf8", script_path, *sys.argv[1:]],
            env,
        )

    # 已经在正确解释器中时，也把 MiKTeX PATH 应用到当前进程及其子进程。
    os.environ.update(env)


_bootstrap_local_runtime()

import time
import subprocess
import re
import asyncio
import importlib.util
import threading
from datetime import datetime

# 检查指定文件夹下是否有 .dat、.swi、.scset 文件，齐全则自动调用 main_scc.py
def check_and_run_simulation(folder_path):
    dat = None
    swi = None
    scset = None
    for f in os.listdir(folder_path):
        if f.endswith('.dat'):
            dat = os.path.join(folder_path, f)
        elif f.endswith('.swi'):
            swi = os.path.join(folder_path, f)
        elif f.endswith('.scset'):
            scset = os.path.join(folder_path, f)
    if dat and swi and scset:
        # 检查是否已有仿真进程在运行（可选，简单防止重复）
        print(f"检测到 {folder_path} 下三文件齐全，启动仿真分析流程...")
        # 获取脚本所在目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_scc_path = os.path.join(script_dir, "powergrid_pipeline_v2", "functional_tests", "main_scc.py")
        subprocess.Popen([sys.executable, main_scc_path, dat], cwd=script_dir)
        return True
    return False

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
import glob, json
import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# 获取脚本所在目录，确保静态文件路径正确
script_dir = os.path.dirname(os.path.abspath(__file__))
static_folder_path = os.path.join(script_dir, "..", "frame_fore-end_design")
static_folder_path = os.path.abspath(static_folder_path)
print(f"DEBUG: 静态文件目录: {static_folder_path}")
print(f"DEBUG: 静态文件目录存在: {os.path.exists(static_folder_path)}")

# 检查 CSS 和 JS 文件
if os.path.exists(static_folder_path):
    css_files = glob.glob(os.path.join(static_folder_path, "*.css"))
    js_files = glob.glob(os.path.join(static_folder_path, "*.js"))
    print(f"DEBUG: 找到 {len(css_files)} 个 CSS 文件: {[os.path.basename(f) for f in css_files]}")
    print(f"DEBUG: 找到 {len(js_files)} 个 JS 文件: {[os.path.basename(f) for f in js_files]}")

app = Flask(__name__, static_folder=static_folder_path, static_url_path="")
app.config['MAX_CONTENT_LENGTH'] = 10000 * 1024 * 1024  # 允许最大 10000MB 的请求体
CORS(app)  # 允许所有跨域请求

# 确保所有 JSON 响应都使用 UTF-8 编码
@app.after_request
def after_request(response):
    # 只对 API 请求设置 JSON Content-Type，不影响静态文件
    if request.path.startswith('/api/'):
        response.headers.add('Content-Type', 'application/json; charset=utf-8')
    return response

class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        return super().default(obj)

app.json_encoder = JSONEncoder

TASKS = {}

# PRECOMPUTED_RESULT_ROOT = os.path.join(script_dir, "fulfillment_scc_11")
# RESULT_ROOT = PRECOMPUTED_RESULT_ROOT if os.path.isdir(PRECOMPUTED_RESULT_ROOT) else os.path.join(script_dir, "fulfillment_scc")
RESULT_ROOT = os.path.join(script_dir, "fulfillment_scc")
REPORT_TEST_INPUT_DIR = os.environ.get("REPORT_TEST_INPUT_DIR", "").strip()
REPORT_BACKGROUND_CONTEXT_FILE = os.environ.get("REPORT_BACKGROUND_CONTEXT_FILE", "").strip()
ANALYSIS_ROOT = None
REPORT_FILES = {
    "pf_report_1.json": "潮流仿真报告",
    "n1_report_1.json": "N-1 校核报告",
    "scc_report_1.json": "短路电流报告"
}
USE_PRECOMPUTED_RESULTS = False    #如果设置为 True，则创建任务时不启动 main_scc.py，而是直接加载 RESULT_ROOT 目录下的方案和报告数据，适合演示和测试使用预生成结果的场景。

CASE_CONFIGS = {
    "shuifu": {
        "context": "powergrid_pipeline_v2/data/context_shuifu.json",
        "initial_prompt": "powergrid_pipeline_v2/data/prompts/generate_solution_n1_initial.txt",
        "iteration_prompt": "powergrid_pipeline_v2/data/prompts/generate_solution_n1_iteration.txt",
        "n1_report": "fulfillment_shuifu/analysis_1/n1_report_1.json",
        "initial_scc_issues": "13",
        "success_n1_issues": "3",
        "fixed_analysis_report": "连接节点\"滇溪右50\"和节点\"滇牛寨51\"的线路存在过载问题。",
        "target_overload_node1": "滇溪右50",
        "target_overload_node2": "滇牛寨51",
        "related_nodes": "滇水富51,滇牛寨51,滇溪右50",
        "filter_500kv_only": True,
        "target_node_name": "滇水富51",
        "target_load_p": "0",
        "target_solution_instruction": "你需要先定位过载线路的位置，然后通过将滇水富51节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。",
        "iteration_solution_instruction": "你需要先定位过载线路的位置，然后通过将滇水富51节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。由经验得，问题节点的既定负荷很大，需要传输能力很强的线路，或设置多回线路来解决该线网问题。",
    },
    "yuezhou": {
        "context": "powergrid_pipeline_v2/data/context_yuezhou.json",
        "initial_prompt": "powergrid_pipeline_v2/data/prompts/generate_solution_n1_initial.txt",
        "iteration_prompt": "powergrid_pipeline_v2/data/prompts/generate_solution_n1_iteration.txt",
        "n1_report": "fulfillment_yuezhou/analysis_1/n1_report_1.json",
        "initial_scc_issues": "0",
        "success_n1_issues": "0",
        "filter_500kv_only": True,
        "target_node_name": "滇越州51",
        "target_load_p": "119",
        "target_solution_instruction": "你需要先定位过载线路的位置，然后通过将滇越州51节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。",
        "iteration_solution_instruction": "你需要先定位过载线路的位置，然后通过将滇越州51节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。由经验得，问题节点的既定负荷很大，需要传输能力很强的线路，或设置多回线路来解决该线网问题。",
    },
    "generic": {
        "context": "powergrid_pipeline_v2/data/context_generic_template.json",
        "initial_prompt": "powergrid_pipeline_v2/data/prompts/generate_solution_n1_initial.txt",
        "iteration_prompt": "powergrid_pipeline_v2/data/prompts/generate_solution_n1_iteration.txt",
        "n1_report": None,
        "initial_scc_issues": "0",
        "success_n1_issues": "0",
        "filter_500kv_only": False,
        "skip_scc_analysis": True,
        "target_node_name": "bus0",
        "target_load_p": "0",
        "target_solution_instruction": "你需要先定位过载线路的位置，然后通过将bus0节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。",
        "iteration_solution_instruction": "请仔细研究最新问题报告，优先解决仍然存在的 N-1 过载或短路电流问题。",
    },
}

DEFAULT_PROMPT_SECTIONS = {
    "shuifu": {
        "connectionMode": """    - 辐射式接线：新增1回线路，直接连接单一主电源节点与目标节点，不拆除原线路；
    - 环式接线：新增至少两条连线，将目标节点与周边至少两个不同节点相连形成物理多边形闭环，常态开环运行；
    - π接：断开原有的线路的一小部分，并将指定位置的节点接入到断开的线路中，需要在输出的JSON数据中标明需要删除的线路的信息；需要指明在距离什么端点多远距离的地方断开多长的线路，然后通过新建多长的线路将指定节点接入线网；
    - 网状接线：保留周边骨干线路，新增至少3条连线，将目标节点与多个枢纽节点直接相连；
    - 背靠背柔性直流互联：在两个交流分区之间，插入一个特殊的节点。该节点内部不包含任何交流传输线，而是通过背靠背的整流器和逆变器相连；
    - 直流联网接线：新增一条点对点的直流传输通道。在图结构中表现为：[源端交流节点] -> [整流站] ==(直流边)==> [逆变站] -> [目标交流节点]；
    - 柔性交流装置加装：不增加图的边，而是在现有的边（线路）或节点上，串联或并联插入一个主动控制元件（如 UPFC 统一潮流控制器，或 SVC/STATCOM 静止无功发生器）；
    - 加强通道：新增线路将指定位置的节点连接到原网架中的其他节点。""",
        "requirements": """每个方案都需要输出对应的JSON数据
    - 注意：格式需要仿照当前网架结构的JSON数据，并标注对应方案几
    - 每个方案都需要加入“滇水富51”节点的JSON数据，对应的数据卡类型是“B”，对应的有功负荷（LOAD_P）为0
    - 只需输出删除、修改和新增的部份。
    - 需要指明每个数据卡对应的操作是什么。
    - 注意！L卡中“MILES”字段需要正确反映完整线路（新建线路+保留线路）的长度。
    - 每生成一个方案的JSON数据，都需要完整详细的文字说明和经济性分析（建设成本和维护成本）。""",
        "formulas": """(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；\n(2)电阻的计算方式：电阻=线路长度*0.000095*1.2；""",
    },
    "yuezhou": {
        "connectionMode": """    - 辐射式接线：新增1回线路，直接连接单一主电源节点与目标节点，不拆除原线路；
    - 环式接线：新增至少两条连线，将目标节点与周边至少两个不同节点相连形成物理多边形闭环，常态开环运行；
    - π接：断开原有的线路的一小部分，并将指定位置的节点接入到断开的线路中，需要在输出的JSON数据中标明需要删除的线路的信息；需要指明在距离什么端点多远距离的地方断开多长的线路，然后通过新建多长的线路将指定节点接入线网；
    - 网状接线：保留周边骨干线路，新增至少3条连线，将目标节点与多个枢纽节点直接相连；
    - 背靠背柔性直流互联：在两个交流分区之间，插入一个特殊的节点。该节点内部不包含任何交流传输线，而是通过背靠背的整流器和逆变器相连；
    - 直流联网接线：新增一条点对点的直流传输通道。在图结构中表现为：[源端交流节点] -> [整流站] ==(直流边)==> [逆变站] -> [目标交流节点]；
    - 柔性交流装置加装：不增加图的边，而是在现有的边（线路）或节点上，串联或并联插入一个主动控制元件（如 UPFC 统一潮流控制器，或 SVC/STATCOM 静止无功发生器）；
    - 加强通道：新增线路将指定位置的节点连接到原网架中的其他节点。""",
        "requirements": """每个方案都需要输出对应的JSON数据
    - 注意：格式需要仿照当前网架结构的JSON数据，并标注对应方案几
    - 每个方案都需要加入“滇越州51”节点的JSON数据，对应的数据卡类型是“B”，对应的有功负荷（LOAD_P）为119
    - 只需输出删除、修改和新增的部份。
    - 需要指明每个数据卡对应的操作是什么。
    - 注意！L卡中“MILES”字段需要正确反映完整线路（新建线路+保留线路）的长度。
    - 每生成一个方案的JSON数据，都需要完整详细的文字说明和经济性分析（建设成本和维护成本）。""",
        "formulas": """(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；\n(2)电阻的计算方式：电阻=线路长度*0.000095*1.2；""",
    },
    "generic": {
        "connectionMode": """    - 辐射式接线：新增1回线路，直接连接单一主电源节点与目标节点，不拆除原线路；
    - 环式接线：新增至少两条连线，将目标节点与周边至少两个不同节点相连形成物理多边形闭环，常态开环运行；
    - π接：断开原有的线路的一小部分，并将指定位置的节点接入到断开的线路中，需要在输出的JSON数据中标明需要删除的线路的信息；需要指明在距离什么端点多远距离的地方断开多长的线路，然后通过新建多长的线路将指定节点接入线网；
    - 网状接线：保留周边骨干线路，新增至少3条连线，将目标节点与多个枢纽节点直接相连；
    - 背靠背柔性直流互联：在两个交流分区之间，插入一个特殊的节点。该节点内部不包含任何交流传输线，而是通过背靠背的整流器和逆变器相连；
    - 直流联网接线：新增一条点对点的直流传输通道。在图结构中表现为：[源端交流节点] -> [整流站] ==(直流边)==> [逆变站] -> [目标交流节点]；
    - 柔性交流装置加装：不增加图的边，而是在现有的边（线路）或节点上，串联或并联插入一个主动控制元件（如 UPFC 统一潮流控制器，或 SVC/STATCOM 静止无功发生器）；
    - 加强通道：新增线路将指定位置的节点连接到原网架中的其他节点。""",
        "requirements": """每个方案都需要输出对应的JSON数据
    - 注意：格式需要仿照当前网架结构的JSON数据，并标注对应方案几
    - 每个方案都需要加入“bus0”节点的JSON数据，对应的数据卡类型是“B”，对应的有功负荷（LOAD_P）为0
    - 只需输出删除、修改和新增的部份。
    - 需要指明每个数据卡对应的操作是什么。
    - 注意！L卡中“MILES”字段需要正确反映完整线路（新建线路+保留线路）的长度。
    - 每生成一个方案的JSON数据，都需要完整详细的文字说明和经济性分析（建设成本和维护成本）。""",
        "formulas": """(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；\n(2)电阻的计算方式：电阻=线路长度*0.000095*1.2；""",
    },
}

PROMPT_CONTEXT_KEYS = {
    "siteRole": "site_role_prompt",
    "connectionMode": "wiring_mode_prompt",
    "requirements": "requirements_prompt",
    "formulas": "calculation_formula_prompt",
}

DEFAULT_SITE_ROLE = "load_substation"
DEFAULT_RADIAL_CIRCUIT_COUNTS = ["1"]

SITE_ROLE_PROMPT_SNIPPETS = {
    "load_substation": "    - 下网负荷变电站：该站点以承接和供应区域负荷为主，方案应优先保证负荷供电可靠性、供电能力和 N-1 安全裕度；",
    "renewable_collection": "    - 新能源汇集站：该站点以汇集风电、光伏等新能源出力为主，方案应优先考虑送出通道能力、消纳条件和新能源波动下的网架适应性；",
    "power_interconnection": "    - 电源接入站：该站点以接入常规电源或外部电源为主，方案应优先考虑电源送出能力、潮流分布和接入后系统安全稳定；",
    "grid_optimization": "    - 网架优化：该站点以优化既有网架结构、缓解过载或提升供电可靠性为主，方案应优先考虑潮流转移、薄弱断面加强和整体网架经济性。",
}

DEFAULT_SELECTED_WIRING_MODES = [
    "radial",
    "ring",
    "mesh",
    "pi",
    "back_to_back_dc",
    "dc_networking",
    "flexible_ac",
    "reinforcement",
]

WIRING_MODE_PROMPT_SNIPPETS = {
    "radial": [],
    "ring": [
        "    - 环式接线：新增至少两条连线，将目标节点与周边至少两个不同节点相连形成物理多边形闭环，常态开环运行；",
    ],
    "mesh": [
        "    - 网状接线：保留周边骨干线路，新增至少3条连线，将目标节点与多个枢纽节点直接相连；",
    ],
    "pi": [
        "    - π接：断开原有的线路的一小部分，并将指定位置的节点接入到断开的线路中，需要在输出的JSON数据中标明需要删除的线路的信息；需要指明在距离什么端点多远距离的地方断开多长的线路，然后通过新建多长的线路将指定节点接入线网；",
    ],
    "back_to_back_dc": [
        "    - 背靠背柔性直流互联：在两个交流分区之间，插入一个特殊的节点。该节点内部不包含任何交流传输线，而是通过背靠背的整流器和逆变器相连；",
    ],
    "dc_networking": [
        "    - 直流联网接线：新增一条点对点的直流传输通道。在图结构中表现为：[源端交流节点] -> [整流站] ==(直流边)==> [逆变站] -> [目标交流节点]；",
    ],
    "flexible_ac": [
        "    - 柔性交流装置加装：不增加图的边，而是在现有的边（线路）或节点上，串联或并联插入一个主动控制元件（如 UPFC 统一潮流控制器，或 SVC/STATCOM 静止无功发生器）；",
    ],
    "reinforcement": [
        "    - 加强通道：新增线路将指定位置的节点连接到原网架中的其他节点。",
    ],
}
REPORT_APP_DIR = os.path.abspath(os.path.join(script_dir, "..", "dianwang_report_gen"))
if REPORT_APP_DIR not in sys.path:
    sys.path.insert(0, REPORT_APP_DIR)
report_api_spec = importlib.util.spec_from_file_location(
    "dianwang_report_main_api",
    os.path.join(REPORT_APP_DIR, "main_api.py"),
)
report_api_module = importlib.util.module_from_spec(report_api_spec)
assert report_api_spec and report_api_spec.loader
sys.modules[report_api_spec.name] = report_api_module
report_api_spec.loader.exec_module(report_api_module)
report_loop = asyncio.new_event_loop()


def _run_report_loop():
    asyncio.set_event_loop(report_loop)
    report_loop.run_forever()


report_loop_thread = threading.Thread(
    target=_run_report_loop,
    name="report-api-loop",
    daemon=True,
)
report_loop_thread.start()

# 内存任务结构：
# TASKS[taskId] = {
#   "baseModelDir": "xxx",
#   "baseModelPath": "xxx.dat",
#   "schemes": [...],
#   "anomalies": [...],
#   "targetSchemeCount": n
# }

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return default


def build_site_role_prompt(site_role=None):
    role = str(site_role or DEFAULT_SITE_ROLE).strip() or DEFAULT_SITE_ROLE
    return SITE_ROLE_PROMPT_SNIPPETS.get(role, SITE_ROLE_PROMPT_SNIPPETS[DEFAULT_SITE_ROLE])


def normalize_radial_circuit_counts(radial_circuit_counts=None):
    if radial_circuit_counts is None:
        radial_circuit_counts = DEFAULT_RADIAL_CIRCUIT_COUNTS
    elif isinstance(radial_circuit_counts, str):
        radial_circuit_counts = [item.strip() for item in radial_circuit_counts.split(",") if item.strip()]
    elif not isinstance(radial_circuit_counts, list):
        radial_circuit_counts = DEFAULT_RADIAL_CIRCUIT_COUNTS

    allowed_counts = {"1", "2", "3", "4"}
    normalized = []
    for count in radial_circuit_counts:
        count_text = str(count).strip()
        if count_text in allowed_counts and count_text not in normalized:
            normalized.append(count_text)
    return normalized or list(DEFAULT_RADIAL_CIRCUIT_COUNTS)


def build_radial_wiring_mode_prompts(radial_circuit_counts=None):
    return [
        f"    - 辐射式接线：新增{count}回线路，直接连接单一主电源节点与目标节点，不拆除原线路；"
        for count in normalize_radial_circuit_counts(radial_circuit_counts)
    ]


def build_wiring_mode_prompt(selected_modes=None, custom_wiring_mode="", radial_circuit_counts=None):
    if selected_modes is None:
        selected_modes = DEFAULT_SELECTED_WIRING_MODES
    elif isinstance(selected_modes, str):
        selected_modes = [item.strip() for item in selected_modes.split(",") if item.strip()]
    elif not isinstance(selected_modes, list):
        selected_modes = DEFAULT_SELECTED_WIRING_MODES

    lines = []
    seen_lines = set()
    for mode in selected_modes:
        mode_key = str(mode)
        mode_lines = (
            build_radial_wiring_mode_prompts(radial_circuit_counts)
            if mode_key == "radial"
            else WIRING_MODE_PROMPT_SNIPPETS.get(mode_key, [])
        )
        for line in mode_lines:
            if line not in seen_lines:
                lines.append(line)
                seen_lines.add(line)

    custom_text = str(custom_wiring_mode or "").strip()
    if custom_text:
        lines.append("    - 用户填写的其他接线方式：" + custom_text)
    return "\n".join(lines)

def get_prompt_sections(case_type):
    sections = DEFAULT_PROMPT_SECTIONS.get(case_type, DEFAULT_PROMPT_SECTIONS["shuifu"]).copy()
    sections["siteRole"] = DEFAULT_SITE_ROLE
    sections["siteRolePrompt"] = build_site_role_prompt(DEFAULT_SITE_ROLE)
    sections["selectedWiringModes"] = list(DEFAULT_SELECTED_WIRING_MODES)
    sections["radialCircuitCounts"] = list(DEFAULT_RADIAL_CIRCUIT_COUNTS)
    sections["customWiringMode"] = ""
    sections["connectionMode"] = build_wiring_mode_prompt(
        sections["selectedWiringModes"],
        radial_circuit_counts=sections["radialCircuitCounts"],
    )
    return sections


def build_prompt_context(case_type, overrides=None):
    defaults = get_prompt_sections(case_type)
    case_config = CASE_CONFIGS.get(case_type, CASE_CONFIGS["shuifu"])
    overrides = overrides if isinstance(overrides, dict) else {}
    prompt_context = {}
    prompt_context.update({
        "target_node_name": case_config.get("target_node_name", "目标节点"),
        "target_load_p": case_config.get("target_load_p", "0"),
        "target_solution_instruction": case_config.get("target_solution_instruction", ""),
        "iteration_solution_instruction": case_config.get("iteration_solution_instruction", ""),
    })
    for frontend_key, context_key in PROMPT_CONTEXT_KEYS.items():
        if frontend_key == "siteRole":
            prompt_context[context_key] = build_site_role_prompt(overrides.get("siteRole"))
            continue
        if frontend_key == "requirements":
            extra_requirements = str(overrides.get("requirementsExtra") or "").strip()
            prompt_context["additional_requirements_prompt"] = (
                f"    用户新增要求：\n{extra_requirements}"
                if extra_requirements
                else ""
            )
            prompt_context[context_key] = (
                f"{defaults[frontend_key]}\n    用户新增要求：\n{extra_requirements}"
                if extra_requirements
                else defaults[frontend_key]
            )
            continue
        if frontend_key == "connectionMode":
            selected_modes = overrides.get("selectedWiringModes")
            custom_wiring_mode = overrides.get("customWiringMode")
            radial_circuit_counts = overrides.get("radialCircuitCounts")
            legacy_value = str(overrides.get("connectionMode") or "").strip()
            if legacy_value and not selected_modes and not custom_wiring_mode:
                prompt_context[context_key] = legacy_value
            else:
                prompt_context[context_key] = build_wiring_mode_prompt(
                    selected_modes,
                    custom_wiring_mode,
                    radial_circuit_counts=radial_circuit_counts,
                )
            continue
        value = str(overrides.get(frontend_key) or "").strip()
        prompt_context[context_key] = value or defaults[frontend_key]
    return prompt_context


def extract_prompt_overrides(payload):
    overrides = payload.get("promptOverrides")
    if not isinstance(overrides, dict):
        overrides = {}
    merged = dict(overrides)
    for key in ("siteRole", "connectionMode", "selectedWiringModes", "radialCircuitCounts", "customWiringMode", "requirementsExtra", "formulas"):
        if key in payload and payload.get(key) not in (None, ""):
            merged[key] = payload.get(key)
    return merged


def create_timestamped_result_root(timestamp=None):
    timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    result_root = os.path.join(RESULT_ROOT, timestamp)
    suffix = 1
    while os.path.exists(result_root):
        result_root = os.path.join(RESULT_ROOT, f"{timestamp}_{suffix:02d}")
        suffix += 1
    os.makedirs(result_root, exist_ok=True)
    return result_root


def get_task_result_root(task=None):
    if task and task.get("resultRoot"):
        return task["resultRoot"]
    return RESULT_ROOT


def extract_run_number(path):
    match = re.search(r"run_(\d+)", path)
    return int(match.group(1)) if match else 0


def list_success_run_dirs(result_root=None):
    pattern = os.path.join(result_root or RESULT_ROOT, "run_*")
    run_dirs = [p for p in glob.glob(pattern) if os.path.isdir(p)]
    return sorted(run_dirs, key=extract_run_number)


def resolve_latest_analysis_root(result_root=None):
    candidates = []
    for run_dir in list_success_run_dirs(result_root):
        pattern = os.path.join(run_dir, "test_output_v*", "analysis_1")
        for path in glob.glob(pattern):
            if os.path.isdir(path):
                candidates.append(path)
    if not candidates:
        fallback = os.path.join(result_root or RESULT_ROOT, "analysis_1")
        return fallback
    candidates.sort(key=lambda path: (extract_run_number(path), os.path.getmtime(path)))
    return candidates[-1]


def summarize_modifications(modifications):
    if not modifications:
        return "该方案未记录改造动作。"

    action_labels = {
        "add_line": "新增线路",
        "add_bus": "新增母线",
        "disable_branch": "停运线路",
        "remove_line": "拆除线路",
        "split_bus": "母线拆分"
    }
    counts = {}
    for item in modifications:
        action = item.get("action", "unknown")
        counts[action] = counts.get(action, 0) + 1

    parts = []
    for action, count in counts.items():
        parts.append(f"{action_labels.get(action, action)} {count} 项")
    return "，".join(parts)


def count_actions_from_proposals(proposals):
    action_counts = {}
    for proposal_data in proposals:
        proposal = proposal_data.get("proposal", {})
        for item in proposal.get("modifications", []) or []:
            action = item.get("action", "unknown")
            action_counts[action] = action_counts.get(action, 0) + 1
    return action_counts


def merge_topology(topologies):
    node_map = {}
    edge_map = {}
    circuit_counts = {}

    def normalized_edge_key(edge):
        source = edge.get("source")
        target = edge.get("target")
        ordered = tuple(sorted([source, target]))
        return (ordered[0], ordered[1], edge.get("type"))

    for topology in topologies:
        for node in topology.get("nodes", []):
            node_map[node["id"]] = node
        for edge in topology.get("edges", []):
            count_key = normalized_edge_key(edge)
            circuit_counts[count_key] = circuit_counts.get(count_key, 0) + 1
            edge_key = (
                edge.get("source"),
                edge.get("target"),
                edge.get("type"),
                edge.get("proposalName"),
                edge.get("iteration"),
                edge.get("schemeNumber")
            )
            edge_map[edge_key] = edge

    merged_edges = list(edge_map.values())
    for edge in merged_edges:
        edge["circuitCount"] = circuit_counts.get(normalized_edge_key(edge), 1)

    return {"nodes": list(node_map.values()), "edges": merged_edges}


def build_topology_from_proposal(proposal, iteration=None, scheme_number=None):
    proposal_name = proposal.get("proposal_name") or "未命名方案"
    modifications = proposal.get("modifications", [])
    node_map = {}
    edges = []

    def ensure_node(name, node_type="电网节点"):
        if not name:
            return
        if name not in node_map:
            node_map[name] = {
                "id": name,
                "label": name,
                "type": node_type,
                "voltage": "未知"
            }

    for item in modifications:
        action = item.get("action", "")
        params = item.get("params", {})
        branch_data = params.get("full_branch_data", {})
        bus_data = params.get("full_bus_data", {})

        if bus_data:
            ensure_node(bus_data.get("NAME"), "新增母线")

        if branch_data:
            source = branch_data.get("NAME1")
            target = branch_data.get("NAME2")
            ensure_node(source)
            ensure_node(target)
            if source and target:
                edges.append({
                    "source": source,
                    "target": target,
                    "type": "新增线路" if action == "add_line" else "停运线路" if action == "disable_branch" else action,
                    "proposalName": proposal_name,
                    "iteration": iteration,
                    "schemeNumber": scheme_number
                })

    return {"nodes": list(node_map.values()), "edges": edges}


def select_final_proposal(proposal_files):
    ranked = []
    for proposal_path in proposal_files:
        try:
            proposal_data = load_json(proposal_path)
            ranked.append((
                int(proposal_data.get("iteration", 0)),
                int(proposal_data.get("scheme_number", 0)),
                proposal_path,
                proposal_data
            ))
        except Exception as e:
            print(f"Warning: 加载方案文件失败 {proposal_path}: {e}")
    if not ranked:
        return None, None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    _, _, final_path, final_data = ranked[-1]
    return final_path, final_data


def build_scheme_from_run(run_dir):
    proposal_glob = os.path.join(run_dir, "result", "proposal", "*.json")
    proposal_files = sorted(glob.glob(proposal_glob))
    if not proposal_files:
        return None

    latest_updated_at = max(os.path.getmtime(path) for path in proposal_files)

    proposal_path, selected = select_final_proposal(proposal_files)
    if not selected:
        return None

    proposal_topologies = []
    proposal_payloads = []
    proposal_summaries = []
    for proposal_file in proposal_files:
        try:
            proposal_data = load_json(proposal_file)
            proposal_payloads.append(proposal_data)
            proposal_body = proposal_data.get("proposal", {})
            proposal_topologies.append(
                build_topology_from_proposal(
                    proposal_body,
                    iteration=int(proposal_data.get("iteration", 0)),
                    scheme_number=int(proposal_data.get("scheme_number", 0))
                )
            )
            proposal_summaries.append({
                "path": proposal_file,
                "iteration": int(proposal_data.get("iteration", 0)),
                "schemeNumber": int(proposal_data.get("scheme_number", 0)),
                "proposalName": proposal_body.get("proposal_name") or "未命名方案"
            })
        except Exception as e:
            print(f"Warning: 汇总方案拓扑失败 {proposal_file}: {e}")

    proposal = selected.get("proposal", {})
    modifications = proposal.get("modifications", [])
    run_number = extract_run_number(run_dir)
    iteration = int(selected.get("iteration", 0))
    scheme_number = int(selected.get("scheme_number", 0))
    iteration_count = len([
        item for item in os.listdir(run_dir)
        if os.path.isdir(os.path.join(run_dir, item)) and item.startswith("test_output_v")
    ])
    action_counts = count_actions_from_proposals(proposal_payloads)
    added_line_count = action_counts.get("add_line", 0)
    removed_line_count = action_counts.get("disable_branch", 0) + action_counts.get("remove_line", 0)
    summary = (
        f"对应 run_{run_number} 的最终成功方案，"
        f"新增线路 {added_line_count} 项，删除线路 {removed_line_count} 项。"
    )

    return {
        "schemeId": f"run_{run_number}",
        "name": proposal.get("proposal_name") or f"run_{run_number} 最终方案",
        "summary": summary,
        "score": None,
        "runNumber": run_number,
        "iteration": iteration,
        "schemeNumber": scheme_number,
        "iterationCount": iteration_count,
        "runDir": run_dir,
        "proposalPath": proposal_path,
        "latestUpdatedAt": latest_updated_at,
        "proposal": proposal,
        "proposalFiles": proposal_summaries,
        "topology": merge_topology(proposal_topologies),
        "raw": selected
    }


def load_schemes(updated_after=None, result_root=None):
    schemes = []
    for run_dir in list_success_run_dirs(result_root):
        scheme = build_scheme_from_run(run_dir)
        if scheme and (updated_after is None or scheme.get("latestUpdatedAt", 0) >= updated_after):
            schemes.append(scheme)
    return schemes


def extract_anomaly_items(report_payloads):
    items = []
    pf_report = report_payloads.get("pf_report_1.json", {})
    pf_analysis = pf_report.get("analysis", {})
    if pf_analysis.get("is_convergent") is False:
        items.append({
            "severity": "高",
            "title": "潮流不收敛",
            "location": pf_report.get("input_dat", "基础模型")
        })
    for line in pf_analysis.get("overloaded_lines", []) or []:
        items.append({
            "severity": "中",
            "title": line.get("问题描述", "潮流异常"),
            "location": f"{line.get('线路端点1', '未知')} - {line.get('线路端点2', '未知')}"
        })

    n1_report = report_payloads.get("n1_report_1.json", {})
    for case in n1_report.get("contingencies_with_issues", []) or []:
        items.append({
            "severity": "高",
            "title": "N-1 校核异常",
            "location": case.get("contingency_branch_uid", "未知断面")
        })

    scc_report = report_payloads.get("scc_report_1.json", {})
    scc_analysis = scc_report.get("analysis", {})
    for case in scc_analysis.get("contingencies_with_issues", []) or []:
        items.append({
            "severity": "中",
            "title": f"短路电流超限（{case.get('fault_type', '未知故障')})",
            "location": case.get("bus_name", "未知母线")
        })
    return items


def resolve_initial_analysis_root(case_config):
    n1_report = case_config.get("n1_report") if case_config else None
    if not n1_report:
        return None

    report_path = n1_report if os.path.isabs(n1_report) else os.path.join(script_dir, n1_report)
    if not os.path.exists(report_path):
        return None
    return os.path.dirname(report_path)


def load_anomaly_reports(result_root=None, analysis_root=None):
    analysis_root = analysis_root or resolve_latest_analysis_root(result_root)
    reports = {}
    files = []
    for filename, title in REPORT_FILES.items():
        path = os.path.join(analysis_root, filename)
        files.append({
            "name": filename,
            "title": title,
            "path": path,
            "exists": os.path.exists(path)
        })
        if os.path.exists(path):
            try:
                reports[filename] = load_json(path)
            except Exception as e:
                reports[filename] = {"error": f"读取失败: {e}"}

    return {
        "files": files,
        "reports": reports,
        "items": extract_anomaly_items(reports)
    }


SCHEMES = load_schemes()
ANOMALIES = load_anomaly_reports()


def ensure_report_api_ready():
    if getattr(report_api_module, "READY", False):
        return True, ""
    try:
        report_api_module._init_clients_once()
        report_api_module.READY = True
        report_api_module.READY_ERROR = ""
        return True, ""
    except Exception as exc:
        report_api_module.READY = False
        report_api_module.READY_ERROR = str(exc)
        return False, str(exc)


async def proxy_report_api_async(path, method=None, forward_body=True):
    method = method or request.method
    should_check_ready = not path.startswith("/api/compare-reports")
    if should_check_ready:
        ready, error = ensure_report_api_ready()
        if not ready:
            return jsonify({
                "error": "报告服务不可用",
                "detail": error,
            }), 502
    query_string = request.query_string.decode("utf-8")
    target_url = f"http://report-api.local{path}"
    if query_string:
        target_url = f"{target_url}?{query_string}"

    headers = {}
    if request.content_type:
        headers["Content-Type"] = request.content_type

    body = request.get_data() if forward_body else None
    if path == "/api/compare-reports" and method == "POST" and forward_body:
        try:
            payload = request.get_json(force=True, silent=True) or {}
            if REPORT_TEST_INPUT_DIR:
                payload["inputDir"] = REPORT_TEST_INPUT_DIR
            else:
                task = TASKS.get(payload.get("taskId", ""))
                if task and task.get("resultRoot"):
                    payload["inputDir"] = task["resultRoot"]
                elif payload.get("useReportInputOverride") and payload.get("inputDir"):
                    payload["inputDir"] = payload["inputDir"]
                else:
                    return jsonify({"error": "缺少 taskId 或任务结果目录，无法生成比选报告"}), 400
            if REPORT_BACKGROUND_CONTEXT_FILE and not payload.get("backgroundContextFile"):
                payload["backgroundContextFile"] = REPORT_BACKGROUND_CONTEXT_FILE
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        except Exception as exc:
            print(f"Warning: 注入比选报告输入目录失败: {exc}")
    transport = httpx.ASGITransport(app=report_api_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://report-api.local", timeout=120.0) as client:
        upstream = await client.request(
            method=method,
            url=target_url,
            content=body,
            headers=headers,
        )

    excluded_headers = {"content-encoding", "transfer-encoding", "connection"}
    response_headers = [
        (key, value)
        for key, value in upstream.headers.items()
        if key.lower() not in excluded_headers
    ]
    return Response(
        upstream.content,
        status=upstream.status_code,
        headers=response_headers,
    )


def proxy_report_api(path, method=None, forward_body=True):
    future = asyncio.run_coroutine_threadsafe(
        proxy_report_api_async(path, method=method, forward_body=forward_body),
        report_loop,
    )
    return future.result()

@app.route("/api/files/upload", methods=["POST"])
def upload():
    print("DEBUG: 收到文件上传请求")
    print(f"DEBUG: MAX_CONTENT_LENGTH = {app.config.get('MAX_CONTENT_LENGTH')}")
    # 使用相对于脚本的路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_ROOT = os.path.join(script_dir, "powergrid_pipeline_v2", "data_test")
    files = request.files.getlist("file")
    relative_paths = request.form.getlist("relativePath")
    if not files:
        # 兼容单文件上传
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "未收到文件"}), 400
        files = [file]

    saved_files = []
    abs_files = []
    base_model_path = None
    for index, file in enumerate(files):
        rel_path = relative_paths[index] if index < len(relative_paths) else ""
        if not rel_path:
            rel_path = getattr(file, 'filename', None) or ""
        if not rel_path:
            rel_path = file.filename
        save_path = os.path.join(UPLOAD_ROOT, rel_path)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)
        saved_files.append(rel_path)
        abs_path = os.path.abspath(save_path)
        abs_files.append(abs_path)
        if abs_path.lower().endswith('.dat') and base_model_path is None:
            base_model_path = abs_path

    return jsonify({
        "fileId": "file-local-1",
        "saved": saved_files,
        "abs_paths": abs_files,
        "baseModelPath": base_model_path,
        "uploadRoot": os.path.abspath(UPLOAD_ROOT)
    })


@app.route("/api/prompt-defaults")
def prompt_defaults():
    case_type = str(request.args.get("caseType") or request.args.get("case") or "shuifu").lower()
    if case_type not in CASE_CONFIGS:
        return jsonify({"error": f"未知案例类型: {case_type}"}), 400
    return jsonify(get_prompt_sections(case_type))

@app.route("/api/tasks", methods=["POST"])
def create_task():
    print("DEBUG: create_task called")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    payload = request.get_json(force=True, silent=True) or {}
    base_model_path = payload.get("baseModelPath") or payload.get("baseModelDir")
    target = int(payload.get("targetSchemeCount", payload.get("target", 0)))
    case_type = str(payload.get("caseType") or payload.get("case") or "shuifu").lower()
    enable_transient_analysis = parse_bool(payload.get("enableTransientAnalysis"), default=False)
    if case_type not in CASE_CONFIGS:
        return jsonify({"error": f"未知案例类型: {case_type}"}), 400
    case_config = CASE_CONFIGS[case_type]
    prompt_overrides = extract_prompt_overrides(payload)
    prompt_context = build_prompt_context(case_type, prompt_overrides)
    result_root = create_timestamped_result_root()
    run_timestamp = os.path.basename(result_root)
    print(f"DEBUG: base_model_path = {base_model_path}, target = {target}, case_type = {case_type}, result_root = {result_root}")
    if not base_model_path and not USE_PRECOMPUTED_RESULTS:
        print("DEBUG: no base_model_path")
        return jsonify({"error": "必须提供原始 .dat 文件路径 baseModelPath"}), 400

    if base_model_path and not os.path.exists(base_model_path) and not USE_PRECOMPUTED_RESULTS:
        print(f"DEBUG: file not exists {base_model_path}")
        return jsonify({"error": f".dat 文件不存在: {base_model_path}"}), 400
    task_id = f"task_{run_timestamp}"

    # 从本任务结果目录加载，避免多次运行/多案例之间串结果。
    schemes = load_schemes(result_root=result_root)
    initial_analysis_root = resolve_initial_analysis_root(case_config)
    anomalies = load_anomaly_reports(result_root=result_root, analysis_root=initial_analysis_root)
    initial_reports_ready = bool(initial_analysis_root and anomalies.get("reports"))
    if initial_reports_ready:
        print(f"DEBUG: using existing initial analysis reports: {initial_analysis_root}")

    TASKS[task_id] = {
        "baseModelPath": base_model_path,
        "caseType": case_type,
        "resultRoot": result_root,
        "schemes": schemes,
        "anomalies": anomalies,
        "targetSchemeCount": target,
        "enableTransientAnalysis": enable_transient_analysis,
        "process": None,
        "start_time": time.time(),
        "resultFilterStart": None if USE_PRECOMPUTED_RESULTS else time.time(),
        "anomaliesPresented": False,
        "initialAnalysisRoot": initial_analysis_root,
        "initialReportsReady": initial_reports_ready,
        "status": "COMPLETED" if USE_PRECOMPUTED_RESULTS else "RUNNING",
        "precomputed": USE_PRECOMPUTED_RESULTS
    }

    if USE_PRECOMPUTED_RESULTS:
        print(f"DEBUG: task created with precomputed results, task_id = {task_id}")
        return jsonify({
            "taskId": task_id,
        "message": f"已加载预生成结果目录: {os.path.basename(result_root)}",
        "resultRoot": result_root
        })

    context_json_path = case_config["context"]
    filter_500kv_only = case_config.get("filter_500kv_only", False)

    if base_model_path:
        from powergrid_pipeline_v2.src.services.preprocessing_service import PreprocessingService

        print(f"DEBUG: {case_type} case detected, generating context.json from dat file...")

        preprocessing_service = PreprocessingService()
        generated_context_path = os.path.join(result_root, "context.json")

        if case_type == "generic":
            base_context_path = os.path.join(script_dir, "powergrid_pipeline_v2", "data", "context_generic_template.json")
            task_description = "请基于当前网架结构生成五个可行的通用接入方案，解决目标的 N-1 过载问题。"
        else:
            base_context_path = os.path.join(script_dir, case_config["context"])
            task_description = None

        success, message = preprocessing_service.build_context_from_dat(
            dat_path=base_model_path,
            output_path=generated_context_path,
            base_context_path=base_context_path,
            task_description=task_description,
            filter_500kv_only=filter_500kv_only,
        )

        if not success:
            print(f"DEBUG: failed to generate context.json: {message}")
            return jsonify({"error": f"生成 context.json 失败: {message}"}), 500

        context_json_path = generated_context_path
        print(f"DEBUG: context.json generated at: {generated_context_path}")

    try:
        with open(context_json_path, "r", encoding="utf-8") as f:
            context_data = json.load(f)
        context_data.update(prompt_context)
        with open(context_json_path, "w", encoding="utf-8") as f:
            json.dump(context_data, f, indent=2, ensure_ascii=False)
        prompt_context_path = os.path.join(result_root, "prompt_context.json")
        with open(prompt_context_path, "w", encoding="utf-8") as f:
            json.dump({
                "caseType": case_type,
                "promptOverrides": prompt_overrides,
                "promptContext": prompt_context,
                "contextJsonPath": context_json_path,
                "enableTransientAnalysis": enable_transient_analysis,
            }, f, indent=2, ensure_ascii=False)
        print("DEBUG: prompt overrides written to context.json")
    except Exception as exc:
        print(f"DEBUG: failed to write prompt overrides: {exc}")
        return jsonify({"error": f"写入 Prompt 输入失败: {exc}"}), 500

    # 启动 main_scc.py 进程，并将输出重定向到日志文件
    try:
        print("DEBUG: starting subprocess")

        # 使用绝对路径创建日志目录
        log_dir = os.path.join(script_dir, "powergrid_pipeline_v2", "logs", task_id)
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "main_scc.log")
        progress_path = os.path.join(log_dir, "progress.json")
        log_file = open(log_path, "w", encoding="utf-8", buffering=1)

        main_scc_path = os.path.join(script_dir, "powergrid_pipeline_v2", "functional_tests", "main_scc.py")

        # 设置环境变量，确保 Python 使用 UTF-8 编码
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'
        env['PROGRESS_FILE'] = progress_path
        env['TARGET_SCHEME_COUNT'] = str(target)

        command = [
            sys.executable,
            "-u",
            main_scc_path,
            base_model_path,
            str(target),
            "--context-json",
            context_json_path,
            "--initial-prompt",
            case_config["initial_prompt"],
            "--iteration-prompt",
            case_config["iteration_prompt"],
            "--output-root",
            result_root,
            "--initial-scc-issues",
            case_config["initial_scc_issues"],
            "--success-n1-issues",
            case_config["success_n1_issues"],
        ]
        if case_config.get("n1_report"):
            command.extend(["--n1-report", case_config["n1_report"]])
        if case_config.get("fixed_analysis_report"):
            command.extend(["--fixed-analysis-report", case_config["fixed_analysis_report"]])
        if case_config.get("target_overload_node1") and case_config.get("target_overload_node2"):
            command.extend([
                "--target-overload-node1",
                case_config["target_overload_node1"],
                "--target-overload-node2",
                case_config["target_overload_node2"],
            ])
        if case_config.get("related_nodes"):
            command.extend([
                "--related-nodes",
                case_config["related_nodes"],
            ])
        if case_config.get("skip_scc_analysis"):
            command.append("--skip-scc-analysis")
        if enable_transient_analysis:
            command.append("--enable-transient-analysis")

        process = subprocess.Popen(
            command,
            stdout=log_file, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True,
            cwd=script_dir,
            env=env
        )
        TASKS[task_id]["process"] = process
        TASKS[task_id]["log_path"] = log_path
        TASKS[task_id]["progress_path"] = progress_path
        print(f"DEBUG: subprocess started, PID: {process.pid}, log: {log_path}")
    except Exception as e:
        print(f"DEBUG: subprocess error: {e}")
        TASKS[task_id]["status"] = "FAILED"
        return jsonify({"error": f"启动 main_scc.py 失败: {str(e)}"}), 500

    print(f"DEBUG: task created, task_id = {task_id}")
    return jsonify({
        "taskId": task_id,
        "caseType": case_type,
        "resultRoot": result_root,
        "promptContextPath": os.path.join(result_root, "prompt_context.json"),
    })
@app.route("/api/tasks/<tid>/log")
def task_log(tid):
    task = TASKS.get(tid)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    log_path = task.get("log_path")
    if not log_path or not os.path.exists(log_path):
        return jsonify({"log": "日志文件不存在或任务尚未启动。"})
    content = safe_read_log(log_path)
    if content is None:
        content = "日志读取失败，内容为空。"
    return jsonify({"log": str(content)})

def safe_read_log(log_path):
    try:
        with open(log_path, "rb") as f:
            raw = f.read()[-10000:]
        # 优先尝试 utf-8
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return raw.decode("gbk")
            except UnicodeDecodeError:
                return raw.decode("latin1", errors="replace")
    except Exception as e:
        return f"读取日志失败: {e}"

def read_progress(progress_path):
    try:
        if not os.path.exists(progress_path):
            return None
        with open(progress_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return None

@app.route("/api/tasks/<tid>/progress")
def get_progress(tid):
    task = TASKS.get(tid)
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    progress_path = task.get("progress_path")
    if not progress_path:
        return jsonify({"error": "进度信息不可用"}), 404

    progress = read_progress(progress_path)
    if progress is None:
        return jsonify({"stage": "UNKNOWN", "message": "等待进度更新...", "logs": []})

    return jsonify(progress)

@app.route("/api/tasks/<tid>/status")
def status(tid):
    task = TASKS.get(tid)
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    process = task.get("process")
    progress_path = task.get("progress_path")
    progress = read_progress(progress_path) if progress_path else None
    result_filter_start = task.get("resultFilterStart")
    result_root = get_task_result_root(task)
    filtered_schemes = load_schemes(updated_after=result_filter_start, result_root=result_root)
    progress_generated_count = int((progress or {}).get("generated_scheme_count", 0) or 0)
    progress_target_count = int((progress or {}).get("target_scheme_count", task.get("targetSchemeCount", 0)) or 0)
    initial_reports_ready = bool(task.get("initialReportsReady"))
    reports_ready = bool((progress or {}).get("analysis_reports_ready")) or initial_reports_ready
    anomalies_presented = bool(task.get("anomaliesPresented"))
    current_generated_count = progress_generated_count

    if process:
        message = progress.get("message", "正在执行...") if progress else "正在执行 main_scc.py..."
        if process.poll() is None:
            task["schemes"] = filtered_schemes
            if progress_target_count > 0 and current_generated_count >= progress_target_count:
                status = "COMPLETED"
            elif reports_ready and anomalies_presented:
                status = "PLANNING"
            elif reports_ready:
                status = "ANOMALY_DONE"
            else:
                status = "SIMULATING"
        else:
            if process.returncode == 0:
                schemes = filtered_schemes
                task["schemes"] = schemes
                current_generated_count = progress_generated_count or len(schemes)
                if current_generated_count >= progress_target_count > 0:
                    status = "COMPLETED"
                    message = progress.get("message", f"任务完成，已生成 {current_generated_count} 个方案") if progress else f"任务完成，已生成 {current_generated_count} 个方案"
                elif schemes:
                    status = "PLANNING"
                elif reports_ready and anomalies_presented:
                    status = "PLANNING"
                elif reports_ready:
                    status = "ANOMALY_DONE"
                else:
                    status = "FAILED"
                    message = "任务完成但未找到方案结果"
            else:
                status = "FAILED"
                message = f"main_scc.py 执行失败，返回码: {process.returncode}"
                if progress and progress.get("error"):
                    message = progress.get("message", message)
    else:
        status = task.get("status", "UNKNOWN")
        if task.get("precomputed"):
            schemes = filtered_schemes
            task["schemes"] = schemes
            current_generated_count = len(schemes)
            status = "COMPLETED"
            message = f"已加载预生成结果，共 {current_generated_count} 个成功方案"
        else:
            message = "任务状态未知"

    schemes = task.get("schemes", [])
    response = {
        "taskId": tid,
        "status": status,
        "generatedSchemeCount": current_generated_count,
        "targetSchemeCount": progress_target_count or task.get("targetSchemeCount", len(schemes)),
        "message": message,
        "caseType": task.get("caseType", "shuifu"),
        "resultRoot": result_root,
    }

    if progress:
        response["progress"] = {
            "stage": progress.get("stage", "UNKNOWN"),
            "step": progress.get("step", 0),
            "total_steps": progress.get("total_steps", 0),
            "logs": progress.get("logs", []),
            "generated_scheme_count": progress.get("generated_scheme_count", 0),
            "target_scheme_count": progress.get("target_scheme_count", 0),
            "analysis_reports_ready": progress.get("analysis_reports_ready", False) or initial_reports_ready
        }
        if progress.get("error"):
            response["error"] = progress.get("error")

    return jsonify(response)

@app.route("/api/tasks/<tid>/anomalies")
def anomalies(tid):
    task = TASKS.get(tid)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    anomaly_data = load_anomaly_reports(
        result_root=get_task_result_root(task),
        analysis_root=task.get("initialAnalysisRoot"),
    )
    task["anomalies"] = anomaly_data
    if anomaly_data.get("reports"):
        task["anomaliesPresented"] = True
    return jsonify(anomaly_data)

@app.route("/api/tasks/<tid>/schemes")
def schemes(tid):
    task = TASKS.get(tid)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    schemes = load_schemes(updated_after=task.get("resultFilterStart"), result_root=get_task_result_root(task))
    task["schemes"] = schemes
    l = int(request.args.get("limit", len(schemes)))
    items = [{k:v for k,v in s.items() if k!="raw"} for s in schemes[:l]]
    return jsonify({"items": items})

@app.route("/api/tasks/<tid>/schemes/<sid>")
def scheme_detail(tid, sid):
    task = TASKS.get(tid)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    schemes = load_schemes(updated_after=task.get("resultFilterStart"), result_root=get_task_result_root(task))
    task["schemes"] = schemes
    scheme = next((item for item in schemes if item.get("schemeId") == sid), None)
    if not scheme:
        return jsonify({"error": "方案不存在"}), 404
    detail = {k: v for k, v in scheme.items()}
    return jsonify(detail)

@app.route("/api/tasks/<tid>/schemes/<sid>/topology")
def topology(tid,sid):
    task = TASKS.get(tid)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    schemes = load_schemes(updated_after=task.get("resultFilterStart"), result_root=get_task_result_root(task))
    task["schemes"] = schemes
    s = next((x for x in schemes if x.get("schemeId") == sid), None)
    if not s:
        return jsonify({"error": "方案不存在"}), 404
    return jsonify(s.get("topology", {}))


@app.route("/api/report-service/health")
def report_service_health():
    return proxy_report_api("/api/health", method="GET", forward_body=False)


@app.route("/api/compare-reports", methods=["POST"])
def create_compare_report_proxy():
    return proxy_report_api("/api/compare-reports")


@app.route("/api/compare-reports/<path:subpath>", methods=["GET", "POST"])
def compare_reports_proxy(subpath):
    return proxy_report_api(f"/api/compare-reports/{subpath}")


@app.route("/api/reports/read-md", methods=["POST"])
def read_report_md_proxy():
    return proxy_report_api("/api/reports/read-md")


@app.route("/api/reports/save-md", methods=["POST"])
def save_report_md_proxy():
    return proxy_report_api("/api/reports/save-md")


@app.route("/api/reports/reset-md", methods=["POST"])
def reset_report_md_proxy():
    return proxy_report_api("/api/reports/reset-md")


@app.route("/api/reports/convert", methods=["POST"])
def convert_report_proxy():
    return proxy_report_api("/api/reports/convert")


@app.route("/api/reports/versions", methods=["GET"])
def list_report_versions_proxy():
    return proxy_report_api("/api/reports/versions", method="GET", forward_body=False)


@app.route("/api/reports/versions/read", methods=["POST"])
def read_report_version_proxy():
    return proxy_report_api("/api/reports/versions/read")


@app.route("/api/reports/versions/rollback", methods=["POST"])
def rollback_report_version_proxy():
    return proxy_report_api("/api/reports/versions/rollback")


@app.route("/api/reports/versions/delete", methods=["POST"])
def delete_report_version_proxy():
    return proxy_report_api("/api/reports/versions/delete")


@app.route("/api/reports/rewrite", methods=["POST"])
def rewrite_report_proxy():
    return proxy_report_api("/api/reports/rewrite")


@app.route("/api/reports/download", methods=["GET"])
def download_report_proxy():
    return proxy_report_api("/api/reports/download", method="GET", forward_body=False)

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def frontend(path):
    print(f"DEBUG: frontend() 请求路径: {path}")
    if path != "":
        file_path = os.path.join(app.static_folder, path)
        print(f"DEBUG: 检查文件: {file_path}, 存在: {os.path.exists(file_path)}")
        if os.path.exists(file_path):
            print(f"DEBUG: 返回静态文件: {path}")
            return send_from_directory(app.static_folder, path)
    print(f"DEBUG: 返回 index.html")
    return send_from_directory(app.static_folder, "index.html")

if __name__ == "__main__":
    app.run(
        port=int(os.environ.get("PORT", "8080")),
        host=os.environ.get("HOST", "127.0.0.1"),
        debug=False,
    )
