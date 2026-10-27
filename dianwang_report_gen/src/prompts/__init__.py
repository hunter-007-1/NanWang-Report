from pathlib import Path

BASE_DIR = Path(__file__).parent
SKILLS_DIR = Path(__file__).parents[1] / "skills"

ACCESS_SCHEMES_COMPARING_PRINCIPLES = (
    SKILLS_DIR / "insights_generation" / "resources" / "access_schemes_comparing_principles.md"
).read_text(encoding="utf-8")

REPORT_OUTLINE = (SKILLS_DIR / "report_generation" / "resources" / "report_outline.md").read_text(encoding="utf-8")

chart_code_generation_user_prompt_template = (
    SKILLS_DIR / "chart_generation" / "SKILL.md"
).read_text(encoding="utf-8")

report_generation_user_prompt_template = (
    SKILLS_DIR / "report_generation" / "SKILL.md"
).read_text(encoding="utf-8")

report_iterative_generation_prompt_template = (
    SKILLS_DIR / "report_generation" / "SKILL.md"
).read_text(encoding="utf-8")

report_iterative_generation_prompt_template_old = (
    SKILLS_DIR / "report_generation" / "resources" / "claim_protocol.md"
).read_text(encoding="utf-8")

pandoc_tables_syntax = (SKILLS_DIR / "report_generation" / "resources" / "pandoc_tables_syntax.md").read_text(
    encoding="utf-8"
)

insights_generation_system_prompt_template = (
    SKILLS_DIR / "insights_generation" / "SKILL.md"
).read_text(encoding="utf-8")

INSIGHTS_EXTRACTION_USER_PROMPT = (
    SKILLS_DIR / "insights_extraction" / "SKILL.md"
).read_text(encoding="utf-8")

insights_review_user_prompt_template = (
    SKILLS_DIR / "insights_review" / "SKILL.md"
).read_text(encoding="utf-8")

insights_revision_user_prompt_template = (
    SKILLS_DIR / "insights_revision" / "SKILL.md"
).read_text(encoding="utf-8")

report_optimization_user_prompt_template = (
    SKILLS_DIR / "report_optimization" / "SKILL.md"
).read_text(encoding="utf-8")


__all__ = [
    "ACCESS_SCHEMES_COMPARING_PRINCIPLES",
    "REPORT_OUTLINE",
    "chart_code_generation_user_prompt_template",
    "report_generation_user_prompt_template",
    "report_iterative_generation_prompt_template",
    "report_iterative_generation_prompt_template_old",
    "pandoc_tables_syntax",
    "insights_generation_system_prompt_template",
    "INSIGHTS_EXTRACTION_USER_PROMPT",
    "insights_review_user_prompt_template",
    "insights_revision_user_prompt_template",
    "report_optimization_user_prompt_template",
]
