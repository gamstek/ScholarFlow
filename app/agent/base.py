"""
base.py

Agent 基础设施的核心抽象：Tool、ToolRegistry、Agent、ReActLoop。

设计原则：
- 所有 Tool 必须支持 async run()，因为 Repository 和 API 调用均为 async；
- ToolRegistry 提供注册/查找/列表功能；
- Agent 是 ReAct 模式的抽象基类；
- ReActLoop 封装思考→行动→观察的标准循环。
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ============================================================
# 1. Tool 抽象与结果模型
# ============================================================


class ToolResult(BaseModel):
    """Tool 执行结果。"""

    success: bool
    data: Any | None = None
    error: str | None = None


class Tool(ABC):
    """
    Tool 抽象基类。

    每个 Tool 子类必须定义：
    - name: 唯一标识符
    - description: 给 LLM 看的功能描述
    - input_schema: Pydantic 参数模型
    - run(): 异步执行逻辑

    用法：
        @dataclass
        class SearchParams(BaseModel):
            query: str
            max_results: int = 5

        class SearchTool(Tool):
            name = "search_literature"
            description = "从 Europe PMC 检索文献"
            input_schema = SearchParams

            async def run(self, params: SearchParams) -> ToolResult:
                ...
    """

    name: str
    description: str
    input_schema: type[BaseModel]

    @abstractmethod
    async def run(self, params: BaseModel) -> ToolResult:
        """异步执行 Tool。Repository 和 API 调用均为 async，Tool 必须支持 await。"""
        ...

    def to_openai_schema(self) -> dict[str, Any]:
        """
        转换为 OpenAI tool-calling 兼容的 JSON Schema。

        返回格式：
            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": { ... JSON Schema ... }
                }
            }
        """
        schema = self.input_schema.model_json_schema()
        # 移除 JSON Schema 顶层无关字段
        for key in ("title", "type"):
            schema.pop(key, None)
        # 递归清理所有嵌套的 title
        _clean_titles(schema)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


def _clean_titles(schema: dict[str, Any]) -> None:
    """递归移除 JSON Schema 中所有嵌套的 title 字段。"""
    if isinstance(schema, dict):
        schema.pop("title", None)
        for value in schema.values():
            _clean_titles(value)
    elif isinstance(schema, list):
        for item in schema:
            _clean_titles(item)


# ============================================================
# 2. Tool 注册中心
# ============================================================


class ToolRegistry:
    """
    Tool 注册中心。

    全局单例，所有 Tool 在此注册后通过名称查找调用。

    用法：
        registry = ToolRegistry()
        registry.register(SearchTool())
        tool = registry.get("search_literature")
        result = await tool.run(params)
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个 Tool。同名 Tool 会覆盖旧值。"""
        if tool.name in self._tools:
            logger.warning("Tool %s 已注册，将被覆盖。", tool.name)
        self._tools[tool.name] = tool
        logger.info("Tool 已注册：%s", tool.name)

    def get(self, name: str) -> Tool:
        """按名称获取 Tool。未找到时抛出 KeyError。"""
        if name not in self._tools:
            raise KeyError(f"Tool 未注册: {name}")
        return self._tools[name]

    def list_tools(self) -> list[Tool]:
        """列出所有已注册的 Tool。"""
        return list(self._tools.values())

    def to_openai_schemas(self) -> list[dict[str, Any]]:
        """将所有已注册 Tool 转为 OpenAI tool-calling 兼容格式。"""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# ============================================================
# 3. Agent 基类
# ============================================================


class Agent(ABC):
    """
    Agent 抽象基类。

    子类需要实现 async run() 方法，具体可以是：
    - ReAct 循环（LiteratureAgent）
    - 任务规划（TaskPlanner）
    - 报告生成（ReportWriter）
    """

    @abstractmethod
    async def run(self, **kwargs: Any) -> Any:
        """执行 Agent 任务，返回结果。"""
        ...


# ============================================================
# 4. ReAct 循环执行器
# ============================================================


class ReActLoop:
    """
    ReAct（Reasoning + Acting）循环执行器。

    封装标准的「思考 → 行动 → 观察」的迭代过程。

    用法：
        loop = ReActLoop(
            llm_client=ollama_client,
            registry=tool_registry,
            system_prompt="你是文献分析专家...",
        )
        answer = await loop.run(user_query="HMO 的结构解析方法？")
    """

    MAX_ITERATIONS: int = 10

    def __init__(
        self,
        llm_client: Any,
        registry: ToolRegistry,
        system_prompt: str = "",
        max_iterations: int = 10,
    ) -> None:
        """
        初始化 ReAct 循环。

        参数：
            llm_client:
                LLM 客户端（需要支持 chat(messages, tools) 接口）。

            registry:
                Tool 注册中心。

            system_prompt:
                系统提示词。

            max_iterations:
                最大迭代次数，防止无限循环。
        """
        self.llm_client = llm_client
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations

    async def run(
        self,
        user_query: str,
    ) -> dict[str, Any]:
        """
        执行 ReAct 循环。

        返回：
            {
                "answer": str,
                "iterations": int,
                "tool_calls": list[dict],
                "history": list[dict],
            }
        """
        messages: list[dict[str, Any]] = []

        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        messages.append({"role": "user", "content": user_query})

        tool_calls_log: list[dict[str, Any]] = []
        tools = self.registry.to_openai_schemas() if self.registry else None

        for iteration in range(1, self.max_iterations + 1):
            logger.info("ReAct 迭代 %d/%d", iteration, self.max_iterations)

            # 调用 LLM
            response = await self.llm_client.chat(
                messages=messages,
                tools=tools,
            )

            messages.append(response.message)

            # 如果 LLM 决定给出最终回答
            if response.finish_reason == "stop":
                return {
                    "answer": response.content or "",
                    "iterations": iteration,
                    "tool_calls": tool_calls_log,
                    "history": messages,
                }

            # 如果 LLM 请求调用 Tool
            if response.finish_reason == "tool_calls" and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("arguments", {})
                    call_id = tool_call.get("id", "")

                    # 查找并执行 Tool
                    try:
                        tool = self.registry.get(tool_name)
                        params = tool.input_schema(**tool_args)
                        result = await tool.run(params)
                        tool_output = (
                            json.dumps(result.data, ensure_ascii=False)
                            if result.success
                            else f"Error: {result.error}"
                        )
                    except Exception as exc:
                        tool_output = f"Error: {exc}"

                    tool_calls_log.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "output": tool_output,
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_output,
                    })
            else:
                # 未知 finish_reason，默认视为 stop
                return {
                    "answer": response.content or "",
                    "iterations": iteration,
                    "tool_calls": tool_calls_log,
                    "history": messages,
                }

        # 达到最大迭代次数
        logger.warning("ReAct 循环达到最大迭代次数 %d", self.max_iterations)
        return {
            "answer": "ReAct 循环达到最大迭代次数，未能获取最终回答。",
            "iterations": self.max_iterations,
            "tool_calls": tool_calls_log,
            "history": messages,
        }
