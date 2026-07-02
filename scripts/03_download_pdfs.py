"""
download_open_access_pdfs.py

开放获取 PDF 批量下载脚本。

运行方式：
    python scripts/download_open_access_pdfs.py

指定数量：
    python scripts/download_open_access_pdfs.py --limit 5

覆盖已有文件：
    python scripts/download_open_access_pdfs.py --limit 5 --overwrite

作用：
1. 从 papers 表中筛选开放获取文献；
2. 尝试下载 PDF；
3. 保存到 data/papers/；
4. 更新 papers.local_pdf_path 和 status。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path


# ============================================================
# 让脚本可以从项目根目录导入 app 模块
# ============================================================

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.harvest.literature.pdf_resolver import OpenAccessPdfResolver  # noqa: E402
from app.storage.repositories import PaperRepository  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="下载开放获取文献 PDF，并写入本地路径。"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="最多尝试下载多少篇文献。",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="如果本地已有 PDF，是否覆盖。",
    )

    parser.add_argument(
        "--include-already-downloaded",
        action="store_true",
        help="是否把已有 local_pdf_path 的文献也纳入候选。",
    )

    return parser.parse_args()


async def main() -> None:
    """
    主函数。
    """
    args = parse_args()

    print("=" * 80)
    print("开始下载开放获取 PDF 文献")
    print("=" * 80)
    print(f"limit: {args.limit}")
    print(f"overwrite: {args.overwrite}")
    print(f"include_already_downloaded: {args.include_already_downloaded}")
    print("=" * 80)

    resolver = OpenAccessPdfResolver()

    candidates = await resolver.list_candidate_papers(
        limit=args.limit,
        include_already_downloaded=args.include_already_downloaded,
    )

    print(f"候选开放获取文献数量：{len(candidates)}")

    if not candidates:
        print("没有可下载候选文献。")
        return

    print("\n候选文献：")
    for index, paper in enumerate(candidates, start=1):
        print("-" * 80)
        print(f"[{index}] paper_id={paper['id']}")
        print(f"    title: {paper['title']}")
        print(f"    doi: {paper['doi']}")
        print(f"    pmcid: {paper['pmcid']}")
        print(f"    pdf_url: {paper['pdf_url']}")
        print(f"    status: {paper['status']}")

    print("\n开始下载…")
    results = await resolver.download_batch(
        limit=args.limit,
        overwrite=args.overwrite,
        include_already_downloaded=args.include_already_downloaded,
    )

    success_count = sum(1 for result in results if result.success and result.status != "skipped")
    skipped_count = sum(1 for result in results if result.status == "skipped")
    failed_count = sum(1 for result in results if not result.success)

    print("\n下载结果：")
    for result in results:
        print("-" * 80)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))

    print("=" * 80)
    print("汇总：")
    print(f"  success_count: {success_count}")
    print(f"  skipped_count: {skipped_count}")
    print(f"  failed_count: {failed_count}")

    print("\n数据库中已下载 PDF 的文献：")
    paper_repo = PaperRepository()
    downloaded_papers = await paper_repo.list_papers(
        limit=10,
        offset=0,
        status="pdf_downloaded",
    )

    for index, paper in enumerate(downloaded_papers, start=1):
        print("-" * 80)
        print(f"[{index}] {paper['title']}")
        print(f"    id: {paper['id']}")
        print(f"    local_pdf_path: {paper['local_pdf_path']}")
        print(f"    status: {paper['status']}")

    print("\n开放获取 PDF 下载流程已完成。")


if __name__ == "__main__":
    asyncio.run(main())