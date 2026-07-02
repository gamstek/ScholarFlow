"""
literature.py

采集类 Tool：文献检索、元数据查询、领域过滤。

包装对象：
- EuropePmcClient.search → SearchLiteratureTool
- PaperRepository.get_paper → FetchPaperMetadataTool
- classify_paper → FilterByDomainTool
- CrossrefClient.search → CrossrefSearchTool（骨架预留）
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from app.agent.base import Tool, ToolResult
from app.domain.filters import classify_paper
from app.harvest.harvester import LiteratureHarvester
from app.harvest.literature.crossref_client import CrossrefClient
from app.storage.repositories import PaperRepository


# ============================================================
# 1. SearchLiteratureTool
# ============================================================


class SearchLiteratureParams(BaseModel):
    """文献检索参数。"""

    query: str = Field(..., description="检索查询词，如 'human milk oligosaccharides LC-MS/MS'")
    max_results: int = Field(default=20, description="最大返回结果数")
    enhance_query: bool = Field(default=True, description="是否自动增强查询词")


class SearchLiteratureTool(Tool):
    """
    从 Europe PMC 采集文献 metadata，经领域过滤后写入数据库。

    包装 LiteratureHarvester.crawl_from_europe_pmc。
    """

    name = "search_literature"
    description = (
        "从 Europe PMC 检索文献，经领域过滤器筛选后入库。"
        "输入搜索 query 和最大结果数，返回采集报告（入库数量、过滤数量等）。"
    )
    input_schema = SearchLiteratureParams

    def __init__(self, min_domain_score: float = 0.4) -> None:
        self._min_domain_score = min_domain_score

    async def run(self, params: SearchLiteratureParams) -> ToolResult:
        try:
            harvester = LiteratureHarvester(
                min_domain_score=self._min_domain_score,
            )
            report = await harvester.crawl_from_europe_pmc(
                query=params.query,
                max_results=params.max_results,
                enhance_query=params.enhance_query,
            )
            return ToolResult(
                success=True,
                data={
                    "task_id": report.task_id,
                    "retrieved_count": report.retrieved_count,
                    "kept_count": report.kept_count,
                    "filtered_out_count": report.filtered_out_count,
                    "saved_count": report.saved_count,
                    "saved_paper_ids": report.saved_paper_ids,
                    "errors": report.errors,
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 2. FetchPaperMetadataTool
# ============================================================


class FetchPaperMetadataParams(BaseModel):
    """文献元数据查询参数。"""

    paper_id: int = Field(..., description="文献 ID")


class FetchPaperMetadataTool(Tool):
    """
    根据 paper_id 从数据库查询文献元数据。

    包装 PaperRepository.get_paper。
    """

    name = "fetch_paper_metadata"
    description = "根据文献 ID 查询数据库中已入库文献的完整元数据。"
    input_schema = FetchPaperMetadataParams

    def __init__(self) -> None:
        self._repo = PaperRepository()

    async def run(self, params: FetchPaperMetadataParams) -> ToolResult:
        try:
            paper = await self._repo.get_paper(params.paper_id)
            if paper is None:
                return ToolResult(
                    success=False,
                    error=f"文献 ID={params.paper_id} 不存在。",
                )
            return ToolResult(success=True, data=paper)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 3. FilterByDomainTool
# ============================================================


class FilterByDomainParams(BaseModel):
    """领域过滤参数。"""

    title: str = Field(..., description="论文标题")
    abstract: str | None = Field(default=None, description="论文摘要")
    journal: str | None = Field(default=None, description="期刊名称")
    keywords: list[str] | None = Field(default=None, description="关键词列表")


class FilterByDomainTool(Tool):
    """
    对单篇文献进行领域相关性评分。

    包装 app.domain.filters.classify_paper。
    注意：classify_paper 是同步函数，通过 asyncio.to_thread 执行。
    """

    name = "filter_by_domain"
    description = (
        "对文献标题和摘要进行领域相关性评分。"
        "返回 keep（是否保留）、domain_score（0-1）、reason 和匹配到的关键词。"
    )
    input_schema = FilterByDomainParams

    async def run(self, params: FilterByDomainParams) -> ToolResult:
        try:
            result = await asyncio.to_thread(
                classify_paper,
                title=params.title,
                abstract=params.abstract,
                journal=params.journal,
                keywords=params.keywords,
            )
            return ToolResult(success=True, data=result)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 4. CrossrefSearchTool（骨架）
# ============================================================


class CrossrefSearchParams(BaseModel):
    """Crossref 检索参数。"""

    query: str = Field(..., description="检索查询词")
    rows: int = Field(default=10, description="最大返回行数")


class CrossrefSearchTool(Tool):
    """
    从 Crossref API 检索文献。

    包装 CrossrefClient.search。
    注意：CrossrefClient 当前为骨架实现，此 Tool 待后续填充。
    """

    name = "crossref_search"
    description = "从 Crossref API 检索文献元数据（当前为骨架，待后续完善）。"
    input_schema = CrossrefSearchParams

    def __init__(self) -> None:
        self._client = CrossrefClient()

    async def run(self, params: CrossrefSearchParams) -> ToolResult:
        try:
            results = await asyncio.to_thread(
                self._client.search,
                query=params.query,
                rows=params.rows,
            )
            return ToolResult(success=True, data={"results": results, "count": len(results)})
        except NotImplementedError:
            return ToolResult(
                success=False,
                error="CrossrefClient 尚未完整实现，此 Tool 暂不可用。",
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
