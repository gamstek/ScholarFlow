"""
name_utils.py

中文作者名 → 英文拼音变体自动扩展工具。

作用：
    当用户输入中文作者名（如"张爽"），自动生成英文发表文献中
    可能出现的所有拼音格式变体，用于构建 OR 检索查询。

原理：
    1. 用 pypinyin 将中文转为拼音（无声调）
    2. 拆分姓（首字）和名（剩余字）
    3. 生成 8 种常见英文署名格式变体

变体覆盖：
    - "Shuang Zhang"     名+空格+姓（title case）
    - "Zhang Shuang"     姓+空格+名（title case）
    - "ZhangShuang"      姓名连写（title case）
    - "Zhangshuang"      姓首字母大写+名小写
    - "shuangzhang"      全小写名姓
    - "zhangshuang"      全小写姓名
    - "ShuangZhang"      名姓连写（title case）
    - "Shuangzhang"      名首字母大写+姓小写

依赖：pypinyin（pip install pypinyin）
"""

from __future__ import annotations

import re
from typing import Optional

# Unicode 范围：CJK 统一表意文字
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_chinese(text: str) -> bool:
    """检测文本是否包含中文字符。"""
    return bool(_CJK_RE.search(text))


def _get_pinyin(chars: str) -> Optional[list[str]]:
    """
    获取中文字符的拼音列表。

    返回：
        [surname_pinyin, given_pinyin, ...] 或 None（pypinyin 不可用时）
    """
    try:
        from pypinyin import lazy_pinyin, Style
        return lazy_pinyin(chars, style=Style.NORMAL)  # 无声调拼音
    except ImportError:
        return None


def expand_chinese_name(name: str) -> list[str]:
    """
    将中文作者名扩展为英文拼音变体列表。

    参数：
        name: 作者名，如 "张爽" 或 "张三丰"。

    返回：
        拼音变体列表。若不含中文或 pypinyin 不可用，返回 [name]。

    示例：
        >>> expand_chinese_name("张爽")
        ['Shuang Zhang', 'Zhang Shuang', 'ZhangShuang', 'Zhangshuang',
         'shuangzhang', 'zhangshuang', 'ShuangZhang', 'Shuangzhang']
    """
    name = name.strip()

    # 不含中文则直接返回
    if not _has_chinese(name):
        return [name]

    # 仅含中文部分才做拼音转换（兼容 "张Shuang" 这种混合输入）
    # 先提取纯中文部分用于拼音
    chinese_chars = "".join(_CJK_RE.findall(name))
    if not chinese_chars:
        return [name]

    pinyin_list = _get_pinyin(chinese_chars)
    if pinyin_list is None:
        # pypinyin 不可用，返回原值
        return [name]

    # 拆分姓（首字）和名（剩余字）
    surname_py = pinyin_list[0].capitalize()    # "Zhang"
    given_raw = "".join(pinyin_list[1:])        # "shuang"
    given_py = given_raw.capitalize()           # "Shuang"

    # 生成 8 种变体
    variants = [
        f"{given_py} {surname_py}",      # Shuang Zhang
        f"{surname_py} {given_py}",      # Zhang Shuang
        f"{surname_py}{given_py}",       # ZhangShuang
        f"{surname_py}{given_raw}",      # Zhangshuang
        f"{given_raw}{surname_py.lower()}",  # shuangzhang
        f"{surname_py.lower()}{given_raw}",  # zhangshuang
        f"{given_py}{surname_py}",       # ShuangZhang
        f"{given_py}{surname_py.lower()}",   # Shuangzhang
    ]

    return variants


def build_author_or_query(author: str, api_prefix: str = "AUTH") -> str:
    """
    将作者名（可能含中文）转换为带 OR 的 API 查询片段。

    参数：
        author: 原始作者输入，可能含中文。
        api_prefix: API 查询前缀，如 Europe PMC 用 "AUTH"、arXiv 用 "au"。

    返回：
        OR 查询片段，如：
        (AUTH:"Shuang Zhang" OR AUTH:"Zhang Shuang" OR AUTH:"ZhangShuang" OR ...)

    示例：
        >>> build_author_or_query("张爽")
        '(AUTH:"Shuang Zhang" OR AUTH:"Zhang Shuang" OR ...)'
        >>> build_author_or_query("Hinton")
        'AUTH:"Hinton"'
    """
    variants = expand_chinese_name(author)

    if len(variants) == 1:
        return f'{api_prefix}:"{variants[0]}"'

    # 多变体 OR 查询
    clauses = [f'{api_prefix}:"{v}"' for v in variants]
    return "(" + " OR ".join(clauses) + ")"
