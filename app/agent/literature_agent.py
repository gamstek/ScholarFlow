"""
literature_agent.py

文献问答 Agent（ReAct 模式）。

作用：
1. 接收用户自然语言提问；
2. 决策是否需要检索本地文献库；
3. 调用 RAG 检索 Tool 获取证据；
4. 证据不足时重新生成 query 再检索；
5. 证据充足时调用生成 Tool 输出带引用的回答。

⚠ 待第 8 步实现完整 ReAct loop。
"""

from __future__ import annotations


class LiteratureAgent:
    """
    文献问答 Agent。

    输入用户提问，通过 ReAct 循环调用检索和生成 Tool 完成回答。
    """

    def __init__(self) -> None:
        raise NotImplementedError("待第 8 步实现 LiteratureAgent")
