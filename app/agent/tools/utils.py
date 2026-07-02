"""
utils.py

辅助类 Tool：日志写入、文献列表。

包装对象：
- PaperRepository.list_papers → ListPapersTool
- WriteDevLogTool → 写开发日志
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agent.base import Tool, ToolResult
from app.storage.repositories import PaperRepository


# ============================================================
# 1. ListPapersTool
# ============================================================


class ListPapersParams(BaseModel):
    """文献列表查询参数。"""

    limit: int = Field(default=20, description="返回数量上限")
    offset: int = Field(default=0, description="偏移量")
    status: str | None = Field(default=None, description="按状态筛选")


class ListPapersTool(Tool):
    """
    列出本地文献库中的所有文献。

    包装 PaperRepository.list_papers。
    """

    name = "list_papers"
    description = (
        "列出本地文献库中的文献。支持分页和状态筛选。"
        "返回文献列表（含 id、title、doi、year、status 等）。"
    )
    input_schema = ListPapersParams

    def __init__(self) -> None:
        self._repo = PaperRepository()

    async def run(self, params: ListPapersParams) -> ToolResult:
        try:
            papers = await self._repo.list_papers(
                limit=params.limit,
                offset=params.offset,
                status=params.status,
            )
            return ToolResult(
                success=True,
                data={
                    "count": len(papers),
                    "offset": params.offset,
                    "papers": [
                        {
                            "id": p.get("id"),
                            "title": p.get("title"),
                            "doi": p.get("doi"),
                            "year": p.get("year"),
                            "status": p.get("status"),
                            "domain_score": p.get("domain_score"),
                        }
                        for p in papers
                    ],
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# ============================================================
# 2. WriteDevLogTool
# ============================================================


class WriteDevLogParams(BaseModel):
    """开发日志写入参数。"""

    title: str = Field(..., description="日志标题")
    content: str = Field(..., description="日志正文内容")
    category: str = Field(default="agent", description="日志分类")


class WriteDevLogTool(Tool):
    """
    写入开发日志（追加到 dev_log.md）。

    可在 Agent 任务完成后调用，记录采集统计、错误、新发现等信息。
    """

    name = "write_dev_log"
    description = "写入一条开发日志记录，用于追踪 Agent 任务的执行历史和产出。"
    input_schema = WriteDevLogParams

    async def run(self, params: WriteDevLogParams) -> ToolResult:
        try:
            from pathlib import Path

            # 项目根目录下的 dev_log.md
            log_path = Path(__file__).resolve().parents[3] / "dev_log.md"

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = (
                f"\n## [{params.category}] {params.title}\n"
                f"> {timestamp}\n\n"
                f"{params.content}\n"
            )

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)

            return ToolResult(
                success=True,
                data={
                    "message": f"日志已写入 {log_path}",
                    "category": params.category,
                    "title": params.title,
                    "timestamp": timestamp,
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
