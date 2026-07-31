#!/usr/bin/env python3
"""
ScholarFlow 公共环境工具模块
============================
被 check_env.py / fix_env.py / check_gui.py 共享引用。
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 从 _lib/ → skills/ → .github/ → 项目根目录（4 级向上）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 默认 conda 环境名
DEFAULT_CONDA_ENV = "scholarflow"


# ---------------------------------------------------------------------------
# 命令执行
# ---------------------------------------------------------------------------

def run_cmd(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """运行命令，返回 (returncode, stdout, stderr).

    强制使用 UTF-8 编码，避免 Windows 下 GBK/管道编码错配导致中文乱码。
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=(sys.platform == "win32"),
            encoding="utf-8",
            errors="replace",
        )
        stdout = proc.stdout.strip() if proc.stdout else ""
        stderr = proc.stderr.strip() if proc.stderr else ""
        return proc.returncode, stdout, stderr
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0] if isinstance(cmd, list) else cmd}"
    except subprocess.TimeoutExpired:
        return -2, "", f"Command timed out: {cmd[0] if isinstance(cmd, list) else cmd}"


# ---------------------------------------------------------------------------
# Conda 环境检测
# ---------------------------------------------------------------------------

def list_conda_envs(env_name: str = DEFAULT_CONDA_ENV) -> Dict[str, Any]:
    """列出所有 conda 环境，检查指定环境是否存在.

    Returns:
        {
            "conda_available": bool,
            "target_exists": bool,
            "target_path": str | None,
            "all_envs": List[str],
        }
    """
    result: Dict[str, Any] = {
        "conda_available": False,
        "target_exists": False,
        "target_path": None,
        "all_envs": [],
    }

    ret, out, _ = run_cmd(["conda", "--version"])
    if ret != 0:
        return result
    result["conda_available"] = True

    ret2, out2, _ = run_cmd(["conda", "env", "list"])
    if ret2 != 0:
        return result

    for line in out2.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        # 跳过路径格式的行（以盘符、/、\\ 开头）
        if re.match(r"^[A-Za-z]:|^/|^\\", name):
            continue
        if name == "base":
            continue
        result["all_envs"].append(name)
        if name == env_name:
            result["target_exists"] = True
            for p in parts[1:]:
                if p not in ("*", ""):
                    result["target_path"] = p
                    break

    return result


def get_active_env() -> Optional[str]:
    """获取当前激活的 conda 环境名."""
    return os.environ.get("CONDA_DEFAULT_ENV", None)


def detect_conda() -> Dict[str, Any]:
    """检测完整 conda 环境信息（向后兼容 check_env.py）."""
    envs = list_conda_envs()
    active = get_active_env()

    result: Dict[str, Any] = {
        "conda_available": envs["conda_available"],
        "in_conda_env": active is not None,
        "env_name": active,
        "env_prefix": os.environ.get("CONDA_PREFIX", None),
        "is_scholarflow_env": (active == DEFAULT_CONDA_ENV),
        "scholarflow_exists": envs["target_exists"],
        "scholarflow_path": envs["target_path"],
        "all_envs": envs["all_envs"],
    }

    # 如果不在 conda 环境中，尝试通过 conda info 获取
    if not active:
        ret2, out2, _ = run_cmd(["conda", "info", "--json"])
        if ret2 == 0:
            try:
                import json
                info = json.loads(out2)
                active_prefix = info.get("active_prefix_name") or info.get("active_prefix")
                if active_prefix:
                    result["in_conda_env"] = True
                    if isinstance(active_prefix, str) and not active_prefix.startswith("/"):
                        result["env_name"] = active_prefix
                    else:
                        result["env_name"] = os.path.basename(str(active_prefix))
                    result["is_scholarflow_env"] = (result["env_name"] == DEFAULT_CONDA_ENV)
            except (json.JSONDecodeError, Exception):
                pass

    return result


def create_conda_env(name: str = DEFAULT_CONDA_ENV, python_ver: str = "3.11") -> bool:
    """创建 conda 环境."""
    print(f"[创建] 正在创建 conda 环境 '{name}' (Python {python_ver})...")
    ret, out, err = run_cmd(
        ["conda", "create", "-n", name, f"python={python_ver}", "-y"],
        timeout=300,
    )
    if ret == 0:
        print(f"[成功] 环境 '{name}' 创建完成。")
        return True
    else:
        print(f"[失败] 创建环境失败:\n{err or out}")
        return False
