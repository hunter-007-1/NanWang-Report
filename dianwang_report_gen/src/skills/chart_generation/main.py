from __future__ import annotations

from dataclasses import dataclass

from src.skills.base import read_skill, render_template


@dataclass(frozen=True)
class ChartGenerationInput:
    visualization_description: str


def render_prompt(payload: ChartGenerationInput) -> str:
    return render_template(
        read_skill(__file__),
        visualization_description=payload.visualization_description,
    )

