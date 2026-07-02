"""
pdf_parser.py

PDF 正文解析模块。

作用：
1. 使用 PyMuPDF 读取 PDF；
2. 按页提取文本；
3. 清洗基本空白字符；
4. 输出结构化解析结果；
5. 为后续章节识别、chunk 切分、向量化做准备。

当前阶段：
    PDF -> pages + full_text + metadata

后续阶段：
    parsed JSON -> chunks -> embeddings -> FAISS
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class ParsedPdfPage:
    """
    单页 PDF 解析结果。

    字段说明：
        page_number:
            页码，从 1 开始。

        text:
            当前页提取出的文本。

        char_count:
            当前页文本字符数。
    """

    page_number: int
    text: str
    char_count: int


@dataclass
class ParsedPdfDocument:
    """
    整篇 PDF 解析结果。

    字段说明：
        pdf_path:
            PDF 文件路径。

        page_count:
            PDF 页数。

        full_text:
            全文文本。

        pages:
            每页文本列表。

        metadata:
            PDF 文件内置 metadata，例如 title、author 等。
    """

    pdf_path: str
    page_count: int
    full_text: str
    pages: list[ParsedPdfPage]
    metadata: dict[str, Any]


class PdfParser:
    """
    PDF 解析器。

    当前使用 PyMuPDF。
    安装：
        pip install pymupdf

    导入包名：
        import fitz
    """

    def __init__(
        self,
        sort_text: bool = True,
        min_page_text_chars: int = 10,
    ) -> None:
        """
        初始化 PDF 解析器。

        参数：
            sort_text:
                是否按页面上的自然阅读顺序排序文本。
                对论文 PDF 通常建议 True。

            min_page_text_chars:
                如果某页提取字符数低于该值，说明该页可能是图片页、空白页或扫描页。
        """
        self.sort_text = sort_text
        self.min_page_text_chars = min_page_text_chars

    def parse(
        self,
        pdf_path: str | Path,
    ) -> ParsedPdfDocument:
        """
        解析 PDF 文件。

        参数：
            pdf_path:
                PDF 文件路径。

        返回：
            ParsedPdfDocument。
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 文件不存在：{pdf_path}")

        if not pdf_path.is_file():
            raise ValueError(f"路径不是文件：{pdf_path}")

        try:
            import fitz
        except ImportError as exc:
            raise ImportError(
                "缺少 PyMuPDF。请先运行：pip install pymupdf"
            ) from exc

        pages: list[ParsedPdfPage] = []
        full_text_parts: list[str] = []

        with fitz.open(pdf_path) as document:
            page_count = document.page_count

            metadata = dict(document.metadata or {})

            for page_index in range(page_count):
                page = document.load_page(page_index)

                raw_text = page.get_text(
                    "text",
                    sort=self.sort_text,
                )

                cleaned_text = clean_pdf_text(raw_text)

                page_number = page_index + 1

                page_result = ParsedPdfPage(
                    page_number=page_number,
                    text=cleaned_text,
                    char_count=len(cleaned_text),
                )

                pages.append(page_result)

                if cleaned_text:
                    full_text_parts.append(
                        f"\n\n[PAGE {page_number}]\n\n{cleaned_text}"
                    )

        full_text = "\n".join(full_text_parts).strip()

        return ParsedPdfDocument(
            pdf_path=str(pdf_path),
            page_count=len(pages),
            full_text=full_text,
            pages=pages,
            metadata=metadata,
        )

    def to_dict(
        self,
        parsed_document: ParsedPdfDocument,
    ) -> dict[str, Any]:
        """
        将 ParsedPdfDocument 转成普通 dict。

        方便保存为 JSON。
        """
        return {
            "pdf_path": parsed_document.pdf_path,
            "page_count": parsed_document.page_count,
            "full_text": parsed_document.full_text,
            "pages": [
                asdict(page)
                for page in parsed_document.pages
            ],
            "metadata": parsed_document.metadata,
        }


def clean_pdf_text(text: Optional[str]) -> str:
    """
    清洗 PDF 提取出的文本。

    处理内容：
    1. None 转空字符串；
    2. 统一换行；
    3. 去掉连续空格；
    4. 去掉多余空行；
    5. 修复英文断词换行。

    注意：
        这里只做温和清洗，不做激进处理。
        因为后续还需要尽量保留论文原始结构。
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # 修复英文 PDF 常见断词：
    # "structural elu-\ncidation" -> "structural elucidation"
    text = re.sub(r"([A-Za-z])-\n([A-Za-z])", r"\1\2", text)

    # 将行内多个空格压缩
    text = re.sub(r"[ \t]+", " ", text)

    # 去掉每行首尾空白
    lines = [line.strip() for line in text.split("\n")]

    # 删除过多空行，最多保留一个空行
    cleaned_lines: list[str] = []
    previous_empty = False

    for line in lines:
        if not line:
            if not previous_empty:
                cleaned_lines.append("")
            previous_empty = True
        else:
            cleaned_lines.append(line)
            previous_empty = False

    cleaned_text = "\n".join(cleaned_lines)

    # 再次压缩 3 个以上连续换行
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)

    return cleaned_text.strip()


def parsed_document_to_plain_text(
    parsed_document: ParsedPdfDocument,
) -> str:
    """
    将解析结果转成纯文本。

    当前主要用于调试。
    后续正式切 chunk 时建议使用 JSON 中的 pages 和 sections。
    """
    return parsed_document.full_text