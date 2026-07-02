"""
task_planner.py

任务规划 Agent。

作用：
1. 接收用户自然语言意图；
2. 将意图分解为子任务列表（采集→下载→解析→切分→索引）；
3. 输出结构化的任务计划供 Orchestrator 执行。

⚠ 待第 8 步实现 LLM + ReAct 规划逻辑。
"""

from __future__ import annotations


def plan_tasks(user_intent: str) -> list[dict]:
    """
    将用户意图分解为子任务列表。

    参数：
        user_intent: 用户自然语言意图，例如「跟踪黄酮类质谱解析文献」。

    返回：
        list[dict]: 子任务列表，每项包含 stage / tool / params。
    """
    raise NotImplementedError("待第 8 步实现 plan_tasks")
