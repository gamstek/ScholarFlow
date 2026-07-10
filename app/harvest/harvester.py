"""
harvester.py

文献采集总控模块。

支持的数据源：
    - europe_pmc:       Europe PMC（通用生物医学）
    - nature:           Nature 系列期刊
    - science:          Science 系列期刊
    - cell:             Cell Press 系列期刊
    - arxiv:            arXiv 预印本
    - semantic_scholar: Semantic Scholar（通用学术搜索，Google Scholar 替代）

工作流：
1. 支持同时从多个数据源采集；
2. 跨源去重（DOI → PMID → 标题归一化）；
3. 查询驱动语义评分；
4. 按相关度降序排序；
5. 过滤低分文献，将保留的文献 metadata 写入数据库；
6. 更新 crawl_tasks 任务状态；
7. 返回采集报告。
"""

from __future__ import annotations

import asyncio
import json as _json
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Optional

from app.domain.filters import QueryDrivenScorer
from app.harvest.literature.europe_pmc_client import (
    EuropePmcClient,
    PaperMetadata,
)
from app.harvest.literature.nature_client import NatureClient
from app.harvest.literature.science_client import ScienceClient
from app.harvest.literature.cell_client import CellClient
from app.harvest.literature.arxiv_client import ArxivClient
from app.harvest.literature.semantic_scholar_client import SemanticScholarClient
from app.storage.database import async_session_factory, init_db
from app.storage.repositories import CrawlTaskRepository, PaperRepository

from sqlalchemy import select, func as sa_func
from app.storage.models import Paper


@dataclass
class HarvestReport:
    """
    文献采集报告。
    """

    task_id: int
    query: str
    sources: list[str]
    retrieved_count: int
    deduplicated_count: int
    kept_count: int
    filtered_out_count: int
    saved_count: int
    failed_count: int
    saved_paper_ids: list[int]
    filtered_examples: list[dict[str, Any]]
    errors: list[str]


@dataclass
class SearchHit:
    """单条检索结果（不入库，仅返回给前端预览）。"""

    title: str
    abstract: Optional[str]
    authors: Optional[list[str]]
    year: Optional[int]
    journal: Optional[str]
    doi: Optional[str]
    pmid: Optional[str]
    pmcid: Optional[str]
    source: str
    url: Optional[str]
    pdf_url: Optional[str]
    license: Optional[str]
    is_open_access: int
    citation_count: Optional[int]
    domain_score: float
    in_library: bool
    paper_id: Optional[int]


@dataclass
class SearchReport:
    """检索报告（不入库）。"""

    query: str
    sources: list[str]
    retrieved_count: int
    deduplicated_count: int
    results: list[SearchHit]
    keywords: Optional[list[str]]
    domain: Optional[str]
    errors: list[str]
    sort_by: str = "relevance"
    sort_order: str = "desc"


class LiteratureHarvester:
    """
    通用文献采集器。

    支持 6 个数据源，可同时选择多个数据源采集，
    自动去重并按语义相关度排序。
    """

    def __init__(
        self,
        europe_pmc_client: Optional[EuropePmcClient] = None,
        nature_client: Optional[NatureClient] = None,
        science_client: Optional[ScienceClient] = None,
        cell_client: Optional[CellClient] = None,
        arxiv_client: Optional[ArxivClient] = None,
        semantic_scholar_client: Optional[SemanticScholarClient] = None,
        min_domain_score: float = 0.25,
    ) -> None:
        """
        初始化采集器。

        参数：
            europe_pmc_client: Europe PMC 客户端。
            nature_client: Nature 系列期刊客户端。
            science_client: Science 系列期刊客户端。
            cell_client: Cell Press 系列期刊客户端。
            arxiv_client: arXiv 客户端。
            semantic_scholar_client: Semantic Scholar 客户端。
            min_domain_score: 最低语义相似度阈值，低于该分数的文献不入库。
                查询驱动评分模式下，推荐 0.20~0.30。
        """
        self.europe_pmc_client = europe_pmc_client or EuropePmcClient()
        self.nature_client = nature_client or NatureClient()
        self.science_client = science_client or ScienceClient()
        self.cell_client = cell_client or CellClient()
        self.arxiv_client = arxiv_client or ArxivClient()
        self.semantic_scholar_client = semantic_scholar_client or SemanticScholarClient()
        self.min_domain_score = min_domain_score

        self.task_repo = CrawlTaskRepository()
        self.paper_repo = PaperRepository()

    # ================================================================
    # 公共采集入口
    # ================================================================

    async def crawl(
        self,
        query: str,
        sources: list[str] | None = None,
        source: str | None = None,
        max_results: int = 20,
        enhance_query: bool = True,
        enhance_terms: list[str] | None = None,
    ) -> HarvestReport:
        """
        统一采集入口 — 支持同时从多个数据源采集。

        参数：
            query: 用户原始检索词。
            sources: 数据源列表，如 ["europe_pmc", "arxiv"]。
                为 None 时默认使用 ["europe_pmc"]。
            source: 单个数据源（兼容旧接口），优先级低于 sources。
            max_results: 每个数据源的最大检索数量。
            enhance_query: 是否自动追加方向检索词（仅 Europe PMC 支持）。
            enhance_terms: 增强检索时使用的方向词列表。

        返回：
            HarvestReport 采集报告。
        """
        if sources is None:
            sources = [source] if source else ["europe_pmc"]

        return await self._do_crawl(
            query=query,
            sources=sources,
            max_results=max_results,
            enhance_query=enhance_query,
            enhance_terms=enhance_terms,
        )

    # ================================================================
    # 仅检索不入库
    # ================================================================

    async def search_only(
        self,
        query: str,
        sources: list[str] | None = None,
        max_results: int = 20,
        enhance_query: bool = True,
        enhance_terms: list[str] | None = None,
        keywords: list[str] | None = None,
        domain: str | None = None,
        sort_by: str = "relevance",
        sort_order: str = "desc",
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SearchReport:
        """
        仅检索 + 评分 + 检查在库状态，不写入数据库。

        参数：
            query: 检索词（如果已通过 LLM 提取，则为关键词拼接）。
            sources: 数据源列表。
            max_results: 每源最大检索数。
            enhance_query: 是否增强检索（仅 europe_pmc）。
            enhance_terms: 增强方向词。
            keywords: LLM 提取的关键词（用于返回给前端展示）。
            domain: LLM 提取的领域标签。

        返回：
            SearchReport。
        """
        if sources is None:
            sources = ["europe_pmc"]

        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        await init_db()

        retrieved_count = 0
        errors: list[str] = []
        all_papers: list[PaperMetadata] = []

        # 1. 多源并行采集
        total_expected = len(sources) * max_results

        async def _fetch_source(source: str) -> tuple[str, list[PaperMetadata], Optional[Exception]]:
            """在线程池中执行单个数据源的同步检索。"""
            try:
                papers = await asyncio.to_thread(
                    self._search_one_source,
                    source=source,
                    query=query,
                    max_results=max_results,
                    enhance_query=enhance_query,
                    enhance_terms=enhance_terms,
                )
                return (source, papers, None)
            except Exception as exc:
                return (source, [], exc)

        tasks = [_fetch_source(s) for s in sources]
        fetch_results = await asyncio.gather(*tasks)

        for source, papers, exc in fetch_results:
            if exc is not None:
                errors.append(f"[{source}] 搜索失败：{exc}")
            else:
                all_papers.extend(papers)
                retrieved_count += len(papers)
            if progress_callback:
                progress_callback(retrieved_count, total_expected, source)

        if not all_papers:
            return SearchReport(
                query=query,
                sources=sources,
                retrieved_count=0,
                deduplicated_count=0,
                results=[],
                keywords=keywords,
                domain=domain,
                errors=errors,
            )

        # 2. 跨源去重
        all_papers = self._deduplicate(all_papers)
        deduplicated_count = len(all_papers)

        # 3. 查询驱动批量评分
        scorer = QueryDrivenScorer()
        scorer.prepare(query=query)

        paper_dicts = [
            {"title": p.title, "abstract": p.abstract}
            for p in all_papers
        ]
        filter_results = scorer.score_papers_batch(paper_dicts)

        # 4. 排序：先按 domain_score 排（基础/二级排序），再按用户选择的一级字段排
        scored_papers = list(zip(all_papers, filter_results))
        scored_papers.sort(key=lambda x: x[1].domain_score, reverse=True)
        reverse = (sort_order == "desc")
        if sort_by == "year":
            scored_papers.sort(key=lambda x: (x[0].year is not None, x[0].year or 0), reverse=reverse)
        elif sort_by == "citations":
            scored_papers.sort(key=lambda x: (x[0].citation_count is not None, x[0].citation_count or 0), reverse=reverse)
        # else: relevance — 保持 domain_score 排序

        # 5. 批量查库 — 检查哪些已在库中
        in_library_map = await self._batch_check_in_library(scored_papers)

        # 6. 构造 SearchHit 列表
        results: list[SearchHit] = []

        for paper, fresult in scored_papers:
            doi_key = self._normalize_doi(paper.doi) if paper.doi else None
            title_key = _normalize_title(paper.title)

            paper_id = None
            in_library = False

            if doi_key and doi_key in in_library_map["doi"]:
                paper_id = in_library_map["doi"][doi_key]
                in_library = True
            elif paper.pmid and paper.pmid in in_library_map["pmid"]:
                paper_id = in_library_map["pmid"][paper.pmid]
                in_library = True
            elif title_key and title_key in in_library_map["title"]:
                paper_id = in_library_map["title"][title_key]
                in_library = True

            results.append(SearchHit(
                title=paper.title,
                abstract=paper.abstract,
                authors=paper.authors,
                year=paper.year,
                journal=paper.journal,
                doi=paper.doi,
                pmid=paper.pmid,
                pmcid=paper.pmcid,
                source=paper.source,
                url=paper.url,
                pdf_url=paper.pdf_url,
                license=paper.license,
                is_open_access=paper.is_open_access,
                citation_count=paper.citation_count,
                domain_score=fresult.domain_score,
                in_library=in_library,
                paper_id=paper_id,
            ))

        return SearchReport(
            query=query,
            sources=sources,
            retrieved_count=retrieved_count,
            deduplicated_count=deduplicated_count,
            results=results,
            keywords=keywords,
            domain=domain,
            sort_by=sort_by,
            sort_order=sort_order,
            errors=errors,
        )

    # ================================================================
    # 流式检索（SSE）
    # ================================================================

    async def search_only_stream(
        self,
        query: str,
        sources: list[str] | None = None,
        max_results: int = 20,
        enhance_query: bool = True,
        enhance_terms: list[str] | None = None,
        keywords: list[str] | None = None,
        domain: str | None = None,
        sort_by: str = "relevance",
        sort_order: str = "desc",
    ) -> AsyncGenerator[str, None]:
        """
        流式检索：逐源推送进度事件（SSE），最后推送完整结果。

        用法：
            async for event in harvester.search_only_stream(...):
                yield event  # SSE 格式 "data: {...}\n\n"
        """
        if sources is None:
            sources = ["europe_pmc"]

        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        await init_db()

        total_expected = len(sources) * max_results
        retrieved_count = 0
        errors: list[str] = []
        all_papers: list[PaperMetadata] = []

        # 1. 多源并行采集（逐源推送进度）
        async def _fetch_source(source: str) -> tuple[str, list[PaperMetadata], Optional[Exception]]:
            try:
                papers = await asyncio.to_thread(
                    self._search_one_source,
                    source=source,
                    query=query,
                    max_results=max_results,
                    enhance_query=enhance_query,
                    enhance_terms=enhance_terms,
                )
                return (source, papers, None)
            except Exception as exc:
                return (source, [], exc)

        tasks = [_fetch_source(s) for s in sources]
        for coro in asyncio.as_completed(tasks):
            source, papers, exc = await coro
            if exc is not None:
                errors.append(f"[{source}] 搜索失败：{exc}")
            else:
                all_papers.extend(papers)
                retrieved_count += len(papers)
            yield f"data: {_json.dumps({'type': 'progress', 'current': retrieved_count, 'total': total_expected, 'source': source, 'source_count': len(papers)}, ensure_ascii=False)}\n\n"

        if not all_papers:
            yield f"data: {_json.dumps({'type': 'result', 'query': query, 'sources': sources, 'retrieved_count': 0, 'deduplicated_count': 0, 'results': [], 'keywords': keywords, 'domain': domain, 'sort_by': sort_by, 'sort_order': sort_order, 'errors': errors}, ensure_ascii=False)}\n\n"
            return

        # 2. 跨源去重
        all_papers = self._deduplicate(all_papers)
        deduplicated_count = len(all_papers)

        # 3. 查询驱动批量评分
        scorer = QueryDrivenScorer()
        scorer.prepare(query=query)

        paper_dicts = [
            {"title": p.title, "abstract": p.abstract}
            for p in all_papers
        ]
        filter_results = scorer.score_papers_batch(paper_dicts)

        # 4. 排序
        scored_papers = list(zip(all_papers, filter_results))
        scored_papers.sort(key=lambda x: x[1].domain_score, reverse=True)
        reverse = (sort_order == "desc")
        if sort_by == "year":
            scored_papers.sort(key=lambda x: (x[0].year is not None, x[0].year or 0), reverse=reverse)
        elif sort_by == "citations":
            scored_papers.sort(key=lambda x: (x[0].citation_count is not None, x[0].citation_count or 0), reverse=reverse)

        # 5. 批量查库
        in_library_map = await self._batch_check_in_library(scored_papers)

        # 6. 构造结果
        results: list[SearchHit] = []
        for paper, fresult in scored_papers:
            doi_key = self._normalize_doi(paper.doi) if paper.doi else None
            title_key = _normalize_title(paper.title)

            paper_id = None
            in_library = False

            if doi_key and doi_key in in_library_map["doi"]:
                paper_id = in_library_map["doi"][doi_key]
                in_library = True
            elif paper.pmid and paper.pmid in in_library_map["pmid"]:
                paper_id = in_library_map["pmid"][paper.pmid]
                in_library = True
            elif title_key and title_key in in_library_map["title"]:
                paper_id = in_library_map["title"][title_key]
                in_library = True

            results.append(SearchHit(
                title=paper.title,
                abstract=paper.abstract,
                authors=paper.authors,
                year=paper.year,
                journal=paper.journal,
                doi=paper.doi,
                pmid=paper.pmid,
                pmcid=paper.pmcid,
                source=paper.source,
                url=paper.url,
                pdf_url=paper.pdf_url,
                license=paper.license,
                is_open_access=paper.is_open_access,
                citation_count=paper.citation_count,
                domain_score=fresult.domain_score,
                in_library=in_library,
                paper_id=paper_id,
            ))

        # 7. 推送最终结果
        result_dict = {
            "type": "result",
            "query": query,
            "sources": sources,
            "retrieved_count": retrieved_count,
            "deduplicated_count": deduplicated_count,
            "keywords": keywords,
            "domain": domain,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "results": [
                {
                    "title": h.title,
                    "abstract": h.abstract,
                    "authors": h.authors,
                    "year": h.year,
                    "journal": h.journal,
                    "doi": h.doi,
                    "pmid": h.pmid,
                    "pmcid": h.pmcid,
                    "source": h.source,
                    "url": h.url,
                    "pdf_url": h.pdf_url,
                    "license": h.license,
                    "is_open_access": h.is_open_access,
                    "citation_count": h.citation_count,
                    "domain_score": h.domain_score,
                    "in_library": h.in_library,
                    "paper_id": h.paper_id,
                }
                for h in results
            ],
            "errors": errors,
        }
        yield f"data: {_json.dumps(result_dict, ensure_ascii=False)}\n\n"

    @staticmethod
    def _normalize_doi(doi: Optional[str]) -> Optional[str]:
        """标准化 DOI。"""
        if not doi:
            return None
        value = doi.strip().lower()
        value = value.replace("https://doi.org/", "")
        value = value.replace("http://doi.org/", "")
        value = value.replace("doi:", "")
        return value or None

    async def _batch_check_in_library(
        self,
        scored_papers: list[tuple[PaperMetadata, Any]],
    ) -> dict[str, dict[str, int]]:
        """
        批量检查文献是否已在库中。

        返回三个映射：doi_map, pmid_map, title_map。
        """
        doi_set: set[str] = set()
        pmid_set: set[str] = set()
        title_set: set[str] = set()

        for paper, _ in scored_papers:
            ndoi = self._normalize_doi(paper.doi)
            if ndoi:
                doi_set.add(ndoi)
            if paper.pmid:
                pmid_set.add(paper.pmid.strip())
            ntitle = _normalize_title(paper.title)
            if ntitle:
                title_set.add(ntitle)

        doi_map: dict[str, int] = {}
        pmid_map: dict[str, int] = {}
        title_map: dict[str, int] = {}

        if not (doi_set or pmid_set or title_set):
            return {"doi": doi_map, "pmid": pmid_map, "title": title_map}

        async with async_session_factory() as session:
            if doi_set:
                result = await session.execute(
                    select(Paper.id, Paper.doi).where(Paper.doi.in_(doi_set))
                )
                for row in result.fetchall():
                    doi_map[row._mapping["doi"]] = row._mapping["id"]

            if pmid_set:
                result = await session.execute(
                    select(Paper.id, Paper.pmid).where(Paper.pmid.in_(pmid_set))
                )
                for row in result.fetchall():
                    pmid_map[row._mapping["pmid"]] = row._mapping["id"]

            if title_set:
                result = await session.execute(
                    select(Paper.id, Paper.title).where(
                        sa_func.lower(Paper.title).in_(
                            {t for t in title_set}
                        )
                    )
                )
                for row in result.fetchall():
                    ntitle = _normalize_title(row._mapping["title"])
                    if ntitle and ntitle not in title_map:
                        title_map[ntitle] = row._mapping["id"]

        return {"doi": doi_map, "pmid": pmid_map, "title": title_map}

    # ================================================================
    # 内部实现
    # ================================================================

    def _get_search_fn(self, source: str) -> Callable[..., list[PaperMetadata]]:
        """根据来源名称获取对应的搜索函数。"""
        mapping = {
            "europe_pmc":       self.europe_pmc_client.search,
            "nature":           self.nature_client.search,
            "science":          self.science_client.search,
            "cell":             self.cell_client.search,
            "arxiv":            self.arxiv_client.search,
            "semantic_scholar": self.semantic_scholar_client.search,
        }

        if source not in mapping:
            raise ValueError(
                f"不支持的数据源：{source}。"
                f"可选：{', '.join(mapping.keys())}"
            )

        return mapping[source]

    def _search_one_source(
        self,
        source: str,
        query: str,
        max_results: int,
        enhance_query: bool,
        enhance_terms: list[str] | None,
    ) -> list[PaperMetadata]:
        """从单个数据源搜索文献。"""
        search_fn = self._get_search_fn(source)

        kwargs: dict[str, Any] = {"query": query, "max_results": max_results}
        if source == "europe_pmc":
            kwargs["enhance_query"] = enhance_query
            kwargs["enhance_terms"] = enhance_terms

        return search_fn(**kwargs)

    def _deduplicate(
        self,
        papers: list[PaperMetadata],
    ) -> list[PaperMetadata]:
        """
        跨源去重。

        去重优先级：
            1. DOI（最可靠）
            2. PMID
            3. 标题归一化（小写 + 去除标点和空格）

        当同一文献被多个数据源返回时，保留第一个出现的
        （通常来自先搜索的数据源）。
        """
        seen_doi: set[str] = set()
        seen_pmid: set[str] = set()
        seen_title: set[str] = set()
        unique: list[PaperMetadata] = []

        for paper in papers:
            # DOI 去重
            if paper.doi:
                doi_key = paper.doi.strip().lower()
                if doi_key in seen_doi:
                    continue
                seen_doi.add(doi_key)

            # PMID 去重
            if paper.pmid:
                pmid_key = paper.pmid.strip()
                if pmid_key in seen_pmid:
                    continue
                seen_pmid.add(pmid_key)

            # 标题归一化去重
            title_key = _normalize_title(paper.title)
            if title_key and title_key in seen_title:
                continue
            if title_key:
                seen_title.add(title_key)

            unique.append(paper)

        return unique

    async def _do_crawl(
        self,
        query: str,
        sources: list[str],
        max_results: int,
        enhance_query: bool,
        enhance_terms: list[str] | None,
    ) -> HarvestReport:
        """通用采集流程 — 多源采集 → 去重 → 评分 → 排序 → 过滤 → 入库。"""
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        await init_db()

        task_id = await self.task_repo.create_task(
            query=query,
            task_type="literature",
            sources=sources,
            max_results=max_results,
        )

        await self.task_repo.update_status(task_id=task_id, status="running")

        retrieved_count = 0
        deduplicated_count = 0
        kept_count = 0
        filtered_out_count = 0
        saved_count = 0
        failed_count = 0
        saved_paper_ids: list[int] = []
        filtered_examples: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            # ---- 1. 多源采集 ----
            all_papers: list[PaperMetadata] = []

            for source in sources:
                try:
                    papers = self._search_one_source(
                        source=source,
                        query=query,
                        max_results=max_results,
                        enhance_query=enhance_query,
                        enhance_terms=enhance_terms,
                    )
                    all_papers.extend(papers)
                    retrieved_count += len(papers)
                except Exception as exc:
                    errors.append(f"[{source}] 搜索失败：{exc}")

            if not all_papers:
                await self.task_repo.update_status(
                    task_id=task_id,
                    status="done",
                    success_count=0,
                    failed_count=0,
                    finish=True,
                )
                return HarvestReport(
                    task_id=task_id,
                    query=query,
                    sources=sources,
                    retrieved_count=0,
                    deduplicated_count=0,
                    kept_count=0,
                    filtered_out_count=0,
                    saved_count=0,
                    failed_count=len(errors),
                    saved_paper_ids=[],
                    filtered_examples=[],
                    errors=errors,
                )

            # ---- 2. 跨源去重 ----
            all_papers = self._deduplicate(all_papers)
            deduplicated_count = len(all_papers)

            # ---- 3. 查询驱动批量评分 ----
            scorer = QueryDrivenScorer()
            scorer.prepare(query=query)

            paper_dicts = [
                {"title": p.title, "abstract": p.abstract}
                for p in all_papers
            ]
            filter_results = scorer.score_papers_batch(paper_dicts)

            # ---- 4. 按相关度降序排序 ----
            scored_papers = list(zip(all_papers, filter_results))
            scored_papers.sort(key=lambda x: x[1].domain_score, reverse=True)

            # ---- 5. 过滤 + 入库 ----
            for paper, fresult in scored_papers:
                try:
                    keep = fresult.keep
                    domain_score = fresult.domain_score

                    if not keep or domain_score < self.min_domain_score:
                        filtered_out_count += 1

                        if len(filtered_examples) < 5:
                            filtered_examples.append(
                                {
                                    "title": paper.title,
                                    "domain_score": domain_score,
                                    "reason": fresult.reason,
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
            sources=sources,
            retrieved_count=retrieved_count,
            deduplicated_count=deduplicated_count,
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
        """将标准化文献 metadata 写入数据库。"""
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
            citation_count=paper.citation_count,
            domain_score=domain_score,
            status="metadata_only",
            crawl_task_id=task_id,
        )

        return paper_id


def _normalize_title(title: str) -> str:
    """
    标题归一化 — 用于去重比较。

    转小写，去除标点符号和多余空格。
    """
    if not title:
        return ""

    import re

    # 转小写
    t = title.lower().strip()
    # 去除所有非字母数字字符
    t = re.sub(r"[^a-z0-9]", "", t)

    return t


def report_to_dict(report: HarvestReport) -> dict[str, Any]:
    """将 HarvestReport 转换为 dict。"""
    return {
        "task_id": report.task_id,
        "query": report.query,
        "sources": report.sources,
        "retrieved_count": report.retrieved_count,
        "deduplicated_count": report.deduplicated_count,
        "kept_count": report.kept_count,
        "filtered_out_count": report.filtered_out_count,
        "saved_count": report.saved_count,
        "failed_count": report.failed_count,
        "saved_paper_ids": report.saved_paper_ids,
        "filtered_examples": report.filtered_examples,
        "errors": report.errors,
    }


def search_report_to_dict(report: SearchReport) -> dict[str, Any]:
    """将 SearchReport 转换为 dict。"""
    return {
        "query": report.query,
        "sources": report.sources,
        "retrieved_count": report.retrieved_count,
        "deduplicated_count": report.deduplicated_count,
        "keywords": report.keywords,
        "domain": report.domain,
        "results": [
            {
                "title": h.title,
                "abstract": h.abstract,
                "authors": h.authors,
                "year": h.year,
                "journal": h.journal,
                "doi": h.doi,
                "pmid": h.pmid,
                "pmcid": h.pmcid,
                "source": h.source,
                "url": h.url,
                "pdf_url": h.pdf_url,
                "license": h.license,
                "is_open_access": h.is_open_access,
                "citation_count": h.citation_count,
                "domain_score": h.domain_score,
                "in_library": h.in_library,
                "paper_id": h.paper_id,
            }
            for h in report.results
        ],
        "errors": report.errors,
        "sort_by": report.sort_by,
        "sort_order": report.sort_order,
    }
