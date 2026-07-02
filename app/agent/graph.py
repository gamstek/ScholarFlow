"""
graph.py

LangGraph 工作流定义。

完整的文献采集与问答工作流：
    TaskPlanner → HumanApproval → [采集分支 | QA分支] → Merge → Ask → Report

特性：
- SSE 流式进度推送 (astream)
- 人机协作 (interrupt)
- 持久化恢复 (PostgresSaver)
- 并行下载/解析 (Send fan-out)
- 双路检索 (已有库 FAISS + 实时采集 Europe PMC)
"""

from __future__ import annotations

import logging
import os
import operator
from typing import Annotated, Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, Send, interrupt
from typing_extensions import TypedDict

from app.agent.llm import OllamaLlmClient
from app.agent.tools.registry import tool_registry
from app.storage.database import DATABASE_URL

logger = logging.getLogger(__name__)


# ============================================================
# 1. 工作流状态
# ============================================================


class WorkflowState(TypedDict, total=False):
    """LangGraph 工作流全局状态。"""

    # ── 输入 ──
    user_intent: str              # 用户自然语言意图
    user_question: str            # 要回答的具体问题
    thread_id: str                # 对话线程 ID（用于 checkpoint）

    # ── TaskPlanner 输出 ──
    plan: list[dict[str, Any]]    # [{stage, tool_name, params}, ...]
    has_crawl: bool               # plan 中是否包含采集阶段

    # ── 采集阶段产出 ──
    crawl_result: dict[str, Any]  # 采集报告 (kept_count, saved_paper_ids, ...)
    paper_ids: list[int]          # 采集到的 paper_id 列表
    download_results: Annotated[list[dict[str, Any]], operator.add]  # 各篇 PDF 下载结果
    parse_results: Annotated[list[dict[str, Any]], operator.add]    # 各篇解析结果
    chunk_results: list[dict[str, Any]]  # chunk 构建结果
    index_result: dict[str, Any]  # FAISS 索引构建结果

    # ── RAG 双路结果 ──
    rag_search_result: dict[str, Any]    # 已有库 FAISS 检索结果
    crawl_realtime_result: dict[str, Any]  # 实时采集 metadata
    merged_context: str                  # 分层拼接的 LLM context
    sources: list[dict[str, Any]]        # 最终来源（分「已收录」+「新发现」）

    # ── 最终输出 ──
    answer: str                          # 最终回答
    report: str                          # Markdown 报告

    # ── 控制 ──
    current_stage: str                   # 当前阶段标签
    errors: Annotated[list[dict[str, Any]], operator.add]  # 错误收集
    human_approved: bool                 # interrupt 确认状态


# ============================================================
# 2. 节点实现
# ============================================================


async def node_task_planner(state: WorkflowState) -> dict[str, Any]:
    """
    TaskPlanner: LLM 拆解用户意图 → 子任务列表。

    输入：user_intent + user_question
    输出：plan [{stage, tool_name, params}, ...] + has_crawl
    """
    intent = state.get("user_intent", "")
    question = state.get("user_question", "")

    logger.info("[TaskPlanner] 意图: %s", intent)

    # 简单实现：如果用户意图包含"找"/"搜"/"跟踪"等关键词，则触发采集
    # 后续可升级为 LLM 调用
    trigger_crawl = any(
        kw in intent
        for kw in ("找", "搜", "跟踪", "收集", "采集", "检索", "search", "crawl")
    )

    plan: list[dict[str, Any]] = []

    if trigger_crawl or not intent:
        # 采集全流程
        plan = [
            {"stage": "crawl",    "tool_name": "search_literature", "params": {"query": intent or question, "max_results": 10}},
            {"stage": "download", "tool_name": "download_open_access_pdf", "params": {"limit": 5}},
            {"stage": "parse",    "tool_name": "parse_pdf", "params": {}},
            {"stage": "chunk",    "tool_name": "build_chunks", "params": {}},
            {"stage": "index",    "tool_name": "build_faiss_index", "params": {"limit": 50}},
        ]
        has_crawl = True
    else:
        has_crawl = False

    # 最终 QA（无论是否有采集，最后都做 QA）
    plan.append({"stage": "rag_search", "tool_name": "rag_search", "params": {"query": question, "top_k": 5}})

    return {
        "plan": plan,
        "has_crawl": has_crawl,
        "current_stage": "planning",
    }


async def node_human_approval(state: WorkflowState) -> dict[str, Any]:
    """等待人工确认。用 interrupt 暂停执行。"""
    plan = state.get("plan", [])
    has_crawl = state.get("has_crawl", False)

    logger.info("[HumanApproval] 计划已完成，等待确认。%d 步", len(plan))

    approved = interrupt({
        "type": "interrupt",
        "message": "已规划以下步骤，是否执行？",
        "plan": plan,
        "has_crawl": has_crawl,
    })

    return {"human_approved": bool(approved)}


async def node_condition_router(state: WorkflowState) -> Literal["node_crawl", "node_rag_search"]:
    """条件路由：有采集任务走采集分支，否则直接进入 QA。"""
    if state.get("has_crawl"):
        return "node_crawl"
    return "node_rag_search"


# ── 采集分支 ──


async def node_crawl(state: WorkflowState) -> dict[str, Any]:
    """节点：从 Europe PMC 采集文献。"""
    logger.info("[Crawl] 开始采集")
    try:
        tool = tool_registry.get("search_literature")
        plan = state.get("plan", [])
        crawl_params = next((s for s in plan if s["stage"] == "crawl"), {})
        params = tool.input_schema(**crawl_params.get("params", {}))

        result = await tool.run(params)
        data = result.data or {}
        paper_ids = data.get("saved_paper_ids", [])

        return {
            "crawl_result": data,
            "paper_ids": paper_ids,
            "current_stage": "crawl",
        }
    except Exception as exc:
        return {"errors": [{"stage": "crawl", "error": str(exc)}]}


async def node_download(state: WorkflowState) -> list[Send]:
    """节点：并行下载 PDF。fan-out 到每篇论文。"""
    paper_ids = state.get("paper_ids", [])
    if not paper_ids:
        logger.info("[Download] 无待下载论文")
        return []

    logger.info("[Download] 并行下载 %d 篇论文", len(paper_ids))
    return [Send("node_download_single", {"paper_id": pid}) for pid in paper_ids]


async def node_download_single(state: dict[str, Any]) -> dict[str, Any]:
    """子节点：下载单篇论文 PDF。"""
    paper_id = state.get("paper_id")
    # 使用 download_for_paper 下载单篇
    from app.harvest.literature.pdf_resolver import OpenAccessPdfResolver
    from app.storage.repositories import PaperRepository

    resolver = OpenAccessPdfResolver()
    repo = PaperRepository()
    paper = await repo.get_paper(paper_id)

    if not paper:
        return {"download_results": [{"paper_id": paper_id, "status": "failed", "message": "文献不存在"}]}

    result = await resolver.download_for_paper(paper)
    return {"download_results": [{
        "paper_id": result.paper_id,
        "status": result.status,
        "message": result.message,
        "local_pdf_path": result.local_pdf_path,
    }]}


async def node_download_merge(state: WorkflowState) -> dict[str, Any]:
    """合并并行下载结果。"""
    results = state.get("download_results", [])
    success = [r for r in results if r["status"] == "success"]
    logger.info("[Download] 完成: %d/%d 成功", len(success), len(results))

    pdf_paths = [r.get("local_pdf_path") for r in success if r.get("local_pdf_path")]
    return {"current_stage": "download", "pdf_paths": pdf_paths}


# ── parse 阶段 ──


async def node_parse(state: WorkflowState) -> list[Send]:
    """节点：并行解析 PDF。"""
    pdf_paths = state.get("pdf_paths", [])
    if not pdf_paths:
        return []
    logger.info("[Parse] 并行解析 %d 篇 PDF", len(pdf_paths))
    return [Send("node_parse_single", {"pdf_path": p}) for p in pdf_paths]


async def node_parse_single(state: dict[str, Any]) -> dict[str, Any]:
    """子节点：解析单篇 PDF。"""
    import asyncio

    from app.document.pdf_parser import PdfParser
    from app.document.section_parser import parse_sections_from_pages, sections_to_dicts
    from app.storage.file_store import resolve_project_path

    pdf_path_str = state.get("pdf_path", "")
    pdf_path = resolve_project_path(pdf_path_str)

    try:
        parser = PdfParser()
        parsed = await asyncio.to_thread(parser.parse, pdf_path)
        parsed_dict = await asyncio.to_thread(parser.to_dict, parsed)
        sections = parse_sections_from_pages(pages=parsed_dict["pages"])
        section_dicts = sections_to_dicts(sections)

        return {"parse_results": [{
            "pdf_path": pdf_path_str,
            "status": "success",
            "page_count": parsed_dict["page_count"],
            "section_count": len(section_dicts),
            "total_chars": len(parsed_dict.get("full_text", "")),
            "sections": [s.get("title") for s in section_dicts],
        }]}
    except Exception as exc:
        return {"parse_results": [{"pdf_path": pdf_path_str, "status": "failed", "error": str(exc)}]}


async def node_parse_merge(state: WorkflowState) -> dict[str, Any]:
    """合并并行解析结果。"""
    results = state.get("parse_results", [])
    success = [r for r in results if r["status"] == "success"]
    logger.info("[Parse] 完成: %d/%d 成功", len(success), len(results))
    return {"current_stage": "parse"}


# ── chunk 阶段 ──


async def node_chunk(state: WorkflowState) -> dict[str, Any]:
    """节点：构建 chunks。"""
    logger.info("[Chunk] 开始构建 chunks")

    try:
        tool = tool_registry.get("build_chunks")
        from app.services.pipeline_service import build_chunks_service
        result = await build_chunks_service(limit=10)
        return {"chunk_results": [result], "current_stage": "chunk"}
    except Exception as exc:
        return {"errors": [{"stage": "chunk", "error": str(exc)}], "current_stage": "chunk"}


# ── index 阶段 ──


async def node_index(state: WorkflowState) -> dict[str, Any]:
    """节点：构建 FAISS 索引。"""
    logger.info("[Index] 开始构建索引")

    try:
        tool = tool_registry.get("build_faiss_index")
        params = tool.input_schema(limit=50)
        result = await tool.run(params)
        return {"index_result": result.data or {}, "current_stage": "index"}
    except Exception as exc:
        return {"errors": [{"stage": "index", "error": str(exc)}], "current_stage": "index"}


# ── QA 阶段 ──


async def node_rag_search(state: WorkflowState) -> dict[str, Any]:
    """节点：已有库 FAISS 检索。"""
    question = state.get("user_question", "")
    logger.info("[RAG Search] 检索已有库: %s", question[:50])

    try:
        tool = tool_registry.get("rag_search")
        params = tool.input_schema(query=question, top_k=5)
        result = await tool.run(params)
        return {"rag_search_result": result.data or {}, "current_stage": "rag_search"}
    except Exception as exc:
        return {"errors": [{"stage": "rag_search", "error": str(exc)}]}


async def node_crawl_realtime(state: WorkflowState) -> dict[str, Any]:
    """节点：实时采集 Europe PMC（与已有库检索并行）。"""
    question = state.get("user_question", "")
    intent = state.get("user_intent", "")
    query = intent or question

    logger.info("[Crawl Realtime] 实时采集: %s", query[:50])

    try:
        from app.harvest.harvester import LiteratureHarvester
        harvester = LiteratureHarvester(min_domain_score=0.4)
        report = await harvester.crawl_from_europe_pmc(
            query=query,
            max_results=5,
            enhance_query=True,
        )
        return {
            "crawl_realtime_result": {
                "kept_count": report.kept_count,
                "saved_paper_ids": report.saved_paper_ids,
                "filtered_examples": report.filtered_examples[:3] if hasattr(report, "filtered_examples") else [],
            },
            "current_stage": "crawl_realtime",
        }
    except Exception as exc:
        return {"errors": [{"stage": "crawl_realtime", "error": str(exc)}]}


async def node_merge_results(state: WorkflowState) -> dict[str, Any]:
    """
    节点：双路结果合并，分层拼接 LLM context。

    【已收录文献】已有全文 + FAISS 向量
    【新发现文献】仅 metadata + domain_score
    """
    rag = state.get("rag_search_result", {})
    crawl = state.get("crawl_realtime_result", {})

    existing_sources = rag.get("sources", [])
    new_sources = crawl.get("saved_paper_ids", [])

    # 构建分层 context
    context_parts: list[str] = []

    if existing_sources:
        context_parts.append("════════════════════════════════════════════\n【已收录文献】已下载全文，包含详细章节内容\n════════════════════════════════════════════")
        for s in existing_sources:
            score = s.get("score", 0)
            title = s.get("paper_title", "Unknown")
            section = s.get("section_title", "Unknown")
            text = (s.get("text") or "")[:500]
            context_parts.append(f"[{s['source_id']}] (相似度: {score:.2f}) {title} - {section}\n  \"{text}\"")

    if crawl.get("kept_count", 0) > 0:
        context_parts.append("\n════════════════════════════════════════════\n【新发现文献】仅含摘要，尚未下载全文\n════════════════════════════════════════════")
        context_parts.append(f"(共发现 {crawl['kept_count']} 篇新文献)")

    merged_context = "\n\n".join(context_parts)

    # 分类 sources
    sources: list[dict[str, Any]] = []
    for s in existing_sources:
        s["category"] = "已收录"
        sources.append(s)

    papers = new_sources if isinstance(new_sources, list) else []
    for pid in papers[:5]:
        try:
            from app.storage.repositories import PaperRepository
            repo = PaperRepository()
            paper = await repo.get_paper(pid)
            if paper:
                sources.append({
                    "source_id": f"N{len(sources)+1}",
                    "paper_id": pid,
                    "paper_title": paper.get("title", ""),
                    "year": paper.get("year"),
                    "doi": paper.get("doi"),
                    "domain_score": paper.get("domain_score"),
                    "category": "新发现",
                })
        except Exception:
            pass

    return {"merged_context": merged_context, "sources": sources, "current_stage": "merge"}


async def node_rag_ask(state: WorkflowState) -> dict[str, Any]:
    """节点：LLM 生成最终回答。"""
    question = state.get("user_question", "")
    context = state.get("merged_context", "")

    if not context:
        return {"answer": "未检索到相关文献信息。", "current_stage": "qa"}

    logger.info("[RAG Ask] 生成回答")

    llm = OllamaLlmClient()
    prompt = (
        "你是科研文献分析助手。请基于以下文献证据回答用户问题。\n"
        "如果【已收录文献】包含详细内容，优先使用。\n"
        "如果仅有【新发现文献】的摘要信息，请注明'根据新发现文献的摘要'。\n"
        "引用时标注来源编号。\n\n"
        f"用户问题：{question}\n\n"
        "文献证据：\n"
        f"{context}"
    )

    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": "你是科研文献分析助手，基于提供的文献证据回答问题。不要输出思考过程。"},
                {"role": "user", "content": prompt},
            ]
        )
        return {"answer": response.content or "未能生成回答。", "current_stage": "qa"}
    except Exception as exc:
        logger.warning("LLM 调用失败: %s", exc)
        return {
            "answer": f"检索已完成但 LLM 生成失败（{exc}）。请查看 sources 获取相关文献。",
            "current_stage": "qa",
        }


async def node_report_writer(state: WorkflowState) -> dict[str, Any]:
    """节点：生成 Markdown 报告。"""
    answer = state.get("answer", "")
    sources = state.get("sources", [])
    errors = state.get("errors", [])
    crawl_result = state.get("crawl_result", {})
    index_result = state.get("index_result", {})

    report_lines = [
        "# ScholarFlow 任务报告",
        "",
        f"## 用户意图\n{state.get('user_intent', 'N/A')}",
        "",
        f"## 最终回答\n{answer}",
        "",
        "## 参考来源",
    ]

    for s in sources:
        report_lines.append(
            f"- [{s.get('source_id', '?')}] ({s.get('category', '?')}) "
            f"{s.get('paper_title', 'N/A')}"
        )

    if crawl_result:
        report_lines.extend([
            "",
            "## 采集统计",
            f"- 检索到: {crawl_result.get('retrieved_count', 0)} 篇",
            f"- 入库: {crawl_result.get('kept_count', 0)} 篇",
            f"- 过滤: {crawl_result.get('filtered_out_count', 0)} 篇",
        ])

    if errors:
        report_lines.extend(["", "## 错误", *[f"- [{e.get('stage')}] {e.get('error')}" for e in errors]])

    return {"report": "\n".join(report_lines), "current_stage": "report"}


# ============================================================
# 3. Graph 构建
# ============================================================


def build_workflow_graph() -> StateGraph:
    """构建 LangGraph 工作流图。"""

    graph = StateGraph(WorkflowState)

    # ── 注册所有节点 ──
    graph.add_node("node_task_planner", node_task_planner)
    graph.add_node("node_human_approval", node_human_approval)
    graph.add_node("node_condition_router", node_condition_router)

    # 采集分支
    graph.add_node("node_crawl", node_crawl)
    graph.add_node("node_download", node_download)
    graph.add_node("node_download_single", node_download_single)
    graph.add_node("node_download_merge", node_download_merge)
    graph.add_node("node_parse", node_parse)
    graph.add_node("node_parse_single", node_parse_single)
    graph.add_node("node_parse_merge", node_parse_merge)
    graph.add_node("node_chunk", node_chunk)
    graph.add_node("node_index", node_index)

    # QA 分支
    graph.add_node("node_rag_search", node_rag_search)
    graph.add_node("node_crawl_realtime", node_crawl_realtime)
    graph.add_node("node_merge_results", node_merge_results)
    graph.add_node("node_rag_ask", node_rag_ask)
    graph.add_node("node_report_writer", node_report_writer)

    # ── 定义边 ──
    graph.add_edge(START, "node_task_planner")
    graph.add_edge("node_task_planner", "node_human_approval")
    graph.add_conditional_edges(
        "node_human_approval",
        lambda s: "approved" if s.get("human_approved") else "rejected",
        {"approved": "node_condition_router", "rejected": END},
    )

    graph.add_conditional_edges(
        "node_condition_router",
        node_condition_router,
        {"node_crawl": "node_crawl", "node_rag_search": "node_rag_search"},
    )

    # 采集分支：crawl → download → download_merge → parse → parse_merge → chunk → index → rag_search
    graph.add_conditional_edges("node_crawl", lambda s: "next" if not s.get("errors") else "skip", {"next": "node_download", "skip": "node_rag_search"})
    graph.add_conditional_edges(
        "node_download",
        lambda s: "fan_out" if s.get("download_results") is None else "merge",
        {
            "fan_out": "node_download_single",
            "merge": "node_download_merge",
        },
    )
    graph.add_edge("node_download_single", "node_download_merge")
    graph.add_edge("node_download_merge", "node_parse")

    graph.add_conditional_edges(
        "node_parse",
        lambda s: "fan_out" if s.get("parse_results") is None else "merge",
        {"fan_out": "node_parse_single", "merge": "node_parse_merge"},
    )
    graph.add_edge("node_parse_single", "node_parse_merge")
    graph.add_edge("node_parse_merge", "node_chunk")
    graph.add_edge("node_chunk", "node_index")
    graph.add_edge("node_index", "node_rag_search")

    # QA 分支：并行 rag_search + crawl_realtime → merge → ask → report
    graph.add_edge("node_rag_search", "node_crawl_realtime")
    graph.add_edge("node_crawl_realtime", "node_merge_results")
    graph.add_edge("node_merge_results", "node_rag_ask")
    graph.add_edge("node_rag_ask", "node_report_writer")
    graph.add_edge("node_report_writer", END)

    return graph


# ============================================================
# 4. 编译与导出
# ============================================================


def compile_workflow(
    use_checkpoint: bool = True,
) -> CompiledStateGraph:
    """编译工作流图，返回可执行的 app。

    参数：
        use_checkpoint: 是否启用持久化（默认 MemorySaver）。
                        PostgresSaver 需在应用启动时异步初始化，使用 compile_workflow_async()。
    """
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_workflow_graph()

    if use_checkpoint:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            # AsyncPostgresSaver 需要 await，这里做不到，降级到 MemorySaver
            raise NotImplementedError("请使用 compile_workflow_async() 获取 PostgresSaver 支持")
        except ImportError:
            pass
        except NotImplementedError:
            pass

    return graph.compile(checkpointer=MemorySaver())


async def compile_workflow_async() -> CompiledStateGraph:
    """异步编译工作流图（使用 PostgresSaver）。

    在 FastAPI lifespan 中调用：
        app.state.agent_workflow = await compile_workflow_async()
    """
    graph = build_workflow_graph()

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        # 替换 DATABASE_URL 中的 asyncpg 为 psycopg（PostgresSaver 用同步驱动）
        sync_url = DATABASE_URL.replace("+asyncpg", "")
        async with AsyncPostgresSaver.from_conn_string(sync_url) as checkpointer:
            await checkpointer.setup()
            logger.info("PostgresSaver 已就绪")
            return graph.compile(checkpointer=checkpointer)
    except Exception as exc:
        logger.warning("PostgresSaver 配置失败，使用 MemorySaver: %s", exc)
        from langgraph.checkpoint.memory import MemorySaver
        return graph.compile(checkpointer=MemorySaver())


# 默认编译（带 checkpoint）
workflow = compile_workflow()
