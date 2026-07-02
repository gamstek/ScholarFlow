"""
rag.py

检索类 Tool：FAISS 检索、RAG 问答、文献状态查询。

包装对象：
- LocalChunkRetriever.retrieve → RagSearchTool
- LocalRagEngine.ask → RagAskTool
- PaperRepository.list_papers → CheckPaperStatusTool
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agent.base import Tool, ToolResult
from app.rag.rag_engine import LocalRagEngine
from app.rag.retriever import LocalChunkRetriever, evidences_to_dicts
from app.storage.repositories import PaperRepository


# ============================================================
# 1. RagSearchTool
# ============================================================


class RagSearchParams(BaseModel):
    """RAG 检索参数。"""

    query: str = Field(..., description="检索查询词")
    top_k: int = Field(default=5, description="返回前 k 个结果")
    min_score: float | None = Field(default=None, description="最低相似度分数")
    section_filter: list[str] | None = Field(default=None, description="章节过滤")
    year_from: int | None = Field(default=None, description="起始年份")
    year_to: int | None = Field(default=None, description="结束年份")


class RagSearchTool(Tool):
    """
    在本地 FAISS 索引中检索最相关的文献 chunks。

    包装 LocalChunkRetriever.retrieve。
    """

    name = "rag_search"
    description = (
        "在本地知识库中检索与查询最相关的文献 chunks。"
        "输入查询词和检索参数，返回 top-k 个检索证据（含相似度、chunk 原文、论文元数据）。"
    )
    input_schema = RagSearchParams

    def __init__(self) -> None:
        self._retriever = LocalChunkRetriever()

    async def run(self, params: RagSearchParams) -> ToolResult:
        try:
            evidences = await self._retriever.retrieve(
                query=params.query,
                top_k=params.top_k,
                min_score=params.min_score,
                section_filter=params.section_filter,
                year_from=params.year_from,
                year_to=params.year_to,
            )
            return ToolResult(
                success=True,
                data={
                    "count": len(evidences),
                    "sources": evidences_to_dicts(evidences),
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 2. RagAskTool
# ============================================================


class RagAskParams(BaseModel):
    """RAG 问答参数。"""

    question: str = Field(..., description="用户问题")
    top_k: int = Field(default=3, description="检索前 k 个 chunks")
    min_score: float | None = Field(default=None, description="最低相似度分数")
    max_chars_per_evidence: int = Field(default=800, description="每条证据最多字符数")
    language: str = Field(default="zh", description="回答语言 zh/en")
    generate: bool = Field(default=True, description="是否调用 LLM 生成回答")


class RagAskTool(Tool):
    """
    本地 RAG 问答：检索 + LLM 生成。

    包装 LocalRagEngine.ask。
    """

    name = "rag_ask"
    description = (
        "在本地知识库中检索相关文献，并基于检索结果生成回答。"
        "输入问题和检索参数，返回回答、来源和上下文。"
    )
    input_schema = RagAskParams

    def __init__(self) -> None:
        self._engine = LocalRagEngine()

    async def run(self, params: RagAskParams) -> ToolResult:
        try:
            result = await self._engine.ask(
                question=params.question,
                top_k=params.top_k,
                min_score=params.min_score,
                max_chars_per_evidence=params.max_chars_per_evidence,
                language=params.language,
                generate=params.generate,
            )
            return ToolResult(
                success=True,
                data={
                    "question": result.question,
                    "answer": result.answer,
                    "model": result.model,
                    "sources": result.sources,
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 3. CheckPaperStatusTool
# ============================================================


class CheckPaperStatusParams(BaseModel):
    """文献状态查询参数。"""

    limit: int = Field(default=50, description="最多返回多少篇文献")
    status: str | None = Field(default=None, description="按状态筛选（metadata_only/pdf_downloaded/parsed/chunked/indexed）")


class CheckPaperStatusTool(Tool):
    """
    查看本地文献库中文献的处理状态。

    包装 PaperRepository.list_papers。
    """

    name = "check_paper_status"
    description = (
        "查询本地文献库中文献的处理状态。"
        "输入可选的 status 筛选和 limit，返回文献列表（含 id、title、status、pdf_path、text_path）。"
    )
    input_schema = CheckPaperStatusParams

    def __init__(self) -> None:
        self._repo = PaperRepository()

    async def run(self, params: CheckPaperStatusParams) -> ToolResult:
        try:
            papers = await self._repo.list_papers(
                limit=params.limit,
                offset=0,
                status=params.status,
            )
            return ToolResult(
                success=True,
                data={
                    "count": len(papers),
                    "papers": [
                        {
                            "id": p.get("id"),
                            "title": p.get("title"),
                            "year": p.get("year"),
                            "status": p.get("status"),
                            "domain_score": p.get("domain_score"),
                            "local_pdf_path": p.get("local_pdf_path"),
                            "local_text_path": p.get("local_text_path"),
                        }
                        for p in papers
                    ],
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
