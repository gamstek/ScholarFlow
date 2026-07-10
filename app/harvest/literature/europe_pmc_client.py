"""
europe_pmc_client.py

Europe PMC 文献采集客户端。

作用：
1. 调用 Europe PMC Articles RESTful API；
2. 根据用户 query 检索文献；
3. 将 Europe PMC 返回结果标准化为统一的 PaperMetadata 数据结构；
4. 为后续 harvester 入库提供干净的数据。

当前阶段：
- 只采集 metadata；
- 不下载 PDF；
- 不解析全文；
- 不做复杂翻页采集，只支持 max_results 控制数量。

使用标准库 urllib，不额外依赖 requests。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class PaperMetadata:
    """
    标准化后的文献 metadata。

    这个对象是系统内部统一使用的文献格式。
    不管原始数据来自 Europe PMC、Crossref、PubMed 还是其他来源，
    后续都应该尽量转换成这个格式。
    """

    title: str
    abstract: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    source: str = "europe_pmc"
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    license: Optional[str] = None
    is_open_access: int = 0
    citation_count: Optional[int] = None
    raw: Optional[dict[str, Any]] = None


class EuropePmcClient:
    """
    Europe PMC REST API 客户端。

    Europe PMC 搜索接口：
        https://www.ebi.ac.uk/europepmc/webservices/rest/search

    常用参数：
        query:
            检索语句。

        format:
            返回格式，这里使用 json。

        resultType:
            返回结果类型。
            当前使用 core，返回核心 metadata。

        pageSize:
            每页数量。

        cursorMark:
            翻页游标。
    """

    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        retry_sleep: float = 1.0,
        user_agent: str = "ScholarFlow/0.2",
    ) -> None:
        """
        初始化 Europe PMC 客户端。

        参数：
            timeout:
                单次请求超时时间，单位秒。

            max_retries:
                最大重试次数。

            retry_sleep:
                请求失败后的等待时间，单位秒。

            user_agent:
                User-Agent 请求头。
                给 API 服务端一个清晰身份，属于比较规范的做法。
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.user_agent = user_agent

    def search(
        self,
        query: str,
        max_results: int = 20,
        page_size: int = 25,
        enhance_query: bool = True,
        enhance_terms: list[str] | None = None,
    ) -> list[PaperMetadata]:
        """
        搜索 Europe PMC 文献。

        参数：
            query:
                用户原始检索词。

            max_results:
                最多返回多少条文献。

            page_size:
                Europe PMC 每页请求数量。

            enhance_query:
                是否对 query 做方向增强。
                True 时，会追加 enhance_terms 中指定的方向词。

            enhance_terms:
                增强检索时使用的方向词列表。
                为 None 时不增强。

        返回：
            PaperMetadata 列表。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        if max_results <= 0:
            return []

        page_size = max(1, min(page_size, 1000))

        final_query = (
            build_enhanced_query(query, enhance_terms)
            if enhance_query
            else query.strip()
        )

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

            # 如果 Europe PMC 没有给新的 cursor，或者 cursor 没变化，说明不能继续翻页
            if not next_cursor_mark or next_cursor_mark == cursor_mark:
                break

            cursor_mark = next_cursor_mark

        return collected

    def _request_search_page(
        self,
        query: str,
        page_size: int,
        cursor_mark: str,
    ) -> dict[str, Any]:
        """
        请求 Europe PMC 单页搜索结果。

        这里带有重试机制，避免偶发网络失败直接导致任务失败。
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
                ) as response:
                    status_code = response.status

                    if status_code != 200:
                        raise RuntimeError(
                            f"Europe PMC 请求失败，HTTP 状态码：{status_code}"
                        )

                    body = response.read().decode("utf-8")
                    return json.loads(body)

            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                json.JSONDecodeError,
                RuntimeError,
            ) as exc:
                last_error = exc

                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep * attempt)
                else:
                    break

        raise RuntimeError(
            f"Europe PMC 请求失败，已重试 {self.max_retries} 次。"
            f"最后错误：{last_error}"
        )

    def _parse_result_item(
        self,
        item: dict[str, Any],
    ) -> Optional[PaperMetadata]:
        """
        将 Europe PMC 单条结果转换成 PaperMetadata。

        Europe PMC 返回字段可能不完整，所以这里要尽量做容错。
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

        source = clean_text(item.get("source")) or "europe_pmc"

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
            source="europe_pmc",
            url=url,
            pdf_url=pdf_url,
            license=license_text,
            is_open_access=is_open_access,
            citation_count=citation_count,
            raw=item,
        )


def build_enhanced_query(
    user_query: str,
    enhance_terms: list[str] | None = None,
) -> str:
    """
    构造增强检索语句。

    如果 enhance_terms 为空，则直接返回原始 query。
    否则将用户 query 与指定方向词做 AND 连接。

    参数：
        user_query: 用户原始检索词。
        enhance_terms: 方向词列表，例如 ["mass spectrometry", "LC-MS/MS"]。
    """
    cleaned_query = user_query.strip()

    if not enhance_terms:
        return cleaned_query

    terms_str = " OR ".join(
        f'"{term}"' for term in enhance_terms
    )

    return f"({cleaned_query}) AND ({terms_str})"


def clean_text(value: Any) -> Optional[str]:
    """
    清洗文本字段。

    将 None、空字符串处理成 None；
    将多余空白压缩成单个空格。
    """
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return " ".join(text.split())


def parse_authors(author_string: Any) -> Optional[list[str]]:
    """
    解析 Europe PMC 的 authorString。

    Europe PMC 常返回一个作者字符串。
    这里尽量转换为 list[str]，方便写入 authors_json。
    """
    if not author_string:
        return None

    text = str(author_string).strip()

    if not text:
        return None

    # Europe PMC 的 authorString 有时是：
    # "Smith J, Zhang Y, Wang L."
    # 也可能含有分号。这里做一个保守拆分。
    if ";" in text:
        authors = [part.strip(" .") for part in text.split(";")]
    else:
        authors = [part.strip(" .") for part in text.split(",")]

    authors = [author for author in authors if author]

    return authors or [text]


def parse_year(value: Any) -> Optional[int]:
    """
    解析发表年份。
    """
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    # pubYear 一般是 4 位年份，但也做容错处理。
    digits = "".join(ch for ch in text if ch.isdigit())

    if len(digits) >= 4:
        try:
            return int(digits[:4])
        except ValueError:
            return None

    return None


def parse_open_access(item: dict[str, Any]) -> int:
    """
    判断文献是否开放获取。

    Europe PMC 返回值可能是：
    - isOpenAccess: "Y" / "N"
    - isOpenAccess: true / false
    """
    value = item.get("isOpenAccess")

    if isinstance(value, bool):
        return 1 if value else 0

    if value is None:
        return 0

    text = str(value).strip().lower()

    if text in {"y", "yes", "true", "1"}:
        return 1

    return 0


def parse_citation_count(item: dict[str, Any]) -> Optional[int]:
    """
    解析引用计数。

    Europe PMC 的 resultType=core 返回 citedByCount 字段。
    其他经过 Europe PMC 的源（Nature/Science/Cell）也使用此函数。
    """
    value = item.get("citedByCount")
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def extract_pdf_url(item: dict[str, Any]) -> Optional[str]:
    """
    从 Europe PMC 结果中提取 PDF URL。

    注意：
        当前只保存 URL，不下载。
        PDF 下载会在后续步骤单独实现。
    """
    full_text_url_list = item.get("fullTextUrlList")

    if not isinstance(full_text_url_list, dict):
        return None

    urls = full_text_url_list.get("fullTextUrl")

    if not isinstance(urls, list):
        return None

    # 优先选择 documentStyle 为 pdf 的链接
    for url_item in urls:
        if not isinstance(url_item, dict):
            continue

        document_style = str(url_item.get("documentStyle", "")).lower()
        url = clean_text(url_item.get("url"))

        if url and "pdf" in document_style:
            return url

    # 如果没有明确 PDF，则返回第一个可用链接
    for url_item in urls:
        if not isinstance(url_item, dict):
            continue

        url = clean_text(url_item.get("url"))
        if url:
            return url

    return None


def extract_license(item: dict[str, Any]) -> Optional[str]:
    """
    提取 license 信息。

    Europe PMC 不同记录的 license 字段可能不一致，
    当前做保守读取。
    """
    license_text = clean_text(item.get("license"))

    if license_text:
        return license_text

    full_text_url_list = item.get("fullTextUrlList")

    if not isinstance(full_text_url_list, dict):
        return None

    urls = full_text_url_list.get("fullTextUrl")

    if not isinstance(urls, list):
        return None

    for url_item in urls:
        if not isinstance(url_item, dict):
            continue

        availability_code = clean_text(url_item.get("availabilityCode"))
        if availability_code:
            return availability_code

    return None


def build_europe_pmc_article_url(
    pmid: Optional[str],
    pmcid: Optional[str],
    doi: Optional[str],
) -> Optional[str]:
    """
    构造 Europe PMC 文献详情页 URL。

    优先级：
    1. PMCID；
    2. PMID；
    3. DOI。
    """
    base = "https://europepmc.org/article"

    if pmcid:
        return f"{base}/PMC/{pmcid.replace('PMC', '')}"

    if pmid:
        return f"{base}/MED/{pmid}"

    if doi:
        encoded_doi = urllib.parse.quote(doi)
        return f"https://europepmc.org/search?query=DOI:{encoded_doi}"

    return None