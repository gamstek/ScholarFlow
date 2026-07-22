"""
web_search.py

轻量级网页搜索模块 — 使用 DuckDuckGo 免费搜索 API。

作用：
1. 作为 Agent 的 web_search 工具后端，补充文献 API 覆盖不到的来源；
2. 返回标题、摘要片段、URL 列表，由 Agent LLM 自行解析提取论文信息。

依赖：ddgs（pip install ddgs）
"""

from __future__ import annotations

from typing import Any


class WebSearcher:
    """DuckDuckGo 网页搜索器。"""

    def __init__(self, timeout: int = 15, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries

    def search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",
    ) -> list[dict[str, str]]:
        """
        执行网页搜索。

        参数：
            query: 搜索查询字符串。
            max_results: 最大返回结果数。
            region: 搜索区域，默认全球。

        返回：
            [{"title": ..., "snippet": ..., "url": ..., "source": ...}, ...]
        """
        if not query or not query.strip():
            return []

        from ddgs import DDGS

        results: list[dict[str, str]] = []

        for attempt in range(1, self.max_retries + 1):
            try:
                with DDGS(timeout=self.timeout) as ddgs:
                    for r in ddgs.text(
                        query=query.strip(),
                        region=region,
                        max_results=max_results,
                    ):
                        results.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                            "url": r.get("href", ""),
                            "source": "web_search",
                        })
                break
            except Exception:
                if attempt >= self.max_retries:
                    raise

        return results[:max_results]


# 模块级单例
_searcher: WebSearcher | None = None


def get_searcher() -> WebSearcher:
    global _searcher
    if _searcher is None:
        _searcher = WebSearcher()
    return _searcher
