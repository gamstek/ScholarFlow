"""
pipeline_routes.py

文件设计目的：
为“文献智能体系统”提供一组统一的数据流程 API 接口，
让前端或外部调用方可以按步骤驱动整条处理流水线。

主要作用：
1. 接收文献采集、PDF 下载、PDF 解析、chunk 构建、FAISS 索引构建等请求；
2. 将请求参数封装成结构化数据并转交给对应的 service 层处理；
3. 统一把 service 执行过程中的异常转换为 HTTP 500 错误返回给调用方。

返回值：
本文件中的各个路由函数都会返回一个 dict，
其内容由对应的 service 函数决定，通常包含执行结果、处理状态、统计信息或错误相关信息。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.pipeline_service import (
    build_chunks_service,
    build_faiss_index_service,
    crawl_literature_service,
    download_open_access_pdfs_service,
    parse_downloaded_pdfs_service,
)


router = APIRouter(
    prefix="/pipeline",
    tags=["pipeline"],
)


class CrawlLiteratureRequest(BaseModel):
    """
    文献采集请求（统一入口，支持多数据源）。
    """

    query: str = Field(
        ...,
        description="检索主题。",
        examples=["human milk oligosaccharides LC-MS/MS structural elucidation"],
    )

    source: str = Field(
        "europe_pmc",
        description=(
            "数据源。可选："
            "europe_pmc / nature / science / cell / arxiv / semantic_scholar"
        ),
    )

    max_results: int = Field(
        20,
        ge=1,
        le=200,
        description="最大检索数量。",
    )

    min_domain_score: float = Field(
        0.25,
        ge=0.0,
        le=1.0,
        description="最低语义相似度阈值（查询与文献的 embedding 余弦相似度）。",
    )

    enhance_query: bool = Field(
        True,
        description="是否自动增强领域相关检索词（仅 europe_pmc 生效）。",
    )


class DownloadPdfsRequest(BaseModel):
    """
    PDF 下载请求。
    """

    limit: int = Field(
        5,
        ge=1,
        le=100,
        description="最多处理多少篇文献。",
    )

    overwrite: bool = Field(
        False,
        description="是否覆盖已有 PDF。",
    )

    include_already_downloaded: bool = Field(
        False,
        description="是否包含已经下载过 PDF 的文献。",
    )


class ParsePdfsRequest(BaseModel):
    """
    PDF 解析请求。
    """

    limit: int = Field(
        5,
        ge=1,
        le=100,
        description="最多解析多少篇 PDF。",
    )

    overwrite: bool = Field(
        False,
        description="是否覆盖已有解析结果。",
    )

    include_parsed: bool = Field(
        False,
        description="是否包含已经 parsed 的文献。",
    )


class BuildChunksRequest(BaseModel):
    """
    chunk 构建请求。
    """

    limit: int = Field(
        5,
        ge=1,
        le=100,
        description="最多处理多少篇文献。",
    )

    max_chars: int = Field(
        2500,
        ge=500,
        le=10000,
        description="每个 chunk 最大字符数。",
    )

    overlap_chars: int = Field(
        300,
        ge=0,
        le=2000,
        description="chunk overlap 字符数。",
    )

    min_chars: int = Field(
        300,
        ge=0,
        le=2000,
        description="过短 chunk 合并阈值。",
    )

    overwrite: bool = Field(
        False,
        description="是否覆盖已有 chunks。",
    )

    include_chunked: bool = Field(
        False,
        description="是否包含已经 chunked 的文献。",
    )

    keep_references: bool = Field(
        False,
        description="是否保留 References 等低价值章节。",
    )


class BuildFaissIndexRequest(BaseModel):
    """
    FAISS 索引构建请求。
    """

    limit: int = Field(
        100,
        ge=1,
        le=5000,
        description="最多处理多少个 pending chunks。",
    )

    batch_size: int = Field(
        4,
        ge=1,
        le=128,
        description="embedding 批处理大小。",
    )

    model_name: str = Field(
        "BAAI/bge-m3",
        description="embedding 模型名称或本地路径。",
    )

    device: Optional[str] = Field(
        None,
        description="embedding 设备，例如 cuda / cpu。",
    )

    rebuild: bool = Field(
        False,
        description="是否重建整个 FAISS 索引。",
    )


@router.post("/crawl-literature")
async def crawl_literature(
    request: CrawlLiteratureRequest,
) -> dict:
    """
    采集文献 metadata（支持多数据源，自动去重排序）。

    支持的数据源：
        - europe_pmc:       Europe PMC（通用生物医学）
        - nature:           Nature 系列期刊
        - science:          Science 系列期刊
        - cell:             Cell Press 系列期刊
        - arxiv:            arXiv 预印本
        - semantic_scholar: Semantic Scholar（通用学术搜索）
    """
    try:
        return await crawl_literature_service(
            query=request.query,
            sources=request.sources,
            max_results=request.max_results,
            min_domain_score=request.min_domain_score,
            enhance_query=request.enhance_query,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.post("/download-pdfs")
async def download_pdfs(
    request: DownloadPdfsRequest,
) -> dict:
    """
    下载开放获取 PDF。
    """
    try:
        return await download_open_access_pdfs_service(
            limit=request.limit,
            overwrite=request.overwrite,
            include_already_downloaded=request.include_already_downloaded,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.post("/parse-pdfs")
async def parse_pdfs(
    request: ParsePdfsRequest,
) -> dict:
    """
    解析已下载 PDF。
    """
    try:
        return await parse_downloaded_pdfs_service(
            limit=request.limit,
            overwrite=request.overwrite,
            include_parsed=request.include_parsed,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.post("/build-chunks")
async def build_chunks(
    request: BuildChunksRequest,
) -> dict:
    """
    将 parsed JSON 构建为 chunks。
    """
    try:
        return await build_chunks_service(
            limit=request.limit,
            max_chars=request.max_chars,
            overlap_chars=request.overlap_chars,
            min_chars=request.min_chars,
            overwrite=request.overwrite,
            include_chunked=request.include_chunked,
            keep_references=request.keep_references,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.post("/build-index")
async def build_index(
    request: BuildFaissIndexRequest,
) -> dict:
    """
    将 pending chunks 向量化并写入 FAISS。
    """
    try:
        return await build_faiss_index_service(
            limit=request.limit,
            batch_size=request.batch_size,
            model_name=request.model_name,
            device=request.device,
            rebuild=request.rebuild,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc