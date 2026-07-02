"""
test_ollama_chinese.py

测试 Python 调用 Ollama 时中文是否能正常传入模型。

运行方式：
    python scripts/test_ollama_chinese.py
"""

from __future__ import annotations

import json
import urllib.request


def main() -> None:
    """
    使用 Python 原生 urllib 向 Ollama 发送中文 prompt。
    """
    url = "http://localhost:11434/api/generate"

    payload = {
        "model": "qwen3:8b",
        "prompt": "请只输出两个字：成功",
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": 0,
            "num_predict": 32,
            "num_ctx": 2048,
        },
    }

    # ensure_ascii=False：JSON 中保留中文
    # encode("utf-8")：明确使用 UTF-8 发送
    data = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read().decode("utf-8")
        result = json.loads(body)

    print("response:")
    print(result.get("response"))

    print("\nraw result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()