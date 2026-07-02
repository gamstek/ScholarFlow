import os
from pathlib import Path

from huggingface_hub.constants import HF_HUB_CACHE

print("=" * 60)
print("Hugging Face 缓存位置")
print("=" * 60)

print("用户主目录：", Path.home())
print("当前 Hugging Face Hub 缓存目录：", HF_HUB_CACHE)

print("\n可能覆盖默认路径的环境变量：")
print("HF_HOME =", os.environ.get("HF_HOME"))
print("HF_HUB_CACHE =", os.environ.get("HF_HUB_CACHE"))
print(
    "SENTENCE_TRANSFORMERS_HOME =",
    os.environ.get("SENTENCE_TRANSFORMERS_HOME"),
)