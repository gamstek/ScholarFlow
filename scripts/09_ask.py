"""
ask_local_rag.py

本地 RAG 问答脚本。

推荐运行：

    python scripts/ask_local_rag.py --question "HMO 的 LC-MS/MS 结构解析通常用哪些方法？" --embedding-device cuda --ollama-model qwen3:8b

如果本地模型慢，使用：

    python scripts/ask_local_rag.py --question "HMO 的 LC-MS/MS 结构解析通常用哪些方法？" --top-k 2 --max-chars-per-evidence 600 --num-ctx 4096 --num-predict 384 --timeout 900 --embedding-device cuda --ollama-model qwen3:8b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from app.rag.embedder import DEFAULT_EMBEDDING_MODEL  # noqa: E402
from app.rag.rag_engine import LocalRagEngine  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="基于本地文献知识库进行 RAG 问答。"
    )

    parser.add_argument(
        "--question",
        type=str,
        default="HMO 的 LC-MS/MS 结构解析通常用哪些方法？",
        help="用户问题。",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="检索前 k 个 chunk。建议本地 8B 模型先用 2 或 3。",
    )

    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="最低检索相似度分数，可选。",
    )

    parser.add_argument(
        "--section-filter",
        type=str,
        default=None,
        help="章节过滤，多个章节用逗号分隔。",
    )

    parser.add_argument(
        "--year-from",
        type=int,
        default=None,
        help="起始年份过滤。",
    )

    parser.add_argument(
        "--year-to",
        type=int,
        default=None,
        help="结束年份过滤。",
    )

    parser.add_argument(
        "--embedding-model",
        type=str,
        default=DEFAULT_EMBEDDING_MODEL,
        help="embedding 模型名称或本地路径。",
    )

    parser.add_argument(
        "--embedding-device",
        type=str,
        default=None,
        help="embedding 设备，例如 cpu / cuda。",
    )

    parser.add_argument(
        "--ollama-model",
        type=str,
        default="qwen3:8b",
        help="Ollama 模型名称。",
    )

    parser.add_argument(
        "--ollama-base-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama 服务地址。",
    )

    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="生成温度。",
    )

    parser.add_argument(
        "--num-ctx",
        type=int,
        default=4096,
        help="Ollama 上下文窗口大小。qwen3:8b 本地建议先用 4096。",
    )

    parser.add_argument(
        "--num-predict",
        type=int,
        default=512,
        help="最大输出 token 数。越大越慢。",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Ollama HTTP 请求超时时间，单位秒。",
    )

    parser.add_argument(
        "--max-chars-per-evidence",
        type=int,
        default=1000,
        help="每条证据最多放入 prompt 的字符数。本地 8B 建议 600~1200。",
    )

    parser.add_argument(
        "--language",
        type=str,
        default="zh",
        choices=["zh", "en"],
        help="回答语言。",
    )

    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="只检索证据，不调用 Ollama 生成回答。",
    )

    parser.add_argument(
        "--show-context",
        action="store_true",
        help="是否打印实际送入模型的 context。",
    )

    parser.add_argument(
        "--save-json",
        type=str,
        default=None,
        help="可选：将完整结果保存为 JSON 文件。",
    )

    return parser.parse_args()


def parse_section_filter(value: Optional[str]) -> Optional[list[str]]:
    """
    解析章节过滤参数。
    """
    if not value:
        return None

    sections = [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]

    return sections or None


async def main() -> None:
    """
    主函数。
    """
    args = parse_args()

    section_filter = parse_section_filter(args.section_filter)

    print("=" * 80)
    print("本地文献知识库 RAG 问答流程")
    print("=" * 80)
    print(f"question: {args.question}")
    print(f"top_k: {args.top_k}")
    print(f"min_score: {args.min_score}")
    print(f"section_filter: {section_filter}")
    print(f"year_from: {args.year_from}")
    print(f"year_to: {args.year_to}")
    print(f"embedding_model: {args.embedding_model}")
    print(f"embedding_device: {args.embedding_device}")
    print(f"ollama_model: {args.ollama_model}")
    print(f"num_ctx: {args.num_ctx}")
    print(f"num_predict: {args.num_predict}")
    print(f"timeout: {args.timeout}")
    print(f"max_chars_per_evidence: {args.max_chars_per_evidence}")
    print(f"generate: {not args.no_generate}")
    print("=" * 80)

    engine = LocalRagEngine(
        embedding_model_name=args.embedding_model,
        embedding_device=args.embedding_device,
        ollama_model=args.ollama_model,
        ollama_base_url=args.ollama_base_url,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        num_predict=args.num_predict,
        timeout=args.timeout,
    )

    result = await engine.ask(
        question=args.question,
        top_k=args.top_k,
        min_score=args.min_score,
        section_filter=section_filter,
        year_from=args.year_from,
        year_to=args.year_to,
        max_chars_per_evidence=args.max_chars_per_evidence,
        language=args.language,
        generate=not args.no_generate,
    )

    print("\n" + "=" * 80)
    print("回答结果")
    print("=" * 80)
    print(result.answer)

    print("\n" + "=" * 80)
    print("参考文献来源")
    print("=" * 80)

    if not result.sources:
        print("暂无参考来源。")
    else:
        for source in result.sources:
            print("-" * 80)
            print(f"[{source['source_id']}]")
            print(f"score: {source['score']:.4f}")
            print(f"title: {source['paper_title']}")
            print(f"year: {source['year']}")
            print(f"journal: {source['journal']}")
            print(f"doi: {source['doi']}")
            print(f"section: {source['section_title']}")
            print(f"pages: {source['page_start']} - {source['page_end']}")
            print(f"chunk_id: {source['chunk_id']}")

    if args.show_context:
        print("\n" + "=" * 80)
        print("传入模型的上下文内容")
        print("=" * 80)
        print(result.context)

    if args.save_json:
        output_path = Path(args.save_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output_data = {
            "question": result.question,
            "answer": result.answer,
            "model": result.model,
            "sources": result.sources,
            "context": result.context,
        }

        with output_path.open("w", encoding="utf-8") as file:
            json.dump(
                output_data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print(f"\n完整结果已保存到：{output_path}")

    print("\n本地 RAG 问答流程已完成。")


if __name__ == "__main__":
    asyncio.run(main())