"""
arxiv_client.py

arXiv 文献检索客户端。

作用：
1. 调用 arXiv API (Atom XML) 检索预印本文献；
2. 将结果标准化为统一的 PaperMetadata 数据结构。

arXiv API 文档：https://info.arxiv.org/help/api/index.html
API 端点：http://export.arxiv.org/api/query

arXiv 覆盖领域：物理、数学、计算机科学、定量生物学、定量金融、
统计学、电气工程、经济学等。

使用标准库 urllib + xml.etree，不额外依赖。
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Optional

from app.harvest.literature.europe_pmc_client import PaperMetadata


# Atom XML 命名空间
ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"

# 命名空间映射，方便查找
NAMESPACES = {
    "atom": ATOM_NS,
    "arxiv": ARXIV_NS,
}


class ArxivClient:
    """
    arXiv API 客户端。

    使用示例：
        client = ArxivClient()
        results = client.search("transformer attention mechanism", max_results=20)
    """

    BASE_URL = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        retry_sleep: float = 3.0,
        user_agent: str = "ScholarFlow/0.2",
    ) -> None:
        """
        初始化 arXiv 客户端。

        参数：
            timeout: 单次请求超时时间，单位秒。
            max_retries: 最大重试次数。
            retry_sleep: 请求失败后的等待时间，单位秒。
                        arXiv 建议请求间隔 ≥3 秒，这里作为最小重试间隔。
            user_agent: User-Agent 请求头。
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.user_agent = user_agent
        # 创建不验证证书的 SSL 上下文（解决 Windows 证书链问题）
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE

    def search(
        self,
        query: str,
        max_results: int = 20,
        page_size: int = 25,
        sort_by: str = "relevance",
    ) -> list[PaperMetadata]:
        """
        搜索 arXiv 文献。

        参数：
            query: 用户检索词。
            max_results: 最多返回多少条文献。
            page_size: 每页请求数量。
            sort_by: 排序方式，relevance / lastUpdatedDate / submittedDate。

        返回：
            PaperMetadata 列表。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        if max_results <= 0:
            return []

        page_size = max(1, min(page_size, 200))

        # arXiv API 一次请求即可获取 max_results 条，无需翻页
        response_xml = self._request_search_page(
            query=query.strip(),
            start=0,
            page_size=min(page_size, max_results),
            sort_by=sort_by,
        )

        entries = self._parse_feed(response_xml)

        collected: list[PaperMetadata] = []
        for entry in entries:
            metadata = self._parse_entry(entry)
            if metadata is not None:
                collected.append(metadata)

            if len(collected) >= max_results:
                break

        return collected

    def _request_search_page(
        self,
        query: str,
        start: int,
        page_size: int,
        sort_by: str,
    ) -> str:
        """
        请求 arXiv 单页搜索结果，返回 XML 文本。
        """
        params = {
            "search_query": f"all:{query}",
            "start": str(start),
            "max_results": str(page_size),
            "sortBy": sort_by,
            "sortOrder": "descending",
        }

        encoded_params = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}?{encoded_params}"

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/atom+xml",
        }

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                request = urllib.request.Request(
                    url=url,
                    headers=headers,
                    method="GET",
                )

                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout,
                    context=self._ssl_context,
                ) as response:
                    status_code = response.status

                    if status_code != 200:
                        raise RuntimeError(
                            f"arXiv 请求失败，HTTP 状态码：{status_code}"
                        )

                    return response.read().decode("utf-8")

            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                RuntimeError,
            ) as exc:
                last_error = exc

                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep * attempt)
                else:
                    break

        raise RuntimeError(
            f"arXiv 请求失败，已重试 {self.max_retries} 次。"
            f"最后错误：{last_error}"
        )

    def _parse_feed(self, xml_text: str) -> list[ET.Element]:
        """
        解析 arXiv Atom Feed XML，返回 entry 元素列表。
        """
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise RuntimeError(f"arXiv XML 解析失败：{exc}")

        entries = root.findall(f"{{{ATOM_NS}}}entry")
        return entries

    def _parse_entry(self, entry: ET.Element) -> Optional[PaperMetadata]:
        """
        将单个 arXiv entry 转换为 PaperMetadata。
        """
        title = self._get_text(entry, "title")
        if not title:
            return None

        abstract = self._get_text(entry, "summary")
        authors = self._parse_authors(entry)

        # 解析发表日期获取年份
        published = self._get_text(entry, "published")
        year = self._parse_year(published)

        # arXiv ID 从 <id> 标签提取
        entry_id = self._get_text(entry, "id") or ""
        arxiv_id = self._extract_arxiv_id(entry_id)

        # DOI (arXiv 记录有时有 doi 字段)
        doi = self._get_arxiv_field(entry, "doi")

        # journal_ref
        journal = self._get_arxiv_field(entry, "journal_ref") or "arXiv"

        # PDF 链接
        pdf_url = self._extract_pdf_link(entry)
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        # 主页 URL
        url = entry_id if entry_id else f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None

        return PaperMetadata(
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            journal=journal,
            doi=doi,
            pmid=None,
            pmcid=None,
            source="arxiv",
            url=url,
            pdf_url=pdf_url,
            license=None,
            is_open_access=1,  # arXiv 文献全部开放获取
            raw=self._entry_to_dict(entry),
        )

    # ---- 辅助方法 ----

    def _get_text(self, parent: ET.Element, tag: str) -> Optional[str]:
        """获取 Atom 命名空间下的文本。"""
        elem = parent.find(f"{{{ATOM_NS}}}{tag}")
        if elem is None or elem.text is None:
            return None
        text = " ".join(elem.text.split())
        return text if text else None

    def _get_arxiv_field(self, parent: ET.Element, tag: str) -> Optional[str]:
        """获取 arXiv 扩展命名空间下的文本。"""
        elem = parent.find(f"{{{ARXIV_NS}}}{tag}")
        if elem is None or elem.text is None:
            return None
        text = " ".join(elem.text.split())
        return text if text else None

    def _parse_authors(self, entry: ET.Element) -> Optional[list[str]]:
        """解析 arXiv entry 的作者列表。"""
        author_elems = entry.findall(f"{{{ATOM_NS}}}author")
        if not author_elems:
            return None

        authors: list[str] = []
        for author_elem in author_elems:
            name_elem = author_elem.find(f"{{{ATOM_NS}}}name")
            if name_elem is not None and name_elem.text:
                name = name_elem.text.strip()
                if name:
                    authors.append(name)

        return authors if authors else None

    def _parse_year(self, date_str: Optional[str]) -> Optional[int]:
        """从 ISO 日期字符串中提取年份。"""
        if not date_str:
            return None
        match = re.match(r"(\d{4})", date_str.strip())
        if match:
            return int(match.group(1))
        return None

    def _extract_arxiv_id(self, entry_id: str) -> Optional[str]:
        """从 arXiv entry URL 中提取 arXiv ID。

        例：http://arxiv.org/abs/2106.12345v1 -> 2106.12345v1
        """
        if not entry_id:
            return None
        match = re.search(r"/abs/(.+)$", entry_id.strip())
        if match:
            return match.group(1)
        return None

    def _extract_pdf_link(self, entry: ET.Element) -> Optional[str]:
        """从 arXiv entry 的 link 标签中提取 PDF 链接。"""
        for link_elem in entry.findall(f"{{{ATOM_NS}}}link"):
            rel = link_elem.get("rel", "")
            link_type = link_elem.get("type", "")
            href = link_elem.get("href", "")

            if "pdf" in link_type or rel == "enclosure":
                return href

        return None

    def _entry_to_dict(self, entry: ET.Element) -> dict[str, Any]:
        """将 ET.Element 序列化为简单 dict（用于 raw 字段）。"""
        result: dict[str, Any] = {}
        for child in entry:
            tag = child.tag.split("}")[-1]  # 去掉命名空间前缀
            if child.text and child.text.strip():
                result[tag] = child.text.strip()
            elif len(child) == 0:
                result[tag] = None
            else:
                # 嵌套元素
                result[tag] = self._entry_to_dict(child)
        return result
