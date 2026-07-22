"""
review_service.py

文献综述生成服务。

作用：
1. 接收综述主题；
2. 用 LocalChunkRetriever 检索相关 chunks；
3. 通过 llm_factory.create_raw_llm() 调用 LLM 生成结构化 Markdown 综述；
4. 返回综述全文 + 引用来源。

LLM 后端由 AppConfig.llm_backend 统一控制（不再硬编码 Ollama）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.rag.retriever import (
    LocalChunkRetriever,
    evidences_to_dicts,
    format_evidence_for_context,
)


@dataclass
class ReviewResult:
    """综述生成结果。"""

    topic: str
    review: str
    sources: list[dict[str, Any]]
    evidence_count: int
    model: str


def build_review_prompt(topic: str, context: str) -> str:
    """构造综述生成的用户 prompt。"""
    return f"""
请基于以下 Context 中的文献证据，撰写一篇关于「{topic}」的结构化文献综述。

要求：
1. 综述应包含：引言、主要研究发现（分主题归纳）、讨论与展望、结论。
2. 每个观点必须引用来源编号，例如 [S1]、[S2]。
3. 证据不足的方面要如实说明，不要编造。
4. 输出 Markdown 格式。
5. 请用中文撰写，保留英文专业术语。

Context:
{context}
""".strip()


async def generate_review(
    topic: str,
    top_k: int = 10,
    min_score: Optional[float] = None,
    max_chars_per_evidence: int = 1000,
    temperature: float = 0.3,
    num_predict: int = 2048,
) -> ReviewResult:
    """
    生成文献综述。

    LLM 后端由 AppConfig.llm_backend 统一控制。

    参数：
        topic: 综述主题。
        top_k: 检索前 k 个 chunks 作为证据。
        min_score: 最低相似度分数。
        max_chars_per_evidence: 每条证据放入 prompt 的最大字符数。
        temperature: 生成温度，综述建议 0.3~0.5。
        num_predict: 最大输出 token 数。
    """
    from app.config import get_config
    from app.llm_factory import create_raw_llm

    cfg = get_config()

    # 1. 检索相关 chunks
    retriever = LocalChunkRetriever()
    evidences = await retriever.retrieve(
        query=topic,
        top_k=top_k,
        min_score=min_score,
    )

    if not evidences:
        return ReviewResult(
            topic=topic,
            review="当前本地文献库中没有检索到与该主题相关的证据。请先通过「文献检索」功能采集并索引文献。",
            sources=[],
            evidence_count=0,
            model=cfg.active_model_name,
        )

    # 2. 格式化为 context
    context = format_evidence_for_context(
        evidences=evidences,
        max_chars_per_evidence=max_chars_per_evidence,
    )

    sources = evidences_to_dicts(evidences)

    # 3. 生成综述
    client = create_raw_llm()
    user_prompt = build_review_prompt(topic=topic, context=context)
    system_prompt = (
        "你是科研文献综述写作助手。"
        "不要输出思考过程。"
        "只能基于给定 Context 中的证据撰写综述。"
    )

    try:
        review = client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=num_predict,
        )
    except Exception as exc:
        review = f"LLM 调用失败：{exc}"

    if not review:
        review = "模型调用成功，但返回内容为空。建议减少 top_k 或调整生成参数。"

    return ReviewResult(
        topic=topic,
        review=review.strip(),
        sources=sources,
        evidence_count=len(evidences),
        model=cfg.active_model_name,
    )
