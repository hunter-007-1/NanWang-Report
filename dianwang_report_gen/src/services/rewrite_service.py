from __future__ import annotations

from dataclasses import dataclass

from src.llm import client_manager
from src.skills.segment_rewrite.main import (
    SegmentRewriteInput,
    render_prompt as render_segment_rewrite_prompt,
)


@dataclass
class RewriteResult:
    rewritten_text: str
    notes: str = ""


def rewrite_selected_segment(
    selected_text: str,
    instruction: str,
    left_context: str = "",
    right_context: str = "",
) -> RewriteResult:
    """Rewrite only the selected markdown segment according to user instruction."""
    llm_client, llm_model, llm_temperature = client_manager.get_llm_openai_client()
    if llm_client is None or not llm_model:
        raise RuntimeError("LLM 客户端未初始化")

    prompt = render_segment_rewrite_prompt(
        SegmentRewriteInput(
            selected_text=selected_text,
            instruction=instruction,
            left_context=left_context,
            right_context=right_context,
        )
    )

    response = llm_client.chat.completions.create(
        model=llm_model,
        temperature=llm_temperature,
        messages=[{"role": "user", "content": prompt}],
    )

    choices = getattr(response, "choices", None) or []
    text = ""
    if choices and getattr(choices[0], "message", None):
        text = str(choices[0].message.content or "").strip()

    if not text:
        raise RuntimeError("模型未返回改写结果")

    return RewriteResult(
        rewritten_text=text,
        notes="demo_mvp_single_round",
    )
