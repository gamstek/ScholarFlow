"""
author_utils.py

向后兼容的作者数据解析工具。

旧格式：authors_json = ["John Smith", "Jane Doe"]
新格式：authors_json = [{"name": "John Smith", "institution": "MIT"}, ...]

本模块提供统一的解析/格式化接口，确保旧数据无缝兼容。
"""

from __future__ import annotations

import json
from typing import Any, Optional


def parse_authors_json(authors_json: Optional[str]) -> list[dict[str, Optional[str]]]:
    """
    向后兼容解析 authors_json 字段。

    旧格式（list[str]）自动升级为新格式（list[dict]）。
    返回：
        [{"name": "...", "institution": "..." or None}, ...]
    """
    if not authors_json:
        return []

    try:
        data = json.loads(authors_json)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(data, list):
        return []

    result: list[dict[str, Optional[str]]] = []
    for item in data:
        if isinstance(item, str):
            result.append({"name": item, "institution": None})
        elif isinstance(item, dict):
            result.append({
                "name": item.get("name", ""),
                "institution": item.get("institution"),
            })
        else:
            result.append({"name": str(item), "institution": None})

    return result


def format_authors_json(authors: list[dict[str, Optional[str]]]) -> str:
    """
    将结构化作者列表序列化为 JSON 字符串。

    去除空字符串和 None 值的 institution 字段以减小存储。
    """
    cleaned: list[dict[str, Any]] = []
    for a in authors:
        entry: dict[str, Any] = {"name": a.get("name", "")}
        inst = a.get("institution")
        if inst:
            entry["institution"] = inst
        cleaned.append(entry)
    return json.dumps(cleaned, ensure_ascii=False)


def authors_to_strings(authors: list[dict[str, Optional[str]]]) -> list[str]:
    """提取作者名列表（纯字符串），供旧接口兼容使用。"""
    return [a.get("name", "") for a in authors if a.get("name")]
