"""
build_faiss_index_from_chunks.py

将 chunks 表中的文本向量化，并写入 FAISS 持久化索引。

运行方式：
    python scripts/build_faiss_index_from_chunks.py

指定数量：
    python scripts/build_faiss_index_from_chunks.py --limit 100

重建整个索引：
    python scripts/build_faiss_index_from_chunks.py --rebuild --limit 1000

使用 CPU：
    python scripts/build_faiss_index_from_chunks.py --device cpu

使用 GPU：
    python scripts/build_faiss_index_from_chunks.py --device cuda

作用：
1. 从 chunks 表读取待向量化文本；
2. 调用 BGE-M3 生成 embedding；
3. 写入 FAISS index；
4. 保存 chunk metadata；
5. 更新 chunks 表状态；
6. 将对应 papers.status 更新为 indexed。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


# ============================================================
# 让脚本可以从项目根目录导入 app 模块
# ============================================================

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.rag.embedder import TextEmbedder  # noqa: E402
from app.rag.vector_store import FaissVectorStore  # noqa: E402
from app.storage.database import async_session_factory, init_db  # noqa: E402
from app.storage.repositories import ChunkRepository  # noqa: E402

from sqlalchemy import text as sa_text, bindparam  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="将 chunks 表中的文本向量化并写入 FAISS。"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="最多处理多少个 pending chunks。",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="embedding 批处理大小。显存小就调小。",
    )

    parser.add_argument(
        "--model-name",
        type=str,
        default="BAAI/bge-m3",
        help="embedding 模型名称或本地路径。",
    )

    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="运行设备，例如 cpu 或 cuda。默认自动判断。",
    )

    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="是否重建整个 FAISS 索引，并重置 chunks embedding 状态。",
    )

    return parser.parse_args()


async def reset_embedding_status_for_rebuild() -> None:
    """
    重建索引时，重置数据库中的 embedding 状态。

    处理逻辑：
        1. 所有 chunks.embedding_status 改为 pending；
        2. 所有 chunks.faiss_vector_id 清空；
        3. 已 indexed 的 papers 状态改回 chunked。
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

    默认读取：
        embedding_status = 'pending'

    同时关联 papers 表，拿到 title、doi、year 等 metadata。
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
    构造写入 FAISS metadata 文件的 chunk 元数据。

    注意：
        FAISS 只保存向量；
        真正文献追溯信息靠 metadata 和数据库。
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
    更新 chunks 表中的 embedding 状态和 faiss_vector_id。
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
    将已经完成 embedding 的 chunks 所属论文更新为 indexed。

    这里采用保守逻辑：
        只有某篇 paper 的所有 chunks 都已经 embedded，
        才把 papers.status 更新为 indexed。
    """
    if not chunk_ids:
        return

    async with async_session_factory() as session:
        # 获取涉及的 paper_ids
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


async def main() -> None:
    """
    主函数。
    """
    args = parse_args()

    print("=" * 80)
    print("开始将 chunks 向量化并写入 FAISS 索引流程")
    print("=" * 80)
    print(f"limit: {args.limit}")
    print(f"batch_size: {args.batch_size}")
    print(f"model_name: {args.model_name}")
    print(f"device: {args.device}")
    print(f"rebuild: {args.rebuild}")
    print("=" * 80)

    await init_db()

    print("正在加载 embedding 模型…")
    embedder = TextEmbedder(
        model_name=args.model_name,
        device=args.device,
        normalize_embeddings=True,
    )

    print(f"模型加载完成，embedding dimension = {embedder.dimension}")

    vector_store = FaissVectorStore(
        dimension=embedder.dimension,
    )

    if args.rebuild:
        print("检测到 --rebuild，正在重置 FAISS 索引以及数据库中的 embedding 状态…")
        vector_store.reset()
        await reset_embedding_status_for_rebuild()
    else:
        vector_store.load_or_create()

    print(f"当前 FAISS 向量总数：{vector_store.ntotal}")

    chunks = await list_chunks_for_embedding(
        limit=args.limit,
    )

    print(f"待向量化 chunks 数量：{len(chunks)}")

    if not chunks:
        print("没有待向量化的 chunks。")
        return

    texts = [chunk["text"] for chunk in chunks]
    metadata_list = [
        build_metadata_for_chunk(chunk)
        for chunk in chunks
    ]
    chunk_ids = [
        int(chunk["chunk_id"])
        for chunk in chunks
    ]

    print("开始生成 embeddings…")
    embedding_result = embedder.encode_texts(
        texts=texts,
        batch_size=args.batch_size,
        show_progress_bar=True,
    )

    print("embeddings 生成完成。")
    print(f"embedding shape: {embedding_result.embeddings.shape}")

    print("开始写入 FAISS 索引…")
    faiss_vector_ids = vector_store.add_embeddings(
        embeddings=embedding_result.embeddings,
        metadata_list=metadata_list,
    )

    vector_store.save()

    print("FAISS 索引已保存。")
    print(f"index_path: {vector_store.index_path}")
    print(f"metadata_path: {vector_store.metadata_path}")
    print(f"当前 FAISS 向量数量：{vector_store.ntotal}")

    await update_chunks_as_embedded(
        chunk_ids=chunk_ids,
        faiss_vector_ids=faiss_vector_ids,
    )

    await update_papers_as_indexed_for_chunks(
        chunk_ids=chunk_ids,
    )

    report = {
        "processed_chunk_count": len(chunks),
        "first_chunk_id": chunk_ids[0],
        "last_chunk_id": chunk_ids[-1],
        "first_faiss_vector_id": faiss_vector_ids[0],
        "last_faiss_vector_id": faiss_vector_ids[-1],
        "faiss_ntotal": vector_store.ntotal,
        "index_path": str(vector_store.index_path),
        "metadata_path": str(vector_store.metadata_path),
    }

    print("\n构建报告：")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    print("\n完成：chunks 已完成 embedding，并写入 FAISS 持久化索引。")


if __name__ == "__main__":
    asyncio.run(main())