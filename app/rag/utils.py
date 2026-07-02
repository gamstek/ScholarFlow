"""
utils.py

RAG 模块通用工具函数。
"""

from __future__ import annotations

import numpy as np


def ensure_float32_array(array: np.ndarray) -> np.ndarray:
    """
    确保 numpy array 是 float32 且内存连续。

    FAISS 通常要求输入为 float32。
    """
    array = np.asarray(array, dtype=np.float32)

    if not array.flags["C_CONTIGUOUS"]:
        array = np.ascontiguousarray(array)

    return array
