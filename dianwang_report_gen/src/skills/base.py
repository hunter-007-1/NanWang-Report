from __future__ import annotations

from pathlib import Path
from typing import Any


def skill_dir(anchor_file: str) -> Path:
    return Path(anchor_file).resolve().parent


def read_skill(anchor_file: str) -> str:
    return (skill_dir(anchor_file) / "SKILL.md").read_text(encoding="utf-8")


def read_resource(anchor_file: str, name: str) -> str:
    return (skill_dir(anchor_file) / "resources" / name).read_text(encoding="utf-8")


def read_shared_resource(name: str) -> str:
    return (Path(__file__).resolve().parent / "resources" / name).read_text(
        encoding="utf-8"
    )


def render_template(template: str, **values: Any) -> str:
    return template.format(**values)

