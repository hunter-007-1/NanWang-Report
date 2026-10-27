from __future__ import annotations

from dataclasses import dataclass

from src.skills.base import read_skill, render_template


@dataclass(frozen=True)
class ReportOptimizationInput:
    report_content: str


def render_prompt(payload: ReportOptimizationInput) -> str:
    return render_template(read_skill(__file__), report_content=payload.report_content)

