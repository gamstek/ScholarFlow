"""
author_utils.py

向后兼容的作者数据解析工具。

支持格式：authors_json = ["John Smith", "Jane Doe"]
        或 authors_json = [{"name": "John Smith"}, ...]

本模块提供统一的解析/格式化接口，确保旧数据无缝兼容。
"""

from __future__ import annotations

import json
from typing import Any, Optional


def parse_authors_json(authors_json: Optional[str]) -> list[str]:
    """
    向后兼容解析 authors_json 字段。

    支持两种旧格式：
      - list[str]：["John Smith", "Jane Doe"]
      - list[dict]：[{"name": "John Smith"}, ...]

    返回统一格式：["John Smith", "Jane Doe"]
    """
    if not authors_json:
        return []

    try:
        data = json.loads(authors_json)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(data, list):
        return []

    result: list[str] = []
    for item in data:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            name = item.get("name", "")
            if name:
                result.append(name)
        else:
            result.append(str(item))

    return result


def format_authors_json(authors: list[str]) -> str:
    """
    将作者列表序列化为 JSON 字符串。
    """
    return json.dumps(authors, ensure_ascii=False)


def authors_to_strings(authors: list[str]) -> list[str]:
    """返回作者名列表（等同于输入，供接口兼容使用）。"""
    return authors
