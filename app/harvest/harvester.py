"""
harvester.py

文献采集总控模块。

当前阶段实现：
1. 调用 Europe PMC 搜索文献；
2. 使用领域过滤器进行筛选；
3. 将保留的文献 metadata 写入数据库；
4. 更新 crawl_tasks 任务状态；
5. 返回采集报告。

这个模块是后续 LiteratureAgent 的雏形。
当前先不要做复杂 Agent，先做稳定工作流。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.domain.filters import classify_paper
from app.harvest.literature.europe_pmc_client import (
    EuropePmcClient,
    PaperMetadata,
)
from app.harvest.literature.nature_client import NatureClient
from app.harvest.literature.science_client import ScienceClient
from app.storage.database import init_db
from app.storage.repositories import CrawlTaskRepository, PaperRepository


@dataclass
class HarvestReport:
    """
    文献采集报告。

    用于向脚本或 API 返回本次采集结果。
    """

    task_id: int
    query: str
    retrieved_count: int
    kept_count: int
    filtered_out_count: int
    saved_count: int
    failed_count: int
    saved_paper_ids: list[int]
    filtered_examples: list[dict[str, Any]]
    errors: list[str]


class LiteratureHarvester:
    """
    通用文献采集器。

    当前支持：
        Europe PMC -> Domain Filter -> 数据库

    后续可以扩展：
        Crossref 补充 DOI / 期刊 / license；
        PDF 下载；
        PDF 正文解析；
        chunk 入库；
        FAISS 索引。
    """

    def __init__(
        self,
        europe_pmc_client: Optional[EuropePmcClient] = None,
        nature_client: Optional[NatureClient] = None,
        science_client: Optional[ScienceClient] = None,
        min_domain_score: float = 0.40,
    ) -> None:
        """
        初始化采集器。

        参数：
            europe_pmc_client:
                Europe PMC 客户端，可选。

            nature_client:
                Nature 系列期刊客户端，可选。

            science_client:
                Science 系列期刊客户端，可选。

            min_domain_score:
                最低领域相关性评分。
                低于该分数的文献不入库。
        """
        self.europe_pmc_client = europe_pmc_client or EuropePmcClient()
        self.nature_client = nature_client or NatureClient()
        self.science_client = science_client or ScienceClient()
        self.min_domain_score = min_domain_score

        self.task_repo = CrawlTaskRepository()
        self.paper_repo = PaperRepository()

    async def crawl_from_europe_pmc(
        self,
        query: str,
        max_results: int = 20,
        enhance_query: bool = True,
        enhance_terms: list[str] | None = None,
    ) -> HarvestReport:
        """
        从 Europe PMC 采集文献并入库。

        参数：
            query:
                用户原始检索词。

            max_results:
                最大检索数量。

            enhance_query:
                是否自动追加方向检索词。

            enhance_terms:
                增强检索时使用的方向词列表，为 None 时不增强。

        返回：
            HarvestReport 采集报告。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        # 确保数据库已经初始化
        await init_db()

        task_id = await self.task_repo.create_task(
            query=query,
            task_type="literature",
            sources=["europe_pmc"],
            max_results=max_results,
        )

        await self.task_repo.update_status(
            task_id=task_id,
            status="running",
        )

        retrieved_count = 0
        kept_count = 0
        filtered_out_count = 0
        saved_count = 0
        failed_count = 0
        saved_paper_ids: list[int] = []
        filtered_examples: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            papers = self.europe_pmc_client.search(
                query=query,
                max_results=max_results,
                enhance_query=enhance_query,
                enhance_terms=enhance_terms,
            )

            retrieved_count = len(papers)

            for paper in papers:
                try:
                    filter_result = classify_paper(
                        title=paper.title,
                        abstract=paper.abstract,
                        journal=paper.journal,
                    )

                    keep = bool(filter_result["keep"])
                    domain_score = float(filter_result["domain_score"])

                    if not keep or domain_score < self.min_domain_score:
                        filtered_out_count += 1

                        if len(filtered_examples) < 5:
                            filtered_examples.append(
                                {
                                    "title": paper.title,
                                    "domain_score": domain_score,
                                    "reason": filter_result["reason"],
                                }
                            )

                        continue

                    kept_count += 1

                    paper_id = await self._save_paper(
                        paper=paper,
                        domain_score=domain_score,
                        task_id=task_id,
                    )

                    saved_paper_ids.append(paper_id)
                    saved_count += 1

                except Exception as exc:
                    failed_count += 1
                    errors.append(
                        f"处理文献失败：{paper.title}；错误：{exc}"
                    )

            await self.task_repo.update_status(
                task_id=task_id,
                status="done",
                success_count=saved_count,
                failed_count=failed_count,
                finish=True,
            )

        except Exception as exc:
            failed_count += 1
            errors.append(str(exc))

            await self.task_repo.update_status(
                task_id=task_id,
                status="failed",
                success_count=saved_count,
                failed_count=failed_count,
                error_message=str(exc),
                finish=True,
            )

        return HarvestReport(
            task_id=task_id,
            query=query,
            retrieved_count=retrieved_count,
            kept_count=kept_count,
            filtered_out_count=filtered_out_count,
            saved_count=saved_count,
            failed_count=failed_count,
            saved_paper_ids=saved_paper_ids,
            filtered_examples=filtered_examples,
            errors=errors,
        )

    async def crawl_from_nature(
        self,
        query: str,
        max_results: int = 20,
    ) -> HarvestReport:
        """
        从 Nature 系列期刊采集文献并入库。

        参数：
            query: 用户原始检索词。
            max_results: 最大检索数量。

        返回：
            HarvestReport 采集报告。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        await init_db()

        task_id = await self.task_repo.create_task(
            query=query,
            task_type="literature",
            sources=["nature"],
            max_results=max_results,
        )

        await self.task_repo.update_status(
            task_id=task_id,
            status="running",
        )

        retrieved_count = 0
        kept_count = 0
        filtered_out_count = 0
        saved_count = 0
        failed_count = 0
        saved_paper_ids: list[int] = []
        filtered_examples: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            papers = self.nature_client.search(
                query=query,
                max_results=max_results,
            )

            retrieved_count = len(papers)

            for paper in papers:
                try:
                    filter_result = classify_paper(
                        title=paper.title,
                        abstract=paper.abstract,
                        journal=paper.journal,
                    )

                    keep = bool(filter_result["keep"])
                    domain_score = float(filter_result["domain_score"])

                    if not keep or domain_score < self.min_domain_score:
                        filtered_out_count += 1

                        if len(filtered_examples) < 5:
                            filtered_examples.append(
                                {
                                    "title": paper.title,
                                    "domain_score": domain_score,
                                    "reason": filter_result["reason"],
                                }
                            )

                        continue

                    kept_count += 1

                    paper_id = await self._save_paper(
                        paper=paper,
                        domain_score=domain_score,
                        task_id=task_id,
                    )

                    saved_paper_ids.append(paper_id)
                    saved_count += 1

                except Exception as exc:
                    failed_count += 1
                    errors.append(
                        f"处理文献失败：{paper.title}；错误：{exc}"
                    )

            await self.task_repo.update_status(
                task_id=task_id,
                status="done",
                success_count=saved_count,
                failed_count=failed_count,
                finish=True,
            )

        except Exception as exc:
            failed_count += 1
            errors.append(str(exc))

            await self.task_repo.update_status(
                task_id=task_id,
                status="failed",
                success_count=saved_count,
                failed_count=failed_count,
                error_message=str(exc),
                finish=True,
            )

        return HarvestReport(
            task_id=task_id,
            query=query,
            retrieved_count=retrieved_count,
            kept_count=kept_count,
            filtered_out_count=filtered_out_count,
            saved_count=saved_count,
            failed_count=failed_count,
            saved_paper_ids=saved_paper_ids,
            filtered_examples=filtered_examples,
            errors=errors,
        )

    async def crawl_from_science(
        self,
        query: str,
        max_results: int = 20,
    ) -> HarvestReport:
        """
        从 Science 系列期刊采集文献并入库。

        参数：
            query: 用户原始检索词。
            max_results: 最大检索数量。

        返回：
            HarvestReport 采集报告。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        await init_db()

        task_id = await self.task_repo.create_task(
            query=query,
            task_type="literature",
            sources=["science"],
            max_results=max_results,
        )

        await self.task_repo.update_status(
            task_id=task_id,
            status="running",
        )

        retrieved_count = 0
        kept_count = 0
        filtered_out_count = 0
        saved_count = 0
        failed_count = 0
        saved_paper_ids: list[int] = []
        filtered_examples: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            papers = self.science_client.search(
                query=query,
                max_results=max_results,
            )

            retrieved_count = len(papers)

            for paper in papers:
                try:
                    filter_result = classify_paper(
                        title=paper.title,
                        abstract=paper.abstract,
                        journal=paper.journal,
                    )

                    keep = bool(filter_result["keep"])
                    domain_score = float(filter_result["domain_score"])

                    if not keep or domain_score < self.min_domain_score:
                        filtered_out_count += 1

                        if len(filtered_examples) < 5:
                            filtered_examples.append(
                                {
                                    "title": paper.title,
                                    "domain_score": domain_score,
                                    "reason": filter_result["reason"],
                                }
                            )

                        continue

                    kept_count += 1

                    paper_id = await self._save_paper(
                        paper=paper,
                        domain_score=domain_score,
                        task_id=task_id,
                    )

                    saved_paper_ids.append(paper_id)
                    saved_count += 1

                except Exception as exc:
                    failed_count += 1
                    errors.append(
                        f"处理文献失败：{paper.title}；错误：{exc}"
                    )

            await self.task_repo.update_status(
                task_id=task_id,
                status="done",
                success_count=saved_count,
                failed_count=failed_count,
                finish=True,
            )

        except Exception as exc:
            failed_count += 1
            errors.append(str(exc))

            await self.task_repo.update_status(
                task_id=task_id,
                status="failed",
                success_count=saved_count,
                failed_count=failed_count,
                error_message=str(exc),
                finish=True,
            )

        return HarvestReport(
            task_id=task_id,
            query=query,
            retrieved_count=retrieved_count,
            kept_count=kept_count,
            filtered_out_count=filtered_out_count,
            saved_count=saved_count,
            failed_count=failed_count,
            saved_paper_ids=saved_paper_ids,
            filtered_examples=filtered_examples,
            errors=errors,
        )

    async def _save_paper(
        self,
        paper: PaperMetadata,
        domain_score: float,
        task_id: int,
    ) -> int:
        """
        将标准化文献 metadata 写入数据库。
        """
        paper_id = await self.paper_repo.upsert_paper(
            title=paper.title,
            abstract=paper.abstract,
            authors=paper.authors,
            year=paper.year,
            journal=paper.journal,
            doi=paper.doi,
            pmid=paper.pmid,
            pmcid=paper.pmcid,
            crossref_id=None,
            source=paper.source,
            url=paper.url,
            pdf_url=paper.pdf_url,
            license=paper.license,
            is_open_access=paper.is_open_access,
            domain_score=domain_score,
            status="metadata_only",
            crawl_task_id=task_id,
        )

        return paper_id


def report_to_dict(report: HarvestReport) -> dict[str, Any]:
    """
    将 HarvestReport 转换为 dict，方便打印或 FastAPI 返回。
    """
    return {
        "task_id": report.task_id,
        "query": report.query,
        "retrieved_count": report.retrieved_count,
        "kept_count": report.kept_count,
        "filtered_out_count": report.filtered_out_count,
        "saved_count": report.saved_count,
        "failed_count": report.failed_count,
        "saved_paper_ids": report.saved_paper_ids,
        "filtered_examples": report.filtered_examples,
        "errors": report.errors,
    }