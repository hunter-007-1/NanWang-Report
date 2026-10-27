from __future__ import annotations

from dataclasses import dataclass

from src.skills.base import read_skill, render_template


@dataclass(frozen=True)
class InsightsReviewInput:
    insights: str
    previous_revision_plan: str = ""


def render_prompt(payload: InsightsReviewInput) -> str:
    return render_template(
        read_skill(__file__),
        insights=payload.insights,
        previous_revision_plan=payload.previous_revision_plan,
    )

