"""
paper_tags.py

论文自动分类标签 — 在检索结果卡片上标记"综述/经典/前沿"等标签。

标签规则：
    📝 综述 (review):
        - PubMed pubtype 含 "Review"
        - 标题含 review / survey / 综述 等关键词
        - 期刊名含 "Annual Review" / "Trends in"

    🏛️ 经典 (classic):
        - 引用 > 100 且发表 > 5 年前
        - 或引用 > 500（超高影响力，不限年份）

    🚀 前沿 (cutting-edge):
        - 发表 <= 2 年 且有引用（已有初步影响力）
        - 不与其他标签冲突（非综述、非经典）
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


# 综述关键词（标题匹配）
_REVIEW_TITLE_PATTERNS = [
    re.compile(r"\breview\b", re.IGNORECASE),
    re.compile(r"\bsurvey\b", re.IGNORECASE),
    re.compile(r"综述", re.IGNORECASE),
    re.compile(r"\bmeta.analysis\b", re.IGNORECASE),
    re.compile(r"\bsystematic review\b", re.IGNORECASE),
]

# 综述期刊关键词
_REVIEW_JOURNAL_PATTERNS = [
    re.compile(r"annual review", re.IGNORECASE),
    re.compile(r"trends in", re.IGNORECASE),
    re.compile(r"nature reviews", re.IGNORECASE),
]


def classify_paper_tags(
    title: str,
    year: Optional[int] = None,
    citation_count: Optional[int] = None,
    pubtype: Optional[list[str]] = None,
    journal: Optional[str] = None,
    source: str = "",
) -> list[str]:
    """
    对论文进行自动标签分类。

    参数：
        title: 论文标题。
        year: 发表年份。
        citation_count: 引用次数。
        pubtype: PubMed pubtype 列表（如 ["Review", "Journal Article"]）。
        journal: 期刊名。
        source: 数据来源。

    返回：
        标签列表，如 ["综述", "经典"] 或 ["前沿"] 或 []。
    """
    tags: list[str] = []

    current_year = datetime.now().year

    # ---- 综述 ----
    is_review = False
    if pubtype:
        for pt in pubtype:
            if "review" in str(pt).lower():
                is_review = True
                break
    if not is_review:
        for pat in _REVIEW_TITLE_PATTERNS:
            if pat.search(title):
                is_review = True
                break
    if not is_review and journal:
        for pat in _REVIEW_JOURNAL_PATTERNS:
            if pat.search(journal):
                is_review = True
                break
    if is_review:
        tags.append("综述")

    # ---- 经典 ----
    is_classic = False
    if citation_count and year:
        if citation_count >= 500:
            is_classic = True
        elif citation_count >= 100 and year <= current_year - 5:
            is_classic = True
    if is_classic:
        tags.append("经典")

    # ---- 前沿 ----
    # 排除 arXiv 预印本（几乎都是新的，标签无意义）
    is_arxiv = "arxiv" in source.lower()
    if not is_arxiv and year and year >= current_year - 2:
        if citation_count and citation_count > 0:
            if not is_review and not is_classic:
                tags.append("前沿")

    return tags
