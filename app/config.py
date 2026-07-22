"""
config.py

ScholarFlow 全局配置 —— 所有模块的唯一配置入口。

设计原则：
    1. 单一事实来源：所有模块从此处读取配置，不再各自读环境变量或硬编码
    2. 延迟加载：首次调用 get_config() 时才解析 .env，避免 import 顺序依赖
    3. 线程安全：使用 threading.Lock 保护单例创建
    4. 零新依赖：仅使用标准库 + dotenv（项目已有）

用法：
    from app.config import get_config

    cfg = get_config()
    print(cfg.llm_backend)       # "deepseek"
    print(cfg.database_url)      # "postgresql+asyncpg://..."
    print(cfg.is_cloud_backend)  # True
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional


# ============================================================
# 项目根目录
# ============================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _find_dotenv() -> Optional[Path]:
    """查找 .env 文件（优先项目根目录）。"""
    candidate = _PROJECT_ROOT / ".env"
    return candidate if candidate.exists() else None


def _load_dotenv() -> None:
    """
    加载 .env 到 os.environ（幂等：只执行一次）。

    注意：main.py 中也调用了 load_dotenv()，这里做二次保障，
    确保非 FastAPI 入口（如 scripts 或独立 import）也能读取配置。
    """
    dotenv_path = _find_dotenv()
    if dotenv_path is None:
        return

    try:
        from dotenv import load_dotenv as _load
        _load(dotenv_path=dotenv_path, override=False)
    except ImportError:
        # dotenv 未安装时，依赖调用方手动加载
        pass


# ============================================================
# AppConfig
# ============================================================

class AppConfig:
    """
    ScholarFlow 全局配置。

    所有字段对应 .env 中的变量名，提供类型化的属性访问。
    不依赖 pydantic_settings，纯 Python 实现。
    """

    def __init__(self) -> None:
        # 确保 .env 已加载
        _load_dotenv()

        # ========== 数据库 ==========
        self.database_url: str = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:scholarflow@127.0.0.1:5433/scholarflow",
        )

        # ========== LLM 后端选择 ==========
        self.llm_backend: str = os.getenv("LLM_BACKEND", "ollama").strip().lower()
        # 合法值：ollama / deepseek / openai / qwen

        # 本地 Ollama
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
        self.ollama_base_url: str = os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        ).rstrip("/")

        # 云端 API（LLM_BACKEND != ollama 时生效）
        self.cloud_api_key: str = os.getenv("CLOUD_API_KEY", "")
        self.cloud_api_base: str = os.getenv(
            "CLOUD_API_BASE", "https://api.deepseek.com/v1"
        ).rstrip("/")
        self.cloud_model: str = os.getenv("CLOUD_MODEL", "deepseek-chat")

        # ========== Embedding ==========
        self.bge_model_path: str = os.getenv("BGE_MODEL_PATH", "embedding/bge-m3")
        self.hf_hub_offline: bool = (
            os.getenv("HF_HUB_OFFLINE", "0").strip() == "1"
        )

        # ========== 生成默认参数 ==========
        self.default_temperature: float = float(
            os.getenv("DEFAULT_TEMPERATURE", "0.3")
        )
        self.default_num_ctx: int = int(
            os.getenv("DEFAULT_NUM_CTX", "4096")
        )
        self.default_num_predict: int = int(
            os.getenv("DEFAULT_NUM_PREDICT", "512")
        )
        self.translate_max_tokens: int = int(
            os.getenv("TRANSLATE_MAX_TOKENS", "4096")
        )
        self.review_num_predict: int = int(
            os.getenv("REVIEW_NUM_PREDICT", "2048")
        )

    # ================================================================
    # 派生属性
    # ================================================================

    @property
    def is_cloud_backend(self) -> bool:
        """是否使用云端 API（非 Ollama）。"""
        return self.llm_backend != "ollama"

    @property
    def active_model_name(self) -> str:
        """当前激活的 LLM 模型名称。"""
        if self.is_cloud_backend:
            return self.cloud_model
        return self.ollama_model

    @property
    def active_base_url(self) -> str:
        """当前激活的 LLM 服务地址。"""
        if self.is_cloud_backend:
            return self.cloud_api_base
        return self.ollama_base_url

    # ================================================================
    # 校验
    # ================================================================

    def validate(self) -> list[str]:
        """
        校验配置完整性，返回警告列表（空列表表示一切正常）。

        FastAPI lifespan 中调用此方法，在启动时打印配置问题。
        """
        warnings: list[str] = []

        if self.is_cloud_backend:
            if not self.cloud_api_key:
                warnings.append(
                    f"LLM_BACKEND={self.llm_backend} 但 CLOUD_API_KEY 未设置，"
                    f"云端 API 将不可用"
                )
        else:
            # Ollama 模式：仅提示（不阻塞启动，因为 Ollama 可能后启动）
            pass

        return warnings

    def summary(self) -> str:
        """单行配置摘要，用于启动日志。"""
        return (
            f"LLM: {self.llm_backend} | "
            f"model: {self.active_model_name} | "
            f"db: {_mask_password(self.database_url)} | "
            f"embedding: {self.bge_model_path} | "
            f"offline: {self.hf_hub_offline}"
        )


def _mask_password(url: str) -> str:
    """隐藏数据库 URL 中的密码（用于日志打印）。"""
    import re
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", url)


# ============================================================
# 单例管理
# ============================================================

_config: Optional[AppConfig] = None
_lock = threading.Lock()


def get_config() -> AppConfig:
    """
    获取 AppConfig 全局单例（线程安全，延迟加载）。

    用法：
        from app.config import get_config
        cfg = get_config()
    """
    global _config
    if _config is None:
        with _lock:
            if _config is None:
                _config = AppConfig()
    return _config


def reset_config() -> None:
    """
    重置配置单例（仅用于测试）。

    生产代码不应调用此函数。
    """
    global _config
    with _lock:
        _config = None
