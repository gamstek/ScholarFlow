"""
rag_engine.py

本地 RAG 问答引擎。

作用：
1. 接收用户问题；
2. 调用 LocalChunkRetriever 检索相关 chunks；
3. 将 evidence 格式化为 context；
4. 调用 OllamaGenerator 生成回答；
5. 返回 answer + sources。

注意：
    本版本支持 think 参数，用于控制 qwen3:8b 的 thinking 模式。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.rag.generator import OllamaGenerator
from app.rag.embedder import DEFAULT_EMBEDDING_MODEL
from app.rag.retriever import (
    LocalChunkRetriever,
    evidences_to_dicts,
    format_evidence_for_context,
)


@dataclass
class RagAnswer:
    """
    RAG 回答结果。

    字段说明：
        question:
            用户问题。

        answer:
            大模型生成的回答。

        sources:
            引用来源列表。

        context:
            实际送入模型的上下文。

        model:
            使用的 Ollama 模型名称。
    """

    question: str
    answer: str
    sources: list[dict[str, Any]]
    context: str
    model: str


class LocalRagEngine:
    """
    本地 RAG 引擎。

    使用：
        engine = LocalRagEngine(...)
        result = engine.ask("你的问题")
    """

    def __init__(
        self,
        embedding_model_name: str = DEFAULT_EMBEDDING_MODEL,
        embedding_device: str | None = None,
        ollama_model: str = "qwen3:8b",
        ollama_base_url: str = "http://localhost:11434",
        temperature: float = 0.2,
        num_ctx: int = 4096,
        num_predict: int = 512,
        timeout: int = 900,
        think: Optional[bool] = False,
        keep_alive: str = "30m",
    ) -> None:
        """
        初始化 RAG 引擎。

        参数：
            embedding_model_name:
                embedding 模型名称或本地路径。

            embedding_device:
                embedding 设备，例如 cpu / cuda / None。

            ollama_model:
                Ollama 生成模型，例如 qwen3:8b。

            ollama_base_url:
                Ollama 服务地址。

            temperature:
                生成温度。

            num_ctx:
                Ollama 上下文窗口大小。

            num_predict:
                最大输出 token 数。

            timeout:
                Ollama HTTP 请求超时时间，单位秒。

            think:
                Qwen3 thinking 控制。
                False：关闭 thinking；
                True：开启 thinking；
                None：不发送 think 字段。

            keep_alive:
                Ollama 模型在内存/显存中保留时间。
        """

        # ----------------------------------------------------
        # 1. 初始化本地检索器
        # ----------------------------------------------------
        self.retriever = LocalChunkRetriever(
            model_name=embedding_model_name,
            device=embedding_device,
        )

        # ----------------------------------------------------
        # 2. 初始化本地生成器
        # ----------------------------------------------------
        self.generator = OllamaGenerator(
            model=ollama_model,
            base_url=ollama_base_url,
            timeout=timeout,
            temperature=temperature,
            num_ctx=num_ctx,
            num_predict=num_predict,
            think=think,
            keep_alive=keep_alive,
            force_no_think_prefix=True,
            debug=True,
        )

    async def ask(
        self,
        question: str,
        top_k: int = 3,
        min_score: Optional[float] = None,
        section_filter: Optional[list[str]] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        max_chars_per_evidence: int = 800,
        language: str = "zh",
        generate: bool = True,
    ) -> RagAnswer:
        """
        执行一次 RAG 问答。

        参数：
            question:
                用户问题。

            top_k:
                检索前 k 个 chunks。

            min_score:
                最低相似度分数，可选。

            section_filter:
                章节过滤，可选。

            year_from:
                起始年份过滤，可选。

            year_to:
                结束年份过滤，可选。

            max_chars_per_evidence:
                每条 evidence 放入 prompt 的最大字符数。

            language:
                zh / en。

            generate:
                是否调用 Ollama 生成回答。
                False 表示只返回检索证据。
        """

        # ----------------------------------------------------
        # 1. 检索相关 chunks
        # ----------------------------------------------------
        evidences = await self.retriever.retrieve(
            query=question,
            top_k=top_k,
            min_score=min_score,
            section_filter=section_filter,
            year_from=year_from,
            year_to=year_to,
        )

        # ----------------------------------------------------
        # 2. 格式化为 RAG context
        # ----------------------------------------------------
        context = format_evidence_for_context(
            evidences=evidences,
            max_chars_per_evidence=max_chars_per_evidence,
        )

        sources = evidences_to_dicts(evidences)

        # ----------------------------------------------------
        # 3. 没有证据时直接返回
        # ----------------------------------------------------
        if not evidences:
            return RagAnswer(
                question=question,
                answer="当前本地文献库中没有检索到足够相关的证据。",
                sources=[],
                context="",
                model=self.generator.model,
            )

        # ----------------------------------------------------
        # 4. 只检索，不生成
        # ----------------------------------------------------
        if not generate:
            return RagAnswer(
                question=question,
                answer="已完成检索，但未调用生成模型。请查看 sources。",
                sources=sources,
                context=context,
                model=self.generator.model,
            )

        # ----------------------------------------------------
        # 5. 调用 Ollama 生成回答
        # ----------------------------------------------------
        generation_result = self.generator.generate_answer(
            question=question,
            context=context,
            language=language,
        )

        answer = generation_result.answer

        # 防御：如果模型调用成功但返回空内容
        if not answer:
            answer = (
                "模型调用成功，但返回内容为空。"
                "建议尝试：1）将 think_mode 设为 off；"
                "2）减少 top_k；3）减少 max_chars_per_evidence；"
                "4）改用 qwen2.5:7b 等非 thinking 模型。"
            )

        return RagAnswer(
            question=question,
            answer=answer,
            sources=sources,
            context=context,
            model=generation_result.model,
        )