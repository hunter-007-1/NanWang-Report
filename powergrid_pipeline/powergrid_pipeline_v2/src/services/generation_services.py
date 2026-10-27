import os
import re
import json
import glob
from openai import OpenAI
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from src.utils.config import load_config_as_dotdict
from .analysis_services import AnalysisService

SCHEMES_PER_GENERATION = 10


def _format_scheme_name_list(count: int) -> str:
    return "、".join(f"方案{i}" for i in range(1, count + 1))


class SelectionService:
    """
    【选择服务】: 负责解析N-1安全分析和短路电流分析报告，选择最优方案并提取关键信息
    """

    def __init__(self, pf_threshold: float = 80.0, scc_threshold: float = 60.0):
        self.pf_threshold = pf_threshold  # 负载阈值
        self.scc_threshold = scc_threshold  # 短路电流阈值

    def parse_pf_report(self, file_path: str) -> Dict[str, Any]:
        """
        解析潮流分析报告文件

        Args:
            file_path (str): PF报告文件路径

        Returns:
            Dict包含潮流分析信息，如果有错误则包含error字段
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            result = {
                "analysis_type": "power_flow",
                "file_path": file_path,
                "is_convergent": data["analysis"]["is_convergent"]
            }

            result["analysis_data"] = data["analysis"]

            # 检查是否有error字段
            if "error" in result["analysis_data"]:
                result["error"] = result["analysis_data"]["error"]
                result["has_error"] = True
            else:
                result["has_error"] = False

            return result

        except Exception as e:
            print(f"❌ 解析潮流分析报告失败 {file_path}: {e}")
            return {
                "analysis_type": "power_flow",
                "file_path": file_path,
                "error": f"解析文件失败: {str(e)}",
                "has_error": True
            }

    def parse_n1_report(self, file_path: str) -> Dict[str, Any]:
        """
        解析单个N-1报告文件
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 提取方案编号
            scheme_num = self._extract_scheme_number(file_path)

            # 优先使用结构化字段；旧报告没有该字段时再从summary解析。
            summary = data.get("summary", "")
            remaining_issues = data.get("remaining_issues")
            if remaining_issues is None:
                remaining_issues = self._parse_remaining_issues(summary)

            result = {
                "scheme_number": scheme_num,
                "remaining_issues": remaining_issues,
                "file_path": file_path,
                "contingencies": data.get("contingencies_with_issues", []),
                "precheck_failed": bool(data.get("precheck_failed")),
                "early_stopped": bool(data.get("early_stopped")),
                "screening_mode": bool(data.get("screening_mode")),
                "screening_discarded": bool(data.get("screening_discarded")),
                "full_scan": bool(data.get("full_scan"))
            }

            return result

        except Exception as e:
            print(f"❌ 解析N-1报告失败 {file_path}: {e}")
            return {}

    def parse_scc_report(self, file_path: str) -> Dict[str, Any]:
        """
        解析短路电流分析报告文件

        Args:
            file_path (str): SCC报告文件路径

        Returns:
            Dict包含短路分析信息
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 解析summary获取剩余问题数
            summary = data.get("analysis", {}).get("summary", "")
            remaining_issues = self._parse_remaining_issues(summary)

            # 获取第一个故障实例
            first_contingency = None
            contingencies = data.get("analysis", {}).get("contingencies_with_issues", [])
            if contingencies:
                first_contingency = contingencies[0]

            result = {
                "analysis_type": "short_circuit",
                "remaining_issues": remaining_issues,
                "file_path": file_path,
                "first_contingency": first_contingency
            }

            return result

        except Exception as e:
            print(f"❌ 解析短路电流报告失败 {file_path}: {e}")
            return {}

    def parse_combined_reports(self, analysis_dir: str) -> Dict[str, Any]:
        """
        组合解析N-1报告、短路电流报告和潮流分析报告

        Args:
            analysis_dir: 分析目录路径

        Returns:
            组合的分析结果
        """
        # 查找PF报告文件
        pf_pattern = os.path.join(analysis_dir, "pf_report_*.json")
        pf_files = glob.glob(pf_pattern)

        # 解析潮流分析报告
        pf_data = {}
        pf_error = None
        if pf_files:
            pf_data = self.parse_pf_report(pf_files[0])
            if pf_data.get("has_error", False):
                pf_error = pf_data.get("error", "潮流分析报告存在错误")

        # 查找N-1报告文件
        n1_pattern = os.path.join(analysis_dir, "n1_report_*.json")
        n1_files = glob.glob(n1_pattern)

        if not n1_files:
            print(f"❌ 在目录 {analysis_dir} 中未找到N-1报告文件")
            return {}

        # 解析第一个N-1报告
        n1_data = self.parse_n1_report(n1_files[0])
        if not n1_data:
            return {}

        n1_issues = n1_data.get("remaining_issues", 0)

        # 查找短路电流报告文件
        scc_pattern = os.path.join(analysis_dir, "scc_report_*.json")
        scc_files = glob.glob(scc_pattern)

        # 解析短路电流报告
        scc_data = {}
        if scc_files:
            scc_data = self.parse_scc_report(scc_files[0])

        return {
            "pf_data": pf_data,
            "n1_data": n1_data,
            "scc_data": scc_data,
            "pf_error": pf_error,
            "n1_issues": n1_issues,
            "scc_issues": scc_data.get("remaining_issues", 0) if scc_data else 0
        }

    def generate_combined_analysis_report(self, analysis_dir: str) -> str:
        """
        生成组合分析报告

        Args:
            analysis_dir: 分析目录路径

        Returns:
            组合的分析报告文本
        """
        combined_data = self.parse_combined_reports(analysis_dir)

        if not combined_data:
            return "无法解析分析报告。"

        n1_issues = combined_data["n1_issues"]
        scc_data = combined_data["scc_data"]

        report_parts = []

        # N-1报告分析
        if n1_issues > 0:
            n1_report = self.generate_n1_analysis_report(combined_data["n1_data"])
            report_parts.append(n1_report)
        else:
            report_parts.append("N-1安全分析无过载问题。")

        return "\n".join(report_parts)

    def generate_scc_analysis_report(self, scc_data: Dict[str, Any]) -> str:
        """
        生成短路电流分析报告

        Args:
            scc_data: 短路电流分析数据

        Returns:
            格式化的短路电流问题描述文本
        """
        first_contingency = scc_data.get("first_contingency")
        if not first_contingency:
            return "无法解析短路电流故障实例信息。"

        # 提取故障信息
        bus_name = first_contingency.get("bus_name", "未知节点")
        voltage_kv = first_contingency.get("voltage_kV", 0)
        fault_type = first_contingency.get("fault_type", "")
        breaker_current = first_contingency.get("breaker_current_kA", 0)
        short_circuit_capacity = first_contingency.get("short_circuit_capacity_MVA", 0)
        short_circuit_current = first_contingency.get("short_circuit_current_kA", 0)
        r1 = first_contingency.get("r1", 0)
        x1 = first_contingency.get("x1", 0)
        r2 = first_contingency.get("r2", 0)
        x2 = first_contingency.get("x2", 0)
        r0 = first_contingency.get("r0", 0)
        x0 = first_contingency.get("x0", 0)
        partition = first_contingency.get("partition", "")

        # 构建报告
        report = f'B卡节点"{bus_name}"的短路电流为{short_circuit_current}kA，超过阈值{self.scc_threshold}kA。该线路的其他信息如下：\n'
        report += f'节点电压为{voltage_kv}kV，故障类型为"{fault_type}"，遮断电流为{breaker_current}kA，短路容量为{short_circuit_capacity}MVA，短路电流为{short_circuit_current}kA，'
        report += f'正序等值电阻（R1）为{r1}欧，正序等值电抗（X1）为{x1}欧，负序等值电阻（R2）为{r2}欧，负序等值电抗（X2）为{x2}欧，'
        report += f'零序等值电阻为（R0）为{r0}欧，零序等值电抗（X0）为{x0}欧，分区为"{partition}"'

        return report

    def parse_folder(self, folder_path: str) -> Dict[str, Any]:
        """
        解析文件夹中的所有N-1报告，选择最优方案

        Args:
            folder_path (str): 包含N-1报告的文件夹路径

        Returns:
            Dict包含最优方案信息
        """
        # 查找所有n1_report_{i}.json文件
        pattern = os.path.join(folder_path, "n1_report_*.json")
        n1_files = glob.glob(pattern)

        if not n1_files:
            print(f"❌ 在文件夹 {folder_path} 中未找到N-1报告文件")
            return {}

        print(f"📁 找到 {len(n1_files)} 个N-1报告文件")

        # 解析所有文件并选择剩余问题数最少的
        best_scheme = None
        min_issues = float('inf')

        for file_path in n1_files:
            result = self.parse_n1_report(file_path)
            if result and result.get("remaining_issues") is not None:
                issues = result["remaining_issues"]
                scheme_num = result.get("scheme_number", "未知")
                print(f"  方案 {scheme_num}: 剩余问题数 = {issues}")

                if issues < min_issues:
                    min_issues = issues
                    best_scheme = result

        if not best_scheme:
            print("❌ 未能找到有效的方案")
            return {}

        print(f"✅ 选择最优方案 {best_scheme['scheme_number']}, 剩余问题数: {min_issues}")

        return best_scheme

    def _select_best_scheme(self, analysis_root_dir: str) -> Optional[int]:
        """
        独立查找最优方案，返回最优方案的序号

        Args:
            analysis_root_dir: 分析结果根目录

        Returns:
            最优方案的序号(整数)，如果未找到则返回None
        """
        # 查找所有分析目录
        analysis_pattern = os.path.join(analysis_root_dir, "analysis_*")
        analysis_dirs = glob.glob(analysis_pattern)

        if not analysis_dirs:
            print(f"❌ 在 {analysis_root_dir} 中未找到分析目录")
            return None

        # 收集所有分析目录的结果
        analysis_results = []
        for analysis_dir in analysis_dirs:
            combined_data = self.parse_combined_reports(analysis_dir)
            if combined_data:
                # 检查PF报告是否有错误
                pf_error = combined_data.get("pf_error")
                if pf_error:
                    scheme_num = self._extract_scheme_number_from_path(analysis_dir)
                    print(f"❌ 方案 {scheme_num} 的PF报告存在错误，跳过: {pf_error}")
                    continue

                # 前置N-1检测或简易N-1抽样不通过的候选方案直接舍弃。
                scheme_num = self._extract_scheme_number_from_path(analysis_dir)
                n1_data = combined_data.get("n1_data", {})
                if n1_data.get("precheck_failed"):
                    reason = n1_data.get("precheck_failed_reason") or "前置N-1检测存在问题"
                    print(f"⏭️ 方案 {scheme_num} {reason}N-1存在问题，舍弃")
                    continue
                if n1_data.get("screening_discarded"):
                    print(f"⏭️ 方案 {scheme_num} 简易N-1抽样全部存在问题，舍弃")
                    continue

                # 计算综合问题数（N-1问题数 + SCC问题数）
                n1_issues = combined_data["n1_issues"]
                scc_issues = combined_data.get("scc_data", {}).get("remaining_issues", 0)
                total_issues = n1_issues + scc_issues

                analysis_results.append({
                    "scheme_number": scheme_num,
                    "analysis_dir": analysis_dir,
                    "n1_issues": n1_issues,
                    "scc_issues": scc_issues,
                    "total_issues": total_issues,
                })

        if not analysis_results:
            print(f"❌ 未找到任何有效的分析结果")
            return None

        print(f"📊 找到 {len(analysis_results)} 个有效分析目录")

        # 打印每个方案的问题数
        for result in analysis_results:
            scheme_num = result["scheme_number"]
            n1_issues = result["n1_issues"]
            scc_issues = result["scc_issues"]
            if scc_issues == float('inf'):
                scc_issues = '仿真错误'
            total_issues = result["total_issues"]

            print(f"  方案 {scheme_num}: N-1问题数 = {n1_issues}, SCC问题数 = {scc_issues}, 总问题数 = {total_issues}")

        # 选择N-1问题数最少的方案
        best_scheme_number = None
        min_n1_issues = float('inf')

        for result in analysis_results:
            n1_issues = result["n1_issues"]

            if n1_issues < min_n1_issues:
                min_n1_issues = n1_issues
                best_scheme_number = result["scheme_number"]

        if best_scheme_number is not None:
            print(f"🎯 选择最优方案 {best_scheme_number}, N-1问题数: {min_n1_issues}")
        else:
            print("❌ 未能选择出最优方案")

        return best_scheme_number

    def save_best_proposal(self, analysis_root_dir: str, output_path: Optional[str] = None) -> bool:
        """
        保存最优方案到指定路径的JSON文件中

        Args:
            analysis_root_dir: 分析根目录
            output_path: 输出文件路径，如果不指定则使用默认路径

        Returns:
            bool: 是否成功保存
        """
        try:
            # 1. 查找最优方案
            best_scheme_num = self._select_best_scheme(analysis_root_dir)
            if best_scheme_num is None:
                print("❌ 未找到最优方案")
                return False

            # 2. 提取最优方案的JSON块
            result = self.extract_best_proposal_json(analysis_root_dir, best_scheme_num, output_path)
            if result:
                print(f"✅ 最优方案 {best_scheme_num} 已成功保存")
            return result

        except Exception as e:
            print(f"❌ 保存最优方案失败: {e}")
            return False

    def generate_best_scheme_report(self, analysis_root_dir: str) -> Dict[str, Any]:
        """
        构建最优方案对应的分析报告

        Args:
            analysis_root_dir: 分析根目录

        Returns:
            包含最优方案分析报告的字典
        """
        try:
            # 1. 查找最优方案
            best_scheme_num = self._select_best_scheme(analysis_root_dir)
            if best_scheme_num is None:
                return {"error": "未找到最优方案"}

            # 2. 获取分析目录
            analysis_dir = os.path.join(analysis_root_dir, f"analysis_{best_scheme_num}")
            if not os.path.exists(analysis_dir):
                print(f"❌ 分析目录不存在: {analysis_dir}")
                return {"error": f"分析目录不存在: {analysis_dir}"}

            # 3. 解析组合报告
            combined_data = self.parse_combined_reports(analysis_dir)
            if not combined_data:
                return {"error": "无法解析分析报告"}

            # 4. 生成分析报告文本
            analysis_report = self.generate_combined_analysis_report(analysis_dir)

            # 5. 获取模型路径
            model_path = f"{analysis_root_dir}/application/method_{best_scheme_num}/applied_model_{best_scheme_num}.dat"
            if not os.path.exists(model_path):
                print(f"⚠️ 未找到对应模型文件: {model_path}")
                model_path = None

            # 6. 返回完整信息
            return {
                "scheme_number": best_scheme_num,
                "n1_issues": combined_data["n1_issues"],
                "scc_issues": combined_data.get("scc_data", {}).get("remaining_issues", 0),
                "total_issues": combined_data["n1_issues"] + combined_data.get("scc_data", {}).get("remaining_issues", 0),
                "analysis_report": analysis_report,
                "analysis_dir": analysis_dir,
                "model_path": model_path
            }

        except Exception as e:
            print(f"❌ 构建最优方案报告失败: {e}")
            return {"error": f"构建报告失败: {str(e)}"}

    def adjust_generator_for_best_scheme(self, analysis_root_dir: str) -> bool:
        """
        调整最优方案的发电机参数

        Args:
            analysis_root_dir: 分析根目录

        Returns:
            bool: 是否成功调整
        """
        try:
            # 1. 查找最优方案
            best_scheme_num = self._select_best_scheme(analysis_root_dir)
            if best_scheme_num is None:
                print("❌ 未找到最优方案")
                return False

            # 2. 调用 AnalysisService 的 adjust_generator_all 方法调整发电机参数
            config = load_config_as_dotdict()
            analysis_service = AnalysisService(config)
            result = analysis_service.adjust_generator_all(analysis_root_dir, best_scheme_num)

            if result:
                print(f"✅ 最优方案 {best_scheme_num} 的发电机参数已成功调整")
            else:
                print(f"✅ 最优方案 {best_scheme_num} 的发电机参数调整完成")

            return result

        except Exception as e:
            print(f"❌ 调整发电机参数失败: {e}")
            return False

    def extract_best_proposal_json(self, analysis_root_dir: str, scheme_num: int) -> bool:
        """
        提取最优方案的JSON块并保存到指定文件

        Args:
            analysis_root_dir: 分析根目录
            scheme_num: 最优方案编号

        Returns:
            bool: 是否成功保存
        """
        try:
            # 构建parsed_proposals.json文件路径
            proposals_file_path = os.path.join(analysis_root_dir, "generation", "parsed_proposals.json")

            if not os.path.exists(proposals_file_path):
                print(f"❌ 文件不存在: {proposals_file_path}")
                return False

            # 读取parsed_proposals.json文件
            with open(proposals_file_path, 'r', encoding='utf-8') as f:
                proposals_data = json.load(f)

            # 查找对应方案编号的JSON块
            target_proposal = None
            for proposal in proposals_data.get("proposals", []):
                proposal_name = proposal.get("proposal_name", "")
                if f"方案{scheme_num}" in proposal_name:
                    target_proposal = proposal
                    break

            if not target_proposal:
                print(f"❌ 未找到方案{scheme_num}的JSON块")
                return False

            # 准备要保存的数据
            save_data = {
                "scheme_number": scheme_num,
                "analysis_root_dir": analysis_root_dir,
                # "timestamp": datetime.now().isoformat(),
                "proposal": target_proposal
            }

            # 构建目标文件路径
            result_dir = os.path.join(str(Path(analysis_root_dir).parent), "result")
            os.makedirs(result_dir, exist_ok=True)
            target_file_path = os.path.join(result_dir, "proposals.json")

            # 处理文件追加
            if os.path.exists(target_file_path):
                # 文件存在，读取现有内容
                with open(target_file_path, 'r', encoding='utf-8') as f:
                    try:
                        existing_data = json.load(f)
                    except json.JSONDecodeError:
                        existing_data = []
            else:
                # 文件不存在，创建新列表
                existing_data = []

            # 确保是列表格式
            if not isinstance(existing_data, list):
                existing_data = [existing_data]

            # 追加新数据
            existing_data.append(save_data)

            # 保存到文件
            with open(target_file_path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)

            print(f"✅ 方案{scheme_num}的JSON块已追加保存至: {target_file_path}")
            print(f"   当前文件中共有 {len(existing_data)} 个方案记录")
            return True

        except Exception as e:
            print(f"❌ 提取最优方案JSON块失败: {e}")
            return False

    def generate_n1_analysis_report(self, n1_data: Dict[str, Any]) -> str:
        """
        生成N-1分析报告文本

        Args:
            n1_data: N-1报告数据

        Returns:
            格式化的问题描述文本
        """
        contingencies = n1_data.get("contingencies", [])

        if not contingencies or n1_data.get("remaining_issues", 0) == 0:
            return "当前方案无过载问题。"

        # 解析第一个故障实例
        first_contingency_info = self.get_first_contingency_info(n1_data.get("file_path", ""))
        if not first_contingency_info:
            return "无法解析故障实例信息。"

        # 构建报告
        branch_uid = first_contingency_info["branch_uid"]
        node1 = first_contingency_info["node1"]
        node2 = first_contingency_info["node2"]

        line_info = first_contingency_info.get("overloaded_line")
        if line_info:
            current_ratio = float(line_info.get("电流比例(%)", 0))
            current = float(line_info.get("电流(A)", 0))
            rated_current = float(line_info.get("额定电流(A)", 0))
            apparent_power = float(line_info.get("视在功率(MVA)", 0))
            rated_apparent_power = float(line_info.get("额定视在功率(MVA)", 0))
            power_ratio = float(line_info.get("视在功率比例(%)", 0))
            power_factor = float(line_info.get("功率因数", 0))
            angle = float(line_info.get("角度(度)", 0))

            contingency_report = f"""连接节点"{node1}"和节点"{node2}"的L卡线路电流比例为{current_ratio:.2f}%，超过阈值{self.pf_threshold}%。该线路的其他信息如下：
电流为{current}A,额定电流为{rated_current}A，视在功率为{apparent_power}MVA，额定视在功率为{rated_apparent_power}MVA，视在功率比例为{power_ratio:.2f}%，功率因数为{power_factor}，角度为{angle}度。"""

            return contingency_report
        else:
            return f"连接节点\"{node1}\"和节点\"{node2}\"的线路存在过载问题。"

    def get_first_contingency_info(self, n1_report_path: str) -> Optional[Dict[str, Any]]:
        """
        获取N-1报告中第一个故障实例的信息

        Args:
            n1_report_path: N-1报告文件路径

        Returns:
            第一个故障实例的详细信息
        """
        try:
            with open(n1_report_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            contingencies = data.get("contingencies_with_issues", [])
            if not contingencies:
                return None

            first_contingency = contingencies[0]
            branch_uid = first_contingency.get("contingency_branch_uid", "")

            # 提取节点信息
            match = re.match(r'(.+)\s*-\s*(.+)', branch_uid.split('(CKT=')[0].strip())
            if match:
                node1, node2 = match.groups()
            else:
                node1, node2 = "未知节点1", "未知节点2"

            # 获取过载线路信息
            overloaded_lines = first_contingency.get("result", {}).get("analysis", {}).get("overloaded_lines", [])
            line_info = None
            if overloaded_lines:
                line_info = overloaded_lines[0]  # 取第一个过载线路

            return {
                "branch_uid": branch_uid,
                "node1": node1.strip(),
                "node2": node2.strip(),
                "contingency_data": first_contingency,
                "overloaded_line": line_info
            }
        except Exception as e:
            print(f"❌ 解析N-1报告失败: {e}")
            return None

    def _extract_scheme_number(self, file_path: str) -> Optional[int]:
        """从文件路径提取方案编号"""
        try:
            # 匹配 n1_report_数字.json 模式
            match = re.search(r'n1_report_(\d+)\.json', file_path)
            if match:
                return int(match.group(1))

            # 匹配 analysis_数字/n1_report_数字.json 模式
            match = re.search(r'analysis_(\d+)[\\/]n1_report_\1\.json', file_path)
            if match:
                return int(match.group(1))

            return None
        except:
            return None

    def _extract_scheme_number_from_path(self, dir_path: str) -> Optional[int]:
        """从目录路径提取方案编号"""
        try:
            match = re.search(r'analysis_(\d+)', dir_path)
            if match:
                return int(match.group(1))
            return None
        except:
            return None

    def _parse_remaining_issues(self, summary: str) -> Optional[int]:
        """从summary中解析剩余问题数"""
        try:
            match = re.search(r'发现\s*(\d+)', summary)
            if match:
                return int(match.group(1))
            return float('inf')
        except:
            return None

    def evaluate_iteration_termination(self, current_version: int, previous_best_issues: float,
                                      same_issues_count: int, max_same_count: int,
                                      initial_scc_issues: int, base_model_path: str, dir: str) -> Dict[str, Any]:
        """
        评估迭代是否应终止，实现第一段代码中检查终止条件部分的功能

        Args:
            current_version: 当前迭代版本
            previous_best_issues: 上一轮的最优问题数
            same_issues_count: 相同问题数计数
            max_same_count: 最大允许相同次数
            initial_scc_issues: 初始SCC问题数
            base_model_path: 基础模型路径
            dir: 分析结果根目录(fulfillment_)

        Returns:
            包含评估结果的字典
        """
        try:
            # 获取分析根目录
            analysis_root = os.path.join(dir, f"test_output_v{current_version}")

            if not os.path.exists(analysis_root):
                return {
                    "terminate": True,
                    "termination_reason": f"分析根目录不存在: {analysis_root}",
                    "best_scheme_number": None
                }

            # 调用_select_best_scheme函数查找最优方案
            best_scheme_number = self._select_best_scheme(analysis_root)

            if best_scheme_number is None:
                return {
                    "terminate": True,
                    "termination_reason": "未找到最优方案",
                    "best_scheme_number": None
                }

            # 获取最优方案的详细信息
            analysis_dir = os.path.join(analysis_root, f"analysis_{best_scheme_number}")
            combined_data = self.parse_combined_reports(analysis_dir)

            if not combined_data:
                return {
                    "terminate": True,
                    "termination_reason": f"无法解析方案{best_scheme_number}的分析报告",
                    "best_scheme_number": None
                }

            # 获取问题数
            n1_issues = combined_data.get("n1_issues", 0)
            scc_issues = combined_data.get("scc_data", {}).get("remaining_issues", 0) if combined_data.get("scc_data") else 0
            total_issues = n1_issues + scc_issues

            # 检查SCC问题数是否大于初始值
            if scc_issues > initial_scc_issues:
                return {
                    "terminate": True,
                    "termination_reason": f"SCC问题数({scc_issues})大于初始值({initial_scc_issues})",
                    "best_scheme_number": best_scheme_number,
                    "n1_issues": n1_issues,
                    "scc_issues": scc_issues
                }

            # 检查终止条件1: 是否有方案的n1_issues等于0
            if n1_issues == 0:
                return {
                    "terminate": True,
                    "termination_reason": "有方案的N-1问题数为0",
                    "best_scheme_number": best_scheme_number,
                    "n1_issues": n1_issues,
                    "scc_issues": scc_issues
                }

            # 检查终止条件2: n-1问题数是否增加
            if n1_issues > previous_best_issues:
                return {
                    "terminate": True,
                    "termination_reason": f"N-1问题数增加 ({previous_best_issues} -> {n1_issues})",
                    "best_scheme_number": best_scheme_number,
                    "n1_issues": n1_issues,
                    "scc_issues": scc_issues
                }

            # 检查终止条件3: 连续相同n-1问题数
            new_same_count = same_issues_count
            if n1_issues == previous_best_issues:
                new_same_count += 1
                if new_same_count >= max_same_count:
                    return {
                        "terminate": True,
                        "termination_reason": f"连续{max_same_count}次N-1问题数相同",
                        "best_scheme_number": best_scheme_number,
                        "n1_issues": n1_issues,
                        "scc_issues": scc_issues
                    }
            else:
                new_same_count = 0

            # 获取方案详细信息
            model_path = os.path.join(analysis_root, f"application/method_{best_scheme_number}/applied_model_{best_scheme_number}.dat")
            if not os.path.exists(model_path):
                model_path = base_model_path

            return {
                "terminate": False,
                "termination_reason": None,
                "best_scheme_number": best_scheme_number,
                "n1_issues": n1_issues,
                "scc_issues": scc_issues,
                "total_issues": total_issues,
                "analysis_dir": analysis_dir,
                "model_path": model_path,
                "same_issues_count": new_same_count
            }

        except Exception as e:
            print(f"❌ 评估迭代终止条件时出错: {e}")
            return {
                "terminate": True,
                "termination_reason": f"评估过程中出错: {str(e)}",
                "best_scheme_number": None
            }

    def get_scheme_detailed_info(self, analysis_root: str, scheme_number: int,
                                initial_scc_issues: int) -> Dict[str, Any]:
        """
        获取方案的详细信息

        Args:
            analysis_root: 分析根目录
            scheme_number: 方案编号
            initial_scc_issues: 初始SCC问题数

        Returns:
            方案详细信息字典
        """
        try:
            analysis_dir = os.path.join(analysis_root, f"analysis_{scheme_number}")
            combined_data = self.parse_combined_reports(analysis_dir)

            if not combined_data:
                return None

            n1_issues = combined_data.get("n1_issues", 0)
            scc_issues = combined_data.get("scc_data", {}).get("remaining_issues", 0) if combined_data.get("scc_data") else 0
            total_issues = n1_issues + scc_issues

            # 检查SCC问题数
            if scc_issues > initial_scc_issues:
                return None

            # 获取模型路径
            model_path = os.path.join(analysis_root, f"application/method_{scheme_number}/applied_model_{scheme_number}.dat")

            return {
                "scheme_number": scheme_number,
                "n1_issues": n1_issues,
                "scc_issues": scc_issues,
                "total_issues": total_issues,
                "analysis_dir": analysis_dir,
                "model_path": model_path if os.path.exists(model_path) else None
            }

        except Exception as e:
            print(f"❌ 获取方案{scheme_number}详细信息时出错: {e}")
            return None

class PlanInterpreter:
    """
    【子模块】: 负责解析由LLM生成的规划方案文本。
    """
    def parse(self, llm_output_text: str) -> List[Dict[str, Any]]:
        """
        从LLM的完整输出文本中，提取所有符合预定义格式的方案JSON块。
        """
        proposals: List[Dict[str, Any]] = []

        scheme_pattern = r'```json\s*([\s\S]*?)```'
        scheme_blocks = re.findall(scheme_pattern, llm_output_text, re.DOTALL)

        if not scheme_blocks:
            print("  [Interpreter] 警告: 在LLM输出中未找到任何完整的方案块。")
            return []

        print(f"  [Interpreter] 找到 {len(scheme_blocks)} 个潜在的方案块，正在进行解析和验证...")

        for i, json_block in enumerate(scheme_blocks):
            try:
                data = self._loads_json_block(json_block, i)
                proposal_name = self._extract_proposal_name(data, i)
                proposal = {
                    "proposal_name": proposal_name,
                    "modifications": self._convert_grid_data_to_modifications(data)
                }

                if proposal["modifications"]:
                    print(f"    - ✅ 成功: 方案块 #{i+1} ('{proposal['proposal_name']}') 已解析。")
                    proposals.append(proposal)
                else:
                    print(f"    - ⚠️ 警告: 方案块 #{i+1} 没有找到任何操作详情。")

            except json.JSONDecodeError as e:
                print(f"    - ❌ 错误: 解析方案JSON块 #{i+1} 失败: {e}")
                continue
            except Exception as e:
                print(f"    - ❌ 错误: 处理方案块 #{i+1} 时发生意外错误: {e}")
                continue

        return proposals

    def _loads_json_block(self, json_block: str, index: int) -> Dict[str, Any]:
        """Parse one model-produced JSON block, with an optional repair fallback."""
        text = json_block.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as original_error:
            try:
                from json_repair import repair_json
            except ImportError:
                raise original_error

            repaired_text = repair_json(text)
            try:
                data = json.loads(repaired_text)
                print(f"      - ℹ️ 方案块 #{index+1} JSON 已自动修复后解析。")
                return data
            except json.JSONDecodeError:
                raise original_error

    def _extract_proposal_name(self, data: Dict[str, Any], index: int) -> str:
        """从数据中提取方案名称"""
        if "proposals" in data and isinstance(data["proposals"], list):
            proposals = data["proposals"]
            if index < len(proposals):
                proposal = proposals[index]
                if "proposal_name" in proposal:
                    return proposal["proposal_name"]

        if "grid_data" in data and isinstance(data["grid_data"], dict):
            for key in data["grid_data"].keys():
                if key.startswith("方案"):
                    return key

        return f"方案{index+1}"

    def _convert_grid_data_to_modifications(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从数据中提取操作详情并转换为标准的modifications格式"""
        modifications = []

        def find_operation_details(obj, path=""):
            if isinstance(obj, dict):
                if "操作" in obj and isinstance(obj["操作"], list):
                    return obj["操作"]
                for key, value in obj.items():
                    result = find_operation_details(value, f"{path}.{key}")
                    if result is not None:
                        return result
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    result = find_operation_details(item, f"{path}[{i}]")
                    if result is not None:
                        return result
            return None

        operation_details = find_operation_details(data)

        if not operation_details:
            return modifications

        for operation in operation_details:
            if not isinstance(operation, dict):
                continue

            operation_type = operation.get("操作类型", "")
            data_card_type = operation.get("数据卡", "")
            data_content = operation.get("信息", {})

            action = None
            if operation_type == "新增" and data_card_type == "L":
                action = "add_line"
            elif operation_type == "新增" and data_card_type == "B":
                action = "add_bus"
            elif operation_type == "删除" and data_card_type == "L":
                action = "disable_branch"
            else:
                print(f"      - ⚠️ 警告: 未知的操作类型 '{operation_type}' 或数据卡类型 '{data_card_type}'")
                continue

            modification = {
                "action": action,
                "params": {
                    "full_branch_data" if data_card_type == "L" else "full_bus_data": data_content
                }
            }

            modifications.append(modification)

        return modifications

class GenerationService:
    """
    【改进的主服务】: 在拼接prompt前先进行解析
    """
    def __init__(self, config):
        self.config = config.api
        self.client = OpenAI(
            base_url=self.config.modelscope_base_url,
            api_key=self.config.modelscope_api_key
        )
        self.model = self.config.llm_model_name
        self.interpreter = PlanInterpreter()
        self.selector = SelectionService()
        print(f"[Generation] 服务已初始化，使用模型: {self.model}")

    def _read_prompt_template(self, template_path: str) -> str:
        """从文件安全地读取Prompt模板。"""
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"Prompt模板文件未找到: {template_path}")
        except Exception as e:
            raise IOError(f"读取Prompt模板文件时出错: {e}")

    def _prepare_prompt_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """补齐 prompt 模板所需的后端默认参数。"""
        prepared = dict(context)
        count = prepared.get("schemes_per_generation", SCHEMES_PER_GENERATION)
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = SCHEMES_PER_GENERATION
        if count <= 0:
            count = SCHEMES_PER_GENERATION

        prepared["schemes_per_generation"] = count
        prepared["scheme_name_list"] = _format_scheme_name_list(count)
        prepared.setdefault("target_node_name", "目标节点")
        prepared.setdefault("target_load_p", 0)
        prepared.setdefault(
            "target_solution_instruction",
            "你需要先定位过载线路的位置，然后通过将目标节点接入线网，解决该电网问题，也就是将过载线路的线路电流比例下降至80%以下。"
        )
        prepared.setdefault(
            "iteration_solution_instruction",
            "请仔细研究最新问题报告，优先解决仍然存在的 N-1 过载。"
        )
        return prepared

    def _parse_before_generation(self, parse_target: str, is_file: bool = True) -> Tuple[str, Dict[str, Any]]:
        """
        在生成前进行解析，不包含保存功能

        Args:
            parse_target (str): 要解析的文件路径或文件夹路径
            is_file (bool): 是否为文件解析模式

        Returns:
            Tuple[分析报告文本, 解析数据]
        """
        print(f"[解析] 开始解析{'文件' if is_file else '文件夹'}: {parse_target}")

        if is_file:
            # 如果是单个文件，解析其所在目录
            analysis_dir = os.path.dirname(parse_target)
            analysis_report = self.selector.generate_combined_analysis_report(analysis_dir)

            # 解析该目录获取数据
            combined_data = self.selector.parse_combined_reports(analysis_dir)
            return analysis_report, combined_data

        else:
            # 解析文件夹选择最优方案
            best_scheme = self.selector._select_best_scheme(parse_target)
            if not best_scheme:
                raise ValueError(f"无法解析分析文件夹: {parse_target}")

            analysis_report = best_scheme.get("analysis_report", "")

            # 注意：这里移除了保存最优方案的功能
            # 只返回分析报告和解析的数据
            return analysis_report, best_scheme

    def generate_and_parse(self, prompt_template_path: str, context: Dict[str, Any],
                          parse_target: str = None, is_file_parse: bool = True,
                          save_raw_output_path: str = None) -> List[Dict[str, Any]]:
        """
        改进的生成并解析方法，支持解析前置处理，不包含保存功能

        Args:
            prompt_template_path (str): Prompt模板文件的路径
            context (Dict[str, Any]): 用于填充模板的上下文数据
            parse_target (str, optional): 要解析的文件或文件夹路径
            is_file_parse (bool): 是否为文件解析模式
            save_raw_output_path (str, optional): 保存原始响应的路径

        Returns:
            A list of valid, parsed proposal dictionaries
        """
        print(f"[Generation] 正在使用模板 '{os.path.basename(prompt_template_path)}' 生成方案...")

        # 1. 前置解析（如果指定了parse_target）
        analysis_report = ""
        if parse_target:
            # 只获取分析报告，不保存任何文件
            analysis_report, _ = self._parse_before_generation(parse_target, is_file_parse)
            context["n-1_analysis_report"] = analysis_report

        # 2. 构建Prompt
        try:
            template = self._read_prompt_template(prompt_template_path)
            context = self._prepare_prompt_context(context)
            prompt = template.format(**context)
        except KeyError as e:
            raise ValueError(f"构建Prompt失败: 模板需要一个名为 '{e}' 的键，但在context中未提供。")

        # 3. 调用API
        print("  - 正在调用LLM API...")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )

            collected_messages = []
            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    collected_messages.append(chunk.choices[0].delta.content)

            llm_output_text = "".join(collected_messages)
            print("  - 已成功从LLM获取响应。")

            if save_raw_output_path:
                os.makedirs(os.path.dirname(save_raw_output_path), exist_ok=True)
                with open(save_raw_output_path, "w", encoding="utf-8") as f:
                    f.write("--- PROMPT SENT TO LLM ---\n")
                    f.write(prompt)
                    f.write("\n\n--- RAW RESPONSE FROM LLM ---\n")
                    f.write(llm_output_text)
                print(f"  - LLM的原始响应已保存至: {save_raw_output_path}")

        except Exception as e:
            print(f"  - ❌ 调用LLM API时发生严重错误: {e}")
            raise

        # 4. 解析结果
        print("  - 正在解析LLM响应...")
        parsed_proposals = self.interpreter.parse(llm_output_text)
        if not parsed_proposals:
            print("  - 首次解析未得到有效方案，尝试让LLM修复JSON格式后重新解析...")
            repaired_output_text = self._repair_llm_json_output(llm_output_text)
            if save_raw_output_path and repaired_output_text:
                with open(save_raw_output_path, "a", encoding="utf-8") as f:
                    f.write("\n\n--- REPAIRED RESPONSE FROM LLM ---\n")
                    f.write(repaired_output_text)
            parsed_proposals = self.interpreter.parse(repaired_output_text)

        print(f"[Generation] 流程完成，成功解析出 {len(parsed_proposals)} 个有效方案。")
        return parsed_proposals

    def _repair_llm_json_output(self, llm_output_text: str) -> str:
        """Ask the model to convert its previous answer into strict JSON code blocks."""
        repair_prompt = (
            "下面是一段电网规划方案输出，其中包含多个 ```json ... ``` 代码块，但 JSON 语法可能不合法。\n"
            "请只修复 JSON 语法，不要改变方案含义、节点名、字段名或数值。\n"
            "输出要求：只输出修复后的 ```json ... ``` 代码块；每个方案一个代码块；"
            "不要输出解释文字、Markdown 列表、注释、尾随逗号或省略号；"
            "字符串内部如需引用节点名，请使用中文引号“”或转义英文双引号。\n\n"
            f"{llm_output_text}"
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "user", "content": repair_prompt}],
                stream=True,
            )

            collected_messages = []
            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    collected_messages.append(chunk.choices[0].delta.content)
            repaired_output_text = "".join(collected_messages)
            print("  - JSON格式修复响应已获取。")
            return repaired_output_text
        except Exception as e:
            print(f"  - ⚠️ JSON格式修复失败: {e}")
            return llm_output_text

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="按指定方案目录筛选并调整发电机。")
    parser.add_argument("output_dir", help="包含方案和仿真结果的目录")
    parser.add_argument("--pf-threshold", type=float, default=80.0)
    parser.add_argument("--scc-threshold", type=float, default=60.0)
    args = parser.parse_args()
    selector = SelectionService(
        pf_threshold=args.pf_threshold,
        scc_threshold=args.scc_threshold,
    )
    selector.adjust_generator_for_best_scheme(args.output_dir)
