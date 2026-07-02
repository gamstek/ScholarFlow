"""
section_parser.py

论文正文章节识别模块。

作用：
1. 根据 PDF 提取文本，粗略识别 Abstract / Introduction / Methods / Results 等章节；
2. 给每个 section 记录起始页、结束页和文本；
3. 为后续 chunk 切分提供 section_title。

当前是规则版 Section Parser：
    - 可解释；
    - 易调试；
    - 适合 V0。

后续可以升级：
    - 基于版面信息的标题识别；
    - 基于字体大小的标题识别；
    - 基于机器学习的 section classification。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ParsedSection:
    """
    解析出的章节。

    字段说明：
        section_title:
            章节标题。

        page_start:
            起始页码。

        page_end:
            结束页码。

        text:
            章节文本。

        char_count:
            字符数。
    """

    section_title: str
    page_start: int | None
    page_end: int | None
    text: str
    char_count: int


# 常见论文一级章节标题
CANONICAL_SECTION_NAMES: list[str] = [
    "abstract",
    "graphical abstract",
    "keywords",
    "introduction",
    "background",
    "related work",
    "materials and methods",
    "methods",
    "experimental",
    "experimental section",
    "sample preparation",
    "chemicals and reagents",
    "lc-ms/ms analysis",
    "mass spectrometry",
    "liquid chromatography",
    "data processing",
    "results",
    "results and discussion",
    "discussion",
    "structural elucidation",
    "structural characterization",
    "conclusion",
    "conclusions",
    "author contributions",
    "conflict of interest",
    "acknowledgements",
    "acknowledgments",
    "references",
    "supplementary material",
]


def normalize_line(line: str) -> str:
    """
    标准化单行文本，用于标题判断。
    """
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    return line


def strip_number_prefix(line: str) -> str:
    """
    去掉章节编号。

    示例：
        "1 Introduction" -> "Introduction"
        "2. Materials and methods" -> "Materials and methods"
        "3.1 LC-MS/MS analysis" -> "LC-MS/MS analysis"
    """
    line = line.strip()

    # 匹配 1 / 1. / 1.1 / 1.1.2 等章节编号
    line = re.sub(
        r"^\d+(\.\d+)*\.?\s+",
        "",
        line,
    )

    return line.strip()


def is_probable_section_title(line: str) -> bool:
    """
    判断某一行是否可能是章节标题。

    规则：
        1. 行不能太长；
        2. 去掉编号后，和常见章节名匹配；
        3. 或者包含特定关键词且行较短。
    """
    line = normalize_line(line)

    if not line:
        return False

    # 太长一般不是标题
    if len(line) > 120:
        return False

    # 参考文献中的条目经常以数字开头，但很长，这里已经被长度挡掉一部分
    candidate = strip_number_prefix(line).lower().strip(" .:-")

    if candidate in CANONICAL_SECTION_NAMES:
        return True

    # 常见方法章节标题
    important_terms = [
        "lc-ms",
        "lc-ms/ms",
        "mass spectrometry",
        "sample preparation",
        "structural elucidation",
        "structural characterization",
        "fragmentation",
        "data analysis",
    ]

    if len(candidate) <= 80:
        for term in important_terms:
            if term in candidate:
                return True

    return False


def canonicalize_section_title(line: str) -> str:
    """
    将章节标题规范化。

    示例：
        "1. Introduction" -> "Introduction"
        "MATERIALS AND METHODS" -> "Materials And Methods"
    """
    line = normalize_line(line)
    line = strip_number_prefix(line)
    line = line.strip(" .:-")

    if not line:
        return "Unknown"

    # 保留 LC-MS/MS 等特殊写法
    lower = line.lower()

    special_map = {
        "abstract": "Abstract",
        "introduction": "Introduction",
        "materials and methods": "Materials and Methods",
        "methods": "Methods",
        "experimental": "Experimental",
        "results": "Results",
        "discussion": "Discussion",
        "results and discussion": "Results and Discussion",
        "conclusion": "Conclusion",
        "conclusions": "Conclusion",
        "references": "References",
        "lc-ms/ms analysis": "LC-MS/MS Analysis",
        "mass spectrometry": "Mass Spectrometry",
        "structural elucidation": "Structural Elucidation",
        "structural characterization": "Structural Characterization",
    }

    if lower in special_map:
        return special_map[lower]

    return line.title()


def parse_sections_from_pages(
    pages: list[dict[str, Any]],
) -> list[ParsedSection]:
    """
    从页面文本中粗略解析章节。

    参数：
        pages:
            PDF parser 输出的 pages 列表。
            每个元素应包含：
                page_number
                text

    返回：
        ParsedSection 列表。
    """
    sections: list[ParsedSection] = []

    current_title = "Unknown"
    current_lines: list[str] = []
    current_page_start: int | None = None
    current_page_end: int | None = None

    def flush_current_section() -> None:
        """
        将当前累积的 section 写入 sections。
        """
        nonlocal current_lines
        nonlocal current_title
        nonlocal current_page_start
        nonlocal current_page_end

        text = "\n".join(current_lines).strip()

        if not text:
            current_lines = []
            return

        section = ParsedSection(
            section_title=current_title,
            page_start=current_page_start,
            page_end=current_page_end,
            text=text,
            char_count=len(text),
        )

        sections.append(section)
        current_lines = []

    for page in pages:
        page_number = page.get("page_number")
        page_text = page.get("text") or ""

        if not isinstance(page_number, int):
            page_number = None

        lines = page_text.split("\n")

        for raw_line in lines:
            line = normalize_line(raw_line)

            if not line:
                if current_lines:
                    current_lines.append("")
                continue

            if is_probable_section_title(line):
                # 遇到新章节标题，先保存上一节
                flush_current_section()

                current_title = canonicalize_section_title(line)
                current_page_start = page_number
                current_page_end = page_number
                current_lines = [line]
            else:
                if current_page_start is None:
                    current_page_start = page_number

                current_page_end = page_number
                current_lines.append(line)

    flush_current_section()

    return sections


def sections_to_dicts(
    sections: list[ParsedSection],
) -> list[dict[str, Any]]:
    """
    将 ParsedSection 列表转换成 dict 列表。
    """
    return [asdict(section) for section in sections]