from __future__ import annotations

from dataclasses import dataclass

from src.skills.base import read_skill, render_template


@dataclass(frozen=True)
class InsightsRevisionInput:
    old_insights: str
    revision_plan: str


def render_prompt(payload: InsightsRevisionInput) -> str:
    return render_template(
        read_skill(__file__),
        old_insights=payload.old_insights,
        revision_plan=payload.revision_plan,
    )

