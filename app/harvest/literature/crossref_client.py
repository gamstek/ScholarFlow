"""
crossref_client.py

Crossref API 客户端。

作用：
1. 通过 Crossref REST API 检索文献元数据；
2. 作为 Europe PMC 的补充数据源；
3. 支持按关键词、作者、DOI 等条件检索。

⚠ 待后续填充完整检索与分页逻辑。
"""

from __future__ import annotations


class CrossrefClient:
    """
    Crossref REST API 客户端。

    使用示例：
        client = CrossrefClient()
        results = client.search("machine learning", rows=10)
    """

    def __init__(self, base_url: str = "https://api.crossref.org/works") -> None:
        self.base_url = base_url

    def search(self, query: str, rows: int = 10) -> list[dict]:
        """
        按关键词检索文献。

        参数：
            query: 检索关键词。
            rows: 返回条数。

        返回：
            list[dict]: 文献元数据列表。
        """
        raise NotImplementedError("CrossrefClient.search 待实现")
