"""
protocol_agent.py

C01 ProtocolAgent — 研究问题建模与项目协议。

输入：自然语言课题描述
输出：PICO 框架 + 纳排标准 + 检索策略

此 Agent 是 LangGraph 工作流的第一个节点。
执行完毕后进入人工审批门 (interrupt)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from json_repair import repair_json

from app.agent.llm import OllamaLlmClient
from app.storage.repositories import ProtocolRepository

logger = logging.getLogger(__name__)


PICO_SYSTEM_PROMPT = """You are a research methodology expert. Decompose the user's natural language research question into a structured protocol.

Reply in JSON (Chinese or English based on input language):

{
  "pico": {
    "population": "Study subjects (population/animal/cell/compound etc.)",
    "intervention": "Intervention / method (e.g. LC-MS/MS, structural analysis)",
    "comparison": "Comparison group (null if none)",
    "outcome": "Outcome / endpoints"
  },
  "keywords_en": ["keyword1", "keyword2"],
  "keywords_zh": ["关键词1", "关键词2"],
  "search_query": "Boolean search expression",
  "inclusion_criteria": [
    {"criterion": "...", "rationale": "..."}
  ],
  "exclusion_criteria": [
    {"criterion": "...", "rationale": "..."}
  ],
  "suggested_time_range": {"from": 2015, "to": 2026},
  "suggested_study_types": ["randomized controlled trial"],
  "suggested_data_sources": ["PubMed", "Europe PMC"]
}

Requirements:
- 5-10 keywords each in EN and ZH
- 3-5 inclusion/exclusion criteria each with rationale
- Boolean search query using AND/OR/NOT
- Default time range is last 10 years if not specified
- Output ONLY the JSON, no markdown wrapping, no trailing text"""


async def generate_protocol(raw_question: str) -> dict[str, Any]:
    """
    ProtocolAgent 主函数。

    输入原始研究问题，调用 LLM 生成结构化研究协议。

    返回：
        {
            "pico": {...},
            "keywords_en": [...],
            "keywords_zh": [...],
            "search_query": "...",
            "inclusion_criteria": [...],
            "exclusion_criteria": [...],
            "time_from": 2015,
            "time_to": 2026,
            "study_types": [...],
            "data_sources": [...]
        }
    """
    logger.info("[ProtocolAgent] 处理课题: %s", raw_question[:80])

    llm = OllamaLlmClient(temperature=0.3, num_predict=4096)

    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": PICO_SYSTEM_PROMPT},
                {"role": "user", "content": raw_question},
            ]
        )

        content = response.content or ""
        # 提取 JSON
        content = _extract_json(content)
        # json-repair 自动修复常见 LLM JSON 问题
        content = repair_json(content)
        protocol_data = json.loads(content)

        # 标准化输出
        pico = protocol_data.get("pico", {})
        time_range = protocol_data.get("suggested_time_range", {})

        return {
            "pico": pico,
            "keywords_en": protocol_data.get("keywords_en", []),
            "keywords_zh": protocol_data.get("keywords_zh", []),
            "search_query": protocol_data.get("search_query", ""),
            "inclusion_criteria": protocol_data.get("inclusion_criteria", []),
            "exclusion_criteria": protocol_data.get("exclusion_criteria", []),
            "time_from": time_range.get("from", 2015),
            "time_to": time_range.get("to", 2026),
            "study_types": protocol_data.get("suggested_study_types", []),
            "data_sources": protocol_data.get("suggested_data_sources", []),
        }
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("[ProtocolAgent] LLM 解析失败，降级到空协议: %s", exc)
        return {
            "pico": {
                "population": "",
                "intervention": "",
                "comparison": None,
                "outcome": "",
            },
            "keywords_en": [],
            "keywords_zh": [],
            "search_query": "",
            "inclusion_criteria": [],
            "exclusion_criteria": [],
            "time_from": 2015,
            "time_to": 2026,
            "study_types": [],
            "data_sources": [],
        }


async def save_protocol(
    raw_question: str,
    protocol_data: dict[str, Any],
    project_name: str = "默认项目",
) -> int:
    """将协议保存到数据库。"""
    repo = ProtocolRepository()
    return await repo.create_protocol(
        project_name=project_name,
        raw_question=raw_question,
        pico_json=json.dumps(protocol_data.get("pico"), ensure_ascii=False),
        keywords_en="\n".join(protocol_data.get("keywords_en", [])),
        keywords_zh="\n".join(protocol_data.get("keywords_zh", [])),
        search_query=protocol_data.get("search_query", ""),
        inclusion_criteria=json.dumps(protocol_data.get("inclusion_criteria", []), ensure_ascii=False),
        exclusion_criteria=json.dumps(protocol_data.get("exclusion_criteria", []), ensure_ascii=False),
        time_from=protocol_data.get("time_from"),
        time_to=protocol_data.get("time_to"),
        languages="en,zh",
        study_types=json.dumps(protocol_data.get("study_types", []), ensure_ascii=False),
        data_sources=json.dumps(protocol_data.get("data_sources", []), ensure_ascii=False),
    )


def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON 字符串。"""
    text = text.strip()

    # 尝试去掉 ```json ``` 包裹
    m = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if m:
        text = m.group(1).strip()

    # 找到第一个 { 和最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    return text
