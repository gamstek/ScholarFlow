"""
embedder.py

文本向量化模块 Text Embedder。

作用：
1. 加载 embedding 模型；
2. 将论文 chunks 转换成向量；
3. 将用户问题转换成向量；
4. 为 FAISS 语义检索提供输入。

当前默认模型：
    BAAI/bge-m3

为什么使用 BGE-M3？
    1. 支持中英文；
    2. 对检索任务 Retrieval 较友好；
    3. 适合文献、技术文本、长文本语义匹配；
    4. 你前面的轻量 RAG 系统本来就计划使用 BGE-M3。

模型加载优先级：
    1. .env 中 BGE_MODEL_PATH 指向的有效本地路径
    2. 项目根目录 embedding/bge-m3/（本地模型文件夹）
    3. "BAAI/bge-m3"（HuggingFace Hub 自动下载）

离线使用：
    设置环境变量 HF_HUB_OFFLINE=1 并确保模型已在本地。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


# ============================================================
# Embedding 模型路径解析
# ============================================================

# embedder.py 位于 app/rag/，项目根目录 = parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EMBEDDING_DIR = _PROJECT_ROOT / "embedding"
_DEFAULT_LOCAL_MODEL_DIR = _EMBEDDING_DIR / "bge-m3"

# HuggingFace Hub 上的模型标识（作为最终回退）
_HF_BGE_M3_NAME = "BAAI/bge-m3"


def _resolve_embedding_model_path() -> str:
    """
    解析 embedding 模型路径。

    优先级：
        1. 环境变量 BGE_MODEL_PATH 指向的有效本地路径
        2. 项目根目录 embedding/bge-m3/（如果存在）
        3. BAAI/bge-m3（HuggingFace Hub 自动下载）

    返回：
        模型路径字符串。
    """
    env_path = os.getenv("BGE_MODEL_PATH", "").strip()

    # 优先级 1：环境变量明确指向存在的本地路径
    if env_path:
        env_resolved = Path(env_path)
        if not env_resolved.is_absolute():
            env_resolved = (_PROJECT_ROOT / env_path).resolve()
        if env_resolved.exists():
            return str(env_resolved)

    # 优先级 2：项目根目录下的 embedding/bge-m3/
    if _DEFAULT_LOCAL_MODEL_DIR.exists():
        return str(_DEFAULT_LOCAL_MODEL_DIR)

    # 优先级 3：回退到 HuggingFace Hub 名称
    return _HF_BGE_M3_NAME


# 模块级默认路径（导入时解析一次）
DEFAULT_EMBEDDING_MODEL = _resolve_embedding_model_path()


@dataclass
class EmbeddingResult:
    """
    向量化结果。

    字段说明：
        texts:
            原始文本列表。

        embeddings:
            numpy array，形状为：
                [文本数量, 向量维度]

        dimension:
            向量维度。
    """

    texts: list[str]
    embeddings: np.ndarray
    dimension: int


class TextEmbedder:
    """
    文本向量化器。

    当前使用 sentence-transformers 加载 BGE-M3。

    主要方法：
        encode_texts:
            批量向量化文本。

        encode_query:
            向量化用户问题。
    """

    # 默认 embedding 模型路径（自动解析：本地 > HuggingFace Hub）
    DEFAULT_MODEL = DEFAULT_EMBEDDING_MODEL

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        normalize_embeddings: bool = True,
    ) -> None:
        """
        初始化向量化模型。

        参数：
            model_name:
                模型名称或本地模型路径。

            device:
                运行设备。
                可选：
                    None：自动判断；
                    "cpu"：CPU；
                    "cuda"：GPU。

            normalize_embeddings:
                是否对向量做 L2 归一化。
                归一化后，FAISS IndexFlatIP 的内积相似度就等价于 cosine similarity。
        """
        self.model_name = model_name
        self.device = device
        self.normalize_embeddings = normalize_embeddings

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "缺少 sentence-transformers。请先运行：\n"
                "pip install sentence-transformers"
            ) from exc

        # HF_HUB_OFFLINE=1 时强制从本地缓存加载，不联网验证
        _local_only = os.getenv("HF_HUB_OFFLINE") == "1"

        if device:
            self.model = SentenceTransformer(
                model_name,
                device=device,
                local_files_only=_local_only,
            )
        else:
            self.model = SentenceTransformer(
                model_name,
                local_files_only=_local_only,
            )

        self.dimension = self._infer_dimension()

    def _infer_dimension(self) -> int:
        """
        推断 embedding 向量维度。

        方法：
            用一个短文本做一次 encode，然后读取向量长度。
        """
        vector = self.model.encode(
            ["dimension test"],
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return int(vector.shape[1])

    def encode_texts(
        self,
        texts: Iterable[str],
        batch_size: int = 16,
        show_progress_bar: bool = True,
    ) -> EmbeddingResult:
        """
        批量向量化文本。

        参数：
            texts:
                文本列表。

            batch_size:
                批处理大小。
                显存小就调小，例如 4 或 8；
                显存足够可以调大，例如 32。

            show_progress_bar:
                是否显示进度条。

        返回：
            EmbeddingResult。
        """
        text_list = [text for text in texts if text and text.strip()]

        if not text_list:
            raise ValueError("没有可向量化的文本。")

        embeddings = self.model.encode(
            text_list,
            batch_size=batch_size,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=show_progress_bar,
        )

        embeddings = ensure_float32_array(embeddings)

        return EmbeddingResult(
            texts=text_list,
            embeddings=embeddings,
            dimension=int(embeddings.shape[1]),
        )

    def encode_query(
        self,
        query: str,
    ) -> np.ndarray:
        """
        向量化用户查询问题。

        参数：
            query:
                用户问题。

        返回：
            shape = [1, dimension] 的 numpy array。
        """
        if not query or not query.strip():
            raise ValueError("query 不能为空。")

        embedding = self.model.encode(
            [query],
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        return ensure_float32_array(embedding)


from app.rag.utils import ensure_float32_array  # noqa: F401