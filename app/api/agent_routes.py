"""
agent_routes.py

Agent API 路由（SSE 流式）。

提供 LangGraph 工作流的 HTTP 接口：
- POST /agent/run        → 创建任务，SSE 流式推送进度
- POST /agent/resume     → 恢复 interrupt 暂停的任务
- GET  /agent/status/{thread_id} → 查询任务状态

SSE 事件类型：
    node_start    → 节点开始执行
    node_complete → 节点完成（含结果摘要）
    interrupt     → 等待人工确认
    answer        → 最终回答
    error         → 某节点报错
    done          → 流程结束
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.graph import workflow

router = APIRouter(prefix="/agent", tags=["agent"])


# ============================================================
# 1. 请求模型
# ============================================================


class AgentRunRequest(BaseModel):
    """Agent 任务启动请求。"""

    user_intent: str = Field(
        default="",
        description="用户意图，如「跟踪 HMO 质谱解析文献」",
    )
    user_question: str = Field(
        ...,
        description="要回答的具体问题",
    )
    thread_id: str = Field(
        default="",
        description="对话线程 ID。留空自动生成。",
    )


class AgentResumeRequest(BaseModel):
    """Agent 任务恢复请求（interrupt 后调用）。"""

    thread_id: str = Field(..., description="对话线程 ID")
    approved: bool = Field(default=True, description="是否批准执行")


# ============================================================
# 2. 路由
# ============================================================


@router.post("/run")
async def agent_run(request: AgentRunRequest):
    """
    接收用户意图，创建 LangGraph 任务，返回 SSE 流。

    前端用 EventSource 接收实时进度。
    """
    thread_id = request.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "user_intent": request.user_intent,
        "user_question": request.user_question,
        "thread_id": thread_id,
    }

    async def event_generator():
        """SSE 事件生成器。将 langgraph astream 事件转为 SSE。"""
        try:
            yield _sse("thread", {"thread_id": thread_id})

            async for event in workflow.astream(initial_state, config):
                node_name = list(event.keys())[0] if event else "unknown"
                node_data = event.get(node_name, {})

                # 分类发送事件
                if node_name == "__interrupt__":
                    yield _sse("interrupt", {
                        "type": "interrupt",
                        "thread_id": thread_id,
                        "plan": node_data[0].get("plan", []) if isinstance(node_data, list) else [],
                        "has_crawl": node_data[0].get("has_crawl", False) if isinstance(node_data, list) else False,
                    })
                elif node_name in ("node_rag_ask",):
                    answer = node_data.get("answer", "")
                    sources = node_data.get("sources", [])
                    yield _sse("answer", {
                        "answer": answer,
                        "sources": sources,
                    })
                elif node_name in ("node_report_writer",):
                    yield _sse("report", {
                        "report": node_data.get("report", ""),
                    })
                elif "errors" in node_data and node_data["errors"]:
                    for err in node_data["errors"]:
                        yield _sse("error", {
                            "stage": err.get("stage", node_name),
                            "error": err.get("error", str(err)),
                        })
                else:
                    yield _sse("node_complete", {
                        "node": node_name,
                        "stage": node_data.get("current_stage", node_name),
                        "summary": _summarize_node(node_name, node_data),
                    })

            yield _sse("done", {"message": "流程已完成"})

        except Exception as exc:
            yield _sse("error", {"stage": "system", "error": str(exc)})
            yield _sse("done", {"message": "流程异常终止"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/resume")
async def agent_resume(request: AgentResumeRequest):
    """
    用户在 interrupt 节点确认后，恢复执行。
    """
    from langgraph.types import Command

    config = {"configurable": {"thread_id": request.thread_id}}

    async def event_generator():
        try:
            resume_value = {"approved": request.approved} if request.approved else None
            async for event in workflow.astream(Command(resume=resume_value), config):
                node_name = list(event.keys())[0] if event else "unknown"
                node_data = event.get(node_name, {})

                yield _sse("node_complete", {
                    "node": node_name,
                    "stage": node_data.get("current_stage", node_name),
                    "summary": _summarize_node(node_name, node_data),
                })

            yield _sse("done", {"message": "流程已完成"})

        except Exception as exc:
            yield _sse("error", {"stage": "system", "error": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/status/{thread_id}")
async def agent_status(thread_id: str):
    """
    查询任务当前状态（从 checkpoint 读取最后的状态快照）。
    """
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state = workflow.get_state(config)
        if state is None:
            return {"thread_id": thread_id, "status": "not_found", "message": "未找到该任务"}

        values = state.values if hasattr(state, "values") else {}
        return {
            "thread_id": thread_id,
            "status": "running",
            "current_stage": values.get("current_stage", "unknown") if isinstance(values, dict) else "unknown",
            "plan": values.get("plan", []) if isinstance(values, dict) else [],
        }
    except Exception as exc:
        return {"thread_id": thread_id, "status": "error", "message": str(exc)}


# ============================================================
# 3. 辅助函数
# ============================================================


def _sse(event: str, data: dict[str, Any]) -> str:
    """构造 SSE 格式字符串。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _summarize_node(node_name: str, data: dict[str, Any]) -> dict[str, Any]:
    """根据节点名生成可展示的摘要。"""
    if node_name == "node_task_planner":
        return {"plan_count": len(data.get("plan", [])), "has_crawl": data.get("has_crawl", False)}
    if node_name == "node_crawl":
        return {"kept": data.get("crawl_result", {}).get("kept_count", 0)}
    if node_name == "node_download_merge":
        return {"downloaded": sum(1 for r in data.get("download_results", []) if r.get("status") == "success")}
    if node_name == "node_parse_merge":
        return {"parsed": sum(1 for r in data.get("parse_results", []) if r.get("status") == "success")}
    if node_name == "node_chunk":
        return {"chunks": "ok" if data.get("chunk_results") else "no action"}
    if node_name == "node_index":
        return {"index": data.get("index_result", {}).get("faiss_ntotal", 0)}
    if node_name == "node_rag_ask":
        return {"answer_preview": (data.get("answer", "") or "")[:200]}
    return {}
