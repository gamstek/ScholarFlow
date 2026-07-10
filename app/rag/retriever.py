"""
retriever.py

本地 RAG 检索模块 Retriever。

作用：
1. 加载 embedding 模型；
2. 加载 FAISS 向量索引；
3. 将用户问题转成 query embedding；
4. 从 FAISS 中检索最相似 chunks；
5. 根据 chunk_id 从数据库读取 chunk 原文和论文元数据；
6. 返回可用于 RAG 上下文拼接的证据列表。

当前阶段：
    Query -> BGE-M3 embedding -> FAISS search -> SQLite chunks/papers -> Evidence

后续可扩展：
1. metadata 过滤；
2. 按年份过滤；
3. 按 section 过滤；
4. reranker 重排序；
5. 混合检索：BM25 + dense embedding。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from app.rag.embedder import TextEmbedder
from app.rag.vector_store import FaissVectorStore
from app.storage.database import async_session_factory

from sqlalchemy import text as sa_text


@dataclass
class RetrievedEvidence:
    """
    RAG 检索证据。

    字段说明：
        source_id:
            给大模型和最终回答使用的来源编号，例如 S1、S2。

        rank:
            检索排名。

        score:
            FAISS 相似度分数。

        chunk_id:
            chunks 表中的 chunk ID。

        paper_id:
            papers 表中的 paper ID。

        paper_title:
            文献标题。

        year:
            发表年份。

        journal:
            期刊名称。

        doi:
            DOI。

        section_title:
            chunk 所属章节。

        page_start:
            起始页。

        page_end:
            结束页。

        text:
            chunk 正文。

        url:
            文献链接。
    """

    source_id: str
    rank: int
    score: float
    chunk_id: int
    paper_id: int
    paper_title: str
    year: Optional[int]
    journal: Optional[str]
    doi: Optional[str]
    section_title: Optional[str]
    page_start: Optional[int]
    page_end: Optional[int]
    text: str
    url: Optional[str]


class LocalChunkRetriever:
    """
    本地 chunk 检索器。

    使用：
        retriever = LocalChunkRetriever(...)
        evidences = retriever.retrieve("your question", top_k=5)
    """

    def __init__(
        self,
        model_name: str = TextEmbedder._LOCAL_BGE_M3_PATH,
        device: str | None = None,
    ) -> None:
        """
        初始化检索器。

        参数：
            model_name:
                embedding 模型名称或本地路径。

            device:
                运行设备，例如：
                    "cpu"
                    "cuda"
                    None
                若未显式指定，从环境变量 EMBEDDING_DEVICE 读取（默认 cpu）。
        """
        # 若未显式指定设备，从环境变量读取（默认 cuda，通过 EMBEDDING_DEVICE=cpu 可切回 CPU）
        if device is None:
            device = os.getenv("EMBEDDING_DEVICE", "cuda")

        self.embedder = TextEmbedder(
            model_name=model_name,
            device=device,
            normalize_embeddings=True,
        )

        self.vector_store = FaissVectorStore(
            dimension=self.embedder.dimension,
        )

        self.vector_store.load_or_create()

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_score: Optional[float] = None,
        section_filter: Optional[list[str]] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> list[RetrievedEvidence]:
        """
        检索与用户问题最相关的 evidence chunks。

        参数：
            query:
                用户问题。

            top_k:
                返回前 k 个结果。

            min_score:
                最低相似度分数，可选。
                如果设置，例如 0.45，则低于该分数的结果会被丢弃。

            section_filter:
                章节过滤，可选。
                例如：
                    ["Methods", "Mass Spectrometry", "Results and Discussion"]

            year_from:
                起始年份过滤，可选。

            year_to:
                结束年份过滤，可选。

        返回：
            RetrievedEvidence 列表。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        # 为了支持过滤，先多取一些候选，再本地过滤
        raw_top_k = max(top_k * 3, top_k)

        query_embedding = self.embedder.encode_query(query)

        search_results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=raw_top_k,
        )

        evidences: list[RetrievedEvidence] = []

        for result in search_results:
            metadata = result.metadata
            chunk_id = int(metadata["chunk_id"])

            chunk_record = await get_chunk_with_paper(chunk_id)

            if chunk_record is None:
                continue

            if min_score is not None and result.score < min_score:
                continue

            if not pass_section_filter(
                section_title=chunk_record.get("section_title"),
                section_filter=section_filter,
            ):
                continue

            if not pass_year_filter(
                year=chunk_record.get("year"),
                year_from=year_from,
                year_to=year_to,
            ):
                continue

            source_id = f"S{len(evidences) + 1}"

            evidence = RetrievedEvidence(
                source_id=source_id,
                rank=len(evidences) + 1,
                score=float(result.score),
                chunk_id=int(chunk_record["chunk_id"]),
                paper_id=int(chunk_record["paper_id"]),
                paper_title=chunk_record["paper_title"] or "",
                year=chunk_record.get("year"),
                journal=chunk_record.get("journal"),
                doi=chunk_record.get("doi"),
                section_title=chunk_record.get("section_title"),
                page_start=chunk_record.get("page_start"),
                page_end=chunk_record.get("page_end"),
                text=chunk_record["text"] or "",
                url=chunk_record.get("url"),
            )

            evidences.append(evidence)

            if len(evidences) >= top_k:
                break

        return evidences


async def get_chunk_with_paper(
    chunk_id: int,
) -> dict[str, Any] | None:
    """
    根据 chunk_id 从数据库读取 chunk 原文和所属文献信息。
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
                    papers.year AS year,
                    papers.journal AS journal,
                    papers.doi AS doi,
                    papers.url AS url,
                    papers.pmid AS pmid,
                    papers.pmcid AS pmcid

                FROM chunks
                INNER JOIN papers
                    ON chunks.paper_id = papers.id
                WHERE chunks.id = :chunk_id;
            """),
            {"chunk_id": chunk_id},
        )

        row = result.fetchone()

    return dict(row._mapping) if row else None


def pass_section_filter(
    section_title: Optional[str],
    section_filter: Optional[list[str]],
) -> bool:
    """
    判断 chunk 是否通过章节过滤。

    如果 section_filter 为空，则不过滤。

    例子：
        section_title = "Mass Spectrometry"
        section_filter = ["methods", "mass spectrometry"]
        返回 True。
    """
    if not section_filter:
        return True

    if not section_title:
        return False

    section_title_lower = section_title.lower()

    for wanted in section_filter:
        wanted_lower = wanted.lower()
        if wanted_lower in section_title_lower:
            return True

    return False


def pass_year_filter(
    year: Optional[int],
    year_from: Optional[int],
    year_to: Optional[int],
) -> bool:
    """
    判断文献年份是否通过过滤。
    """
    if year is None:
        return True

    if year_from is not None and year < year_from:
        return False

    if year_to is not None and year > year_to:
        return False

    return True


def format_evidence_for_context(
    evidences: list[RetrievedEvidence],
    max_chars_per_evidence: int = 1800,
) -> str:
    """
    将 evidence 列表格式化成给大模型看的 context。

    这里的格式非常重要。
    我们明确给每个证据编号：
        [S1]
        [S2]

    后续要求大模型回答时必须引用这些编号。
    """
    context_parts: list[str] = []

    for evidence in evidences:
        text = evidence.text.strip()

        if len(text) > max_chars_per_evidence:
            text = text[:max_chars_per_evidence].rstrip() + "\n...[truncated]"

        source_header = build_source_header(evidence)

        context_parts.append(
            f"[{evidence.source_id}]\n"
            f"{source_header}\n"
            f"Content:\n{text}"
        )

    return "\n\n" + ("-" * 80 + "\n\n").join(context_parts)


def build_source_header(
    evidence: RetrievedEvidence,
) -> str:
    """
    构造证据来源头部信息。
    """
    pieces = [
        f"Title: {evidence.paper_title}",
    ]

    if evidence.year:
        pieces.append(f"Year: {evidence.year}")

    if evidence.journal:
        pieces.append(f"Journal: {evidence.journal}")

    if evidence.doi:
        pieces.append(f"DOI: {evidence.doi}")

    if evidence.section_title:
        pieces.append(f"Section: {evidence.section_title}")

    if evidence.page_start or evidence.page_end:
        pieces.append(f"Pages: {evidence.page_start}-{evidence.page_end}")

    return "\n".join(pieces)


def evidences_to_dicts(
    evidences: list[RetrievedEvidence],
) -> list[dict[str, Any]]:
    """
    将 evidence dataclass 转成 dict，方便 JSON 输出。
    """
    result: list[dict[str, Any]] = []

    for evidence in evidences:
        result.append(
            {
                "source_id": evidence.source_id,
                "rank": evidence.rank,
                "score": evidence.score,
                "chunk_id": evidence.chunk_id,
                "paper_id": evidence.paper_id,
                "paper_title": evidence.paper_title,
                "year": evidence.year,
                "journal": evidence.journal,
                "doi": evidence.doi,
                "section_title": evidence.section_title,
                "page_start": evidence.page_start,
                "page_end": evidence.page_end,
                "url": evidence.url,
                "text": evidence.text,
            }
        )

    return result