"""
test_pubmed_pmc_search.py

综合测试 PubMed 和 Europe PMC 的搜索功能：
- 仅作者
- 仅关键词
- 仅自然语言  
- 作者+关键词
- 作者+自然语言
- 关键词+自然语言
- 三者组合
"""

from __future__ import annotations

import asyncio
import sys
import time
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Optional

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.harvest.literature.europe_pmc_client import EuropePmcClient
from app.harvest.literature.pubmed_client import PubmedClient
from app.harvest.harvester import LiteratureHarvester, SearchReport


@dataclass
class TestResult:
    name: str
    source: str
    status: str = "pending"  # ok | failed | error
    paper_count: int = 0
    error: Optional[str] = None
    elapsed_ms: float = 0.0
    sample: list[str] = field(default_factory=list)


def run_client_test(name: str, source: str, client: Any, query: str, max_results: int = 10, **kwargs) -> TestResult:
    """直接测试客户端（绕过 harvester）。"""
    result = TestResult(name=name, source=source)
    try:
        start = time.time()
        papers = client.search(query=query, max_results=max_results, **kwargs)
        elapsed = (time.time() - start) * 1000
        result.elapsed_ms = elapsed
        result.paper_count = len(papers)
        result.status = "ok" if len(papers) > 0 else "failed"
        for p in papers[:3]:
            authors_str = ", ".join(p.authors[:3]) if p.authors else "(无作者)"
            result.sample.append(f"  {p.title[:80]} | {authors_str} | {p.year}")
    except Exception as e:
        result.status = "error"
        result.error = f"{type(e).__name__}: {str(e)[:200]}"
    return result


async def run_harvester_test(name: str, sources: list[str], query: str, max_results: int = 10, **kwargs) -> TestResult:
    """通过 harvester 测试（完整流程）。"""
    result = TestResult(name=name, source="+".join(sources))
    try:
        harvester = LiteratureHarvester()
        start = time.time()
        report = await harvester.search_only(
            query=query,
            sources=sources,
            max_results=max_results,
            enhance_query=False,
            **kwargs,
        )
        elapsed = (time.time() - start) * 1000
        result.elapsed_ms = elapsed
        result.paper_count = len(report.results)
        result.status = "ok" if len(report.results) > 0 else "failed"
        for r in report.results[:3]:
            authors_str = ", ".join(r.authors[:3]) if r.authors else "(无作者)"
            result.sample.append(f"  {r.title[:80]} | {authors_str} | {r.year}")
        if report.errors:
            if not result.error:
                result.error = ""
            result.error += "; ".join(report.errors)
    except Exception as e:
        result.status = "error"
        result.error = f"{type(e).__name__}: {str(e)[:200]}"
        result.elapsed_ms = (time.time() - start) * 1000 if 'start' in dir() else 0
    return result


def print_results(title: str, results: list[TestResult]):
    print()
    print("=" * 80)
    print(f"  {title}")
    print("=" * 80)
    ok = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "failed")
    errors = sum(1 for r in results if r.status == "error")
    print(f"  总计: {len(results)} | ✅ {ok} | ❌ {failed} | 💥 {errors}")
    print()
    for r in results:
        icon = {"ok": "✅", "failed": "❌", "error": "💥"}[r.status]
        print(f"  {icon} [{r.source:>12}] {r.name:<45} | {r.paper_count:>3}篇 | {r.elapsed_ms:>8.0f}ms")
        if r.error:
            print(f"       错误: {r.error}")
        for s in r.sample:
            print(s)
    print()


async def main():
    print("=" * 80)
    print("  PubMed + Europe PMC 综合搜索测试")
    print("=" * 80)

    pmc = EuropePmcClient(timeout=30, max_retries=2)
    pubmed = PubmedClient(timeout=30, max_retries=2)

    # ================================================================
    # Phase 1: 直接客户端测试（绕过 harvester，排除中间层干扰）
    # ================================================================
    print("\n>>> Phase 1: 直接客户端测试")

    client_tests = []

    # --- 1a. 仅关键词 ---
    client_tests.append(run_client_test(
        "仅关键词", "europe_pmc", pmc, "CRISPR gene editing", 10))
    client_tests.append(run_client_test(
        "仅关键词", "pubmed", pubmed, "CRISPR gene editing", 10))

    # --- 1b. 仅作者 ---
    client_tests.append(run_client_test(
        "仅作者", "europe_pmc", pmc, "", 10, author="Geoffrey Hinton"))
    client_tests.append(run_client_test(
        "仅作者", "pubmed", pubmed, "", 10, author="Geoffrey Hinton"))

    # --- 1c. 仅自然语言 ---
    client_tests.append(run_client_test(
        "仅自然语言", "europe_pmc", pmc,
        "recent advances in CRISPR gene editing for cancer immunotherapy", 10))
    client_tests.append(run_client_test(
        "仅自然语言", "pubmed", pubmed,
        "recent advances in CRISPR gene editing for cancer immunotherapy", 10))

    # --- 1d. 作者 + 关键词 ---
    client_tests.append(run_client_test(
        "作者+关键词", "europe_pmc", pmc, "deep learning", 10, author="Geoffrey Hinton"))
    client_tests.append(run_client_test(
        "作者+关键词", "pubmed", pubmed, "deep learning", 10, author="Geoffrey Hinton"))

    # --- 1e. 作者 + 自然语言 ---
    client_tests.append(run_client_test(
        "作者+自然语言", "europe_pmc", pmc,
        "recent advances in deep learning for computer vision", 10, author="Geoffrey Hinton"))
    client_tests.append(run_client_test(
        "作者+自然语言", "pubmed", pubmed,
        "recent advances in deep learning for computer vision", 10, author="Geoffrey Hinton"))

    print_results("Phase 1: 直接客户端测试结果", client_tests)

    # ================================================================
    # Phase 2: Harvester 完整流程测试
    # ================================================================
    print("\n>>> Phase 2: Harvester 完整流程测试")

    harvester_tests = []

    # --- 2a. 仅关键词 ---
    harvester_tests.append(await run_harvester_test(
        "仅关键词", ["europe_pmc"], "CRISPR gene editing", 10))
    harvester_tests.append(await run_harvester_test(
        "仅关键词", ["pubmed"], "CRISPR gene editing", 10))

    # --- 2b. 仅作者 ---
    harvester_tests.append(await run_harvester_test(
        "仅作者", ["europe_pmc"], "", 10, author="Geoffrey Hinton"))
    harvester_tests.append(await run_harvester_test(
        "仅作者", ["pubmed"], "", 10, author="Geoffrey Hinton"))

    # --- 2c. 仅自然语言 ---
    harvester_tests.append(await run_harvester_test(
        "仅自然语言", ["europe_pmc"],
        "recent advances in CRISPR gene editing for cancer immunotherapy", 10))
    harvester_tests.append(await run_harvester_test(
        "仅自然语言", ["pubmed"],
        "recent advances in CRISPR gene editing for cancer immunotherapy", 10))

    # --- 2d. 作者 + 关键词 ---
    harvester_tests.append(await run_harvester_test(
        "作者+关键词", ["europe_pmc"], "deep learning", 10, author="Geoffrey Hinton"))
    harvester_tests.append(await run_harvester_test(
        "作者+关键词", ["pubmed"], "deep learning", 10, author="Geoffrey Hinton"))

    # --- 2e. 作者 + 自然语言 ---
    harvester_tests.append(await run_harvester_test(
        "作者+自然语言", ["europe_pmc"],
        "recent advances in deep learning", 10, author="Geoffrey Hinton"))
    harvester_tests.append(await run_harvester_test(
        "作者+自然语言", ["pubmed"],
        "recent advances in deep learning", 10, author="Geoffrey Hinton"))

    # --- 2f. 双源同时搜索 (europe_pmc + pubmed) ---
    harvester_tests.append(await run_harvester_test(
        "双源-仅关键词", ["europe_pmc", "pubmed"], "CRISPR gene editing", 10))
    harvester_tests.append(await run_harvester_test(
        "双源-仅作者", ["europe_pmc", "pubmed"], "", 10, author="Geoffrey Hinton"))
    harvester_tests.append(await run_harvester_test(
        "双源-作者+关键词", ["europe_pmc", "pubmed"], "deep learning", 10, author="Geoffrey Hinton"))

    print_results("Phase 2: Harvester 完整流程测试结果", harvester_tests)

    # ================================================================
    # Summary
    # ================================================================
    all_results = client_tests + harvester_tests
    ok = sum(1 for r in all_results if r.status == "ok")
    failed = sum(1 for r in all_results if r.status == "failed")
    errors = sum(1 for r in all_results if r.status == "error")

    print("=" * 80)
    print(f"  总览: {len(all_results)} 测试 | ✅ {ok} | ❌ {failed} | 💥 {errors}")
    print("=" * 80)

    if failed > 0 or errors > 0:
        print("\n  ⚠️ 存在失败测试，需要修复！")
        for r in all_results:
            if r.status in ("failed", "error"):
                print(f"    [{r.source}] {r.name}: {r.error or '返回0条结果'}")
    else:
        print("\n  ✅ 所有测试通过！")


if __name__ == "__main__":
    asyncio.run(main())
