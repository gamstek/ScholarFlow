"""
main.py

ScholarFlow FastAPI 服务入口。

当前接口：
1. GET  /health
   健康检查。

2. GET  /stats
   查看数据库中文献、chunks、索引状态。

3. GET  /papers
   查看本地文献库。

4. GET  /papers/{paper_id}
   查看单篇文献详情。

5. GET  /papers/{paper_id}/chunks
   查看某篇文献的 chunks。

6. POST /chunks/search
   只检索 chunks，不调用大模型生成。

7. POST /ask
   本地 RAG 问答：检索 + Ollama 生成。

8. POST /rag/warmup
   预加载 embedding 模型和 FAISS 索引，减少首次请求等待时间。

运行方式：
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

访问文档：
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.pipeline_routes import router as pipeline_router
from app.api.agent_routes import router as agent_router
from app.rag.rag_engine import LocalRagEngine
from app.rag.retriever import LocalChunkRetriever, evidences_to_dicts
from app.storage.database import async_session_factory, init_db
from app.storage.repositories import ChunkRepository, PaperRepository

from sqlalchemy import text as sa_text



# ============================================================
# 1. FastAPI 应用
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    """
    FastAPI lifespan: 启动时初始化数据库，关闭时释放连接。
    """
    await init_db()
    yield


app = FastAPI(
    title="ScholarFlow",
    description=(
        "通用文献采集与检索智能体。"
        "支持本地文献检索、chunk 检索和基于 Ollama 的问答。"
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(pipeline_router)
app.include_router(agent_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
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
        "C:/Users/Admin/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
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
        "C:/Users/Admin/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
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
        "C:/Users/Admin/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181",
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
            ollama_model=request.ollama_model,
            ollama_base_url=request.ollama_base_url,
            temperature=request.temperature,
            num_ctx=request.num_ctx,
            num_predict=request.num_predict,
            timeout=request.timeout,
            think=think,
            keep_alive="30m",
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
    """
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    """
    健康检查接口。
    """
    return {
        "status": "ok",
        "service": "ScholarFlow",
        "version": "0.2.0",
    }


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


@app.post("/rag/warmup")
def warmup(
    request: WarmupRequest,
) -> dict[str, Any]:
    """
    预加载 embedding 模型和 FAISS 索引。

    作用：
        第一次请求通常会很慢，因为要加载 BGE-M3 和 FAISS。
        可以先调用这个接口预热。
    """
    try:
        # 预热 retriever
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