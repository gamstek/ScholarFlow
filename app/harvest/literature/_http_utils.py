"""
_http_utils.py —— HTTP 响应体安全解码工具。

问题背景：
    部分学术 API（arXiv、Europe PMC 等）返回的响应虽然 Content-Type
    声明为 UTF-8，但实际内容可能混入 Latin-1/Windows-1252 编码的字符
    （如作者名中的 é、ñ、ü 等），直接 .decode("utf-8") 会抛出
    UnicodeDecodeError 导致搜索流程中断。

策略（按优先级）：
    1. 从 Content-Type 头提取 charset，按声明编码解码
    2. 如果声明为 utf-8 但解码失败，尝试 latin-1（最可能混入的编码）
    3. 如果项目安装了 charset_normalizer，用它嗅探实际编码
    4. 最后兜底：utf-8 + errors="replace"
"""

from __future__ import annotations

import re
from typing import Optional


def decode_response_body(
    raw_bytes: bytes,
    content_type: str = "",
    *,
    fallback_encodings: tuple[str, ...] = ("latin-1",),
) -> str:
    """
    安全地将 HTTP 响应体 bytes 解码为 str，保证不抛 UnicodeDecodeError。

    参数：
        raw_bytes: response.read() 得到的原始字节
        content_type: 响应头 Content-Type 的值
        fallback_encodings: 声明编码失败时的回退编码列表

    返回：
        解码后的字符串
    """
    declared = _parse_charset(content_type)

    # 策略 1：按声明编码解码
    if declared:
        try:
            return raw_bytes.decode(declared)
        except (UnicodeDecodeError, LookupError):
            pass

    # 策略 2：声明为 utf-8 但实际是 latin-1（最常见场景）
    if declared and declared.lower() in ("utf-8", "utf8"):
        for enc in fallback_encodings:
            try:
                return raw_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue

    # 策略 3：charset_normalizer 嗅探（可选依赖）
    try:
        from charset_normalizer import from_bytes  # type: ignore[import-untyped]
    except ImportError:
        pass
    else:
        detected = from_bytes(raw_bytes).best()
        if detected is not None:
            return str(detected)

    # 策略 4：兜底
    return raw_bytes.decode("utf-8", errors="replace")


def _parse_charset(content_type: str) -> Optional[str]:
    """从 Content-Type 头提取 charset 值。

    例：
        'application/json; charset=utf-8'  → 'utf-8'
        'text/xml; charset=iso-8859-1'      → 'iso-8859-1'
    """
    if not content_type:
        return None
    match = re.search(r"charset=([^\s;]+)", content_type, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().strip("'\"")
