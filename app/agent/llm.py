"""
llm.py

LLM 客户端抽象层。

提供统一的 LLM 调用接口，支持：
- Ollama（本地部署）
- 后续可扩展 OpenAI / Azure / Anthropic 等

核心接口：
    LlmClient: 协议基类，定义 chat(messages, tools) -> ChatResponse
    OllamaLlmClient: Ollama /api/chat 的 async 实现，支持 tool-calling
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ============================================================
# 1. 响应模型
# ============================================================


@dataclass
class ChatResponse:
    """
    LLM 聊天响应。

    字段说明：
        content:
            LLM 输出的文本内容（最终回答）。

        finish_reason:
            "stop": LLM 给出最终回答；
            "tool_calls": LLM 请求调用 Tool；
            "length": 达到最大 token 数。

        message:
            完整的 assistant 消息，可直接追加到对话历史。

        tool_calls:
            当 finish_reason == "tool_calls" 时，Tool 调用列表。
            每项包含：{id, name, arguments}
    """

    content: str | None = None
    finish_reason: str = "stop"
    message: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


# ============================================================
# 2. LLM 客户端协议
# ============================================================


class LlmClient:
    """
    LLM 客户端协议（鸭子类型）。

    任何满足此接口的类都可以注入到 Agent 中。

    方法签名：
        async chat(messages, tools=None) -> ChatResponse
    """

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """发送对话消息，返回 LLM 响应。"""
        raise NotImplementedError


# ============================================================
# 3. Ollama 客户端实现
# ============================================================


class OllamaLlmClient(LlmClient):
    """
    Ollama LLM 客户端（async）。

    复用 app/rag/generator.py 的 Ollama /api/chat 调用逻辑，
    但使用 httpx 实现真正的 async HTTP 调用。

    用法：
        client = OllamaLlmClient(model="qwen3:8b")
        response = await client.chat(
            messages=[{"role": "user", "content": "你好"}],
            tools=[...],
        )
    """

    def __init__(
        self,
        model: str = "qwen3:8b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.2,
        num_ctx: int = 4096,
        num_predict: int = 512,
        timeout: float = 120.0,
        think: bool | None = False,
    ) -> None:
        """
        初始化 Ollama 客户端。

        参数：
            model:
                Ollama 模型名，如 qwen3:8b / qwen2.5:7b。

            base_url:
                Ollama 服务地址。

            temperature:
                生成温度。

            num_ctx:
                上下文窗口大小。

            num_predict:
                最大生成 token 数。

            timeout:
                HTTP 请求超时时间（秒）。

            think:
                think 参数。对 qwen3 建议 False。
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.timeout = timeout
        self.think = think

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """
        调用 Ollama /api/chat 接口。

        目前 Ollama 对 tool-calling 支持有限：
        - 如果模型支持 tool-calling，Ollama 会返回 tool_calls；
        - 如果不支持，需要业务层通过文本解析推断 Tool 调用（ReAct 退化）。
        """
        url = f"{self.base_url}/api/chat"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }

        if tools:
            payload["tools"] = tools

        if self.think is not None:
            payload["think"] = self.think

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    "调用 Ollama /api/chat 失败。请检查：\n"
                    "1. Ollama 是否启动；\n"
                    "2. 模型是否存在：ollama list；\n"
                    "3. 模型是否能通过 ollama run 正常回答。\n"
                    f"当前模型：{self.model}\n"
                    f"原始错误：{exc}"
                ) from exc

        return self._parse_response(data)

    def _prepare_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """准备发送给 Ollama 的消息列表。移除不支持的字段。"""
        result = []
        for msg in messages:
            role = msg.get("role", "user")
            prepared: dict[str, Any] = {"role": role, "content": msg.get("content", "")}

            # 传递 tool_call_id（如果存在）
            if "tool_call_id" in msg:
                prepared["tool_call_id"] = msg["tool_call_id"]

            # 传递 tool_calls（多轮对话中需要保留 assistant 的工具调用历史）
            if "tool_calls" in msg:
                prepared["tool_calls"] = msg["tool_calls"]

            result.append(prepared)
        return result

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
        """解析 Ollama 响应。"""
        message = data.get("message", {})
        content = message.get("content", "")

        # Ollama tool-calling 响应
        tool_calls = message.get("tool_calls", [])

        if tool_calls:
            return ChatResponse(
                content=content or None,
                finish_reason="tool_calls",
                message={"role": "assistant", "content": content or "", "tool_calls": tool_calls},
                tool_calls=[
                    {
                        "id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", {}),
                    }
                    for tc in tool_calls
                ],
            )

        # 普通文本响应
        done = data.get("done", True)
        finish_reason = data.get("done_reason", "stop" if done else "length")

        return ChatResponse(
            content=content,
            finish_reason=finish_reason,
            message={"role": "assistant", "content": content or ""},
        )
