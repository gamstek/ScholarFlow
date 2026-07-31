"""
filters.py

查询驱动评分器 Query-Driven Scorer。

核心思想：
不再使用固定领域词表硬编码评分，而是基于用户当前查询做语义匹配。
用 BGE-M3 embedding 计算查询与文献标题+摘要的余弦相似度，
相似度越高说明文献与查询越相关，分数越高。

优点：
1. 完全通用 — 任何领域、任何查询都能工作；
2. 无需维护关键词词表；
3. 语义匹配比关键词匹配更准确（能理解同义词、上下文）。

评分流程：
1. 将用户查询向量化；
2. 将每篇文献的 title + abstract 拼接后向量化；
3. 计算余弦相似度（归一化向量内积）；
4. 相似度即为 domain_score，范围 0~1。

注意：
BGE-M3 对短查询和长文本都效果良好，
但文献摘要可能为空，此时退化为只用标题。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from app.rag.embedder import DEFAULT_EMBEDDING_MODEL


@dataclass
class DomainFilterResult:
    """
    领域过滤结果。

    字段说明：
        keep: 是否建议保留该文献。
        domain_score: 领域相关性评分，范围 0~1。
        reason: 简要说明为什么保留或丢弃。
        similarity: 查询与文献的原始余弦相似度。
    """

    keep: bool
    domain_score: float
    reason: str
    similarity: float


# ============================================================
# Embedding 模型单例缓存
# ============================================================

# TextEmbedder 加载很慢（需要加载 BGE-M3 模型），
# 所以用全局单例 + 线程锁保证只加载一次。
_EMBEDDER_LOCK = threading.Lock()
_EMBEDDER_CACHE: dict[str, Any] = {}


def _get_embedder(
    model_name: str,
    device: Optional[str] = None,
) -> Any:
    """
    获取（或创建）TextEmbedder 单例。

    参数：
        model_name: embedding 模型名称或本地路径。
        device: 运行设备，None 表示自动。

    返回：
        TextEmbedder 实例。
    """
    cache_key = f"{model_name}::{device}"

    if cache_key not in _EMBEDDER_CACHE:
        with _EMBEDDER_LOCK:
            if cache_key not in _EMBEDDER_CACHE:
                from app.rag.embedder import TextEmbedder

                _EMBEDDER_CACHE[cache_key] = TextEmbedder(
                    model_name=model_name,
                    device=device,
                )

    return _EMBEDDER_CACHE[cache_key]


# ============================================================
# 查询驱动评分器
# ============================================================

class QueryDrivenScorer:
    """
    查询驱动评分器。

    使用 embedding 语义相似度对文献进行评分。
    评分流程：
        1. 向量化用户查询；
        2. 批量向量化文献的 title + abstract；
        3. 计算余弦相似度；
        4. 相似度即为 domain_score。

    使用示例：
        scorer = QueryDrivenScorer()
        scorer.prepare(query="anomalous diffusion")
        result = scorer.score_paper(title="...", abstract="...")
        print(result.domain_score)
    """

    # 默认 embedding 模型（从 embedder 模块统一解析）
    DEFAULT_MODEL = DEFAULT_EMBEDDING_MODEL

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        author_bonus: float = 0.15,
    ) -> None:
        """
        初始化评分器。

        参数：
            model_name: embedding 模型路径，None 使用默认 BGE-M3。
            device: 运行设备，None 自动选择。
            author_bonus: 作者名匹配时的 domain_score 加分（0~1）。
        """
        self.model_name = model_name or self.DEFAULT_MODEL
        self.device = device
        self.author_bonus = author_bonus

        self._query_vec: Optional[np.ndarray] = None
        self._query: Optional[str] = None
        self._target_author: Optional[str] = None

    def prepare(
        self,
        query: str,
        author: Optional[str] = None,
    ) -> None:
        """
        预处理：向量化用户查询，并记录目标作者用于后续匹配加分。

        在批量评分前调用一次，避免每篇文献都重复向量化查询。

        参数：
            query: 用户检索词。
            author: 目标作者名（可选），用于匹配加分。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        embedder = _get_embedder(
            model_name=self.model_name,
            device=self.device,
        )

        self._query = query.strip()
        self._query_vec = embedder.encode_query(self._query)
        self._target_author = author.strip() if author and author.strip() else None

    def score_paper(
        self,
        title: str,
        abstract: Optional[str] = None,
        authors: Optional[list[str]] = None,
        author_affiliations: Optional[list[dict]] = None,
    ) -> DomainFilterResult:
        """
        对单篇文献评分。

        参数：
            title: 文献标题。
            abstract: 文献摘要，可选。
            authors: 作者名列表，用于作者匹配加分，可选。
            author_affiliations: 作者机构列表，用于机构匹配加分，可选。

        返回：
            DomainFilterResult。

        注意：
            调用前必须先调用 prepare(query)。
        """
        if self._query_vec is None:
            raise RuntimeError("请先调用 prepare(query) 预处理查询。")

        # 拼接文献文本：标题 + 摘要
        paper_text = self._build_paper_text(title, abstract)

        if not paper_text.strip():
            return DomainFilterResult(
                keep=False,
                domain_score=0.0,
                reason="文献文本为空，无法评分。",
                similarity=0.0,
            )

        # 向量化文献
        embedder = _get_embedder(
            model_name=self.model_name,
            device=self.device,
        )

        paper_vec = embedder.encode_query(paper_text)

        # 计算余弦相似度（向量已 L2 归一化，内积即 cosine similarity）
        similarity = float(np.dot(self._query_vec[0], paper_vec[0]))

        # 相似度通常在 0~1 之间（归一化向量），
        # 但也可能出现负值，截断到 [0, 1]
        similarity = max(0.0, min(similarity, 1.0))

        # ---- 作者/机构匹配加分 ----
        bonus = 0.0
        bonus_reasons: list[str] = []

        if self._target_author:
            from app.agent.name_utils import match_author
            if match_author(self._target_author, authors):
                bonus += self.author_bonus
                bonus_reasons.append("作者匹配")

        domain_score = round(min(similarity + bonus, 1.0), 4)

        # 保留决策：相似度 >= 阈值则保留
        keep = domain_score >= 0.30

        if keep:
            base_reason = f"语义相似度 {similarity:.2f}"
            if bonus_reasons:
                reason = f"{base_reason}，{' + '.join(bonus_reasons)} → {domain_score:.2f}"
            else:
                reason = f"{base_reason}，与查询相关。"
        else:
            reason = f"语义相似度 {domain_score:.2f}，与查询相关性不足。"

        return DomainFilterResult(
            keep=keep,
            domain_score=domain_score,
            reason=reason,
            similarity=similarity,
        )

    def score_papers_batch(
        self,
        papers: list[dict[str, Any]],
    ) -> list[DomainFilterResult]:
        """
        批量评分 — 一次性向量化所有文献，效率更高。

        参数：
            papers: 文献列表，每项需包含 title 字段，abstract 可选。
                    可选字段：authors (list[str])、author_affiliations (list[dict])
                    用于作者/机构匹配加分。

        返回：
            与 papers 等长的 DomainFilterResult 列表。

        注意：
            调用前必须先调用 prepare(query)。
        """
        if self._query_vec is None:
            raise RuntimeError("请先调用 prepare(query) 预处理查询。")

        if not papers:
            return []

        # 构建文献文本列表
        paper_texts = [
            self._build_paper_text(
                p.get("title", ""),
                p.get("abstract"),
            )
            for p in papers
        ]

        # 找出非空文本的索引
        valid_indices = [i for i, t in enumerate(paper_texts) if t.strip()]
        valid_texts = [paper_texts[i] for i in valid_indices]

        results: list[DomainFilterResult] = []

        if valid_texts:
            embedder = _get_embedder(
                model_name=self.model_name,
                device=self.device,
            )

            # 批量向量化
            batch_result = embedder.encode_texts(
                valid_texts,
                batch_size=16,
                show_progress_bar=False,
            )

            # 计算每篇文献与查询的相似度
            query_vec = self._query_vec[0]  # shape: [dim]

            for idx, paper_idx in enumerate(valid_indices):
                paper_vec = batch_result.embeddings[idx]
                similarity = float(np.dot(query_vec, paper_vec))
                similarity = max(0.0, min(similarity, 1.0))

                # ---- 作者/机构匹配加分 ----
                bonus = 0.0
                bonus_reasons: list[str] = []
                paper = papers[paper_idx]

                if self._target_author:
                    from app.agent.name_utils import match_author
                    paper_authors = paper.get("authors")
                    if match_author(self._target_author, paper_authors):
                        bonus += self.author_bonus
                        bonus_reasons.append("作者匹配")

                domain_score = round(min(similarity + bonus, 1.0), 4)

                keep = domain_score >= 0.30
                if keep:
                    base_reason = f"语义相似度 {similarity:.2f}"
                    if bonus_reasons:
                        reason = f"{base_reason}，{' + '.join(bonus_reasons)} → {domain_score:.2f}"
                    else:
                        reason = f"{base_reason}，与查询相关。"
                else:
                    reason = f"语义相似度 {domain_score:.2f}，与查询相关性不足。"

                results.append(DomainFilterResult(
                    keep=keep,
                    domain_score=domain_score,
                    reason=reason,
                    similarity=similarity,
                ))

        # 填充空文本的结果
        final_results: list[DomainFilterResult] = []
        valid_iter = iter(results)

        for i, text in enumerate(paper_texts):
            if text.strip():
                final_results.append(next(valid_iter))
            else:
                final_results.append(DomainFilterResult(
                    keep=False,
                    domain_score=0.0,
                    reason="文献文本为空，无法评分。",
                    similarity=0.0,
                ))

        return final_results

    @staticmethod
    def _build_paper_text(
        title: str,
        abstract: Optional[str],
    ) -> str:
        """
        拼接文献文本。

        标题权重更高，重复一次标题。
        摘要为空时只用标题。
        """
        title = (title or "").strip()
        abstract = (abstract or "").strip()

        if title and abstract:
            return f"{title}. {title}. {abstract}"
        elif title:
            return title
        elif abstract:
            return abstract
        else:
            return ""


# ============================================================
# 兼容接口 — 供 harvester 调用
# ============================================================

# 全局 scorer 实例缓存，按 query 复用
# （同一次采集任务中 query 不变，避免重复向量化）
_SCORER_CACHE: dict[str, QueryDrivenScorer] = {}


def classify_paper(
    title: str,
    abstract: Optional[str] = None,
    journal: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    query: str = "",
    scorer: Optional[QueryDrivenScorer] = None,
) -> dict[str, object]:
    """
    面向外部模块的分类接口（查询驱动版）。

    参数：
        title: 文献标题。
        abstract: 文献摘要。
        journal: 期刊名（保留参数，当前不参与评分）。
        keywords: 关键词列表（保留参数，当前不参与评分）。
        query: 用户检索词，用于语义匹配。
        scorer: 预创建的 QueryDrivenScorer 实例。
            如果传入已 prepare 的 scorer，则直接使用；
            否则需要传 query 来创建。

    返回 dict，字段与旧版保持兼容：
        keep: 是否保留。
        domain_score: 领域相关性评分。
        reason: 判断原因。
        matched_terms: 命中关键词（查询驱动模式下为空）。
    """
    if scorer is None:
        if not query:
            raise ValueError("查询驱动评分需要提供 query 或 scorer。")

        if query not in _SCORER_CACHE:
            _SCORER_CACHE.clear()  # 只缓存最近一次查询
            s = QueryDrivenScorer()
            s.prepare(query)
            _SCORER_CACHE[query] = s

        scorer = _SCORER_CACHE[query]

    result = scorer.score_paper(title=title, abstract=abstract)

    return {
        "keep": result.keep,
        "domain_score": result.domain_score,
        "reason": result.reason,
        "matched_terms": {},
    }


# ============================================================
# 质量评分 — 多因子加权（Phase 2）
# ============================================================

import math
from datetime import datetime


def compute_quality_score(
    domain_score: float,
    citation_count: int | None = None,
    year: int | None = None,
    source: str = "",
) -> float:
    """
    综合质量评分（0~1）。

    加权因子：
        - 语义相关性 (0.40)：BGE-M3 余弦相似度
        - 引用影响力 (0.25)：log 归一化引用数
        - 时效性     (0.20)：近年论文加分
        - 发表类型   (0.15)：来源信誉加成（ArXiv 略低）

    arXiv 特殊处理：引用权重翻倍（0.50），无时效衰减。

    参数：
        domain_score: BGE-M3 语义相似度 (0~1)。
        citation_count: 引用次数。
        year: 发表年份。
        source: 数据来源（用于 arXiv 判断）。

    返回：
        综合质量评分 (0~1)。
    """
    is_arxiv = "arxiv" in source.lower()

    # 引用分数：log 归一化
    if citation_count and citation_count > 0:
        citation_score = min(math.log10(citation_count + 1) / 4.0, 1.0)
    else:
        citation_score = 0.0

    # 时效分数
    current_year = datetime.now().year
    if year and year > 1990:
        age = current_year - year
        if is_arxiv:
            recency_score = 1.0  # arXiv 不衰减
        else:
            recency_score = max(0.0, 1.0 - age / 15.0)
    else:
        recency_score = 0.5

    if is_arxiv:
        # arXiv: 引用权重翻倍，无时效衰减
        return round(
            0.40 * domain_score +
            0.50 * citation_score +
            0.10 * recency_score,
            4,
        )
    else:
        return round(
            0.40 * domain_score +
            0.25 * citation_score +
            0.20 * recency_score +
            0.15 * 0.8,  # 来源基础信誉
            4,
        )
