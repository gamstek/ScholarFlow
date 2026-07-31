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


def build_author_keyword_query(author: str) -> str:
    """
    将作者名转换为可用于关键词检索的查询字符串。

    用于当 query 为空但 author 不为空时，
    将作者名的拼音变体作为关键词检索词，帮助所有 API 都能返回结果。

    示例：
        >>> build_author_keyword_query("张爽")
        '"Shuang Zhang" "Zhang Shuang" ZhangShuang Zhangshuang shuangzhang zhangshuang ShuangZhang Shuangzhang'
        >>> build_author_keyword_query("Hinton")
        'Hinton'
    """
    variants = expand_chinese_name(author)
    # 对于含空格的变体加引号，无空格的直接拼接
    parts: list[str] = []
    for v in variants:
        if " " in v:
            parts.append(f'"{v}"')
        else:
            parts.append(v)
    return " ".join(parts)


# ============================================================
# 本地作者/机构匹配（后置过滤用）
# ============================================================

def _normalize_for_match(name: str) -> str:
    """归一化名称用于比对：小写、去标点、合并空白。"""
    name = name.lower().strip()
    name = _CJK_RE.sub("", name)  # 移除残留中文（以拼音比对）
    name = re.sub(r"[^\w\s]", "", name)  # 去标点
    name = re.sub(r"\s+", " ", name)     # 合并空白
    return name.strip()


def _parts_match(parts1: list[str], parts2: list[str]) -> bool:
    """
    检查两个名字的 part 列表是否匹配（支持首字母缩写、正序/逆序）。

    例如 ["s", "zhang"] 匹配 ["shuang", "zhang"]
         ["hinton", "g"] 匹配 ["geoffrey", "hinton"]（逆序 + 首字母缩写）
    """
    if len(parts1) != len(parts2):
        return False
    for p1, p2 in zip(parts1, parts2):
        if len(p1) == 1 and p2.startswith(p1):
            continue
        elif len(p2) == 1 and p1.startswith(p2):
            continue
        elif p1 == p2:
            continue
        else:
            return False
    return True


def _initials_match(name1: str, name2: str) -> bool:
    """
    检查两个名字是否通过首字母缩写匹配，同时尝试正序和逆序。
    例如 "s zhang" 匹配 "shuang zhang"，
        "hinton g" 匹配 "geoffrey hinton"（逆序 + 首字母缩写）。
    """
    parts1 = name1.split()
    parts2 = name2.split()

    # 正序匹配
    if _parts_match(parts1, parts2):
        return True
    # 逆序匹配（处理 "姓 名缩写" ↔ "名 姓" 等格式）
    if _parts_match(parts1, list(reversed(parts2))):
        return True

    return False


def _name_parts_overlap(nv_parts: list[str], npa_parts: list[str]) -> bool:
    """
    检查两组 name parts 是否有显著重叠（每个 part 至少部分匹配）。
    用于处理 "hinton g" 与 "geoffrey hinton" 的部分重叠场景。
    """
    if not nv_parts or not npa_parts:
        return False
    all_matched = True
    for npa_p in npa_parts:
        found = False
        for nv_p in nv_parts:
            if len(npa_p) == 1:
                # 缩写：检查是否匹配 nv 中某个 part 的首字母
                if nv_p.startswith(npa_p):
                    found = True
                    break
            elif len(nv_p) == 1:
                if npa_p.startswith(nv_p):
                    found = True
                    break
            elif npa_p == nv_p:
                found = True
                break
            elif npa_p in nv_p or nv_p in npa_p:
                found = True
                break
        if not found:
            all_matched = False
            break
    return all_matched


def match_author(target_author: str, paper_authors: list[str] | None) -> bool:
    """
    检查目标作者（可能含中文）是否匹配论文作者列表中的任意一位。

    支持：
        - 中文名自动转拼音后比对
        - 大小写不敏感
        - 首字母缩写匹配（如 "S. Zhang" ↔ "Shuang Zhang"）
        - 姓/名顺序互换匹配（如 "Hinton G" ↔ "Geoffrey Hinton"）
        - 部分重叠匹配（如 "Hinton" ↔ "Geoffrey Hinton"）

    参数：
        target_author: 用户输入的目标作者名，可能含中文。
        paper_authors: 论文的作者名列表。

    返回：
        True 表示匹配成功。
    """
    if not paper_authors:
        return False

    variants = expand_chinese_name(target_author)
    norm_variants = [_normalize_for_match(v) for v in variants]
    norm_paper_authors = [_normalize_for_match(a) for a in paper_authors if a]

    for nv in norm_variants:
        if not nv:
            continue
        nv_parts = nv.split()
        for npa in norm_paper_authors:
            if not npa:
                continue
            # 精确匹配
            if nv == npa:
                return True
            # 首字母缩写匹配（正序+逆序）
            if _initials_match(nv, npa):
                return True
            # 双向包含（处理 "Zhang" 匹配 "Zhang, Shuang" 等格式）
            if nv in npa or npa in nv:
                return True
            # Parts 重叠匹配（处理 "Hinton G" ↔ "Geoffrey Hinton" 等交叉情况）
            npa_parts = npa.split()
            if _name_parts_overlap(nv_parts, npa_parts):
                return True

    return False



