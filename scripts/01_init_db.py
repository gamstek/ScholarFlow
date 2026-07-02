"""
init_db.py

数据库初始化脚本。

运行方式：
    python scripts/init_db.py

作用：
1. 创建 data/ 相关目录；
2. 创建数据库表；
3. 创建所有核心表；
4. 插入一条测试任务和一条测试文献，验证数据库是否可用。
"""

from __future__ import annotations

import sys
import asyncio
from pathlib import Path


# ============================================================
# 让脚本可以从项目根目录导入 app 模块
# ============================================================

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.storage.database import DATABASE_URL, init_db  # noqa: E402
from app.storage.repositories import CrawlTaskRepository, PaperRepository  # noqa: E402


async def main() -> None:
    """
    初始化数据库并进行简单测试。
    """
    print("正在初始化数据库...")

    init_db()

    print(f"数据库初始化完成：{DATABASE_URL}")

    # --------------------------------------------------------
    # 1. 创建一条测试采集任务
    # --------------------------------------------------------
    task_repo = CrawlTaskRepository()

    task_id = task_repo.create_task(
        query="human milk oligosaccharides LC-MS/MS structural elucidation",
        task_type="literature",
        sources=["europe_pmc", "crossref"],
        max_results=20,
    )

    print(f"测试采集任务创建成功，task_id = {task_id}")

    # --------------------------------------------------------
    # 2. 插入一条测试文献
    # --------------------------------------------------------
    paper_repo = PaperRepository()

    paper_id = paper_repo.upsert_paper(
        title="Test paper for food structure RAG",
        abstract=(
            "This is a test paper about food component structural analysis "
            "using LC-MS/MS."
        ),
        authors=["Test Author"],
        year=2026,
        journal="Test Journal",
        doi="10.0000/test-food-structure-rag",
        source="manual",
        url="https://example.com/test-paper",
        is_open_access=1,
        domain_score=0.95,
        status="metadata_only",
        crawl_task_id=task_id,
    )

    print(f"测试文献插入成功，paper_id = {paper_id}")

    # --------------------------------------------------------
    # 3. 查询测试文献
    # --------------------------------------------------------
    paper = await paper_repo.get_paper(paper_id)

    if paper is None:
        raise RuntimeError("测试文献查询失败。")

    print("测试文献查询成功：")
    print(f"  title = {paper['title']}")
    print(f"  doi = {paper['doi']}")
    print(f"  domain_score = {paper['domain_score']}")
    print(f"  status = {paper['status']}")

    # --------------------------------------------------------
    # 4. 更新任务状态
    # --------------------------------------------------------
    await task_repo.update_status(
        task_id=task_id,
        status="done",
        success_count=1,
        failed_count=0,
        finish=True,
    )

    task = await task_repo.get_task(task_id)

    if task is None:
        raise RuntimeError("测试任务查询失败。")

    print("测试任务更新成功：")
    print(f"  query = {task['query']}")
    print(f"  status = {task['status']}")
    print(f"  success_count = {task['success_count']}")

    print("\n第一步完成：数据库存储层已经可以正常使用。")


if __name__ == "__main__":
    asyncio.run(main())