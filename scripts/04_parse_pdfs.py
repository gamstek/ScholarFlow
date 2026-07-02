"""
parse_downloaded_pdfs.py

批量解析已下载 PDF。

运行方式：
    python scripts/parse_downloaded_pdfs.py

指定数量：
    python scripts/parse_downloaded_pdfs.py --limit 5

覆盖已有解析结果：
    python scripts/parse_downloaded_pdfs.py --limit 5 --overwrite

作用：
1. 从 papers 表中筛选 status = pdf_downloaded 的文献；
2. 读取 local_pdf_path；
3. 使用 PyMuPDF 解析 PDF；
4. 使用 section_parser 粗略识别章节；
5. 保存结构化 JSON 到 data/texts/；
6. 更新 papers.local_text_path 和 status = parsed。
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


from app.document.pdf_parser import PdfParser  # noqa: E402
from app.document.section_parser import (  # noqa: E402
    parse_sections_from_pages,
    sections_to_dicts,
)
from app.storage.file_store import (  # noqa: E402
    get_relative_path,
    get_text_path,
    resolve_project_path,
    save_json,
)
from app.storage.repositories import PaperRepository  # noqa: E402
from app.storage.database import async_session_factory, init_db  # noqa: E402

from sqlalchemy import text as sa_text, bindparam  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="解析已下载 PDF，保存结构化文本 JSON。"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="最多解析多少篇 PDF。",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="如果已有解析文本，是否覆盖。",
    )

    parser.add_argument(
        "--include-parsed",
        action="store_true",
        help="是否把已经 parsed 的文献也纳入候选。",
    )

    return parser.parse_args()


async def list_candidate_papers(
    limit: int,
    include_parsed: bool = False,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    """
    从数据库中筛选待解析 PDF 的文献。

    默认筛选：
        status = 'pdf_downloaded'
        local_pdf_path 不为空

    如果 include_parsed=True：
        也包含 status = 'parsed' 的文献。

    如果 overwrite=False：
        会跳过已经有 local_text_path 的文献。
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


async def parse_single_paper(
    paper: dict[str, Any],
    parser: PdfParser,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    解析单篇文献 PDF。

    参数：
        paper:
            papers 表中的文献记录。

        parser:
            PdfParser 实例。

        overwrite:
            是否覆盖已有解析结果。

    返回：
        解析结果摘要。
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


async def main() -> None:
    """
    主函数。
    """
    args = parse_args()

    print("=" * 80)
    print("开始解析已下载的 PDF 文献正文")
    print("=" * 80)
    print(f"limit: {args.limit}")
    print(f"overwrite: {args.overwrite}")
    print(f"include_parsed: {args.include_parsed}")
    print("=" * 80)

    candidates = await list_candidate_papers(
        limit=args.limit,
        include_parsed=args.include_parsed,
        overwrite=args.overwrite,
    )

    print(f"候选 PDF 文献数量：{len(candidates)}")

    if not candidates:
        print("没有可解析的 PDF。")
        return

    print("\n候选文献：")
    for index, paper in enumerate(candidates, start=1):
        print("-" * 80)
        print(f"[{index}] paper_id={paper['id']}")
        print(f"    title: {paper['title']}")
        print(f"    local_pdf_path: {paper['local_pdf_path']}")
        print(f"    local_text_path: {paper['local_text_path']}")
        print(f"    status: {paper['status']}")

    parser = PdfParser()

    results: list[dict[str, Any]] = []

    print("\n开始解析…")
    for paper in candidates:
        try:
            result = await parse_single_paper(
                paper=paper,
                parser=parser,
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

    print("=" * 80)
    print("汇总：")
    print(f"  success_count: {success_count}")
    print(f"  skipped_count: {skipped_count}")
    print(f"  failed_count: {failed_count}")

    print("\nPDF 正文解析流程已完成。")


if __name__ == "__main__":
    asyncio.run(main())