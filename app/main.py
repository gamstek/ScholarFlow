"""
main.py

ScholarFlow 个人文献工作站 — FastAPI 服务入口。

四大功能：
1. 文献检索  POST /search          → Europe PMC 检索 + 入库
2. 文献查询  POST /ask              → RAG 问答（检索 + Ollama 生成）
3. 文献存储  GET  /papers           → 文献库列表/详情/chunks
4. 写综述    POST /review           → 基于本地文献生成 Markdown 综述

辅助接口：
- GET  /health                      健康检查
- GET  /stats                       数据库统计
- POST /chunks/search               只检索 chunks（不生成）
- POST /rag/warmup                  预热 embedding + FAISS
- /pipeline/*                       处理流水线（下载/解析/切块/索引）

运行方式：
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
"""

from __future__ import annotations

import os
import threading
from dotenv import load_dotenv

# 加载 .env 环境变量（必须在其他 import 之前，确保 DATABASE_URL 等已设置）
load_dotenv()
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.pipeline_routes import router as pipeline_router
from app.rag.embedder import DEFAULT_EMBEDDING_MODEL
from app.rag.rag_engine import LocalRagEngine
from app.rag.retriever import LocalChunkRetriever, evidences_to_dicts
from app.services.review_service import generate_review
from app.services.pipeline_service import (
    crawl_literature_service,
    search_papers_service,
    import_single_paper_service,
)
from app.storage.database import async_session_factory, init_db, PROJECT_ROOT
from app.storage.repositories import ChunkRepository, PaperRepository

from sqlalchemy import text as sa_text



# ============================================================
# 0. 配置校验
# ============================================================

def _validate_config() -> None:
    """
    FastAPI 启动时校验配置一致性，打印警告或确认信息。

    不阻塞启动——仅做诊断输出。
    """
    from app.config import get_config

    cfg = get_config()

    print(f"[Config] {cfg.summary()}")

    warnings = cfg.validate()
    if warnings:
        for w in warnings:
            print(f"[Config] ⚠ {w}")
    else:
        print(f"[Config] ✓ 配置校验通过")


# ============================================================
# 1. FastAPI 应用
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    """
    FastAPI lifespan: 初始化数据库，后台预热 embedding 模型。

    优化：BGE-M3 加载耗时 7-11s，移到后台线程不阻塞启动，
    服务器在 ~1s 内就绪，模型在后台 5-7s 热好。
    """
    await init_db()

    # 配置一致性校验
    _validate_config()

    # 后台线程预热 BGE-M3 embedding 模型（不阻塞启动）
    def _warmup():
        try:
            from app.domain.filters import _get_embedder
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _get_embedder(model_name=DEFAULT_EMBEDDING_MODEL, device=device)
            print(f"[Lifespan] BGE-M3 embedding model warmed up ({device})")
        except Exception as exc:
            print(f"[Lifespan] embedding warmup failed: {exc}")

    threading.Thread(target=_warmup, daemon=True).start()

    yield


app = FastAPI(
    title="ScholarFlow-Bio",
    description=(
        "生物医学文献智能体。"
        "支持本地文献检索、chunk 检索和基于 Ollama 的问答。"
    ),
    version="1.3.0",
    lifespan=lifespan,
)

app.include_router(pipeline_router)

# 前端构建产物目录（React SPA）
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

# ============================================================
# 2. 全局缓存
# ============================================================

# 说明：
# embedding 模型和 FAISS 索引加载比较慢。
# 如果每次请求都重新加载，速度会非常灾难。
# 所以这里用简单的全局缓存。
#
# V0 阶段这样足够；
# 后续大规模使用可以改成 dependency injection / worker pool / model service。
_RAG_ENGINE_CACHE: dict[str, LocalRagEngine] = {}
_RETRIEVER_CACHE: dict[str, LocalChunkRetriever] = {}


# ============================================================
# 3. Pydantic 请求 / 响应模型
# ============================================================

class AskRequest(BaseModel):
    """
    RAG 问答请求体。
    """

    question: str = Field(
        ...,
        description="用户问题。",
        examples=["HMO 的 LC-MS/MS 结构解析通常用哪些方法？"],
    )

    top_k: int = Field(
        3,
        ge=1,
        le=20,
        description="检索前 k 个 chunks。本地 8B 模型建议 2~3。",
    )

    min_score: Optional[float] = Field(
        None,
        description="最低相似度分数。可选。",
    )

    section_filter: Optional[list[str]] = Field(
        None,
        description="章节过滤，例如 ['Methods', 'Mass Spectrometry']。",
    )

    year_from: Optional[int] = Field(
        None,
        description="起始年份过滤。",
    )

    year_to: Optional[int] = Field(
        None,
        description="结束年份过滤。",
    )

    max_chars_per_evidence: int = Field(
        800,
        ge=200,
        le=3000,
        description="每条 evidence 放入上下文的最大字符数。",
    )

    language: str = Field(
        "zh",
        description="回答语言：zh 或 en。",
    )

    generate: bool = Field(
        True,
        description="是否调用 Ollama 生成回答。False 表示只检索证据。",
    )

    embedding_model: str = Field(
        DEFAULT_EMBEDDING_MODEL,
        description="embedding 模型名称或本地路径。",
    )

    embedding_device: Optional[str] = Field(
        None,
        description="embedding 设备，例如 cuda / cpu。None 表示自动。",
    )

    ollama_model: str = Field(
        "qwen3:8b",
        description="Ollama 生成模型名称。",
    )

    ollama_base_url: str = Field(
        "http://localhost:11434",
        description="Ollama 服务地址。",
    )

    temperature: float = Field(
        0.2,
        ge=0.0,
        le=2.0,
        description="生成温度。",
    )

    num_ctx: int = Field(
        4096,
        ge=512,
        description="Ollama 上下文窗口大小。",
    )

    num_predict: int = Field(
        512,
        ge=64,
        le=4096,
        description="最大输出 token 数。",
    )

    timeout: int = Field(
        900,
        ge=30,
        description="Ollama HTTP 超时时间，单位秒。",
    )

    think_mode: str = Field(
        "off",
        description=(
            "Qwen3 thinking 控制："
            "off=think false；omit=不发送 think 字段；on=think true。"
            "RAG 推荐 off。"
        ),
    )


class ChunkSearchRequest(BaseModel):
    """
    chunk 检索请求体。
    """

    query: str = Field(
        ...,
        description="检索问题或关键词。",
        examples=["How are human milk oligosaccharides characterized by LC-MS/MS?"],
    )

    top_k: int = Field(
        5,
        ge=1,
        le=50,
        description="返回前 k 个 chunks。",
    )

    min_score: Optional[float] = Field(
        None,
        description="最低相似度分数。",
    )

    section_filter: Optional[list[str]] = Field(
        None,
        description="章节过滤。",
    )

    year_from: Optional[int] = Field(
        None,
        description="起始年份过滤。",
    )

    year_to: Optional[int] = Field(
        None,
        description="结束年份过滤。",
    )

    embedding_model: str = Field(
        DEFAULT_EMBEDDING_MODEL,
        description="embedding 模型名称或本地路径。",
    )

    embedding_device: Optional[str] = Field(
        None,
        description="embedding 设备，例如 cuda / cpu。",
    )


class WarmupRequest(BaseModel):
    """
    预热请求体。
    """

    embedding_model: str = Field(
        DEFAULT_EMBEDDING_MODEL,
        description="embedding 模型名称或本地路径。",
    )

    embedding_device: Optional[str] = Field(
        None,
        description="embedding 设备，例如 cuda / cpu。",
    )

    ollama_model: str = Field(
        "qwen3:8b",
        description="Ollama 生成模型名称。",
    )

    ollama_base_url: str = Field(
        "http://localhost:11434",
        description="Ollama 服务地址。",
    )


# ============================================================
# 4. 工具函数
# ============================================================

def parse_think_mode(think_mode: str) -> Optional[bool]:
    """
    将 think_mode 字符串转换成 Python 值。

    off:
        返回 False，发送 think=false。

    on:
        返回 True，发送 think=true。

    omit:
        返回 None，不发送 think 字段。
    """
    value = think_mode.lower().strip()

    if value == "off":
        return False

    if value == "on":
        return True

    if value == "omit":
        return None

    raise HTTPException(
        status_code=400,
        detail="think_mode 只能是 off / on / omit。",
    )


def make_retriever_cache_key(
    embedding_model: str,
    embedding_device: Optional[str],
) -> str:
    """
    构造 retriever 缓存 key。
    """
    return f"{embedding_model}::{embedding_device}"


def make_rag_engine_cache_key(
    request: AskRequest | WarmupRequest,
    think: Optional[bool] = False,
) -> str:
    """
    构造 RAG engine 缓存 key。

    注意：
        不同 embedding 模型、设备、Ollama 模型都应该分开缓存。
    """
    embedding_model = getattr(request, "embedding_model")
    embedding_device = getattr(request, "embedding_device")
    ollama_model = getattr(request, "ollama_model")
    ollama_base_url = getattr(request, "ollama_base_url")

    return (
        f"embedding={embedding_model}::"
        f"device={embedding_device}::"
        f"ollama={ollama_model}::"
        f"base={ollama_base_url}::"
        f"think={think}"
    )


def get_cached_retriever(
    embedding_model: str,
    embedding_device: Optional[str],
) -> LocalChunkRetriever:
    """
    获取缓存的 LocalChunkRetriever。

    如果缓存中没有，则创建并缓存。
    """
    key = make_retriever_cache_key(
        embedding_model=embedding_model,
        embedding_device=embedding_device,
    )

    if key not in _RETRIEVER_CACHE:
        _RETRIEVER_CACHE[key] = LocalChunkRetriever(
            model_name=embedding_model,
            device=embedding_device,
        )

    return _RETRIEVER_CACHE[key]


def get_cached_rag_engine(
    request: AskRequest,
) -> LocalRagEngine:
    """
    获取缓存的 LocalRagEngine。
    """
    think = parse_think_mode(request.think_mode)

    key = make_rag_engine_cache_key(
        request=request,
        think=think,
    )

    if key not in _RAG_ENGINE_CACHE:
        _RAG_ENGINE_CACHE[key] = LocalRagEngine(
            embedding_model_name=request.embedding_model,
            embedding_device=request.embedding_device,
            temperature=request.temperature,
            num_ctx=request.num_ctx,
            num_predict=request.num_predict,
        )

    return _RAG_ENGINE_CACHE[key]


async def row_count(table_name: str) -> int:
    """
    查询某张表的行数。

    注意：
        table_name 不接受用户输入，只在内部使用。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            sa_text(f"SELECT COUNT(*) AS count FROM {table_name};")
        )
        row = result.fetchone()

    return int(row._mapping["count"]) if row else 0


# ============================================================
# 5. API 路由
# ============================================================
@app.get("/")
def index() -> FileResponse:
    """
    Web 前端首页。

    返回 React 构建产物（frontend/dist/index.html）。
    禁用缓存，确保每次构建后浏览器加载最新的 JS/CSS。
    """
    return FileResponse(
        FRONTEND_DIST / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    """
    健康检查接口（含模型信息）。
    """
    import httpx
    from app.config import get_config

    cfg = get_config()
    embedding_model = DEFAULT_EMBEDDING_MODEL

    # 根据配置确定模型信息
    llm_provider = cfg.llm_backend
    llm_model = cfg.active_model_name
    llm_base_url = cfg.active_base_url

    # 检测 LLM 是否可用
    llm_status = "unknown"
    if cfg.llm_backend == "ollama":
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{llm_base_url}/api/tags")
                llm_status = "ok" if resp.status_code == 200 else f"error:{resp.status_code}"
        except Exception:
            llm_status = "offline"
    else:
        # 云端 API：检查 key 是否配置
        llm_status = "ok" if cfg.cloud_api_key else "no_api_key"

    return {
        "status": "ok",
        "service": "ScholarFlow",
        "version": "1.2.0",
        "llm": {
            "provider": llm_provider,
            "model": llm_model,
            "base_url": llm_base_url,
            "status": llm_status,
        },
        "embedding": {
            "provider": "sentence-transformers",
            "model": embedding_model,
        },
    }


class TranslateRequest(BaseModel):
    """翻译请求。"""
    text: str = Field(..., description="待翻译的英文文本。")


@app.post("/translate")
async def translate(request: TranslateRequest) -> dict[str, Any]:
    """
    将英文文本翻译为中文（使用配置的 LLM）。

    根据 .env 中 LLM_BACKEND 选择 ollama 或云端 API。
    """
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空。")

    # 仅翻译英文摘要（检测是否含中文字符）
    has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in text)
    if has_cjk:
        return {"translated": text, "original": text, "note": "已为中文，无需翻译"}

    prompt = (
        "你是一个专业的学术翻译助手。请将以下英文学术摘要翻译成中文，"
        "保持专业术语的准确性，语言流畅自然。只返回翻译结果，不要加任何解释。\n\n"
        f"{text}"
    )

    try:
        from app.llm_factory import create_raw_llm, LLMClientError
        from app.config import get_config

        cfg = get_config()
        client = create_raw_llm()
        translated = await client.achat(
            system_prompt="你是一个专业的学术翻译助手。",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=cfg.translate_max_tokens,
        )

        return {"translated": translated, "original": text}
    except LLMClientError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"翻译 API 错误: {exc.response_body or str(exc)}"
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/stats")
async def stats() -> dict[str, Any]:
    """
    查看当前本地知识库统计信息。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            sa_text("""
                SELECT status, COUNT(*) AS count
                FROM papers
                GROUP BY status
                ORDER BY status;
            """)
        )
        paper_status = [dict(row._mapping) for row in result.fetchall()]

        result = await session.execute(
            sa_text("""
                SELECT embedding_status, COUNT(*) AS count
                FROM chunks
                GROUP BY embedding_status
                ORDER BY embedding_status;
            """)
        )
        chunk_status = [dict(row._mapping) for row in result.fetchall()]

    return {
        "papers_total": await row_count("papers"),
        "chunks_total": await row_count("chunks"),
        "compounds_total": await row_count("compounds"),
        "spectra_total": await row_count("spectra"),
        "paper_status": paper_status,
        "chunk_status": chunk_status,
        "rag_engine_cache_size": len(_RAG_ENGINE_CACHE),
        "retriever_cache_size": len(_RETRIEVER_CACHE),
    }


@app.get("/institutions")
async def list_institutions(
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    """
    返回本地文献库中机构排名（按出现频率降序）。

    从 papers.authors_json 提取所有 institution 字段，聚合计数。
    """
    from app.harvest.literature.author_utils import parse_authors_json
    from app.storage.models import Paper as PaperModel
    from sqlalchemy import select as sa_select

    async with async_session_factory() as session:
        result = await session.execute(
            sa_select(PaperModel.authors_json).where(PaperModel.authors_json.isnot(None))
        )
        rows = result.fetchall()

    counter: dict[str, int] = {}
    for row in rows:
        authors = parse_authors_json(row[0])
        for a in authors:
            inst = a.get("institution")
            if inst:
                # 处理多机构情况（分号分隔）
                for part in inst.split(";"):
                    part = part.strip()
                    if part:
                        counter[part] = counter.get(part, 0) + 1

    sorted_insts = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    top = [{"name": k, "count": v} for k, v in sorted_insts[:limit]]

    return {
        "institutions": top,
        "total_unique": len(counter),
    }


@app.get("/papers")
async def list_papers(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    min_domain_score: Optional[float] = Query(None),
) -> dict[str, Any]:
    """
    查看本地文献库。
    """
    paper_repo = PaperRepository()

    papers = await paper_repo.list_papers(
        limit=limit,
        offset=offset,
        status=status,
        min_domain_score=min_domain_score,
    )

    return {
        "limit": limit,
        "offset": offset,
        "count": len(papers),
        "papers": papers,
    }


@app.get("/papers/{paper_id}")
async def get_paper(
    paper_id: int,
) -> dict[str, Any]:
    """
    查看单篇文献详情。
    """
    paper_repo = PaperRepository()
    paper = await paper_repo.get_paper(paper_id)

    if paper is None:
        raise HTTPException(
            status_code=404,
            detail=f"paper_id={paper_id} 不存在。",
        )

    return paper


@app.get("/papers/{paper_id}/chunks")
async def get_paper_chunks(
    paper_id: int,
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """
    查看某篇文献的 chunks。
    """
    paper_repo = PaperRepository()
    paper = await paper_repo.get_paper(paper_id)

    if paper is None:
        raise HTTPException(
            status_code=404,
            detail=f"paper_id={paper_id} 不存在。",
        )

    chunk_repo = ChunkRepository()
    chunks = await chunk_repo.list_chunks_by_paper(paper_id)

    return {
        "paper_id": paper_id,
        "paper_title": paper["title"],
        "count": min(len(chunks), limit),
        "total_chunks": len(chunks),
        "chunks": chunks[:limit],
    }


@app.get("/papers/{paper_id}/text")
async def get_paper_text(paper_id: int) -> dict[str, Any]:
    """
    获取文献全文 — 将 chunks 按 chunk_index 拼回完整文稿。
    """
    paper_repo = PaperRepository()
    paper = await paper_repo.get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"paper_id={paper_id} 不存在。")

    chunk_repo = ChunkRepository()
    chunks = await chunk_repo.list_chunks_by_paper(paper_id)

    # 按 chunk_index 排序后拼接
    sorted_chunks = sorted(chunks, key=lambda c: c.get("chunk_index", 0))
    full_text = "\n\n".join(
        (c.get("section_title") or "") + "\n" + (c.get("text", ""))
        for c in sorted_chunks
    )

    return {
        "paper_id": paper_id,
        "paper_title": paper["title"],
        "total_chunks": len(chunks),
        "full_text": full_text,
    }


@app.get("/papers/{paper_id}/pdf")
async def get_paper_pdf(paper_id: int):
    """
    返回文献 PDF 文件（如果有本地副本）。
    """
    paper_repo = PaperRepository()
    paper = await paper_repo.get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"paper_id={paper_id} 不存在。")

    local_path = paper.get("local_pdf_path")
    if not local_path:
        raise HTTPException(status_code=404, detail="该文献暂无本地 PDF。请先通过 /pipeline 下载。")

    pdf_path = PROJECT_ROOT / local_path
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF 文件不存在：{pdf_path}")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"paper_{paper_id}.pdf",
    )


@app.post("/chunks/search")
async def search_chunks(
    request: ChunkSearchRequest,
) -> dict[str, Any]:
    """
    只检索 chunks，不调用 Ollama。

    适合用于：
    1. 调试召回；
    2. 查看 RAG 证据；
    3. 判断问题是否能从本地库中找到依据。
    """
    try:
        retriever = get_cached_retriever(
            embedding_model=request.embedding_model,
            embedding_device=request.embedding_device,
        )

        evidences = await retriever.retrieve(
            query=request.query,
            top_k=request.top_k,
            min_score=request.min_score,
            section_filter=request.section_filter,
            year_from=request.year_from,
            year_to=request.year_to,
        )

        return {
            "query": request.query,
            "top_k": request.top_k,
            "count": len(evidences),
            "sources": evidences_to_dicts(evidences),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post("/ask")
async def ask(
    request: AskRequest,
) -> dict[str, Any]:
    """
    本地 RAG 问答接口。

    流程：
        question
            ↓
        FAISS 检索
            ↓
        数据库取 chunk 原文
            ↓
        Ollama 生成回答
            ↓
        返回 answer + sources
    """
    try:
        engine = get_cached_rag_engine(request)

        result = await engine.ask(
            question=request.question,
            top_k=request.top_k,
            min_score=request.min_score,
            section_filter=request.section_filter,
            year_from=request.year_from,
            year_to=request.year_to,
            max_chars_per_evidence=request.max_chars_per_evidence,
            language=request.language,
            generate=request.generate,
        )

        return {
            "question": result.question,
            "answer": result.answer,
            "model": result.model,
            "sources": result.sources,
            "context": result.context if not request.generate else None,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# 6. 文献检索 + 文献综述
# ============================================================

class SearchRequest(BaseModel):
    """文献检索请求。"""

    query: str = Field(
        "",
        description="检索关键词或主题。如果使用 natural_query，此字段可为空。",
        examples=["human milk oligosaccharides LC-MS/MS"],
    )

    natural_query: Optional[str] = Field(
        None,
        description=(
            "自然语言输入。如果提供，会先调用 LLM 提取关键词和领域，"
            "再用提取的关键词检索。例如：'我想找母乳低聚糖结构鉴定的文章'"
        ),
    )

    sources: list[str] = Field(
        ["europe_pmc"],
        description=(
            "数据源列表。可选："
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
    sort_by: str = Field(
        "relevance",
        description="排序方式：relevance（相关度）/ year（年份）/ citations（引用量）。",
    )
    sort_order: str = Field(
        "desc",
        description="排序顺序：asc（升序）/ desc（降序）。",
    )
    author: Optional[str] = Field(
        None,
        description="按作者名过滤。例如 'Geoffrey Hinton'。",
    )
    journal: Optional[str] = Field(
        None,
        description="按期刊名过滤。例如 'Nature'。仅 europe_pmc 源生效。",
    )
    preprint_sources: Optional[list[str]] = Field(
        None,
        description="OpenAlex 预印本源 ID 列表。如 ['S4306402567','S3005729997']。仅 openalex 源生效。",
    )
    institution: Optional[str] = Field(
        None,
        description="按机构名筛选。例如 'MIT' 或 'CSAIL'。仅 OpenAlex / PubMed 生效。",
    )
    language: Optional[str] = Field(
        None,
        description="文献语言：zh=中文 / en=外文 / null=不限。仅 europe_pmc/pubmed/openalex 生效。",
    )
    max_total: Optional[int] = Field(
        None,
        ge=1,
        le=500,
        description="总计最多返回篇数（跨源汇总后截断）。设置后忽略 max_results。",
    )


class ReviewRequest(BaseModel):
    """文献综述生成请求。"""

    topic: str = Field(
        ...,
        description="综述主题。",
        examples=["HMO 的 LC-MS/MS 结构解析方法"],
    )
    top_k: int = Field(
        10,
        ge=1,
        le=30,
        description="检索前 k 个 chunks 作为证据。",
    )
    min_score: Optional[float] = Field(
        None,
        description="最低相似度分数。",
    )
    max_chars_per_evidence: int = Field(
        1000,
        ge=200,
        le=3000,
        description="每条证据放入 prompt 的最大字符数。",
    )
    temperature: float = Field(
        0.3,
        ge=0.0,
        le=2.0,
        description="生成温度，综述建议 0.3~0.5。",
    )
    num_predict: int = Field(
        2048,
        ge=64,
        le=8192,
        description="最大输出 token 数。",
    )


@app.post("/search")
async def search(request: SearchRequest) -> dict[str, Any]:
    """
    文献检索：仅检索 + 评分 + 在库检查，不自动入库。

    支持两种输入模式：
    1. 直接输入关键词（query 字段）
    2. 自然语言输入（natural_query 字段）→ LLM 自动提取关键词 + 领域

    返回结果包含每篇论文的在库状态（in_library）和 paper_id，
    库外论文可通过 POST /papers/import 入库。
    """
    try:
        query = request.query.strip()
        keywords = None
        domain = None

        # 自然语言模式：LLM 提取关键词
        if request.natural_query and request.natural_query.strip():
            from app.agent.keyword_extractor import extract_keywords

            extraction = extract_keywords(request.natural_query)

            keywords = extraction.keywords
            domain = extraction.domain

            # 用提取的关键词拼接为检索 query
            query = " ".join(keywords) if keywords else request.natural_query.strip()

        if not query and not (request.author and request.author.strip()) and not (request.institution and request.institution.strip()):
            raise HTTPException(
                status_code=400,
                detail="必须提供 query、natural_query、author 或 institution。",
            )

        result = await search_papers_service(
            query=query,
            sources=request.sources,
            max_results=request.max_results,
            enhance_query=request.enhance_query,
            keywords=keywords,
            domain=domain,
            sort_by=request.sort_by,
            sort_order=request.sort_order,
            author=request.author,
            journal=request.journal,
            preprint_sources=request.preprint_sources,
            institution=request.institution,
            language=request.language,
            max_total=request.max_total,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post("/search/stream")
async def search_stream(request: SearchRequest):
    """
    流式文献检索：通过 SSE（Server-Sent Events）逐源推送进度，最后推送完整结果。

    SSE 事件格式：
        data: {"type": "progress", "current": 10, "total": 30, "source": "europe_pmc"}
        data: {"type": "result", ...完整 SearchResult...}

    前端可通过 EventSource 或 fetch + ReadableStream 读取。
    """
    try:
        query = request.query.strip()
        keywords = None
        domain = None

        if request.natural_query and request.natural_query.strip():
            from app.agent.keyword_extractor import extract_keywords
            extraction = extract_keywords(request.natural_query)
            keywords = extraction.keywords
            domain = extraction.domain
            query = " ".join(keywords) if keywords else request.natural_query.strip()

        if not query and not (request.author and request.author.strip()) and not (request.institution and request.institution.strip()):
            raise HTTPException(
                status_code=400,
                detail="必须提供 query、natural_query、author 或 institution。",
            )

        from app.services.pipeline_service import search_papers_stream_service

        async def event_stream():
            async for event in search_papers_stream_service(
                query=query,
                sources=request.sources,
                max_results=request.max_results,
                enhance_query=request.enhance_query,
                keywords=keywords,
                domain=domain,
                sort_by=request.sort_by,
                sort_order=request.sort_order,
                author=request.author,
                journal=request.journal,
                preprint_sources=request.preprint_sources,
                institution=request.institution,
                language=request.language,
                max_total=request.max_total,
            ):
                yield event

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post("/rag/warmup")
def warmup(
    request: WarmupRequest,
) -> dict[str, Any]:
    """
    预加载 embedding 模型和 FAISS 索引，减少首次请求等待时间。
    """
    try:
        retriever = get_cached_retriever(
            embedding_model=request.embedding_model,
            embedding_device=request.embedding_device,
        )
        return {
            "status": "ok",
            "message": "RAG retriever 已预热。",
            "embedding_model": request.embedding_model,
            "embedding_device": request.embedding_device,
            "faiss_ntotal": retriever.vector_store.ntotal,
            "retriever_cache_size": len(_RETRIEVER_CACHE),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post("/review")
async def review(request: ReviewRequest) -> dict[str, Any]:
    """
    文献综述：基于本地文献库生成 Markdown 综述。
    """
    try:
        result = await generate_review(
            topic=request.topic,
            top_k=request.top_k,
            min_score=request.min_score,
            max_chars_per_evidence=request.max_chars_per_evidence,
            temperature=request.temperature,
            num_predict=request.num_predict,
        )
        return {
            "topic": result.topic,
            "review": result.review,
            "sources": result.sources,
            "evidence_count": result.evidence_count,
            "model": result.model,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


# ============================================================
# 7. 单篇论文入库 + 后台流水线触发
# ============================================================

class PaperImportRequest(BaseModel):
    """单篇论文入库请求。"""

    title: str = Field(..., description="论文标题。")
    abstract: Optional[str] = Field(None, description="论文摘要。")
    authors: Optional[list[str]] = Field(None, description="作者列表。")
    year: Optional[int] = Field(None, description="发表年份。")
    journal: Optional[str] = Field(None, description="期刊。")
    doi: Optional[str] = Field(None, description="DOI。")
    pmid: Optional[str] = Field(None, description="PMID。")
    pmcid: Optional[str] = Field(None, description="PMCID。")
    source: str = Field("manual_import", description="来源。")
    url: Optional[str] = Field(None, description="文献 URL。")
    pdf_url: Optional[str] = Field(None, description="PDF URL。")
    license: Optional[str] = Field(None, description="许可证。")
    is_open_access: int = Field(0, description="是否开放获取。")
    domain_score: float = Field(0.0, description="领域相关性评分。")


@app.post("/papers/import")
async def import_paper(request: PaperImportRequest) -> dict[str, Any]:
    """
    单篇论文入库（metadata）。

    入库后可通过 POST /papers/{id}/process 触发完整流水线
    （下载 PDF → 解析 → 切块 → 索引）。
    """
    try:
        result = await import_single_paper_service(
            title=request.title,
            abstract=request.abstract,
            authors=request.authors,
            year=request.year,
            journal=request.journal,
            doi=request.doi,
            pmid=request.pmid,
            pmcid=request.pmcid,
            source=request.source,
            url=request.url,
            pdf_url=request.pdf_url,
            license=request.license,
            is_open_access=request.is_open_access,
            domain_score=request.domain_score,
        )
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.post("/papers/{paper_id}/process")
async def process_paper(
    paper_id: int,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """
    对已入库论文触发后台流水线：
    下载 PDF → 解析 → 切块 → 索引。

    立即返回任务状态，流水线在后台异步执行。
    """
    paper_repo = PaperRepository()
    paper = await paper_repo.get_paper(paper_id)

    if paper is None:
        raise HTTPException(
            status_code=404,
            detail=f"paper_id={paper_id} 不存在。",
        )

    # 注册后台任务
    background_tasks.add_task(_run_pipeline_for_paper, paper_id)

    return {
        "paper_id": paper_id,
        "title": paper["title"],
        "status": paper.get("status", "metadata_only"),
        "message": "后台流水线已触发：下载 PDF → 解析 → 切块 → 索引。"
                   "可通过 GET /papers/{id} 查看进度。",
    }


@app.post("/papers/upload-pdf")
async def upload_standalone_pdf(
    file: UploadFile = File(...),
    title: Optional[str] = Query(None, description="可选标题，不填则用文件名"),
    background_tasks: BackgroundTasks = None,
) -> dict[str, Any]:
    """
    独立上传 PDF 入库。

    无需预先检索入库，直接上传任意 PDF 文件：
    系统创建 paper 记录 → 保存 PDF → 触发 解析 → 切块 → 索引。
    """
    # 验证文件类型
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="请上传 PDF 格式文件。",
        )

    # 用文件名作为标题（去掉 .pdf 后缀），或使用用户提供的标题
    paper_title = title.strip() if title and title.strip() else file.filename.rsplit(".", 1)[0]

    # 创建 paper 记录
    paper_repo = PaperRepository()
    paper_id = await paper_repo.upsert_paper(
        title=paper_title,
        source="manual_upload",
        status="metadata_only",
    )

    # 保存 PDF
    pdf_dir = PROJECT_ROOT / "data" / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    save_filename = f"paper_{paper_id}.pdf"
    save_path = pdf_dir / save_filename
    relative_path = f"data/pdfs/{save_filename}"

    content = await file.read()
    save_path.write_bytes(content)

    # 更新文件路径和状态
    await paper_repo.update_file_paths(
        paper_id,
        local_pdf_path=relative_path,
        status="pdf_downloaded",
    )
    await paper_repo.update_pipeline_progress(
        paper_id, step="pdf_uploaded", clear_error=True,
    )

    # 触发后台流水线
    if background_tasks:
        background_tasks.add_task(_run_pipeline_for_paper, paper_id)

    return {
        "paper_id": paper_id,
        "title": paper_title,
        "filename": file.filename,
        "saved_path": relative_path,
        "status": "pdf_downloaded",
        "message": "PDF 上传成功，已创建文献记录并触发解析 → 切块 → 索引流水线。",
    }


@app.post("/papers/{paper_id}/upload-pdf")
async def upload_paper_pdf(
    paper_id: int,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
) -> dict[str, Any]:
    """
    手动上传 PDF 文件并触发处理流水线。

    用于自动下载失败时的备选方案：
    用户手动下载 PDF → 上传到此处 → 系统保存并触发 解析 → 切块 → 索引。
    """
    paper_repo = PaperRepository()
    paper = await paper_repo.get_paper(paper_id)

    if paper is None:
        raise HTTPException(
            status_code=404,
            detail=f"paper_id={paper_id} 不存在。",
        )

    # 验证文件类型
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="请上传 PDF 格式文件。",
        )

    # 保存到 data/pdfs/ 目录
    pdf_dir = PROJECT_ROOT / "data" / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    save_filename = f"paper_{paper_id}.pdf"
    save_path = pdf_dir / save_filename
    relative_path = f"data/pdfs/{save_filename}"

    content = await file.read()
    save_path.write_bytes(content)

    # 更新数据库
    await paper_repo.update_file_paths(
        paper_id,
        local_pdf_path=relative_path,
        status="pdf_downloaded",
    )
    await paper_repo.update_pipeline_progress(
        paper_id, step="pdf_uploaded", clear_error=True,
    )

    # 触发后台流水线（从解析开始，跳过下载步骤）
    if background_tasks:
        background_tasks.add_task(_run_pipeline_for_paper, paper_id)

    return {
        "paper_id": paper_id,
        "title": paper["title"],
        "filename": file.filename,
        "saved_path": relative_path,
        "status": "pdf_downloaded",
        "message": "PDF 上传成功，已触发解析 → 切块 → 索引流水线。",
    }


@app.delete("/papers/{paper_id}")
async def delete_paper(paper_id: int) -> dict[str, Any]:
    """
    删除文献记录，包括：
    - 数据库中的 paper 及关联的 chunks（级联删除）
    - 本地 PDF 文件和文本文件
    """
    paper_repo = PaperRepository()
    paper = await paper_repo.get_paper(paper_id)

    if paper is None:
        raise HTTPException(
            status_code=404,
            detail=f"paper_id={paper_id} 不存在。",
        )

    # 删除本地 PDF 文件
    pdf_path = paper.get("local_pdf_path")
    if pdf_path:
        full_pdf_path = PROJECT_ROOT / pdf_path
        if full_pdf_path.exists():
            full_pdf_path.unlink()

    # 删除本地文本文件
    text_path = paper.get("local_text_path")
    if text_path:
        full_text_path = PROJECT_ROOT / text_path
        if full_text_path.exists():
            full_text_path.unlink()

    # 从数据库删除（级联删除 chunks）
    deleted = await paper_repo.delete_paper(paper_id)

    return {
        "deleted": deleted,
        "paper_id": paper_id,
        "title": paper.get("title"),
    }


async def _run_pipeline_for_paper(paper_id: int) -> None:
    """
    后台流水线：对单篇论文执行完整处理。

    下载 PDF → 解析 → 切块 → 索引。
    每步更新 pipeline_step 和 pipeline_error 到数据库，供前端查询进度。
    """
    import logging

    logger = logging.getLogger("scholarflow.pipeline")
    repo = PaperRepository()

    async def set_step(step: str) -> None:
        logger.info("[paper %d] %s", paper_id, step)
        await repo.update_pipeline_progress(paper_id, step=step, clear_error=True)

    async def set_error(step: str, err_msg: str) -> None:
        logger.warning("[paper %d] %s 失败: %s", paper_id, step, err_msg)
        await repo.update_pipeline_progress(paper_id, step=step, error=err_msg)

    try:
        # Step 1: 下载 PDF
        await set_step("downloading_pdf")
        from app.harvest.literature.pdf_resolver import OpenAccessPdfResolver

        resolver = OpenAccessPdfResolver()
        candidates = await resolver.list_candidate_papers(
            limit=100,
            include_already_downloaded=False,
        )
        target = next((c for c in candidates if c.get("id") == paper_id), None)

        download_failed = False
        if target:
            result = await resolver.download_for_paper(target, overwrite=False)
            if result.success:
                logger.info("[paper %d] PDF 下载成功", paper_id)
            else:
                await set_error("downloading_pdf", f"PDF 下载失败: {result.message}")
                download_failed = True
        else:
            logger.info("[paper %d] 无需下载 PDF（已下载或无候选）", paper_id)

        # 检查是否有 PDF 文件可用
        paper = await repo.get_paper(paper_id)
        pdf_path = paper.get("local_pdf_path") if paper else None
        if not pdf_path or not (PROJECT_ROOT / pdf_path).exists():
            if download_failed:
                # 下载失败且无 PDF 文件，中止流水线
                await repo.update_pipeline_progress(
                    paper_id,
                    step="failed",
                    error=f"PDF 下载失败，无法继续后续步骤。可手动上传 PDF 文件。",
                )
                return
            else:
                # 无 PDF 来源（非开放获取），标记为仅元数据
                await repo.update_pipeline_progress(
                    paper_id,
                    step="done",
                    error=None,
                )
                return

        # Step 2: 解析 PDF
        await set_step("parsing_pdf")
        from app.services.pipeline_service import (
            list_pdf_parse_candidates,
            parse_single_pdf_service,
        )
        from app.document.pdf_parser import PdfParser

        parser = PdfParser()
        parse_candidates = await list_pdf_parse_candidates(limit=200, include_parsed=False)

        parse_target = next((c for c in parse_candidates if c["id"] == paper_id), None)

        if parse_target:
            try:
                parse_result = await parse_single_pdf_service(
                    paper=parse_target,
                    parser=parser,
                    overwrite=False,
                )
                if parse_result.get("success"):
                    logger.info("[paper %d] PDF 解析成功", paper_id)
                else:
                    await set_error("parsing_pdf", parse_result.get("message", "解析失败"))
            except Exception as exc:
                await set_error("parsing_pdf", str(exc))
        else:
            logger.info("[paper %d] 无需解析（已解析或无 PDF）", paper_id)

        # Step 3: 切块
        await set_step("building_chunks")
        from app.services.pipeline_service import (
            list_chunk_candidates,
            build_chunks_for_single_paper_service,
        )
        from app.document.chunker import SectionBasedChunker

        chunker = SectionBasedChunker()
        chunk_candidates = await list_chunk_candidates(limit=200, include_chunked=False)

        chunk_target = next((c for c in chunk_candidates if c["id"] == paper_id), None)

        if chunk_target:
            try:
                chunk_result = await build_chunks_for_single_paper_service(
                    paper=chunk_target,
                    chunker=chunker,
                    overwrite=False,
                )
                if chunk_result.get("success"):
                    logger.info("[paper %d] chunks 构建成功: %d chunks",
                                paper_id, chunk_result.get("chunk_count", 0))
                else:
                    await set_error("building_chunks", chunk_result.get("message", "切块失败"))
            except Exception as exc:
                await set_error("building_chunks", str(exc))
        else:
            logger.info("[paper %d] 无需切块（已切块或无文本）", paper_id)

        # Step 4: FAISS 索引
        await set_step("building_index")
        from app.services.pipeline_service import build_faiss_index_service

        try:
            index_result = await build_faiss_index_service(limit=200)
            logger.info("[paper %d] FAISS 索引完成: %s",
                         paper_id, index_result.get("message", ""))
        except Exception as exc:
            await set_error("building_index", str(exc))

        # 检查是否有错误发生
        final_paper = await repo.get_paper(paper_id)
        if final_paper and final_paper.get("pipeline_error"):
            await repo.update_pipeline_progress(paper_id, step="failed")
        else:
            await set_step("done")

    except Exception as exc:
        logger.error("[paper %d] 流水线执行失败: %s", paper_id, exc, exc_info=True)
        await repo.update_pipeline_progress(paper_id, step="failed", error=str(exc))


# ============================================================
# 8. Agent 对话
# ============================================================

class AgentChatRequest(BaseModel):
    """Agent 对话请求。"""

    message: str = Field(
        ...,
        description="用户消息。",
        examples=["帮我找关于 CRISPR 基因编辑在农作物改良方面的论文"],
    )
    session_id: Optional[str] = Field(
        None,
        description="会话 ID。为空则自动创建新会话。传入已有 ID 则继续该会话（多轮对话）。",
    )
    model: str = Field("qwen3:8b", description="Ollama 模型名称。")
    base_url: str = Field("http://localhost:11434", description="Ollama 服务地址。")
    temperature: float = Field(0.3, ge=0.0, le=2.0, description="生成温度。")
    num_ctx: int = Field(4096, ge=512, description="上下文窗口大小。")
    search_depth: str = Field(
        "deep",
        description="搜索深度：quick=快速（仅标题年份），deep=深度（完整 metadata + 入库建议）。",
    )


@app.post("/agent/chat")
async def agent_chat(request: AgentChatRequest) -> dict[str, Any]:
    """
    Agent 对话入口（支持多轮上下文记忆）。

    Agent 会自动决策调用哪个 Tool：
    - search_papers（检索论文）
    - view_paper（查看论文）
    - ask_paper（RAG 问答）
    - write_review（写综述）

    传入 session_id 可继续已有会话，Agent 会参考历史对话理解上下文。
    """
    try:
        from app.agent.agent import run_agent

        result = run_agent(
            message=request.message,
            session_id=request.session_id,
            model=request.model,
            base_url=request.base_url,
            temperature=request.temperature,
            num_ctx=request.num_ctx,
            search_depth=request.search_depth,
        )

        return {
            "answer": result["answer"],
            "tool_calls": result["tool_calls"],
            "session_id": result["session_id"],
            "model": request.model,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@app.get("/agent/sessions")
async def agent_list_sessions() -> dict[str, Any]:
    """列出所有 Agent 对话会话。"""
    from app.agent.agent import SessionManager

    return {"sessions": SessionManager.list_sessions()}


@app.get("/agent/sessions/{session_id}")
async def agent_get_session(session_id: str) -> dict[str, Any]:
    """获取指定会话的完整消息历史。"""
    from app.agent.agent import SessionManager

    messages = SessionManager.get_raw_messages(session_id)
    if not messages and session_id not in SessionManager._sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {"session_id": session_id, "messages": messages}


@app.delete("/agent/sessions/{session_id}")
async def agent_delete_session(session_id: str) -> dict[str, Any]:
    """删除指定会话。"""
    from app.agent.agent import SessionManager

    deleted = SessionManager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {"deleted": True, "session_id": session_id}


# ============================================================
# 8.5 管理工具 — 清除缓存
# ============================================================

@app.post("/admin/clear-sessions")
async def admin_clear_sessions() -> dict[str, Any]:
    """清空所有 Agent 会话历史。"""
    from app.agent.agent import SessionManager

    SessionManager.clear_all()
    return {"cleared": True, "message": "已清除所有 Agent 会话历史"}


@app.post("/admin/clear-all")
async def admin_clear_all() -> dict[str, Any]:
    """
    清除所有本地数据：文献记录、PDF、提取文本、FAISS 索引、Agent 会话。
    此操作不可恢复。
    """
    import shutil
    from pathlib import Path

    from app.agent.agent import SessionManager
    from app.storage.repositories import PaperRepository

    data_dir = Path(__file__).resolve().parent.parent / "data"
    errors: list[str] = []

    # 1. 获取所有文献文件路径
    paper_repo = PaperRepository()
    paper_files = await paper_repo.get_all_paper_ids()
    papers_count = len(paper_files)

    # 2. 删除数据库中的论文记录
    await paper_repo.delete_all_papers()

    # 3. 删除 PDF 和提取文本文件
    for pf in paper_files:
        for path_key in ("local_pdf_path", "local_text_path"):
            file_path = pf.get(path_key)
            if file_path:
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception as exc:
                    errors.append(f"删除文件失败 {file_path}: {exc}")

    # 4. 删除 FAISS 索引
    index_dir = data_dir / "index"
    if index_dir.exists():
        try:
            shutil.rmtree(index_dir)
            index_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            errors.append(f"删除索引目录失败: {exc}")

    # 5. 删除会话历史
    try:
        SessionManager.clear_all()
    except Exception as exc:
        errors.append(f"清除会话失败: {exc}")

    return {
        "cleared": True,
        "papers": papers_count,
        "message": f"已清除所有数据（{papers_count} 篇文献）",
        "errors": errors if errors else None,
    }


# ============================================================
# 9. SPA 路由回退 — 必须放在所有 API 路由之后
# ============================================================

@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    """
    SPA 路由回退。

    对于非 API 的 GET 请求，返回前端 index.html，
    让 React Router 在客户端处理路由。
    必须放在所有 API 路由之后，否则会拦截 API 请求。
    """
    # 如果路径对应前端静态文件，直接返回
    frontend_file = FRONTEND_DIST / full_path
    if frontend_file.is_file():
        return FileResponse(frontend_file)

    # 回退到 index.html
    return FileResponse(FRONTEND_DIST / "index.html")


# ============================================================
# 10. 入口 — 启动 uvicorn
# ============================================================

if __name__ == "__main__":
    import uvicorn

    host = "127.0.0.1"
    port = 8000

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )