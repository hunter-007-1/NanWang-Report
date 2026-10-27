"""
PCN 验证策略模块

实现论文中定义的验证策略：
- Exact match（精确匹配）
- Rounded match（四舍五入匹配）

参考：Proof-carrying Numbers (PCN) Section 3.4
"""

import re
import math
from dataclasses import dataclass, field
from typing import Optional, Set
from enum import Enum
from decimal import Decimal, ROUND_HALF_UP


class VerificationMode(Enum):
    """验证模式枚举"""
    EXACT = "exact"
    ROUNDED = "rounded"


@dataclass
class VerificationPolicy:
    """
    验证策略配置

    策略字符串格式：
    - "exact": 精确匹配
    - "round{d}": 四舍五入到d位小数，如 "round1", "round0"
    - 组合: "exact|round1"
    """

    modes: Set[VerificationMode] = field(default_factory=lambda: {VerificationMode.EXACT})
    round_digits: Optional[int] = None  # 用于 ROUNDED 模式

    @classmethod
    def from_string(cls, policy_str: str) -> "VerificationPolicy":
        """
        从策略字符串解析验证策略

        Args:
            policy_str: 策略字符串，如 "exact", "round(1)"

        Returns:
            VerificationPolicy 实例
        """
        if not policy_str or policy_str.strip().lower() == "exact":
            return cls(modes={VerificationMode.EXACT})

        part_lower = policy_str.strip().lower()

        # 四舍五入匹配: round(d)
        if part_lower.startswith("round(") and part_lower.endswith(")"):
            try:
                round_digits = int(part_lower[6:-1])  # 提取括号中的数字
                return cls(
                    modes={VerificationMode.ROUNDED},
                    round_digits=round_digits,
                )
            except ValueError:
                return cls(modes={VerificationMode.EXACT})

        # 默认精确匹配
        return cls(modes={VerificationMode.EXACT})

    def to_string(self) -> str:
        """将策略转换为字符串表示"""
        if VerificationMode.ROUNDED in self.modes and self.round_digits is not None:
            return f"round({self.round_digits})"

        return "exact"


class VerificationResult(Enum):
    """验证结果枚举"""
    VERIFIED = "verified"           # 验证通过
    MISMATCH = "mismatch"           # 数值不匹配
    NOT_FOUND = "not_found"         # Claim 未找到
    BARE = "bare"                   # 裸数字（无 claim 标签）


def normalize_number(text: str) -> float:
    """
    归一化数字字符串

    Args:
        text: 包含数字的文本，如 "1,234.56", "12.34 MW"

    Returns:
        数值
    """
    if not text:
        return 0.0

    text = text.strip()

    # 移除空格、逗号，保留数字、小数点和负号
    cleaned = re.sub(r"[\s,a-zA-Z%]+", "", text)

    # 尝试解析为浮点数
    try:
        value = float(cleaned)
    except ValueError:
        value = 0.0

    return value


def round_to_digits(value: float, digits: int) -> float:
    """
    四舍五入到指定小数位

    Args:
        value: 原始数值
        digits: 小数位数

    Returns:
        四舍五入后的数值
    """
    if digits < 0:
        return value

    # 使用 Decimal 进行精确的四舍五入
    d = Decimal(str(value))
    rounded = d.quantize(Decimal(10) ** -digits, rounding=ROUND_HALF_UP)
    return float(rounded)


def check_exact_match(v_text: float, v_claim: float) -> bool:
    """
    精确匹配检查

    R_exact(t, c) = 1 ⇔ v̂ = v*
    """
    return math.isclose(v_text, v_claim, rel_tol=0, abs_tol=0)


def check_rounded_match(v_text: float, v_claim: float, digits: int) -> bool:
    """
    四舍五入匹配检查

    R_round^(d)(t,c) = 1 ⇔ round_d(v̂) = round_d(v*)
    """
    return round_to_digits(v_text, digits) == round_to_digits(v_claim, digits)


def verify_claim(
    text_value: str,
    reference_value: float,
    policy: VerificationPolicy,
    surrounding_text: str = "",
) -> tuple[VerificationResult, str]:
    """
    验证 claim 值是否符合策略

    Args:
        text_value: 文本中的数值字符串
        reference_value: 参考数值
        policy: 验证策略
        surrounding_text: surrounding text for context

    Returns:
        (验证结果, 详细信息)
    """
    # 归一化数值
    v_text = normalize_number(text_value)
    v_claim = float(reference_value)

    # 根据策略模式进行验证
    if VerificationMode.ROUNDED in policy.modes and policy.round_digits is not None:
        # 四舍五入匹配
        if check_rounded_match(v_text, v_claim, policy.round_digits):
            return VerificationResult.VERIFIED, f"rounded match (d={policy.round_digits})"
        rounded_claim = round_to_digits(v_claim, policy.round_digits)
        rounded_text = round_to_digits(v_text, policy.round_digits)
        return VerificationResult.MISMATCH, f"rounded(d={policy.round_digits}): {rounded_text} != {rounded_claim}"
    else:
        # 精确匹配（默认）
        if check_exact_match(v_text, v_claim):
            return VerificationResult.VERIFIED, "exact match"
        return VerificationResult.MISMATCH, f"exact: {v_text} != {v_claim}"


# 便捷函数：创建常用策略


def exact_policy() -> VerificationPolicy:
    """创建精确匹配策略"""
    return VerificationPolicy(modes={VerificationMode.EXACT})


def rounded_policy(digits: int) -> VerificationPolicy:
    """创建四舍五入匹配策略"""
    return VerificationPolicy(
        modes={VerificationMode.ROUNDED},
        round_digits=digits
    )
