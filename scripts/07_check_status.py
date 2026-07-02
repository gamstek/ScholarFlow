"""
check_paper_status.py

查看 papers 表中文献的处理状态。

运行方式：
    python scripts/check_paper_status.py

作用：
1. 查看每篇文献当前 status；
2. 查看 local_pdf_path 是否存在；
3. 查看 local_text_path 是否存在；
4. 判断 PDF 是否已经下载、正文是否已经解析。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


# ============================================================
# 让脚本可以从项目根目录导入 app 模块
# ============================================================

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.storage.database import async_session_factory  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402


async def main() -> None:
    """
    查看 papers 表中的文献状态。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            sa_text("""
                SELECT
                    id,
                    title,
                    year,
                    doi,
                    status,
                    local_pdf_path,
                    local_text_path
                FROM papers
                ORDER BY id ASC;
            """)
        )
        rows = result.fetchall()

    if not rows:
        print("papers 表中暂无文献记录。")
        return

    print("=" * 100)
    print("当前 papers 表处理状态")
    print("=" * 100)

    for row in rows:
        print("-" * 100)
        print(f"id: {row.id}")
        print(f"title: {row.title}")
        print(f"year: {row.year}")
        print(f"doi: {row.doi}")
        print(f"status: {row.status}")
        print(f"local_pdf_path: {row.local_pdf_path}")
        print(f"local_text_path: {row.local_text_path}")

    print("=" * 100)
    print("状态说明：")
    print("metadata_only   = 仅有文献元数据，尚未下载 PDF")
    print("pdf_downloaded  = PDF 已下载，但正文尚未解析")
    print("parsed          = PDF 已解析为文本 JSON")
    print("indexed         = 已完成向量化，可用于检索")


if __name__ == "__main__":
    asyncio.run(main())
