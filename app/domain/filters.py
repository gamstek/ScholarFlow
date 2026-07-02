"""
filters.py

领域过滤器 Domain Filter。

作用：
1. 判断一篇文献是否与目标领域相关；
2. 计算领域相关性评分 domain_score；
3. 给出保留 / 丢弃建议；
4. 为后续采集模块提供过滤能力。

核心思想：
不是只看一个关键词，而是综合判断：
- 来源 Source；
- 成分类别 Component；
- 结构分析 Structural Analysis；
- 质谱方法 Mass Spectrometry；
- 组学方向 Omics；
- 强相关关键词 Strong Positive；
- 排除关键词 Exclusion。

当前是规则过滤 Rule-based Filter。
优点：可解释、可控、适合 V0。
后续可以升级为：
- 机器学习分类器 Machine Learning Classifier；
- LLM Judge；
- embedding 相似度过滤。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.domain.keywords import (
    EXCLUSION_KEYWORDS,
    FOOD_COMPONENT_KEYWORDS,
    FOOD_SOURCE_KEYWORDS,
    MASS_SPEC_KEYWORDS,
    OMICS_KEYWORDS,
    STRONG_POSITIVE_KEYWORDS,
    STRUCTURE_ANALYSIS_KEYWORDS,
)


@dataclass
class DomainFilterResult:
    """
    领域过滤结果 Domain Filter Result。

    字段说明：
        keep:
            是否建议保留该文献。

        domain_score:
            领域相关性评分，范围 0~1。

        reason:
            简要说明为什么保留或丢弃。

        matched_food_sources:
            命中的食品来源关键词。

        matched_components:
            命中的食品成分类别关键词。

        matched_structure_terms:
            命中的结构分析关键词。

        matched_ms_terms:
            命中的质谱方法关键词。

        matched_omics_terms:
            命中的组学关键词。

        matched_strong_terms:
            命中的强相关关键词。

        matched_exclusion_terms:
            命中的排除关键词。
    """

    keep: bool
    domain_score: float
    reason: str
    matched_food_sources: list[str]
    matched_components: list[str]
    matched_structure_terms: list[str]
    matched_ms_terms: list[str]
    matched_omics_terms: list[str]
    matched_strong_terms: list[str]
    matched_exclusion_terms: list[str]


def normalize_text(text: Optional[str]) -> str:
    """
    标准化文本。

    参数：
        text:
            输入文本，可以是标题、摘要、关键词等。

    返回：
        标准化后的字符串。

    处理内容：
    1. None 转为空字符串；
    2. 转小写；
    3. 替换换行和多余空格；
    4. 保留英文、数字和常见符号。

    注意：
        这里不做复杂分词，因为当前主要处理英文文献 metadata。
    """
    if not text:
        return ""

    text = text.lower()
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    # 将多个空白字符合并成一个空格
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def keyword_in_text(keyword: str, text: str) -> bool:
    """
    判断关键词是否出现在文本中。

    这里做了一个简单优化：
    - 对于普通短词，如 ms，要求边界匹配；
    - 对于短语，如 lc-ms/ms，直接 substring 匹配。

    为什么要特殊处理短词？
    因为 "ms" 如果直接用 in 判断，可能误匹配到其他单词片段。
    """
    keyword = keyword.lower().strip()

    if not keyword:
        return False

    # 如果是非常短的词，使用词边界匹配
    if len(keyword) <= 3 and keyword.isalnum():
        pattern = rf"\b{re.escape(keyword)}\b"
        return re.search(pattern, text) is not None

    return keyword in text


def find_matched_keywords(text: str, keywords: list[str]) -> list[str]:
    """
    找出文本中命中的关键词。

    参数：
        text:
            已标准化文本。

        keywords:
            关键词列表。

    返回：
        命中的关键词列表，保持原关键词形式。
    """
    matched = []

    for keyword in keywords:
        if keyword_in_text(keyword, text):
            matched.append(keyword)

    return matched


def calculate_group_score(
    matched_keywords: list[str],
    max_effective_matches: int,
) -> float:
    """
    计算某一类关键词的组内得分。

    参数：
        matched_keywords:
            当前类别命中的关键词。

        max_effective_matches:
            最大有效命中数。

    返回：
        0~1 的组内得分。

    例子：
        如果 max_effective_matches = 4：
        - 命中 0 个，得分 0；
        - 命中 1 个，得分 0.25；
        - 命中 2 个，得分 0.5；
        - 命中 4 个及以上，得分 1。
    """
    if max_effective_matches <= 0:
        return 0.0

    score = len(matched_keywords) / max_effective_matches

    return min(score, 1.0)


def calculate_domain_score(
    title: str,
    abstract: Optional[str] = None,
    journal: Optional[str] = None,
    keywords: Optional[list[str]] = None,
) -> DomainFilterResult:
    """
    计算文献的领域相关性评分。

    参数：
        title:
            文献标题。

        abstract:
            文献摘要。

        journal:
            期刊名称，可选。

        keywords:
            文献关键词，可选。

    返回：
        DomainFilterResult。

    评分逻辑：
        domain_score =
            0.20 × 来源得分
          + 0.20 × 成分类别得分
          + 0.20 × 结构分析得分
          + 0.20 × 质谱方法得分
          + 0.10 × 组学方向得分
          + 0.10 × 强相关关键词得分

    目标文献通常同时满足：
    - 研究对象明确；
    - 研究方法是 LC-MS/MS、MALDI 等；
    - 研究目标是结构鉴定、表征、碎片规律。
    """
    keyword_text = " ".join(keywords or [])

    # 标题权重通常比摘要更高，因此标题重复加入一次
    combined_text = " ".join(
        [
            normalize_text(title),
            normalize_text(title),
            normalize_text(abstract),
            normalize_text(journal),
            normalize_text(keyword_text),
        ]
    )

    matched_food_sources = find_matched_keywords(
        combined_text,
        FOOD_SOURCE_KEYWORDS,
    )

    matched_components = find_matched_keywords(
        combined_text,
        FOOD_COMPONENT_KEYWORDS,
    )

    matched_structure_terms = find_matched_keywords(
        combined_text,
        STRUCTURE_ANALYSIS_KEYWORDS,
    )

    matched_ms_terms = find_matched_keywords(
        combined_text,
        MASS_SPEC_KEYWORDS,
    )

    matched_omics_terms = find_matched_keywords(
        combined_text,
        OMICS_KEYWORDS,
    )

    matched_strong_terms = find_matched_keywords(
        combined_text,
        STRONG_POSITIVE_KEYWORDS,
    )

    matched_exclusion_terms = find_matched_keywords(
        combined_text,
        EXCLUSION_KEYWORDS,
    )

    # --------------------------------------------------------
    # 计算各类别分数
    # --------------------------------------------------------
    food_source_score = calculate_group_score(
        matched_food_sources,
        max_effective_matches=3,
    )

    component_score = calculate_group_score(
        matched_components,
        max_effective_matches=3,
    )

    structure_score = calculate_group_score(
        matched_structure_terms,
        max_effective_matches=3,
    )

    ms_score = calculate_group_score(
        matched_ms_terms,
        max_effective_matches=3,
    )

    omics_score = calculate_group_score(
        matched_omics_terms,
        max_effective_matches=2,
    )

    strong_score = calculate_group_score(
        matched_strong_terms,
        max_effective_matches=2,
    )

    domain_score = (
        0.20 * food_source_score
        + 0.20 * component_score
        + 0.20 * structure_score
        + 0.20 * ms_score
        + 0.10 * omics_score
        + 0.10 * strong_score
    )

    # --------------------------------------------------------
    # 排除词惩罚
    # --------------------------------------------------------
    # 如果出现排除词，降低分数。
    # 但不是直接归零，因为有些食品代谢物文献也可能出现 clinical 等词。
    if matched_exclusion_terms:
        domain_score -= 0.20

    domain_score = max(0.0, min(domain_score, 1.0))
    domain_score = round(domain_score, 4)

    # --------------------------------------------------------
    # 判断是否保留
    # --------------------------------------------------------
    keep, reason = make_keep_decision(
        domain_score=domain_score,
        matched_food_sources=matched_food_sources,
        matched_components=matched_components,
        matched_structure_terms=matched_structure_terms,
        matched_ms_terms=matched_ms_terms,
        matched_omics_terms=matched_omics_terms,
        matched_strong_terms=matched_strong_terms,
        matched_exclusion_terms=matched_exclusion_terms,
    )

    return DomainFilterResult(
        keep=keep,
        domain_score=domain_score,
        reason=reason,
        matched_food_sources=matched_food_sources,
        matched_components=matched_components,
        matched_structure_terms=matched_structure_terms,
        matched_ms_terms=matched_ms_terms,
        matched_omics_terms=matched_omics_terms,
        matched_strong_terms=matched_strong_terms,
        matched_exclusion_terms=matched_exclusion_terms,
    )


def make_keep_decision(
    domain_score: float,
    matched_food_sources: list[str],
    matched_components: list[str],
    matched_structure_terms: list[str],
    matched_ms_terms: list[str],
    matched_omics_terms: list[str],
    matched_strong_terms: list[str],
    matched_exclusion_terms: list[str],
) -> tuple[bool, str]:
    """
    根据评分和关键词命中情况，决定是否保留文献。

    规则说明：
    1. 强相关关键词命中较多，并且没有严重排除词，可以保留；
    2. 同时命中“食品/成分”和“质谱/结构分析”，可以保留；
    3. 分数达到阈值，可以保留；
    4. 排除词较多且分数低，则丢弃。
    """

    has_food_or_component = bool(matched_food_sources or matched_components)
    has_structure_or_ms = bool(matched_structure_terms or matched_ms_terms)
    has_strong_signal = len(matched_strong_terms) >= 1
    has_many_exclusions = len(matched_exclusion_terms) >= 2

    # 情况 1：强相关，直接保留
    if has_strong_signal and domain_score >= 0.35 and not has_many_exclusions:
        return True, "命中强相关关键词，且领域评分达到最低要求。"

    # 情况 2：同时具有研究对象和分析方法，保留
    if has_food_or_component and has_structure_or_ms and domain_score >= 0.40:
        return True, "同时命中食品/成分类关键词和结构/质谱分析关键词。"

    # 情况 3：组学方向 + 食品/成分 + 分数足够
    if matched_omics_terms and has_food_or_component and domain_score >= 0.40:
        return True, "命中食品组学/代谢组学方向，并且领域评分达到要求。"

    # 情况 4：总分足够高
    if domain_score >= 0.50 and not has_many_exclusions:
        return True, "领域相关性评分较高。"

    # 情况 5：排除词明显
    if has_many_exclusions:
        return False, "命中多个排除关键词，疑似偏离目标领域方向。"

    return False, "领域相关性不足，暂不进入文献库。"


def should_keep_paper(
    title: str,
    abstract: Optional[str] = None,
    journal: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    min_score: float = 0.40,
) -> bool:
    """
    简化接口：判断文献是否应该保留。

    参数：
        min_score:
            最低领域评分阈值，默认 0.40。

    返回：
        True：建议保留；
        False：建议丢弃。

    注意：
        这个函数只返回布尔值。
        如果需要查看原因和命中关键词，请使用 calculate_domain_score。
    """
    result = calculate_domain_score(
        title=title,
        abstract=abstract,
        journal=journal,
        keywords=keywords,
    )

    return result.keep and result.domain_score >= min_score


def explain_filter_result(result: DomainFilterResult) -> str:
    """
    将过滤结果转换为可读文本。

    用于调试、日志、接口返回。
    """
    lines = [
        f"keep: {result.keep}",
        f"domain_score: {result.domain_score}",
        f"reason: {result.reason}",
        f"matched_food_sources: {result.matched_food_sources}",
        f"matched_components: {result.matched_components}",
        f"matched_structure_terms: {result.matched_structure_terms}",
        f"matched_ms_terms: {result.matched_ms_terms}",
        f"matched_omics_terms: {result.matched_omics_terms}",
        f"matched_strong_terms: {result.matched_strong_terms}",
        f"matched_exclusion_terms: {result.matched_exclusion_terms}",
    ]

    return "\n".join(lines)


def classify_paper(
    title: str,
    abstract: Optional[str] = None,
    journal: Optional[str] = None,
    keywords: Optional[list[str]] = None,
) -> dict[str, object]:
    """
    面向外部模块的分类接口。

    返回 dict，而不是 dataclass，方便：
    1. FastAPI 返回 JSON；
    2. 写入日志；
    3. 后续和 harvester 模块集成。

    返回字段：
        keep:
            是否保留。

        domain_score:
            领域相关性评分。

        reason:
            判断原因。

        matched_terms:
            各类别命中的关键词。
    """
    result = calculate_domain_score(
        title=title,
        abstract=abstract,
        journal=journal,
        keywords=keywords,
    )

    return {
        "keep": result.keep,
        "domain_score": result.domain_score,
        "reason": result.reason,
        "matched_terms": {
            "food_sources": result.matched_food_sources,
            "components": result.matched_components,
            "structure": result.matched_structure_terms,
            "mass_spec": result.matched_ms_terms,
            "omics": result.matched_omics_terms,
            "strong": result.matched_strong_terms,
            "exclusion": result.matched_exclusion_terms,
        },
    }