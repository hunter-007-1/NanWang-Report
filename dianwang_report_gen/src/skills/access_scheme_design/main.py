from __future__ import annotations

from src.skills.base import read_skill


def render_prompt(payload=None) -> str:
    return read_skill(__file__)

