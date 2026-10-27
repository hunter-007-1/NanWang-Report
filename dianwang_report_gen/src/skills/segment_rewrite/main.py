from __future__ import annotations

from dataclasses import dataclass

from src.skills.base import read_skill, render_template


@dataclass(frozen=True)
class SegmentRewriteInput:
    selected_text: str
    instruction: str
    left_context: str = ""
    right_context: str = ""


def render_prompt(payload: SegmentRewriteInput) -> str:
    return render_template(
        read_skill(__file__),
        selected_text=payload.selected_text,
        instruction=payload.instruction,
        left_context=payload.left_context,
        right_context=payload.right_context,
    ).strip()

