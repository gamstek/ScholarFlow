"""
entity_normalizer.py

待实现实体归一化逻辑。

将不同来源的实体（作者、机构、期刊等）归一化为统一格式，
支持基于规则和模糊匹配的去重与合并。
"""

from __future__ import annotations


def normalize_entity(name: str, entity_type: str = "generic") -> str:
    """
    对单一实体名称做归一化处理（待实现）。

    参数：
        name: 原始实体名称。
        entity_type: 实体类型，如 "author"、"institution"、"journal"。

    返回值：
        归一化后的实体名称。

    Raises:
        NotImplementedError: 此功能尚未实现。
    """
    raise NotImplementedError("实体归一化逻辑待实现")


def normalize_entities(
    names: list[str],
    entity_type: str = "generic",
) -> list[str]:
    """
    批量归一化实体名称（待实现）。

    参数：
        names: 原始实体名称列表。
        entity_type: 实体类型。

    返回值：
        归一化后的实体名称列表。

    Raises:
        NotImplementedError: 此功能尚未实现。
    """
    raise NotImplementedError("批量实体归一化逻辑待实现")
