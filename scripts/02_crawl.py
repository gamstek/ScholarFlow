"""
crawl_literature.py

通用文献采集脚本。

运行方式示例：

    python scripts/crawl_literature.py

或者指定 query：

    python scripts/crawl_literature.py --query "magnesium-based materials" --max-results 10

作用：
1. 调用公开来源搜索文献；
2. 使用可配置过滤规则筛选候选文献；
3. 将保留文献写入数据库；
4. 打印采集报告；
5. 打印当前数据库中的部分文献。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


# ============================================================
# 让脚本可以从项目根目录导入 app 模块
# ============================================================

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.harvest.harvester import (  # noqa: E402
    LiteratureHarvester,
    report_to_dict,
)
from app.storage.repositories import PaperRepository  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="采集文献 metadata，并写入数据库。"
    )

    parser.add_argument(
        "--query",
        type=str,
        default="human milk oligosaccharides LC-MS/MS structural elucidation",
        help="检索主题。",
    )

    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="最大检索数量。",
    )

    parser.add_argument(
        "--min-domain-score",
        type=float,
        default=0.40,
        help="最低领域相关性评分。",
    )

    parser.add_argument(
        "--no-enhance-query",
        action="store_true",
        help="不自动增强检索词。",
    )

    return parser.parse_args()


async def main() -> None:
    """
    主函数。
    """
    args = parse_args()

    print("=" * 80)
    print("开始采集文献 metadata")
    print("=" * 80)
    print(f"query: {args.query}")
    print(f"max_results: {args.max_results}")
    print(f"min_domain_score: {args.min_domain_score}")
    print(f"enhance_query: {not args.no_enhance_query}")
    print("=" * 80)

    harvester = LiteratureHarvester(
        min_domain_score=args.min_domain_score,
    )

    report = await harvester.crawl_from_europe_pmc(
        query=args.query,
        max_results=args.max_results,
        enhance_query=not args.no_enhance_query,
    )

    report_dict = report_to_dict(report)

    print("\n采集报告：")
    print(json.dumps(report_dict, ensure_ascii=False, indent=2))

    print("\n数据库中最新文献：")
    paper_repo = PaperRepository()
    papers = await paper_repo.list_papers(
        limit=10,
        offset=0,
        min_domain_score=args.min_domain_score,
    )

    for index, paper in enumerate(papers, start=1):
        print("-" * 80)
        print(f"[{index}] {paper['title']}")
        print(f"    year: {paper['year']}")
        print(f"    journal: {paper['journal']}")
        print(f"    doi: {paper['doi']}")
        print(f"    pmid: {paper['pmid']}")
        print(f"    pmcid: {paper['pmcid']}")
        print(f"    domain_score: {paper['domain_score']}")
        print(f"    is_open_access: {paper['is_open_access']}")
        print(f"    status: {paper['status']}")

    print("\nEurope PMC 文献 metadata 采集与入库流程已完成。")

if __name__ == "__main__":
    asyncio.run(main())