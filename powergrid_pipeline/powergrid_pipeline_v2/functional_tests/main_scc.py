import sys, os
# 把 powergrid_pipeline_v2 的父目录加入 sys.path，确保 import src 可用
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# 设置 stdout 编码为 utf-8，避免 Windows 下 Emoji 输出报错。
# line_buffering/write_through 让重定向到 main_scc.log 时也能尽快落盘。
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True, write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True, write_through=True)

import os
import json
import glob
import shutil
import time
import sys
import argparse
from src.utils.config import load_config_as_dotdict
from src.services.generation_services import GenerationService
from src.services.application_service import ApplicationService
from src.services.analysis_services import AnalysisService
from src.services.generation_services import SelectionService

DEFAULT_PROMPT_CONTEXT_BY_CASE = {
    "shuifu": {
        "site_role_prompt": "    - 下网负荷变电站：该站点以承接和供应区域负荷为主，方案应优先保证负荷供电可靠性、供电能力和 N-1 安全裕度；",
        "wiring_mode_prompt": """    - 辐射式接线：新增1回线路，直接连接单一主电源节点与目标节点，不拆除原线路；
    - 环式接线：新增至少两条连线，将目标节点与周边至少两个不同节点相连形成物理多边形闭环，常态开环运行；
    - π接：断开原有的线路的一小部分，并将指定位置的节点接入到断开的线路中，需要在输出的JSON数据中标明需要删除的线路的信息；需要指明在距离什么端点多远距离的地方断开多长的线路，然后通过新建多长的线路将指定节点接入线网；
    - 网状接线：保留周边骨干线路，新增至少3条连线，将目标节点与多个枢纽节点直接相连；
    - 背靠背柔性直流互联：在两个交流分区之间，插入一个特殊的节点。该节点内部不包含任何交流传输线，而是通过背靠背的整流器和逆变器相连；
    - 直流联网接线：新增一条点对点的直流传输通道。在图结构中表现为：[源端交流节点] -> [整流站] ==(直流边)==> [逆变站] -> [目标交流节点]；
    - 柔性交流装置加装：不增加图的边，而是在现有的边（线路）或节点上，串联或并联插入一个主动控制元件（如 UPFC 统一潮流控制器，或 SVC/STATCOM 静止无功发生器）；
    - 加强通道：新增线路将指定位置的节点连接到原网架中的其他节点。""",
        "calculation_formula_prompt": """(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；
    (2)电阻的计算方式：电阻=线路长度*0.000095*1.2；""",
        "additional_requirements_prompt": "",
        "target_node_name": "滇水富51",
        "target_load_p": "0",
        "target_solution_instruction": "你需要先定位过载线路的位置，然后通过将滇水富51节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。",
        "iteration_solution_instruction": "你需要先定位过载线路的位置，然后通过将滇水富51节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。由经验得，问题节点的既定负荷很大，需要传输能力很强的线路，或设置多回线路来解决该线网问题。",
    },
    "yuezhou": {
        "site_role_prompt": "    - 下网负荷变电站：该站点以承接和供应区域负荷为主，方案应优先保证负荷供电可靠性、供电能力和 N-1 安全裕度；",
        "wiring_mode_prompt": """    - 辐射式接线：新增1回线路，直接连接单一主电源节点与目标节点，不拆除原线路；
    - 环式接线：新增至少两条连线，将目标节点与周边至少两个不同节点相连形成物理多边形闭环，常态开环运行；
    - π接：断开原有的线路的一小部分，并将指定位置的节点接入到断开的线路中，需要在输出的JSON数据中标明需要删除的线路的信息；需要指明在距离什么端点多远距离的地方断开多长的线路，然后通过新建多长的线路将指定节点接入线网；
    - 网状接线：保留周边骨干线路，新增至少3条连线，将目标节点与多个枢纽节点直接相连；
    - 背靠背柔性直流互联：在两个交流分区之间，插入一个特殊的节点。该节点内部不包含任何交流传输线，而是通过背靠背的整流器和逆变器相连；
    - 直流联网接线：新增一条点对点的直流传输通道。在图结构中表现为：[源端交流节点] -> [整流站] ==(直流边)==> [逆变站] -> [目标交流节点]；
    - 柔性交流装置加装：不增加图的边，而是在现有的边（线路）或节点上，串联或并联插入一个主动控制元件（如 UPFC 统一潮流控制器，或 SVC/STATCOM 静止无功发生器）；
    - 加强通道：新增线路将指定位置的节点连接到原网架中的其他节点。""",
        "calculation_formula_prompt": """(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；
    (2)电阻的计算方式：电阻=线路长度*0.000095*1.2；""",
        "additional_requirements_prompt": "",
        "target_node_name": "滇越州51",
        "target_load_p": "119",
        "target_solution_instruction": "你需要先定位过载线路的位置，然后通过将滇越州51节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。",
        "iteration_solution_instruction": "你需要先定位过载线路的位置，然后通过将滇越州51节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。由经验得，问题节点的既定负荷很大，需要传输能力很强的线路，或设置多回线路来解决该线网问题。",
    },
    "generic": {
        "site_role_prompt": "    - 下网负荷变电站：该站点以承接和供应区域负荷为主，方案应优先保证负荷供电可靠性、供电能力和 N-1 安全裕度；",
        "wiring_mode_prompt": """    - 辐射式接线：新增1回线路，直接连接单一主电源节点与目标节点，不拆除原线路；
    - 环式接线：新增至少两条连线，将目标节点与周边至少两个不同节点相连形成物理多边形闭环，常态开环运行；
    - π接：断开原有的线路的一小部分，并将指定位置的节点接入到断开的线路中，需要在输出的JSON数据中标明需要删除的线路的信息；需要指明在距离什么端点多远距离的地方断开多长的线路，然后通过新建多长的线路将指定节点接入线网；
    - 网状接线：保留周边骨干线路，新增至少3条连线，将目标节点与多个枢纽节点直接相连；
    - 背靠背柔性直流互联：在两个交流分区之间，插入一个特殊的节点。该节点内部不包含任何交流传输线，而是通过背靠背的整流器和逆变器相连；
    - 直流联网接线：新增一条点对点的直流传输通道。在图结构中表现为：[源端交流节点] -> [整流站] ==(直流边)==> [逆变站] -> [目标交流节点]；
    - 柔性交流装置加装：不增加图的边，而是在现有的边（线路）或节点上，串联或并联插入一个主动控制元件（如 UPFC 统一潮流控制器，或 SVC/STATCOM 静止无功发生器）；
    - 加强通道：新增线路将指定位置的节点连接到原网架中的其他节点。""",
        "calculation_formula_prompt": """(1)电抗的计算方式：电抗=线路长度*0.00001*1.2；
    (2)电阻的计算方式：电阻=线路长度*0.000095*1.2；""",
        "additional_requirements_prompt": "",
        "target_node_name": "bus0",
        "target_load_p": "0",
        "target_solution_instruction": "你需要先定位过载线路的位置，然后通过将bus0节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。",
        "iteration_solution_instruction": "请仔细研究最新问题报告，优先解决仍然存在的 N-1 过载或短路电流问题。",
    },
}


def infer_case_type_from_prompt_path(prompt_template_path, context_json_path=None):
    prompt_name = os.path.basename(str(prompt_template_path or "")).lower()
    context_name = os.path.basename(str(context_json_path or "")).lower()
    combined_name = f"{prompt_name} {context_name}"
    if "yuezhou" in combined_name:
        return "yuezhou"
    if "generic" in combined_name:
        return "generic"
    return "shuifu"


def ensure_prompt_context_fields(context, prompt_template_path, context_json_path=None):
    case_type = infer_case_type_from_prompt_path(prompt_template_path, context_json_path)
    defaults = DEFAULT_PROMPT_CONTEXT_BY_CASE[case_type]
    for key, value in defaults.items():
        context.setdefault(key, value)
    return context

# 进度报告器
class ProgressReporter:
    def __init__(self, progress_file_path):
        self.progress_file_path = progress_file_path
        self.current_stage = "INIT"
        self.current_step = 0
        self.total_steps = 0
        self.message = ""
        self.error = None
        self.logs = []
        self.generated_scheme_count = 0
        self.target_scheme_count = 0
        self.initial_analysis_complete = False
        self.analysis_reports_ready = False
        self._write_progress()
    
    def update(
        self,
        stage=None,
        step=None,
        total_steps=None,
        message=None,
        error=None,
        generated_scheme_count=None,
        target_scheme_count=None,
        initial_analysis_complete=None,
        analysis_reports_ready=None
    ):
        if stage is not None:
            self.current_stage = stage
        if step is not None:
            self.current_step = step
        if total_steps is not None:
            self.total_steps = total_steps
        if message is not None:
            self.logs.append({"time": time.strftime("%H:%M:%S"), "msg": message})
            if len(self.logs) > 50:
                self.logs = self.logs[-50:]
            self.message = message
        if error is not None:
            self.error = error
        if generated_scheme_count is not None:
            self.generated_scheme_count = generated_scheme_count
        if target_scheme_count is not None:
            self.target_scheme_count = target_scheme_count
        if initial_analysis_complete is not None:
            self.initial_analysis_complete = initial_analysis_complete
        if analysis_reports_ready is not None:
            self.analysis_reports_ready = analysis_reports_ready
        self._write_progress()
    
    def _write_progress(self):
        progress_data = {
            "stage": self.current_stage,
            "step": self.current_step,
            "total_steps": self.total_steps,
            "message": self.message,
            "error": self.error,
            "logs": self.logs[-20:],
            "generated_scheme_count": self.generated_scheme_count,
            "target_scheme_count": self.target_scheme_count,
            "initial_analysis_complete": self.initial_analysis_complete,
            "analysis_reports_ready": self.analysis_reports_ready,
            "timestamp": time.time()
        }
        try:
            os.makedirs(os.path.dirname(self.progress_file_path), exist_ok=True)
            with open(self.progress_file_path, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"写入进度文件失败: {e}")

PROGRESS_REPORTER = None

def init_progress(progress_file_path):
    global PROGRESS_REPORTER
    PROGRESS_REPORTER = ProgressReporter(progress_file_path)

def report_progress(
    stage=None,
    step=None,
    total_steps=None,
    message=None,
    error=None,
    generated_scheme_count=None,
    target_scheme_count=None,
    initial_analysis_complete=None,
    analysis_reports_ready=None
):
    global PROGRESS_REPORTER
    if PROGRESS_REPORTER:
        PROGRESS_REPORTER.update(
            stage=stage,
            step=step,
            total_steps=total_steps,
            message=message,
            error=error,
            generated_scheme_count=generated_scheme_count,
            target_scheme_count=target_scheme_count,
            initial_analysis_complete=initial_analysis_complete,
            analysis_reports_ready=analysis_reports_ready
        )

def find_related_file(base_path, extension):
    """Find a sibling file related to base_path by extension."""
    base_dir = os.path.dirname(base_path)
    stem = os.path.splitext(os.path.basename(base_path))[0]
    candidates = [
        os.path.join(base_dir, stem + extension.lower()),
        os.path.join(base_dir, stem + extension.upper()),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    pattern = os.path.join(base_dir, f"*{extension}")
    matches = glob.glob(pattern) + glob.glob(os.path.join(base_dir, f"*{extension.upper()}"))
    return matches[0] if matches else os.path.join(base_dir, stem + extension.lower())

def read_initial_scc_issues(selector, n1_report_path, default_value=13):
    """Read initial SCC issue count from the analysis report beside n1_report_path."""
    if not n1_report_path:
        print(f"⚠️ 未提供初始N-1报告，使用默认SCC问题数: {default_value}")
        return default_value

    analysis_dir = os.path.dirname(n1_report_path)
    combined_data = selector.parse_combined_reports(analysis_dir)
    if not combined_data or not combined_data.get("scc_data"):
        print(f"⚠️ 未找到初始SCC报告，使用默认SCC问题数: {default_value}")
        return default_value

    scc_issues = combined_data.get("scc_issues")
    if isinstance(scc_issues, (int, float)) and scc_issues != float('inf'):
        return int(scc_issues)

    print(f"⚠️ 初始SCC报告中未解析到问题数，使用默认SCC问题数: {default_value}")
    return default_value

def initial_analysis(base_model_path, output_dir="fulfillment_scc", skip_scc_analysis=False):
    """初始分析：对基础模型进行完整的分析"""
    report_progress(stage="INITIAL_ANALYSIS", step=0, total_steps=4, message="开始初始分析...")
    print("--- 开始初始分析 ---")
    selector = SelectionService(pf_threshold=80.0, scc_threshold=60.0)
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 复制基础模型文件到输出目录
    report_progress(message="复制基础模型文件...")
    base_model_name = os.path.basename(base_model_path)
    target_base_model = os.path.join(output_dir, "base_model", base_model_name)
    os.makedirs(os.path.dirname(target_base_model), exist_ok=True)
    
    # 复制相关文件
    base_dir = os.path.dirname(base_model_path)
    for ext in ['.dat', '.swi', '.scset']:
        src_file = base_model_path if ext == '.dat' else find_related_file(base_model_path, ext)
        if os.path.exists(src_file):
            dst_file = os.path.join(os.path.dirname(target_base_model), os.path.basename(src_file))
            shutil.copy2(src_file, dst_file)
            print(f"✅ 已复制: {os.path.basename(src_file)}")
    
    # 复制故障集文件
    lsd_src = os.path.join(base_dir, "三永N-1故障集.lsd")
    lsd_dst = os.path.join(output_dir, "base_model", "三永N-1故障集.lsd")
    if os.path.exists(lsd_src):
        shutil.copy2(lsd_src, lsd_dst)
        print(f"✅ 已复制: 三永N-1故障集.lsd")
    
    # 执行完整的分析流程
    config = load_config_as_dotdict()
    analysis_service = AnalysisService(config)
    
    # 潮流分析
    report_progress(step=1, message="执行潮流分析...")
    print("\n[1/6] 执行潮流分析...")
    pf_report_path = os.path.join(output_dir, "analysis_1", "pf_report_1.json")
    os.makedirs(os.path.dirname(pf_report_path), exist_ok=True)
    
    pf_report = analysis_service.analyze_power_flow(target_base_model, balanced_machine_output=True)
    with open(pf_report_path, 'w', encoding='utf-8') as f:
        json.dump(pf_report, f, indent=2, ensure_ascii=False)
    print("✅ 潮流分析完成")
    
    # N-1分析
    report_progress(step=2, message="执行N-1安全分析...")
    print("\n[2/6] 执行N-1分析...")
    n1_report_path = os.path.join(output_dir, "analysis_1", "n1_report_1.json")
    run_dir_for_n1 = os.path.join(output_dir, "analysis_1", "n1_intermediate_1")
    os.makedirs(os.path.dirname(n1_report_path), exist_ok=True)
    
    n1_conditions = {
        "min_voltage_kv": 500.0,
        "ckt_id": "2"
    }
    n1_report = analysis_service.analyze_n_security(target_base_model, n1_conditions, run_dir_for_n1, full_scan=True)
    with open(n1_report_path, 'w', encoding='utf-8') as f:
        json.dump(n1_report, f, indent=2, ensure_ascii=False)
    print("✅ N-1分析完成")
    
    # 获取初始scc_issues
    initial_scc_issues = 13
    if skip_scc_analysis:
        print("⏭️ 通用案例跳过短路电流分析")
    else:
        # 短路分析
        report_progress(step=3, message="执行短路电流分析...")
        print("\n[4/6] 执行短路分析...")
        scc_report_path = os.path.join(output_dir, "analysis_1", "scc_report_1.json")
        swi_file = target_base_model.replace('.dat', '.swi')
        scset_file = target_base_model.replace('.dat', '.scset')
        
        scc_report = analysis_service.analyze_short_circuit(target_base_model, swi_file, scset_file)
        with open(scc_report_path, 'w', encoding='utf-8') as f:
            json.dump(scc_report, f, indent=2, ensure_ascii=False)
        print("✅ 短路分析完成")
        initial_scc_issues = read_initial_scc_issues(selector, n1_report_path)
    
    print(f"📊 初始SCC问题数: {initial_scc_issues}")
    print(f"\n🎉 初始分析完成！所有结果已保存到: {output_dir}")

    initial_n1_issues = 0
    initial_n1_issues = n1_report["remaining_issues"]
    print(f"📊 初始N-1问题数: {initial_n1_issues}")
    
    report_progress(
        stage="ANALYSIS_READY",
        step=4,
        message=f"初始分析完成，N-1问题数: {initial_n1_issues}，SCC问题数: {initial_scc_issues}",
        initial_analysis_complete=True,
        analysis_reports_ready=True
    )
    
    return n1_report_path, initial_n1_issues, initial_scc_issues

def generation_with_selection(
    parse_target,
    prompt_template_path,
    base_model_path=None,
    version=0,
    output_dir=None,
    context_json_path=None,
    fixed_analysis_report=None,
):
    """改进的生成函数，支持前置解析功能和自定义基础模型"""
    report_progress(stage="GENERATION", message="调用AI生成规划方案...")
    print("--- 运行AI生成服务功能（改进版） ---")
    config = load_config_as_dotdict()
    service = GenerationService(config)

    # 定义输出路径
    raw_output = os.path.join(output_dir, "generation", "llm_raw_output.txt")
    parsed_output = os.path.join(output_dir, "generation", "parsed_proposals.json")

    # 读取基础上下文
    context_file = context_json_path or "powergrid_pipeline_v2/data/context_shuifu.json"
    with open(context_file, 'r', encoding='utf-8') as f:
        context = json.load(f)
    ensure_prompt_context_fields(context, prompt_template_path, context_file)
    
    # 检查解析目标是否存在。水富等固定问题场景可直接传 fixed_analysis_report。
    if fixed_analysis_report:
        context["n-1_analysis_report"] = fixed_analysis_report
    elif not parse_target:
        raise ValueError("❌ 错误: 必须提供解析目标(文件路径或目录路径)")
    elif not os.path.exists(parse_target):
        raise FileNotFoundError(f"❌ 错误: 解析目标路径不存在: {parse_target}")
    
    # 判断是文件还是目录
    is_file = os.path.isfile(parse_target) if parse_target else True
    
    try:
        # 进行前置解析
        report_progress(message="正在调用AI模型生成方案...")
        print(f"🔍 正在进行前置解析: {parse_target}")
        proposals = service.generate_and_parse(
            prompt_template_path=prompt_template_path,
            context=context,
            parse_target=None if fixed_analysis_report else parse_target,
            is_file_parse=is_file,  # 根据路径类型设置
            save_raw_output_path=raw_output
        )
        
        assert isinstance(proposals, list), "返回的不是一个列表"
        assert len(proposals) > 0, "未能解析出任何方案"
        print(f"✅ 运行通过，成功解析出 {len(proposals)} 个方案。")
        report_progress(message=f"AI生成完成，共生成 {len(proposals)} 个方案")
        
        # 保存解析结果
        os.makedirs(os.path.dirname(parsed_output), exist_ok=True)
        with open(parsed_output, 'w', encoding='utf-8') as f:
            json.dump({"proposals": proposals}, f, indent=2, ensure_ascii=False)
            
        return version

    except Exception as e:
        print(f"❌ 运行失败: {e}")
        report_progress(error=str(e), message=f"AI生成失败: {e}")
        raise

def _normalize_endpoint_name(value):
    return str(value or "").strip()

def _line_endpoint_from_branch_data(branch_data):
    if not isinstance(branch_data, dict):
        return None
    node1 = _normalize_endpoint_name(branch_data.get("NAME1"))
    node2 = _normalize_endpoint_name(branch_data.get("NAME2"))
    if not node1 or not node2:
        return None
    return tuple(sorted((node1, node2)))

def _proposal_line_endpoint_signature(proposal):
    """Return a topology signature made only from all added line endpoint pairs."""
    endpoints = []
    for modification in proposal.get("modifications", []) or []:
        if modification.get("action") != "add_line":
            continue
        params = modification.get("params", {}) or {}
        endpoint = _line_endpoint_from_branch_data(params.get("full_branch_data", {}) or {})
        if endpoint:
            endpoints.append(endpoint)

    if not endpoints:
        return None
    return tuple(sorted(endpoints))

def _signature_to_jsonable(signature):
    return [list(endpoint) for endpoint in signature] if signature else []

def _iter_selected_proposal_files(output_root):
    pattern = os.path.join(output_root, "run_*", "result", "proposal", "selected_proposal_iter*_scheme*.json")
    return sorted(glob.glob(pattern))

def _load_taken_topology_signatures(output_root):
    signatures = {}
    for proposal_path in _iter_selected_proposal_files(output_root):
        try:
            with open(proposal_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            proposal = data.get("proposal", data)
            signature = _proposal_line_endpoint_signature(proposal)
            if not signature:
                continue
            signatures.setdefault(signature, proposal_path)
        except Exception as e:
            print(f"⚠️ 读取已采用方案拓扑失败: {proposal_path}, 错误: {e}")
    return signatures

def deduplicate_generated_proposals(output_dir, output_root):
    """Drop generated proposals whose line-endpoint topology was already taken."""
    proposal_file = os.path.join(output_dir, "generation", "parsed_proposals.json")
    if not os.path.exists(proposal_file):
        raise FileNotFoundError(f"❌ 错误: 方案文件不存在: {proposal_file}")

    with open(proposal_file, 'r', encoding='utf-8') as f:
        proposal_data = json.load(f)

    proposals = proposal_data.get("proposals", []) or []
    if not proposals:
        return 0

    taken_signatures = _load_taken_topology_signatures(output_root)
    kept_proposals = []
    skipped = []

    for original_index, proposal in enumerate(proposals, start=1):
        signature = _proposal_line_endpoint_signature(proposal)
        if not signature:
            kept_proposals.append(proposal)
            continue

        duplicate_source = taken_signatures.get(signature)
        if duplicate_source:
            skipped.append({
                "original_scheme_number": original_index,
                "proposal_name": proposal.get("proposal_name", f"方案{original_index}"),
                "duplicate_of": duplicate_source,
                "line_endpoints": _signature_to_jsonable(signature),
            })
            print(
                f"⏭️ 方案 {original_index} 与已采用方案拓扑重复，跳过应用和仿真: "
                f"{_signature_to_jsonable(signature)}"
            )
            continue

        kept_proposals.append(proposal)

    if skipped:
        proposal_data["proposals"] = kept_proposals
        with open(proposal_file, 'w', encoding='utf-8') as f:
            json.dump(proposal_data, f, indent=2, ensure_ascii=False)

        report_path = os.path.join(output_dir, "generation", "dedupe_report.json")
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                "original_count": len(proposals),
                "kept_count": len(kept_proposals),
                "skipped_count": len(skipped),
                "skipped": skipped,
            }, f, indent=2, ensure_ascii=False)
        print(f"✅ 方案拓扑查重完成：保留 {len(kept_proposals)}/{len(proposals)} 个方案，报告: {report_path}")

    if not kept_proposals:
        raise ValueError("所有模型输出方案均与已采用方案拓扑重复，跳过本轮应用和仿真")

    return len(skipped)

def application(version, base_model_path=None, output_dir=None):
    """改进的应用函数，支持自定义基础模型"""
    report_progress(stage="APPLICATION", message="应用规划方案到电网模型...")
    print("--- 运行方案应用服务功能 ---")
    service = ApplicationService()

    # 定义输入输出路径
    proposal_file = os.path.join(output_dir, "generation", "parsed_proposals.json")
    
    
    # 检查方案文件是否存在
    if not os.path.exists(proposal_file):
        raise FileNotFoundError(f"❌ 错误: 方案文件不存在: {proposal_file}")
    
    # 使用指定的基础模型或默认基础模型
    if base_model_path:
        base_model = base_model_path
        # 检查基础模型文件是否存在
        if not os.path.exists(base_model):
            raise FileNotFoundError(f"❌ 错误: 基础模型文件不存在: {base_model}")
        
        # 从基础模型路径推断其他文件路径
        base_dir = os.path.dirname(base_model_path)
        swi_file = find_related_file(base_model_path, ".swi")
        scset_file = find_related_file(base_model_path, ".scset")
        lsd_file = os.path.join(base_dir, "三永N-1故障集.lsd")
        
        # 检查相关文件是否存在
        for file_path, file_name in [(swi_file, "swi文件"), (scset_file, "scset文件"), (lsd_file, "lsd文件")]:
            if not os.path.exists(file_path):
                print(f"⚠️ 警告: {file_name}不存在: {file_path}")
    else:
        base_model = "powergrid_pipeline_v2/data/base_models/yunnan_base.dat"
        swi_file = "powergrid_pipeline_v2/data/base_models/yunnan_base.swi"
        scset_file = "powergrid_pipeline_v2/data/base_models/yunnan_base.scset"
        lsd_file = "powergrid_pipeline_v2/data/base_models/三永N-1故障集.lsd"
        
        # 检查默认文件是否存在
        for file_path, file_name in [(base_model, "基础模型"), (swi_file, "swi文件"), 
                                   (scset_file, "scset文件"), (lsd_file, "lsd文件")]:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"❌ 错误: {file_name}不存在: {file_path}")
    
    output_model = os.path.join(output_dir, "application")

    # --- 运行应用 ---
    print("\n[1/1] 运行 apply...")
    with open(proposal_file, 'r', encoding='utf-8') as f:
        proposal = json.load(f)
        
    success, msg = service.apply_all_proposals(proposal, base_model, swi_file, scset_file, lsd_file, output_model)
    
    assert success, f"应用方案失败: {msg}"
    assert os.path.exists(output_model)
    
    print("✅ 运行通过，新模型已生成并验证。")
    print("\n--- 所有方案应用服务运行完成 ---")
    report_progress(message="方案应用完成，新模型已生成")

def _extract_target_line_from_text(text):
    """
    从文本中提取目标线路信息
    
    Args:
        text: 包含目标线路信息的文本，如 "连接节点\"滇溪右50\"和节点\"滇牛寨51\"的线路存在过载问题。"
    
    Returns:
        dict: 目标线路信息 {"node1": "节点1", "node2": "节点2"} 或 None
    """
    if not text:
        return None
    
    import re
    pattern = r'连接节点["\']([^"\']+)["\']和节点["\']([^"\']+)["\']'
    match = re.search(pattern, text)
    if match:
        return {
            "node1": match.group(1),
            "node2": match.group(2)
        }
    
    return None

def _extract_target_line_from_context(context_json_path):
    """
    从 context.json 中提取目标线路信息
    
    Args:
        context_json_path: context.json 文件路径
    
    Returns:
        dict: 目标线路信息 {"node1": "节点1", "node2": "节点2"} 或 None
    """
    if not context_json_path or not os.path.exists(context_json_path):
        return None
    
    try:
        with open(context_json_path, 'r', encoding='utf-8') as f:
            context_data = json.load(f)
        
        n1_report = context_data.get("n-1_analysis_report", "")
        return _extract_target_line_from_text(n1_report)
    except Exception as e:
        print(f"⚠️ 提取目标线路信息失败: {e}")
        return None

def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _normalize_ckt_id(value):
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text

def _is_first_circuit(ckt_id):
    return _normalize_ckt_id(ckt_id) in ("", "1")

def _branch_compare_key(branch_info):
    name1 = str(branch_info.get("NAME1") or "").strip()
    name2 = str(branch_info.get("NAME2") or "").strip()
    ckt = _normalize_ckt_id(branch_info.get("CKT ID"))
    endpoints = tuple(sorted([name1, name2]))
    return endpoints[0], endpoints[1], ckt

def _branch_line_group_key(branch_info):
    name1 = str(branch_info.get("NAME1") or "").strip()
    name2 = str(branch_info.get("NAME2") or "").strip()
    endpoints = tuple(sorted([name1, name2]))
    return endpoints[0], endpoints[1]

def _collect_line_branches(dat_path, min_voltage_kv=500.0):
    from pybpa.dat.bpa_dat import DAT

    dat = DAT.build_from(dat_path, True)
    branches = []
    for branch in dat.branch:
        if str(branch.get_value('TYPE', '')).strip() != 'L':
            continue

        base1 = _as_float(branch.get_value('BASE1'))
        base2 = _as_float(branch.get_value('BASE2'))
        if base1 < min_voltage_kv or base2 < min_voltage_kv:
            continue

        branches.append({
            "NAME1": str(branch.get_value('NAME1', '')).strip(),
            "NAME2": str(branch.get_value('NAME2', '')).strip(),
            "CKT ID": _normalize_ckt_id(branch.get_value('CKT ID')),
            "BASE1": base1,
            "BASE2": base2,
        })
    return branches

def _get_added_non_first_circuit_lines(base_dat_path, applied_dat_path, min_voltage_kv=500.0):
    """Return lines newly added by a proposal whose circuit ID is not 1."""
    if not base_dat_path or not os.path.exists(base_dat_path):
        return []
    if not applied_dat_path or not os.path.exists(applied_dat_path):
        return []

    try:
        base_keys = {
            _branch_compare_key(branch)
            for branch in _collect_line_branches(base_dat_path, min_voltage_kv=min_voltage_kv)
        }
        added_lines = []
        seen_line_groups = set()
        for branch in _collect_line_branches(applied_dat_path, min_voltage_kv=min_voltage_kv):
            key = _branch_compare_key(branch)
            line_group_key = _branch_line_group_key(branch)
            if key in base_keys or line_group_key in seen_line_groups:
                continue
            if _is_first_circuit(branch.get("CKT ID")):
                continue
            seen_line_groups.add(line_group_key)

            added_lines.append({
                "node1": branch.get("NAME1"),
                "node2": branch.get("NAME2"),
                "ckt": branch.get("CKT ID"),
                "reason": "新增非一回线路"
            })

        if added_lines:
            line_labels = [f"{line['node1']} - {line['node2']} (CKT={line['ckt']})" for line in added_lines]
            print(f"  🎯 新增非一回线路前置检测对象: {line_labels}")
        return added_lines
    except Exception as e:
        print(f"⚠️ 识别新增非一回线路失败: {e}")
        return []

def _read_n1_issue_count(n1_report_path):
    with open(n1_report_path, 'r', encoding='utf-8') as f:
        report = json.load(f)
    return report.get("remaining_issues", 0), report

def _run_final_full_n1_validation(best_scheme_info, acceptable_n1_issues=0, enable_transient_analysis=False):
    """Run a complete all-network N-1 scan before accepting a final scheme."""
    if not best_scheme_info:
        return False

    scheme_number = best_scheme_info.get("scheme_number")
    dat_file = best_scheme_info.get("model_path")
    analysis_dir = best_scheme_info.get("analysis_dir")
    if not scheme_number or not dat_file or not analysis_dir:
        print("⚠️ 最终N-1复核缺少方案编号、模型路径或分析目录")
        return False

    n1_report_path = os.path.join(analysis_dir, f"n1_report_{scheme_number}.json")
    run_dir_for_n1 = os.path.join(analysis_dir, f"n1_final_full_{scheme_number}")
    print(f"🔁 方案 {scheme_number} 进入最终确认：执行一次完整全网N-1复核...")
    analysis_n1(dat_file, run_dir_for_n1, n1_report_path, full_scan=True)

    n1_issues, final_report = _read_n1_issue_count(n1_report_path)
    best_scheme_info["n1_issues"] = n1_issues
    best_scheme_info["total_issues"] = n1_issues + best_scheme_info.get("scc_issues", 0)
    best_scheme_info["final_n1_report_path"] = n1_report_path
    best_scheme_info["final_n1_total_contingencies_run"] = final_report.get("total_contingencies_run", 0)

    if n1_issues <= acceptable_n1_issues:
        if not enable_transient_analysis:
            best_scheme_info["transient_verified"] = False
            best_scheme_info["transient_skipped"] = True
            best_scheme_info["final_n1_verified"] = True
            print(f"✅ 方案 {scheme_number} 最终全网N-1问题数满足阈值，未启用暂态分析，正式选定")
            return True

        transient_report_path = os.path.join(analysis_dir, f"transient_report_{scheme_number}.json")
        swi_file = find_related_file(dat_file, ".swi")
        lsd_file = find_related_file(dat_file, ".lsd")
        print(f"🔁 方案 {scheme_number} 最终全网N-1复核问题数 {n1_issues} <= {acceptable_n1_issues}，继续执行暂态N-1分析...")
        try:
            transient_passed = analysis_transient(dat_file, swi_file, lsd_file, transient_report_path)
        except Exception as e:
            transient_passed = False
            best_scheme_info["transient_error"] = str(e)
            print(f"⚠️ 方案 {scheme_number} 暂态分析执行失败: {e}")

        best_scheme_info["transient_msg_report_path"] = _transient_msg_report_path(transient_report_path)
        best_scheme_info["transient_verified"] = transient_passed
        if transient_passed:
            best_scheme_info["final_n1_verified"] = True
            print(f"✅ 方案 {scheme_number} 最终全网N-1问题数满足阈值且暂态分析通过，正式选定")
            return True

        best_scheme_info["final_n1_verified"] = False
        print(f"⚠️ 方案 {scheme_number} 暂态分析未通过，MSG异常摘要报告: {_transient_msg_report_path(transient_report_path)}，继续迭代")
        return False

    best_scheme_info["final_n1_verified"] = False
    best_scheme_info["final_n1_new_issues"] = True
    print(f"⚠️ 方案 {scheme_number} 最终全网N-1复核发现 {n1_issues} 个问题，超过允许阈值 {acceptable_n1_issues}，已记录到 {n1_report_path}，继续迭代")
    return False

def _target_line_from_contingency_info(contingency_info):
    if not contingency_info:
        return None

    overloaded_line = contingency_info.get("overloaded_line") or {}
    node1 = overloaded_line.get("线路端点1")
    node2 = overloaded_line.get("线路端点2")
    if node1 and node2:
        return {"node1": node1, "node2": node2}

    node1 = contingency_info.get("node1")
    node2 = contingency_info.get("node2")
    if node1 and node2 and "未知" not in node1 and "未知" not in node2:
        return {"node1": node1, "node2": node2}

    return None

def _extract_target_line_from_n1_report_file(n1_report_path):
    if not n1_report_path or not os.path.exists(n1_report_path):
        return None

    try:
        selector = SelectionService(pf_threshold=80.0, scc_threshold=60.0)
        return _target_line_from_contingency_info(selector.get_first_contingency_info(n1_report_path))
    except Exception as e:
        print(f"⚠️ 从N-1报告提取目标线路失败: {e}")
        return None

def _get_applied_scheme_numbers(output_dir):
    """Return scheme numbers that have generated applied DAT files."""
    application_dir = os.path.join(output_dir, "application")
    pattern = os.path.join(application_dir, "method_*", "applied_model_*.dat")
    scheme_numbers = []

    for dat_file in glob.glob(pattern):
        method_name = os.path.basename(os.path.dirname(dat_file))
        if not method_name.startswith("method_"):
            continue

        try:
            scheme_number = int(method_name.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            continue

        expected_name = f"applied_model_{scheme_number}.dat"
        if os.path.basename(dat_file) == expected_name:
            scheme_numbers.append(scheme_number)

    scheme_numbers = sorted(set(scheme_numbers))
    if not scheme_numbers:
        print(f"⚠️ 未找到可分析的方案文件: {pattern}")
    else:
        print(f"📋 本轮可分析方案数: {len(scheme_numbers)}，方案编号: {scheme_numbers}")

    return scheme_numbers

def delete_scheme_artifacts(output_dir, scheme_number, reason=""):
    """Delete one infeasible candidate's analysis_* and application/method_* folders."""
    paths = [
        os.path.join(output_dir, f"analysis_{scheme_number}"),
        os.path.join(output_dir, "application", f"method_{scheme_number}"),
    ]
    removed = []
    for folder in paths:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
                removed.append(folder)
            except Exception as e:
                print(f"⚠️ 删除不可行方案目录失败: {folder}, 错误: {e}")

    if removed:
        suffix = f"，原因: {reason}" if reason else ""
        print(f"🗑️ 已删除不可行方案 {scheme_number} 的相关文件夹{suffix}")
    return removed

def run_analysis_for_iteration(version, previous_best_issues=3, output_dir=None, context_json_path=None, target_line=None, base_model_path=None, skip_scc_analysis=False):
    """为指定迭代轮次运行分析
    
    Args:
        target_line: 目标线路信息 {"node1": "节点1", "node2": "节点2"}，如果提供则优先检测该线路的N-1
    """
    report_progress(stage="ANALYSIS", message=f"执行第 {version} 轮分析评估...")
    selector = SelectionService(pf_threshold=80.0, scc_threshold=60.0)
    
    # 如果没有直接提供 target_line，尝试从 context.json 中提取
    if not target_line and context_json_path:
        target_line = _extract_target_line_from_context(context_json_path)
    
    if target_line:
        print(f"🎯 目标线路: {target_line['node1']} - {target_line['node2']}")

    if not os.path.exists(output_dir):
        raise FileNotFoundError(f"❌ 错误: 输出目录不存在: {output_dir}")
    
    for i in _get_applied_scheme_numbers(output_dir):
        dat_file = f"{output_dir}/application/method_{i}/applied_model_{i}.dat"
        method_dir = os.path.dirname(dat_file)
        swi_file = find_related_file(dat_file, ".swi")
        scset_file = find_related_file(dat_file, ".scset")
        
        pf_report_path = f"{output_dir}/analysis_{i}/pf_report_{i}.json"
        n1_report_path = f"{output_dir}/analysis_{i}/n1_report_{i}.json"
        scc_report_path = f"{output_dir}/analysis_{i}/scc_report_{i}.json"
        
        run_dir_for_n1 = f"{output_dir}/analysis_{i}/n1_intermediate_{i}"
        
        os.makedirs(os.path.dirname(pf_report_path), exist_ok=True)
        
        if not os.path.exists(dat_file):
            print(f"⚠️ 警告: 数据文件不存在，跳过分析: {dat_file}")
            delete_scheme_artifacts(output_dir, i, "数据文件不存在")
            continue
        
        analysis_powerflow(dat_file, pf_report_path)

        pf_data = {}
        if pf_report_path:
            pf_data = selector.parse_pf_report(pf_report_path)
            if not pf_data["is_convergent"]:
                print("潮流分析报告存在错误")
                delete_scheme_artifacts(output_dir, i, "潮流不收敛")
                continue
            else:
                priority_lines = _get_added_non_first_circuit_lines(base_model_path, dat_file)
                analysis_n1(
                    dat_file,
                    run_dir_for_n1,
                    n1_report_path,
                    target_line=target_line,
                    priority_lines=priority_lines,
                    early_stop_issue_limit=previous_best_issues,
                )
                if skip_scc_analysis:
                    print(f"⏭️ 方案 {i} 跳过短路电流分析")
                else:
                    analysis_scc(dat_file, swi_file, scset_file, scc_report_path)
                analysis_dir = f"{output_dir}/analysis_{i}"
                n1_pattern = os.path.join(analysis_dir, "n1_report_*.json")
                n1_files = glob.glob(n1_pattern)
                if not n1_files:
                    print(f"❌ 在目录 {analysis_dir} 中未找到N-1报告文件")
                    delete_scheme_artifacts(output_dir, i, "未生成N-1报告")
                    continue
                n1_data = selector.parse_n1_report(n1_files[0])
                if n1_data.get("precheck_failed"):
                    reason = n1_data.get("precheck_failed_reason") or "前置N-1检测存在问题"
                    print(f"⏭️ 方案 {i} {reason}N-1存在问题，舍弃此方案")
                    delete_scheme_artifacts(output_dir, i, f"{reason}N-1存在问题")
                    continue
                if n1_data.get("screening_discarded"):
                    print(f"⏭️ 方案 {i} 简易N-1抽样全部存在问题，舍弃此方案")
                    delete_scheme_artifacts(output_dir, i, "简易N-1抽样全部存在问题")
                    continue
                n1_issues = n1_data.get("remaining_issues", 0)
                
                if n1_issues > previous_best_issues:
                    print(f"⚠️ 方案 {i} N-1问题数({n1_issues})大于原先问题数({previous_best_issues})，跳过此方案")
                    delete_scheme_artifacts(output_dir, i, f"N-1问题数增加: {n1_issues}>{previous_best_issues}")
                    continue
                
                if n1_issues < previous_best_issues:
                    break

def _node_pair_matches(text, node_pair):
    if not node_pair:
        return False
    node1, node2 = node_pair
    return node1 in text and node2 in text

def _target_overload_resolved(n1_report_path, node_pair):
    if not node_pair:
        return False
    try:
        with open(n1_report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
    except Exception as e:
        print(f"⚠️ 无法读取N-1报告以判断目标问题是否解决: {e}")
        return False

    contingencies = report.get("contingencies_with_issues", []) or []
    for contingency in contingencies:
        branch_uid = str(contingency.get("contingency_branch_uid", ""))
        if _node_pair_matches(branch_uid, node_pair):
            return False
        overloaded_lines = contingency.get("result", {}).get("analysis", {}).get("overloaded_lines", []) or []
        for line in overloaded_lines:
            line_text = json.dumps(line, ensure_ascii=False)
            if _node_pair_matches(line_text, node_pair):
                return False
    return True

def _get_related_overloaded_lines(n1_report_path, related_nodes):
    """
    获取与指定节点相关的过载线路列表
    
    Args:
        n1_report_path: N-1报告文件路径
        related_nodes: 相关节点列表，如 ["滇水富51", "滇牛寨51", "滇溪右50"]
    
    Returns:
        list: 与指定节点相关的过载线路列表
    """
    if not related_nodes:
        return []
    
    try:
        with open(n1_report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
    except Exception as e:
        print(f"⚠️ 无法读取N-1报告以获取相关过载线路: {e}")
        return []
    
    related_overloads = []
    contingencies = report.get("contingencies_with_issues", []) or []
    
    for contingency in contingencies:
        overloaded_lines = contingency.get("result", {}).get("analysis", {}).get("overloaded_lines", []) or []
        for line in overloaded_lines:
            node1 = line.get("线路端点1", "")
            node2 = line.get("线路端点2", "")
            if node1 in related_nodes or node2 in related_nodes:
                related_overloads.append({
                    "contingency_branch_uid": contingency.get("contingency_branch_uid", ""),
                    "overloaded_line": line,
                    "node1": node1,
                    "node2": node2
                })
    
    return related_overloads

def _generate_overload_report_text(overload_info):
    """
    根据过载线路信息生成报告文本
    """
    if not overload_info:
        return ""
    
    line = overload_info.get("overloaded_line", {})
    node1 = overload_info.get("node1", "")
    node2 = overload_info.get("node2", "")
    contingency_uid = overload_info.get("contingency_branch_uid", "")
    
    current_ratio = line.get("电流比例(%)", 0)
    current = line.get("电流(A)", 0)
    rated_current = line.get("额定电流(A)", 0)
    
    report = (
        f"在N-1故障场景（断开{contingency_uid}）下，"
        f"连接节点\"{node1}\"和节点\"{node2}\"的线路存在过载问题，"
        f"电流为{current:.2f}A，额定电流为{rated_current:.2f}A，"
        f"电流比例为{current_ratio:.2f}%，超过80%的阈值。"
    )
    
    return report

def _check_all_related_overloads_resolved(n1_report_path, related_nodes):
    """
    检查与指定节点相关的所有过载是否已解决
    
    Returns:
        tuple: (是否全部解决, 未解决的过载列表)
    """
    if not related_nodes:
        return True, []
    
    remaining_overloads = _get_related_overloaded_lines(n1_report_path, related_nodes)
    return len(remaining_overloads) == 0, remaining_overloads

def run_analysis_until_target_resolved(version, output_dir=None, target_node_pair=None, context_json_path=None, target_line=None, base_model_path=None, previous_best_issues=float('inf'), skip_scc_analysis=False):
    """Analyze all candidates and return the best one that resolves the target overload.
    
    Args:
        target_line: 目标线路信息 {"node1": "节点1", "node2": "节点2"}，如果提供则优先检测该线路的N-1
        previous_best_issues: 原先的N-1问题数，如果当前方案的N-1问题数大于这个值，则跳过此方案
    
    Returns:
        int: 解决目标线路过载问题的最优方案编号，如果没有则返回None
    """
    report_progress(stage="ANALYSIS", message=f"执行第 {version} 轮分析评估...")
    
    # 如果没有直接提供 target_line，尝试从 context.json 中提取
    if not target_line and context_json_path:
        target_line = _extract_target_line_from_context(context_json_path)
    
    if target_line:
        print(f"🎯 目标线路: {target_line['node1']} - {target_line['node2']}")
    
    if not os.path.exists(output_dir):
        raise FileNotFoundError(f"❌ 错误: 输出目录不存在: {output_dir}")

    best_resolved_scheme = None
    best_resolved_issues = float('inf')

    for i in _get_applied_scheme_numbers(output_dir):
        dat_file = f"{output_dir}/application/method_{i}/applied_model_{i}.dat"
        swi_file = find_related_file(dat_file, ".swi")
        scset_file = find_related_file(dat_file, ".scset")

        pf_report_path = f"{output_dir}/analysis_{i}/pf_report_{i}.json"
        n1_report_path = f"{output_dir}/analysis_{i}/n1_report_{i}.json"
        scc_report_path = f"{output_dir}/analysis_{i}/scc_report_{i}.json"
        run_dir_for_n1 = f"{output_dir}/analysis_{i}/n1_intermediate_{i}"

        os.makedirs(os.path.dirname(pf_report_path), exist_ok=True)
        if not os.path.exists(dat_file):
            print(f"⚠️ 警告: 数据文件不存在，跳过分析: {dat_file}")
            delete_scheme_artifacts(output_dir, i, "数据文件不存在")
            continue

        analysis_powerflow(dat_file, pf_report_path)
        priority_lines = _get_added_non_first_circuit_lines(base_model_path, dat_file)
        analysis_n1(
            dat_file,
            run_dir_for_n1,
            n1_report_path,
            target_line=target_line,
            priority_lines=priority_lines,
            early_stop_issue_limit=previous_best_issues,
        )
        if skip_scc_analysis:
            print(f"⏭️ 方案 {i} 跳过短路电流分析")
        else:
            analysis_scc(dat_file, swi_file, scset_file, scc_report_path)
        
        try:
            with open(n1_report_path, 'r', encoding='utf-8') as f:
                n1_report = json.load(f)
            if n1_report.get("precheck_failed"):
                reason = n1_report.get("precheck_failed_reason") or "前置N-1检测存在问题"
                print(f"⏭️ 方案 {i} {reason}N-1存在问题，舍弃此方案")
                delete_scheme_artifacts(output_dir, i, f"{reason}N-1存在问题")
                continue
            if n1_report.get("screening_discarded"):
                print(f"⏭️ 方案 {i} 简易N-1抽样全部存在问题，舍弃此方案")
                delete_scheme_artifacts(output_dir, i, "简易N-1抽样全部存在问题")
                continue
            n1_issues = n1_report.get("remaining_issues", 0)
            
            if n1_issues > previous_best_issues:
                print(f"⚠️ 方案 {i} N-1问题数({n1_issues})大于原先问题数({previous_best_issues})，跳过此方案")
                delete_scheme_artifacts(output_dir, i, f"N-1问题数增加: {n1_issues}>{previous_best_issues}")
                continue
        except Exception as e:
            print(f"⚠️ 无法读取N-1报告: {e}")
            delete_scheme_artifacts(output_dir, i, "无法读取N-1报告")
            continue

        if _target_overload_resolved(n1_report_path, target_node_pair):
            print(f"✅ 方案 {i} 已解决目标线路过载问题")
            try:
                with open(n1_report_path, 'r', encoding='utf-8') as f:
                    n1_report = json.load(f)
                n1_issues = n1_report.get("remaining_issues", 0)
                if n1_issues < best_resolved_issues:
                    best_resolved_issues = n1_issues
                    best_resolved_scheme = i
            except:
                best_resolved_scheme = i
        else:
            print(f"⚠️ 方案 {i} 未解决目标线路过载问题，舍弃此方案")
            delete_scheme_artifacts(output_dir, i, "未解决目标线路过载问题")

    if best_resolved_scheme:
        print(f"🏆 最优方案: 方案 {best_resolved_scheme} (N-1问题数: {best_resolved_issues})")
    return best_resolved_scheme

def run_iterative_improvement_with_initial_analysis(
    base_model_path,
    n1_report_path,
    prompt_template_path,
    max_iterations=10,
    max_same_count=2,
    initial_scc_issues=13,
    run=1,
    context_json_path=None,
    iteration_prompt_template_path=None,
    output_root="fulfillment_scc",
    fixed_analysis_report=None,
    target_overload_nodes=None,
    related_nodes=None,
    skip_scc_analysis=False,
    acceptable_n1_issues=0,
    enable_transient_analysis=False,
):
    """运行包含初始分析的迭代改进流程，返回最终最优方案信息
    
    Args:
        related_nodes: 相关节点列表，如 ["滇水富51", "滇牛寨51", "滇溪右50"]
                      用于检查与这些节点相关的线路过载
    """
    selector = SelectionService(pf_threshold=80.0, scc_threshold=60.0)
    previous_best_issues = float('inf')
    same_issues_count = 0
    
    # 检查基础模型文件是否存在
    if not os.path.exists(base_model_path):
        raise FileNotFoundError(f"❌ 错误: 基础模型文件不存在: {base_model_path}")
    
    if not n1_report_path or not os.path.exists(n1_report_path):
        if n1_report_path:
            print(f"⚠️ 警告: N-1报告文件不存在，将执行初始分析: {n1_report_path}")
        else:
            print(f"⚠️ 未提供N-1报告路径，将执行初始分析...")
        n1_report_path, previous_best_issues, initial_scc_issues = initial_analysis(
            base_model_path,
            output_root,
            skip_scc_analysis=skip_scc_analysis,
        )
    else:
        print(f"✅ 使用已有的N-1报告: {n1_report_path}")
        selector = SelectionService(pf_threshold=80.0, scc_threshold=60.0)
        n1_data = selector.parse_n1_report(n1_report_path)
        previous_best_issues = n1_data.get("remaining_issues", 0)
        initial_scc_issues = read_initial_scc_issues(selector, n1_report_path, initial_scc_issues)
        print(f"📊 从N-1报告中读取初始问题数: {previous_best_issues}")
    
    print(f"📊 记录初始N-1问题数: {previous_best_issues}")
    print(f"📊 记录初始SCC问题数: {initial_scc_issues}")
    
    # 检查prompt模板是否存在
    if not os.path.exists(prompt_template_path):
        raise FileNotFoundError(f"❌ 错误: Prompt模板文件不存在: {prompt_template_path}")
    
    # 在第0轮迭代前，将 fixed_analysis_report 写入 context.json
    # 这样后续分析可以从中提取目标线路信息
    if fixed_analysis_report and context_json_path:
        try:
            with open(context_json_path, 'r', encoding='utf-8') as f:
                context_data = json.load(f)
            context_data["n-1_analysis_report"] = fixed_analysis_report
            with open(context_json_path, 'w', encoding='utf-8') as f:
                json.dump(context_data, f, indent=2, ensure_ascii=False)
            print(f"📝 已将 fixed_analysis_report 写入 context.json")
        except Exception as e:
            print(f"⚠️ 写入 context.json 失败: {e}")
    
    # 提取目标线路信息（用于N-1分析优化）
    target_line = None
    if fixed_analysis_report:
        target_line = _extract_target_line_from_text(fixed_analysis_report)
    if not target_line and context_json_path:
        target_line = _extract_target_line_from_context(context_json_path)
    if not target_line:
        target_line = _extract_target_line_from_n1_report_file(n1_report_path)
    if target_line:
        print(f"🎯 目标线路: {target_line['node1']} - {target_line['node2']}")
    
    # 第0轮：基于初始分析结果生成方案
    print(f"\n{'='*60}")
    print(f"🔄 第 0 轮迭代改进")
    print(f"{'='*60}")
    
    # 使用初始分析结果生成方案
    current_version = 0
    current_output_dir = f"{output_root}/run_{run}/test_output_v{current_version}"
    generation_with_selection(
        parse_target=n1_report_path,
        prompt_template_path=prompt_template_path,
        base_model_path=base_model_path,
        version=current_version,
        output_dir=current_output_dir,
        context_json_path=context_json_path,
        fixed_analysis_report=fixed_analysis_report,
    )
    deduplicate_generated_proposals(current_output_dir, output_root)
    
    # 应用方案
    application(current_version, base_model_path=base_model_path, output_dir=current_output_dir)
    
    # 执行分析
    resolved_scheme_number = None
    if target_overload_nodes:
        resolved_scheme_number = run_analysis_until_target_resolved(
            current_version,
            output_dir=current_output_dir,
            target_node_pair=target_overload_nodes,
            context_json_path=context_json_path,
            target_line=target_line,
            base_model_path=base_model_path,
            previous_best_issues=previous_best_issues,
            skip_scc_analysis=skip_scc_analysis,
        )
    else:
        run_analysis_for_iteration(
            current_version, 
            previous_best_issues=previous_best_issues, 
            output_dir=current_output_dir,
            context_json_path=context_json_path,
            target_line=target_line,
            base_model_path=base_model_path,
            skip_scc_analysis=skip_scc_analysis,
        )
    
    # 使用SelectionService的evaluate_iteration_termination函数评估第0轮
    evaluation_result = selector.evaluate_iteration_termination(
        current_version=current_version,
        previous_best_issues=previous_best_issues,
        same_issues_count=same_issues_count,
        max_same_count=max_same_count,
        initial_scc_issues=initial_scc_issues,
        base_model_path=base_model_path,
        dir=f"{output_root}/run_{run}"
    )
    if resolved_scheme_number:
        evaluation_result["best_scheme_number"] = resolved_scheme_number
        evaluation_result["terminate"] = True
        evaluation_result["termination_reason"] = "目标线路过载问题已解决"
    
    # 获取最优方案信息
    best_scheme_info = selector.get_scheme_detailed_info(
        analysis_root=current_output_dir,
        scheme_number=evaluation_result["best_scheme_number"],
        initial_scc_issues=initial_scc_issues
    )
    
    if not best_scheme_info:
        print("❌ 无法获取最优方案详细信息，终止迭代")
        return None
    if resolved_scheme_number:
        best_scheme_info["target_resolved"] = True
        if best_scheme_info.get("n1_issues", 0) != 0:
            print("ℹ️ 目标问题已解决，但候选N-1筛选仍发现问题，继续迭代")
            evaluation_result["terminate"] = False
            evaluation_result["termination_reason"] = None
    
    if best_scheme_info["n1_issues"] > 50:
        print(f"⚠️ 第0轮最优方案N-1问题数过多 ({best_scheme_info['n1_issues']}), 可能无法改进，终止迭代")
        return None
    
    # 更新状态
    previous_best_issues = best_scheme_info["n1_issues"]
    same_issues_count = evaluation_result.get("same_issues_count", 0)
    
    # 检查相关节点过载是否已解决（第0轮）
    if related_nodes:
        best_n1_report_path = f"{best_scheme_info.get('analysis_dir')}/n1_report_{best_scheme_info['scheme_number']}.json"
        all_resolved, remaining_overloads = _check_all_related_overloads_resolved(best_n1_report_path, related_nodes)
        
        if all_resolved:
            print(f"✅ 所有相关节点过载问题已解决！")
            best_scheme_info["all_related_resolved"] = True
        elif remaining_overloads:
            print(f"⚠️ 仍有 {len(remaining_overloads)} 条相关节点线路过载")
            first_overload = remaining_overloads[0]
            overload_report = _generate_overload_report_text(first_overload)
            print(f"   下一条待处理过载: {first_overload['node1']} - {first_overload['node2']}")
            
            if context_json_path:
                with open(context_json_path, 'r', encoding='utf-8') as f:
                    context_data = json.load(f)
                context_data["n-1_analysis_report"] = overload_report
                with open(context_json_path, 'w', encoding='utf-8') as f:
                    json.dump(context_data, f, indent=2, ensure_ascii=False)
                print(f"   已更新 context.json 中的 n-1_analysis_report")

    final_validation_passed = False
    candidate_ready_for_final = best_scheme_info.get("n1_issues", 0) <= acceptable_n1_issues
    if candidate_ready_for_final:
        final_validation_passed = _run_final_full_n1_validation(
            best_scheme_info,
            acceptable_n1_issues=acceptable_n1_issues,
            enable_transient_analysis=enable_transient_analysis,
        )
        if not final_validation_passed:
            previous_best_issues = best_scheme_info["n1_issues"]
            same_issues_count = 0
            evaluation_result["terminate"] = False
            evaluation_result["termination_reason"] = None
    
    promoted_candidate_infos = []
    if final_validation_passed:
        promoted_candidate_infos = promote_later_simple_n1_candidates(
            current_output_dir,
            best_scheme_info["scheme_number"],
            run,
            output_root,
            selector,
            initial_scc_issues,
            acceptable_n1_issues,
            enable_transient_analysis=enable_transient_analysis,
        )
        best_scheme_info["promoted_candidate_infos"] = promoted_candidate_infos

    # 保存选中的方案到结果目录
    save_selected_proposal(best_scheme_info["scheme_number"], current_version, run, output_root=output_root)
    
    # 删除非最优方案的文件
    cleanup_other_schemes(current_version, best_scheme_info["scheme_number"], run, output_root=output_root)
    
    selector.adjust_generator_for_best_scheme(current_output_dir)

    if final_validation_passed:
        return best_scheme_info
    
    # 终止条件（第0轮）：保留原来的终止条件
    if evaluation_result["terminate"]:
        print(f"❌ 第0轮迭代终止: {evaluation_result.get('termination_reason', '未知原因')}")
        return None

    print(f"✅ 第 0 轮迭代完成，选择方案 {best_scheme_info['scheme_number']}: N-1问题数={best_scheme_info['n1_issues']}, SCC问题数={best_scheme_info['scc_issues']}")

    # 第1轮到最大迭代轮次
    final_iteration = 0
    for iteration in range(1, max_iterations + 1):
        print(f"\n{'='*60}")
        print(f"🔄 第 {iteration} 轮迭代改进")
        print(f"{'='*60}")
        
        # 基于最优方案进行改进
        print(f"📋 基于方案{best_scheme_info['scheme_number']}的分析结果进行改进")
        
        # 使用SelectionService获取第一个故障实例信息
        if best_scheme_info["n1_issues"] != 0:
            report_file = f"{best_scheme_info.get('analysis_dir')}/n1_report_{best_scheme_info['scheme_number']}.json"
        else:
            report_file = f"{best_scheme_info.get('analysis_dir')}/scc_report_{best_scheme_info['scheme_number']}.json"
        
        first_contingency = selector.get_first_contingency_info(report_file)
        iteration_target_line = _target_line_from_contingency_info(first_contingency)
        
        if first_contingency:
            print(f"🔧 将针对线路 {first_contingency['branch_uid']} 进行优化")
        if iteration_target_line:
            print(f"🎯 本轮前置N-1检测目标线路: {iteration_target_line['node1']} - {iteration_target_line['node2']}")
        
        # 运行新版本的生成和应用
        current_version = iteration
        current_output_dir = f"{output_root}/run_{run}/test_output_v{current_version}"
        iteration_prompt = iteration_prompt_template_path or "powergrid_pipeline_v2/data/prompts/generate_solution_n1_iteration.txt"
        generation_with_selection(
            parse_target=report_file,
            prompt_template_path=iteration_prompt,
            base_model_path=best_scheme_info.get("model_path"),
            version=current_version,
            output_dir=current_output_dir,
            context_json_path=context_json_path,
            fixed_analysis_report=None,
        )
        deduplicate_generated_proposals(current_output_dir, output_root)
        application(current_version, base_model_path=best_scheme_info.get("model_path"), output_dir=current_output_dir)
        
        # 执行分析（后续迭代中从 context.json 提取最新的目标线路）
        resolved_scheme_number = None
        if target_overload_nodes:
            resolved_scheme_number = run_analysis_until_target_resolved(
                current_version,
                output_dir=current_output_dir,
                target_node_pair=target_overload_nodes,
                context_json_path=context_json_path,
                target_line=iteration_target_line,
                base_model_path=best_scheme_info.get("model_path"),
                previous_best_issues=previous_best_issues,
                skip_scc_analysis=skip_scc_analysis,
            )
        else:
            run_analysis_for_iteration(
                current_version, 
                previous_best_issues=previous_best_issues, 
                output_dir=current_output_dir,
                context_json_path=context_json_path,
                target_line=iteration_target_line,
                base_model_path=best_scheme_info.get("model_path"),
                skip_scc_analysis=skip_scc_analysis,
            )
        
        # 使用SelectionService的evaluate_iteration_termination函数评估当前轮次
        evaluation_result = selector.evaluate_iteration_termination(
            current_version=current_version,
            previous_best_issues=previous_best_issues,
            same_issues_count=same_issues_count,
            max_same_count=max_same_count,
            initial_scc_issues=initial_scc_issues,
            base_model_path=base_model_path,
            dir=f"{output_root}/run_{run}"
        )
        if resolved_scheme_number:
            evaluation_result["best_scheme_number"] = resolved_scheme_number
            evaluation_result["terminate"] = True
            evaluation_result["termination_reason"] = "目标线路过载问题已解决"
        
        # 获取新最优方案信息
        new_best_scheme_info = selector.get_scheme_detailed_info(
            analysis_root=current_output_dir,
            scheme_number=evaluation_result["best_scheme_number"],
            initial_scc_issues=initial_scc_issues
        )
        
        if not new_best_scheme_info:
            print(f"❌ 第{iteration}轮无法获取最优方案详细信息，终止迭代")
            final_iteration = iteration - 1
            break
        if resolved_scheme_number:
            new_best_scheme_info["target_resolved"] = True
            if new_best_scheme_info.get("n1_issues", 0) != 0:
                print("ℹ️ 目标问题已解决，但候选N-1筛选仍发现问题，继续迭代")
                evaluation_result["terminate"] = False
                evaluation_result["termination_reason"] = None
        
        if new_best_scheme_info["n1_issues"] > 50:
            print(f"⚠️ 第{iteration}轮最优方案N-1问题数过多 ({new_best_scheme_info['n1_issues']}), 可能无法改进，终止迭代")
            return None

        # 更新状态
        previous_best_issues = new_best_scheme_info["n1_issues"]
        same_issues_count = evaluation_result.get("same_issues_count", 0)
        best_scheme_info = new_best_scheme_info
        
        # 检查相关节点过载是否已解决（后续迭代）
        if related_nodes:
            best_n1_report_path = f"{best_scheme_info.get('analysis_dir')}/n1_report_{best_scheme_info['scheme_number']}.json"
            all_resolved, remaining_overloads = _check_all_related_overloads_resolved(best_n1_report_path, related_nodes)
            
            if all_resolved:
                print(f"✅ 所有相关节点过载问题已解决！")
                best_scheme_info["all_related_resolved"] = True
            elif remaining_overloads:
                print(f"⚠️ 仍有 {len(remaining_overloads)} 条相关节点线路过载")
                first_overload = remaining_overloads[0]
                overload_report = _generate_overload_report_text(first_overload)
                print(f"   下一条待处理过载: {first_overload['node1']} - {first_overload['node2']}")
                
                if context_json_path:
                    with open(context_json_path, 'r', encoding='utf-8') as f:
                        context_data = json.load(f)
                    context_data["n-1_analysis_report"] = overload_report
                    with open(context_json_path, 'w', encoding='utf-8') as f:
                        json.dump(context_data, f, indent=2, ensure_ascii=False)
                    print(f"   已更新 context.json 中的 n-1_analysis_report")

        final_validation_passed = False
        candidate_ready_for_final = best_scheme_info.get("n1_issues", 0) <= acceptable_n1_issues
        if candidate_ready_for_final:
            final_validation_passed = _run_final_full_n1_validation(
                best_scheme_info,
                acceptable_n1_issues=acceptable_n1_issues,
                enable_transient_analysis=enable_transient_analysis,
            )
            if not final_validation_passed:
                previous_best_issues = best_scheme_info["n1_issues"]
                same_issues_count = 0
                evaluation_result["terminate"] = False
                evaluation_result["termination_reason"] = None
        
        promoted_candidate_infos = []
        if final_validation_passed:
            promoted_candidate_infos = promote_later_simple_n1_candidates(
                current_output_dir,
                best_scheme_info["scheme_number"],
                run,
                output_root,
                selector,
                initial_scc_issues,
                acceptable_n1_issues,
                enable_transient_analysis=enable_transient_analysis,
            )
            best_scheme_info["promoted_candidate_infos"] = promoted_candidate_infos

        # 保存选中的方案到结果目录
        save_selected_proposal(best_scheme_info["scheme_number"], current_version, run, output_root=output_root)
        
        # 删除非最优方案的文件
        cleanup_other_schemes(current_version, best_scheme_info["scheme_number"], run, output_root=output_root)
        
        selector.adjust_generator_for_best_scheme(current_output_dir)

        if final_validation_passed:
            return best_scheme_info

        # 终止条件：保留原来的终止条件
        if evaluation_result["terminate"]:
            print(f"❌ 第{iteration}轮迭代终止: {evaluation_result.get('termination_reason', '未知原因')}")
            final_iteration = iteration - 1
            break
        
        print(f"✅ 第 {iteration} 轮迭代完成，选择方案 {best_scheme_info['scheme_number']}: N-1问题数={best_scheme_info['n1_issues']}, SCC问题数={best_scheme_info['scc_issues']}")
        
        final_iteration = iteration
    
    print(f"\n🎊 迭代改进完成，共进行 {final_iteration} 轮迭代")
    if best_scheme_info and best_scheme_info.get("final_n1_verified"):
        print(f"最终最优方案: N-1问题数={best_scheme_info['n1_issues']}, SCC问题数={best_scheme_info['scc_issues']}, 总问题数={best_scheme_info['total_issues']}")
        return best_scheme_info

    print("❌ 未找到通过最终全网N-1复核的方案")
    return None

def save_selected_proposal(scheme_number, current_version, run, output_root="fulfillment_scc"):
    """
    保存选中的方案到结果目录
    """
    try:
        # 源文件路径
        source_file = f"{output_root}/run_{run}/test_output_v{current_version}/generation/parsed_proposals.json"
        
        # 结果目录路径
        result_dir = f"{output_root}/run_{run}/result/proposal"
        os.makedirs(result_dir, exist_ok=True)
        
        # 目标文件路径
        target_file = os.path.join(result_dir, f"selected_proposal_iter{current_version}_scheme{scheme_number}.json")
        
        # 读取源文件
        with open(source_file, 'r', encoding='utf-8') as f:
            proposals_data = json.load(f)
        
        # 提取选中的方案
        proposals = proposals_data.get("proposals", [])
        if scheme_number <= len(proposals):
            selected_proposal = proposals[scheme_number-1]
            
            # 保存选中的方案
            with open(target_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "iteration": current_version,
                    "scheme_number": scheme_number,
                    "proposal": selected_proposal
                }, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 已保存方案 {scheme_number} 到: {target_file}")
        else:
            print(f"⚠️ 方案 {scheme_number} 不存在于解析结果中")
            
    except Exception as e:
        print(f"⚠️ 保存选中的方案时出错: {e}")

def cleanup_other_schemes(version, best_scheme_number, run, output_root="fulfillment_scc"):
    """
    删除非最优方案生成的文件
    包含在"analysis_*"和"application/method_*"这两个文件夹中
    """
    try:
        base_dir = f"{output_root}/run_{run}/test_output_v{version}"
        removed_folders = []
        
        # 删除analysis文件夹中非最优方案的文件
        analysis_pattern = os.path.join(base_dir, "analysis_*")
        analysis_folders = glob.glob(analysis_pattern)
        
        for folder in analysis_folders:
            try:
                # 提取方案编号
                folder_name = os.path.basename(folder)
                scheme_num = int(folder_name.split("_")[1])
                
                # 如果不是最优方案，删除该文件夹
                if scheme_num != best_scheme_number:
                    shutil.rmtree(folder)
                    removed_folders.append(folder)
                    print(f"🗑️ 已删除非最优方案文件夹: {folder}")
            except (ValueError, IndexError) as e:
                print(f"⚠️ 无法解析analysis文件夹名: {folder}, 错误: {e}")
        
        # 删除application/method文件夹中非最优方案的文件
        method_pattern = os.path.join(base_dir, "application", "method_*")
        method_folders = glob.glob(method_pattern)
        
        for folder in method_folders:
            try:
                # 提取方案编号
                folder_name = os.path.basename(folder)
                scheme_num = int(folder_name.split("_")[1])
                
                # 如果不是最优方案，删除该文件夹
                if scheme_num != best_scheme_number:
                    shutil.rmtree(folder)
                    removed_folders.append(folder)
                    print(f"🗑️ 已删除非最优方案文件夹: {folder}")
            except (ValueError, IndexError) as e:
                print(f"⚠️ 无法解析method文件夹名: {folder}, 错误: {e}")
        
        if removed_folders:
            print(f"✅ 已删除 {len(removed_folders)} 个非最优方案文件夹")
        else:
            print("✅ 无需删除，已是最优方案或已清理")
            
    except Exception as e:
        print(f"⚠️ 清理非最优方案文件时出错: {e}")

def _scheme_passed_simple_n1(combined_data, acceptable_n1_issues):
    if not combined_data or combined_data.get("pf_error"):
        return False

    n1_data = combined_data.get("n1_data", {}) or {}
    if n1_data.get("precheck_failed") or n1_data.get("screening_discarded"):
        return False

    return combined_data.get("n1_issues", float('inf')) <= acceptable_n1_issues

def _collect_later_simple_n1_passed_schemes(
    analysis_root,
    selected_scheme_number,
    selector,
    initial_scc_issues,
    acceptable_n1_issues,
):
    """Collect later-numbered candidates that passed the lightweight N-1 gate."""
    candidate_infos = []
    for scheme_number in _get_applied_scheme_numbers(analysis_root):
        if scheme_number <= selected_scheme_number:
            continue

        analysis_dir = os.path.join(analysis_root, f"analysis_{scheme_number}")
        combined_data = selector.parse_combined_reports(analysis_dir)
        if not _scheme_passed_simple_n1(combined_data, acceptable_n1_issues):
            continue

        scc_issues = combined_data.get("scc_data", {}).get("remaining_issues", 0) if combined_data.get("scc_data") else 0
        if scc_issues > initial_scc_issues:
            print(f"⏭️ 方案 {scheme_number} SCC问题数({scc_issues})超过初始值({initial_scc_issues})，不迁移")
            continue

        model_path = os.path.join(analysis_root, "application", f"method_{scheme_number}", f"applied_model_{scheme_number}.dat")
        if not os.path.exists(model_path):
            print(f"⚠️ 方案 {scheme_number} 缺少应用后模型，不迁移: {model_path}")
            continue

        candidate_infos.append({
            "scheme_number": scheme_number,
            "n1_issues": combined_data.get("n1_issues", 0),
            "scc_issues": scc_issues,
            "total_issues": combined_data.get("n1_issues", 0) + scc_issues,
            "analysis_dir": analysis_dir,
            "model_path": model_path,
        })

    if candidate_infos:
        scheme_numbers = [item["scheme_number"] for item in candidate_infos]
        print(f"📦 发现同轮后续简易N-1达标方案，将迁移到后续run_*: {scheme_numbers}")
    return candidate_infos

def _copy_generation_outputs(source_output_dir, target_output_dir):
    source_generation_dir = os.path.join(source_output_dir, "generation")
    target_generation_dir = os.path.join(target_output_dir, "generation")
    if os.path.exists(source_generation_dir):
        if os.path.exists(target_generation_dir):
            shutil.rmtree(target_generation_dir)
        shutil.copytree(source_generation_dir, target_generation_dir)

def _move_scheme_artifacts_to_run(candidate_info, source_output_dir, target_run, output_root):
    """Move one candidate's analysis/application folders into a later run directory."""
    scheme_number = candidate_info["scheme_number"]
    target_output_dir = os.path.join(output_root, f"run_{target_run}", "test_output_v0")
    os.makedirs(target_output_dir, exist_ok=True)
    _copy_generation_outputs(source_output_dir, target_output_dir)

    moves = [
        (
            os.path.join(source_output_dir, f"analysis_{scheme_number}"),
            os.path.join(target_output_dir, f"analysis_{scheme_number}"),
        ),
        (
            os.path.join(source_output_dir, "application", f"method_{scheme_number}"),
            os.path.join(target_output_dir, "application", f"method_{scheme_number}"),
        ),
    ]
    for src, dst in moves:
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            shutil.rmtree(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)

    moved_info = dict(candidate_info)
    moved_info["iteration"] = 0
    moved_info["source_run"] = None
    moved_info["promoted_from_output_dir"] = source_output_dir
    moved_info["analysis_dir"] = os.path.join(target_output_dir, f"analysis_{scheme_number}")
    moved_info["model_path"] = os.path.join(target_output_dir, "application", f"method_{scheme_number}", f"applied_model_{scheme_number}.dat")
    return moved_info

def promote_later_simple_n1_candidates(
    source_output_dir,
    selected_scheme_number,
    current_run,
    output_root,
    selector,
    initial_scc_issues,
    acceptable_n1_issues,
    enable_transient_analysis=False,
):
    """Move later lightweight-N-1-passed candidates into later run_* dirs and final-validate them."""
    promoted_infos = []
    candidate_infos = _collect_later_simple_n1_passed_schemes(
        source_output_dir,
        selected_scheme_number,
        selector,
        initial_scc_issues,
        acceptable_n1_issues,
    )

    for offset, candidate_info in enumerate(candidate_infos, start=1):
        target_run = current_run + offset
        moved_info = _move_scheme_artifacts_to_run(candidate_info, source_output_dir, target_run, output_root)
        moved_info["source_run"] = current_run
        print(f"📦 已将方案 {moved_info['scheme_number']} 迁移到 {output_root}/run_{target_run}")

        final_validation_passed = _run_final_full_n1_validation(
            moved_info,
            acceptable_n1_issues=acceptable_n1_issues,
            enable_transient_analysis=enable_transient_analysis,
        )
        save_selected_proposal(moved_info["scheme_number"], 0, target_run, output_root=output_root)
        cleanup_other_schemes(0, moved_info["scheme_number"], target_run, output_root=output_root)

        if final_validation_passed:
            moved_info["promoted_run"] = target_run
            promoted_infos.append(moved_info)
            print(f"✅ 迁移方案 {moved_info['scheme_number']} 已在 run_{target_run} 通过最终验证")
        else:
            promoted_run_dir = os.path.join(output_root, f"run_{target_run}")
            if os.path.exists(promoted_run_dir):
                shutil.rmtree(promoted_run_dir)
            print(f"⚠️ 迁移方案 {moved_info['scheme_number']} 未通过最终验证，已删除 run_{target_run}")

    return promoted_infos

def analysis_powerflow(dat_file, pf_report_path):
    # 检查数据文件是否存在
    if not os.path.exists(dat_file):
        raise FileNotFoundError(f"❌ 错误: 数据文件不存在: {dat_file}")
        
    config = load_config_as_dotdict()
    service = AnalysisService(config)
    print("\n[1/6] 测试 analyze_power_flow...")
    report = service.analyze_power_flow(dat_file, balanced_machine_output=True)
    os.makedirs(os.path.dirname(pf_report_path), exist_ok=True)
    with open(pf_report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("✅ 测试通过，潮流分析报告已生成。")

def analysis_n1(dat_file, run_dir_for_n1, n1_report_path, target_line=None, priority_lines=None, early_stop_issue_limit=None, full_scan=False):
    # 检查数据文件是否存在
    if not os.path.exists(dat_file):
        raise FileNotFoundError(f"❌ 错误: 数据文件不存在: {dat_file}")
        
    config = load_config_as_dotdict()
    service = AnalysisService(config)
    
    print("\n[2/6] 测试 analyze_n_security (n-1测试)...")
    n1_conditions = {
        "min_voltage_kv": 500.0,
        "ckt_id": "2"
    }
    report = service.analyze_n_security(
        dat_file,
        n1_conditions,
        run_dir_for_n1,
        target_line=target_line,
        priority_lines=priority_lines,
        early_stop_issue_limit=early_stop_issue_limit,
        full_scan=full_scan,
    )
    assert "error" not in report, f"N-1分析失败: {report.get('error')}"
    with open(n1_report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("✅ 测试通过，N-1分析报告已生成。")

def analysis_scc(dat_file, swi_file, scset_file, scc_report_path):
    # 检查文件是否存在
    for file_path, file_name in [(dat_file, "数据文件"), (swi_file, "swi文件"), (scset_file, "scset文件")]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"❌ 错误: {file_name}不存在: {file_path}")
            
    config = load_config_as_dotdict()
    service = AnalysisService(config)
    print("\n[4/6] analyze_short_circuit...")
    report = service.analyze_short_circuit(dat_file, swi_file, scset_file)
    with open(scc_report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("✅ 测试通过，scc分析报告已生成。")


def _transient_report_passed(report):
    if not report.get("execution_success"):
        return False

    analysis = report.get("analysis", {}) or {}
    if analysis.get("error"):
        return False

    block_results = analysis.get("results", []) or []
    if not block_results:
        return False

    return all("error" not in block_result for block_result in block_results)

def _stability_msg_report_passed(report):
    if not report.get("execution_success"):
        return False

    analysis = report.get("analysis", {}) or {}
    if analysis.get("error"):
        return False

    return analysis.get("files_with_instability", 0) == 0

def _transient_msg_report_path(transient_report_path):
    report_dir = os.path.dirname(transient_report_path)
    report_stem = os.path.splitext(os.path.basename(transient_report_path))[0]
    msg_report_stem = report_stem.replace("transient_report", "transient_msg_report", 1)
    return os.path.join(report_dir, f"{msg_report_stem}.json")

def _filter_problem_msg_report(report):
    filtered_report = dict(report)
    analysis = dict((report.get("analysis") or {}))
    files = analysis.get("files", []) or []
    problem_files = [
        item for item in files
        if item.get("has_voltage_instability")
        or item.get("has_frequency_instability")
        or item.get("error")
    ]
    analysis["files"] = problem_files
    filtered_report["analysis"] = analysis
    return filtered_report

def analysis_transient(dat_file, swi_file, lsd_file, transient_report_path):
    for file_path, file_name in [(dat_file, "数据文件"), (swi_file, "swi文件"), (lsd_file, "lsd文件")]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"❌ 错误: {file_name}不存在: {file_path}")

    config = load_config_as_dotdict()
    service = AnalysisService(config)
    print("\n[5/6] analyze_transient_stability...")
    report = service.analyze_transient_stability(dat_file, swi_file, lsd_file)
    os.makedirs(os.path.dirname(transient_report_path), exist_ok=True)

    msg_folder_path = os.path.dirname(dat_file)
    msg_report_path = _transient_msg_report_path(transient_report_path)
    msg_report = service.analyze_stability_msg(msg_folder_path)
    filtered_msg_report = _filter_problem_msg_report(msg_report)
    with open(msg_report_path, 'w', encoding='utf-8') as f:
        json.dump(filtered_msg_report, f, indent=2, ensure_ascii=False)

    transient_passed = _transient_report_passed(report)
    msg_passed = _stability_msg_report_passed(msg_report)
    passed = transient_passed and msg_passed
    if passed:
        print(f"✅ 暂态分析和MSG稳定性分析均通过，MSG异常摘要报告已生成: {msg_report_path}")
    else:
        if not transient_passed:
            print("⚠️ 暂态分析存在失败或异常场景，未输出 transient_report_*.json")
        if not msg_passed:
            print(f"⚠️ MSG稳定性分析未通过或未找到MSG文件，异常摘要报告已生成: {msg_report_path}")
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行电网规划方案生成与迭代评估流程。")
    parser.add_argument("base_model_path", help="基础 .dat 模型路径。")
    parser.add_argument("target_count", nargs="?", type=int, default=None, help="目标最终方案数量，默认 5。")
    parser.add_argument("--context-json", default="powergrid_pipeline_v2/data/context_shuifu.json", help="用于填充 prompt 的 context.json。")
    parser.add_argument("--n1-report", default=None, help="初始 N-1 报告路径；不提供或为空时会执行初始分析。")
    parser.add_argument("--initial-prompt", default="powergrid_pipeline_v2/data/prompts/generate_solution_n1_initial.txt", help="第 0 轮使用的 prompt 模板。")
    parser.add_argument("--iteration-prompt", default="powergrid_pipeline_v2/data/prompts/generate_solution_n1_iteration.txt", help="后续迭代使用的 prompt 模板。")
    parser.add_argument("--output-root", default="fulfillment_scc", help="运行输出根目录。")
    parser.add_argument("--initial-scc-issues", type=int, default=13, help="初始 SCC 问题数默认值。")
    parser.add_argument("--success-n1-issues", type=int, default=3, help="判定一次运行成功的 N-1 问题数。")
    parser.add_argument("--fixed-analysis-report", default=None, help="固定写入 prompt 的需解决问题文本；提供后不再从初始报告提取问题。")
    parser.add_argument("--target-overload-node1", default=None, help="目标过载线路节点1；用于分析阶段提前停止。")
    parser.add_argument("--target-overload-node2", default=None, help="目标过载线路节点2；用于分析阶段提前停止。")
    parser.add_argument("--related-nodes", default=None, help="相关节点列表（逗号分隔），如 '滇水富51,滇牛寨51,滇溪右50'，用于检查与这些节点相关的线路过载。")
    parser.add_argument("--skip-scc-analysis", action="store_true", help="跳过短路电流分析；通用案例使用。")
    parser.add_argument("--enable-transient-analysis", action="store_true", help="启用最终暂态分析；不提供时跳过暂态分析。")
    args = parser.parse_args()

    base_model_path = args.base_model_path
    target_count = args.target_count
    if target_count is None:
        target_count = 5
        env_target_count = os.environ.get("TARGET_SCHEME_COUNT")
        if env_target_count:
            try:
                target_count = max(1, int(env_target_count))
            except ValueError:
                print(f"⚠️ 警告: 环境变量 TARGET_SCHEME_COUNT 无效，已回退为默认值 5: {env_target_count}")
    else:
        target_count = max(1, target_count)
    
    # 初始化进度报告器（进度文件路径从环境变量获取或使用默认值）
    progress_file = os.environ.get('PROGRESS_FILE', 'progress.json')
    init_progress(progress_file)
    report_progress(stage="INIT", message="任务初始化中...")
    
    # 验证基础模型路径是否存在
    if not os.path.exists(base_model_path):
        error_msg = f"基础模型文件不存在: {base_model_path}"
        print(f"❌ 错误: {error_msg}")
        report_progress(error=error_msg, message=error_msg)
        sys.exit(1)
    
    print(f"✅ 基础模型路径: {base_model_path}")
    report_progress(message=f"基础模型路径验证通过: {base_model_path}")
    
    n1_report_path = args.n1_report
    prompt_template_path = args.initial_prompt
    
    # 验证提示模板路径是否存在
    if not os.path.exists(prompt_template_path):
        error_msg = f"提示模板文件不存在: {prompt_template_path}"
        print(f"❌ 错误: {error_msg}")
        report_progress(error=error_msg, message=error_msg)
        sys.exit(1)

    if not os.path.exists(args.iteration_prompt):
        error_msg = f"迭代提示模板文件不存在: {args.iteration_prompt}"
        print(f"❌ 错误: {error_msg}")
        report_progress(error=error_msg, message=error_msg)
        sys.exit(1)

    if not os.path.exists(args.context_json):
        error_msg = f"context JSON 文件不存在: {args.context_json}"
        print(f"❌ 错误: {error_msg}")
        report_progress(error=error_msg, message=error_msg)
        sys.exit(1)
    
    print(f"✅ 提示模板路径: {prompt_template_path}")
    print(f"✅ 迭代提示模板路径: {args.iteration_prompt}")
    print(f"✅ Context路径: {args.context_json}")
    
    # 运行计数器
    run_count = 0
    successful_runs = 0
    
    print(f"🚀 开始生成 {target_count} 个最终最优方案")
    report_progress(
        stage="RUNNING",
        message=f"开始生成 {target_count} 个最优方案",
        generated_scheme_count=0,
        target_scheme_count=target_count
    )
    print("=" * 60)
    
    while successful_runs < target_count:
        run_count += 1
        report_progress(
            step=run_count,
            total_steps=target_count,
            message=f"第 {run_count} 次运行 (已完成: {successful_runs}/{target_count})",
            generated_scheme_count=successful_runs,
            target_scheme_count=target_count
        )
        print(f"\n{'='*60}")
        print(f"🔄 第 {run_count} 次运行，目标: {target_count} 个最优方案 (已成功: {successful_runs}/{target_count})")
        print(f"{'='*60}")
        
        # 为每次运行创建独立的工作目录
        run_dir = f"{args.output_root}/run_{run_count}"
        
        # 创建运行目录
        os.makedirs(run_dir, exist_ok=True)
        
        try:
            # 运行迭代改进流程
            best_scheme_info = run_iterative_improvement_with_initial_analysis(
                base_model_path=base_model_path,
                n1_report_path=n1_report_path,
                prompt_template_path=prompt_template_path,
                max_iterations=10,
                max_same_count=2,
                initial_scc_issues=args.initial_scc_issues,
                run=run_count,
                context_json_path=args.context_json,
                iteration_prompt_template_path=args.iteration_prompt,
                output_root=args.output_root,
                fixed_analysis_report=args.fixed_analysis_report,
                target_overload_nodes=(
                    (args.target_overload_node1, args.target_overload_node2)
                    if args.target_overload_node1 and args.target_overload_node2
                    else None
                ),
                related_nodes=(
                    [n.strip() for n in args.related_nodes.split(",")]
                    if args.related_nodes
                    else None
                ),
                skip_scc_analysis=args.skip_scc_analysis,
                acceptable_n1_issues=args.success_n1_issues,
                enable_transient_analysis=args.enable_transient_analysis,
            )
            
            # 判断成功的逻辑：只有最终完整全网N-1复核无问题，才算真正选定方案。
            is_success = False
            if best_scheme_info and best_scheme_info.get("final_n1_verified"):
                is_success = True
                print(f"✅ 最终完整全网N-1复核通过")
            
            if is_success:
                successful_runs += 1
                print(f"✅ 成功生成第 {successful_runs} 个最终最优方案")
                report_progress(
                    stage="RUNNING",
                    message=f"成功生成第 {successful_runs} 个最优方案",
                    generated_scheme_count=successful_runs,
                    target_scheme_count=target_count
                )
                
                # 保存最终最优方案信息
                solution_info = {
                    "run_number": run_count,
                    "solution_number": successful_runs,
                    "best_scheme_info": best_scheme_info,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "iteration_count": best_scheme_info.get("iteration", 0)
                }
                
                promoted_candidate_infos = best_scheme_info.get("promoted_candidate_infos", []) or []
                if promoted_candidate_infos:
                    highest_promoted_run = max(item.get("promoted_run", run_count) for item in promoted_candidate_infos)
                    for promoted_info in promoted_candidate_infos:
                        if successful_runs >= target_count:
                            break
                        successful_runs += 1
                        print(
                            f"✅ 迁移的 run_{promoted_info.get('promoted_run')} "
                            f"计为第 {successful_runs} 个最终最优方案"
                        )
                        report_progress(
                            stage="RUNNING",
                            message=f"成功生成第 {successful_runs} 个最优方案",
                            generated_scheme_count=successful_runs,
                            target_scheme_count=target_count
                        )
                    run_count = max(run_count, highest_promoted_run)

                # 打印进度
                print(f"\n📊 进度: {successful_runs}/{target_count} 个最优方案已生成")
            
            else:
                # 删除 run_* 文件夹，便于排查未生成最优方案的运行结果。
                if os.path.exists(run_dir):
                    shutil.rmtree(run_dir)
                print(f"⚠️ 第 {run_count} 次运行未生成最优方案")
                report_progress(
                    stage="RUNNING",
                    message=f"第 {run_count} 次运行未生成最优方案，继续尝试...",
                    generated_scheme_count=successful_runs,
                    target_scheme_count=target_count
                )
                
        except Exception as e:
            # 删除 run_* 文件夹，便于排查失败运行的中间结果。
            if os.path.exists(run_dir):
                shutil.rmtree(run_dir)
            error_msg = f"第 {run_count} 次运行失败: {e}"
            print(f"❌ {error_msg}")
            report_progress(
                error=str(e),
                message=error_msg,
                generated_scheme_count=successful_runs,
                target_scheme_count=target_count
            )
            import traceback
            traceback.print_exc()
        
        print(f"\n⏱️ 已完成 {run_count} 次运行，成功 {successful_runs}/{target_count} 次")
        print("-" * 60)
    
    report_progress(
        stage="COMPLETED",
        message=f"任务完成，成功生成 {successful_runs} 个最优方案",
        generated_scheme_count=successful_runs,
        target_scheme_count=target_count
    )
    print(f"\n{'='*60}")
    print(f"🎉 成功生成 {successful_runs} 个最终最优方案！")
    print(f"🏁 总运行次数: {run_count}")
    print(f"{'='*60}")

# if __name__ == "__main__":
#     base_model_path = r"powergrid_pipeline_v2\data\base_models\yunnan_base.dat"
#     n1_report_path, previous_best_issues, initial_scc_issues = initial_analysis(base_model_path, "fulfillment_scc_test")
#     print(f"初始N-1问题数: {previous_best_issues}, 初始SCC问题数: {initial_scc_issues}")
