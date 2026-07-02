"""
generator.py

本地大模型生成模块 Generator。

当前版本：
1. 使用 Ollama /api/chat，而不是 /api/generate；
2. 适配 qwen3:8b 的 thinking 行为；
3. 默认关闭 thinking；
4. 从 message.content 提取最终回答；
5. 用于科研文献 RAG 问答。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass
class GenerationResult:
    """
    生成结果。

    字段说明：
        answer:
            大模型最终回答。

        model:
            使用的模型名。

        prompt:
            拼接后的用户 prompt，主要用于调试。

        raw_response:
            Ollama 原始返回。
    """

    answer: str
    model: str
    prompt: str
    raw_response: dict


class OllamaGenerator:
    """
    Ollama 本地生成器。

    重点：
        qwen3:8b 属于 thinking 模型。
        对 RAG 来说，建议关闭 thinking，
        否则可能出现 response/message.content 为空、生成很慢等问题。
    """

    def __init__(
        self,
        model: str = "qwen3:8b",
        base_url: str = "http://localhost:11434",
        timeout: int = 900,
        temperature: float = 0.2,
        top_p: float = 0.9,
        num_ctx: int = 4096,
        num_predict: int = 512,
        think: Optional[bool] = False,
        keep_alive: str = "30m",
        force_no_think_prefix: bool = True,
        debug: bool = True,
    ) -> None:
        """
        初始化 Ollama 生成器。

        参数：
            model:
                Ollama 模型名称，例如 qwen3:8b。

            base_url:
                Ollama 服务地址。

            timeout:
                HTTP 请求超时时间，单位秒。

            temperature:
                生成温度。RAG 建议 0.1~0.3。

            top_p:
                nucleus sampling 参数。

            num_ctx:
                上下文窗口大小。本地 8B 模型建议 2048~4096 起步。

            num_predict:
                最大输出 token 数。

            think:
                是否启用 thinking。
                对 qwen3:8b 做 RAG，默认 False。

            keep_alive:
                模型在内存/显存中保留时间。

            force_no_think_prefix:
                是否在用户消息前加 /no_think。

            debug:
                当回答为空时是否打印 raw_response 摘要。
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.think = think
        self.keep_alive = keep_alive
        self.force_no_think_prefix = force_no_think_prefix
        self.debug = debug

    def generate_answer(
        self,
        question: str,
        context: str,
        language: str = "zh",
    ) -> GenerationResult:
        """
        基于检索上下文生成 RAG 回答。
        """
        user_prompt = build_rag_user_prompt(
            question=question,
            context=context,
            language=language,
        )

        if self.force_no_think_prefix:
            user_prompt = "/no_think\n" + user_prompt

        system_prompt = build_system_prompt(language=language)

        raw_response = self._call_ollama_chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        answer = extract_chat_answer(raw_response)

        if not answer and self.debug:
            print("\n[warning] Ollama /api/chat returned an empty message.content. Raw response summary:")
            print(json.dumps(summarize_raw_response(raw_response), ensure_ascii=False, indent=2))

        return GenerationResult(
            answer=answer.strip(),
            model=self.model,
            prompt=user_prompt,
            raw_response=raw_response,
        )

    def _call_ollama_chat(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """
        调用 Ollama /api/chat。

        相比 /api/generate，/api/chat 对 chat/instruct 模型更稳，
        尤其是 qwen3:8b 这种 thinking-capable 模型。
        """
        url = f"{self.base_url}/api/chat"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }

        # think 是顶层字段。
        # 对 qwen3:8b，建议 False。
        if self.think is not None:
            payload["think"] = self.think

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(
            url=url,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)

        except urllib.error.URLError as exc:
            raise RuntimeError(
                "调用 Ollama /api/chat 失败。请检查：\n"
                "1. Ollama 是否启动；\n"
                "2. 模型是否存在：ollama list；\n"
                "3. qwen3:8b 是否能通过 ollama run 正常回答；\n"
                "4. 如果仍然为空，建议改用 qwen2.5:7b 或 qwen2.5:3b。\n"
                f"当前模型：{self.model}\n"
                f"原始错误：{exc}"
            ) from exc


def build_system_prompt(language: str = "zh") -> str:
    """
    构造 system prompt。

    system prompt 尽量短，避免本地模型负担太重。
    """
    if language == "en":
        return (
            "You are a RAG assistant for scientific literature. "
            "Do not output reasoning. Answer only based on the provided context."
        )

    return (
        "你是科研文献 RAG 助手。"
        "不要输出思考过程。"
        "只能基于给定 Context 回答。"
    )


def build_rag_user_prompt(
    question: str,
    context: str,
    language: str = "zh",
) -> str:
    """
    构造用户消息。

    本版本保持短 prompt，避免 qwen3:8b 本地生成过慢。
    """
    if language == "en":
        answer_language_instruction = "Answer in English."
    else:
        answer_language_instruction = "请用中文回答，必要时保留英文专业术语。"

    prompt = f"""
请基于 Context 回答 Question。

规则：
1. 必须引用来源编号，例如 [S1]、[S2]。
2. 证据不足时说“当前证据不足”，不要编造。
3. 对结构鉴定要谨慎：单个 m/z 不能直接确认结构。
4. 回答尽量简洁，分点说明。
5. {answer_language_instruction}

Question:
{question}

Context:
{context}

Answer:
""".strip()

    return prompt


def extract_chat_answer(
    raw_response: dict,
) -> str:
    """
    从 Ollama /api/chat 返回中提取最终回答。

    正常结构：
        {
          "message": {
            "role": "assistant",
            "content": "..."
          }
        }
    """
    message = raw_response.get("message")

    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    # 兼容 generate 风格，虽然当前不用 generate
    response = raw_response.get("response")
    if isinstance(response, str) and response.strip():
        return response.strip()

    return ""


def summarize_raw_response(
    raw_response: dict,
) -> dict:
    """
    生成 raw_response 摘要，避免打印超长内容。
    """
    message = raw_response.get("message")

    if isinstance(message, dict):
        message_summary = {
            "role": message.get("role"),
            "content": truncate_text(message.get("content")),
            "thinking": truncate_text(message.get("thinking")),
        }
    else:
        message_summary = message

    return {
        "model": raw_response.get("model"),
        "created_at": raw_response.get("created_at"),
        "message": message_summary,
        "response": truncate_text(raw_response.get("response")),
        "thinking": truncate_text(raw_response.get("thinking")),
        "done": raw_response.get("done"),
        "done_reason": raw_response.get("done_reason"),
        "total_duration": raw_response.get("total_duration"),
        "load_duration": raw_response.get("load_duration"),
        "prompt_eval_count": raw_response.get("prompt_eval_count"),
        "prompt_eval_duration": raw_response.get("prompt_eval_duration"),
        "eval_count": raw_response.get("eval_count"),
        "eval_duration": raw_response.get("eval_duration"),
    }


def truncate_text(value: object, max_length: int = 300) -> object:
    """
    截断过长字符串，方便调试打印。
    """
    if isinstance(value, str) and len(value) > max_length:
        return value[:max_length] + "...[truncated]"

    return value