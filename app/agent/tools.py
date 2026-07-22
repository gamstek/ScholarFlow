"""
tools.py

LangChain Tool 定义 — 将 ScholarFlow 的四大功能封装为 Agent 可调用的 Tool。

Tools:
    1. search_papers  — 检索论文（支持自然语言）
    2. view_paper     — 查看论文全文
    3. ask_paper      — 对论文内容/领域知识 RAG 问答
    4. write_review   — 根据关键词写文献综述
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from langchain_core.tools import tool

from app.rag.embedder import DEFAULT_EMBEDDING_MODEL


# ============================================================
# 1. 检索论文
# ============================================================

@tool
def search_papers(
    query: str,
    sources: str = "europe_pmc",
    max_results: int = 20,
    author: str | None = None,
) -> str:
    """
    检索学术论文。输入自然语言或关键词，返回相关论文列表（含评分、DOI、在库状态）。

    参数：
        query: 检索关键词或自然语言描述。
        sources: 数据源，逗号分隔。可选：europe_pmc, nature, science, cell, arxiv, semantic_scholar
        max_results: 每个数据源最大检索数量。
        author: 按作者名过滤。例如 "Geoffrey Hinton"。可选。

    返回：
        JSON 字符串，包含检索结果列表。
    """
    from app.agent.keyword_extractor import extract_keywords
    from app.services.pipeline_service import search_papers_service

    # 先尝试 LLM 关键词提取
    extraction = extract_keywords(query)

    if extraction.keywords and not extraction.used_fallback:
        search_query = " ".join(extraction.keywords)
        keywords = extraction.keywords
        domain = extraction.domain
    else:
        search_query = query
        keywords = None
        domain = None

    source_list = [s.strip() for s in sources.split(",") if s.strip()]

    result = asyncio.run(search_papers_service(
        query=search_query,
        sources=source_list,
        max_results=max_results,
        keywords=keywords,
        domain=domain,
        author=author,
    ))

    # 精简输出，避免 token 过长
    summary = {
        "query": result.get("query"),
        "keywords": result.get("keywords"),
        "domain": result.get("domain"),
        "retrieved_count": result.get("retrieved_count"),
        "deduplicated_count": result.get("deduplicated_count"),
        "results": [
            {
                "title": r.get("title", ""),
                "authors": r.get("authors"),
                "doi": r.get("doi"),
                "year": r.get("year"),
                "journal": r.get("journal"),
                "domain_score": r.get("domain_score"),
                "in_library": r.get("in_library"),
                "paper_id": r.get("paper_id"),
                "source": r.get("source"),
            }
            for r in result.get("results", [])[:15]
        ],
        "errors": result.get("errors", []),
    }

    return json.dumps(summary, ensure_ascii=False, indent=2)


# ============================================================
# 1b. 查看本地文献库
# ============================================================

@tool
def list_library() -> str:
    """
    查看本地已入库的文献列表。直接查询本地数据库，不调用外部 API。

    返回：
        JSON 字符串，包含已入库文献的 ID、标题、状态、年份等。
    """
    import asyncio
    from app.storage.repositories import PaperRepository

    async def _get():
        repo = PaperRepository()
        papers = await repo.list_papers(limit=50, offset=0)
        return {
            "total": len(papers),
            "papers": [
                {
                    "id": p.get("id"),
                    "title": p.get("title", ""),
                    "year": p.get("year"),
                    "journal": p.get("journal"),
                    "status": p.get("status"),
                    "doi": p.get("doi"),
                    "source": p.get("source"),
                    "domain_score": p.get("domain_score"),
                    "has_pdf": bool(p.get("local_pdf_path")),
                    "has_text": bool(p.get("local_text_path")),
                }
                for p in papers
            ],
        }

    result = asyncio.run(_get())
    return json.dumps(result, ensure_ascii=False, indent=2)


# ============================================================
# 2. 查看论文全文
# ============================================================

@tool
def view_paper(paper_id: int) -> str:
    """
    查看库中论文的全文内容。

    参数：
        paper_id: 论文 ID（从 search_papers 结果中获取）。

    返回：
        JSON 字符串，包含论文标题、全文文本（截断）、章节列表。
    """
    from app.storage.repositories import PaperRepository, ChunkRepository

    async def _get():
        paper_repo = PaperRepository()
        chunk_repo = ChunkRepository()

        paper = await paper_repo.get_paper(paper_id)
        if paper is None:
            return {"error": f"paper_id={paper_id} 不存在。"}

        chunks = await chunk_repo.list_chunks_by_paper(paper_id)
        sorted_chunks = sorted(chunks, key=lambda c: c.get("chunk_index", 0))

        # 截断全文，避免 token 过长
        full_text = "\n\n".join(
            (c.get("section_title") or "") + "\n" + (c.get("text", ""))
            for c in sorted_chunks
        )

        if len(full_text) > 8000:
            full_text = full_text[:8000] + "\n\n... [全文过长，已截断]"

        sections = list(set(
            c.get("section_title") or "Unknown"
            for c in sorted_chunks
        ))

        return {
            "paper_id": paper_id,
            "title": paper.get("title"),
            "doi": paper.get("doi"),
            "year": paper.get("year"),
            "journal": paper.get("journal"),
            "status": paper.get("status"),
            "local_pdf_path": paper.get("local_pdf_path"),
            "local_text_path": paper.get("local_text_path"),
            "total_chunks": len(chunks),
            "sections": sections,
            "full_text": full_text,
        }

    result = asyncio.run(_get())
    return json.dumps(result, ensure_ascii=False, indent=2)


# ============================================================
# 3. RAG 问答
# ============================================================

@tool
def ask_paper(question: str, top_k: int = 5) -> str:
    """
    对本地文献库进行 RAG 问答。基于已入库的论文内容回答问题。

    参数：
        question: 用户问题。
        top_k: 检索前 k 个 chunks 作为证据。

    返回：
        JSON 字符串，包含回答和引用来源。
    """
    from app.rag.rag_engine import LocalRagEngine

    engine = LocalRagEngine(
        embedding_model_name=DEFAULT_EMBEDDING_MODEL,
        temperature=0.2,
        num_ctx=4096,
        num_predict=512,
    )

    result = asyncio.run(engine.ask(
        question=question,
        top_k=top_k,
        generate=True,
    ))

    return json.dumps({
        "question": result.question,
        "answer": result.answer,
        "model": result.model,
        "sources": result.sources[:5],
    }, ensure_ascii=False, indent=2)


# ============================================================
# 4. 文献综述
# ============================================================

@tool
def write_review(topic: str, top_k: int = 10) -> str:
    """
    根据主题/关键词撰写文献综述。基于本地文献库中的论文内容生成结构化 Markdown 综述。

    参数：
        topic: 综述主题或关键词。
        top_k: 检索前 k 个 chunks 作为证据。

    返回：
        JSON 字符串，包含综述全文和引用来源。
    """
    from app.services.review_service import generate_review

    result = asyncio.run(generate_review(
        topic=topic,
        top_k=top_k,
    ))

    return json.dumps({
        "topic": result.topic,
        "review": result.review,
        "evidence_count": result.evidence_count,
        "model": result.model,
        "sources": result.sources[:5],
    }, ensure_ascii=False, indent=2)


# ============================================================
# 5. 网页搜索
# ============================================================

@tool
def web_search(
    query: str,
    max_results: int = 10,
) -> str:
    """
    通过网页搜索引擎查找信息。适用于：
    - 搜索特定作者发表的论文（补充文献 API 覆盖不到的来源）
    - 查找论文的个人主页、Google Scholar 档案、机构仓库等
    - 查找 API 数据库未收录的出版物

    参数：
        query: 搜索查询字符串。建议使用 "作者名 论文" 或 "作者名 publications" 格式。
        max_results: 最大返回结果数，默认 10。

    返回：
        JSON 字符串，包含搜索结果的标题、摘要片段和 URL。
    """
    from app.agent.web_search import get_searcher

    searcher = get_searcher()
    results = searcher.search(query=query, max_results=max_results)

    summary = {
        "query": query,
        "total": len(results),
        "results": results,
    }

    return json.dumps(summary, ensure_ascii=False, indent=2)


# ============================================================
# 6. 单篇论文入库
# ============================================================

@tool
def import_paper(
    title: str,
    authors: str | None = None,
    doi: str | None = None,
    year: int | None = None,
    journal: str | None = None,
    source: str = "agent_import",
) -> str:
    """
    将一篇论文导入本地文献库。用户说"入库"、"保存"、"加入文库"时使用。

    参数：
        title: 论文标题（必填）。
        authors: 作者列表，逗号分隔。例如 "Geoffrey Hinton, Yann LeCun"。可选。
        doi: DOI 号。可选。
        year: 发表年份。可选。
        journal: 期刊/会议名称。可选。
        source: 来源标记，默认 "agent_import"。

    返回：
        JSON 字符串，包含入库结果（paper_id、状态）。
    """
    from app.services.pipeline_service import import_single_paper_service

    author_list = [a.strip() for a in authors.split(",")] if authors else None

    result = asyncio.run(import_single_paper_service(
        title=title,
        authors=author_list,
        doi=doi,
        year=year,
        journal=journal,
        source=source,
    ))

    return json.dumps({
        "paper_id": result.get("paper_id"),
        "title": result.get("title"),
        "status": result.get("status"),
        "message": result.get("message", "入库成功"),
    }, ensure_ascii=False, indent=2)


# ============================================================
# Tool 列表
# ============================================================

ALL_TOOLS = [search_papers, list_library, view_paper, ask_paper, write_review, web_search, import_paper]
