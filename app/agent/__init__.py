"""
app.agent

Agent 基础设施包。

导出：
- Tool, ToolResult: Tool 抽象基类与结果模型
- ToolRegistry: Tool 注册中心
- Agent: Agent 基类
- ReActLoop: ReAct 循环执行器
"""

from app.agent.base import Agent, ReActLoop, Tool, ToolRegistry, ToolResult

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "Agent",
    "ReActLoop",
]
