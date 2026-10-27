# src/services/preprocessing_service.py

import json
import os
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

from pybpa.dat.bpa_dat import DAT


class PreprocessingService:
    """
    Build the LLM context used by the planning pipeline.

    The core flow is:
    1. convert a BPA .dat file into structured JSON;
    2. place that JSON under context["grid_structure_json"];
    3. preserve or inject prompt-side fields such as reference_content,
       reference_format and task_description.
    """

    def dat_to_json(
        self,
        dat_path: str,
        output_path: Optional[str] = None,
        filter_kv: Optional[float] = None,
        filter_500kv_only: bool = False,
    ) -> Tuple[bool, Any]:
        """
        Convert a .dat model file to {"buses": [...], "branches": [...]}.

        If output_path is provided, the JSON is written to disk. The returned
        message is the generated data so callers can immediately compose a
        context.json without reading the file again.
        
        Args:
            dat_path: DAT文件路径
            output_path: 输出JSON文件路径
            filter_kv: 最小电压等级过滤阈值
            filter_500kv_only: 是否只保留500kV以上设备（用于缩减上下文长度）
        """
        try:
            grid_data = self.convert_dat_to_grid_json(dat_path, filter_kv=filter_kv, filter_500kv_only=filter_500kv_only)
        except Exception as exc:
            print(f"[Preprocess] DAT 转 JSON 失败: {exc}")
            return False, str(exc)

        if output_path:
            try:
                self._write_json(output_path, grid_data)
            except Exception as exc:
                print(f"[Preprocess] 保存 DAT JSON 失败: {exc}")
                return False, str(exc)

        print(
            "[Preprocess] DAT 转 JSON 完成: "
            f"{len(grid_data['buses'])} 个母线, {len(grid_data['branches'])} 条支路"
        )
        return True, grid_data

    def convert_dat_to_grid_json(
        self,
        dat_path: str,
        filter_kv: Optional[float] = None,
        filter_500kv_only: bool = False,
    ) -> Dict[str, Any]:
        """Return structured grid data parsed from a BPA .dat file.
        
        Args:
            dat_path: DAT文件路径
            filter_kv: 最小电压等级过滤阈值
            filter_500kv_only: 是否只保留500kV以上设备（用于缩减上下文长度）
        """
        if not dat_path or not os.path.exists(dat_path):
            raise FileNotFoundError(f"DAT 文件不存在: {dat_path}")

        dat = DAT.build_from(dat_path, True)
        grid_data = {"buses": [], "branches": []}
        
        self.unprocessed_bus_types = set()
        self.unprocessed_branch_types = set()

        for bus in dat.bus:
            card_data = self._bus_card_to_dict(bus)
            if card_data:
                grid_data["buses"].append(card_data)

        for branch in dat.branch:
            card_data = self._branch_card_to_dict(branch)
            if card_data:
                grid_data["branches"].append(card_data)
        
        if self.unprocessed_bus_types:
            print(f"[Preprocess] 警告：发现未处理的bus类型: {', '.join(self.unprocessed_bus_types)}")
        if self.unprocessed_branch_types:
            print(f"[Preprocess] 警告：发现未处理的branch类型: {', '.join(self.unprocessed_branch_types)}")

        if filter_500kv_only:
            return self._filter_500kv_only(grid_data)
        if filter_kv is not None:
            return self._filter_by_voltage(grid_data, filter_kv)
        return grid_data

    def build_context(
        self,
        output_path: str,
        dat_path: Optional[str] = None,
        grid_structure_json_path: Optional[str] = None,
        base_context_path: Optional[str] = None,
        reference_content_path: Optional[str] = None,
        reference_format_path: Optional[str] = None,
        task_description: Optional[str] = None,
        filter_kv: Optional[float] = None,
        filter_500kv_only: bool = False,
        **legacy_kwargs,
    ) -> Tuple[bool, str]:
        """
        Build context.json for generation.

        Preferred generic usage:
            build_context(output_path, dat_path="case.dat", task_description="...")

        Backward-compatible usage still accepts grid_structure_json_path and
        older keyword names used by the previous tests.
        
        Args:
            output_path: 输出context.json文件路径
            dat_path: DAT文件路径
            grid_structure_json_path: 已有的网架结构JSON文件路径
            base_context_path: 基础context模板文件路径
            reference_content_path: 参考内容文件路径
            reference_format_path: 参考格式文件路径
            task_description: 任务描述
            filter_kv: 最小电压等级过滤阈值
            filter_500kv_only: 是否只保留500kV以上设备（用于缩减上下文长度）
        """
        try:
            grid_structure_json_path = (
                grid_structure_json_path
                or legacy_kwargs.get("grid_json")
                or legacy_kwargs.get("grid_json_path")
            )
            reference_content_path = reference_content_path or legacy_kwargs.get("ref_doc")
            task_description = task_description or legacy_kwargs.get("task_description")

            context_data = self._load_base_context(base_context_path)
            context_data["grid_structure_json"] = self._resolve_grid_structure(
                dat_path=dat_path,
                grid_structure_json_path=grid_structure_json_path,
                filter_kv=filter_kv,
                filter_500kv_only=filter_500kv_only,
            )

            if reference_content_path:
                context_data["reference_content"] = self._read_text_file(reference_content_path)
            else:
                context_data.setdefault("reference_content", "")

            if reference_format_path:
                context_data["reference_format"] = self._read_json_file(reference_format_path)
            else:
                context_data.setdefault("reference_format", self._default_reference_format())

            if task_description:
                context_data["task_description"] = task_description
            else:
                context_data.setdefault(
                    "task_description",
                    "请基于当前网架结构生成五个可行的通用接入方案，解决目标的 N-1 过载问题。",
                )

            self._write_json(output_path, context_data)
            print(f"[Preprocess] context.json 已生成: {os.path.abspath(output_path)}")
            return True, f"成功生成文件: {output_path}"
        except Exception as exc:
            print(f"[Preprocess] 构建 context.json 失败: {exc}")
            return False, str(exc)

    def build_context_from_dat(
        self,
        dat_path: str,
        output_path: str,
        base_context_path: Optional[str] = None,
        task_description: Optional[str] = None,
        filter_kv: Optional[float] = None,
        filter_500kv_only: bool = False,
    ) -> Tuple[bool, str]:
        """Convenience wrapper for the generic case."""
        return self.build_context(
            output_path=output_path,
            dat_path=dat_path,
            base_context_path=base_context_path,
            task_description=task_description,
            filter_kv=filter_kv,
            filter_500kv_only=filter_500kv_only,
        )

    def _resolve_grid_structure(
        self,
        dat_path: Optional[str],
        grid_structure_json_path: Optional[str],
        filter_kv: Optional[float],
        filter_500kv_only: bool = False,
    ) -> Dict[str, Any]:
        if dat_path:
            return self.convert_dat_to_grid_json(dat_path, filter_kv=filter_kv, filter_500kv_only=filter_500kv_only)
        if grid_structure_json_path:
            data = self._read_json_file(grid_structure_json_path)
            if isinstance(data, dict) and "grid_structure_json" in data:
                grid_data = data["grid_structure_json"]
            elif isinstance(data, dict):
                grid_data = data
            else:
                raise ValueError(f"网架 JSON 格式不正确: {grid_structure_json_path}")
            
            if filter_500kv_only:
                return self._filter_500kv_only(grid_data)
            return grid_data
        raise ValueError("必须提供 dat_path 或 grid_structure_json_path")

    unprocessed_bus_types = set()
    unprocessed_branch_types = set()

    def _bus_card_to_dict(self, bus) -> Dict[str, Any]:
        """将bus卡片转换为字典，支持所有bus卡片类型"""
        bus_type = bus.get_value('TYPE')
        
        if bus_type in ['B ', 'BT', 'BC', 'BV']:
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "LOAD_P": bus.get_value('LOAD_P'),
                "LOAD_Q": bus.get_value('LOAD_Q'),
                "SHUNTZP": bus.get_value('SHUNTZP'),
                "SHUNTZQ": bus.get_value('SHUNTZQ'),
                "GEN_P_MAX": bus.get_value('GEN_P_MAX'),
                "GEN_P": bus.get_value('GEN_P'),
                "QSCHED": bus.get_value('QSCHED'),
                "GEN_Q_MIN": bus.get_value('GEN_Q_MIN'),
                "VMAX": bus.get_value('VMAX'),
                "VMIN": bus.get_value('VMIN'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type in ['BE', 'BQ', 'BF', 'BJ']:
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "LOAD_P": bus.get_value('LOAD_P'),
                "LOAD_Q": bus.get_value('LOAD_Q'),
                "SHUNTZP": bus.get_value('SHUNTZP'),
                "SHUNTZQ": bus.get_value('SHUNTZQ'),
                "GEN_P_MAX": bus.get_value('GEN_P_MAX'),
                "GEN_P": bus.get_value('GEN_P'),
                "GEN_Q_MAX": bus.get_value('GEN_Q_MAX'),
                "GEN_Q_MIN": bus.get_value('GEN_Q_MIN'),
                "VMAX": bus.get_value('VMAX'),
                "VMIN": bus.get_value('VMIN'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type in ['BS', 'BK', 'BL']:
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "LOAD_P": bus.get_value('LOAD_P'),
                "LOAD_Q": bus.get_value('LOAD_Q'),
                "SHUNTZP": bus.get_value('SHUNTZP'),
                "SHUNTZQ": bus.get_value('SHUNTZQ'),
                "GEN_P_MAX": bus.get_value('GEN_P_MAX'),
                "GEN_P": bus.get_value('GEN_P'),
                "GEN_Q_MAX": bus.get_value('GEN_Q_MAX'),
                "GEN_Q_MIN": bus.get_value('GEN_Q_MIN'),
                "VSCHED": bus.get_value('VSCHED'),
                "ANGLE": bus.get_value('ANGLE'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BX':
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "LOAD_P": bus.get_value('LOAD_P'),
                "LOAD_Q": bus.get_value('LOAD_Q'),
                "SHUNTZP": bus.get_value('SHUNTZP'),
                "SHUNTZQ": bus.get_value('SHUNTZQ'),
                "GEN_P_MAX": bus.get_value('GEN_P_MAX'),
                "GEN_P": bus.get_value('GEN_P'),
                "GEN_Q_MAX": bus.get_value('GEN_Q_MAX'),
                "GEN_Q_MIN": bus.get_value('GEN_Q_MIN'),
                "VMAX": bus.get_value('VMAX'),
                "VMIN": bus.get_value('VMIN'),
                "REMOTE BUS": bus.get_value('REMOTE BUS'),
                "REMOTE BASE": bus.get_value('REMOTE BASE'),
                "SUPPLIED VAR": bus.get_value('SUPPLIED VAR'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BD':
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "PBRCKT BRDGS": bus.get_value('PBRCKT BRDGS'),
                "SMOOTHING REACTOR": bus.get_value('SMOOTHING REACTOR'),
                "RECT OPER MIN": bus.get_value('RECT OPER MIN'),
                "INVERTER OPER STOP": bus.get_value('INVERTER OPER STOP'),
                "VOL DROP (VOLTS)": bus.get_value('VOL DROP (VOLTS)'),
                "BRDGE CRRNT RATING (AMPS)": bus.get_value('BRDGE CRRNT RATING (AMPS)'),
                "COMMUTATING BUS NAME": bus.get_value('COMMUTATING BUS NAME'),
                "COMMUTATING BASE": bus.get_value('COMMUTATING BASE'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BM':
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "NAME2": bus.get_value('NAME2'),
                "BASE2": bus.get_value('BASE2'),
                "BM TYPE": bus.get_value('BM TYPE'),
                "DEG": bus.get_value('DEG'),
                "MIN DEG": bus.get_value('MIN DEG'),
                "CONVTR POWER": bus.get_value('CONVTR POWER'),
                "CONVTR VOLTAGE": bus.get_value('CONVTR VOLTAGE'),
                "DC VOLTAGE": bus.get_value('DC VOLTAGE'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BZ':
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "TOTAL MVA": bus.get_value('TOTAL MVA'),
                "R": bus.get_value('R'),
                "L": bus.get_value('L'),
                "LEVEL L NUM": bus.get_value('LEVEL L NUM'),
                "C": bus.get_value('C'),
                "LOSS": bus.get_value('LOSS'),
                "DC MOD": bus.get_value('DC MOD'),
                "V HOLD": bus.get_value('V HOLD'),
                "N POLE": bus.get_value('N POLE'),
                "DC BASE": bus.get_value('DC BASE'),
                "POLE FDCR": bus.get_value('POLE FDCR'),
                "GROUND FDCR": bus.get_value('GROUND FDCR'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BZ+':
            return {
                "TYPE": bus_type,
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "P": bus.get_value('P'),
                "Q": bus.get_value('Q'),
                "DC MOD": bus.get_value('DC MOD'),
                "DC BASE": bus.get_value('DC BASE'),
                "DC V HOLD": bus.get_value('DC V HOLD'),
                "TRAN R": bus.get_value('TRAN R'),
                "TRAN X": bus.get_value('TRAN X'),
                "TAP1": bus.get_value('TAP1'),
                "TAP2": bus.get_value('TAP2'),
                "Q-COMP": bus.get_value('Q-COMP'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BA':
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "LTYPE": bus.get_value('LTYPE'),
                "LBVBL": bus.get_value('LBVBL'),
                "BRGNUM": bus.get_value('BRGNUM'),
                "SHUNT REACTOR": bus.get_value('SHUNT REACTOR'),
                "POWER PER": bus.get_value('POWER PER'),
                "QSHUNT": bus.get_value('QSHUNT'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BA1':
            return {
                "TYPE": bus_type,
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "TRAN DCSIDE BASE": bus.get_value('TRAN DCSIDE BASE'),
                "TRAN RATE": bus.get_value('TRAN RATE'),
                "TRAN R": bus.get_value('TRAN R'),
                "TRAN X": bus.get_value('TRAN X'),
                "TAP MAX": bus.get_value('TAP MAX'),
                "TAP MIN": bus.get_value('TAP MIN'),
                "TA NUM": bus.get_value('TA NUM'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BA2':
            return {
                "TYPE": bus_type,
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "VAVLE DROP": bus.get_value('VAVLE DROP'),
                "BRDGE CUR RATING": bus.get_value('BRDGE CUR RATING'),
                "ALPHA MIN": bus.get_value('ALPHA MIN'),
                "ALPHA MAX": bus.get_value('ALPHA MAX'),
                "ALPHA NORMAL": bus.get_value('ALPHA NORMAL'),
                "GAMMA MIN": bus.get_value('GAMMA MIN'),
                "TA NUM": bus.get_value('TA NUM'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'BB':
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "ZONE": bus.get_value('ZONE'),
                "CTYPE": bus.get_value('CTYPE'),
                "LEVEL": bus.get_value('LEVEL'),
                "POWER PER": bus.get_value('POWER PER'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == '+':
            return {
                "TYPE": bus_type,
                "CODE": bus.get_value('CODE'),
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "CODE YEAR": bus.get_value('CODE YEAR'),
                "LOAD_P": bus.get_value('LOAD_P'),
                "LOAD_Q": bus.get_value('LOAD_Q'),
                "SHUNTZP": bus.get_value('SHUNTZP'),
                "SHUNTZQ": bus.get_value('SHUNTZQ'),
                "GEN_P": bus.get_value('GEN_P'),
                "QSCHED": bus.get_value('QSCHED'),
                "COMMENT": bus.get_value('COMMENT')
            }
        elif bus_type == 'X ':
            return {
                "TYPE": bus_type,
                "CHANGE CODE": bus.get_value('CHANGE CODE'),
                "OWNER": bus.get_value('OWNER'),
                "NAME": bus.get_value('NAME'),
                "BASE": bus.get_value('BASE'),
                "RMT BUS NAME": bus.get_value('RMT BUS NAME'),
                "RMT BUS BASE": bus.get_value('RMT BUS BASE'),
                "STEP1": bus.get_value('STEP1'),
                "DELTA MVAR1": bus.get_value('DELTA MVAR1'),
                "STEP2": bus.get_value('STEP2'),
                "DELTA MVAR2": bus.get_value('DELTA MVAR2'),
                "STEP3": bus.get_value('STEP3'),
                "DELTA MVAR3": bus.get_value('DELTA MVAR3'),
                "STEP4": bus.get_value('STEP4'),
                "DELTA MVAR4": bus.get_value('DELTA MVAR4'),
                "STEP5": bus.get_value('STEP5'),
                "DELTA MVAR5": bus.get_value('DELTA MVAR5'),
                "STEP6": bus.get_value('STEP6'),
                "DELTA MVAR6": bus.get_value('DELTA MVAR6'),
                "STEP7": bus.get_value('STEP7'),
                "DELTA MVAR7": bus.get_value('DELTA MVAR7'),
                "STEP8": bus.get_value('STEP8'),
                "DELTA MVAR8": bus.get_value('DELTA MVAR8'),
                "COMMENT": bus.get_value('COMMENT')
            }
        else:
            self.unprocessed_bus_types.add(bus_type)
            return {}

    def _branch_card_to_dict(self, branch) -> Dict[str, Any]:
        """将branch卡片转换为字典，支持所有branch卡片类型"""
        branch_type = branch.get_value('TYPE')
        
        if branch_type == 'L ':
            return {
                "TYPE": branch_type,
                "CHANGE CODE": branch.get_value('CHANGE CODE'),
                "OWNER": branch.get_value('OWNER'),
                "NAME1": branch.get_value('NAME1'),
                "BASE1": branch.get_value('BASE1'),
                "METER": branch.get_value('METER'),
                "NAME2": branch.get_value('NAME2'),
                "BASE2": branch.get_value('BASE2'),
                "CKT ID": branch.get_value('CKT ID'),
                "SECTION": branch.get_value('SECTION'),
                "TOTAL CURRENT RATE AMP": branch.get_value('TOTAL CURRENT RATE AMP'),
                "OF CKT": branch.get_value('OF CKT'),
                "R": branch.get_value('R'),
                "X": branch.get_value('X'),
                "G": branch.get_value('G'),
                "B": branch.get_value('B'),
                "MILES": branch.get_value('MILES'),
                "DESCDATA": branch.get_value('DESCDATA'),
                "DATA IN M": branch.get_value('DATA IN M'),
                "DATA IN Y": branch.get_value('DATA IN Y'),
                "DATA OUT M": branch.get_value('DATA OUT M'),
                "DATA OUT Y": branch.get_value('DATA OUT Y'),
                "Ith": branch.get_value('Ith'),
                "MODEL": branch.get_value('MODEL'),
                "LINE NAME": branch.get_value('LINE NAME'),
                "COMMENT": branch.get_value('COMMENT')
            }
        elif branch_type == 'L+':
            return {
                "TYPE": branch_type,
                "CHANGE CODE": branch.get_value('CHANGE CODE'),
                "OWNER": branch.get_value('OWNER'),
                "NAME1": branch.get_value('NAME1'),
                "BASE1": branch.get_value('BASE1'),
                "METER": branch.get_value('METER'),
                "NAME2": branch.get_value('NAME2'),
                "BASE2": branch.get_value('BASE2'),
                "CKT ID": branch.get_value('CKT ID'),
                "SECTION": branch.get_value('SECTION'),
                "MVAR1": branch.get_value('MVAR1'),
                "MVAR2": branch.get_value('MVAR2'),
                "COMMENT": branch.get_value('COMMENT')
            }
        elif branch_type == 'LD':
            return {
                "TYPE": branch_type,
                "CHANGE CODE": branch.get_value('CHANGE CODE'),
                "OWNER": branch.get_value('OWNER'),
                "NAME1": branch.get_value('NAME1'),
                "BASE1": branch.get_value('BASE1'),
                "METER": branch.get_value('METER'),
                "NAME2": branch.get_value('NAME2'),
                "BASE2": branch.get_value('BASE2'),
                "CKT ID": branch.get_value('CKT ID'),
                "TOTAL CURRENT RATE AMP": branch.get_value('TOTAL CURRENT RATE AMP'),
                "R": branch.get_value('R'),
                "L": branch.get_value('L'),
                "C": branch.get_value('C'),
                "CONTROL": branch.get_value('CONTROL'),
                "DC LINE POWER": branch.get_value('DC LINE POWER'),
                "RECT VOLT": branch.get_value('RECT VOLT'),
                "RECT TIFIER": branch.get_value('RECT TIFIER'),
                "INVERTER": branch.get_value('INVERTER'),
                "MILES": branch.get_value('MILES'),
                "COMMENT": branch.get_value('COMMENT')
            }
        elif branch_type == 'LZ':
            return {
                "TYPE": branch_type,
                "CHANGE CODE": branch.get_value('CHANGE CODE'),
                "OWNER": branch.get_value('OWNER'),
                "NAME1": branch.get_value('NAME1'),
                "BASE1": branch.get_value('BASE1'),
                "METER": branch.get_value('METER'),
                "NAME2": branch.get_value('NAME2'),
                "BASE2": branch.get_value('BASE2'),
                "CKT ID": branch.get_value('CKT ID'),
                "SECTION": branch.get_value('SECTION'),
                "LINE RAT": branch.get_value('LINE RAT'),
                "R": branch.get_value('R'),
                "L": branch.get_value('L'),
                "C": branch.get_value('C'),
                "SIDE1 SHUNTR": branch.get_value('SIDE1 SHUNTR'),
                "SIDE2 SHUNTR": branch.get_value('SIDE2 SHUNTR'),
                "LENTH": branch.get_value('LENTH'),
                "COMMENT": branch.get_value('COMMENT')
            }
        elif branch_type == 'LY':
            return {
                "TYPE": branch_type,
                "CHANGE CODE": branch.get_value('CHANGE CODE'),
                "OWNER": branch.get_value('OWNER'),
                "NAME1": branch.get_value('NAME1'),
                "BASE1": branch.get_value('BASE1'),
                "NAME2": branch.get_value('NAME2'),
                "BASE2": branch.get_value('BASE2'),
                "LINE RAT": branch.get_value('LINE RAT'),
                "DC R": branch.get_value('DC R'),
                "DC L": branch.get_value('DC L'),
                "DC C": branch.get_value('DC C'),
                "LENTH": branch.get_value('LENTH'),
                "COMMENT": branch.get_value('COMMENT')
            }
        elif branch_type == 'LM':
            return {
                "TYPE": branch_type,
                "CHANGE CODE": branch.get_value('CHANGE CODE'),
                "OWNER": branch.get_value('OWNER'),
                "NAME1": branch.get_value('NAME1'),
                "BASE1": branch.get_value('BASE1'),
                "METER": branch.get_value('METER'),
                "NAME2": branch.get_value('NAME2'),
                "BASE2": branch.get_value('BASE2'),
                "CKT ID": branch.get_value('CKT ID'),
                "TOTAL CURRENT RATE AMP": branch.get_value('TOTAL CURRENT RATE AMP'),
                "R": branch.get_value('R'),
                "L": branch.get_value('L'),
                "C": branch.get_value('C'),
                "MILES": branch.get_value('MILES'),
                "DATA IN M": branch.get_value('DATA IN M'),
                "DATA IN Y": branch.get_value('DATA IN Y'),
                "DATA OUT M": branch.get_value('DATA OUT M'),
                "DATA OUT Y": branch.get_value('DATA OUT Y'),
                "COMMENT": branch.get_value('COMMENT')
            }
        elif branch_type == 'T ':
            return {
                "TYPE": branch_type,
                "CHANGE CODE": branch.get_value('CHANGE CODE'),
                "OWNER": branch.get_value('OWNER'),
                "NAME1": branch.get_value('NAME1'),
                "BASE1": branch.get_value('BASE1'),
                "METER": branch.get_value('METER'),
                "NAME2": branch.get_value('NAME2'),
                "BASE2": branch.get_value('BASE2'),
                "CKT ID": branch.get_value('CKT ID'),
                "SECTION": branch.get_value('SECTION'),
                "CAPACITY MVA": branch.get_value('CAPACITY MVA'),
                "OF CKT": branch.get_value('OF CKT'),
                "R": branch.get_value('R'),
                "X": branch.get_value('X'),
                "G": branch.get_value('G'),
                "B": branch.get_value('B'),
                "TP1": branch.get_value('TP1'),
                "TP2": branch.get_value('TP2'),
                "DATA IN M": branch.get_value('DATA IN M'),
                "DATA IN Y": branch.get_value('DATA IN Y'),
                "DATA OUT M": branch.get_value('DATA OUT M'),
                "DATA OUT Y": branch.get_value('DATA OUT Y'),
                "COMMENT": branch.get_value('COMMENT')
            }
        elif branch_type == 'R ':
            return {
                "TYPE": branch_type,
                "CHANGE CODE": branch.get_value('CHANGE CODE'),
                "OWNER": branch.get_value('OWNER'),
                "NAME1": branch.get_value('NAME1'),
                "BASE1": branch.get_value('BASE1'),
                "METER": branch.get_value('METER'),
                "NAME2": branch.get_value('NAME2'),
                "BASE2": branch.get_value('BASE2'),
                "CKT ID": branch.get_value('CKT ID'),
                "REMOTE BUS": branch.get_value('REMOTE BUS'),
                "REMOTE BASE": branch.get_value('REMOTE BASE'),
                "MAX TAP": branch.get_value('MAX TAP'),
                "MIN TAP": branch.get_value('MIN TAP'),
                "#TAPS": branch.get_value('#TAPS'),
                "COMMENT": branch.get_value('COMMENT')
            }
        else:
            self.unprocessed_branch_types.add(branch_type)
            return {}

    def _card_to_dict(self, card_obj) -> Dict[str, Any]:
        card_dict = {}
        field_index = getattr(card_obj, "field_index", None)
        if not field_index:
            return card_dict

        for field_name in field_index:
            value = card_obj.get_value(field_name, default=None)
            if value is None:
                continue
            card_dict[field_name] = value
        return card_dict

    def _filter_by_voltage(self, data: Dict[str, Any], min_kv: float) -> Dict[str, Any]:
        filtered_buses = [
            bus
            for bus in data.get("buses", [])
            if self._as_number(bus.get("BASE")) is not None
            and self._as_number(bus.get("BASE")) >= min_kv
        ]

        filtered_branches = [
            branch
            for branch in data.get("branches", [])
            if self._branch_meets_voltage(branch, min_kv)
        ]
        return {"buses": filtered_buses, "branches": filtered_branches}

    def _filter_500kv_only(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        只保留500kV以上的设备，用于缩减网架结构的上下文长度。
        
        过滤规则：
        - B卡和BQ卡：只保留BASE > 500的母线
        - L卡和T卡：只保留BASE1 > 500且BASE2 > 500的支路
        """
        filtered_buses = []
        for bus in data.get("buses", []):
            if bus.get("TYPE") in ["B ", "BQ"]:
                base = self._as_number(bus.get("BASE"))
                if base is not None and base > 500:
                    filtered_buses.append(bus)
        
        filtered_branches = []
        for branch in data.get("branches", []):
            if branch.get("TYPE") in ["L ", "T "]:
                base1 = self._as_number(branch.get("BASE1"))
                base2 = self._as_number(branch.get("BASE2"))
                if base1 is not None and base2 is not None and base1 > 500 and base2 > 500:
                    filtered_branches.append(branch)
        
        return {"buses": filtered_buses, "branches": filtered_branches}

    def _branch_meets_voltage(self, branch: Dict[str, Any], min_kv: float) -> bool:
        base1 = self._as_number(branch.get("BASE1"))
        base2 = self._as_number(branch.get("BASE2"))
        if base1 is None and base2 is None:
            return True
        return (base1 is None or base1 >= min_kv) and (base2 is None or base2 >= min_kv)

    def _as_number(self, value: Any) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _load_base_context(self, base_context_path: Optional[str]) -> Dict[str, Any]:
        if not base_context_path:
            return {}
        data = self._read_json_file(base_context_path)
        if not isinstance(data, dict):
            raise ValueError(f"基础 context 不是 JSON 对象: {base_context_path}")
        return deepcopy(data)

    def _read_json_file(self, file_path: str) -> Any:
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"JSON 文件不存在: {file_path}")
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _read_text_file(self, file_path: str) -> str:
        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"文本文件不存在: {file_path}")
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()

    def _write_json(self, output_path: str, data: Dict[str, Any]) -> None:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def _default_reference_format(self) -> Dict[str, Any]:
        return {
            "proposal_name": "方案1",
            "description": "方案文字说明",
            "modifications": [
                {
                    "action": "add_bus",
                    "params": {"full_bus_data": {"TYPE": "B ", "NAME": "目标节点", "BASE": 525.0}},
                },
                {
                    "action": "add_line",
                    "params": {
                        "full_branch_data": {
                            "TYPE": "L ",
                            "NAME1": "目标节点",
                            "BASE1": 525.0,
                            "NAME2": "接入节点",
                            "BASE2": 525.0,
                            "CKT ID": "1",
                            "R": 0.0,
                            "X": 0.0,
                            "B": 0.0,
                            "MILES": 0.0,
                            "TOTAL CURRENT RATE AMP": 3000.0,
                        }
                    },
                },
            ],
            "expected_effect": "预期效果",
            "construction_cost": 0,
            "maintenance_cost": 0,
        }
