"""
agent.py

LangChain Agent — 统一调度 ScholarFlow 的四大功能。

基于 langchain.agents.create_agent（langchain >= 1.0 推荐 API）。
支持多轮对话和上下文记忆：
    - 基于 session_id 维护对话历史
    - 每次调用将历史消息注入 messages 列表
    - 内存存储，重启后清空（V0 阶段够用）
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.tools import ALL_TOOLS


# ============================================================
# 会话持久化路径
# ============================================================

_SESSIONS_FILE = Path(__file__).resolve().parents[2] / "data" / "sessions.json"


# ============================================================
# System Prompt
# ============================================================

_AGENT_SYSTEM_PROMPT = """你是 ScholarFlow 文献工作站助手。你可以帮助用户检索论文、查看论文全文、回答论文相关问题、撰写文献综述。

你可以使用以下工具：
1. search_papers — 检索学术论文，输入关键词或自然语言描述
2. list_library — 查看本地已入库的文献列表
3. view_paper — 查看库中论文的全文内容（需要 paper_id）
4. ask_paper — 对本地文献库进行 RAG 问答
5. write_review — 根据主题撰写文献综述

使用规则：
- 用户想"找论文"、"搜索"、"检索"时，使用 search_papers
- 用户问"库里有什么"、"有哪些论文"、"文献库"时，使用 list_library
- 用户想"看全文"、"读论文"时，先用 list_library 或 search_papers 找到 paper_id，再用 view_paper
- 用户提问论文内容时，使用 ask_paper
- 用户想"写综述"、"总结"时，使用 write_review
- 回答用中文，保留英文专业术语
- 保持简洁，不要过度解释

你可以参考之前的对话历史来理解用户的上下文意图。如果用户说"上面那篇"、"继续找"等指代词，请结合历史消息理解。
"""


# ============================================================
# 会话管理（内存存储）
# ============================================================

class SessionManager:
    """管理 Agent 对话会话，支持多轮上下文记忆 + 文件持久化。"""

    # session_id → { messages, created_at, title }
    _sessions: dict[str, dict[str, Any]] = {}
    _loaded = False

    # 每个会话最多保留的历史消息轮数（防止上下文过长）
    MAX_HISTORY_ROUNDS = 10

    @classmethod
    def _load(cls) -> None:
        """从文件加载会话（仅首次调用时执行）。"""
        if cls._loaded:
            return
        cls._loaded = True
        if not _SESSIONS_FILE.exists():
            return
        try:
            data = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8"))
            for sid, sdata in data.items():
                sdata["messages"] = []  # LangChain 对象不可序列化，从 raw 重建
                cls._sessions[sid] = sdata
        except Exception:
            pass

    @classmethod
    def _persist(cls) -> None:
        """将会话保存到文件。"""
        try:
            _SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            # 仅保存可序列化的字段（raw_messages, title, created_at）
            serializable: dict[str, Any] = {}
            for sid, s in cls._sessions.items():
                serializable[sid] = {
                    "title": s["title"],
                    "created_at": s["created_at"],
                    "raw_messages": s.get("raw_messages", []),
                }
            _SESSIONS_FILE.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def create_session(cls, title: str = "新对话") -> str:
        """创建新会话，返回 session_id。"""
        cls._load()
        session_id = uuid.uuid4().hex[:12]
        cls._sessions[session_id] = {
            "messages": [],          # LangChain Message 对象列表
            "raw_messages": [],      # 原始 dict 列表（供前端回显）
            "created_at": time.time(),
            "title": title,
        }
        cls._persist()
        return session_id

    @classmethod
    def get_or_create_session(cls, session_id: str | None) -> str:
        """获取会话，不存在则创建。"""
        cls._load()
        if session_id and session_id in cls._sessions:
            return session_id
        return cls.create_session()

    @classmethod
    def get_history(cls, session_id: str) -> list:
        """获取会话的 LangChain 消息历史。"""
        cls._load()
        session = cls._sessions.get(session_id)
        if not session:
            return []
        # 只取最近 MAX_HISTORY_ROUNDS * 2 条消息（每轮 human+ai）
        messages = session["messages"]
        max_msgs = cls.MAX_HISTORY_ROUNDS * 2
        if len(messages) > max_msgs:
            messages = messages[-max_msgs:]
        return messages

    @classmethod
    def add_message(cls, session_id: str, role: str, content: str, tool_calls: list | None = None) -> None:
        """向会话追加消息。"""
        cls._load()
        session = cls._sessions.get(session_id)
        if not session:
            return

        # LangChain 消息（供 Agent 上下文）
        if role == "human":
            session["messages"].append(HumanMessage(content=content))
        else:
            session["messages"].append(AIMessage(content=content))

        # 原始消息（供前端回显）
        raw_msg: dict[str, Any] = {"role": role, "content": content}
        if tool_calls:
            raw_msg["tool_calls"] = tool_calls
        session["raw_messages"].append(raw_msg)

        # 第一条用户消息作为会话标题
        if role == "human" and len(session["raw_messages"]) == 1:
            session["title"] = content[:30] + ("..." if len(content) > 30 else "")

        cls._persist()

    @classmethod
    def get_raw_messages(cls, session_id: str) -> list[dict]:
        """获取会话的原始消息列表（供前端回显）。"""
        cls._load()
        session = cls._sessions.get(session_id)
        if not session:
            return []
        return session["raw_messages"]

    @classmethod
    def list_sessions(cls) -> list[dict]:
        """列出所有会话（按创建时间倒序）。"""
        cls._load()
        sessions = []
        for sid, s in cls._sessions.items():
            sessions.append({
                "session_id": sid,
                "title": s["title"],
                "created_at": s["created_at"],
                "message_count": len(s["raw_messages"]),
            })
        sessions.sort(key=lambda x: x["created_at"], reverse=True)
        return sessions

    @classmethod
    def delete_session(cls, session_id: str) -> bool:
        """删除会话。"""
        cls._load()
        if session_id in cls._sessions:
            del cls._sessions[session_id]
            cls._persist()
            return True
        return False

    @classmethod
    def clear_all(cls) -> None:
        """清空所有会话。"""
        cls._load()
        cls._sessions.clear()
        cls._persist()


# ============================================================
# Agent 工厂
# ============================================================

_AGENT_CACHE: dict[str, Any] = {}


def get_agent(
    model: str = "qwen3:8b",
    base_url: str = "http://localhost:11434",
    temperature: float = 0.3,
    num_ctx: int = 4096,
) -> Any:
    """
    获取（或创建）Agent 单例。

    根据 LLM_BACKEND 环境变量自动选择：
    - deepseek → ChatOpenAI (兼容 DeepSeek API)
    - ollama   → ChatOllama (本地)
    """
    llm_backend = os.getenv("LLM_BACKEND", "ollama")

    if llm_backend == "deepseek":
        api_key = os.getenv("CLOUD_API_KEY", "")
        api_base = os.getenv("CLOUD_API_BASE", "https://api.deepseek.com/v1")
        cloud_model = os.getenv("CLOUD_MODEL", "deepseek-chat")
        cache_key = f"deepseek::{cloud_model}::{temperature}"

        if cache_key not in _AGENT_CACHE:
            llm = ChatOpenAI(
                model=cloud_model,
                base_url=api_base,
                api_key=api_key,
                temperature=temperature,
                max_tokens=4096,
            )
            _AGENT_CACHE[cache_key] = create_agent(
                model=llm,
                tools=ALL_TOOLS,
                system_prompt=_AGENT_SYSTEM_PROMPT,
            )
        return _AGENT_CACHE[cache_key]

    # Ollama 本地模式
    cache_key = f"ollama::{model}::{base_url}::{temperature}::{num_ctx}"

    if cache_key not in _AGENT_CACHE:
        llm = ChatOllama(
            model=model,
            base_url=base_url,
            temperature=temperature,
            num_ctx=num_ctx,
        )

        _AGENT_CACHE[cache_key] = create_agent(
            model=llm,
            tools=ALL_TOOLS,
            system_prompt=_AGENT_SYSTEM_PROMPT,
        )

    return _AGENT_CACHE[cache_key]


def run_agent(
    message: str,
    session_id: str | None = None,
    model: str = "qwen3:8b",
    base_url: str = "http://localhost:11434",
    temperature: float = 0.3,
    num_ctx: int = 4096,
) -> dict[str, Any]:
    """
    运行 Agent 对话（支持多轮上下文记忆）。

    参数：
        message: 用户消息。
        session_id: 会话 ID。为 None 则自动创建新会话。
        model: Ollama 模型名称。
        base_url: Ollama 服务地址。
        temperature: 生成温度。
        num_ctx: 上下文窗口大小。

    返回：
        dict，包含：
            - answer: Agent 最终回答
            - tool_calls: 中间步骤（tool 调用记录）
            - session_id: 会话 ID
    """
    # 获取或创建会话
    sid = SessionManager.get_or_create_session(session_id)

    # 记录用户消息
    SessionManager.add_message(sid, "human", message)

    # 获取历史上下文
    chat_history = SessionManager.get_history(sid)

    agent = get_agent(
        model=model,
        base_url=base_url,
        temperature=temperature,
        num_ctx=num_ctx,
    )

    # 构建消息列表：历史 + 当前输入
    messages = list(chat_history) + [HumanMessage(content=message)]

    result = agent.invoke({"messages": messages})

    # 从返回的消息列表中提取结果
    output_messages = result.get("messages", [])
    answer = ""
    tool_calls: list[dict[str, Any]] = []

    for msg in output_messages:
        if isinstance(msg, AIMessage):
            # 检查是否有工具调用
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "tool": tc.get("name", ""),
                        "input": tc.get("args", {}),
                        "output": "",  # 将在后续 ToolMessage 中填充
                    })
            # 最后一条 AIMessage（不含 tool_calls）是最终回答
            if msg.content and not (hasattr(msg, "tool_calls") and msg.tool_calls):
                answer = msg.content
        elif isinstance(msg, ToolMessage):
            # 将 tool 输出关联到最近的 tool_call
            if tool_calls and not tool_calls[-1]["output"]:
                tool_calls[-1]["output"] = str(msg.content)[:500]

    # 兜底：如果没提取到 answer，取最后一条消息
    if not answer:
        for msg in reversed(output_messages):
            if isinstance(msg, AIMessage) and msg.content:
                answer = msg.content
                break

    if not answer:
        answer = "（Agent 未返回有效回答）"

    # 记录 Agent 回复
    SessionManager.add_message(sid, "ai", answer, tool_calls)

    return {
        "answer": answer,
        "tool_calls": tool_calls,
        "session_id": sid,
    }
