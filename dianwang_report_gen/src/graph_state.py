from langgraph.graph import add_messages
from typing import Optional, List, Annotated, Dict, Any
from dataclasses import dataclass, field
from langchain_core.messages import AnyMessage
from pathlib import Path

from src.pcn import Claim


@dataclass
class InputState:
    uuid: str = ""
    messages: Annotated[list[AnyMessage], add_messages] = field(default_factory=list)


# Graph state
@dataclass
class State(InputState):
    debug: bool = False
    data_filtered: bool = False

    insights: str = ""
    first_insights: str = ""

    input_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    working_dir: Optional[Path] = None
    report_dir: Optional[Path] = None
    md_tables_dir: Optional[Path] = None

    md_tables_str: Optional[str] = None

    # 工程背景 / 接入方案原始资料（来自 generation/background_context.md 等）
    background_context: str = ""
    background_context_source: str = ""

    raw_report: Optional[str] = None
    md_report: Optional[str] = None
    report_quality_result: Optional[Dict[str, Any]] = None

    pdf_report_content: Optional[str] = None
    docx_report_content: Optional[str] = None

    # PCN 相关状态
    pcn_claims: Optional[Dict[str, Claim]] = None
    pcn_claim_index: Optional[Dict[str, List[Claim]]] = None
    pcn_db_path: Optional[Path] = None  # SQLite FTS5 数据库路径
    pcn_verification_result: Optional[Dict[str, Any]] = None
    pcn_verification_passed: bool = False
    pcn_verification_report_path: Optional[Path] = None

    # 检索的 claims
    retrieved_claims: str = ""
