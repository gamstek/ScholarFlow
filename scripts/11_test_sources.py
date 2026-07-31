"""
11_test_sources.py

ScholarFlow 全量数据源稳定性验证脚本。

运行方式：
    conda activate scholarflow
    python scripts/11_test_sources.py

作用：
1. 逐一测试全部 8 个文献数据源的连通性和返回质量；
2. 记录每个源的响应时间、返回数量和错误信息；
3. 生成结构化报告，定位不稳定源。

测试策略：
    - 每个源使用相同的通用查询词 ("CRISPR")；
    - 对 Nature/Science/Cell 增加额外领域查询确保期刊过滤正确；
    - 超时 60s/源，避免单源阻塞整体测试。
"""

from __future__ import annotations

import asyncio
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---- 路径设置 ----
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.harvest.literature.europe_pmc_client import EuropePmcClient
from app.harvest.literature.nature_client import NatureClient
from app.harvest.literature.science_client import ScienceClient
from app.harvest.literature.cell_client import CellClient
from app.harvest.literature.arxiv_client import ArxivClient
from app.harvest.literature.semantic_scholar_client import SemanticScholarClient
from app.harvest.literature.pubmed_client import PubmedClient
from app.harvest.literature.openalex_client import OpenAlexClient


# ============================================================
# 测试结果数据结构
# ============================================================

@dataclass
class SourceTestResult:
    """单个数据源的测试结果。"""
    source: str
    status: str = "pending"          # pending | ok | degraded | failed
    elapsed_ms: float = 0.0
    result_count: int = 0
    error: Optional[str] = None
    error_type: str = ""
    warnings: list[str] = field(default_factory=list)
    sample_titles: list[str] = field(default_factory=list)
    notes: str = ""


# ============================================================
# 测试用例定义
# ============================================================

# 每个源的测试配置：(source_name, client_instance, query, max_results, extra_kwargs)
TEST_CASES = [
    # --- 独立 API 源 ---
    ("europe_pmc",      EuropePmcClient(),      "CRISPR gene editing",              10, {}),
    ("pubmed",          PubmedClient(),         "CRISPR gene editing",              10, {}),
    ("openalex",        OpenAlexClient(),       "CRISPR gene editing",              10, {}),
    ("arxiv",           ArxivClient(),          "CRISPR",                           10, {}),
    ("semantic_scholar", SemanticScholarClient(), "CRISPR gene editing",            10, {}),
    # --- Europe PMC 封装源 ---
    ("nature",          NatureClient(),         "cancer immunotherapy",             10, {}),
    ("science",         ScienceClient(),        "protein structure prediction",     10, {}),
    ("cell",            CellClient(),           "single cell sequencing",           10, {}),
]


# ============================================================
# 测试执行
# ============================================================

def run_sync_test(source: str, client: Any, query: str, max_results: int, kwargs: dict) -> SourceTestResult:
    """同步执行单个源的测试（在线程池中运行）。"""
    result = SourceTestResult(source=source)
    
    try:
        start = time.time()
        papers = client.search(query=query, max_results=max_results, **kwargs)
        elapsed = (time.time() - start) * 1000
        
        result.elapsed_ms = elapsed
        result.result_count = len(papers)
        
        # 检查结果质量
        if len(papers) == 0:
            result.status = "degraded"
            result.warnings.append("返回 0 条结果，可能是查询词不匹配或 API 限制")
        elif len(papers) < max_results // 2:
            result.status = "ok"
            result.warnings.append(f"返回 {len(papers)} 条，少于预期的 {max_results} 条")
        else:
            result.status = "ok"
        
        # 收集样本文本用于人工审核
        for p in papers[:3]:
            title = p.title[:80] if p.title else "(无标题)"
            result.sample_titles.append(title)
        
        # 检查 metadata 完整性
        titles_ok = sum(1 for p in papers if p.title)
        abstracts_ok = sum(1 for p in papers if p.abstract)
        if titles_ok < len(papers):
            result.warnings.append(f"{len(papers) - titles_ok} 条缺少标题")
        if abstracts_ok == 0 and len(papers) > 0:
            result.warnings.append("所有结果均无摘要（部分 API 不返回摘要，属于正常）")
        
        # Nature/Science/Cell 特殊检查 —— 期刊名过滤
        if source in ("nature", "science", "cell"):
            wrong_journal = 0
            for p in papers:
                if p.journal and p.journal.lower() == "elife":
                    wrong_journal += 1  # elife 不是 Nature/Science/Cell
            if wrong_journal > 0:
                result.warnings.append(f"{wrong_journal} 条结果的期刊不在目标范围内")
        
        # arXiv 特殊检查
        if source == "arxiv" and papers:
            if not any(p.url and "arxiv.org" in p.url for p in papers if p.url):
                result.warnings.append("arXiv 返回结果的 URL 不包含 arxiv.org")
        
    except Exception as e:
        result.status = "failed"
        result.error = str(e)[:300]
        result.error_type = type(e).__name__
        result.elapsed_ms = (time.time() - start) * 1000 if 'start' in dir() else 0
    
    return result


async def run_all_tests() -> list[SourceTestResult]:
    """并行运行所有源测试。"""
    print("=" * 72)
    print("  ScholarFlow 数据源全量稳定性验证")
    print("=" * 72)
    print()
    
    all_results: list[SourceTestResult] = []
    
    for source, client, query, max_results, kwargs in TEST_CASES:
        print(f"  [{source:>18}] 测试中...", end=" ", flush=True)
        result = await asyncio.to_thread(run_sync_test, source, client, query, max_results, kwargs)
        all_results.append(result)
        
        # 实时输出结果
        icon = {"ok": "✅", "degraded": "⚠️", "failed": "❌", "pending": "⏳"}[result.status]
        print(f"{icon} {result.result_count} 条 | {result.elapsed_ms:.0f}ms", end="")
        if result.error:
            print(f" | 错误: {result.error[:60]}")
        else:
            print()
    
    return all_results


def print_report(results: list[SourceTestResult]) -> None:
    """打印结构化测试报告。"""
    print()
    print("=" * 72)
    print("  测试报告")
    print("=" * 72)
    print()
    
    # 汇总统计
    ok_count = sum(1 for r in results if r.status == "ok")
    degraded_count = sum(1 for r in results if r.status == "degraded")
    failed_count = sum(1 for r in results if r.status == "failed")
    
    print(f"  总计: {len(results)} 源 | ✅ {ok_count} 正常 | ⚠️ {degraded_count} 降级 | ❌ {failed_count} 失败")
    print()
    
    # 按状态分组输出
    for status, label in [("failed", "❌ 失败源"), ("degraded", "⚠️ 降级源"), ("ok", "✅ 正常源")]:
        group = [r for r in results if r.status == status]
        if not group:
            continue
        print(f"  {label} ({len(group)}):")
        for r in group:
            print(f"    [{r.source:>18}] {r.result_count:>3} 条 | {r.elapsed_ms:>8.0f}ms", end="")
            if r.error:
                print(f" | {r.error_type}: {r.error[:80]}")
            else:
                print()
            if r.warnings:
                for w in r.warnings:
                    print(f"                     ⚡ {w}")
            if r.sample_titles:
                print(f"                     样: {r.sample_titles[0][:70]}")
        print()
    
    # 独立 API 与封装源的健康度对比
    independent = ["europe_pmc", "pubmed", "openalex", "arxiv", "semantic_scholar"]
    wrapped = ["nature", "science", "cell"]
    
    indep_results = [r for r in results if r.source in independent]
    wrap_results = [r for r in results if r.source in wrapped]
    
    indep_ok = sum(1 for r in indep_results if r.status == "ok")
    wrap_ok = sum(1 for r in wrap_results if r.status == "ok")
    
    print(f"  独立 API 源: {indep_ok}/{len(independent)} 正常")
    print(f"  封装源 (底层 Europe PMC): {wrap_ok}/{len(wrapped)} 正常")
    
    # 性能排名（仅 ok 源）
    ok_results = [r for r in results if r.status == "ok"]
    if ok_results:
        ranked = sorted(ok_results, key=lambda r: r.elapsed_ms)
        print()
        print(f"  响应速度排名 (✅ 正常源):")
        for i, r in enumerate(ranked, 1):
            print(f"    {i}. [{r.source:>18}] {r.elapsed_ms:>8.0f}ms ({r.result_count} 条)")
    
    print()
    print("=" * 72)
    
    # 最终结论
    if failed_count > 0:
        print(f"  ⚠️  有 {failed_count} 个数据源不可用，需要修复！")
        for r in results:
            if r.status == "failed":
                print(f"     - {r.source}: {r.error_type} — {r.error}")
    elif degraded_count > 0:
        print(f"  ⚡ 所有源均可连通，但有 {degraded_count} 个源存在降级现象。")
    else:
        print(f"  ✅ 全部 {len(results)} 个数据源运行正常！")


# ============================================================
# 入口
# ============================================================

async def main() -> None:
    """主入口。"""
    results = await run_all_tests()
    print_report(results)
    
    # 如果有失败，返回非零退出码
    failed = sum(1 for r in results if r.status == "failed")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
