"""
vector_store.py

FAISS 向量库模块。

作用：
1. 创建 FAISS IndexFlatIP 索引；
2. 保存 / 加载 FAISS 索引；
3. 保存 / 加载 chunk metadata；
4. 添加 chunk embeddings；
5. 根据 query embedding 检索相似 chunks。

当前使用：
    FAISS IndexFlatIP

说明：
    因为 embedder.py 默认对向量做了 L2 normalize，
    所以 IndexFlatIP 的内积相似度可以近似理解为 cosine similarity。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.storage.database import INDEX_DIR, ensure_data_dirs


@dataclass
class SearchResult:
    """
    FAISS 检索结果。

    字段说明：
        rank:
            排名，从 1 开始。

        score:
            相似度分数。

        faiss_vector_id:
            FAISS 内部向量编号。

        metadata:
            向量对应的 chunk metadata。
    """

    rank: int
    score: float
    faiss_vector_id: int
    metadata: dict[str, Any]


class FaissVectorStore:
    """
    FAISS 向量库。

    保存两个文件：
        data/index/faiss.index
        data/index/chunk_metadata.json

    metadata 列表的下标必须和 FAISS 向量 ID 一一对应：
        metadata[0] 对应 FAISS 第 0 个向量
        metadata[1] 对应 FAISS 第 1 个向量
    """

    def __init__(
        self,
        dimension: int,
        index_path: Path | None = None,
        metadata_path: Path | None = None,
    ) -> None:
        """
        初始化向量库。

        参数：
            dimension:
                embedding 向量维度。

            index_path:
                FAISS index 保存路径。

            metadata_path:
                chunk metadata 保存路径。
        """
        self.dimension = dimension

        ensure_data_dirs()

        self.index_path = index_path or (INDEX_DIR / "faiss.index")
        self.metadata_path = metadata_path or (INDEX_DIR / "chunk_metadata.json")

        self.index = None
        self.metadata: list[dict[str, Any]] = []

    def create_empty_index(self) -> None:
        """
        创建一个空的 FAISS IndexFlatIP 索引。
        """
        try:
            import faiss
        except ImportError as exc:
            raise ImportError(
                "缺少 faiss。请先运行：\n"
                "pip install faiss-cpu\n"
                "或者：conda install -c conda-forge faiss-cpu"
            ) from exc

        self.index = faiss.IndexFlatIP(self.dimension)
        self.metadata = []

    def load_or_create(self) -> None:
        """
        如果本地已有索引，则加载；
        否则创建空索引。
        """
        if self.index_path.exists() and self.metadata_path.exists():
            self.load()
        else:
            self.create_empty_index()

    def load(self) -> None:
        """
        从磁盘加载 FAISS index 和 metadata。
        """
        try:
            import faiss
        except ImportError as exc:
            raise ImportError(
                "缺少 faiss。请先运行：pip install faiss-cpu"
            ) from exc

        if not self.index_path.exists():
            raise FileNotFoundError(f"FAISS index 不存在：{self.index_path}")

        if not self.metadata_path.exists():
            raise FileNotFoundError(f"metadata 文件不存在：{self.metadata_path}")

        self.index = faiss.read_index(str(self.index_path))

        with self.metadata_path.open("r", encoding="utf-8") as file:
            self.metadata = json.load(file)

        if self.index.d != self.dimension:
            raise ValueError(
                f"索引维度不匹配：index.d={self.index.d}, "
                f"expected={self.dimension}"
            )

        if self.index.ntotal != len(self.metadata):
            raise ValueError(
                f"FAISS 向量数量和 metadata 数量不一致："
                f"ntotal={self.index.ntotal}, metadata={len(self.metadata)}"
            )

    def save(self) -> None:
        """
        保存 FAISS index 和 metadata 到磁盘。
        """
        if self.index is None:
            raise RuntimeError("index 尚未初始化。")

        try:
            import faiss
        except ImportError as exc:
            raise ImportError(
                "缺少 faiss。请先运行：pip install faiss-cpu"
            ) from exc

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

        faiss.write_index(self.index, str(self.index_path))

        with self.metadata_path.open("w", encoding="utf-8") as file:
            json.dump(
                self.metadata,
                file,
                ensure_ascii=False,
                indent=2,
            )

    def add_embeddings(
        self,
        embeddings: np.ndarray,
        metadata_list: list[dict[str, Any]],
    ) -> list[int]:
        """
        添加 embeddings 到 FAISS。

        参数：
            embeddings:
                shape = [n, dimension] 的 float32 numpy array。

            metadata_list:
                每个向量对应的 metadata。

        返回：
            新增向量对应的 faiss_vector_id 列表。
        """
        if self.index is None:
            raise RuntimeError("index 尚未初始化，请先调用 load_or_create。")

        embeddings = ensure_float32_array(embeddings)

        if embeddings.ndim != 2:
            raise ValueError("embeddings 必须是二维数组。")

        if embeddings.shape[1] != self.dimension:
            raise ValueError(
                f"embedding 维度不匹配：{embeddings.shape[1]} != {self.dimension}"
            )

        if embeddings.shape[0] != len(metadata_list):
            raise ValueError(
                "embeddings 数量和 metadata 数量不一致。"
            )

        start_id = int(self.index.ntotal)

        self.index.add(embeddings)

        vector_ids = list(
            range(
                start_id,
                start_id + embeddings.shape[0],
            )
        )

        for vector_id, metadata in zip(vector_ids, metadata_list):
            item = dict(metadata)
            item["faiss_vector_id"] = vector_id
            self.metadata.append(item)

        return vector_ids

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """
        根据 query embedding 检索相似 chunks。

        参数：
            query_embedding:
                shape = [1, dimension] 的向量。

            top_k:
                返回前 k 个结果。

        返回：
            SearchResult 列表。
        """
        if self.index is None:
            raise RuntimeError("index 尚未初始化。")

        if self.index.ntotal == 0:
            return []

        query_embedding = ensure_float32_array(query_embedding)

        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        if query_embedding.shape[1] != self.dimension:
            raise ValueError(
                f"query embedding 维度不匹配："
                f"{query_embedding.shape[1]} != {self.dimension}"
            )

        top_k = max(1, min(top_k, int(self.index.ntotal)))

        scores, indices = self.index.search(
            query_embedding,
            top_k,
        )

        results: list[SearchResult] = []

        for rank, (score, vector_id) in enumerate(
            zip(scores[0], indices[0]),
            start=1,
        ):
            if vector_id < 0:
                continue

            metadata = self.metadata[int(vector_id)]

            results.append(
                SearchResult(
                    rank=rank,
                    score=float(score),
                    faiss_vector_id=int(vector_id),
                    metadata=metadata,
                )
            )

        return results

    def reset(self) -> None:
        """
        重置索引。

        作用：
            1. 删除内存中的 FAISS index；
            2. 清空 metadata；
            3. 删除磁盘上的索引文件。

        注意：
            这个方法不会修改数据库 chunks 表。
            数据库状态重置由脚本负责。
        """
        self.create_empty_index()

        if self.index_path.exists():
            self.index_path.unlink()

        if self.metadata_path.exists():
            self.metadata_path.unlink()

    @property
    def ntotal(self) -> int:
        """
        当前索引中的向量数量。
        """
        if self.index is None:
            return 0

        return int(self.index.ntotal)


from app.rag.utils import ensure_float32_array  # noqa: F401