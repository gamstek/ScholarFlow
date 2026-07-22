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

## 工具列表

1. **search_papers** — 检索学术论文，支持按关键词/自然语言/作者名（author 参数）搜索。返回 metadata（标题、作者、DOI、年份、期刊、在库状态等）。
2. **list_library** — 查看本地已入库的文献列表。
3. **view_paper** — 查看库中论文全文（需 paper_id）。
4. **ask_paper** — 对本地文献库进行 RAG 问答。
5. **write_review** — 根据主题撰写文献综述。
6. **web_search** — 网页搜索引擎，补充 API 覆盖不到的来源（个人主页、Google Scholar 等）。
7. **import_paper** — 将论文导入本地文献库（入库/保存）。

## 回复格式要求（非常重要）

### 论文检索结果格式
每次返回论文列表时，必须使用以下 Markdown 表格格式，确保用户能看到完整信息：

```
| # | 标题 | 作者 | 年份 | 期刊 | DOI | 状态 |
|---|------|------|------|------|-----|------|
| 1 | xxx  | xxx  | 2023 | Nature | 10.xxx/xxx | 未入库 |
```

### 快速搜索 vs 深度搜索
- **快速搜索（search_depth=quick）**：只列出标题和年份，回复简洁。用户说"快速找"、"简单搜"、"随便看看"时用此模式。
- **深度搜索（search_depth=deep，默认）**：返回完整 metadata（标题、作者、年份、期刊、DOI、来源），并提供入库建议。用户说"详细"、"深入"、"帮我找论文"时用此模式。

### 核心规则
1. **必须返回 metadata**：每次展示论文，至少包含标题和作者。不能只返回作者名或只说"找到了XX的论文"而不列具体信息。
2. **无法获取的字段留空**：DOI、期刊等缺失时填"无"或留空，不要编造。
3. **搜索后提供入库选项**：每轮论文检索结束后，告诉用户"如需入库某篇，请告诉我要入库的编号或标题"。
4. **已入库的标注**：paper_id 不为空或 in_library=true 的论文标注为"已入库"。
5. **组合搜索**：查作者论文时，同时调用 search_papers(author=...) 和 web_search，整合结果。
6. **回答用中文**，保留英文专业术语。保持结构清晰，不要过度解释。
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
    temperature: float = 0.3,
    num_ctx: int = 4096,
) -> Any:
    """
    获取（或创建）Agent 单例。

    通过 llm_factory.create_chat_model() 统一创建 LLM，
    LLM 后端和模型名由 AppConfig 统一管理（不再通过参数传入）。
    """
    from app.llm_factory import create_chat_model
    from app.config import get_config

    cfg = get_config()

    # 缓存 key：后端 + 温度（模型名由 config 统一管理）
    cache_key = f"{cfg.llm_backend}::{cfg.active_model_name}::{temperature}"

    if cache_key not in _AGENT_CACHE:
        llm = create_chat_model(temperature=temperature, num_ctx=num_ctx)
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
    search_depth: str = "deep",
) -> dict[str, Any]:
    """
    运行 Agent 对话（支持多轮上下文记忆）。

    参数：
        message: 用户消息。
        session_id: 会话 ID。为 None 则自动创建新会话。
        model: （已弃用）LLM 后端和模型由 .env 中 LLM_BACKEND 统一控制，此参数不再生效。
        base_url: （已弃用）同上。
        temperature: 生成温度。
        num_ctx: 上下文窗口大小。
        search_depth: 搜索深度。"quick"=快速（仅标题），"deep"=深度（完整 metadata + 入库建议）。

    返回：
        dict，包含：
            - answer: Agent 最终回答
            - tool_calls: 中间步骤（tool 调用记录）
            - session_id: 会话 ID
    """
    # 获取或创建会话
    sid = SessionManager.get_or_create_session(session_id)

    # 根据搜索深度注入前置指令
    if search_depth == "quick":
        depth_instruction = "[搜索深度：快速] 只需列出标题和年份，回复简洁。\n"
    else:
        depth_instruction = "[搜索深度：深度] 请返回完整 metadata（标题、作者、年份、期刊、DOI），用表格展示，检索结束后主动提供入库选项。\n"

    augmented_message = depth_instruction + message

    # 记录用户消息（原始消息，不含注入指令）
    SessionManager.add_message(sid, "human", message)

    # 获取历史上下文
    chat_history = SessionManager.get_history(sid)

    agent = get_agent(
        temperature=temperature,
        num_ctx=num_ctx,
    )

    # 构建消息列表：历史 + 当前输入（含深度指令）
    messages = list(chat_history) + [HumanMessage(content=augmented_message)]

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
