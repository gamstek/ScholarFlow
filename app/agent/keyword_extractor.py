"""
keyword_extractor.py

LLM 关键词提取服务。

输入一句话（自然语言），LLM 自动解析出：
1. 检索关键词列表（英文，用于多源文献检索）
2. 领域标签（中文，用于前端展示）

调用 OllamaGenerator._call_ollama_chat() 实现。
JSON 解析失败时兜底：直接用原句作为关键词。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from app.rag.generator import OllamaGenerator, extract_chat_answer


@dataclass
class ExtractionResult:
    """关键词提取结果。"""

    keywords: list[str]
    domain: str
    raw_query: str
    used_fallback: bool


# ============================================================
# Prompt 模板
# ============================================================

_SYSTEM_PROMPT = (
    "你是一个科研文献检索助手。"
    "用户会用自然语言描述想找的文献，"
    "你需要从中提取英文检索关键词和领域标签。"
    "只输出 JSON，不要输出其他内容。"
)

_FEW_SHOT_EXAMPLES = """
示例 1：
输入：我想找关于母乳低聚糖用液质联用做结构鉴定的文章
输出：{"keywords": ["human milk oligosaccharides", "LC-MS/MS", "structure elucidation", "glycan characterization"], "domain": "食品组学 / 糖链结构分析"}

示例 2：
输入：帮我查 CRISPR 基因编辑在农作物改良方面的应用
输出：{"keywords": ["CRISPR", "gene editing", "crop improvement", "plant biotechnology"], "domain": "植物生物技术 / 基因编辑"}

示例 3：
输入：肿瘤微环境中巨噬细胞的代谢重编程机制
输出：{"keywords": ["tumor microenvironment", "macrophage", "metabolic reprogramming", "immunometabolism"], "domain": "肿瘤免疫学 / 代谢调控"}
"""

_USER_PROMPT_TEMPLATE = """
{few_shot}

现在请处理以下输入，提取 3-6 个英文检索关键词和一个中文领域标签。

输入：{user_input}

输出（仅 JSON）：
"""


def extract_keywords(
    natural_query: str,
    ollama_model: str = "qwen3:8b",
    ollama_base_url: str = "http://localhost:11434",
    temperature: float = 0.2,
    timeout: int = 120,
) -> ExtractionResult:
    """
    从自然语言句子中提取检索关键词和领域标签。

    参数：
        natural_query: 用户的自然语言输入。
        ollama_model: Ollama 模型名称。
        ollama_base_url: Ollama 服务地址。
        temperature: 生成温度。
        timeout: 请求超时秒数。

    返回：
        ExtractionResult。
    """
    if not natural_query or not natural_query.strip():
        return ExtractionResult(
            keywords=[],
            domain="",
            raw_query=natural_query,
            used_fallback=True,
        )

    generator = OllamaGenerator(
        model=ollama_model,
        base_url=ollama_base_url,
        timeout=timeout,
        temperature=temperature,
        num_ctx=2048,
        num_predict=512,
        think=False,
        force_no_think_prefix=True,
        debug=False,
    )

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        few_shot=_FEW_SHOT_EXAMPLES,
        user_input=natural_query.strip(),
    )

    try:
        raw_response = generator._call_ollama_chat(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt="/no_think\n" + user_prompt,
        )
        answer = extract_chat_answer(raw_response)
    except Exception as exc:
        return _fallback(natural_query, f"Ollama 调用失败：{exc}")

    if not answer:
        return _fallback(natural_query, "Ollama 返回为空")

    parsed = _parse_json_response(answer)

    if parsed is None:
        return _fallback(natural_query, f"JSON 解析失败，原始回答：{answer[:200]}")

    keywords = parsed.get("keywords", [])
    domain = parsed.get("domain", "")

    if not isinstance(keywords, list):
        keywords = [str(keywords)] if keywords else []

    keywords = [str(k).strip() for k in keywords if k and str(k).strip()]
    domain = str(domain).strip() if domain else ""

    if not keywords:
        return _fallback(natural_query, "提取的关键词为空")

    return ExtractionResult(
        keywords=keywords,
        domain=domain,
        raw_query=natural_query,
        used_fallback=False,
    )


def _fallback(natural_query: str, reason: str) -> ExtractionResult:
    """兜底策略：直接用原句分词作为关键词。"""
    words = re.findall(r"[a-zA-Z]{2,}|[\u4e00-\u9fff]+", natural_query)
    keywords = words[:5] if words else [natural_query.strip()]

    return ExtractionResult(
        keywords=keywords,
        domain="",
        raw_query=natural_query,
        used_fallback=True,
    )


def _parse_json_response(text: str) -> Optional[dict]:
    """
    尝试从 LLM 输出中解析 JSON。

    LLM 可能在 JSON 前后加 markdown 标记或多余文字，
    用正则提取第一个 JSON 对象。
    """
    text = text.strip()

    # 去除 markdown 代码块标记
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取第一个 {...} 块
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # 尝试更宽松的匹配（嵌套大括号）
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None
