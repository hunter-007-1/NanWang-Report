# src/core/grid_model_handler.py

import os
from copy import deepcopy
from pybpa.dat.bpa_dat import DAT
from pybpa.dat.bpa_dat_data import DatL, DatB
from typing import Dict, Any, List, Tuple, Optional

class GridModelHandler:
    """
    封装对 BPA .dat 文件的所有读写和修改操作。
    """
    def __init__(self, dat_path: str):
        print(f"  [Handler] 正在加载电网模型: {dat_path}")
        try:
            self.dat_path = dat_path
            self.dat = DAT.build_from(dat_path, True)
            self._original_cards = deepcopy(self.dat.cards)
        except FileNotFoundError:
            raise
        except Exception as e:
            raise IOError(f"加载或解析 .dat 文件 '{dat_path}' 时出错: {e}")

    @staticmethod
    def _is_same_branch(card, name1: str, name2: str, ckt_id: str) -> bool:
        card_name1 = str(card.get_value('NAME1', '')).strip()
        card_name2 = str(card.get_value('NAME2', '')).strip()
        card_ckt_id = str(card.get_value('CKT ID', '')).strip()
        target_name1 = str(name1).strip()
        target_name2 = str(name2).strip()
        target_ckt_id = str(ckt_id).strip()

        same_endpoints = (
            (target_name1 == card_name1 and target_name2 == card_name2) or
            (target_name1 == card_name2 and target_name2 == card_name1)
        )
        return same_endpoints and target_ckt_id == card_ckt_id

    def disable_branch_by_uid(self, full_branch_data: Dict[str, Any], **kwargs):
        """根据支路数据禁用一条支路。"""
        # 从数据中提取关键字段
        name1 = full_branch_data.get("NAME1", "")
        name2 = full_branch_data.get("NAME2", "")
        ckt_id = full_branch_data.get("CKT ID", "")
        
        if not all([name1, name2, ckt_id]):
            print(f"    - 错误: 支路数据不完整，缺少必要字段 (NAME1={name1}, NAME2={name2}, CKT_ID={ckt_id})")
            return False
        
        found = False
        
        for i, card in enumerate(self.dat.cards):
            if isinstance(card, DatL):
                if self._is_same_branch(card, name1, name2, ckt_id):
                    
                    # 注释掉该数据卡
                    card.commented()
                    found = True
                    
                    related_l_plus_count = 0
                    for related_card in self.dat.cards:
                        if str(related_card.get_value('TYPE', '')).strip() == 'L+' and \
                                self._is_same_branch(related_card, name1, name2, ckt_id):
                            related_card.commented()
                            related_l_plus_count += 1
                    
                    print(f"    - 已标记禁用支路: {name1} - {name2} (CKT: {ckt_id})")
                    if related_l_plus_count:
                        print(f"    - 同时禁用了 {related_l_plus_count} 条匹配的L+扩展卡")
                    break
        
    def _find_matching_lines(self, name1: str, name2: str) -> List[Tuple[int, DatL, str]]:
        """
        查找与给定节点名称匹配的所有线路
        
        返回:
            List[Tuple[索引, 线路卡, CKT ID]]
        """
        matching_lines = []
        
        for i, card in enumerate(self.dat.cards):
            if isinstance(card, DatL):
                card_name1 = card.get_value('NAME1', '').strip()
                card_name2 = card.get_value('NAME2', '').strip()
                ckt_id = card.get_value('CKT ID', '').strip()
                
                # 检查节点名称是否匹配（考虑顺序可能相反）
                if ((card_name1 == name1 and card_name2 == name2) or 
                    (card_name1 == name2 and card_name2 == name1)):
                    matching_lines.append((i, card, ckt_id))
        
        return matching_lines

    def _bus_exists(self, name: str) -> bool:
        """检查模型中是否已存在同名母线卡。"""
        target_name = str(name).strip()
        if not target_name:
            return False

        for card in self.dat.cards:
            if not isinstance(card, DatB):
                continue

            card_type = str(card.get_value('TYPE', '')).strip()
            if not card_type.startswith('B'):
                continue

            card_name = str(card.get_value('NAME', '')).strip()
            if card_name == target_name:
                return True

        return False

    @staticmethod
    def _next_numeric_ckt_id(matching_lines: List[Tuple[int, DatL, str]]) -> Optional[int]:
        """Return the next available numeric CKT ID for matching endpoints."""
        numeric_ckt_ids = []
        for _, _, ckt_id in matching_lines:
            try:
                numeric_ckt_ids.append(int(str(ckt_id).strip()))
            except (TypeError, ValueError):
                continue
        if not numeric_ckt_ids:
            return None
        return max(numeric_ckt_ids) + 1

    def _get_insert_position_for_line(self, name1: str, name2: str) -> Tuple[int, Optional[int]]:
        """
        确定新线路的插入位置和CKT ID
        
        参数:
            name1, name2: 新线路的两个节点名称
            
        返回:
            Tuple[插入位置的索引, 新线路的CKT ID；无重复端点时为None]
        """
        # 查找所有匹配的线路
        matching_lines = self._find_matching_lines(name1, name2)
        
        if not matching_lines:
            # 没有找到匹配的线路，使用默认逻辑
            last_l_card_index = max((i for i, c in enumerate(self.dat.cards) if isinstance(c, DatL)), default=-1)
            if last_l_card_index == -1:
                return len(self.dat.cards), None
            return last_l_card_index + 1, None
        
        # 找到最后一个匹配的线路
        last_match_index, last_match_card, last_ckt_id = matching_lines[-1]
        
        # 确定新的CKT ID，避免与相同端点线路重复
        new_ckt_id = self._next_numeric_ckt_id(matching_lines)
        if new_ckt_id is None:
            new_ckt_id = len(matching_lines) + 1
        
        # 检查下一行是否是L+卡
        if last_match_index + 1 < len(self.dat.cards):
            next_card = self.dat.cards[last_match_index + 1]
            if isinstance(next_card, DatB) and next_card.get_value('TYPE') == 'L+':
                # 下一行是L+卡，插入到L+卡后面
                return last_match_index + 2, new_ckt_id
            else:
                # 下一行不是L+卡，直接插入到后面
                return last_match_index + 1, new_ckt_id
        else:
            # 已经是最后一行，插入到末尾
            return len(self.dat.cards), new_ckt_id

    def add_line(self, full_branch_data: Dict[str, Any], **kwargs):
        """
        在电网模型中添加一条新的输电线路 (L卡)。
        
        参数:
            full_branch_data: 包含完整线路数据的字典
        """
        if not full_branch_data:
            raise ValueError("full_branch_data 不能为空")
            
        # 从完整数据中提取必要字段
        required_fields = ['TYPE', 'NAME1', 'BASE1', 'NAME2', 'BASE2', 'CKT ID']
        for field in required_fields:
            if field not in full_branch_data:
                raise ValueError(f"缺少必要字段: {field}")
        
        # 获取节点名称
        name1 = str(full_branch_data.get('NAME1', '')).strip()
        name2 = str(full_branch_data.get('NAME2', '')).strip()
        
        # 查找L卡模板
        template_card = next((c for c in self.dat.cards if isinstance(c, DatL)), None)
        if not template_card:
            raise ValueError("模型中未找到可用的L卡作为模板。")
            
        new_card = deepcopy(template_card)
        
        # 确定插入位置和新的CKT ID
        insert_position, new_ckt_id = self._get_insert_position_for_line(name1, name2)
        effective_ckt_id = str(new_ckt_id) if new_ckt_id is not None else str(full_branch_data.get('CKT ID', '')).strip()
        
        # 设置所有字段
        for field, value in full_branch_data.items():
            try:
                if field in ['BASE1', 'BASE2', 'R', 'X', 'B', 'MILES', 'TOTAL CURRENT RATE AMP']:
                    # 数值字段
                    new_card.set_value(field, float(value))
                elif field in ['NAME1', 'NAME2', 'CKT ID', 'LINE NAME', 'COMMENT']:
                    # 字符串字段
                    if field == 'CKT ID':
                        new_card.set_value(field, effective_ckt_id)
                    else:
                        new_card.set_value(field, str(value))
                else:
                    # 其他字段
                    new_card.set_value(field, value)
            except Exception as e:
                raise ValueError(f"设置字段 '{field}' 时出错: {e}")
        
        # 插入新卡
        self.dat.cards.insert(insert_position, new_card)
        
        line_name = full_branch_data.get('LINE NAME', 'NewLine').strip()
        print(f"    - 已添加新线路 '{line_name}': 从 {name1} 到 {name2} (CKT ID: {effective_ckt_id}, 插入位置: {insert_position})")

    def add_bus(self, full_bus_data: Dict[str, Any], **kwargs):
        """
        在电网模型中添加一个新的母线 (B卡)。
        
        参数:
            full_bus_data: 包含完整母线数据的字典
        """
        if not full_bus_data:
            raise ValueError("full_bus_data 不能为空")
            
        # 从完整数据中提取必要字段
        required_fields = ['TYPE', 'NAME', 'BASE']
        for field in required_fields:
            if field not in full_bus_data:
                raise ValueError(f"缺少必要字段: {field}")

        bus_name = str(full_bus_data.get('NAME', '')).strip()
        if self._bus_exists(bus_name):
            print(f"    - 已存在同名母线，跳过新增: {bus_name}")
            return False
        
        # 查找B卡模板
        template_card = next((c for c in self.dat.cards if isinstance(c, DatB)), None)
        if not template_card:
            raise ValueError("模型中未找到可用的B卡作为模板。")
            
        new_card = deepcopy(template_card)
        
        # 设置所有字段
        for field, value in full_bus_data.items():
            try:
                if field in ['BASE', 'LOAD_P', 'LOAD_Q', 'SHUNTZP', 'SHUNTZQ', 
                           'GEN_P_MAX', 'GEN_P', 'QSCHED', 'GEN_Q_MIN', 'VMAX', 'VMIN']:
                    # 数值字段
                    new_card.set_value(field, float(value))
                elif field in ['NAME', 'ZONE', 'COMMENT']:
                    # 字符串字段
                    new_card.set_value(field, str(value))
                else:
                    # 其他字段
                    new_card.set_value(field, value)
            except Exception as e:
                raise ValueError(f"设置字段 '{field}' 时出错: {e}")
        
        # 插入到最后一个B卡之后，以保持数据区域的连续性
        last_b_card_index = max((i for i, c in enumerate(self.dat.cards) if isinstance(c, DatB)), default=-1)
        if last_b_card_index == -1:
            # 如果没有找到B卡，添加到开头（母线通常在文件开头）
            self.dat.cards.insert(0, new_card)
        else:
            self.dat.cards.insert(last_b_card_index + 1, new_card)
        
        base_kv = full_bus_data.get('BASE', 0)
        print(f"    - 已添加新母线: {bus_name} ({base_kv}kV)")

    def save(self, output_path: str):
        """将当前模型保存到新的 .dat 文件。"""
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            self.dat.save_to_file(output_path)
            print(f"  [Handler] 模型已成功保存到: {output_path}")
        except Exception as e:
            raise IOError(f"保存 .dat 文件到 '{output_path}' 时出错: {e}")
        
    def modify_generator(self):
        """
        修改发电机参数，例如将所有类型为 'Q' 的发电机的 GEN_P 设置为 0。
        """
        for card in self.dat.cards:
            if card.get_value('TYPE') == 'BQ' and card.get_value('GEN_P') != 0.0:
                card.set_value('GEN_P', 0.0)
                break  # 只修改第一个找到的类型为 'Q' 的发电机
        print(f"    - 已修改 1 个类型为 'Q' 的发电机的 GEN_P 参数。")
