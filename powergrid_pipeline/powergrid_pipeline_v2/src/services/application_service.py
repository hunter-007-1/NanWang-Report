# src/services/application_service2.py
import os
from typing import Dict, Any, List, Optional

# 导入底层的核心模块
from ..core.grid_model_handler import GridModelHandler

class ApplicationService:
    """
    负责将一个结构化的规划方案应用到基础电网模型上，生成一个新的模型文件。
    """
    
    def apply_single_proposal(self, proposal: Dict[str, Any], base_dat_path: str, 
                          swi_path: str, scset_path: str, lsd_path: str, 
                          output_dat_path: str) -> tuple[bool, str]:
        """
        应用单个方案到基础电网模型
        """
        print(f"[Application] 正在将方案 '{proposal.get('proposal_name', '未知方案')}' 应用到 '{os.path.basename(base_dat_path)}'...")
        
        try:
            # 1. 加载基础模型
            model_handler = GridModelHandler(base_dat_path)
            
            # 2. 遍历并执行所有修改指令
            modifications = proposal.get('modifications', [])
            if not modifications:
                print("  - 方案中无修改指令，将保存为原始模型的副本。")
            
            for mod in modifications:
                action = mod.get('action')
                params = mod.get('params', {})
                
                print(f"  - 执行动作: {action}")
                
                if action == "disable_branch":
                    model_handler.disable_branch_by_uid(**params)
                elif action == "add_line":
                    model_handler.add_line(**params)
                elif action == "add_bus":
                    # 添加对add_bus动作的支持
                    model_handler.add_bus(**params)
                else:
                    print(f"    - 警告: 跳过未知的动作 '{action}'。")
            
            # 3. 保存新模型
            model_handler.save(output_dat_path)
            
            # 4. 复制swi和scset文件到新模型同目录
            import shutil
            output_dir = os.path.dirname(output_dat_path)
            
            if swi_path and os.path.exists(swi_path):
                swi_filename = os.path.basename(swi_path)
                dest_swi_path = os.path.join(output_dir, swi_filename)
                shutil.copy2(swi_path, dest_swi_path)
                print(f"  - 已复制SWI文件到: {dest_swi_path}")
            
            if scset_path and os.path.exists(scset_path):
                scset_filename = os.path.basename(scset_path)
                dest_scset_path = os.path.join(output_dir, scset_filename)
                shutil.copy2(scset_path, dest_scset_path)
                print(f"  - 已复制SCSET文件到: {dest_scset_path}")

            if lsd_path and os.path.exists(lsd_path):
                lsd_filename = os.path.basename(lsd_path)
                dest_lsd_path = os.path.join(output_dir, lsd_filename)
                shutil.copy2(lsd_path, dest_lsd_path)
                print(f"  - 已复制lsd文件到: {dest_lsd_path}")
            
            print(f"[Application] 方案应用成功！新模型和相关文件已保存。")
            return True, f"成功生成文件: {output_dat_path}"

        except Exception as e:
            print(f"[Application] 方案应用失败: {e}")
            return False, str(e)
    
    def apply(self, proposal_data: Dict[str, Any], base_dat_path: str, output_dat_path: str, 
              proposal_index: int = 0) -> tuple[bool, str]:
        """
        【工具1】: 应用一个方案。
        
        参数:
        - proposal_data: 包含方案数据的字典，可以是单个方案或包含proposals数组的完整数据
        - base_dat_path: 基础模型文件路径
        - output_dat_path: 输出模型文件路径
        - proposal_index: 如果proposal_data包含多个方案，指定要应用的方案索引
        """
        # 检查数据结构，处理两种可能的格式
        if 'proposals' in proposal_data:
            # 格式1: 包含proposals数组的完整数据
            proposals = proposal_data.get('proposals', [])
            if not proposals:
                return False, "未找到任何方案数据"
            
            if proposal_index >= len(proposals):
                return False, f"方案索引 {proposal_index} 超出范围，共有 {len(proposals)} 个方案"
            
            proposal = proposals[proposal_index]
            print(f"[Application] 从方案列表中选择了第 {proposal_index + 1} 个方案: '{proposal.get('proposal_name', '未知方案')}'")
            
        else:
            # 格式2: 单个方案数据
            proposal = proposal_data
        
        return self.apply_single_proposal(proposal, base_dat_path, output_dat_path)
    
    def get_all_proposals(self, proposal_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        获取所有可用的方案列表
        """
        if 'proposals' in proposal_data:
            return proposal_data.get('proposals', [])
        else:
            # 如果传入的是单个方案，包装成列表返回
            return [proposal_data]
    
    def apply_all_proposals(self, proposal_data: Dict[str, Any], base_dat_path: str, 
                            swi_path: str, scset_path: str, lsd_path: str, 
                            output_dir: str) -> List[tuple[bool, str]]:
        """
        应用所有方案，为每个方案生成单独的输出文件
        """
        results = []
        proposals = self.get_all_proposals(proposal_data)
        
        for i, proposal in enumerate(proposals):
            proposal_name = proposal.get('proposal_name', f'方案{i+1}')
            # 清理文件名，移除可能的不合法字符
            # safe_name = "".join(c for c in proposal_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            output_path = os.path.join(output_dir, f"method_{i+1}/applied_model_{i+1}.dat")
            
            print(f"\n[Application] 正在处理方案 {i+1}/{len(proposals)}: {proposal_name}")
            success, message = self.apply_single_proposal(proposal, base_dat_path, swi_path, scset_path, lsd_path, output_path)
            results.append((success, message))
        
        return True, results
    
    # def adjust_generator(self, dat_path: str):
    #     """
    #     【工具2】: 修改发电机参数，例如将所有类型为 'Q' 的发电机的 GEN_P 设置为 0。
    #     """
    #     try:
    #         model_handler = GridModelHandler(dat_path)

    #         model_handler.modify_generator()
    #         model_handler.save(dat_path)  # 保存修改后的模型
    #         print(f"[Application] 已成功调整发电机参数并保存到 '{dat_path}'")
    #         return True, f"已成功调整发电机参数并保存到 '{dat_path}'"
    #     except Exception as e:
    #         print(f"[Application] 调整发电机参数失败: {e}")
    #         return False, str(e)