"""
review_service.py

文献综述生成服务。

作用：
1. 接收综述主题；
2. 用 LocalChunkRetriever 检索相关 chunks；
3. 用 OllamaGenerator 生成结构化 Markdown 综述；
4. 返回综述全文 + 引用来源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.rag.generator import OllamaGenerator
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
    ollama_model: str = "qwen3:8b",
    ollama_base_url: str = "http://localhost:11434",
    temperature: float = 0.3,
    num_ctx: int = 8192,
    num_predict: int = 2048,
    timeout: int = 900,
) -> ReviewResult:
    """
    生成文献综述。

    参数：
        topic:
            综述主题。

        top_k:
            检索前 k 个 chunks 作为证据。

        min_score:
            最低相似度分数。

        max_chars_per_evidence:
            每条证据放入 prompt 的最大字符数。

        ollama_model:
            Ollama 生成模型。

        ollama_base_url:
            Ollama 服务地址。

        temperature:
            生成温度，综述建议 0.3~0.5。

        num_ctx:
            上下文窗口大小，综述需要更大窗口。

        num_predict:
            最大输出 token 数。

        timeout:
            HTTP 请求超时秒数。
    """
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
            model=ollama_model,
        )

    # 2. 格式化为 context
    context = format_evidence_for_context(
        evidences=evidences,
        max_chars_per_evidence=max_chars_per_evidence,
    )

    sources = evidences_to_dicts(evidences)

    # 3. 生成综述
    generator = OllamaGenerator(
        model=ollama_model,
        base_url=ollama_base_url,
        timeout=timeout,
        temperature=temperature,
        num_ctx=num_ctx,
        num_predict=num_predict,
        think=False,
        force_no_think_prefix=True,
        debug=True,
    )

    user_prompt = build_review_prompt(topic=topic, context=context)

    system_prompt = (
        "你是科研文献综述写作助手。"
        "不要输出思考过程。"
        "只能基于给定 Context 中的证据撰写综述。"
    )

    raw_response = generator._call_ollama_chat(
        system_prompt=system_prompt,
        user_prompt="/no_think\n" + user_prompt,
    )

    from app.rag.generator import extract_chat_answer
    review = extract_chat_answer(raw_response)

    if not review:
        review = "模型调用成功，但返回内容为空。建议减少 top_k 或改用 qwen2.5:7b 模型。"

    return ReviewResult(
        topic=topic,
        review=review.strip(),
        sources=sources,
        evidence_count=len(evidences),
        model=ollama_model,
    )
