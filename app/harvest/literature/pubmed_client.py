"""
pubmed_client.py

PubMed E-utilities 文献检索客户端。

作用：
1. 调用 NCBI Entrez E-utilities API 检索 PubMed/MEDLINE 文献；
2. 获取 MeSH 主题词和 Publication Type（综述/临床试验等）；
3. 将结果标准化为统一的 PaperMetadata 数据结构。

API 文档：https://www.ncbi.nlm.nih.gov/books/NBK25501/
API 端点：https://eutils.ncbi.nlm.nih.gov/entrez/eutils/

免认证使用：
- 无 API key 时 3 次/秒（建议注册 key 提升到 10 次/秒）
- 适合个人工作站使用
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from app.harvest.literature.europe_pmc_client import PaperMetadata


class PubmedClient:
    """
    PubMed E-utilities API 客户端。

    使用示例：
        client = PubmedClient()
        results = client.search("CRISPR gene editing", max_results=20)
    """

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        retry_sleep: float = 1.0,
        user_agent: str = "ScholarFlow/0.3",
        api_key: Optional[str] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.user_agent = user_agent
        self.api_key = api_key

    def search(
        self,
        query: str,
        max_results: int = 20,
        author: str | None = None,
        journal: str | None = None,
        institution: str | None = None,
        language: str | None = None,
    ) -> list[PaperMetadata]:
        """
        搜索 PubMed 文献。

        参数：
            query: 用户检索词。
            max_results: 最多返回多少条文献。
            author: 按作者名过滤（PubMed 支持 [AU] 字段）。
            journal: 按期刊名过滤（PubMed 支持 [TA] 字段）。
            institution: 按机构名过滤（PubMed 支持 [AD] 字段）。
            language: 语言过滤（PubMed 支持 [LA] 字段）："zh"=中文 / "en"=英文 / None=不限。

        返回：
            PaperMetadata 列表。
        """
        if not query or not query.strip():
            if not author or not author.strip():
                raise ValueError("query 不能为空（除非提供 author）。")
            query = ""

        # 构建 PubMed 检索式
        search_terms = []
        if author and author.strip():
            search_terms.append(f'{author.strip()}[AU]')
        if journal and journal.strip():
            search_terms.append(f'"{journal.strip()}"[TA]')
        if institution and institution.strip():
            search_terms.append(f'{institution.strip()}[AD]')
        if language and language.strip() in ("zh", "chi"):
            search_terms.append('chinese[LA]')
        elif language and language.strip() == "en":
            search_terms.append('english[LA]')
        if query.strip():
            search_terms.append(query.strip())

        search_query = " AND ".join(search_terms) if search_terms else ""

        if not search_query:
            return []

        if max_results <= 0:
            return []

        # Step 1: esearch — 获取 PMID 列表
        pmids = self._esearch(query=search_query, max_results=max_results)
        if not pmids:
            return []

        # Step 2: esummary — 批量获取元数据
        papers = self._esummary(pmids=pmids)
        return papers

    def _esearch(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[str]:
        """执行 esearch，返回 PMID 列表。"""
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": str(max_results),
            "retmode": "json",
            "sort": "relevance",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/esearch.fcgi?{urllib.parse.urlencode(params)}"

        data = self._request_json(url)
        id_list = data.get("esearchresult", {}).get("idlist", [])
        return id_list

    def _esummary(self, pmids: list[str]) -> list[PaperMetadata]:
        """批量获取文献摘要信息。"""
        if not pmids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/esummary.fcgi?{urllib.parse.urlencode(params)}"

        data = self._request_json(url)
        result = data.get("result", {})
        uids = result.get("uids", [])

        papers: list[PaperMetadata] = []
        for uid in uids:
            item = result.get(uid, {})
            if not item:
                continue

            # 解析作者 + 机构
            authors_raw = item.get("authors", [])
            authors: list[str] = []
            author_affiliations: list[dict] = []
            for a in authors_raw:
                name = a.get("name", "")
                if name:
                    authors.append(name)
                    aff = a.get("affiliation") or None
                    author_affiliations.append({"name": name, "institution": aff})
            author_affiliations = author_affiliations if author_affiliations else None

            # 解析年份
            pubdate = item.get("pubdate", "")
            year = None
            if pubdate:
                import re
                m = re.search(r"(\d{4})", pubdate)
                if m:
                    year = int(m.group(1))

            # 解析 DOI
            article_ids = item.get("articleids", [])
            doi = None
            for aid in article_ids:
                if aid.get("idtype") == "doi":
                    doi = aid.get("value")
                    break

            # 期刊名
            journal = item.get("source", "") or item.get("fulljournalname", "")

            # PubMed ID
            pmid = item.get("uid", "")

            # 获取 pubtype 列表（综述/临床试验等）
            pubtype_list = item.get("pubtype", [])

            papers.append(PaperMetadata(
                title=item.get("title", ""),
                abstract=None,  # esummary 不包含 abstract，需额外 efetch
                authors=authors if authors else None,
                author_affiliations=author_affiliations,
                year=year,
                journal=journal or None,
                doi=doi,
                pmid=pmid,
                pmcid=None,
                source="pubmed",
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                pdf_url=None,
                license=None,
                is_open_access=0,
                citation_count=None,
                raw={"pubtype": pubtype_list},
            ))

        return papers

    def _request_json(self, url: str) -> dict[str, Any]:
        """发送 GET 请求并解析 JSON。"""
        headers = {"User-Agent": self.user_agent}

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                request = urllib.request.Request(url=url, headers=headers, method="GET")
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep * attempt)

        raise RuntimeError(
            f"PubMed 请求失败，已重试 {self.max_retries} 次。最后错误：{last_error}"
        )
