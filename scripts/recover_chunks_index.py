"""
恢复 chunks 和 FAISS 索引 — 从已恢复的 parsed 论文重建。

用法：
    cd d:\ScholarFlow
    python scripts\recover_chunks_index.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pipeline_service import build_chunks_service, build_faiss_index_service
from app.storage.database import init_db


async def recover():
    await init_db()

    # Step 1: 构建 chunks（处理所有 parsed 状态的论文）
    print("=" * 60)
    print("Step 1/2: 构建 chunks...")
    print("=" * 60)

    # 获取论文总数
    from app.storage.database import async_session_factory
    from sqlalchemy import text as sa_text
    async with async_session_factory() as session:
        result = await session.execute(
            sa_text("SELECT COUNT(*) FROM papers WHERE status = 'parsed'")
        )
        total = result.fetchone()[0]
    print(f"待处理论文: {total} 篇\n")

    chunk_result = await build_chunks_service(
        limit=200,
        overwrite=False,
    )
    print(f"\nChunks 构建完成:")
    print(f"  候选: {chunk_result.get('candidate_count', 0)}")
    print(f"  成功: {chunk_result.get('success_count', 0)}")
    print(f"  跳过: {chunk_result.get('skipped_count', 0)}")
    print(f"  失败: {chunk_result.get('failed_count', 0)}")

    # Step 2: 构建 FAISS 索引
    print("\n" + "=" * 60)
    print("Step 2/2: 构建 FAISS 索引...")
    print("=" * 60)

    index_result = await build_faiss_index_service(
        limit=5000,
        batch_size=8,
        rebuild=True,
    )
    print(f"\nFAISS 索引完成:")
    print(f"  处理 chunks: {index_result.get('processed_chunk_count', 0)}")
    print(f"  FAISS total: {index_result.get('faiss_ntotal', 0)}")

    print("\n" + "=" * 60)
    print("全部恢复完成！现在可以使用 RAG 问答和文献综述了。")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(recover())
