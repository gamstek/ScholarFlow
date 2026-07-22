"""
llm_factory.py

统一 LLM 创建工厂 —— 所有模块通过此工厂获取 LLM 客户端，
不再直接 import ChatOllama / ChatOpenAI / OllamaGenerator。

提供两层接口：
    create_chat_model()  → LangChain BaseChatModel（Agent / LangChain 工具使用）
    create_raw_llm()     → RawLLMClient（关键词提取 / 综述 / 翻译使用）

用法：
    from app.llm_factory import create_chat_model, create_raw_llm

    # LangChain Agent
    agent = create_chat_model(temperature=0.3)

    # 底层 HTTP 调用
    client = create_raw_llm()
    answer = client.chat(
        system_prompt="你是文献助手",
        user_prompt="帮我找关于CRISPR的论文",
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from app.config import get_config


# ============================================================
# 自定义异常
# ============================================================

class LLMClientError(Exception):
    """
    LLM 客户端调用失败。

    携带 HTTP 状态码和响应体，供上层转换为合适的 HTTP 异常。
    """

    def __init__(self, message: str, status_code: int = 502, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


# ============================================================
# RawLLMClient — 统一 LLM 底层 HTTP 接口
# ============================================================

class RawLLMClient(ABC):
    """
    统一 LLM 客户端接口。

    封装 Ollama /api/chat 和 OpenAI /chat/completions 的差异，
    对上层提供一致的 chat() 方法。
    """

    @abstractmethod
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 512,
        top_p: float = 0.9,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        """
        发送 chat 请求并返回文本回答。

        参数：
            system_prompt: 系统提示。
            user_prompt:   用户提示。
            temperature:   生成温度。
            max_tokens:    最大输出 token 数。
            top_p:         nucleus sampling 参数。
            timeout:       请求超时秒数。
            **kwargs:      后端特定参数透传。

        返回：
            LLM 生成的文本回答。
        """
        ...

    @abstractmethod
    async def achat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 512,
        top_p: float = 0.9,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        """chat() 的异步版本。"""
        ...


# ============================================================
# OllamaRawClient
# ============================================================

class OllamaRawClient(RawLLMClient):
    """
    Ollama /api/chat 客户端（同步 + 异步）。

    支持 think / keep_alive / num_ctx 等 Ollama 特有参数，
    通过 **kwargs 透传。
    """

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 512,
        top_p: float = 0.9,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        """同步发送 Ollama /api/chat 请求。"""
        payload = self._build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            **kwargs,
        )

        try:
            with httpx.Client(timeout=float(timeout)) as client:
                resp = client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                return _extract_ollama_answer(data)
        except httpx.HTTPError as exc:
            status_code = 502
            body = ""
            if hasattr(exc, 'response') and exc.response is not None:
                status_code = exc.response.status_code
                try:
                    body = exc.response.text[:500]
                except Exception:
                    pass
            raise LLMClientError(
                f"调用 Ollama /api/chat 失败。请检查：\n"
                f"1. Ollama 是否启动；\n"
                f"2. 模型是否存在：ollama list；\n"
                f"当前模型：{self.model}\n"
                f"原始错误：{exc}",
                status_code=status_code,
                response_body=body,
            ) from exc

    async def achat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 512,
        top_p: float = 0.9,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        """异步发送 Ollama /api/chat 请求。"""
        payload = self._build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            **kwargs,
        )

        try:
            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                return _extract_ollama_answer(data)
        except httpx.HTTPError as exc:
            status_code = 502
            body = ""
            if hasattr(exc, 'response') and exc.response is not None:
                status_code = exc.response.status_code
                try:
                    body = exc.response.text[:500]
                except Exception:
                    pass
            raise LLMClientError(
                f"调用 Ollama /api/chat 失败。请检查：\n"
                f"1. Ollama 是否启动；\n"
                f"2. 模型是否存在：ollama list；\n"
                f"当前模型：{self.model}\n"
                f"原始错误：{exc}",
                status_code=status_code,
                response_body=body,
            ) from exc

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        top_p: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """构建 Ollama /api/chat 请求体。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "num_predict": max_tokens,
            },
        }

        # 透传 Ollama 特有参数
        if "num_ctx" in kwargs:
            payload["options"]["num_ctx"] = kwargs["num_ctx"]
        if "keep_alive" in kwargs:
            payload["keep_alive"] = kwargs["keep_alive"]
        if "think" in kwargs and kwargs["think"] is not None:
            payload["think"] = kwargs["think"]

        return payload


def _extract_ollama_answer(data: dict) -> str:
    """从 Ollama /api/chat 返回中提取文本回答。"""
    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    # 兼容 /api/generate 风格
    response = data.get("response")
    if isinstance(response, str) and response.strip():
        return response.strip()
    return ""


# ============================================================
# OpenAIRawClient
# ============================================================

class OpenAIRawClient(RawLLMClient):
    """
    OpenAI 兼容 /chat/completions 客户端（DeepSeek / OpenAI / Qwen 等）。

    支持同步和异步调用。
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 512,
        top_p: float = 0.9,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        """同步发送 OpenAI 兼容 /chat/completions 请求。"""
        payload = self._build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            **kwargs,
        )

        try:
            with httpx.Client(timeout=float(timeout)) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return _extract_openai_answer(data)
        except httpx.HTTPError as exc:
            status_code = 502
            body = ""
            if hasattr(exc, 'response') and exc.response is not None:
                status_code = exc.response.status_code
                try:
                    body = exc.response.text[:500]
                except Exception:
                    pass
            raise LLMClientError(
                f"调用云端 API 失败。\n"
                f"base_url: {self.base_url}\n"
                f"model: {self.model}\n"
                f"原始错误：{exc}",
                status_code=status_code,
                response_body=body,
            ) from exc

    async def achat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 512,
        top_p: float = 0.9,
        timeout: int = 120,
        **kwargs: Any,
    ) -> str:
        """异步发送 OpenAI 兼容 /chat/completions 请求。"""
        payload = self._build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            **kwargs,
        )

        try:
            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return _extract_openai_answer(data)
        except httpx.HTTPError as exc:
            status_code = 502
            body = ""
            if hasattr(exc, 'response') and exc.response is not None:
                status_code = exc.response.status_code
                try:
                    body = exc.response.text[:500]
                except Exception:
                    pass
            raise LLMClientError(
                f"调用云端 API 失败。\n"
                f"base_url: {self.base_url}\n"
                f"model: {self.model}\n"
                f"原始错误：{exc}",
                status_code=status_code,
                response_body=body,
            ) from exc

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        top_p: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """构建 OpenAI 兼容 /chat/completions 请求体。"""
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }


def _extract_openai_answer(data: dict) -> str:
    """从 OpenAI 兼容 /chat/completions 返回中提取文本回答。"""
    choices = data.get("choices")
    if isinstance(choices, list) and len(choices) > 0:
        message = choices[0].get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


# ============================================================
# 工厂函数
# ============================================================

def create_chat_model(
    temperature: Optional[float] = None,
    num_ctx: Optional[int] = None,
    max_tokens: Optional[int] = None,
    **kwargs: Any,
) -> Any:
    """
    创建 LangChain 兼容的 ChatModel（BaseChatModel）。

    根据 AppConfig.llm_backend 自动选择：
    - ollama   → ChatOllama
    - deepseek / openai / qwen → ChatOpenAI

    参数：
        temperature: 生成温度（None 则使用配置默认值）。
        num_ctx:     上下文窗口大小（仅 Ollama）。
        max_tokens:  最大输出 token 数。
        **kwargs:    透传给 ChatOllama / ChatOpenAI 的其他参数。

    返回：
        LangChain BaseChatModel 实例。

    用法：
        agent = create_chat_model(temperature=0.3)
        result = agent.invoke([HumanMessage(content="你好")])
    """
    cfg = get_config()

    temp = temperature if temperature is not None else cfg.default_temperature
    ctx = num_ctx if num_ctx is not None else cfg.default_num_ctx
    tokens = max_tokens if max_tokens is not None else cfg.default_num_predict

    if cfg.llm_backend == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=cfg.ollama_model,
            base_url=cfg.ollama_base_url,
            temperature=temp,
            num_ctx=ctx,
            **kwargs,
        )
    else:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=cfg.cloud_model,
            base_url=cfg.cloud_api_base,
            api_key=cfg.cloud_api_key,
            temperature=temp,
            max_tokens=tokens,
            **kwargs,
        )


def create_raw_llm(
    force_no_think_prefix: bool = True,
) -> RawLLMClient:
    """
    创建底层 RawLLMClient（用于关键词提取 / 综述 / 翻译等）。

    根据 AppConfig.llm_backend 自动选择：
    - ollama   → OllamaRawClient
    - 其他     → OpenAIRawClient

    参数：
        force_no_think_prefix: 是否在 user_prompt 前自动加 /no_think（仅 Ollama 生效）。
                               这是为调用方预留的标记，实际前缀由调用方自行添加。

    返回：
        RawLLMClient 实例。

    用法：
        client = create_raw_llm()
        answer = client.chat(
            system_prompt="你是文献助手",
            user_prompt="/no_think\n帮我找关于CRISPR的论文",
        )
    """
    cfg = get_config()

    if cfg.llm_backend == "ollama":
        return OllamaRawClient(
            base_url=cfg.ollama_base_url,
            model=cfg.ollama_model,
        )
    else:
        return OpenAIRawClient(
            base_url=cfg.cloud_api_base,
            api_key=cfg.cloud_api_key,
            model=cfg.cloud_model,
        )


# ============================================================
# 辅助函数
# ============================================================

def build_rag_user_prompt(
    question: str,
    context: str,
    language: str = "zh",
) -> str:
    """
    构造 RAG 问答的用户 prompt（从 generator.py 迁移而来）。
    """
    if language == "en":
        answer_lang_instruction = "Answer in English."
    else:
        answer_lang_instruction = "请用中文回答，必要时保留英文专业术语。"

    return f"""
请基于 Context 回答 Question。

规则：
1. 必须引用来源编号，例如 [S1]、[S2]。
2. 证据不足时说"当前证据不足"，不要编造。
3. 对结构鉴定要谨慎：单个 m/z 不能直接确认结构。
4. 回答尽量简洁，分点说明。
5. {answer_lang_instruction}

Question:
{question}

Context:
{context}

Answer:
""".strip()


def build_system_prompt(language: str = "zh") -> str:
    """
    构造 RAG 问答的 system prompt（从 generator.py 迁移而来）。
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
