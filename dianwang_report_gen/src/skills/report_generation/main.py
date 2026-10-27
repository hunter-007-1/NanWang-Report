from __future__ import annotations

from dataclasses import dataclass

from src.skills.base import read_resource, read_shared_resource, read_skill, render_template


@dataclass(frozen=True)
class ReportGenerationInput:
    data_tables: str
    insights: str
    retrieved_claims: str = ""
    background_context: str = ""


def render_prompt(payload: ReportGenerationInput) -> str:
    claim_protocol = render_template(
        read_resource(__file__, "claim_protocol.md"),
        retrieved_claims=payload.retrieved_claims or "",
    )
    return render_template(
        read_skill(__file__),
        pandoc_tables_syntax=read_resource(__file__, "pandoc_tables_syntax.md"),
        outline=read_resource(__file__, "report_outline.md"),
        compare_rules=read_shared_resource("compare_rules.md"),
        data_tables=payload.data_tables,
        insights=payload.insights,
        claim_protocol=claim_protocol,
        background_context=payload.background_context or "",
    )

