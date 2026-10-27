from __future__ import annotations

from dataclasses import dataclass

from src.skills.base import read_skill, render_template


@dataclass(frozen=True)
class InsightsExtractionInput:
    data_tables: str = ""


def render_prompt(payload: InsightsExtractionInput | None = None) -> str:
    values = {"data_tables": payload.data_tables if payload else ""}
    return render_template(read_skill(__file__), **values)

