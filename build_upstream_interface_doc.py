from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUT = Path("artifacts/upstream_simulation_data_interface_spec.docx")

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
LIGHT_BLUE = "E8EEF5"
LIGHT_GRAY = "F2F4F7"
BORDER = "AAB4C0"
TEXT = "1F2933"
MUTED = "5B6573"
RISK = "9B1C1C"
GOOD = "1F6B45"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, v in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_table_geometry(table, widths_dxa: list[int], indent_dxa: int = 120) -> None:
    table.autofit = False
    total = sum(widths_dxa)
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(total))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent_dxa))
    tbl_ind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(widths_dxa[idx]))
            tc_w.set(qn("w:type"), "dxa")
            set_cell_margins(cell)


def set_run_font(run, latin="Calibri", east="宋体", size=11, bold=None, color=TEXT, italic=None):
    run.font.name = latin
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), latin)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), latin)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), east)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def style_para(p, after=6, before=0, line=1.25, first_line=0, keep=False):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    if first_line:
        pf.first_line_indent = Pt(first_line)
    pf.keep_with_next = keep


def add_body(doc, text: str, bold_prefix: str | None = None, color=TEXT, first_line=0):
    p = doc.add_paragraph()
    style_para(p, first_line=first_line)
    if bold_prefix and text.startswith(bold_prefix):
        r1 = p.add_run(bold_prefix)
        set_run_font(r1, bold=True, color=color)
        r2 = p.add_run(text[len(bold_prefix):])
        set_run_font(r2, color=color)
    else:
        r = p.add_run(text)
        set_run_font(r, color=color)
    return p


def add_heading(doc, text: str, level: int):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    if level == 1:
        set_run_font(r, latin="Calibri", east="微软雅黑", size=16, bold=True, color=BLUE)
        style_para(p, before=18, after=10, line=1.0, keep=True)
    elif level == 2:
        set_run_font(r, latin="Calibri", east="微软雅黑", size=13, bold=True, color=BLUE)
        style_para(p, before=14, after=7, line=1.0, keep=True)
    else:
        set_run_font(r, latin="Calibri", east="微软雅黑", size=12, bold=True, color=DARK_BLUE)
        style_para(p, before=10, after=5, line=1.0, keep=True)
    return p


def add_bullet(doc, text: str, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    pf = p.paragraph_format
    pf.left_indent = Inches(0.375 + 0.25 * level)
    pf.first_line_indent = Inches(-0.188)
    pf.space_after = Pt(4)
    pf.line_spacing = 1.25
    r = p.add_run(text)
    set_run_font(r)
    return p


def add_number(doc, text: str):
    p = doc.add_paragraph(style="List Number")
    pf = p.paragraph_format
    pf.left_indent = Inches(0.375)
    pf.first_line_indent = Inches(-0.188)
    pf.space_after = Pt(4)
    pf.line_spacing = 1.25
    r = p.add_run(text)
    set_run_font(r)
    return p


def add_callout(doc, title: str, text: str, risk=False):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_geometry(table, [9360], 120)
    cell = table.cell(0, 0)
    set_cell_shading(cell, "FFF4F2" if risk else LIGHT_GRAY)
    p = cell.paragraphs[0]
    style_para(p, after=2, line=1.2)
    r = p.add_run(title + "  ")
    set_run_font(r, east="微软雅黑", bold=True, color=RISK if risk else DARK_BLUE)
    r = p.add_run(text)
    set_run_font(r)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_table(doc, headers: list[str], rows: list[list[str]], widths: list[int], font_size=9):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.style = "Table Grid"
    hdr = table.rows[0]
    set_repeat_table_header(hdr)
    for i, h in enumerate(headers):
        c = hdr.cells[i]
        set_cell_shading(c, LIGHT_BLUE)
        c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = c.paragraphs[0]
        style_para(p, after=0, line=1.1)
        r = p.add_run(h)
        set_run_font(r, east="微软雅黑", size=font_size, bold=True, color=DARK_BLUE)
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            p = cells[i].paragraphs[0]
            style_para(p, after=0, line=1.12)
            r = p.add_run(str(value))
            set_run_font(r, size=font_size)
    set_table_geometry(table, widths, 120)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_code(doc, obj):
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_geometry(table, [9360], 120)
    cell = table.cell(0, 0)
    set_cell_shading(cell, "F7F8FA")
    p = cell.paragraphs[0]
    style_para(p, after=0, line=1.0)
    for idx, line in enumerate(text.splitlines()):
        if idx:
            p.add_run().add_break()
        r = p.add_run(line)
        set_run_font(r, latin="Consolas", east="微软雅黑", size=8.2, color="25313C")
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def setup_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor.from_string(TEXT)
    pf = normal.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(6)
    pf.line_spacing = 1.25
    for style_name in ("List Bullet", "List Bullet 2", "List Number"):
        s = doc.styles[style_name]
        s.font.name = "Calibri"
        s._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        s.font.size = Pt(11)


def add_footer(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("网架规划仿真数据接口规范  |  上游交付版")
    set_run_font(r, size=8.5, color=MUTED)


def build_document():
    doc = Document()
    setup_styles(doc)
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)
    add_footer(section)

    p = doc.add_paragraph()
    style_para(p, after=4)
    r = p.add_run("TECHNICAL DATA CONTRACT")
    set_run_font(r, latin="Arial", east="微软雅黑", size=9.5, bold=True, color=BLUE)

    p = doc.add_paragraph()
    style_para(p, after=5, line=1.0)
    r = p.add_run("网架规划仿真数据—报告生成接口规范")
    set_run_font(r, latin="Arial", east="微软雅黑", size=23, bold=True, color="111827")

    p = doc.add_paragraph()
    style_para(p, after=14, line=1.1)
    r = p.add_run("上游数据提取、文件命名、JSON字段与验收要求")
    set_run_font(r, latin="Arial", east="微软雅黑", size=13, color=MUTED)

    meta = [
        ["版本", "V1.0", "编制日期", "2026-08-20"],
        ["适用模块", "dianwang_report_gen", "输入口径", "单一指定运行场景"],
        ["交付目标", "提取结果可直接作为 REPORT_TEST_INPUT_DIR", "状态", "供上游实施与联调"],
    ]
    add_table(doc, ["项目", "内容", "项目", "内容"], meta, [1100, 3580, 1100, 3580], 9.3)

    add_callout(
        doc,
        "核心结论",
        "报告程序不直接读取 extracted_metrics 文件夹。上游必须按本文规定生成 generation/parsed_proposals.json，"
        "并在 analysis_1、analysis_2……目录中生成 pf_report_i.json、n1_report_i.json、scc_report_i.json、"
        "transient_report_i.json。目录、文件名、方案顺序和字段位置必须完全一致。",
    )

    add_heading(doc, "1. 适用范围与交付原则", 1)
    add_body(doc, "本文定义从 DSP/BPA 等原始仿真文件提取数据后，交付给当前报告生成项目的唯一推荐接口。目标是让上游结构化结果无需人工改名、复制字段或二次转表，即可参与方案比选指标计算。")
    for item in [
        "一个输入根目录只允许包含同一个运行场景；不同场景必须分开交付、分开生成报告。",
        "方案编号从1开始连续递增；parsed_proposals.json 中第i个方案必须对应 analysis_i。",
        "优先提供程序可直接使用的汇总指标，同时保留原始明细记录用于溯源和复核。",
        "数值字段必须是真实JSON number；不得把百分数写成带%号的字符串。",
        "缺失数值使用 null 或省略可选字段；不得写 N/A、--、未知、数据缺失、空字符串或0代替缺失。",
        "所有电压、容量、功率、长度和经济数据必须采用本文规定的单位。",
    ]:
        add_bullet(doc, item)

    add_heading(doc, "2. 输入根目录与强制文件命名", 1)
    add_body(doc, "假设本次交付根目录为 CASE_INPUT。环境变量 REPORT_TEST_INPUT_DIR 必须指向 CASE_INPUT，而不是指向 extracted_metrics、analysis_1 或某一个JSON文件。")
    add_code(doc, """CASE_INPUT/
├─ generation/
│  └─ parsed_proposals.json
├─ analysis_1/
│  ├─ pf_report_1.json
│  ├─ n1_report_1.json
│  ├─ scc_report_1.json
│  ├─ transient_report_1.json
│  └─ transient_msg_report_1.json       # 可选兼容文件
├─ analysis_2/
│  ├─ pf_report_2.json
│  ├─ n1_report_2.json
│  ├─ scc_report_2.json
│  └─ transient_report_2.json
└─ ...""")
    add_table(doc, ["规则", "强制要求"], [
        ["目录编号", "analysis_i 中的 i 必须连续，且与方案数组顺序一致。"],
        ["文件编号", "每个文件名中的 i 必须与所在 analysis_i 一致。"],
        ["大小写", "文件名全部使用本文给出的英文小写形式；不得增加时间戳或中文后缀。"],
        ["编码", "UTF-8 JSON；推荐无BOM；禁止GBK JSON。"],
        ["JSON根结构", "必须是对象；不得用CSV、JSONL或顶层数组替代。"],
        ["场景标识", "scenario_id/scenario_name 在全部文件中必须一致。"],
    ], [1800, 7560], 9.5)

    add_heading(doc, "3. 全局字段、类型与单位约定", 1)
    add_table(doc, ["数据类别", "类型/单位", "规定"], [
        ["标识", "string", "母线名、线路名、方案名、场景ID均不得自动转成数字。"],
        ["布尔", "boolean", "使用 true/false，不使用0/1字符串。"],
        ["比率", "number，%", "95.89表示95.89%，不能写0.9589，也不能写\"95.89%\"。"],
        ["电压", "kV、p.u.", "字段名必须区分 voltage_kv 和 voltage_pu。"],
        ["有功/无功", "MW/Mvar", "有功正负方向必须在上游保持统一。"],
        ["容量", "MVA", "正常额定容量和事故应急允许容量必须分开。"],
        ["电流", "A 或 kA", "潮流设备额定值用A；短路及开断电流用kA。"],
        ["功角", "degree", "只写有限物理值；99999等仿真发散标志不得写入最大功角字段。"],
        ["长度", "km", "优先使用 length_km/LENGTH_KM；只有源数据确实是英里时才使用MILES。"],
        ["经济", "CNY、CNY/year", "不得混用万元与元；如源数据为万元，提取时转换为元。"],
    ], [1800, 1600, 5960], 9.2)
    add_callout(doc, "禁止事项", "MILES 在当前计算器中会自动乘以 1.609344 转成公里。如果上游实际把 MILES 字段当公里使用，必须改写到 LENGTH_KM 或 length_km，否则线路长度和工程投资会被放大。", risk=True)

    add_heading(doc, "4. 指标—文件—字段映射总表", 1)
    add_table(doc, ["指标", "直接读取文件", "推荐直接字段", "单位"], [
        ["基态潮流收敛性", "pf_report_i.json", "analysis.is_convergent", "boolean"],
        ["电压合格率", "pf_report_i.json", "analysis.voltage_pass_rate", "%"],
        ["电压越限严重度", "pf_report_i.json", "analysis.voltage_violation_severity", "p.u.^2"],
        ["有功网损率", "pf_report_i.json", "analysis.active_power_loss_rate", "%"],
        ["关键断面最小裕度率", "pf_report_i.json", "analysis.section_transfer_margin_rate", "%"],
        ["最大线路负载率", "pf_report_i.json", "analysis.max_line_loading_rate", "%"],
        ["最大主变负载率", "pf_report_i.json", "analysis.max_transformer_loading_rate", "%"],
        ["N-1通过率", "n1_report_i.json", "pass_count + total_contingencies_run，或完整contingencies", "%"],
        ["故障后电压越限率", "n1_report_i.json", "post_contingency_voltage_violation_rate", "%"],
        ["故障后最大设备负载率", "n1_report_i.json", "post_contingency_max_loading_rate", "%"],
        ["最小断路器开断裕度率", "scc_report_i.json", "analysis.all_buses中的3-PH记录", "%"],
        ["暂态稳定通过率", "transient_report_i.json", "analysis.transient_stability_pass_rate", "%"],
        ["最大机组相对功角差", "transient_report_i.json", "analysis.maximum_relative_rotor_angle", "degree"],
        ["新建线路长度", "parsed_proposals.json", "proposal.new_line_length 或新增线路length_km", "km"],
        ["线路工程投资", "parsed_proposals.json", "proposal.line_engineering_cost 或长度×单位造价+跨越费", "CNY"],
        ["建设投资/运维/年费用/LCC", "parsed_proposals.json", "construction_cost/operation_cost/annual_cost/lifecycle_cost", "CNY或CNY/year"],
    ], [2100, 1750, 4310, 1200], 8.6)

    add_heading(doc, "5. generation/parsed_proposals.json", 1)
    add_body(doc, "该文件定义方案顺序、工程改动和经济数据。proposals 数组的第i项与 analysis_i 一一对应。")
    add_table(doc, ["字段路径", "类型", "必填", "单位/说明"], [
        ["proposals", "array", "是", "方案数组，顺序不可变。"],
        ["proposals[i].proposal_name", "string", "是", "例如方案1。"],
        ["scenario_id", "string", "是", "同一根目录必须一致。"],
        ["scenario_name", "string", "建议", "人类可读场景名称。"],
        ["description", "string", "建议", "方案简述，不作为主要数值来源。"],
        ["new_line_length", "number", "建议", "km；直接值优先。"],
        ["line_engineering_cost", "number", "建议", "CNY；直接值优先。"],
        ["construction_cost", "number", "经济比选必填", "CNY。"],
        ["operation_cost", "number", "经济比选必填", "CNY/year。"],
        ["annual_cost", "number", "建议", "CNY/year。"],
        ["lifecycle_cost", "number", "建议", "CNY；若提供则直接使用。"],
        ["loss_cost/outage_cost", "number", "LCC建议", "评价口径下的年度成本。"],
        ["interest_rate", "number", "LCC建议", "小数，例如0.07。"],
        ["evaluation_years", "integer", "LCC建议", "评价年限。"],
        ["replacement_costs", "array", "可选", "元素为{year,replacement_cost}。"],
        ["decommissioning_cost", "number", "可选", "评价期末退役成本，CNY。"],
        ["residual_value", "number", "可选", "评价期末残值，CNY。"],
        ["modifications", "array", "是", "add_line、add_bus、disable_branch等。"],
    ], [3600, 1000, 1300, 3460], 8.8)
    add_code(doc, {
        "proposals": [{
            "proposal_name": "方案1",
            "scenario_id": "summer_peak_single_scene",
            "scenario_name": "夏大方式",
            "description": "500kV南屏接入方案1",
            "new_line_length": 177.0,
            "line_engineering_cost": None,
            "construction_cost": None,
            "operation_cost": None,
            "annual_cost": None,
            "lifecycle_cost": None,
            "interest_rate": 0.07,
            "evaluation_years": 20,
            "modifications": [{
                "action": "add_line",
                "params": {
                    "length_km": 85.0,
                    "unit_cost_per_km": None,
                    "crossing_cost": 0,
                    "full_branch_data": {
                        "TYPE": "L ", "NAME1": "滇南屏51", "NAME2": "滇富宁51",
                        "BASE1": 525.0, "BASE2": 525.0, "CKT ID": "1",
                        "LENGTH_KM": 85.0, "LINE NAME": "500kV南屏富宁甲线"
                    }
                }
            }]
        }]
    })

    add_heading(doc, "6. analysis_i/pf_report_i.json", 1)
    add_body(doc, "潮流文件建议同时提供直接汇总字段和明细数组。直接字段保证当前报告立即计算；明细数组用于复核、溯源和未来扩展。")
    add_table(doc, ["字段路径", "类型", "必填", "计算/口径"], [
        ["proposal_index", "integer", "是", "必须等于i。"],
        ["scenario_id/scenario_name", "string", "是", "与其他文件一致。"],
        ["input_dat", "string", "是", "仿真DAT源文件名。"],
        ["analysis.is_convergent", "boolean", "是", "收敛=true。"],
        ["analysis.voltage_pass_rate", "number", "建议直接给", "合格节点数/评价节点数×100%。"],
        ["analysis.voltage_violation_severity", "number", "建议直接给", "Σ[max(0,Vmin−V,V−Vmax)]²。"],
        ["analysis.evaluated_voltage_node_count", "integer", "是", "参与评价节点数。"],
        ["analysis.voltage_violation_count", "integer", "是", "越限节点数。"],
        ["analysis.active_power_loss_rate", "number", "建议直接给", "系统有功损耗/规定区域输入功率×100%。"],
        ["analysis.section_transfer_margin_rate", "number", "建议直接给", "所有关键断面裕度率的最小值。"],
        ["analysis.max_line_loading_rate", "number", "是", "线路负载/允许容量，取最大值。"],
        ["analysis.max_transformer_loading_rate", "number", "是", "主变负载/允许容量，取最大值。"],
        ["analysis.voltage_nodes", "array", "溯源必填", "每个评价节点完整记录。"],
        ["analysis.line_loadings", "array", "溯源必填", "不得只输出超过80%的设备。"],
        ["analysis.transformer_loadings", "array", "溯源必填", "完整主变列表。"],
        ["analysis.critical_sections", "array", "断面指标必填", "section_power_mw和safe_limit_mw。"],
        ["analysis.power_summary", "array", "网损指标必填", "power_loss_mw和input_power_mw。"],
    ], [3850, 950, 1300, 3260], 8.5)
    add_code(doc, {
        "proposal_index": 1,
        "scenario_id": "summer_peak_single_scene",
        "scenario_name": "夏大方式",
        "input_dat": "applied_model_1.dat",
        "analysis": {
            "is_convergent": True,
            "voltage_pass_rate": 90.759017,
            "voltage_violation_severity": 0.397902194077,
            "evaluated_voltage_node_count": 5573,
            "voltage_violation_count": 515,
            "active_power_loss_rate": None,
            "section_transfer_margin_rate": None,
            "max_line_loading_rate": 90.9394,
            "max_transformer_loading_rate": 103.638213,
            "power_summary": [{"power_loss_mw": 3524.1, "input_power_mw": None}],
            "voltage_nodes": [{"bus_name": "示例母线", "voltage_pu": 1.01, "min_voltage": 0.95, "max_voltage": 1.052}],
            "line_loadings": [{"from_bus": "母线A", "to_bus": "母线B", "ckt_id": "1", "loading_percent": 88.2}],
            "transformer_loadings": [{"name": "主变1", "actual_mva": 103.6, "allowed_mva": 100.0, "loading_percent": 103.6}],
            "critical_sections": [{"section_id": "SEC-01", "section_power_mw": None, "safe_limit_mw": None}]
        }
    })

    add_heading(doc, "7. analysis_i/n1_report_i.json", 1)
    add_callout(doc, "字段位置要求", "post_contingency_voltage_violation_rate、post_contingency_voltage_violation_count、total_contingency_node_pairs 和 post_contingency_max_loading_rate 必须放在JSON顶层。放进 analysis 对象会在当前过滤阶段丢失。", risk=True)
    add_table(doc, ["字段路径", "类型", "必填", "说明"], [
        ["scenario_id/scenario_name", "string", "是", "与方案场景一致。"],
        ["input_dat", "string", "是", "源DAT文件名。"],
        ["total_contingencies_run", "integer", "是", "实际完整执行的故障数。"],
        ["pass_count", "integer", "是", "严格通过故障数。"],
        ["passed_load", "number", "加权N-1需要", "通过故障对应权重或负荷。"],
        ["total_load", "number", "加权N-1需要", "全部故障对应权重或负荷。"],
        ["post_contingency_voltage_violation_count", "integer", "是", "越限故障—节点组合数。"],
        ["total_contingency_node_pairs", "integer", "是", "全部有效故障—节点组合数。"],
        ["post_contingency_voltage_violation_rate", "number", "是", "前两项相除×100%。"],
        ["post_contingency_max_loading_rate", "number", "是", "全部故障下线路/主变应急负载率最大值。"],
        ["contingencies", "array", "溯源必填", "全部故障记录，不得只保留问题故障。"],
        ["contingencies_with_issues", "array", "建议", "问题故障摘要，用于报告说明。"],
    ], [3900, 950, 1550, 2960], 8.5)
    add_table(doc, ["contingencies[i].result.analysis字段", "类型", "规定"], [
        ["is_convergent", "boolean", "不收敛即不通过。"],
        ["has_unacceptable_overload", "boolean", "按事故应急允许容量判断。"],
        ["has_voltage_violation", "boolean", "按统一电压限值和节点范围判断。"],
        ["has_unplanned_islanding", "boolean", "非计划孤岛即不通过。"],
        ["has_load_loss", "boolean", "存在负荷损失即不通过。"],
        ["load_loss_mw", "number", "无损失填0，未知填null。"],
        ["evaluated_node_count", "integer", "本故障参与评价节点数。"],
        ["overloaded_lines", "array", "至少含loading_percent、emergency_capacity_mva。"],
        ["overloaded_transformers", "array", "至少含loading_percent、emergency_capacity_mva。"],
        ["voltage_abnormal_nodes", "array", "至少含bus_name、voltage_pu、上下限。"],
    ], [4400, 1100, 3860], 8.8)
    add_code(doc, {
        "scenario_id": "summer_peak_single_scene",
        "scenario_name": "夏大方式",
        "input_dat": "applied_model_1.dat",
        "total_contingencies_run": 73,
        "pass_count": 70,
        "passed_load": None,
        "total_load": None,
        "post_contingency_voltage_violation_count": 37615,
        "total_contingency_node_pairs": 406829,
        "post_contingency_voltage_violation_rate": 9.245899,
        "post_contingency_max_loading_rate": 105.97,
        "contingencies": [{
            "contingency_branch_uid": "母线A|母线B|1",
            "result": {"analysis": {
                "is_convergent": True,
                "has_unacceptable_overload": False,
                "has_voltage_violation": False,
                "has_unplanned_islanding": False,
                "has_load_loss": False,
                "load_loss_mw": 0,
                "evaluated_node_count": 5573,
                "overloaded_lines": [],
                "overloaded_transformers": [],
                "voltage_abnormal_nodes": []
            }}
        }],
        "contingencies_with_issues": []
    })
    add_body(doc, "N-1设备明细必须包含事故应急容量。如果原始仿真只给正常额定容量，可以同时输出正常额定负载率，但不得把它伪装成应急负载率；此时 post_contingency_max_loading_rate 应为 null，等待补充应急容量。")

    add_heading(doc, "8. analysis_i/scc_report_i.json", 1)
    add_body(doc, "最小断路器开断裕度只按三相短路电流计算。当前代码会忽略1-PH记录和未标明故障类型的记录。")
    add_table(doc, ["字段路径", "类型", "必填", "说明"], [
        ["execution_success", "boolean", "是", "短路计算是否成功。"],
        ["analysis.total_buses", "integer", "是", "有效检查母线数。"],
        ["analysis.all_buses", "array", "是", "应包含全部有效3-PH检查记录。"],
        ["bus_name", "string", "是", "母线唯一名称。"],
        ["short_circuit_current_kA", "number", "是", "三相短路电流，kA。"],
        ["breaker_current_kA", "number", "是", "断路器额定开断电流，kA，必须大于0。"],
        ["fault_type", "string", "是", "固定写3-PH。"],
        ["voltage_kV/partition", "number/string", "建议", "用于报告定位。"],
        ["analysis.exceeding_buses", "array", "建议", "Isc大于开断电流的记录。"],
        ["analysis.minimum_breaker_margin_percent", "number", "建议", "可提供校验值，但程序优先由all_buses重算。"],
        ["analysis.short_circuit_over_limit_ratio", "number", "建议", "越限母线数/有效检查母线数×100%。"],
    ], [3900, 1100, 1300, 3060], 8.7)
    add_code(doc, {
        "scenario_id": "summer_peak_single_scene",
        "scenario_name": "夏大方式",
        "input_dat": "applied_model_1.dat",
        "execution_success": True,
        "analysis": {
            "total_buses": 232,
            "all_buses": [{
                "bus_name": "滇博串K2", "short_circuit_current_kA": 110.977,
                "breaker_current_kA": 63.0, "voltage_kV": 525.0,
                "fault_type": "3-PH", "partition": "54"
            }],
            "exceeding_buses": [],
            "minimum_breaker_margin_percent": -76.153968,
            "short_circuit_over_limit_ratio": 0.431034
        }
    })

    add_heading(doc, "9. analysis_i/transient_report_i.json", 1)
    add_body(doc, "暂态通过率应按已确认的功角、电压、频率判据生成。支路过载是否计入暂态失败必须由项目规则统一确认，不能由提取脚本自行决定。")
    add_table(doc, ["字段路径", "类型", "必填", "说明"], [
        ["analysis.stable_count", "integer", "是", "满足规定暂态判据的已完成算例数。"],
        ["analysis.total_count", "integer", "是", "通过率分母；推荐等于completed_count。"],
        ["analysis.transient_stability_pass_rate", "number", "是", "stable_count/total_count×100%。"],
        ["analysis.maximum_relative_rotor_angle", "number", "是", "最大有限物理功角差；禁止99999。"],
        ["analysis.completed_count", "integer", "是", "成功生成并解析结果的block数。"],
        ["analysis.expected_count", "integer", "是", "应执行block总数。"],
        ["analysis.unstable_count", "integer", "是", "已完成结果中的失稳数。"],
        ["analysis.missing_count", "integer", "是", "缺失或执行失败数。"],
        ["analysis.coverage_rate", "number", "是", "completed_count/expected_count×100%。"],
        ["analysis.data_complete", "boolean", "是", "completed=expected且missing=0时为true。"],
        ["analysis.source_format", "string", "建议", "例如DSP_MSG_CSV。"],
        ["analysis.records", "array", "溯源必填", "每个block一条完整判定记录。"],
        ["analysis.angle_sets", "array", "可选", "如不提供直接最大功角，则需提供每时刻机组角数组。"],
    ], [3900, 1000, 1300, 3160], 8.6)
    add_table(doc, ["records[i]推荐字段", "类型", "说明"], [
        ["block_index", "integer", "暂态算例编号。"],
        ["execution_success", "boolean", "是否成功。"],
        ["angle_pass/voltage_pass/frequency_pass", "boolean", "三个判据分别判断。"],
        ["transient_pass", "boolean", "按项目规则合并。"],
        ["max_relative_rotor_angle_deg", "number/null", "有效物理值；失步标志另存。"],
        ["rotor_angle_unstable", "boolean", "99999或失步时为true。"],
        ["minimum_voltage_pu", "number/null", "全节点暂态最低电压。"],
        ["voltage_violation_duration_s", "number/null", "越限持续时间。"],
        ["minimum_frequency_hz/maximum_frequency_hz", "number/null", "频率极值。"],
        ["islanding_detected/branch_overload", "boolean", "独立记录，不混淆判据。"],
        ["failure_reasons", "array[string]", "例如功角失稳、电压失稳、频率失稳。"],
        ["source_msg/source_csv", "string", "相对路径。"],
    ], [4000, 1300, 4060], 8.7)
    add_code(doc, {
        "scenario_id": "summer_peak_single_scene",
        "scenario_name": "夏大方式",
        "input_dat": "applied_model_1.dat",
        "analysis": {
            "stable_count": 136,
            "total_count": 145,
            "transient_stability_pass_rate": 93.793103,
            "maximum_relative_rotor_angle": 114.39,
            "completed_count": 145,
            "expected_count": 147,
            "unstable_count": 9,
            "missing_count": 2,
            "coverage_rate": 98.639456,
            "data_complete": False,
            "source_format": "DSP_MSG_CSV",
            "records": [{
                "block_index": 32, "execution_success": True,
                "angle_pass": False, "voltage_pass": False, "frequency_pass": False,
                "transient_pass": False, "max_relative_rotor_angle_deg": None,
                "rotor_angle_unstable": True, "branch_overload": True,
                "failure_reasons": ["功角失稳", "电压失稳", "频率失稳"],
                "source_msg": "application/method_1/applied_model_1_block32.MSG"
            }]
        }
    })
    add_callout(doc, "完整性说明", "data_complete=false 时，当前报告会把暂态通过率标为部分数据。要形成正式完整指标，上游必须补跑所有缺失block，并使 completed_count + missing_count = expected_count。", risk=True)

    add_heading(doc, "10. transient_msg_report_i.json（兼容文件，可选）", 1)
    add_body(doc, "若上游暂时不能直接生成 transient_report_i.json，可额外生成本文件供当前程序合并。但正式交付仍推荐直接生成上一节的 transient_report_i.json。")
    add_code(doc, {
        "analysis": {
            "total_files": 145,
            "files_with_instability": 9,
            "total_expected_blocks": 147,
            "missing_msg_count": 2
        }
    })

    add_heading(doc, "11. 原始仿真数据必须提取的明细清单", 1)
    add_table(doc, ["来源", "必须提取", "用途"], [
        ["基态PF", "全部评价节点电压；全部线路和主变首末端P/Q、电流、MVA、正常/应急限额；系统损耗；区域输入；断面潮流", "稳态电压、网损、设备负载率、断面裕度"],
        ["73个N-1 PF", "每个故障全部节点电压、全部线路/主变负载率、收敛、孤岛、负荷损失、系统汇总", "严格N-1通过率、故障后电压和设备负载"],
        ["SCC CSV/RPT", "全部母线三相短路电流及对应断路器开断电流", "最小开断裕度和越限比例"],
        ["暂态MSG", "每个block最终状态、最大相对功角、失稳类型、频率极值、孤岛和支路过载", "暂态通过率、功角差、失稳原因"],
        ["暂态CSV/CHT", "最低电压、发生时刻、越限持续时间；必要时导出机组功角和频率通道", "暂态电压和功角复核"],
        ["DAT/方案JSON", "母线、线路、变压器拓扑；额定/应急容量；线路长度与单位；新增/改造/停运标志", "拓扑图、工程量和负载率覆盖"],
        ["规划/经济参数", "单位造价、运维费率、等效网损小时、电价、折现率、年限、残值、停电损失", "投资、年费用、年网损成本和LCC"],
    ], [1600, 4700, 3060], 8.8)

    add_heading(doc, "12. 当前接口尚不能直接计算的四项指标", 1)
    add_body(doc, "以下字段即使由上游提取，当前版本也不会进入本轮核心计算或排序。若后续需要启用，必须先扩展 SUPPORTED_METRICS、过滤字段和核心汇总表，再发布新版接口规范。")
    add_table(doc, ["指标", "建议上游预留字段", "当前状态"], [
        ["节点—时段电压越限率", "node_time_voltage_violation_rate", "当前单场景核心计算未启用。"],
        ["改造线路长度", "modified_line_length", "当前未进入SUPPORTED_METRICS。"],
        ["年电能损耗", "annual_energy_loss", "当前未进入SUPPORTED_METRICS。"],
        ["年网损费用", "annual_loss_cost", "当前未进入SUPPORTED_METRICS。"],
    ], [2600, 3500, 3260], 9.2)

    add_heading(doc, "13. 上游交付验收规则", 1)
    checks = [
        "输入根目录同时存在 generation 和至少一个 analysis_i。",
        "parsed_proposals.json 的方案数量与 analysis_i 目录数量相等。",
        "方案索引连续，文件名索引与目录索引完全一致。",
        "全部JSON使用UTF-8且可被标准JSON解析器读取。",
        "所有文件的 scenario_id/scenario_name 一致，不混入第二个运行场景。",
        "所有百分比字段处于合理范围并采用0～100口径。",
        "电压节点记录具有 voltage_pu、min_voltage、max_voltage。",
        "线路和主变明细具有设备唯一键、实际值和对应允许值。",
        "N-1完整故障记录数等于 total_contingencies_run。",
        "N-1的 pass_count + failed_count 等于 total_contingencies_run。",
        "故障后电压越限数不大于 total_contingency_node_pairs。",
        "SCC参与开断裕度计算的记录全部明确标为3-PH，且开断电流大于0。",
        "暂态 stable_count + unstable_count = completed_count。",
        "暂态 completed_count + missing_count = expected_count。",
        "data_complete=true 时 missing_count 必须为0。",
        "最大相对功角字段不包含99999、Infinity、NaN或字符串。",
        "长度统一为km；如使用MILES，已确认源单位确实为英里。",
        "经济数据统一为元或元/年，不混用万元。",
    ]
    for item in checks:
        add_bullet(doc, "□ " + item)

    add_heading(doc, "14. 联调与运行步骤", 1)
    for text in [
        "将上游交付的整个CASE_INPUT目录复制到项目可访问的位置。",
        "确认CASE_INPUT直接包含generation和analysis_i，不要多套一层同名目录。",
        "在项目根目录激活虚拟环境。",
        "设置 REPORT_TEST_INPUT_DIR 指向CASE_INPUT的绝对路径。",
        "启动 bridge_server，并从前端生成比选报告。",
        "检查报告中的核心表是否仍显示数据缺失；如有缺失，先检查字段位置、文件命名和null值，不要在报告中人工填数。",
    ]:
        add_number(doc, text)
    add_code(doc, """$env:REPORT_TEST_INPUT_DIR = (Resolve-Path "C:\\上游交付目录\\CASE_INPUT").Path
$env:REPORT_TEST_INPUT_DIR

cd C:\\Users\\zyh\\Desktop\\dianwang_report_gen_0728\\powergrid_pipeline
python -m flask --app bridge_server:app run --host 127.0.0.1 --port 8081""")

    add_heading(doc, "15. 最小可交付集与推荐完整交付集", 1)
    add_table(doc, ["级别", "内容", "结果"], [
        ["最小可运行", "parsed_proposals + 每个方案4个汇总JSON；直接指标字段齐全", "报告可生成并计算核心指标，但溯源能力较弱。"],
        ["推荐正式交付", "最小集 + PF完整设备/节点明细 + N-1全部故障明细 + SCC全部3-PH母线 + 暂态每block明细", "可计算、可复核、可溯源，适合正式比选。"],
        ["完整经济比选", "推荐正式交付 + 单位造价、运维、网损、电价、折现、年限、停电损失等", "可进一步完成工程经济和LCC比较。"],
    ], [1800, 4750, 2810], 9.2)

    add_callout(doc, "最终交付要求", "上游交付时应同时提供一份 data_quality_report.json 作为验收附件，记录文件数量、记录数量、缺失字段、单位、仿真失败项及校验结果。该文件当前不参与计算，但用于判断数据是否适合进入正式报告。")

    add_heading(doc, "附录A：建议的 data_quality_report.json", 1)
    add_code(doc, {
        "schema_version": "1.0",
        "scenario_id": "summer_peak_single_scene",
        "proposal_count": 1,
        "analysis_indices": [1],
        "json_encoding": "UTF-8",
        "checks": {
            "directory_contract_passed": True,
            "scenario_consistency_passed": True,
            "all_required_files_present": True,
            "all_json_parseable": True,
            "units_validated": True
        },
        "proposal_quality": [{
            "proposal_index": 1,
            "pf_node_count": 5573,
            "pf_line_rating_coverage_rate": 68.595371,
            "n1_expected_count": 73,
            "n1_completed_count": 73,
            "scc_3ph_record_count": 232,
            "transient_expected_count": 147,
            "transient_completed_count": 145,
            "missing_files": ["block24.MSG", "block58.MSG"],
            "warnings": ["线路额定电流覆盖率不足", "暂态结果不完整"]
        }]
    })

    add_heading(doc, "附录B：接口责任边界", 1)
    add_table(doc, ["责任方", "责任"], [
        ["上游仿真/提取模块", "保证仿真结果完整；按本规范提取、计算汇总、统一单位、保持设备唯一键和输出JSON。"],
        ["规划/经济专业", "提供断面定义、安全限额、事故应急容量、电压评价范围、单位造价及经济参数。"],
        ["报告生成模块", "读取规范JSON，执行确定性公式、结构校验、缺失值显示、报告排版与导出。"],
        ["联合验收", "对至少一个方案进行人工复算，确认上游汇总值与报告核心表一致。"],
    ], [2100, 7260], 9.4)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


if __name__ == "__main__":
    print(build_document().resolve())
