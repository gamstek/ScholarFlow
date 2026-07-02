"""
build_chunks_from_parsed_texts.py

将已解析 PDF 文本 JSON 切分成 chunks，并写入 chunks 表。

运行方式：
    python scripts/build_chunks_from_parsed_texts.py

指定数量：
    python scripts/build_chunks_from_parsed_texts.py --limit 5

覆盖已有 chunks：
    python scripts/build_chunks_from_parsed_texts.py --limit 5 --overwrite

作用：
1. 从 papers 表中筛选 status = 'parsed' 的文献；
2. 读取 local_text_path 对应的 JSON；
3. 使用 SectionBasedChunker 切分文本；
4. 写入 chunks 表；
5. 将 papers.status 更新为 'chunked'。
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


from app.document.chunker import SectionBasedChunker  # noqa: E402
from app.storage.database import async_session_factory, init_db  # noqa: E402
from app.storage.file_store import load_json, resolve_project_path  # noqa: E402
from app.storage.repositories import ChunkRepository, PaperRepository  # noqa: E402

from sqlalchemy import text as sa_text, bindparam  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="将已解析论文 JSON 切分成 chunks 并写入数据库。"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="最多处理多少篇已解析文献。",
    )

    parser.add_argument(
        "--max-chars",
        type=int,
        default=2500,
        help="每个 chunk 最大字符数。",
    )

    parser.add_argument(
        "--overlap-chars",
        type=int,
        default=300,
        help="相邻 chunk 的重叠字符数。",
    )

    parser.add_argument(
        "--min-chars",
        type=int,
        default=300,
        help="过短 chunk 合并阈值。",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="是否删除已有 chunks 并重新切分。",
    )

    parser.add_argument(
        "--include-chunked",
        action="store_true",
        help="是否把 status = chunked 的文献也纳入候选。",
    )

    parser.add_argument(
        "--keep-references",
        action="store_true",
        help="是否保留 References 等低价值章节。默认跳过。",
    )

    return parser.parse_args()


async def list_candidate_papers(
    limit: int,
    include_chunked: bool = False,
) -> list[dict[str, Any]]:
    """
    从 papers 表中筛选待 chunk 的文献。

    默认筛选：
        status = 'parsed'
        local_text_path 不为空

    如果 include_chunked=True：
        同时包含 status = 'chunked' 的文献。
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


async def delete_existing_chunks(
    paper_id: int,
) -> int:
    """
    删除某篇文献已有的 chunks。

    返回：
        删除的 chunk 数量。
    """
    async with async_session_factory() as session:
        count_result = await session.execute(
            sa_text("SELECT COUNT(*) AS count FROM chunks WHERE paper_id = :paper_id"),
            {"paper_id": paper_id},
        )
        row = count_result.fetchone()
        old_count = int(row._mapping["count"]) if row else 0

        await session.execute(
            sa_text("DELETE FROM chunks WHERE paper_id = :paper_id"),
            {"paper_id": paper_id},
        )

        await session.commit()

    return old_count


async def count_existing_chunks(
    paper_id: int,
) -> int:
    """
    查询某篇文献已有 chunk 数量。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            sa_text("SELECT COUNT(*) AS count FROM chunks WHERE paper_id = :paper_id"),
            {"paper_id": paper_id},
        )
        row = result.fetchone()

    return int(row._mapping["count"]) if row else 0


async def build_chunks_for_single_paper(
    paper: dict[str, Any],
    chunker: SectionBasedChunker,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    对单篇文献构建 chunks。

    参数：
        paper:
            papers 表中的一条记录。

        chunker:
            SectionBasedChunker 实例。

        overwrite:
            是否覆盖已有 chunks。

    返回：
        处理结果摘要。
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
            "message": "该文献已有 chunks，跳过。如需重建，请使用 --overwrite。",
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

    # 更新 papers.status
    paper_repo = PaperRepository()
    await paper_repo.update_file_paths(
        paper_id=paper_id,
        status="chunked",
    )

    section_summary = summarize_chunks_by_section(chunks)

    return {
        "paper_id": paper_id,
        "success": True,
        "status": "chunked",
        "message": "chunks 构建成功。",
        "title": title,
        "local_text_path": local_text_path,
        "deleted_count": deleted_count,
        "chunk_count": len(chunks),
        "inserted_chunk_ids": inserted_chunk_ids[:10],
        "inserted_chunk_ids_note": "这里只显示前 10 个 chunk_id。",
        "section_summary": section_summary,
    }


def summarize_chunks_by_section(
    chunks: list[Any],
) -> dict[str, int]:
    """
    按 section_title 统计 chunk 数量。
    """
    summary: dict[str, int] = {}

    for chunk in chunks:
        section_title = chunk.section_title or "Unknown"
        summary[section_title] = summary.get(section_title, 0) + 1

    return summary


async def print_chunk_preview(
    paper_id: int,
    max_chunks: int = 3,
    max_text_chars: int = 500,
) -> None:
    """
    打印某篇文献的前几个 chunk 预览。

    作用：
        方便人工检查 chunk 质量。
    """
    chunk_repo = ChunkRepository()
    chunks = await chunk_repo.list_chunks_by_paper(paper_id)

    if not chunks:
        print("暂无可预览的 chunks。")
        return

    print("\nchunks 预览：")
    for chunk in chunks[:max_chunks]:
        print("-" * 80)
        print(f"chunk_id: {chunk['id']}")
        print(f"chunk_index: {chunk['chunk_index']}")
        print(f"section_title: {chunk['section_title']}")
        print(f"page_start: {chunk['page_start']}")
        print(f"page_end: {chunk['page_end']}")
        print(f"token_count: {chunk['token_count']}")
        print("text preview:")
        text = chunk["text"] or ""
        try:
            print(text[:max_text_chars])
        except UnicodeEncodeError:
            print(text[:max_text_chars].encode("ascii", errors="replace").decode("ascii"))
        if len(text) > max_text_chars:
            print("...")


async def main() -> None:
    """
    主函数。
    """
    args = parse_args()

    print("=" * 80)
    print("开始从已解析 JSON 构建 chunks")
    print("=" * 80)
    print(f"limit: {args.limit}")
    print(f"max_chars: {args.max_chars}")
    print(f"overlap_chars: {args.overlap_chars}")
    print(f"min_chars: {args.min_chars}")
    print(f"overwrite: {args.overwrite}")
    print(f"include_chunked: {args.include_chunked}")
    print(f"keep_references: {args.keep_references}")
    print("=" * 80)

    candidates = await list_candidate_papers(
        limit=args.limit,
        include_chunked=args.include_chunked,
    )

    print(f"候选已解析文献数量：{len(candidates)}")

    if not candidates:
        print("没有可切分的已解析文献。")
        return

    print("\n候选文献列表：")
    for index, paper in enumerate(candidates, start=1):
        print("-" * 80)
        print(f"[{index}] paper_id={paper['id']}")
        print(f"    title: {paper['title']}")
        print(f"    status: {paper['status']}")
        print(f"    local_text_path: {paper['local_text_path']}")

    chunker = SectionBasedChunker(
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
        min_chars=args.min_chars,
        skip_reference_sections=not args.keep_references,
    )

    results: list[dict[str, Any]] = []

    print("\n开始构建 chunks…")
    for paper in candidates:
        try:
            result = await build_chunks_for_single_paper(
                paper=paper,
                chunker=chunker,
                overwrite=args.overwrite,
            )
        except Exception as exc:
            result = {
                "paper_id": paper.get("id"),
                "success": False,
                "status": "failed",
                "message": str(exc),
            }

        results.append(result)

        print("-" * 80)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if result.get("success") and result.get("status") == "chunked":
            await print_chunk_preview(
                paper_id=int(result["paper_id"]),
                max_chunks=2,
                max_text_chars=600,
            )

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

    print("=" * 80)
    print("汇总：")
    print(f"  success_count: {success_count}")
    print(f"  skipped_count: {skipped_count}")
    print(f"  failed_count: {failed_count}")

    print("\n处理完成：论文正文 chunks 已写入数据库。")


if __name__ == "__main__":
    asyncio.run(main())