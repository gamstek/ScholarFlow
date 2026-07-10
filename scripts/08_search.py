"""
search_local_chunks.py

本地 FAISS chunk 检索测试脚本。

运行方式：
    python scripts/search_local_chunks.py --query "How are human milk oligosaccharides characterized by LC-MS/MS?"

中文问题也可以：
    python scripts/search_local_chunks.py --query "HMO 的 LC-MS/MS 结构解析通常用哪些碎片离子？"

作用：
1. 加载 BGE-M3 embedding 模型；
2. 加载本地 FAISS index；
3. 将 query 向量化；
4. 检索最相似 chunks；
5. 从数据库读取 chunk 原文；
6. 打印检索结果。
"""

from __future__ import annotations

import argparse
import asyncio
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
from app.storage.database import async_session_factory  # noqa: E402

from sqlalchemy import text as sa_text  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="测试本地 FAISS chunk 检索。"
    )

    parser.add_argument(
        "--query",
        type=str,
        default="How are human milk oligosaccharides characterized by LC-MS/MS?",
        help="检索问题。",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="返回前 k 个 chunk。",
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
        help="运行设备，例如 cpu 或 cuda。",
    )

    parser.add_argument(
        "--preview-chars",
        type=int,
        default=1000,
        help="每个 chunk 最多预览多少字符。",
    )

    return parser.parse_args()


async def get_chunk_with_paper(
    chunk_id: int,
) -> dict[str, Any] | None:
    """
    根据 chunk_id 从数据库读取 chunk 原文和论文信息。
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


async def main() -> None:
    """
    主函数。
    """
    args = parse_args()

    print("=" * 80)
    print("本地 FAISS chunk 检索")
    print("=" * 80)
    print(f"query: {args.query}")
    print(f"top_k: {args.top_k}")
    print(f"model_name: {args.model_name}")
    print(f"device: {args.device}")
    print("=" * 80)

    print("正在加载 embedding 模型…")
    embedder = TextEmbedder(
        model_name=args.model_name,
        device=args.device,
        normalize_embeddings=True,
    )

    print(f"模型加载完成，dimension = {embedder.dimension}")

    vector_store = FaissVectorStore(
        dimension=embedder.dimension,
    )

    print("正在加载 FAISS 索引…")
    vector_store.load_or_create()

    print(f"FAISS 向量数量：{vector_store.ntotal}")

    query_embedding = embedder.encode_query(args.query)

    results = vector_store.search(
        query_embedding=query_embedding,
        top_k=args.top_k,
    )

    if not results:
        print("没有检索到结果。")
        return

    print("\n检索结果：")

    for result in results:
        metadata = result.metadata
        chunk_id = int(metadata["chunk_id"])

        chunk = await get_chunk_with_paper(chunk_id)

        print("-" * 80)
        print(f"rank: {result.rank}")
        print(f"score: {result.score:.4f}")
        print(f"faiss_vector_id: {result.faiss_vector_id}")
        print(f"chunk_id: {chunk_id}")

        if chunk is None:
            print("数据库中未找到对应的 chunk。")
            continue

        print(f"paper_id: {chunk['paper_id']}")
        print(f"title: {chunk['paper_title']}")
        print(f"year: {chunk['year']}")
        print(f"journal: {chunk['journal']}")
        print(f"doi: {chunk['doi']}")
        print(f"section: {chunk['section_title']}")
        print(f"pages: {chunk['page_start']} - {chunk['page_end']}")
        print(f"token_count: {chunk['token_count']}")
        print("\ntext preview:")
        text = chunk["text"] or ""
        print(text[:args.preview_chars])

        if len(text) > args.preview_chars:
            print("...")

    print("\n本地 chunk 检索流程已完成。")


if __name__ == "__main__":
    asyncio.run(main())