"""
pdf_resolver.py

开放获取 PDF 下载模块 PDF Resolver / Downloader。

作用：
1. 从数据库中筛选开放获取文献；
2. 根据 pdf_url 或 pmcid 构造候选 PDF URL；
3. 尝试下载 PDF；
4. 校验下载结果是否真的是 PDF；
5. 将本地路径写回 papers.local_pdf_path；
6. 将文献状态更新为 pdf_downloaded。

重要原则：
    只下载开放获取文献。
    不做 Sci-Hub、盗版源、绕过访问限制等操作。
"""

from __future__ import annotations

import shutil
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text as sa_text

from app.storage.database import async_session_factory, init_db
from app.storage.file_store import (
    calculate_sha256,
    get_pdf_path,
    get_relative_path,
    is_probably_pdf,
)
from app.storage.repositories import PaperRepository


@dataclass
class PdfDownloadResult:
    """
    PDF 下载结果。

    字段说明：
        paper_id:
            文献 ID。

        success:
            是否下载成功。

        status:
            状态字符串。
            success / skipped / failed / not_pdf / no_url

        message:
            说明信息。

        source_url:
            实际尝试成功的 PDF URL。

        local_pdf_path:
            本地 PDF 相对路径。

        file_size_bytes:
            文件大小。

        sha256:
            文件哈希。
    """

    paper_id: int
    success: bool
    status: str
    message: str
    source_url: Optional[str] = None
    local_pdf_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    sha256: Optional[str] = None


class OpenAccessPdfResolver:
    """
    开放获取 PDF 解析与下载器。

    当前支持：
    1. 使用数据库中的 pdf_url；
    2. 如果有 PMCID，尝试 Europe PMC PDF 渲染链接；
    3. 如果有 PMCID，尝试 PMC PDF 链接。

    注意：
        不是所有开放获取记录都一定能直接下载 PDF。
        有些链接是 HTML 页面，有些需要跳转，有些出版社不提供直接 PDF。
    """

    def __init__(
        self,
        timeout: int = 60,
        max_retries: int = 2,
        retry_sleep: float = 1.0,
        user_agent: str = "ScholarFlow/0.2",
        min_pdf_size_bytes: int = 1024,
    ) -> None:
        """
        初始化下载器。

        参数：
            timeout:
                单次请求超时时间。

            max_retries:
                每个 URL 最大重试次数。

            retry_sleep:
                失败后的等待时间。

            user_agent:
                请求头中的 User-Agent。

            min_pdf_size_bytes:
                最小 PDF 文件大小。
                太小的文件通常是错误页或空文件。
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self.user_agent = user_agent
        self.min_pdf_size_bytes = min_pdf_size_bytes

        self.paper_repo = PaperRepository()

        # 创建不验证证书的 SSL 上下文（解决 Windows 证书链问题）
        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE

    async def list_candidate_papers(
        self,
        limit: int = 20,
        include_already_downloaded: bool = False,
    ) -> list[dict[str, Any]]:
        """
        从数据库中筛选可以尝试下载 PDF 的文献。

        筛选条件：
            1. is_open_access = 1；
            2. 有 pdf_url 或 pmcid；
            3. 默认跳过已经有 local_pdf_path 的文献。
        """
        await init_db()

        conditions = [
            "is_open_access = 1",
            "(pdf_url IS NOT NULL AND pdf_url != '' OR pmcid IS NOT NULL AND pmcid != '')",
        ]

        if not include_already_downloaded:
            conditions.append(
                "(local_pdf_path IS NULL OR local_pdf_path = '')"
            )

        where_sql = " AND ".join(conditions)

        async with async_session_factory() as session:
            result = await session.execute(
                sa_text(
                    f"""
                    SELECT *
                    FROM papers
                    WHERE {where_sql}
                    ORDER BY domain_score DESC, year DESC, id ASC
                    LIMIT :limit;
                    """
                ),
                {"limit": limit},
            )
            rows = result.fetchall()

        return [dict(row._mapping) for row in rows]

    async def download_for_paper(
        self,
        paper: dict[str, Any],
        overwrite: bool = False,
    ) -> PdfDownloadResult:
        """
        为单篇文献下载 PDF。

        参数：
            paper:
                papers 表中的一行记录。

            overwrite:
                如果本地已有 PDF，是否覆盖。
        """
        paper_id = int(paper["id"])
        title = str(paper["title"])
        doi = paper.get("doi")
        existing_local_pdf_path = paper.get("local_pdf_path")

        if existing_local_pdf_path and not overwrite:
            return PdfDownloadResult(
                paper_id=paper_id,
                success=True,
                status="skipped",
                message="该文献已有本地 PDF，跳过下载。",
                local_pdf_path=existing_local_pdf_path,
            )

        candidate_urls = self.build_candidate_pdf_urls(paper)

        if not candidate_urls:
            return PdfDownloadResult(
                paper_id=paper_id,
                success=False,
                status="no_url",
                message="没有可用于下载的 PDF URL 或 PMCID。",
            )

        final_pdf_path = get_pdf_path(
            paper_id=paper_id,
            title=title,
            doi=doi,
        )

        last_message = ""

        for url in candidate_urls:
            try:
                temp_pdf_path = self._download_url_to_temp_file(url)

                if not is_probably_pdf(temp_pdf_path):
                    last_message = f"URL 返回内容不是 PDF：{url}"
                    temp_pdf_path.unlink(missing_ok=True)
                    continue

                file_size = temp_pdf_path.stat().st_size

                if file_size < self.min_pdf_size_bytes:
                    last_message = (
                        f"PDF 文件过小，疑似错误页：{url}，"
                        f"size={file_size}"
                    )
                    temp_pdf_path.unlink(missing_ok=True)
                    continue

                final_pdf_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(temp_pdf_path), str(final_pdf_path))

                sha256 = calculate_sha256(final_pdf_path)
                relative_path = get_relative_path(final_pdf_path)

                await self.paper_repo.update_file_paths(
                    paper_id=paper_id,
                    local_pdf_path=relative_path,
                    status="pdf_downloaded",
                )

                return PdfDownloadResult(
                    paper_id=paper_id,
                    success=True,
                    status="success",
                    message="PDF 下载成功。",
                    source_url=url,
                    local_pdf_path=relative_path,
                    file_size_bytes=file_size,
                    sha256=sha256,
                )

            except Exception as exc:
                last_message = f"下载失败：{url}；错误：{exc}"
                continue

        return PdfDownloadResult(
            paper_id=paper_id,
            success=False,
            status="failed",
            message=last_message or "所有候选 URL 均下载失败。",
        )

    async def download_batch(
        self,
        limit: int = 10,
        overwrite: bool = False,
        include_already_downloaded: bool = False,
    ) -> list[PdfDownloadResult]:
        """
        批量下载开放获取 PDF。

        参数：
            limit:
                最多处理多少篇文献。

            overwrite:
                是否覆盖已有 PDF。

            include_already_downloaded:
                是否把已有 local_pdf_path 的文献也纳入候选。
        """
        papers = await self.list_candidate_papers(
            limit=limit,
            include_already_downloaded=include_already_downloaded,
        )

        results: list[PdfDownloadResult] = []

        for paper in papers:
            result = await self.download_for_paper(
                paper=paper,
                overwrite=overwrite,
            )
            results.append(result)

        return results

    def build_candidate_pdf_urls(
        self,
        paper: dict[str, Any],
    ) -> list[str]:
        """
        根据文献信息构造候选 PDF URL。

        优先级：
            1. 数据库中的 pdf_url；
            2. Europe PMC 的 PDF 渲染链接；
            3. NCBI PMC 的 PDF 入口。

        注意：
            有些 URL 可能返回 HTML 页面，所以下载后必须校验 %PDF。
        """
        urls: list[str] = []

        pdf_url = paper.get("pdf_url")
        pmcid = paper.get("pmcid")

        if pdf_url:
            urls.append(str(pdf_url))

        if pmcid:
            normalized_pmcid = normalize_pmcid(str(pmcid))

            # Europe PMC PDF 渲染链接
            urls.append(
                f"https://europepmc.org/articles/{normalized_pmcid}?pdf=render"
            )

            # NCBI PMC PDF 入口
            urls.append(
                f"https://pmc.ncbi.nlm.nih.gov/articles/{normalized_pmcid}/pdf/"
            )

        # 去重，同时保持顺序
        unique_urls: list[str] = []
        seen = set()

        for url in urls:
            if url and url not in seen:
                unique_urls.append(url)
                seen.add(url)

        return unique_urls

    def _download_url_to_temp_file(
        self,
        url: str,
    ) -> Path:
        """
        下载 URL 内容到临时文件。

        返回：
            临时文件路径。

        说明：
            这里使用流式写入，避免一次性把大 PDF 读入内存。
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/pdf,application/octet-stream,*/*",
        }

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            temp_file = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".pdf",
            )
            temp_path = Path(temp_file.name)

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

                    if status_code < 200 or status_code >= 300:
                        raise RuntimeError(
                            f"HTTP 状态码异常：{status_code}"
                        )

                    with temp_file:
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            temp_file.write(chunk)

                return temp_path

            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                RuntimeError,
            ) as exc:
                last_error = exc
                temp_file.close()
                temp_path.unlink(missing_ok=True)

                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep * attempt)
                else:
                    break

        raise RuntimeError(
            f"URL 下载失败，已重试 {self.max_retries} 次。"
            f"最后错误：{last_error}"
        )


def normalize_pmcid(pmcid: str) -> str:
    """
    标准化 PMCID。

    输入可能是：
        11923967
        PMC11923967

    输出统一为：
        PMC11923967
    """
    value = pmcid.strip()

    if not value:
        return value

    if value.upper().startswith("PMC"):
        number_part = value[3:]
        return f"PMC{number_part}"

    return f"PMC{value}"