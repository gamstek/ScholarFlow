"""
evaluate_retrieval.py

检索效果评估脚本。

作用：
1. 加载本地 FAISS 索引和 chunk 数据；
2. 使用标注的 query-answer 对评估检索命中率；
3. 输出 Precision@k、Recall@k、MRR 等指标。

⚠ 待后续实现评估逻辑与标注数据集构建。
"""

from __future__ import annotations


def main() -> None:
    """检索评估入口函数。"""
    raise NotImplementedError("evaluate_retrieval 待实现")


if __name__ == "__main__":
    main()
