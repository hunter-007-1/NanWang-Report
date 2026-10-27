# src/core/simulation_runner.py

import os
import subprocess
from typing import Tuple

class SimulationRunner:
    """
    封装与外部BPA/DSP仿真程序的命令行交互。
    """
    def __init__(self, config):
        self.dsp_bin_dir = config.paths.dsp_bin_dir
        self.default_pf_mode = config.simulation_params.power_flow_mode
        if not os.path.isdir(self.dsp_bin_dir):
            raise FileNotFoundError(f"DSP Bin 目录未找到: '{self.dsp_bin_dir}'. 请检查配置文件。")

    def run_power_flow(self, dat_path, mode=1):
        """
        执行BPA潮流计算程序Pfauto.exe

        参数:
            dat_path (str): BPA数据文件(.dat)的路径
            mode (int): 运行模式选项,默认为1。可选值如下:
                1 - 默认模式,读写历史解法(操作前20行".DSP"开头的行)
                2 - 不读历史解法,也不写历史解法
                3 - 不读历史解法,但写历史解法
                4 - 读历史解法,也写历史解法

        返回:
            无返回值,直接执行系统命令
        """
        if mode == 1:  # 默认模式:读写历史解法
            command = ''
        elif mode == 2:  # 不读历史解法,也不写历史解法
            command = '1 0'
        elif mode == 3:  # 不读历史解法,但写历史解法
            command = '1 \".DSP\"'
        elif mode == 4:  # 读历史解法,也写历史解法
            command = '1 \".DSP 11000\"'
        else:
            raise ValueError('Unknown mode')
        
        abs_dat_path = os.path.abspath(dat_path)

        # 使用类的实例属性 self.dsp_bin_dir
        command = ' '.join([os.path.join(self.dsp_bin_dir, 'pfauto'), abs_dat_path, command, '> NUL 2> NUL'])
        code = subprocess.run(command, shell=True, check=False).returncode
        return code

    def run_TSSIM(self, dat_path, swi_path):
        """
        注意：dat和swi需要在同个文件夹下
        """
        abs_dat_path = os.path.abspath(dat_path)
        abs_swi_path = os.path.abspath(swi_path)

        # 获取.dat文件所在的目录，这将作为工作目录
        work_dir = os.path.dirname(abs_dat_path)
        
        # 使用类的实例属性 self.dsp_bin_dir
        conv_cmd = [
            os.path.join(self.dsp_bin_dir, 'tsconvt'),
            os.path.basename(abs_swi_path),
            os.path.basename(abs_dat_path),
            'CIDYDAT_E'
        ]
        
        sim_cmd = [
            os.path.join(self.dsp_bin_dir, 'tssim'),
            work_dir + os.sep,
            '100'
        ]

        conv_process = subprocess.run(conv_cmd, cwd=work_dir, shell=False, capture_output=True, text=True)
        sim_process = subprocess.run(sim_cmd, cwd=work_dir, shell=False, capture_output=True, text=True)
        return sim_process.returncode


    def run_short_circuit(self, dat_path: str, swi_path: str, scset_path: str) -> Tuple[bool, str]:
        """
        执行BPA短路电流计算程序 (dspsc.exe)。
        """
        # 兼容不同操作系统
        exe_name = 'dspsc.exe' if os.name == 'nt' else 'dspsc'
        dspsc_exe_path = os.path.join(self.dsp_bin_dir, exe_name)
        
        # 确保所有路径都是绝对路径
        abs_dat_path = os.path.abspath(dat_path)
        abs_swi_path = os.path.abspath(swi_path)
        abs_scset_path = os.path.abspath(scset_path)
        
        command = [
            dspsc_exe_path,
            abs_scset_path,
            abs_dat_path,
            abs_swi_path,
            '1', '0' # 假设这些是固定参数
        ]

        print(f"  [Runner] 执行: {' '.join(command)}")

        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding='gbk', check=False
            )
            success = result.returncode == 0
            log_message = f"返回码: {result.returncode}\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            if not success:
                print(f"  [Runner] 短路计算失败! {log_message}")
            return success, log_message
        except FileNotFoundError:
            return False, f"错误: 无法找到程序 '{dspsc_exe_path}'."
        except Exception as e:
            return False, f"执行时发生未知异常: {e}"
