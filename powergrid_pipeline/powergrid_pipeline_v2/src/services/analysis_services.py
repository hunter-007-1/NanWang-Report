# src/services/analysis_service.py

import os
import re
import json
import math
import random
from typing import Dict, Any, List
import pandas as pd


# 导入底层的核心模块
from ..core.grid_model_handler import GridModelHandler
from ..core.simulation_runner import SimulationRunner
from pybpa.dat.bpa_dat_data import DatL


class AnalysisService:
    """
    提供一系列独立的电网分析工具。
    每个方法都代表一个完整的分析任务，接收输入，并返回一份结构化的评估报告。
    """

    def __init__(self, config):
        self.config = config
        # AnalysisService 依赖 SimulationRunner 来执行计算
        self.runner = SimulationRunner(config)

    def _analyze_pf_result_file(self, pf_path: str, balanced_machine_output: bool = False) -> Dict[str, Any]:
        """【内部工具】: 专门用于解析.pf文件的可复用函数。"""
        if not os.path.exists(pf_path):
            return {'error': f"结果文件未找到: {pf_path}", 'is_convergent': False, 'overloaded_lines': []}

        try:
            with open(pf_path, 'r', encoding='gbk', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            return {'error': f"读取文件时出错: {e}", 'is_convergent': False, 'overloaded_lines': []}

        # 收敛性判断保持不变
        is_convergent = "计算结果收敛" in content
        
        # 使用代码1的解析逻辑
        try:
            # 提取五个数据部分
            sections = self._extract_data_sections(content)
            
            # 解析
            line_overload_data = self._parse_line_overload_section(sections[0])
            # transformer_overload_data = self._parse_transformer_overload_section(sections[1])
            # voltage_abnormal_data = self._parse_voltage_abnormal_section(sections[2])
            power_summary_data = self._parse_power_summary_section(sections[3])
            if balanced_machine_output:
                balance_summary_data = self._parse_balance_summary_section(sections[4])
            
            if line_overload_data is not None:
                    
                # 构建结果
                result = {
                    'is_convergent': is_convergent,
                    'overloaded_lines': line_overload_data,
                    # 'overloaded_transformers': transformer_overload_data,
                    # 'voltage_abnormal_nodes': voltage_abnormal_data,
                    # 'power_summary': power_summary_data
                    'balance_summary': balance_summary_data if balanced_machine_output else None
                }
            
            return result
            
        except Exception as e:
            return {'error': f"解析文件内容时出错: {e}", 'is_convergent': is_convergent, 'overloaded_lines': []}

    def _extract_data_sections(self, text):
        """
        从文本中提取五个指定的数据部分
        """
        # 定义要提取的五个部分的模式
        patterns = [
            r"\*  线路负载超过额定值 80\.0%的数据列表.*?\n(.*?)(?=\n\*|\n>>>|$)",
            r"\*  变压器负载超过额定值 80\.0%的数据列表.*?\n(.*?)(?=\n\*|\n>>>|$)",
            r"\*  低电压和过电压节点数据列表.*?\n(.*?)(?=\n\*|\n>>>|$)",
            r"\*  按分区输出发电、负荷、损耗和并联负荷数据列表.*?\n(.*?)(?=\n\*|\n>>>|$)",
            r"\*  区域平衡机、交换功率等数据.*?\n(.*?)(?=\n\*|\n>>>|$)"
        ]
        
        sections = []
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                sections.append(match.group(1).strip())
            else:
                sections.append("")
        
        return sections

    def _parse_line_overload_section(self, section):
        """
        解析线路负载超过额定值的数据部分
        使用空格分割文本行来提取信息
        只提取电流比例大于90.0%的数据行
        """
        lines = section.split('\n')
        data = []
        
        # 跳过表头行
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
                
            # 使用空格分割行
            parts = line.split()
            if len(parts) < 10:  # 确保有足够的数据列
                continue
                
            # 检查电流比例是否大于90.0%
            try:
                current_ratio = float(parts[-6])  # 电流比例是倒数第6个字段
                if current_ratio <= 90.0:
                    continue  # 跳过不满足条件的行
            except (ValueError, IndexError):
                continue  # 如果无法解析电流比例，跳过此行
                
            # 处理端点1名称
            endpoint1 = parts[0]
            if re.match(r'^[A-Z]', endpoint1):  # EQGEN043样式
                endpoint1 = endpoint1[:8]
            elif re.match(r'^[\u4e00-\u9fa5]', endpoint1):  # 只要第一个字符是中文
                endpoint1 = endpoint1[:5]
            else:
                endpoint1 = endpoint1.split()[0]  # 默认取第一个单词
            
            if parts[1][0].isnumeric():  # 只检查第一个字符
                endpoint2 = parts[2]
            else:
                endpoint2 = parts[1]
            
            if re.match(r'^[A-Z]', endpoint2):  # EQGEN043样式
                endpoint2 = endpoint2[:8]
            elif re.match(r'^[\u4e00-\u9fa5]', endpoint2):  # 只要第一个字符是中文
                endpoint2 = endpoint2[:5]
            else:
                endpoint2 = endpoint2.split()[0]  # 默认取第一个单词
            
            if '5' not in endpoint2 and '5' not in endpoint1:
                continue  # 只保留包含“5”的线路

            # 提取数值字段
            info = parts[-8:]  # 获取最后8个字段
                
            data.append({
                "问题描述": "线路负载超过额定值80.0%",
                "卡片类型": "L",
                "线路端点1": endpoint1,
                "线路端点2": endpoint2,
                "电流(A)": float(info[0]),
                "额定电流(A)": float(info[1]),
                "电流比例(%)": float(info[2]),
                "视在功率(MVA)": float(info[3]),
                "额定视在功率(MVA)": float(info[4]),
                "视在功率比例(%)": float(info[5]),
                "功率因数": float(info[6]),
                "角度(度)": float(info[7])
            })
        
        return data

    def _parse_transformer_overload_section(self, section):
        """
        解析变压器负载超过额定值的数据部分
        使用空格分割文本行来提取信息
        只提取比例大于130.0%的数据行
        """
        lines = section.split('\n')
        data = []
        
        # 跳过表头行
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
                
            # 使用空格分割行
            parts = line.split()
                
            # 检查比例是否大于130.0%
            try:
                ratio = float(parts[-2])  # 比例是倒数第2个字段
                if ratio <= 130.0:
                    continue  # 跳过不满足条件的行
            except (ValueError, IndexError):
                continue  # 如果无法解析比例，跳过此行
                
            # 处理端点1名称
            endpoint1 = parts[0]
            if re.match(r'^[A-Z]', endpoint1):  # EQGEN043样式
                endpoint1 = endpoint1[:8]
            elif re.match(r'^[\u4e00-\u9fa5]', endpoint1):  # 只要第一个字符是中文
                endpoint1 = endpoint1[:5]
            else:
                endpoint1 = endpoint1.split()[0]  # 默认取第一个单词
            
            # 处理端点2名称
            if parts[1][0].isnumeric():  # 只检查第一个字符
                endpoint2 = parts[2]
            else:
                endpoint2 = parts[1]

            
            if re.match(r'^[A-Z]', endpoint2):  # EQGEN043样式
                endpoint2 = endpoint2[:8]
            elif re.match(r'^[\u4e00-\u9fa5]', endpoint2):  # 只要第一个字符是中文
                endpoint2 = endpoint2[:5]
            else:
                endpoint2 = endpoint2.split()[0]  # 默认取第一个单词
            
            # 提取数值字段
            info = parts[-5:]  # 获取最后5个字段
                
            data.append({
                "问题描述": "变压器负载超过额定值80.0%",
                "卡片类型": "T",
                "变压器支路端点1": endpoint1,
                "变压器支路端点2": endpoint2,
                "回路号": int(info[0]),
                "视在功率(MVA)": float(info[1]),
                "额定容量(MVA)": float(info[2]),
                "比例(%)": float(info[3]),
                "功率因素": float(info[4])
            })
        
        return data

    def _parse_voltage_abnormal_section(self, section):
        """
        解析低电压和过电压节点数据部分
        使用空格分割文本行来提取信息
        """
        lines = section.split('\n')
        data = []
        
        # 跳过表头行
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
                
            # 使用空格分割行
            parts = line.split()
            if len(parts) < 7:  # 确保有足够的数据列
                continue
                
            # 处理分区名称
            region = parts[0]
            
            # 处理节点名称
            node = parts[1]
            if re.match(r'^[A-Z]{5}\d{3}$', node):  # EQGEN043样式
                node = node[:8]
            elif re.match(r'^[\u4e00-\u9fa5]', node):  # 只要第一个字符是中文
                node = node[:5]  
            else:
                node = node.split()[0]  # 默认取第一个单词
            
            # 组合类型字段（可能包含空格的部分）
            if parts[3].isalpha():
                type_part = parts[3]
            elif parts[4].isalpha():
                type_part = parts[4]
            else:
                type_part = ' '
            type_str = "B" + type_part.strip()

            # 获取数值字段（最后5个字段）
            voltage_values = parts[-5:]
            if(float(voltage_values[0]) < 500.0):
                continue  # 跳过电压等级低于500kV的行
            
            data.append({
                "问题描述": "低电压和过电压节点（<0.950||>1.052）",
                "分区": region,
                "节点": node,
                "类型": type_str,
                "电压(kV)": float(voltage_values[0]),
                "标幺电压(pu)": float(voltage_values[1]),
                "最小电压(pu)": float(voltage_values[2]),
                "最大电压(pu)": float(voltage_values[3]),
                "越界电压值(pu)": float(voltage_values[4])
            })
        
        return data

    def _parse_power_summary_section(self, section):
        """
        解析按分区输出发电、负荷、损耗和并联负荷数据列表
        只提取最后一行（总结行）
        """
        lines = section.split('\n')
        data = []
        
        # 查找总结行（以"总结"开头）
        for line in lines:
            if line.strip().startswith('总结'):
                # 使用空格分割，过滤空字符串
                parts = [part for part in line.split() if part]
                
                if len(parts) >= 10:  # 确保有足够的数据列（总结 + 9个数值）
                    data.append({
                        "问题描述": "系统功率总结",
                        "发电_MW": float(parts[1]),
                        "发电_MVar": float(parts[2]),
                        "发电_功率因数": float(parts[3]),
                        "负荷_MW": float(parts[4]),
                        "负荷_MVar": float(parts[5]),
                        "负荷_功率因数": float(parts[6]),
                        "损耗_MW": float(parts[7]),
                        "损耗_MVar": float(parts[8]),
                        "并联负荷_MVar": float(parts[9])
                    })
                break
        
        return data
    
    def _parse_balance_summary_section(self, section):
        """
        解析平衡机数据部分
        只解析第二个平衡机的"实际功率"
        """
        lines = section.split('\n')
        count = 0
        
        # 遍历每一行
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 使用空格分割行，并过滤空字符串
            parts = [p for p in line.split() if p]
            
            # 检查是否是数据行（跳过表头行和其他非数据行）
            if len(parts) >= 5 and not parts[0].endswith('数据'):
                # 如果是数据行
                count += 1
                if count == 3:  # 第二个平衡机
                    try:
                        data = []
                        data.append({
                            "区域": parts[0],
                            "平衡机": parts[1],
                            "实际功率": float(parts[3])
                        })
                        return data
                    except (ValueError, IndexError):
                        return None
        
        return None

    def analyze_power_flow(self, dat_path: str, balanced_machine_output: bool = False) -> Dict[str, Any]:
        """
        【工具1】: 对单个.dat文件执行潮流计算并生成评估报告。
        """
        # print(f"[Analysis] 正在对 {os.path.basename(dat_path)} 执行潮流分析...")
        
        # 1. 执行仿真 - 临时解决方案
        self.runner.run_power_flow(dat_path, 1)
        # print('潮流仿真成功')
        
        # 2. 分析结果
        pf_path = dat_path.replace(".dat", ".pf").replace(".DAT", ".pf")
        analysis_result = self._analyze_pf_result_file(pf_path, balanced_machine_output)
        
        # 3. 形成报告
        report = {
            "analysis_type": "Power Flow",
            "input_dat": os.path.basename(dat_path),
            "analysis": analysis_result
        }
        
        # # 清理生成的 .pf 文件
        # if os.path.exists(pf_path):
        #     try:
        #         os.remove(pf_path)
        #     except OSError:
        #         pass

        return report

    def analyze_n_security(self, dat_path: str, conditions: Dict[str, Any], run_dir: str, 
                           target_line: Dict[str, str] = None,
                           priority_lines: List[Dict[str, str]] = None,
                           early_stop_issue_limit: int = None,
                           full_scan: bool = False) -> Dict[str, Any]:
        """
        【工具2】: 对给定的.dat文件执行N-1安全分析。
        
        Args:
            dat_path: DAT文件路径
            conditions: 分析条件（包含 min_voltage_kv, ckt_id）
            run_dir: 运行目录
            target_line: 目标线路，格式为 {"node1": "节点1名称", "node2": "节点2名称"}
                        如果提供，先对目标线路做N-1分析。
            priority_lines: 需要在随机简测前优先校核的线路列表。每项可包含
                            node1/node2 或 NAME1/NAME2，并可选 ckt/CKT ID。
            early_stop_issue_limit: 完整扫描中一旦发现的问题数超过该值，立即停止分析。
                                    在候选方案筛选模式下，该值作为当前N-1剩余问题数x，
                                    简易N-1会随机抽取 x+3 条非一回线路。
            full_scan: True时执行完整全网N-1；False时只执行前置检测和简易随机N-1。
        """

        ckt_id = str(conditions.get("ckt_id", "2")).strip()
        ckt_num = int(ckt_id)

        print(f"[Analysis] 正在对 {os.path.basename(dat_path)} 执行N-{ckt_num-1}安全分析...")
        from pybpa.dat.bpa_dat import DAT
        
        dat = DAT.build_from(dat_path, True)
        
        all_voltage_branches = []
        target_branches = []
        non_first_circuit_branches = []

        def normalize_ckt_id(value):
            text = str(value or "").strip()
            if text.endswith('.0'):
                text = text[:-2]
            return text

        def is_first_circuit(ckt):
            return normalize_ckt_id(ckt) in ("", "1")

        def line_group_key(branch_info):
            return tuple(sorted([branch_info['name1'], branch_info['name2']]))

        def dedupe_by_line_group(branches):
            """Keep one representative outage per physical line corridor."""
            deduped = []
            seen = set()
            for branch_info in branches:
                key = line_group_key(branch_info)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(branch_info)
            return deduped

        for num in range(len(dat.branch)):
            card_type = dat.branch[num].get_value('TYPE').strip()
            base1 = dat.branch[num].get_value('BASE1')
            base2 = dat.branch[num].get_value('BASE2')
            
            if card_type != 'L':
                continue
                
            min_voltage = conditions.get("min_voltage_kv", 0)
            if base1 < min_voltage or base2 < min_voltage:
                continue
                
            branch_ckt = normalize_ckt_id(dat.branch[num].get_value('CKT ID'))
            name1 = dat.branch[num].get_value('NAME1').strip()
            name2 = dat.branch[num].get_value('NAME2').strip()
            
            branch_info = {
                'index': num,
                'name1': name1,
                'name2': name2,
                'ckt': branch_ckt,
                'base1': base1,
                'base2': base2
            }
            all_voltage_branches.append(branch_info)

            if not is_first_circuit(branch_ckt):
                non_first_circuit_branches.append(branch_info)

            if branch_ckt == ckt_id:
                target_branches.append(branch_info)
        
        raw_analysis_branches = non_first_circuit_branches or target_branches
        analysis_branches = dedupe_by_line_group(raw_analysis_branches)
        if not analysis_branches:
            return {"error": f"未找到任何电压≥{conditions.get('min_voltage_kv', 0)}kV且非一回线路进行N-{ckt_num-1}分析。"}
                
        print(f"  - 找到 {len(target_branches)} 条目标线路 (电压≥{conditions.get('min_voltage_kv', 0)}kV, CKT ID={ckt_id})。")
        print(f"  - 找到 {len(non_first_circuit_branches)} 条非一回线路，按端点去重后 {len(analysis_branches)} 条用于N-1校核。")

        n_results = []
        n_cases_dir = os.path.join(run_dir, f"n{ckt_num-1}_cases")
        os.makedirs(n_cases_dir, exist_ok=True)

        def is_same_branch(branch, name1, name2, ckt):
            branch_name1 = str(branch.get_value('NAME1', '')).strip()
            branch_name2 = str(branch.get_value('NAME2', '')).strip()
            branch_ckt = normalize_ckt_id(branch.get_value('CKT ID', ''))
            target_name1 = str(name1).strip()
            target_name2 = str(name2).strip()
            target_ckt = normalize_ckt_id(ckt)

            same_endpoints = (
                (target_name1 == branch_name1 and target_name2 == branch_name2) or
                (target_name1 == branch_name2 and target_name2 == branch_name1)
            )
            return same_endpoints and target_ckt == branch_ckt
        
        def branch_matches_line(branch_info, line_spec):
            if not line_spec:
                return False

            line_name1 = str(line_spec.get("node1") or line_spec.get("NAME1") or "").strip()
            line_name2 = str(line_spec.get("node2") or line_spec.get("NAME2") or "").strip()
            line_ckt = normalize_ckt_id(line_spec.get("ckt") or line_spec.get("CKT ID") or "")

            if not line_name1 or not line_name2:
                return False

            same_endpoints = (
                (line_name1 == branch_info['name1'] and line_name2 == branch_info['name2']) or
                (line_name1 == branch_info['name2'] and line_name2 == branch_info['name1'])
            )
            if not same_endpoints:
                return False

            if line_ckt and line_ckt != normalize_ckt_id(branch_info['ckt']):
                return False

            return True

        def result_has_issue(result):
            analysis = result.get("result", {}).get("analysis", {})
            return not analysis.get("is_convergent") or bool(analysis.get("overloaded_lines"))

        def collect_issues(results):
            return [res for res in results if result_has_issue(res)]

        def make_report(results, analysis_type=None, summary=None, **extra_fields):
            contingencies_with_issues = collect_issues(results)
            final_report = {
                "analysis_type": analysis_type or f"N-{ckt_num-1} Security",
                "input_dat": os.path.basename(dat_path),
                "total_contingencies_run": len(results),
                "summary": summary or f"发现 {len(contingencies_with_issues)} 个问题。",
                "contingencies_with_issues": contingencies_with_issues,
                "remaining_issues": len(contingencies_with_issues)
            }
            final_report.update(extra_fields)
            return final_report

        def find_priority_branch(line_spec):
            search_pools = [analysis_branches, target_branches, all_voltage_branches]
            for branches in search_pools:
                for branch_info in branches:
                    if branch_matches_line(branch_info, line_spec):
                        return branch_info
            return None

        def run_single_n1(branch_info, dat_path, n_cases_dir, orig_filename):
            index = branch_info['index']
            name1 = branch_info['name1']
            name2 = branch_info['name2']
            ckt = branch_info['ckt']
            
            print(f"  - N-{ckt_num-1} Case: {name1} - {name2} (CKT={ckt})")

            modified_dat = DAT.build_from(dat_path, True)
            branch_to_comment = modified_dat.branch[index]
            branch_to_comment.commented()

            related_l_plus_count = 0
            for branch in modified_dat.branch:
                if hasattr(branch, 'get_value') and \
                        str(branch.get_value('TYPE', '')).strip() == 'L+' and \
                        is_same_branch(branch, name1, name2, ckt):
                    branch.commented()
                    related_l_plus_count += 1

            if related_l_plus_count:
                print(f"    同时禁用了 {related_l_plus_count} 条匹配的L+扩展卡")
            
            case_name = f"{orig_filename}_{name1}_{name2}_ckt{ckt}.dat"
            case_dat_path = os.path.join(n_cases_dir, case_name)
            modified_dat.save_to_file(case_dat_path)
            
            case_report = self.analyze_power_flow(case_dat_path, balanced_machine_output=False)
            
            return {
                "contingency_branch_uid": f"{name1} - {name2} (CKT={ckt})",
                "result": case_report
            }
        
        orig_filename = os.path.splitext(os.path.basename(dat_path))[0]

        precheck_lines = []
        if target_line:
            precheck_lines.append({
                "node1": target_line.get("node1"),
                "node2": target_line.get("node2"),
                "ckt": target_line.get("ckt") or target_line.get("CKT ID"),
                "reason": "需解决问题对应线路"
            })
        for line in priority_lines or []:
            precheck_lines.append(line)

        seen_precheck_keys = set()
        prechecked_branch_indices = set()
        prechecked_line_groups = set()
        for line_spec in precheck_lines:
            branch_info = find_priority_branch(line_spec)
            line_label = line_spec.get("reason") or "前置线路"
            if not branch_info:
                print(f"  ⚠️ 未找到{line_label}: {line_spec}")
                continue

            precheck_key = line_group_key(branch_info)
            if precheck_key in seen_precheck_keys:
                continue
            seen_precheck_keys.add(precheck_key)
            prechecked_branch_indices.add(branch_info['index'])
            prechecked_line_groups.add(precheck_key)

            print(f"  🎯 先对{line_label}做N-1分析...")
            precheck_result = run_single_n1(branch_info, dat_path, n_cases_dir, orig_filename)
            n_results.append(precheck_result)

            if result_has_issue(precheck_result):
                print(f"  ⚠️ {line_label}N-1存在问题，跳过后续N-1分析")
                return make_report(
                    n_results,
                    analysis_type=f"N-{ckt_num-1} Security (Precheck Failed)",
                    summary=f"发现 {len(collect_issues(n_results))} 个问题。{line_label}N-1存在问题，跳过后续分析。",
                    precheck_failed=True,
                    precheck_failed_reason=line_label,
                    prechecked_contingencies=len(n_results),
                    full_scan=full_scan,
                    screening_mode=not full_scan
                )

        if not full_scan:
            if precheck_lines:
                print(f"  ✅ 前置线路N-1无问题，继续简易随机N-1测试...")

            try:
                remaining_issue_count = float(early_stop_issue_limit)
                if not math.isfinite(remaining_issue_count):
                    remaining_issue_count = 0
            except (TypeError, ValueError):
                remaining_issue_count = 0
            sample_size = max(0, int(remaining_issue_count)) + 3

            sample_candidates = [
                branch_info for branch_info in analysis_branches
                if branch_info['index'] not in prechecked_branch_indices
                and line_group_key(branch_info) not in prechecked_line_groups
            ]
            if len(sample_candidates) <= sample_size:
                sampled_branches = sample_candidates
            else:
                sampled_branches = random.sample(sample_candidates, sample_size)

            print(f"  🎲 简易N-1测试：随机抽取 {len(sampled_branches)}/{len(sample_candidates)} 条非一回线路（目标 x+3={sample_size}）")
            sample_results = []
            for branch_info in sampled_branches:
                result = run_single_n1(branch_info, dat_path, n_cases_dir, orig_filename)
                n_results.append(result)
                sample_results.append(result)

            sampled_issue_count = len(collect_issues(sample_results))
            screening_discarded = bool(sample_results) and sampled_issue_count == len(sample_results)
            if screening_discarded:
                print("  ⏹️ 简易N-1抽样结果全部存在问题，舍弃该方案")

            return make_report(
                n_results,
                analysis_type=f"N-{ckt_num-1} Security (Screening)",
                summary=f"发现 {len(collect_issues(n_results))} 个问题。已完成前置检测和简易随机N-1测试。",
                screening_mode=True,
                full_scan=False,
                random_sample_size_requested=sample_size,
                random_sample_candidates=len(sample_candidates),
                random_sample_contingencies_run=len(sample_results),
                random_sample_issues=sampled_issue_count,
                screening_discarded=screening_discarded,
                screening_discard_reason="简易N-1抽样结果全部存在问题" if screening_discarded else None,
                prechecked_contingencies=len(prechecked_branch_indices)
            )

        if precheck_lines:
            print(f"  ✅ 前置线路N-1无问题，继续完整全网N-1分析...")
        
        print(f"  🔄 执行完整全网N-1分析...")
        for branch_info in analysis_branches:
            if branch_info['index'] in prechecked_branch_indices or line_group_key(branch_info) in prechecked_line_groups:
                continue
            
            result = run_single_n1(branch_info, dat_path, n_cases_dir, orig_filename)
            n_results.append(result)

            issue_count = len(collect_issues(n_results))
            if early_stop_issue_limit is not None and issue_count > early_stop_issue_limit:
                print(f"  ⏹️ 已发现 {issue_count} 个N-1问题，超过上一轮基准 {early_stop_issue_limit}，提前停止全网N-1分析")
                return make_report(
                    n_results,
                    summary=f"发现 {issue_count} 个问题。已超过上一轮基准 {early_stop_issue_limit}，提前停止全网N-1分析。",
                    early_stopped=True,
                    early_stop_issue_limit=early_stop_issue_limit,
                    full_scan=True
                )

        return make_report(n_results, full_scan=True)

    def _create_scset_from_template(self, template_path: str, target_path: str) -> bool:
        """【内部工具】: 从模板创建.scset文件。"""
        try:
            if not os.path.exists(template_path):
                print(f"    - 错误: 找不到模板文件 {template_path}")
                return False
            
            with open(template_path, 'r', encoding='gbk', errors='ignore') as f:
                content = f.read()
            
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, 'w', encoding='gbk') as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"    - 创建.scset文件时出错: {e}")
            return False

    def _analyze_scc_result_file(self, rpt_path: str) -> Dict[str, Any]:
        """【内部工具】: 解析短路计算生成的.rpt文件。"""
        if not os.path.exists(rpt_path):
            return {'error': f"结果文件未找到: {rpt_path}", 'contingencies_with_issues': []}

        contingencies_with_issues = []
        all_buses = []  # 存储所有母线信息
        
        try:
            with open(rpt_path, 'r', encoding='gbk') as file:
                lines = file.readlines()
            
            # 获取阈值
            threshold = self.config.assessment_thresholds.short_circuit_current_kA
            
            # 跳过文件头，找到数据开始位置
            data_started = False
            for line in lines:
                # 跳过空行和注释行
                if not line.strip() or line.startswith('.#') or 'DSP短路电流计算分析程序' in line:
                    continue
                
                # 检查是否到达数据行（包含电压等级和故障类型）
                if not data_started and ('525.0' in line or 'B' in line or '3-PH' in line or '1-PH' in line):
                    data_started = True
                
                if data_started:
                    # 修改正则表达式，将分区字段作为字符串提取
                    # 匹配模式：母线名称 电压 类型 故障类型 遮断电流 短路容量 短路电流 阻抗数据... 分区
                    pattern = r'\"([^\"]+)\"\s+(-?\d+\.\d+)\s+(\w+)\s+(\S+)\s+([-?\d.]+)\s+([-?\d.]+)\s+([-?\d.]+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+\"([^\"]+)\"'
                    match = re.search(pattern, line)
                    
                    if match:
                        bus_name = match.group(1).strip()
                        voltage = float(match.group(2))
                        bus_type = match.group(3)
                        fault_type = match.group(4)
                        breaker_current = float(match.group(5))  # 遮断电流
                        short_circuit_capacity = float(match.group(6))  # 短路容量
                        short_circuit_current = float(match.group(7))  # 短路电流(第七列)
                        r1 = float(match.group(8))  # 正序等值阻抗R1
                        x1 = float(match.group(9))  # 正序等值阻抗X1
                        r2 = float(match.group(10))  # 负序等值阻抗R2
                        x2 = float(match.group(11))  # 负序等值阻抗X2
                        r0 = float(match.group(12))  # 零序等值阻抗R0
                        x0 = float(match.group(13))  # 零序等值阻抗X0
                        partition = match.group(14).strip()  # 分区字段作为字符串
                        
                        # 记录所有母线信息
                        bus_info = {
                            'bus_name': bus_name,
                            'voltage_kV': voltage,
                            'bus_type': bus_type,
                            'fault_type': fault_type,
                            'breaker_current_kA': breaker_current,
                            'short_circuit_capacity_MVA': short_circuit_capacity,
                            'short_circuit_current_kA': short_circuit_current,
                            'r1': r1,
                            'x1': x1,
                            'r2': r2,
                            'x2': x2,
                            'r0': r0,
                            'x0': x0,
                            'partition': partition
                        }
                        all_buses.append(bus_info)
                        
                        # 检查短路电流是否超过阈值
                        if short_circuit_current > threshold:
                            contingencies_with_issues.append({
                                'bus_name': bus_name,
                                'voltage_kV': voltage,
                                'bus_type': bus_type,
                                'fault_type': fault_type,
                                'breaker_current_kA': breaker_current,
                                'short_circuit_capacity_MVA': short_circuit_capacity,
                                'short_circuit_current_kA': short_circuit_current,
                                'r1': r1,
                                'x1': x1,
                                'r2': r2,
                                'x2': x2,
                                'r0': r0,
                                'x0': x0,
                                'partition': partition
                                })
                            
        except FileNotFoundError:
            return {'error': f"找不到文件 {rpt_path}", 'contingencies_with_issues': []}
        except UnicodeDecodeError:
            return {'error': "文件编码不是GBK", 'contingencies_with_issues': []}
        except Exception as e:
            return {'error': f"解析文件时发生错误: {e}", 'contingencies_with_issues': []}
                
        return {
            'total_buses': len(all_buses),
            'threshold_kA': threshold,
            'summary': f"发现 {len(contingencies_with_issues)}。",
            'contingencies_with_issues': contingencies_with_issues,
            'remaining_issues': len(contingencies_with_issues),
            # 'all_buses': all_buses,  # 返回所有母线信息
        }

    def analyze_short_circuit(self, dat_path: str, swi_path: str, scset_template_path: str) -> Dict[str, Any]:
        """
        【工具3】: 对给定的.dat文件执行短路电流分析。
        """
        print(f"[Analysis] 正在对 {os.path.basename(dat_path)} 执行短路电流分析...")

        # 1. 准备.scset文件
        scset_path = dat_path.replace(".dat", ".scset").replace(".DAT", ".scset")
        if not self._create_scset_from_template(scset_template_path, scset_path):
            return {"error": "无法创建.scset文件，分析终止。"}

        # 2. 执行仿真
        success, log = self.runner.run_short_circuit(dat_path, swi_path, scset_path)
        
        # 3. 分析结果
        rpt_path = dat_path.replace(".dat", ".rpt").replace(".DAT", ".rpt")
        analysis_result = self._analyze_scc_result_file(rpt_path)
        
        # 4. 形成报告
        report = {
            "analysis_type": "Short Circuit",
            "input_dat": os.path.basename(dat_path),
            "execution_success": success,
            "analysis": analysis_result,
            "remaining_issues": analysis_result.get('remaining_issues', []) if success else [],
        }

        # # 5. 清理中间文件
        # for ext in [".scset", ".csv", ".rpt", ".log"]:
        #     file_to_clean = dat_path.replace(".dat", ext).replace(".DAT", ext)
        #     if os.path.exists(file_to_clean):
        #         try:
        #             os.remove(file_to_clean)
        #         except OSError:
        #             pass
                    
        return report
    
    def analyze_transient_stability(self, dat_path: str, swi_path: str, lsd_path: str) -> Dict[str, Any]:
        """
        【工具4】: 对给定的.dat文件执行暂态稳定分析。
        """
        print(f"[Analysis] 正在对 {os.path.basename(dat_path)} 执行暂态稳定分析...")
        
        # 调用SimulationRunner的TSSIM方法
        try:
            # 这里直接调用SimulationRunner的TSSIM方法
            result = self._process_transient_stability(dat_path, lsd_path, swi_path)
            
            report = {
                "analysis_type": "Transient Stability",
                "input_dat": os.path.basename(dat_path),
                "execution_success": True,
                "analysis": result
            }
            
            return report
            
        except Exception as e:
            return {
                "analysis_type": "Transient Stability", 
                "input_dat": os.path.basename(dat_path),
                "execution_success": False,
                "error": f"暂态稳定分析失败: {str(e)}"
            }

    def _process_transient_stability(self, dat_path: str, lsd_path: str, swi_path: str) -> Dict[str, Any]:
        """
        【内部工具】: 处理.lsd和.swi文件，执行暂态分析。
        """
        # 读取.lsd文件
        try:
            with open(lsd_path, 'r', encoding='gbk') as lsd_file:
                lsd_content = lsd_file.readlines()
        except Exception as e:
            return {'error': f"读取.lsd文件失败: {e}"}
        
        # 查找所有以.C开头的数据块
        blocks = self._extract_blocks_from_lsd(lsd_content)
        
        if not blocks:
            return {'error': "在.lsd文件中未找到有效的数据块", 'processed_blocks': 0}
        
        print(f"  - 找到 {len(blocks)} 个数据块")
        
        # 处理每个数据块
        processed_results = []
        for idx, block in enumerate(blocks, 1):
            print(f"  - 处理第 {idx}/{len(blocks)} 个数据块...")
            
            # 处理数据块：去掉后三行行首的点
            processed_block = self._process_lsd_block(block)
            
            # 创建新的swi文件
            new_swi_path = self._create_transient_swi_file(swi_path, processed_block, idx, dat_path)
            
            if new_swi_path:
                # 调用SimulationRunner的TSSIM方法
                try:
                    # 使用SimulationRunner的run_TSSIM方法
                    self.runner.run_TSSIM(dat_path, new_swi_path)
                    print("调用暂态分析成功")
                    
                    # 记录处理结果
                    block_result = {
                        'block_index': idx,
                        'swi_file': os.path.basename(new_swi_path),
                    }
                    processed_results.append(block_result)
                    
                    print(f"    - 第 {idx} 个数据块处理完成")
                except Exception as e:
                    print(f"    - 调用暂态分析失败: {e}")
                    processed_results.append({
                        'block_index': idx,
                        'error': str(e)
                    })
            else:
                print(f"    - 创建新swi文件失败: 第 {idx} 个数据块")
                processed_results.append({
                    'block_index': idx,
                    'error': "创建SWI文件失败"
                })
        
        return {
            'total_blocks': len(blocks),
            'processed_blocks': len([r for r in processed_results if 'error' not in r and r.get('execution_success', False)]),
            'results': processed_results
        }

    def _extract_blocks_from_lsd(self, lsd_content):
        """
        【内部工具】: 从.lsd内容中提取所有以.C开头的数据块
        每个数据块包含.C行和接下来的三行
        """
        blocks = []
        i = 0
        pattern = re.compile(r'^\.C')
        
        while i < len(lsd_content):
            line = lsd_content[i].strip()
            if pattern.match(line):
                # 找到以.C开头的行，提取这个块（当前行+接下来三行）
                if i + 3 < len(lsd_content):
                    block = [
                        lsd_content[i].rstrip('\n\r'),
                        lsd_content[i+1].rstrip('\n\r'),
                        lsd_content[i+2].rstrip('\n\r'),
                        lsd_content[i+3].rstrip('\n\r')
                    ]
                    blocks.append(block)
                    i += 4  # 跳过这个块，继续查找下一个
                else:
                    i += 1
            else:
                i += 1
        
        return blocks

    def _process_lsd_block(self, block):
        """
        【内部工具】: 处理数据块：去掉后三行行首的点
        """
        processed_block = []
        
        # 第一行（.C行）保持不变
        processed_block.append(block[0])
        
        # 处理后三行，去掉行首的点
        for i in range(1, 4):
            line = block[i]
            if line.startswith('.'):
                # 去掉行首的点
                processed_line = line[1:] if len(line) > 1 else ''
            else:
                processed_line = line
            processed_block.append(processed_line)
        
        return processed_block

    def _create_transient_swi_file(self, original_swi_path, processed_block, block_index, dat_path):
        """
        【内部工具】: 创建新的swi文件，用处理后的块替换4-7行
        """
        try:
            # 读取原始swi文件
            with open(original_swi_path, 'r', encoding='gbk') as swi_file:
                swi_content = swi_file.readlines()
            
            # 检查文件行数是否足够
            if len(swi_content) < 7:
                print(f"    - 警告: .swi文件行数不足7行，实际行数: {len(swi_content)}")
                return None
            
            # 替换4-7行（索引3-6）
            for j in range(4):
                if 3 + j < len(swi_content):
                    # 确保每行都有换行符
                    new_line = processed_block[j]
                    if not new_line.endswith('\n'):
                        new_line += '\n'
                    swi_content[3 + j] = new_line
            
            # 生成新文件名
            original_dir = os.path.dirname(dat_path)
            original_name = os.path.splitext(os.path.basename(dat_path))[0]
            new_swi_name = f"{original_name}_block{block_index}.swi"
            new_swi_path = os.path.join(original_dir, new_swi_name)
            
            # 确保目录存在
            os.makedirs(original_dir, exist_ok=True)
            
            # 写入新文件
            with open(new_swi_path, 'w', encoding='gbk') as new_swi_file:
                new_swi_file.writelines(swi_content)
            
            print(f"    - 创建新文件: {new_swi_path}")
            return new_swi_path
            
        except Exception as e:
            print(f"    - 创建新swi文件失败: {e}")
            return None

    def analyze_stability_msg(self, msg_folder_path: str, output_json: str = None) -> Dict[str, Any]:
        """
        【工具5】: 解析.MSG文件，提取电压失稳节点和频率失稳发电机信息。
        基于代码3的功能，但封装成与代码1相同的接口。
        """
        print(f"[Analysis] 正在解析文件夹 {msg_folder_path} 中的.MSG文件...")
        
        # 调用代码3的功能
        try:
            result = self._process_msg_files(msg_folder_path, output_json)
            
            # 形成与代码1相同格式的报告
            report = {
                "analysis_type": "Stability MSG Analysis",
                "input_folder": msg_folder_path,
                "execution_success": True,
                "analysis": result
            }
            
            return report
            
        except Exception as e:
            return {
                "analysis_type": "Stability MSG Analysis",
                "input_folder": msg_folder_path,
                "execution_success": False,
                "error": f"MSG文件分析失败: {str(e)}"
            }

    def _process_msg_files(self, folder_path: str, output_json: str = None) -> Dict[str, Any]:
        """
        【内部工具】: 实现代码3的功能 - 处理固定文件夹中的所有.MSG文件。
        """
        if not os.path.exists(folder_path):
            return {'error': f"文件夹 '{folder_path}' 不存在"}
        
        # 查找所有.MSG文件
        msg_files = []
        for filename in os.listdir(folder_path):
            if filename.lower().endswith('.msg'):
                msg_files.append(os.path.join(folder_path, filename))
        
        if not msg_files:
            return {'error': "在指定文件夹中未找到.MSG文件"}
        
        print(f"  - 找到 {len(msg_files)} 个.MSG文件")
        
        # 处理所有文件
        results = {
            "folder_path": folder_path,
            "total_files": len(msg_files),
            "files_with_instability": 0,
            "files": []
        }
        
        marked_files = []
        
        for file_path in msg_files:
            print(f"  - 正在处理: {os.path.basename(file_path)}")
            result = self._parse_single_msg_file(file_path)
            results["files"].append(result)
            
            # 检查是否需要标记
            if result["has_voltage_instability"] or result["has_frequency_instability"]:
                marked_files.append(os.path.basename(file_path))
                print(f"    ⚠️  需要标记 - 发现不稳定情况")
                
                if result["has_voltage_instability"]:
                    print(f"      - 电压失稳节点数: {len(result['voltage_instability_nodes'])}")
                if result["has_frequency_instability"]:
                    print(f"      - 频率失稳发电机数: {len(result['frequency_instability_generators'])}")
            else:
                print(f"    ✓ 正常 - 无不稳定情况")
        
        # 统计结果
        results["files_with_instability"] = len(marked_files)
        
        # # 如果需要保存到JSON文件
        # if output_json:
        #     try:
        #         os.makedirs(os.path.dirname(output_json), exist_ok=True)
        #         with open(output_json, 'w', encoding='utf-8') as f:
        #             json.dump(results, f, ensure_ascii=False, indent=2)
        #         print(f"  - 结果已保存到: {output_json}")
        #     except Exception as e:
        #         print(f"  - 保存JSON文件时出错: {e}")
        
        return results

    def _parse_single_msg_file(self, file_path: str) -> Dict[str, Any]:
        """
        【内部工具】: 解析单个.MSG文件，提取电压失稳节点和频率失稳发电机信息。
        """
        result = {
            "filename": os.path.basename(file_path),
            "has_voltage_instability": False,
            "has_frequency_instability": False,
            "voltage_instability_nodes": [],
            "frequency_instability_generators": [],
        }
        
        try:
            with open(file_path, 'r', encoding='gbk') as file:
                content = file.read()
                
            # 查找电压失稳节点列表
            voltage_match = re.search(
                r'电压失稳节点列表：\s*\n(.*?)(?=\n\s*\n|\Z)', 
                content, 
                re.DOTALL
            )
            
            if voltage_match:
                voltage_content = voltage_match.group(1).strip()
                if voltage_content != "无" and not voltage_content.startswith("节点名"):
                    # 解析电压失稳节点数据
                    lines = voltage_content.split('\n')
                    header_found = False
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                            
                        if "节点名" in line and "起始时刻" in line:
                            header_found = True
                            continue
                            
                        if header_found and line != "无":
                            # 解析数据行（假设数据以空格分隔）
                            parts = re.split(r'\s+', line)
                            if len(parts) >= 7:
                                node_info = {
                                    "节点名": parts[0],
                                    "起始时刻": parts[1] if len(parts) > 1 else "",
                                    "持续时间": parts[2] if len(parts) > 2 else "",
                                    "电压阈值": parts[3] if len(parts) > 3 else "",
                                    "子网": parts[4] if len(parts) > 4 else "",
                                    "子网节点数": parts[5] if len(parts) > 5 else "",
                                    "子网发电机数": parts[6] if len(parts) > 6 else ""
                                }
                                result["voltage_instability_nodes"].append(node_info)
                                result["has_voltage_instability"] = True
            
            # 查找频率失稳发电机列表
            frequency_match = re.search(
                r'频率失稳发电机列表：\s*\n(.*?)(?=\n\s*\n|\Z)', 
                content, 
                re.DOTALL
            )
            
            if frequency_match:
                frequency_content = frequency_match.group(1).strip()
                if frequency_content != "无" and not frequency_content.startswith("发电机名"):
                    # 解析频率失稳发电机数据
                    lines = frequency_content.split('\n')
                    header_found = False
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                            
                        if "发电机名" in line and "组别" in line:
                            header_found = True
                            continue
                            
                        if header_found and line != "无":
                            # 解析数据行
                            parts = re.split(r'\s+', line)
                            if len(parts) >= 8:
                                generator_info = {
                                    "发电机名": parts[0],
                                    "组别": parts[1] if len(parts) > 1 else "",
                                    "时刻": parts[2] if len(parts) > 2 else "",
                                    "失稳频率": parts[3] if len(parts) > 3 else "",
                                    "频率阈值": parts[4] if len(parts) > 4 else "",
                                    "子网": parts[5] if len(parts) > 5 else "",
                                    "子网节点数": parts[6] if len(parts) > 6 else "",
                                    "子网发电机数": parts[7] if len(parts) > 7 else ""
                                }
                                result["frequency_instability_generators"].append(generator_info)
                                result["has_frequency_instability"] = True
                                
        except Exception as e:
            result["error"] = f"解析文件时出错: {str(e)}"
            
        return result

    def adjust_generator(self, dir, scheme):
        """
        【工具2】: 修改发电机参数，例如将所有类型为 'Q' 的发电机的 GEN_P 设置为 0。
        先读取同一目录下的pf_report.json文件，检查balance_summary中的实际功率是否为负，
        只有为负时才执行修改操作。
        返回实际功率值actual_power，失败时返回null
        """
        try:
            # 1. 获取pf_report.json文件路径
            # 假设pf_report.json与dat文件在同一目录下

            dat_path = os.path.join(dir, 'application', f'method_{scheme}', f'applied_model_{scheme}.dat')
            report_path = os.path.join(dir, f'analysis_{scheme}', f'pf_report_{scheme}.json')

            # 2. 读取并解析json文件
            if not os.path.exists(report_path):
                return None
                
            with open(report_path, 'r', encoding='utf-8') as f:
                report_data = json.load(f)
            
            # 3. 获取balance_summary中的实际功率
            if "analysis" not in report_data or "balance_summary" not in report_data["analysis"]:
                return None
            
            balance_summary = report_data["analysis"]["balance_summary"]
            if not balance_summary:
                return None
            
            # 假设我们需要第一个平衡机的实际功率
            first_balance = balance_summary[0]
            actual_power = first_balance.get("实际功率")
            
            if actual_power is None:
                return None
            
            # 4. 检查实际功率是否为负，为负时执行修改操作
            if actual_power < 0:
                model_handler = GridModelHandler(dat_path)
                model_handler.modify_generator()
                model_handler.save(dat_path)  # 保存修改后的模型
                
                print(f"[Application] 实际功率为负({actual_power})，已成功调整发电机参数并保存到 '{dat_path}'")
            
            return actual_power
            
        except json.JSONDecodeError as e:
            return None
        except Exception as e:
            return None
        
    def adjust_generator_all(self, dir, scheme):
        """
        【工具2】: 修改发电机参数，例如将所有类型为 'Q' 的发电机的 GEN_P 设置为 0。
        不检查实际功率状态，直接调整。
        """
        dat_path = os.path.join(dir, 'application', f'method_{scheme}', f'applied_model_{scheme}.dat')
        pf_report_path = os.path.join(dir, f'analysis_{scheme}', f'pf_report_{scheme}.json')

        actual_power = self.adjust_generator(dir, scheme)
        print(f"[Application] 初始实际功率: {actual_power}")
        while actual_power < 0:
            report = self.analyze_power_flow(dat_path, balanced_machine_output=True)
            with open(pf_report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            actual_power = self.adjust_generator(dir, scheme)
        print(f"[Application] 实际功率已调整为非负值({actual_power})，调整完成。")
