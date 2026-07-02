"""
test_filters.py

领域过滤器测试脚本。

运行方式：
    python scripts/10_test_filters.py

测试目标：
1. 高相关 HMO + LC-MS/MS 文献应该保留；
2. 食品多酚 + 质谱鉴定文献应该保留；
3. 临床癌症治疗文献应该过滤；
4. 普通机器学习论文应该过滤；
5. 食品代谢组学文献应该保留。
"""

from __future__ import annotations

import sys
from pathlib import Path


# ============================================================
# 让脚本可以从项目根目录导入 app 模块
# ============================================================

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.domain.filters import (  # noqa: E402
    calculate_domain_score,
    classify_paper,
    explain_filter_result,
)


def run_single_test(
    title: str,
    abstract: str,
    expected_keep: bool,
) -> None:
    """
    运行单条测试。

    参数：
        title:
            文献标题。

        abstract:
            文献摘要。

        expected_keep:
            预期是否保留。
    """
    result = calculate_domain_score(
        title=title,
        abstract=abstract,
    )

    print("=" * 80)
    print(f"Title: {title}")
    print("-" * 80)
    print(explain_filter_result(result))
    print("-" * 80)
    print(f"Expected keep: {expected_keep}")
    print(f"Actual keep:   {result.keep}")

    if result.keep != expected_keep:
        print("测试结果：不符合预期")
    else:
        print("测试结果：符合预期")


def main() -> None:
    """
    主测试函数。
    """

    test_cases = [
        {
            "title": (
                "Structural characterization of human milk oligosaccharides "
                "by LC-MS/MS"
            ),
            "abstract": (
                "Human milk oligosaccharides were analyzed using liquid "
                "chromatography tandem mass spectrometry. Fragmentation patterns "
                "and diagnostic ions were used for structural elucidation of "
                "isomeric glycans."
            ),
            "expected_keep": True,
        },
        {
            "title": (
                "Identification of polyphenols in tea using high-resolution "
                "mass spectrometry"
            ),
            "abstract": (
                "Food polyphenols and flavonoids in tea samples were characterized "
                "by UHPLC-MS/MS. Fragment ions and neutral losses were used for "
                "compound annotation."
            ),
            "expected_keep": True,
        },
        {
            "title": (
                "Clinical trial of immunotherapy for cancer patients"
            ),
            "abstract": (
                "This randomized controlled trial evaluated therapeutic efficacy "
                "and patient survival after cancer immunotherapy."
            ),
            "expected_keep": False,
        },
        {
            "title": (
                "A deep learning method for image classification"
            ),
            "abstract": (
                "This paper proposes a convolutional neural network for general "
                "image classification benchmarks."
            ),
            "expected_keep": False,
        },
        {
            "title": (
                "Food metabolomics reveals chemical markers in fermented milk"
            ),
            "abstract": (
                "Untargeted metabolomics based on LC-MS was used to profile "
                "metabolites in fermented dairy products. Several small molecules "
                "were annotated according to accurate mass and MS/MS fragments."
            ),
            "expected_keep": True,
        },
    ]

    for case in test_cases:
        run_single_test(
            title=case["title"],
            abstract=case["abstract"],
            expected_keep=case["expected_keep"],
        )

    print("=" * 80)
    print("JSON 风格输出示例：")
    print(
        classify_paper(
            title="LC-MS/MS annotation of oligosaccharides in human milk",
            abstract=(
                "Human milk oligosaccharides were annotated using tandem mass "
                "spectrometry and diagnostic fragment ions."
            ),
        )
    )

    print("\n领域过滤器测试已完成。")


if __name__ == "__main__":
    main()