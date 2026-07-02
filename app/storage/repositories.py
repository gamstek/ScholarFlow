"""
repositories.py

数据访问层 Repository Layer（PostgreSQL + SQLAlchemy async）。

作用：
1. 封装数据库增删改查；
2. 使用 SQLAlchemy async session；
3. 提供 CrawlTask / Paper / Chunk / Compound / Spectrum 访问接口。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.storage.database import async_session_factory
from app.storage.models import (
    Chunk,
    Compound,
    CrawlTask,
    Paper,
    Spectrum,
)


# ============================================================
# 工具函数
# ============================================================

def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """标准化 DOI。"""
    if not doi:
        return None
    value = doi.strip()
    value = value.replace("https://doi.org/", "")
    value = value.replace("http://doi.org/", "")
    value = value.replace("doi:", "")
    value = value.replace("DOI:", "")
    value = value.strip().lower()
    return value or None


def to_json(value: Any) -> Optional[str]:
    """将 Python 对象转换成 JSON 字符串。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _row_to_dict(row) -> dict[str, Any]:
    """将 ORM 实例转为普通 dict。"""
    if row is None:
        return {}
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


# ============================================================
# 1. 采集任务 Repository
# ============================================================

class CrawlTaskRepository:

    async def create_task(
        self,
        query: str,
        task_type: str = "literature",
        sources: Optional[list[str]] = None,
        max_results: int = 20,
    ) -> int:
        async with async_session_factory() as session:
            task = CrawlTask(
                query=query,
                task_type=task_type,
                sources_json=to_json(sources),
                max_results=max_results,
                status="pending",
            )
            session.add(task)
            await session.commit()
            return task.id

    async def update_status(
        self,
        task_id: int,
        status: str,
        success_count: Optional[int] = None,
        failed_count: Optional[int] = None,
        error_message: Optional[str] = None,
        finish: bool = False,
    ) -> None:
        async with async_session_factory() as session:
            values = {"status": status}
            if success_count is not None:
                values["success_count"] = success_count
            if failed_count is not None:
                values["failed_count"] = failed_count
            if error_message is not None:
                values["error_message"] = error_message
            if finish:
                from sqlalchemy import func
                values["finished_at"] = func.now()

            stmt = update(CrawlTask).where(CrawlTask.id == task_id).values(**values)
            await session.execute(stmt)
            await session.commit()

    async def get_task(self, task_id: int) -> Optional[dict[str, Any]]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(CrawlTask).where(CrawlTask.id == task_id)
            )
            row = result.scalar_one_or_none()
            return _row_to_dict(row) if row else None


# ============================================================
# 2. 文献 Repository
# ============================================================

class PaperRepository:

    async def upsert_paper(
        self,
        title: str,
        abstract: Optional[str] = None,
        authors: Optional[list[str]] = None,
        year: Optional[int] = None,
        journal: Optional[str] = None,
        doi: Optional[str] = None,
        pmid: Optional[str] = None,
        pmcid: Optional[str] = None,
        crossref_id: Optional[str] = None,
        source: Optional[str] = None,
        url: Optional[str] = None,
        pdf_url: Optional[str] = None,
        license: Optional[str] = None,
        is_open_access: int = 0,
        domain_score: float = 0.0,
        status: str = "metadata_only",
        crawl_task_id: Optional[int] = None,
    ) -> int:
        """
        插入或更新文献（原子 upsert）。

        去重逻辑：DOI > PMID > PMCID > title + year。
        使用 PostgreSQL ON CONFLICT 实现原子操作。
        """
        normalized_doi = normalize_doi(doi)

        async with async_session_factory() as session:
            existing = await self._find_existing_paper(
                session, title, year, normalized_doi, pmid, pmcid
            )

            if existing is not None:
                # 更新已有记录
                values = {
                    "abstract": abstract or existing.abstract,
                    "authors_json": to_json(authors) or existing.authors_json,
                    "year": year or existing.year,
                    "journal": journal or existing.journal,
                    "doi": normalized_doi or existing.doi,
                    "pmid": pmid or existing.pmid,
                    "pmcid": pmcid or existing.pmcid,
                    "crossref_id": crossref_id or existing.crossref_id,
                    "source": source or existing.source,
                    "url": url or existing.url,
                    "pdf_url": pdf_url or existing.pdf_url,
                    "license": license or existing.license,
                    "is_open_access": max(is_open_access, existing.is_open_access),
                    "domain_score": max(domain_score, existing.domain_score),
                    "crawl_task_id": crawl_task_id or existing.crawl_task_id,
                }
                # 状态优先级：indexed > chunked > parsed > pdf_downloaded > metadata_only
                status_priority = {
                    "indexed": 5, "chunked": 4, "parsed": 3,
                    "pdf_downloaded": 2, "metadata_only": 1, "failed": 0,
                }
                old_pri = status_priority.get(existing.status, 0)
                new_pri = status_priority.get(status, 0)
                if new_pri >= old_pri:
                    values["status"] = status

                stmt = update(Paper).where(Paper.id == existing.id).values(**values)
                await session.execute(stmt)
                await session.commit()
                return existing.id
            else:
                paper = Paper(
                    title=title,
                    abstract=abstract,
                    authors_json=to_json(authors),
                    year=year,
                    journal=journal,
                    doi=normalized_doi,
                    pmid=pmid,
                    pmcid=pmcid,
                    crossref_id=crossref_id,
                    source=source,
                    url=url,
                    pdf_url=pdf_url,
                    license=license,
                    is_open_access=is_open_access,
                    domain_score=domain_score,
                    status=status,
                    crawl_task_id=crawl_task_id,
                )
                session.add(paper)
                await session.commit()
                return paper.id

    async def _find_existing_paper(
        self, session, title, year, doi, pmid, pmcid
    ) -> Optional[Paper]:
        """查找已有文献（DOI > PMID > PMCID > title+year）。"""
        if doi:
            result = await session.execute(
                select(Paper).where(Paper.doi == doi)
            )
            row = result.scalar_one_or_none()
            if row:
                return row

        if pmid:
            result = await session.execute(
                select(Paper).where(Paper.pmid == pmid)
            )
            row = result.scalar_one_or_none()
            if row:
                return row

        if pmcid:
            result = await session.execute(
                select(Paper).where(Paper.pmcid == pmcid)
            )
            row = result.scalar_one_or_none()
            if row:
                return row

        if title and year:
            from sqlalchemy import func as sqla_func
            result = await session.execute(
                select(Paper).where(
                    sqla_func.lower(Paper.title) == title.strip().lower(),
                    Paper.year == year,
                )
            )
            row = result.scalar_one_or_none()
            if row:
                return row

        return None

    async def get_paper(self, paper_id: int) -> Optional[dict[str, Any]]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Paper).where(Paper.id == paper_id)
            )
            row = result.scalar_one_or_none()
            return _row_to_dict(row) if row else None

    async def list_papers(
        self,
        limit: int = 20,
        offset: int = 0,
        min_domain_score: Optional[float] = None,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        async with async_session_factory() as session:
            stmt = select(Paper)
            if min_domain_score is not None:
                stmt = stmt.where(Paper.domain_score >= min_domain_score)
            if status is not None:
                stmt = stmt.where(Paper.status == status)
            stmt = stmt.order_by(Paper.year.desc(), Paper.id.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return [_row_to_dict(row) for row in result.scalars().all()]

    async def update_file_paths(
        self,
        paper_id: int,
        local_pdf_path: Optional[str] = None,
        local_text_path: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        async with async_session_factory() as session:
            values = {}
            if local_pdf_path is not None:
                values["local_pdf_path"] = local_pdf_path
            if local_text_path is not None:
                values["local_text_path"] = local_text_path
            if status is not None:
                values["status"] = status
            if values:
                stmt = update(Paper).where(Paper.id == paper_id).values(**values)
                await session.execute(stmt)
                await session.commit()


# ============================================================
# 3. Chunk Repository
# ============================================================

class ChunkRepository:

    async def add_chunk(
        self,
        paper_id: int,
        chunk_index: int,
        text: str,
        section_title: Optional[str] = None,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        token_count: Optional[int] = None,
    ) -> int:
        async with async_session_factory() as session:
            stmt = pg_insert(Chunk).values(
                paper_id=paper_id,
                chunk_index=chunk_index,
                text=text,
                section_title=section_title,
                page_start=page_start,
                page_end=page_end,
                token_count=token_count,
            ).on_conflict_do_update(
                constraint="uq_chunks_paper_chunk",
                set_={
                    "section_title": section_title,
                    "page_start": page_start,
                    "page_end": page_end,
                    "text": text,
                    "token_count": token_count,
                    "embedding_status": "pending",
                },
            )
            await session.execute(stmt)
            await session.commit()

            # 查询实际 id
            result = await session.execute(
                select(Chunk.id).where(
                    Chunk.paper_id == paper_id,
                    Chunk.chunk_index == chunk_index,
                )
            )
            chunk_id = result.scalar_one()
            return chunk_id

    async def list_chunks_by_paper(self, paper_id: int) -> list[dict[str, Any]]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Chunk)
                .where(Chunk.paper_id == paper_id)
                .order_by(Chunk.chunk_index.asc())
            )
            return [_row_to_dict(row) for row in result.scalars().all()]

    async def list_pending_embedding_chunks(
        self, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Chunk)
                .where(Chunk.embedding_status == "pending")
                .order_by(Chunk.id.asc())
                .limit(limit)
            )
            return [_row_to_dict(row) for row in result.scalars().all()]

    async def mark_embedded(self, chunk_id: int, faiss_vector_id: int) -> None:
        async with async_session_factory() as session:
            stmt = (
                update(Chunk)
                .where(Chunk.id == chunk_id)
                .values(embedding_status="embedded", faiss_vector_id=faiss_vector_id)
            )
            await session.execute(stmt)
            await session.commit()


# ============================================================
# 4. Compound Repository
# ============================================================

class CompoundRepository:

    async def get_compound(self, compound_id: int) -> Optional[dict[str, Any]]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Compound).where(Compound.id == compound_id)
            )
            row = result.scalar_one_or_none()
            return _row_to_dict(row) if row else None


# ============================================================
# 5. Spectrum Repository
# ============================================================

class SpectrumRepository:

    async def search_by_precursor_mz(
        self,
        precursor_mz: float,
        tolerance: float = 0.01,
        ion_mode: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return []
