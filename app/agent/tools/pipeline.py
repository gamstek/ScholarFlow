"""
pipeline.py

处理类 Tool：PDF 下载、解析、chunk 构建、FAISS 索引。

包装对象：
- OpenAccessPdfResolver.download_batch → DownloadOpenAccessPdfTool
- PdfParser + section_parser → ParsePdfTool
- SectionBasedChunker → BuildChunksTool
- build_faiss_index_service → BuildFaissIndexTool
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from app.agent.base import Tool, ToolResult
from app.document.chunker import SectionBasedChunker
from app.document.pdf_parser import PdfParser
from app.document.section_parser import parse_sections_from_pages, sections_to_dicts
from app.harvest.literature.pdf_resolver import OpenAccessPdfResolver
from app.services.pipeline_service import build_faiss_index_service


# ============================================================
# 1. DownloadOpenAccessPdfTool
# ============================================================


class DownloadPdfParams(BaseModel):
    """PDF 下载参数。"""

    limit: int = Field(default=10, description="最多下载多少篇")
    overwrite: bool = Field(default=False, description="是否覆盖已有 PDF")


class DownloadOpenAccessPdfTool(Tool):
    """
    批量下载开放获取 PDF。

    包装 OpenAccessPdfResolver.download_batch。
    """

    name = "download_open_access_pdf"
    description = (
        "从数据库中筛选开放获取文献并批量下载 PDF。"
        "输入 limit 和 overwrite 标志，返回每篇文献的下载结果。"
    )
    input_schema = DownloadPdfParams

    def __init__(self, timeout: int = 60, max_retries: int = 2) -> None:
        self._resolver = OpenAccessPdfResolver(
            timeout=timeout,
            max_retries=max_retries,
        )

    async def run(self, params: DownloadPdfParams) -> ToolResult:
        try:
            results = await self._resolver.download_batch(
                limit=params.limit,
                overwrite=params.overwrite,
            )
            return ToolResult(
                success=True,
                data={
                    "total": len(results),
                    "success_count": sum(1 for r in results if r.status == "success"),
                    "skipped_count": sum(1 for r in results if r.status == "skipped"),
                    "failed_count": sum(1 for r in results if r.status == "failed"),
                    "results": [
                        {
                            "paper_id": r.paper_id,
                            "status": r.status,
                            "message": r.message,
                            "local_pdf_path": r.local_pdf_path,
                        }
                        for r in results
                    ],
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 2. ParsePdfTool
# ============================================================


class ParsePdfParams(BaseModel):
    """PDF 解析参数。"""

    pdf_path: str = Field(..., description="PDF 文件的绝对或相对路径")


class ParsePdfTool(Tool):
    """
    解析单篇 PDF，提取结构化文本。

    包装 PdfParser + section_parser。
    注意：PdfParser.parse 是同步方法，通过 asyncio.to_thread 执行。
    """

    name = "parse_pdf"
    description = (
        "解析 PDF 文件，提取章节结构和全文文本。"
        "输入 PDF 路径，返回 page_count、section_count、full_text 等结构化信息。"
    )
    input_schema = ParsePdfParams

    def __init__(self) -> None:
        self._parser = PdfParser(sort_text=True)

    async def run(self, params: ParsePdfParams) -> ToolResult:
        try:
            from pathlib import Path

            from app.storage.file_store import resolve_project_path

            pdf_path = resolve_project_path(params.pdf_path)

            if not pdf_path.exists():
                return ToolResult(
                    success=False,
                    error=f"PDF 文件不存在：{pdf_path}",
                )

            # 同步解析在线程池中执行
            parsed = await asyncio.to_thread(self._parser.parse, pdf_path)
            parsed_dict = await asyncio.to_thread(self._parser.to_dict, parsed)

            sections = parse_sections_from_pages(pages=parsed_dict["pages"])
            section_dicts = sections_to_dicts(sections)

            return ToolResult(
                success=True,
                data={
                    "page_count": parsed_dict["page_count"],
                    "non_empty_pages": sum(
                        1 for p in parsed_dict["pages"] if p.get("text")
                    ),
                    "section_count": len(section_dicts),
                    "total_chars": len(parsed_dict.get("full_text", "")),
                    "sections": [
                        {"title": s.get("title"), "page_start": s.get("page_start"), "page_end": s.get("page_end")}
                        for s in section_dicts
                    ],
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 3. BuildChunksTool
# ============================================================


class BuildChunksParams(BaseModel):
    """Chunk 构建参数。"""

    text_json_path: str = Field(..., description="已解析文献的 JSON 文件路径")
    max_chars: int = Field(default=2500, description="每个 chunk 最大字符数")
    overlap_chars: int = Field(default=300, description="相邻 chunk 重叠字符数")


class BuildChunksTool(Tool):
    """
    将已解析的文献 JSON 切分为 chunks。

    包装 SectionBasedChunker.chunk_parsed_document。
    注意：chunk_parsed_document 是同步方法，通过 asyncio.to_thread 执行。
    """

    name = "build_chunks"
    description = (
        "将已解析的文献 JSON 切分为多个 chunk。"
        "输入 JSON 路径和切分参数，返回 chunk 数量和各节分布。"
    )
    input_schema = BuildChunksParams

    def __init__(
        self,
        min_chars: int = 300,
        skip_reference_sections: bool = True,
    ) -> None:
        self._chunker = SectionBasedChunker(
            min_chars=min_chars,
            skip_reference_sections=skip_reference_sections,
        )
        self._max_chars = 2500
        self._overlap_chars = 300

    async def run(self, params: BuildChunksParams) -> ToolResult:
        try:
            from pathlib import Path

            from app.storage.file_store import load_json, resolve_project_path

            text_path = resolve_project_path(params.text_json_path)

            if not text_path.exists():
                return ToolResult(
                    success=False,
                    error=f"解析 JSON 文件不存在：{text_path}",
                )

            parsed_json = load_json(text_path)

            # 临时设置切分参数
            self._chunker.max_chars = params.max_chars
            self._chunker.overlap_chars = params.overlap_chars

            chunks = await asyncio.to_thread(
                self._chunker.chunk_parsed_document,
                parsed_json,
            )

            # 按章节统计
            section_summary: dict[str, int] = {}
            for chunk in chunks:
                section = chunk.section_title or "Unknown"
                section_summary[section] = section_summary.get(section, 0) + 1

            return ToolResult(
                success=True,
                data={
                    "chunk_count": len(chunks),
                    "section_summary": section_summary,
                    "preview": [
                        {"index": c.chunk_index, "section": c.section_title, "text_preview": (c.text or "")[:200]}
                        for c in chunks[:5]
                    ],
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 4. BuildFaissIndexTool
# ============================================================


class BuildFaissIndexParams(BaseModel):
    """FAISS 索引构建参数。"""

    limit: int = Field(default=100, description="最多处理多少个 pending chunks")
    batch_size: int = Field(default=4, description="embedding 批大小")
    rebuild: bool = Field(default=False, description="是否重建整个索引")


class BuildFaissIndexTool(Tool):
    """
    将 pending chunks 向量化并写入 FAISS 索引。

    包装 app.services.pipeline_service.build_faiss_index_service。
    """

    name = "build_faiss_index"
    description = (
        "将数据库中 pending 状态的 chunks 向量化并写入 FAISS 索引。"
        "输入处理数量限制和批大小，返回构建报告。"
    )
    input_schema = BuildFaissIndexParams

    async def run(self, params: BuildFaissIndexParams) -> ToolResult:
        try:
            result = await build_faiss_index_service(
                limit=params.limit,
                batch_size=params.batch_size,
                rebuild=params.rebuild,
            )
            return ToolResult(success=True, data=result)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
