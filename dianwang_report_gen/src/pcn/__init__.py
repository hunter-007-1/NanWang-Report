from dataclasses import dataclass, field
from typing import Any, List, Optional

from .verification_policies import (
    VerificationPolicy,
    VerificationResult,
    VerificationMode,
    verify_claim,
    exact_policy,
    rounded_policy,
)


@dataclass
class Claim:
    """
    PCN Claim 数据类

    对应论文中的 claim 结构：
    c = <claim_id, indicator, entity, time, v*, u, m>

    Attributes:
        claim_id: 唯一标识符 (如 "000001")
        indicator: 指标名称 (如 "损耗_MW")
        value: 数值 (v*)
        unit: 单位 (u)，如 "MW", "%", "kV"
        entity: 实体名称 (如设备名、节点名)
        time: 时间维度 (如 "2024", "Q1")
        policy: 验证策略，用于验证时的规则
        metadata: 元数据，包含 source_path, path_to_value, original_type, context
    """

    claim_id: str
    indicator: str
    value: float
    unit: Optional[str] = None
    entity: Optional[str] = None
    time: Optional[str] = None
    policy: Optional[VerificationPolicy] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_policy_string(self) -> str:
        """获取策略字符串表示"""
        if self.policy is None:
            return "exact"
        return self.policy.to_string()


__all__ = [
    # 核心类
    "Claim",
    # 验证策略
    "VerificationPolicy",
    "VerificationResult",
    "VerificationMode",
    "verify_claim",
    # 便捷函数
    "exact_policy",
    "rounded_policy",
]
