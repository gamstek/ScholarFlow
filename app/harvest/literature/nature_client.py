"""
nature_client.py

Nature 系列期刊文献检索客户端。

作用：
1. 通过 Europe PMC API 检索 Nature 系列期刊文献；
2. 自动在查询中追加 Nature 系列期刊名作为过滤条件；
3. 将结果标准化为统一的 PaperMetadata 数据结构。

Nature 系列期刊列表（完整覆盖 Nature Portfolio）：
    - Nature 主刊
    - Nature 子刊（Chemistry / Methods / Medicine / Genetics / Neuroscience 等 30+ 本）
    - Nature Reviews 全系列（23 本综述期刊）
    - Communications 系列（Biology / Chemistry / Physics / Medicine 等 7 本）
    - npj 系列（17 本 partner journals）
    - Scientific Reports / Scientific Data / Humanities and Social Sciences Communications

当前阶段通过 Europe PMC 检索（Nature 系列期刊均被 Europe PMC 收录），
后续可扩展为直接调用 Springer Nature API。

使用标准库 urllib，不额外依赖 requests。
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.harvest.literature._http_utils import decode_response_body
from app.harvest.literature.europe_pmc_client import (
    PaperMetadata,
    build_europe_pmc_article_url,
    clean_text,
    extract_license,
    extract_pdf_url,
    parse_authors,
    parse_citation_count,
    parse_open_access,
    parse_year,
)

# Nature 系列期刊完整列表
# 包含：Nature 主刊 / Nature 子刊 / Nature Reviews 全系列 / npj 系列 / Communications 系列 / 其他 Nature Portfolio 期刊
NATURE_JOURNALS = [
    # ---- Nature 主刊 ----
    "Nature",
    # ---- Nature 研究/子刊（按学科） ----
    "Nature Communications",
    "Nature Chemistry",
    "Nature Methods",
    "Nature Biotechnology",
    "Nature Medicine",
    "Nature Genetics",
    "Nature Neuroscience",
    "Nature Immunology",
    "Nature Cell Biology",
    "Nature Chemical Biology",
    "Nature Materials",
    "Nature Nanotechnology",
    "Nature Physics",
    "Nature Photonics",
    "Nature Climate Change",
    "Nature Energy",
    "Nature Sustainability",
    "Nature Catalysis",
    "Nature Microbiology",
    "Nature Plants",
    "Nature Protocols",
    "Nature Astronomy",
    "Nature Biomedical Engineering",
    "Nature Computational Science",
    "Nature Cardiovascular Research",
    "Nature Ecology & Evolution",
    "Nature Electronics",
    "Nature Food",
    "Nature Geoscience",
    "Nature Human Behaviour",
    "Nature Machine Intelligence",
    "Nature Mental Health",
    "Nature Metabolism",
    "Nature Structural & Molecular Biology",
    "Nature Water",
    "Nature Aging",
    # ---- Nature Reviews 全系列 ----
    "Nature Reviews Chemistry",
    "Nature Reviews Molecular Cell Biology",
    "Nature Reviews Genetics",
    "Nature Reviews Immunology",
    "Nature Reviews Neuroscience",
    "Nature Reviews Cancer",
    "Nature Reviews Drug Discovery",
    "Nature Reviews Microbiology",
    "Nature Reviews Materials",
    "Nature Reviews Physics",
    "Nature Reviews Bioengineering",
    "Nature Reviews Chemical Engineering",
    "Nature Reviews Earth & Environment",
    "Nature Reviews Psychology",
    "Nature Reviews Nephrology",
    "Nature Reviews Cardiology",
    "Nature Reviews Endocrinology",
    "Nature Reviews Gastroenterology & Hepatology",
    "Nature Reviews Neurology",
    "Nature Reviews Rheumatology",
    "Nature Reviews Urology",
    "Nature Reviews Clinical Oncology",
    "Nature Reviews Disease Primers",
    # ---- Communications 系列 ----
    "Communications Biology",
    "Communications Chemistry",
    "Communications Physics",
    "Communications Medicine",
    "Communications Materials",
    "Communications Earth & Environment",
    "Communications Psychology",
    # ---- npj 系列 ----
    "npj Science of Food",
    "npj 2D Materials and Applications",
    "npj Climate Adaptation",
    "npj Clean Water",
    "npj Computational Materials",
    "npj Digital Medicine",
    "npj Flexible Electronics",
    "npj Materials Degradation",
    "npj Precision Oncology",
    "npj Quantum Information",
    "npj Quantum Materials",
    "npj Regenerative Medicine",
    "npj Science of Learning",
    "npj Systems Biology and Applications",
    "npj Vaccines",
    "npj Biofilms and Microbiomes",
    "npj Aging",
    # ---- 其他 Nature Portfolio 期刊 ----
    "Scientific Reports",
    "Scientific Data",
    "Humanities and Social Sciences Communications",
]


class NatureClient:
    """
    Nature 系列期刊文献检索客户端。

    内部使用 Europe PMC API，通过 journal 过滤字段限定检索范围。

    使用示例：
        client = NatureClient()
        results = client.search("machine learning", max_results=20)
    """

    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        retry_sleep: float = 1.0,
        user_agent: str = "ScholarFlow/0.2",
        journals: list[str] | None = None,
    ) -> None:
        """
        初始化 Nature 客户端。

        参数：
            timeout: 单次请求超时时间，单位秒。
            max_retries: 最大重试次数。
            retry_sleep: 请求失败后的等待时间，单位秒。
            user_agent: User-Agent 请求头。
            journals: 自定义 Nature 系列期刊列表，为 None 时使用默认列表。
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.user_agent = user_agent
        self.journals = journals or NATURE_JOURNALS
        # 创建不验证证书的 SSL 上下文（解决 Windows 证书链问题）
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE

    def search(
        self,
        query: str,
        max_results: int = 20,
        page_size: int = 25,
    ) -> list[PaperMetadata]:
        """
        检索 Nature 系列期刊文献。

        参数：
            query: 用户检索词。
            max_results: 最多返回多少条文献。
            page_size: 每页请求数量。

        返回：
            PaperMetadata 列表。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        if max_results <= 0:
            return []

        page_size = max(1, min(page_size, 1000))

        final_query = self._build_nature_query(query.strip())

        collected: list[PaperMetadata] = []
        cursor_mark = "*"

        while len(collected) < max_results:
            current_page_size = min(page_size, max_results - len(collected))

            response_json = self._request_search_page(
                query=final_query,
                page_size=current_page_size,
                cursor_mark=cursor_mark,
            )

            result_list = (
                response_json
                .get("resultList", {})
                .get("result", [])
            )

            if not result_list:
                break

            for item in result_list:
                metadata = self._parse_result_item(item)
                if metadata is not None:
                    collected.append(metadata)

                if len(collected) >= max_results:
                    break

            next_cursor_mark = response_json.get("nextCursorMark")

            if not next_cursor_mark or next_cursor_mark == cursor_mark:
                break

            cursor_mark = next_cursor_mark

        return collected

    def _build_nature_query(self, user_query: str) -> str:
        """
        构造 Nature 期刊过滤查询。

        将用户查询与 Nature 系列期刊名做 AND 连接，
        确保只检索 Nature 家族期刊的文献。
        """
        journal_terms = " OR ".join(
            f'"{journal}"' for journal in self.journals
        )
        return f'({user_query}) AND (JOURNAL:({journal_terms}))'

    def _request_search_page(
        self,
        query: str,
        page_size: int,
        cursor_mark: str,
    ) -> dict[str, Any]:
        """
        请求 Europe PMC 单页搜索结果。
        """
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": str(page_size),
            "cursorMark": cursor_mark,
        }

        encoded_params = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}?{encoded_params}"

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
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
                            f"Europe PMC 请求失败，HTTP 状态码：{status_code}"
                        )

                    raw = response.read()
                    content_type = response.headers.get("Content-Type", "")
                    body = decode_response_body(raw, content_type)
                    return json.loads(body)

            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
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
            f"Nature 检索请求失败，已重试 {self.max_retries} 次。"
            f"最后错误：{last_error}"
        )

    def _parse_result_item(
        self,
        item: dict[str, Any],
    ) -> Optional[PaperMetadata]:
        """
        将单条结果转换成 PaperMetadata。
        """
        title = clean_text(item.get("title"))

        if not title:
            return None

        abstract = clean_text(item.get("abstractText"))
        authors = parse_authors(item.get("authorString"))
        year = parse_year(item.get("pubYear"))

        journal = clean_text(
            item.get("journalTitle")
            or item.get("bookOrReportDetails")
        )

        doi = clean_text(item.get("doi"))
        pmid = clean_text(item.get("pmid"))
        pmcid = clean_text(item.get("pmcid"))

        source = clean_text(item.get("source")) or "nature"

        url = build_europe_pmc_article_url(
            pmid=pmid,
            pmcid=pmcid,
            doi=doi,
        )

        pdf_url = extract_pdf_url(item)
        license_text = extract_license(item)
        is_open_access = parse_open_access(item)
        citation_count = parse_citation_count(item)

        return PaperMetadata(
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            journal=journal,
            doi=doi,
            pmid=pmid,
            pmcid=pmcid,
            source="nature",
            url=url,
            pdf_url=pdf_url,
            license=license_text,
            is_open_access=is_open_access,
            citation_count=citation_count,
            raw=item,
        )
