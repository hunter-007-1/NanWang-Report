# src/utils/config.py

import os
import yaml
from pathlib import Path

def load_config(config_path: str = "config/settings.yaml") -> dict:
    """
    加载并解析YAML配置文件。

    Args:
        config_path (str): 相对于项目根目录的配置文件路径。

    Returns:
        dict: 包含所有配置信息的字典。

    Raises:
        FileNotFoundError: 如果找不到配置文件。
        yaml.YAMLError: 如果配置文件格式有误。
    """
    full_path = Path(__file__).parent.parent.parent / config_path

    if not full_path.exists():
        raise FileNotFoundError(
            f"配置文件未找到: {full_path}. "
            "请确保您在项目的根目录下运行，并且 'config/settings.yaml' 文件存在。"
        )

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        # Machine-specific values belong in the environment, not the shared YAML.
        paths = config_data.setdefault("paths", {})
        api = config_data.setdefault("api", {})
        paths["dsp_bin_dir"] = os.getenv("DSP_BIN_DIR", paths.get("dsp_bin_dir", ""))
        api["modelscope_api_key"] = os.getenv(
            "MODELSCOPE_API_KEY", api.get("modelscope_api_key", "")
        )
        print(f"配置文件已成功加载: {full_path}")
        return config_data
    except yaml.YAMLError as e:
        print(f"解析配置文件时出错: {e}")
        raise

# (可选) 为了方便在代码中以点（.）访问，可以添加一个简单的转换类
class DotDict(dict):
    """
    一个允许通过点表示法访问其键的字典。
    例如: d.key.subkey 而不是 d['key']['subkey']
    """
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for k, v in self.items():
            if isinstance(v, dict):
                self[k] = DotDict(v)

def load_config_as_dotdict(config_path: str = "config/settings.yaml"):
    """加载配置并返回一个DotDict对象，方便使用。"""
    config_dict = load_config(config_path)
    return DotDict(config_dict)
