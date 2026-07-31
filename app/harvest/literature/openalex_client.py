"""
openalex_client.py

OpenAlex 文献检索客户端。

作用：
1. 调用 OpenAlex REST API 进行跨学科学术文献检索；
2. 覆盖 2.5 亿+ 学术作品，含引用计数和期刊级统计；
3. 将结果标准化为统一的 PaperMetadata 数据结构。

API 文档：https://docs.openalex.org/
API 端点：https://api.openalex.org/works

免认证使用（礼貌池）：
- 建议在请求中包含 mailto 参数
- 适合个人工作站使用
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


class OpenAlexClient:
    """
    OpenAlex REST API 客户端。

    使用示例：
        client = OpenAlexClient()
        results = client.search("CRISPR gene editing", max_results=20)
    """

    BASE_URL = "https://api.openalex.org/works"

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        retry_sleep: float = 1.0,
        user_agent: str = "ScholarFlow/0.3",
        email: str = "scholarflow@example.com",
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.user_agent = user_agent
        self.email = email

    def search(
        self,
        query: str,
        max_results: int = 20,
        per_page: int = 25,
        author: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        preprint_sources: list[str] | None = None,
        language: str | None = None,
    ) -> list[PaperMetadata]:
        """
        搜索 OpenAlex 文献。

        参数：
            query: 用户检索词。
            max_results: 最多返回多少条文献。
            per_page: 每页数量（最大 200）。
            author: 按作者名过滤。
            year_from: 发表年份下限。
            year_to: 发表年份上限。
            preprint_sources: 预印本源 ID 列表，如 ["S4306402567", "S3005729997"]。
                按 primary_location.source.id 过滤。

        返回：
            PaperMetadata 列表。
        """
        if not query or not query.strip():
            if not author or not author.strip():
                raise ValueError("query 不能为空（除非提供 author）。")
            query = ""

        if max_results <= 0:
            return []

        per_page = max(1, min(per_page, 200))

        collected: list[PaperMetadata] = []
        page = 1

        while len(collected) < max_results:
            params: dict[str, str] = {
                "search": query.strip() if query.strip() else (author or ""),
                "per_page": str(per_page),
                "page": str(page),
                "sort": "cited_by_count:desc",
            }
            # 构建 filter 参数
            filters: list[str] = []
            if author and author.strip():
                filters.append(f"author.search:{author.strip()}")
            if year_from:
                filters.append(f"from_publication_date:{year_from}-01-01")
            if year_to:
                filters.append(f"to_publication_date:{year_to}-12-31")
            if preprint_sources:
                src_ids = "|".join(preprint_sources)
                filters.append(f"primary_location.source.id:{src_ids}")
            if language and language.strip() in ("zh", "chi"):
                filters.append("language:zh")
            elif language and language.strip() == "en":
                filters.append("language:en")
            if filters:
                params["filter"] = ",".join(filters)

            if self.email:
                params["mailto"] = self.email

            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
            data = self._request_json(url)

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                paper = self._parse_work(item)
                if paper is not None:
                    collected.append(paper)
                if len(collected) >= max_results:
                    break

            # 翻页
            meta = data.get("meta", {})
            total = meta.get("count", 0)
            if page * per_page >= total:
                break
            page += 1

        return collected

    def _parse_work(self, item: dict[str, Any]) -> Optional[PaperMetadata]:
        """解析单条 OpenAlex work 记录。"""
        title = item.get("title", "")
        if not title:
            return None

        # 作者 + 机构
        authorship = item.get("authorships", [])
        authors: list[str] = []
        for a in authorship:
            author_info = a.get("author", {}) or {}
            name = author_info.get("display_name", "")
            if name:
                authors.append(name)
        authors = authors if authors else None

        # 年份
        year = item.get("publication_year")

        # 期刊/来源
        primary_location = item.get("primary_location", {}) or {}
        source_info = primary_location.get("source", {}) or {}
        journal = source_info.get("display_name") or item.get("host_venue", {}).get("display_name")

        # DOI
        doi = item.get("doi", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/"):]

        # PMID/PMCID
        ids = item.get("ids", {}) or {}
        pmid = str(ids.get("pmid", "")) or None
        pmcid = ids.get("pmcid") or None

        # 引用计数
        citation_count = item.get("cited_by_count")

        # 开放获取
        oa = item.get("open_access", {}) or {}
        is_oa = 1 if oa.get("is_oa") else 0
        pdf_url = oa.get("oa_url") or None

        # 摘要（OpenAlex 可能通过 inverted abstract 索引提供）
        abstract = None
        abstract_inverted = item.get("abstract_inverted_index")
        if abstract_inverted and isinstance(abstract_inverted, dict):
            try:
                # 重建摘要文本
                words = sorted(
                    [(pos, word) for word, positions in abstract_inverted.items() for pos in positions],
                    key=lambda x: x[0],
                )
                abstract = " ".join(w for _, w in words)
            except Exception:
                pass

        # URL
        url = item.get("id")  # OpenAlex work URL

        return PaperMetadata(
            title=title,
            abstract=abstract,
            authors=authors,
            author_affiliations=None,
            year=year,
            journal=journal,
            doi=doi or None,
            pmid=pmid,
            pmcid=pmcid,
            source="openalex",
            url=url,
            pdf_url=pdf_url,
            license=oa.get("license") or None,
            is_open_access=is_oa,
            citation_count=citation_count,
            raw={
                "type": item.get("type"),
                "cited_by_count": citation_count,
                "concepts": item.get("concepts", []),
                "host_venue": item.get("host_venue"),
            },
        )

    def _request_json(self, url: str) -> dict[str, Any]:
        """发送 GET 请求并解析 JSON。"""
        headers = {"User-Agent": self.user_agent}

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                request = urllib.request.Request(url=url, headers=headers, method="GET")
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    raw = resp.read()
                    content_type = resp.headers.get("Content-Type", "")
                    return json.loads(decode_response_body(raw, content_type))
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, UnicodeDecodeError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep * attempt)

        raise RuntimeError(
            f"OpenAlex 请求失败，已重试 {self.max_retries} 次。最后错误：{last_error}"
        )
