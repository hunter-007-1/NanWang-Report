import pypandoc
import re
import os
import html
import shutil
import subprocess
from datetime import datetime
import tempfile
from pathlib import Path
from loguru import logger
from src.graph_state import State
from src.utils.markdown import remove_citations, strip_markdown_fence_noise


def _candidate_xelatex_paths():
    home = Path.home()
    candidates = [
        home / "AppData" / "Local" / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64" / "xelatex.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "MiKTeX" / "miktex" / "bin" / "x64" / "xelatex.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "MiKTeX" / "miktex" / "bin" / "x64" / "xelatex.exe",
    ]
    return candidates


def _get_pdf_pandoc_env():
    """Return an env where xelatex is discoverable, including freshly installed MiKTeX."""
    env = os.environ.copy()
    if shutil.which("xelatex") is not None:
        return env

    for xelatex_path in _candidate_xelatex_paths():
        if xelatex_path.exists():
            env["PATH"] = str(xelatex_path.parent) + os.pathsep + env.get("PATH", "")
            return env

    return None


def _pdf_pandoc_output_format():
    """Use LaTeX writer for PDF export; Pandoc selects PDF from the .pdf output path."""
    return "latex"


def _pdf_documentclass():
    """Avoid report/book chapter headings such as "Chapter 1" in exported PDFs."""
    return "article"


def _fontconfig_has_exact_family(font_name: str) -> bool:
    fc_match = shutil.which("fc-match")
    if fc_match is None:
        return False

    try:
        result = subprocess.run(
            [fc_match, "--format=%{family}", font_name],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    families = [family.strip() for family in result.stdout.split(",") if family.strip()]
    return font_name in families


def _first_available_font(candidates: list[str], fallback: str | None = None) -> str:
    for font_name in candidates:
        if _fontconfig_has_exact_family(font_name):
            return font_name
    return fallback or candidates[0]


def _pdf_font_args():
    if os.name == "nt":
        mainfont = _first_available_font(
            ["Times New Roman", "Cambria", "Arial"],
            fallback="Times New Roman",
        )
        cjkfont = _first_available_font(
            ["Microsoft YaHei", "SimSun", "SimHei", "DengXian"],
            fallback="Microsoft YaHei",
        )
    else:
        mainfont = _first_available_font(
            ["Times New Roman", "DejaVu Serif", "Liberation Serif", "Noto Serif", "FreeSerif"],
            fallback="Times New Roman",
        )
        cjkfont = _first_available_font(
            [
                "WenQuanYi Zen Hei",
                "Noto Sans CJK SC",
                "Noto Serif CJK SC",
                "Source Han Sans SC",
                "Droid Sans Fallback",
                "AR PL SungtiL GB",
            ],
            fallback="WenQuanYi Zen Hei",
        )

    return ["-V", f"mainfont={mainfont}", "-V", f"CJKmainfont={cjkfont}"]


def _timestamped_report_path(report_dir: Path, extension: str, created_at: datetime | None = None) -> Path:
    timestamp = (created_at or datetime.now()).strftime("%Y%m%d_%H%M")
    clean_extension = extension.lower().lstrip(".")
    return report_dir / f"report_{timestamp}.{clean_extension}"


def _latest_report_export_path(report_dir: Path, extension: str) -> Path:
    clean_extension = extension.lower().lstrip(".")
    candidates = list(report_dir.glob(f"report_????????_????.{clean_extension}"))
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime)
    return report_dir / f"report.{clean_extension}"


def _run_with_env(env, func):
    old_path = os.environ.get("PATH")
    os.environ["PATH"] = env.get("PATH", "")
    try:
        return func()
    finally:
        if old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old_path


def _normalize_annotation_wrappers(text: str) -> str:
    """恢复被反引号或 HTML 转义包裹的 claim/calculate 标签。"""
    text = html.unescape(text)

    def _unwrap_inline(tag_name: str, raw: str) -> str:
        pattern = rf"`\s*(<{tag_name}\b[\s\S]*?</{tag_name}>)\s*`"
        return re.sub(pattern, r"\1", raw, flags=re.IGNORECASE)

    text = _unwrap_inline("claim", text)
    text = _unwrap_inline("calculate", text)
    return text


def _convert_annotations_to_footnotes(text: str, target_format: str = "docx") -> str:
    """将 claim/calculate 标签转为 Pandoc 原生脚注。"""
    text = _normalize_annotation_wrappers(text)
    footnotes = []

    def _sanitize_note_for_target(note_text: str) -> str:
        if target_format != "pdf":
            return note_text

        # 脚注正文处于文本模式，避免裸 LaTeX 命令（如 \frac/\times）触发 Missing $
        out = note_text
        out = out.replace("\\times", "×")
        out = out.replace("\\frac", "分式")
        out = out.replace("\\", "")
        out = out.replace("{", "(")
        out = out.replace("}", ")")
        return out

    def _new_ref(note_text: str) -> str:
        footnotes.append(note_text)
        # 使用 Pandoc 原生脚注引用，导出后会呈现为上标并在当前页底部排版
        return f"[^fn{len(footnotes)}]"

    def _claim_replacer(match: re.Match) -> str:
        attrs = (match.group(1) or "").strip()
        inner = match.group(2).strip()

        # claim 内容里可能包含验证标记 <sup ...>✓/✗</sup>，提取后附加到导出文本
        clean_inner = re.sub(r"<sup[^>]*>.*?</sup>", "", inner, flags=re.DOTALL).strip()
        sup_title_match = re.search(r'<sup[^>]*title="([^"]*)"[^>]*>', inner)
        sup_text_match = re.search(r"<sup[^>]*>(.*?)</sup>", inner, flags=re.DOTALL)

        attr_pairs = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        title_text = attr_pairs.get("title", "")
        if not title_text and sup_title_match:
            title_text = sup_title_match.group(1)

        sup_text = sup_text_match.group(1).strip() if sup_text_match else ""
        verify_mark = ""
        if "✓" in sup_text or "Verified:" in title_text:
            verify_mark = r"$\surd$" if target_format == "pdf" else "✓"
        elif "✗" in sup_text or "Expected:" in title_text:
            verify_mark = r"$\times$" if target_format == "pdf" else "✗"
        elif "?" in sup_text or "not found" in title_text.lower():
            verify_mark = "?"

        note_parts = [
            "Claim 溯源",
            f"溯源编号={attr_pairs.get('id', '')}",
            f"源文件路径={attr_pairs.get('source_path', '')}",
            f"字段提取路径={attr_pairs.get('path_to_value', '')}",
            f"匹配策略={attr_pairs.get('policy', 'exact')}",
            f"说明={title_text}",
        ]
        note = "; ".join([p for p in note_parts if p and not p.endswith("=")])
        note = _sanitize_note_for_target(note)
        return f"{clean_inner}{verify_mark}{_new_ref(note)}"

    def _calculate_replacer(match: re.Match) -> str:
        content = match.group(1).strip()

        def _extract(field: str) -> str:
            # 兼容 input_source 与 input source 两种写法
            aliases = [field]
            if field == "input_source":
                aliases.append("input source")
            for alias in aliases:
                m = re.search(
                    rf"{re.escape(alias)}\s*:\s*(.*?)(?=(?:input\s*:|input_source\s*:|input source\s*:|formula\s*:|output\s*:|$))",
                    content,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if m:
                    return " ".join(m.group(1).strip().split())
            return ""

        output = _extract("output") or "计算结果"
        note_parts = [
            "Calculate 计算说明",
            f"计算输入={_extract('input')}",
            f"数据来源={_extract('input_source')}",
            f"计算公式={_extract('formula')}",
            f"计算结果={output}",
        ]
        note = "; ".join([p for p in note_parts if p and not p.endswith("=")])
        note = _sanitize_note_for_target(note)
        return f"{output}{_new_ref(note)}"

    processed = re.sub(
        r"<claim(?:\s+([^>]*))?>(.*?)</claim>",
        _claim_replacer,
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    processed = re.sub(
        r"<calculate>(.*?)</calculate>",
        _calculate_replacer,
        processed,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if not footnotes:
        return processed

    # Pandoc 脚注定义可放在文末；渲染时会在引用所在页显示页脚脚注
    footnote_block = [""]
    for i, note in enumerate(footnotes, start=1):
        footnote_block.append(f"[^fn{i}]: {note}")

    return processed.rstrip() + "\n" + "\n".join(footnote_block) + "\n"


def _is_footnote_definition_start(line: str) -> bool:
    """判断一行是否为 Pandoc 脚注定义的开头（形如 `[^fn1]: ...`）。"""
    stripped = line.lstrip()
    return stripped.startswith("[^") and ("]:" in stripped or "] :" in stripped)


def _fix_bare_latex_formula_lines(text: str) -> str:
    """Wrap standalone LaTeX formula lines that Pandoc would otherwise send as text."""
    fixed_lines = []
    in_display_math_block = False
    in_footnote_def = False

    for line in text.splitlines():
        stripped = line.strip()

        # 脚注定义（多行）整段跳过：Pandoc 会自行解析脚注中的公式，
        # 此处再补 $...$ 会破坏 `$$...$$` 与后续分号同行导致的显示块跟踪。
        if _is_footnote_definition_start(line):
            in_footnote_def = True
            fixed_lines.append(line)
            continue
        if in_footnote_def:
            # 空行或非缩进的非脚注延续行结束当前脚注定义
            if not stripped or (stripped and not line.startswith((" ", "\t")) and not _is_footnote_definition_start(line)):
                in_footnote_def = False
            fixed_lines.append(line)
            continue

        if stripped == "$$":
            fixed_lines.append(line)
            in_display_math_block = not in_display_math_block
            continue

        if in_display_math_block:
            fixed_lines.append(line)
            continue

        if (
            stripped
            and "$" not in line
            and ("\\frac" in stripped or "\\times" in stripped or "\\text" in stripped)
            and not stripped.startswith(("#", "-", "*", "|", "[^fn"))
        ):
            leading = line[: len(line) - len(line.lstrip())]
            trailing = line[len(line.rstrip()) :]
            fixed_lines.append(f"{leading}${stripped}${trailing}")
            continue

        fixed_lines.append(line)

    return "\n".join(fixed_lines)


async def convert_report(state: State) -> dict:
    """
    Converts the markdown report to DOCX and PDF formats.
    加入了抗脆弱设计：自动修复 LaTeX 公式，移除系统字体依赖，增强容错。
    """
    logger.info("=== 开始报告转换节点 ===")
    md_report = strip_markdown_fence_noise(state.md_report or "")
    if not md_report:
        logger.error("Markdown report not found in state.")
        return {
            "docx_success": False,
            "pdf_success": False,
            "docx_error": "Markdown report not found in state.",
            "pdf_error": "Markdown report not found in state.",
        }

    report_dir = state.report_dir
    if not report_dir:
        logger.error("report_dir not found in state.")
        return {
            "docx_success": False,
            "pdf_success": False,
            "docx_error": "report_dir not found in state.",
            "pdf_error": "report_dir not found in state.",
        }

    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"报告目录: {report_dir}")

    report_md_path = report_dir / "report.md"
    export_created_at = datetime.now()
    report_docx_path = _timestamped_report_path(report_dir, "docx", export_created_at)
    report_pdf_path = _timestamped_report_path(report_dir, "pdf", export_created_at)

    # 修复未被数学定界符包裹的 LaTeX 公式，避免破坏已正确的公式
    def fix_math_equations(text: str) -> str:
        fixed_lines = []
        # 匹配 formula: 后面跟着可能带有分号结尾的内容
        formula_pattern = re.compile(r"^(\s*formula:\s*)(.+?)(;?\s*)$")
        in_display_math_block = False
        in_footnote_def = False

        for line in text.splitlines():
            stripped = line.strip()

            # 跳过脚注定义整段：避免 `$$...$$` 被拆行后被错误地补一层 `$...$`
            if _is_footnote_definition_start(line):
                in_footnote_def = True
                fixed_lines.append(line)
                continue
            if in_footnote_def:
                if not stripped or (stripped and not line.startswith((" ", "\t")) and not _is_footnote_definition_start(line)):
                    in_footnote_def = False
                fixed_lines.append(line)
                continue

            if line.strip() == "$$":
                fixed_lines.append(line)
                in_display_math_block = not in_display_math_block
                continue

            if in_display_math_block:
                fixed_lines.append(line)
                continue

            # 该行已存在数学定界符时不做修复，防止把合法公式改坏
            if "$" in line:
                fixed_lines.append(line)
                continue

            # 方案1：如果是 formula: 开头的行，直接包裹后面的内容
            match = formula_pattern.search(line)
            if match:
                prefix = match.group(1)
                eq = match.group(2).strip()
                suffix = match.group(3)
                fixed_lines.append(f"{prefix}${eq}${suffix}")
                continue

            # 方案2：对于独立公式行（含 LaTeX 数学命令但缺少定界符）自动补充 $...$
            stripped = line.strip()
            if (
                stripped
                and "$" not in line
                and "=" in stripped
                and ("\\frac" in stripped or "\\times" in stripped)
                and not stripped.startswith(("#", "-", "*", "|", "[^fn"))
            ):
                fixed_lines.append(f"${stripped}$")
                continue

            fixed_lines.append(line)

        return _fix_bare_latex_formula_lines("\n".join(fixed_lines))

    def normalize_cjk_in_math_for_pdf(text: str) -> str:
        """将数学环境中的中文包装为 \text{}，避免 XeLaTeX 在公式内丢失汉字。"""

        def _protect_existing_text_cmd(expr: str):
            placeholders = []

            def _store(match: re.Match) -> str:
                placeholders.append(match.group(0))
                return f"__TEXTCMD_{len(placeholders)-1}__"

            protected = re.sub(r"\\text\{[^{}]*\}", _store, expr)
            return protected, placeholders

        def _restore_existing_text_cmd(expr: str, placeholders):
            restored = expr
            for idx, chunk in enumerate(placeholders):
                restored = restored.replace(f"__TEXTCMD_{idx}__", chunk)
            return restored

        def _wrap_cjk(expr: str) -> str:
            protected, placeholders = _protect_existing_text_cmd(expr)
            wrapped = re.sub(
                r"([\u4e00-\u9fff]+)",
                lambda m: f"\\text{{{m.group(1)}}}",
                protected,
            )
            return _restore_existing_text_cmd(wrapped, placeholders)

        def _block_replacer(match: re.Match) -> str:
            content = match.group(1).strip()
            return f"$$\n{_wrap_cjk(content)}\n$$"

        def _inline_replacer(match: re.Match) -> str:
            content = match.group(1)
            return f"${_wrap_cjk(content)}$"

        out = re.sub(r"\$\$([\s\S]*?)\$\$", _block_replacer, text)
        out = re.sub(r"\$(?!\$)([^$\n]+?)\$", _inline_replacer, out)
        return out

    def normalize_math_fenced_blocks(text: str) -> str:
        """将 ```math 代码块规范化为 $$...$$ 数学块。"""
        return re.sub(
            r"```math\s*\r?\n([\s\S]*?)\r?\n```",
            lambda m: f"$$\n{m.group(1).strip()}\n$$" if m.group(1).strip() else "",
            text,
            flags=re.IGNORECASE,
        )

    def normalize_math_delimiters_and_percent(text: str) -> str:
        """清理孤立 $ 并规范数学定界符，同时转义数学环境中的 %。"""

        def _escape_percent(expr: str) -> str:
            return re.sub(r"(?<!\\)%", r"\\%", expr)

        # 1) 清理独立一行的孤立 "$"
        lines = text.splitlines()
        cleaned_lines = ["" if ln.strip() == "$" else ln for ln in lines]
        out = "\n".join(cleaned_lines)

        # 2) 规范块公式并转义其中的 %
        def _block_replacer(match: re.Match) -> str:
            expr = match.group(1).strip()
            # 展平 display block 内误嵌套的单行 $...$
            inner = re.match(r"^\s*\$(.+)\$\s*$", expr, flags=re.DOTALL)
            if inner:
                expr = inner.group(1).strip()

            # 若块公式包含中文，改写为“文本 + 局部内联数学”，避免 XeLaTeX 在数学环境中吞中文
            if re.search(r"[\u4e00-\u9fff]", expr):
                expr = re.sub(r"\\text\{([^{}]*)\}", r"\1", expr)

                # 将复杂 LaTeX 片段保留为内联数学
                expr = re.sub(
                    r"(\\frac\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})",
                    lambda m: f"${_escape_percent(m.group(1).strip())}$",
                    expr,
                )
                expr = re.sub(
                    r"(?<!\$)(\\times)(?!\$)",
                    lambda m: f"${m.group(1)}$",
                    expr,
                )

                # 合并连续的内联数学片段，避免输出形如 "$\\times$ $\\frac...$"
                expr = re.sub(r"\$\s*\$", "", expr)
                expr = re.sub(r"\s{2,}", " ", expr).strip()
                return expr

            expr = _escape_percent(expr)
            return f"$$\n{expr}\n$$"

        out = re.sub(r"\$\$([\s\S]*?)\$\$", _block_replacer, out)

        # 3) 规范行内公式（去掉两侧冗余空格）并转义其中的 %
        def _inline_replacer(match: re.Match) -> str:
            expr = _escape_percent(match.group(1).strip())
            return f"${expr}$"

        out = re.sub(r"\$(?!\$)([^$\n]+?)\$", _inline_replacer, out)
        return out

    def sanitize_pdf_math_fallback(text: str) -> str:
        """PDF 兜底：移除 \text 包裹并补全疑似裸公式的数学定界符。"""
        out = re.sub(r"\\text\{([^{}]*)\}", r"\1", text)

        fixed_lines = []
        in_display_math_block = False
        in_footnote_def = False
        for line in out.splitlines():
            stripped = line.strip()

            # 跳过脚注定义整段，避免在脚注内的公式被错误补一层 `$...$`
            if _is_footnote_definition_start(line):
                in_footnote_def = True
                fixed_lines.append(line)
                continue
            if in_footnote_def:
                if not stripped or (stripped and not line.startswith((" ", "\t")) and not _is_footnote_definition_start(line)):
                    in_footnote_def = False
                fixed_lines.append(line)
                continue

            if stripped == "$$":
                fixed_lines.append(line)
                in_display_math_block = not in_display_math_block
                continue

            if in_display_math_block:
                fixed_lines.append(line)
                continue

            if (
                stripped
                and "$" not in line
                and ("\\frac" in line or "\\times" in line)
                and "=" in stripped
                and not stripped.startswith(("#", "-", "*", "|", "[^fn"))
            ):
                fixed_lines.append(f"${stripped}$")
            else:
                fixed_lines.append(line)
        return "\n".join(fixed_lines)

    try:
        pandoc_path = pypandoc.get_pandoc_path()
        if not pandoc_path:
            raise RuntimeError("pandoc 未安装或不在 PATH 中")
        # Windows 上 pypandoc 返回的路径可能没有 .exe 后缀
        if os.name == "nt" and not pandoc_path.endswith(".exe"):
            pandoc_path = pandoc_path + ".exe"
        if not os.path.exists(pandoc_path):
            raise RuntimeError(f"pandoc 可执行文件不存在: {pandoc_path}")

        # 1. 保存原始的带引用的 markdown 报告
        with open(report_md_path, "w", encoding="utf-8") as f:
            f.write(md_report)
        logger.info(f"原始 Markdown 报告已保存到 {report_md_path}")

        docx_success = False
        pdf_success = False
        docx_error = ""
        pdf_error = ""

        # 2. 确定要转换的内容（优先使用带 PCN 验证颜色的内容，否则降级使用无引用的纯净版）
        pdf_content = strip_markdown_fence_noise(
            state.pdf_report_content or remove_citations(md_report)
        )
        docx_content = strip_markdown_fence_noise(
            state.docx_report_content or remove_citations(md_report)
        )

        # 3. 将 claim/calculate 标签转换为脚注（仅用于 PDF/DOCX，不改原始 md）
        pdf_content = _convert_annotations_to_footnotes(pdf_content, target_format="pdf")
        docx_content = _convert_annotations_to_footnotes(docx_content, target_format="docx")

        # 3.1 兼容 markdown 的 ```math 代码块
        pdf_content = normalize_math_fenced_blocks(pdf_content)
        docx_content = normalize_math_fenced_blocks(docx_content)

        # 3.2 清理异常数学定界符，避免导出结果中出现裸 "$"
        pdf_content = normalize_math_delimiters_and_percent(pdf_content)
        docx_content = normalize_math_delimiters_and_percent(docx_content)

        # 4. 强制修复准备转换的内容里的数学公式语法！
        pdf_content = fix_math_equations(pdf_content)
        docx_content = fix_math_equations(docx_content)
        pdf_content = normalize_cjk_in_math_for_pdf(pdf_content)

        with tempfile.TemporaryDirectory(prefix="report_convert_", dir=str(report_dir)) as tmpdir:
            tmpdir_path = Path(tmpdir)
            pdf_temp_path = tmpdir_path / "report_pdf_temp.md"
            docx_temp_path = tmpdir_path / "report_docx_temp.md"
            temp_docx_output = tmpdir_path / "report.docx"
            temp_pdf_output = tmpdir_path / "report.pdf"

            with open(pdf_temp_path, "w", encoding="utf-8") as f:
                f.write(pdf_content)
            with open(docx_temp_path, "w", encoding="utf-8") as f:
                f.write(docx_content)

            # ==========================================
            # 转换流程 A：生成 DOCX (稳定保底)
            # ==========================================
            logger.info("开始生成 DOCX 格式报告...")
            try:
                pypandoc.convert_file(
                    str(docx_temp_path),
                    "docx",
                    outputfile=str(temp_docx_output),
                    extra_args=["--standalone", "--resource-path", str(report_dir)]
                )
                os.replace(temp_docx_output, report_docx_path)
                logger.info(f"✅ DOCX 格式报告已成功生成: {report_docx_path}")
                docx_success = True
            except Exception as e:
                logger.error(f"❌ DOCX 生成失败: {e}")
                docx_error = str(e)

            # ==========================================
            # 转换流程 B：生成 PDF (适配 Linux 环境)
            # ==========================================
            logger.info("开始生成 PDF 格式报告...")
            pdf_env = _get_pdf_pandoc_env()
            if pdf_env is None:
                pdf_error = "xelatex 未安装或不在 PATH 中"
                logger.warning(f"❌ PDF 生成失败: {pdf_error}")
            else:
                try:
                    _run_with_env(
                        pdf_env,
                        lambda: pypandoc.convert_file(
                            str(pdf_temp_path),
                            _pdf_pandoc_output_format(),
                            outputfile=str(temp_pdf_output),
                            extra_args=[
                                "--pdf-engine=xelatex",
                                *_pdf_font_args(),
                                "-V", f"documentclass={_pdf_documentclass()}",
                                "--from", "markdown+tex_math_dollars",
                                "--resource-path", str(report_dir),
                            ],
                        ),
                    )
                    os.replace(temp_pdf_output, report_pdf_path)
                    logger.info(f"✅ PDF 格式报告已成功生成: {report_pdf_path}")
                    pdf_success = True
                except Exception as e:
                    logger.warning(f"❌ PDF 首次生成失败，尝试兜底修复后重试: \n{e}")
                    pdf_error = str(e)
                    try:
                        pdf_fallback_content = sanitize_pdf_math_fallback(pdf_content)
                        pdf_fallback_temp_path = tmpdir_path / "report_pdf_temp_fallback.md"
                        with open(pdf_fallback_temp_path, "w", encoding="utf-8") as f:
                            f.write(pdf_fallback_content)

                        _run_with_env(
                            pdf_env,
                            lambda: pypandoc.convert_file(
                                str(pdf_fallback_temp_path),
                                _pdf_pandoc_output_format(),
                                outputfile=str(temp_pdf_output),
                                extra_args=[
                                    "--pdf-engine=xelatex",
                                    *_pdf_font_args(),
                                    "-V", f"documentclass={_pdf_documentclass()}",
                                    "--from", "markdown+tex_math_dollars",
                                    "--resource-path", str(report_dir),
                                ],
                            ),
                        )
                        os.replace(temp_pdf_output, report_pdf_path)
                        logger.info(f"✅ PDF 兜底重试成功: {report_pdf_path}")
                        pdf_success = True
                        pdf_error = ""
                    except Exception as e2:
                        logger.warning(f"❌ PDF 兜底重试仍失败: \n{e2}")
                        logger.warning("跳过 PDF 报错，工作流将继续（已用 DOCX 兜底）。")
                        pdf_error = str(e2)

        logger.info("=== 报告转换节点完成 ===")
        return {
            "docx_report_path": report_docx_path,
            "pdf_report_path": report_pdf_path,
            "docx_success": docx_success,
            "pdf_success": pdf_success,
            "docx_error": docx_error,
            "pdf_error": pdf_error,
        }

    except Exception as e:
        logger.error(f"报告转换过程中发生致命错误: {e}")
        message = str(e)
        return {
            "docx_report_path": str(report_docx_path),
            "pdf_report_path": str(report_pdf_path),
            "docx_success": False,
            "pdf_success": False,
            "docx_error": message,
            "pdf_error": message,
        }