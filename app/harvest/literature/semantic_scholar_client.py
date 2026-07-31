"""
semantic_scholar_client.py

Semantic Scholar 文献检索客户端。

作用：
1. 调用 Semantic Scholar Graph API 进行通用学术文献检索；
2. 覆盖 2 亿+ 论文，作为 Google Scholar 的合规替代方案；
3. 将结果标准化为统一的 PaperMetadata 数据结构。

API 文档：https://api.semanticscholar.org/api-docs/graph
API 端点：https://api.semanticscholar.org/graph/v1/paper/search

免认证使用（无 API key）：
- 速率限制约 100 次/5 分钟（共享 IP 池）
- 适合个人工作站使用

如有更高需求可申请 API key 提升速率。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.harvest.literature._http_utils import decode_response_body
from app.harvest.literature.europe_pmc_client import PaperMetadata


class SemanticScholarClient:
    """
    Semantic Scholar Graph API 客户端。

    使用示例：
        client = SemanticScholarClient()
        results = client.search("CRISPR gene editing", max_results=20)
    """

    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    # 请求的返回字段
    FIELDS = ",".join([
        "paperId",
        "title",
        "abstract",
        "year",
        "authors",
        "venue",
        "externalIds",
        "openAccessPdf",
        "publicationTypes",
        "publicationDate",
        "citationCount",
    ])

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        retry_sleep: float = 2.0,
        user_agent: str = "ScholarFlow/0.2",
        api_key: Optional[str] = None,
    ) -> None:
        """
        初始化 Semantic Scholar 客户端。

        参数：
            timeout: 单次请求超时时间，单位秒。
            max_retries: 最大重试次数。
            retry_sleep: 请求失败后的等待时间，单位秒。
            user_agent: User-Agent 请求头。
            api_key: Semantic Scholar API key，有则提升速率限制。无则使用免费额度。
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.user_agent = user_agent
        self.api_key = api_key
    def search(
        self,
        query: str,
        max_results: int = 20,
        page_size: int = 25,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        author: Optional[str] = None,
    ) -> list[PaperMetadata]:
        """
        搜索 Semantic Scholar 文献。

        参数：
            query: 用户检索词。
            max_results: 最多返回多少条文献。
            page_size: 每页请求数量（Semantic Scholar 最大 100）。
            year_from: 发表年份下限（含），可选。
            year_to: 发表年份上限（含），可选。
            author: 按作者名过滤。通过引用号精确匹配嵌入 query。

        返回：
            PaperMetadata 列表。
        """
        if (not query or not query.strip()) and (not author or not author.strip()):
            raise ValueError("query 不能为空。")

        if max_results <= 0:
            return []

        if author and author.strip():
            from app.agent.name_utils import expand_chinese_name
            variants = expand_chinese_name(author)
            if len(variants) == 1:
                author_clause = f'"{variants[0]}"'
            else:
                clauses = [f'"{v}"' for v in variants]
                author_clause = f'(" OR ".join(clauses))'
            query = f'{author_clause} {query}' if query.strip() else author_clause

        page_size = max(1, min(page_size, 100))

        collected: list[PaperMetadata] = []
        offset = 0

        while len(collected) < max_results:
            current_page_size = min(page_size, max_results - len(collected))

            response_json = self._request_search_page(
                query=query.strip(),
                offset=offset,
                limit=current_page_size,
                year_from=year_from,
                year_to=year_to,
            )

            data_list = response_json.get("data", [])

            if not data_list:
                break

            for item in data_list:
                metadata = self._parse_result_item(item)
                if metadata is not None:
                    collected.append(metadata)

                if len(collected) >= max_results:
                    break

            # 检查是否还有更多结果
            total = response_json.get("total", 0)
            offset += len(data_list)

            if offset >= total:
                break

        return collected

    def _request_search_page(
        self,
        query: str,
        offset: int,
        limit: int,
        year_from: Optional[int],
        year_to: Optional[int],
    ) -> dict[str, Any]:
        """请求 Semantic Scholar 单页搜索结果。"""
        params: dict[str, str] = {
            "query": query,
            "offset": str(offset),
            "limit": str(limit),
            "fields": self.FIELDS,
        }

        # 年份过滤
        if year_from is not None or year_to is not None:
            year_filter = ""
            if year_from is not None:
                year_filter += str(year_from)
            year_filter += "-"
            if year_to is not None:
                year_filter += str(year_to)
            params["year"] = year_filter

        encoded_params = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}?{encoded_params}"

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        if self.api_key:
            headers["x-api-key"] = self.api_key

        last_error: Optional[Exception] = None
        attempt = 0
        rate_limit_retries = 0
        total_rate_limit_wait = 0.0
        MAX_RATE_LIMIT_WAIT = 45.0  # 最多等 45 秒后放弃

        while attempt < self.max_retries:
            attempt += 1

            try:
                request = urllib.request.Request(
                    url=url,
                    headers=headers,
                    method="GET",
                )

                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout,
                ) as response:
                    status_code = response.status

                    if status_code == 429:
                        rate_limit_retries += 1
                        # 指数退避: 2s → 4s → 8s → 16s ...
                        wait = self.retry_sleep * (2 ** min(rate_limit_retries, 5))
                        total_rate_limit_wait += wait
                        if total_rate_limit_wait > MAX_RATE_LIMIT_WAIT:
                            raise RuntimeError(
                                f"Semantic Scholar 速率限制（429），"
                                f"已等待 {total_rate_limit_wait:.0f}s 超过上限。"
                                f"建议：在 .env 中添加 SEMANTIC_SCHOLAR_API_KEY 提升限额，"
                                f"或稍后重试。"
                            )
                        time.sleep(wait)
                        attempt -= 1  # 不消耗正常重试次数
                        continue

                    if status_code != 200:
                        raise RuntimeError(
                            f"Semantic Scholar 请求失败，HTTP 状态码：{status_code}"
                        )

                    raw = response.read()
                    content_type = response.headers.get("Content-Type", "")
                    body = decode_response_body(raw, content_type)
                    return json.loads(body)

            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    rate_limit_retries += 1
                    wait = self.retry_sleep * (2 ** min(rate_limit_retries, 5))
                    total_rate_limit_wait += wait
                    if total_rate_limit_wait > MAX_RATE_LIMIT_WAIT:
                        raise RuntimeError(
                            f"Semantic Scholar 速率限制（429），"
                            f"已等待 {total_rate_limit_wait:.0f}s 超过上限。"
                            f"建议：在 .env 中添加 SEMANTIC_SCHOLAR_API_KEY 提升限额，"
                            f"或稍后重试。"
                        )
                    time.sleep(wait)
                    attempt -= 1
                    continue
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep * attempt)
                else:
                    break

            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
                RuntimeError,
                UnicodeDecodeError,
            ) as exc:
                last_error = exc

                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep * attempt)
                else:
                    break

        raise RuntimeError(
            f"Semantic Scholar 请求失败，已重试 {self.max_retries} 次。"
            f"最后错误：{last_error}"
        )

    def _parse_result_item(
        self,
        item: dict[str, Any],
    ) -> Optional[PaperMetadata]:
        """将 Semantic Scholar 单条结果转换成 PaperMetadata。"""
        title = _clean_text(item.get("title"))

        if not title:
            return None

        abstract = _clean_text(item.get("abstract"))

        # 作者列表
        raw_authors = item.get("authors")
        authors = _parse_authors(raw_authors) if raw_authors else None

        year = item.get("year")
        if year is not None:
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None

        # venue 作为期刊名
        venue = _clean_text(item.get("venue"))

        # externalIds 中的 DOI / PubMed ID
        external_ids = item.get("externalIds") or {}
        doi = _clean_text(external_ids.get("DOI"))
        pmid = _clean_text(external_ids.get("PubMed"))
        corpus_id = _clean_text(external_ids.get("CorpusId"))

        # paperId 作为 Semantic Scholar 内部 ID
        s2_paper_id = _clean_text(item.get("paperId"))

        # 开放获取 PDF 链接
        open_access_pdf = item.get("openAccessPdf")
        pdf_url = None
        if isinstance(open_access_pdf, dict):
            pdf_url = _clean_text(open_access_pdf.get("url"))

        # 构造 URL
        url = None
        if doi:
            url = f"https://doi.org/{doi}"
        elif s2_paper_id:
            url = f"https://www.semanticscholar.org/paper/{s2_paper_id}"

        # 开放获取状态
        is_open_access = 1 if pdf_url else 0

        # 引用计数
        cited_raw = item.get("citationCount")
        citation_count = None
        if cited_raw is not None:
            try:
                citation_count = int(cited_raw)
            except (ValueError, TypeError):
                citation_count = None

        return PaperMetadata(
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            journal=venue,
            doi=doi,
            pmid=pmid,
            pmcid=None,
            source="semantic_scholar",
            url=url,
            pdf_url=pdf_url,
            license=None,
            is_open_access=is_open_access,
            citation_count=citation_count,
            raw=item,
        )


# ---- 辅助函数 ----


def _clean_text(value: Any) -> Optional[str]:
    """清洗文本字段。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return " ".join(text.split())


def _parse_authors(authors_data: Any) -> Optional[list[str]]:
    """解析 Semantic Scholar 的作者列表。

    格式：[{"authorId": "123", "name": "John Smith"}, ...]
    """
    if not isinstance(authors_data, list):
        return None

    authors: list[str] = []
    for author in authors_data:
        if not isinstance(author, dict):
            continue
        name = author.get("name")
        if name and str(name).strip():
            authors.append(str(name).strip())

    return authors if authors else None
