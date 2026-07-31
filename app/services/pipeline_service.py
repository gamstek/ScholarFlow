"""
pipeline_service.py

通用文献采集与检索系统的流程服务层。

作用：
1. 文献采集；
2. 开放获取 PDF 下载；
3. PDF 正文解析；
4. parsed JSON 切 chunks；
5. chunks embedding + FAISS 索引构建。

这个文件把原来 scripts/ 里的流程抽成可被 FastAPI 调用的函数。
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncGenerator

from app.document.chunker import SectionBasedChunker
from app.document.pdf_parser import PdfParser
from app.document.section_parser import parse_sections_from_pages, sections_to_dicts
from app.harvest.harvester import LiteratureHarvester, report_to_dict, search_report_to_dict
from app.harvest.literature.pdf_resolver import OpenAccessPdfResolver
from app.rag.embedder import DEFAULT_EMBEDDING_MODEL, TextEmbedder
from app.rag.vector_store import FaissVectorStore
from app.storage.database import async_session_factory, init_db
from app.storage.file_store import (
    get_relative_path,
    get_text_path,
    load_json,
    resolve_project_path,
    save_json,
)
from app.storage.repositories import ChunkRepository, PaperRepository

from sqlalchemy import text as sa_text, bindparam


# ============================================================
# 1. 文献采集
# ============================================================

async def crawl_literature_service(
    query: str,
    sources: list[str] | None = None,
    max_results: int = 20,
    min_domain_score: float = 0.25,
    enhance_query: bool = True,
) -> dict[str, Any]:
    """
    从指定数据源采集文献 metadata，并写入数据库。

    参数：
        sources: 数据源列表，如 ["europe_pmc", "arxiv"]。
            支持：europe_pmc / nature / science / cell / arxiv / semantic_scholar
    """
    if sources is None:
        sources = ["europe_pmc"]

    harvester = LiteratureHarvester(
        min_domain_score=min_domain_score,
    )

    report = await harvester.crawl(
        query=query,
        sources=sources,
        max_results=max_results,
        enhance_query=enhance_query,
    )

    return report_to_dict(report)


# ============================================================
# 1b. 仅检索不入库
# ============================================================

async def search_papers_service(
    query: str,
    sources: list[str] | None = None,
    max_results: int = 20,
    enhance_query: bool = True,
    keywords: list[str] | None = None,
    domain: str | None = None,
    sort_by: str = "relevance",
    sort_order: str = "desc",
    author: str | None = None,
    journal: str | None = None,
    preprint_sources: list[str] | None = None,
    language: str | None = None,
    max_total: int | None = None,
) -> dict[str, Any]:
    """
    仅检索 + 评分 + 在库检查，不写入数据库。

    参数：
        query: 检索词（如已通过 LLM 提取，则为关键词拼接）。
        sources: 数据源列表。
        max_results: 每源最大检索数。
        enhance_query: 是否增强检索（仅 europe_pmc）。
        keywords: LLM 提取的关键词（透传给前端展示）。
        domain: LLM 提取的领域标签。
        sort_by: 排序方式（relevance / year / citations）。
        sort_order: 排序顺序（asc / desc）。
        author: 按作者名过滤。
        journal: 按期刊名过滤（仅 europe_pmc 生效）。
    """
    if sources is None:
        sources = ["europe_pmc"]

    harvester = LiteratureHarvester()

    report = await harvester.search_only(
        query=query,
        sources=sources,
        max_results=max_results,
        enhance_query=enhance_query,
        keywords=keywords,
        domain=domain,
        sort_by=sort_by,
        sort_order=sort_order,
        author=author,
        journal=journal,
        preprint_sources=preprint_sources,
        language=language,
        max_total=max_total,
    )

    return search_report_to_dict(report)


# ============================================================
# 1b-stream. 流式检索（SSE）
# ============================================================

async def search_papers_stream_service(
    query: str,
    sources: list[str] | None = None,
    max_results: int = 20,
    enhance_query: bool = True,
    keywords: list[str] | None = None,
    domain: str | None = None,
    sort_by: str = "relevance",
    sort_order: str = "desc",
    author: str | None = None,
    journal: str | None = None,
    preprint_sources: list[str] | None = None,
    language: str | None = None,
    max_total: int | None = None,
) -> AsyncGenerator[str, None]:
    """
    流式检索：通过 SSE 逐源推送进度，最后推送完整结果。
    """
    if sources is None:
        sources = ["europe_pmc"]

    harvester = LiteratureHarvester()

    async for event in harvester.search_only_stream(
        query=query,
        sources=sources,
        max_results=max_results,
        enhance_query=enhance_query,
        keywords=keywords,
        domain=domain,
        sort_by=sort_by,
        sort_order=sort_order,
        author=author,
        journal=journal,
        preprint_sources=preprint_sources,
        language=language,
        max_total=max_total,
    ):
        yield event


# ============================================================
# 1c. 单篇论文入库
# ============================================================

async def import_single_paper_service(
    title: str,
    abstract: str | None = None,
    authors: list[str] | None = None,
    author_affiliations: list[dict] | None = None,
    year: int | None = None,
    journal: str | None = None,
    doi: str | None = None,
    pmid: str | None = None,
    pmcid: str | None = None,
    source: str = "manual_import",
    url: str | None = None,
    pdf_url: str | None = None,
    license: str | None = None,
    is_open_access: int = 0,
    domain_score: float = 0.0,
) -> dict[str, Any]:
    """
    单篇论文入库（metadata），返回 paper_id。

    入库后可通过 POST /papers/{id}/process 触发完整流水线。
    """
    await init_db()

    paper_repo = PaperRepository()

    paper_id = await paper_repo.upsert_paper(
        title=title,
        abstract=abstract,
        authors=authors,
        author_affiliations=author_affiliations,
        year=year,
        journal=journal,
        doi=doi,
        pmid=pmid,
        pmcid=pmcid,
        crossref_id=None,
        source=source,
        url=url,
        pdf_url=pdf_url,
        license=license,
        is_open_access=is_open_access,
        domain_score=domain_score,
        status="metadata_only",
        crawl_task_id=None,
    )

    return {
        "paper_id": paper_id,
        "title": title,
        "doi": doi,
        "status": "metadata_only",
        "message": "论文 metadata 已入库。可调用 /papers/{id}/process 触发完整流水线。",
    }


# ============================================================
# 2. PDF 下载
# ============================================================

async def download_open_access_pdfs_service(
    limit: int = 5,
    overwrite: bool = False,
    include_already_downloaded: bool = False,
) -> dict[str, Any]:
    """
    下载开放获取 PDF。
    """
    resolver = OpenAccessPdfResolver()

    candidates = await resolver.list_candidate_papers(
        limit=limit,
        include_already_downloaded=include_already_downloaded,
    )

    # 只查一次候选，避免 download_batch 内部重复查询
    results = []
    for candidate in candidates:
        result = await resolver.download_for_paper(candidate, overwrite=overwrite)
        results.append(result)
        if len(results) >= limit:
            break

    result_dicts = [asdict(result) for result in results]

    success_count = sum(
        1
        for result in results
        if result.success and result.status != "skipped"
    )

    skipped_count = sum(
        1
        for result in results
        if result.status == "skipped"
    )

    failed_count = sum(
        1
        for result in results
        if not result.success
    )

    return {
        "candidate_count": len(candidates),
        "processed_count": len(results),
        "success_count": success_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "results": result_dicts,
    }


# ============================================================
# 3. PDF 解析
# ============================================================

async def list_pdf_parse_candidates(
    limit: int,
    include_parsed: bool = False,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    """
    查询可以进行 PDF 解析的文献。
    """
    await init_db()

    statuses = ["pdf_downloaded"]

    if include_parsed:
        statuses.append("parsed")

    conditions = [
        "status IN :statuses",
        "local_pdf_path IS NOT NULL",
        "local_pdf_path != ''",
    ]

    if not overwrite:
        conditions.append(
            "(local_text_path IS NULL OR local_text_path = '')"
        )

    where_sql = " AND ".join(conditions)

    sql = sa_text(
        f"""
        SELECT *
        FROM papers
        WHERE {where_sql}
        ORDER BY domain_score DESC, year DESC, id ASC
        LIMIT :limit;
        """
    ).bindparams(
        bindparam("statuses", expanding=True),
    )

    async with async_session_factory() as session:
        result = await session.execute(
            sql,
            {"statuses": tuple(statuses), "limit": limit},
        )
        rows = result.fetchall()

    return [dict(row._mapping) for row in rows]


async def parse_single_pdf_service(
    paper: dict[str, Any],
    parser: PdfParser,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    解析单篇 PDF，保存 JSON，并更新 papers 表。
    """
    paper_id = int(paper["id"])
    title = str(paper["title"])
    doi = paper.get("doi")
    local_pdf_path = paper.get("local_pdf_path")
    local_text_path = paper.get("local_text_path")

    if not local_pdf_path:
        return {
            "paper_id": paper_id,
            "success": False,
            "status": "no_pdf_path",
            "message": "local_pdf_path 为空。",
        }

    if local_text_path and not overwrite:
        return {
            "paper_id": paper_id,
            "success": True,
            "status": "skipped",
            "message": "该文献已有解析文本，跳过。",
            "local_text_path": local_text_path,
        }

    pdf_path = resolve_project_path(local_pdf_path)

    if not pdf_path.exists():
        return {
            "paper_id": paper_id,
            "success": False,
            "status": "pdf_not_found",
            "message": f"PDF 文件不存在：{pdf_path}",
        }

    parsed_document = parser.parse(pdf_path)
    parsed_dict = parser.to_dict(parsed_document)

    # 从 PDF metadata 中提取标题，并同步到 papers 表
    pdf_meta_title = (parsed_dict.get("metadata") or {}).get("title")
    if pdf_meta_title and isinstance(pdf_meta_title, str):
        pdf_meta_title = html.unescape(pdf_meta_title).strip()
        # 只保留合理的标题（去除非打印字符、控制字符）
        pdf_meta_title = "".join(ch for ch in pdf_meta_title if ch.isprintable() or ch in "\n\r\t")
        if pdf_meta_title and pdf_meta_title != title:
            await paper_repo.update_title(paper_id, pdf_meta_title)
            title = pdf_meta_title  # 后续 JSON 输出也用 PDF 标题

    sections = parse_sections_from_pages(
        pages=parsed_dict["pages"],
    )

    section_dicts = sections_to_dicts(sections)

    output_data = {
        "paper": {
            "id": paper_id,
            "title": title,
            "doi": doi,
            "pmid": paper.get("pmid"),
            "pmcid": paper.get("pmcid"),
            "year": paper.get("year"),
            "journal": paper.get("journal"),
            "source": paper.get("source"),
            "url": paper.get("url"),
            "pdf_url": paper.get("pdf_url"),
        },
        "pdf": {
            "local_pdf_path": local_pdf_path,
            "page_count": parsed_dict["page_count"],
            "metadata": parsed_dict["metadata"],
        },
        "pages": parsed_dict["pages"],
        "sections": section_dicts,
        "full_text": parsed_dict["full_text"],
    }

    output_path = get_text_path(
        paper_id=paper_id,
        title=title,
        doi=doi,
    )

    save_json(
        data=output_data,
        output_path=output_path,
    )

    relative_text_path = get_relative_path(output_path)

    paper_repo = PaperRepository()
    await paper_repo.update_file_paths(
        paper_id=paper_id,
        local_text_path=relative_text_path,
        status="parsed",
    )

    total_chars = len(parsed_dict["full_text"])
    non_empty_pages = sum(
        1
        for page in parsed_dict["pages"]
        if page.get("char_count", 0) > 0
    )

    return {
        "paper_id": paper_id,
        "success": True,
        "status": "parsed",
        "message": "PDF 解析成功。",
        "local_pdf_path": local_pdf_path,
        "local_text_path": relative_text_path,
        "page_count": parsed_dict["page_count"],
        "non_empty_pages": non_empty_pages,
        "section_count": len(section_dicts),
        "total_chars": total_chars,
    }


async def parse_downloaded_pdfs_service(
    limit: int = 5,
    overwrite: bool = False,
    include_parsed: bool = False,
) -> dict[str, Any]:
    """
    批量解析已下载 PDF。
    """
    candidates = await list_pdf_parse_candidates(
        limit=limit,
        include_parsed=include_parsed,
        overwrite=overwrite,
    )

    parser = PdfParser()

    results: list[dict[str, Any]] = []

    for paper in candidates:
        try:
            result = await parse_single_pdf_service(
                paper=paper,
                parser=parser,
                overwrite=overwrite,
            )
        except Exception as exc:
            result = {
                "paper_id": paper.get("id"),
                "success": False,
                "status": "failed",
                "message": str(exc),
            }

        results.append(result)

    success_count = sum(
        1
        for result in results
        if result.get("success") and result.get("status") == "parsed"
    )

    skipped_count = sum(
        1
        for result in results
        if result.get("status") == "skipped"
    )

    failed_count = sum(
        1
        for result in results
        if not result.get("success")
    )

    return {
        "candidate_count": len(candidates),
        "processed_count": len(results),
        "success_count": success_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "results": results,
    }


# ============================================================
# 4. Chunk 构建
# ============================================================

async def list_chunk_candidates(
    limit: int,
    include_chunked: bool = False,
) -> list[dict[str, Any]]:
    """
    查询可以切 chunk 的文献。
    """
    await init_db()

    statuses = ["parsed"]

    if include_chunked:
        statuses.append("chunked")

    sql = sa_text(
        f"""
        SELECT *
        FROM papers
        WHERE status IN :statuses
          AND local_text_path IS NOT NULL
          AND local_text_path != ''
        ORDER BY domain_score DESC, year DESC, id ASC
        LIMIT :limit;
        """
    ).bindparams(
        bindparam("statuses", expanding=True),
    )

    async with async_session_factory() as session:
        result = await session.execute(
            sql,
            {"statuses": tuple(statuses), "limit": limit},
        )
        rows = result.fetchall()

    return [dict(row._mapping) for row in rows]


async def count_existing_chunks(
    paper_id: int,
) -> int:
    """
    查询某篇论文已有 chunk 数量。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            sa_text("SELECT COUNT(*) AS count FROM chunks WHERE paper_id = :paper_id;"),
            {"paper_id": paper_id},
        )
        row = result.fetchone()

    return int(row._mapping["count"]) if row else 0


async def delete_existing_chunks(
    paper_id: int,
) -> int:
    """
    删除某篇论文已有 chunks。
    """
    async with async_session_factory() as session:
        count_result = await session.execute(
            sa_text("SELECT COUNT(*) AS count FROM chunks WHERE paper_id = :paper_id;"),
            {"paper_id": paper_id},
        )
        row = count_result.fetchone()
        old_count = int(row._mapping["count"]) if row else 0

        await session.execute(
            sa_text("DELETE FROM chunks WHERE paper_id = :paper_id;"),
            {"paper_id": paper_id},
        )
        await session.commit()

    return old_count


def summarize_chunks_by_section(
    chunks: list[Any],
) -> dict[str, int]:
    """
    按章节统计 chunk 数量。
    """
    summary: dict[str, int] = {}

    for chunk in chunks:
        section_title = chunk.section_title or "Unknown"
        summary[section_title] = summary.get(section_title, 0) + 1

    return summary


async def build_chunks_for_single_paper_service(
    paper: dict[str, Any],
    chunker: SectionBasedChunker,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    对单篇文献构建 chunks。
    """
    paper_id = int(paper["id"])
    title = str(paper["title"])
    local_text_path = paper.get("local_text_path")

    if not local_text_path:
        return {
            "paper_id": paper_id,
            "success": False,
            "status": "no_text_path",
            "message": "local_text_path 为空。",
        }

    existing_chunk_count = await count_existing_chunks(paper_id)

    if existing_chunk_count > 0 and not overwrite:
        return {
            "paper_id": paper_id,
            "success": True,
            "status": "skipped",
            "message": "该文献已有 chunks，跳过。如需重建，请使用 overwrite=true。",
            "existing_chunk_count": existing_chunk_count,
        }

    if existing_chunk_count > 0 and overwrite:
        deleted_count = await delete_existing_chunks(paper_id)
    else:
        deleted_count = 0

    text_path = resolve_project_path(local_text_path)

    if not text_path.exists():
        return {
            "paper_id": paper_id,
            "success": False,
            "status": "text_not_found",
            "message": f"解析文本文件不存在：{text_path}",
        }

    parsed_json = load_json(text_path)

    chunks = chunker.chunk_parsed_document(parsed_json)

    if not chunks:
        return {
            "paper_id": paper_id,
            "success": False,
            "status": "no_chunks",
            "message": "没有切出有效 chunks。",
            "deleted_count": deleted_count,
        }

    chunk_repo = ChunkRepository()

    inserted_chunk_ids: list[int] = []

    for chunk in chunks:
        chunk_id = await chunk_repo.add_chunk(
            paper_id=paper_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            section_title=chunk.section_title,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            token_count=chunk.token_count,
        )

        inserted_chunk_ids.append(chunk_id)

    paper_repo = PaperRepository()
    await paper_repo.update_file_paths(
        paper_id=paper_id,
        status="chunked",
    )

    return {
        "paper_id": paper_id,
        "success": True,
        "status": "chunked",
        "message": "chunks 构建成功。",
        "title": title,
        "deleted_count": deleted_count,
        "chunk_count": len(chunks),
        "inserted_chunk_ids_preview": inserted_chunk_ids[:10],
        "section_summary": summarize_chunks_by_section(chunks),
    }


async def build_chunks_service(
    limit: int = 5,
    max_chars: int = 2500,
    overlap_chars: int = 300,
    min_chars: int = 300,
    overwrite: bool = False,
    include_chunked: bool = False,
    keep_references: bool = False,
) -> dict[str, Any]:
    """
    批量构建 chunks。
    """
    candidates = await list_chunk_candidates(
        limit=limit,
        include_chunked=include_chunked,
    )

    chunker = SectionBasedChunker(
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        min_chars=min_chars,
        skip_reference_sections=not keep_references,
    )

    results: list[dict[str, Any]] = []

    for paper in candidates:
        try:
            result = await build_chunks_for_single_paper_service(
                paper=paper,
                chunker=chunker,
                overwrite=overwrite,
            )
        except Exception as exc:
            result = {
                "paper_id": paper.get("id"),
                "success": False,
                "status": "failed",
                "message": str(exc),
            }

        results.append(result)

    success_count = sum(
        1
        for result in results
        if result.get("success") and result.get("status") == "chunked"
    )

    skipped_count = sum(
        1
        for result in results
        if result.get("status") == "skipped"
    )

    failed_count = sum(
        1
        for result in results
        if not result.get("success")
    )

    return {
        "candidate_count": len(candidates),
        "processed_count": len(results),
        "success_count": success_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "results": results,
    }


# ============================================================
# 5. FAISS 索引构建
# ============================================================

async def reset_embedding_status_for_rebuild() -> None:
    """
    重建索引时重置 chunks embedding 状态。
    """
    async with async_session_factory() as session:
        await session.execute(
            sa_text("""
                UPDATE chunks
                SET
                    embedding_status = 'pending',
                    faiss_vector_id = NULL;
            """)
        )

        await session.execute(
            sa_text("""
                UPDATE papers
                SET
                    status = 'chunked',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'indexed';
            """)
        )

        await session.commit()


async def list_chunks_for_embedding(
    limit: int,
) -> list[dict[str, Any]]:
    """
    查询待 embedding 的 chunks。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            sa_text("""
                SELECT
                    chunks.id AS chunk_id,
                    chunks.paper_id AS paper_id,
                    chunks.chunk_index AS chunk_index,
                    chunks.section_title AS section_title,
                    chunks.page_start AS page_start,
                    chunks.page_end AS page_end,
                    chunks.text AS text,
                    chunks.token_count AS token_count,

                    papers.title AS paper_title,
                    papers.doi AS doi,
                    papers.year AS year,
                    papers.journal AS journal,
                    papers.url AS url,
                    papers.pmid AS pmid,
                    papers.pmcid AS pmcid

                FROM chunks
                INNER JOIN papers
                    ON chunks.paper_id = papers.id
                WHERE chunks.embedding_status = 'pending'
                ORDER BY chunks.paper_id ASC, chunks.chunk_index ASC
                LIMIT :limit;
            """),
            {"limit": limit},
        )
        rows = result.fetchall()

    return [dict(row._mapping) for row in rows]


def build_metadata_for_chunk(
    chunk: dict[str, Any],
) -> dict[str, Any]:
    """
    构造写入 FAISS metadata 的 chunk 元数据。
    """
    return {
        "chunk_id": chunk["chunk_id"],
        "paper_id": chunk["paper_id"],
        "chunk_index": chunk["chunk_index"],
        "section_title": chunk["section_title"],
        "page_start": chunk["page_start"],
        "page_end": chunk["page_end"],
        "token_count": chunk["token_count"],
        "paper_title": chunk["paper_title"],
        "doi": chunk["doi"],
        "year": chunk["year"],
        "journal": chunk["journal"],
        "url": chunk["url"],
        "pmid": chunk["pmid"],
        "pmcid": chunk["pmcid"],
    }


async def update_chunks_as_embedded(
    chunk_ids: list[int],
    faiss_vector_ids: list[int],
) -> None:
    """
    更新 chunks 表 embedding 状态。
    """
    if len(chunk_ids) != len(faiss_vector_ids):
        raise ValueError("chunk_ids 和 faiss_vector_ids 数量不一致。")

    chunk_repo = ChunkRepository()

    for chunk_id, vector_id in zip(chunk_ids, faiss_vector_ids):
        await chunk_repo.mark_embedded(
            chunk_id=chunk_id,
            faiss_vector_id=vector_id,
        )


async def update_papers_as_indexed_for_chunks(
    chunk_ids: list[int],
) -> None:
    """
    如果某篇论文所有 chunks 都 embedded，则将 paper.status 更新为 indexed。
    """
    if not chunk_ids:
        return

    async with async_session_factory() as session:
        result = await session.execute(
            sa_text("""
                SELECT DISTINCT paper_id
                FROM chunks
                WHERE id = ANY(:chunk_ids);
            """),
            {"chunk_ids": chunk_ids},
        )

        paper_ids = [int(row._mapping["paper_id"]) for row in result.fetchall()]

        for paper_id in paper_ids:
            count_result = await session.execute(
                sa_text("""
                    SELECT
                        COUNT(*) AS total_chunks,
                        SUM(
                            CASE
                                WHEN embedding_status = 'embedded' THEN 1
                                ELSE 0
                            END
                        ) AS embedded_chunks
                    FROM chunks
                    WHERE paper_id = :paper_id;
                """),
                {"paper_id": paper_id},
            )

            row = count_result.fetchone()
            total_chunks = int(row._mapping["total_chunks"] or 0)
            embedded_chunks = int(row._mapping["embedded_chunks"] or 0)

            if total_chunks > 0 and total_chunks == embedded_chunks:
                await session.execute(
                    sa_text("""
                        UPDATE papers
                        SET
                            status = 'indexed',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :paper_id;
                    """),
                    {"paper_id": paper_id},
                )

        await session.commit()


async def build_faiss_index_service(
    limit: int = 100,
    batch_size: int = 4,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    device: str | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """
    将 pending chunks 向量化并写入 FAISS。
    """
    await init_db()

    embedder = TextEmbedder(
        model_name=model_name,
        device=device,
        normalize_embeddings=True,
    )

    vector_store = FaissVectorStore(
        dimension=embedder.dimension,
    )

    if rebuild:
        vector_store.reset()
        await reset_embedding_status_for_rebuild()
    else:
        vector_store.load_or_create()

    chunks = await list_chunks_for_embedding(
        limit=limit,
    )

    if not chunks:
        return {
            "processed_chunk_count": 0,
            "message": "没有 pending chunks 需要向量化。",
            "faiss_ntotal": vector_store.ntotal,
        }

    texts = [chunk["text"] for chunk in chunks]
    metadata_list = [
        build_metadata_for_chunk(chunk)
        for chunk in chunks
    ]
    chunk_ids = [
        int(chunk["chunk_id"])
        for chunk in chunks
    ]

    embedding_result = embedder.encode_texts(
        texts=texts,
        batch_size=batch_size,
        show_progress_bar=False,
    )

    faiss_vector_ids = vector_store.add_embeddings(
        embeddings=embedding_result.embeddings,
        metadata_list=metadata_list,
    )

    vector_store.save()

    await update_chunks_as_embedded(
        chunk_ids=chunk_ids,
        faiss_vector_ids=faiss_vector_ids,
    )

    await update_papers_as_indexed_for_chunks(
        chunk_ids=chunk_ids,
    )

    return {
        "processed_chunk_count": len(chunks),
        "first_chunk_id": chunk_ids[0],
        "last_chunk_id": chunk_ids[-1],
        "first_faiss_vector_id": faiss_vector_ids[0],
        "last_faiss_vector_id": faiss_vector_ids[-1],
        "faiss_ntotal": vector_store.ntotal,
        "index_path": str(vector_store.index_path),
        "metadata_path": str(vector_store.metadata_path),
        "embedding_dimension": embedder.dimension,
        "model_name": model_name,
        "device": device,
        "rebuild": rebuild,
    }