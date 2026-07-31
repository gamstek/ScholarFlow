#!/usr/bin/env python3
"""
ScholarFlow 环境依赖检测脚本
=============================
用法: python check_env.py [--json] [--quiet] [--target-env NAME]

输出结构化检测报告，覆盖:
  - Conda 环境（当前环境名称、是否为 scholarflow）
  - Python 版本
  - pip 包依赖 (基于 requirements.txt)
  - PyTorch / CUDA / MPS 可用性 + GPU 架构匹配
  - Ollama 服务状态 + 已安装模型
  - PostgreSQL 连接可用性
  - FAISS 向量索引
  - Sentence Transformer 模型
  - 磁盘空间

选项:
  --json        以 JSON 格式输出结果
  --quiet       仅输出失败项（静默模式）
  --target-env   指定要检测的 conda 环境名称（在该环境中运行检测）
  --help        显示帮助
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 导入共享环境工具模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from env_utils import PROJECT_ROOT, DEFAULT_CONDA_ENV, run_cmd, detect_conda  # noqa: E402

# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

# requirements 路径（基础依赖，不含 GPU 专用 torch 版本）
REQUIREMENTS_DIR = PROJECT_ROOT / "requirements"
REQUIREMENTS_PATH = REQUIREMENTS_DIR / "requirements.txt"

# 期望的 Python 版本范围（ScholarFlow 依赖 sentence-transformers>=5.6, langchain>=1.0）
PYTHON_MIN = (3, 10)
PYTHON_MAX = (3, 12)

# 磁盘空间阈值 (GB)
DISK_MIN_GB = 2

# GPU 架构 → 期望 PyTorch 版本映射
# 各 GPU 系列对应的依赖文件: requirements/requirements-rtxXX.txt
GPU_ARCH_RULES = {
    (12,): {"min_torch": "2.7.0", "cuda_tag": "cu128", "label": "RTX 50 系 (Blackwell)", "req_file": "requirements/requirements-rtx50.txt"},
    (8, 9): {"min_torch": "2.5.0", "cuda_tag": "cu124", "label": "RTX 40 系 (Ada Lovelace)", "req_file": "requirements/requirements-rtx40.txt"},
    (8, 6): {"min_torch": "2.5.0", "cuda_tag": "cu121", "label": "RTX 30 系 (Ampere)", "req_file": "requirements/requirements-rtx30.txt"},
    (7, 5): {"min_torch": "2.5.0", "cuda_tag": "cu124", "label": "RTX 20 / GTX 16 系 (Turing)", "req_file": "requirements/requirements-rtx40.txt"},
}

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def parse_requirements(path: Path) -> Dict[str, str]:
    """
    解析 requirements.txt，返回 {package_name: version_spec}.
    处理注释、--index-url、空行。
    """
    packages: Dict[str, str] = {}
    if not path.exists():
        return packages

    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        # 跳过注释、空行、--index-url
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        # 解析包名和版本
        # 支持格式: pkg==1.0, pkg>=1.0, pkg>=1.0,<2.0, pkg>=1.0 ; python_version >= "3.10"
        match = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*((?:[><=!~]+\s*[0-9\.\*]+(?:\s*,\s*[><=!~]+\s*[0-9\.\*]+)*)?)", line)
        if match:
            name = match.group(1).lower().replace("_", "-")
            spec = match.group(2).strip().replace(" ", "") if match.group(2) else "*"
            packages[name] = spec
    return packages


def parse_pip_list() -> Dict[str, str]:
    """通过 pip list --format=json 获取已安装包 {name: version}."""
    ret, out, err = run_cmd([sys.executable, "-m", "pip", "list", "--format=json"])
    if ret != 0:
        # 尝试用 --format=columns 回退
        ret2, out2, _ = run_cmd([sys.executable, "-m", "pip", "list", "--format=columns"])
        if ret2 != 0:
            return {}
        packages: Dict[str, str] = {}
        for line in out2.splitlines()[2:]:  # 跳过表头
            parts = line.split()
            if len(parts) >= 2:
                packages[parts[0].lower().replace("_", "-")] = parts[1]
        return packages

    try:
        data = json.loads(out)
        return {item["name"].lower().replace("_", "-"): item["version"] for item in data}
    except json.JSONDecodeError:
        return {}


def version_tuple(v: str) -> Tuple[int, ...]:
    """将版本字符串转为可比较的元组，如 '2.7.0+cu128' → (2, 7, 0)."""
    v = v.split("+")[0].split("-")[0]  # 去掉 +cu128, -rc1 等后缀
    parts = v.split(".")
    return tuple(int(p) for p in parts if p.isdigit())


def check_version_satisfied(installed: str, spec: str) -> bool:
    """检查已安装版本是否满足 requirements.txt 中的约束."""
    if spec == "*":
        return True
    if not installed:
        return False

    iv = version_tuple(installed)

    # 处理逗号分隔的多重约束，如 ">=6.7.0,<6.8.0"
    constraints = [c.strip() for c in spec.split(",") if c.strip()]
    for constraint in constraints:
        m = re.match(r"^([><=!~]+)\s*([0-9\.]+)$", constraint)
        if not m:
            continue
        op, target = m.group(1), m.group(2)
        tv = version_tuple(target)
        if op == "==" and iv != tv:
            return False
        elif op == ">=" and iv < tv:
            return False
        elif op == ">" and iv <= tv:
            return False
        elif op == "<=" and iv > tv:
            return False
        elif op == "<" and iv >= tv:
            return False
        elif op == "!=" and iv == tv:
            return False
        elif op == "~=":
            # ~=X.Y 表示 >=X.Y, ==X.*
            if iv < tv:
                return False
            if len(tv) >= 2 and iv[:2] != tv[:2]:
                return False
    return True


# detect_conda() 已从 _lib.env_utils 导入


def detect_gpu() -> Optional[Dict[str, Any]]:
    """检测 NVIDIA GPU 信息."""
    ret, out, _ = run_cmd(["nvidia-smi", "--query-gpu=name,compute_cap", "--format=csv,noheader"])
    if ret != 0 or not out:
        return None
    parts = out.split(",")
    if len(parts) < 2:
        return None
    name = parts[0].strip()
    cc_str = parts[1].strip()
    try:
        cc = tuple(int(x) for x in cc_str.split("."))
    except ValueError:
        cc = ()
    return {"name": name, "compute_capability": cc, "cc_str": cc_str}


def get_gpu_arch_rule(cc: Tuple[int, ...]) -> Optional[Dict[str, Any]]:
    """根据计算能力返回对应的架构规则."""
    if not cc:
        return None
    major = cc[0]
    minor = cc[1] if len(cc) > 1 else 0
    # 检查精确匹配
    for cc_key, rule in GPU_ARCH_RULES.items():
        if major == cc_key[0]:
            if len(cc_key) == 1:
                return rule  # 仅按主版本号匹配 (如 12.x → RTX 50)
            if len(cc_key) >= 2 and minor == cc_key[1]:
                return rule
    # 回退：按主版本号大致匹配
    if major >= 12:
        return GPU_ARCH_RULES[(12,)]
    elif major >= 8:
        return GPU_ARCH_RULES[(8, 9)]
    elif major >= 7:
        return GPU_ARCH_RULES[(7, 5)]
    return None


def detect_torch() -> Dict[str, Any]:
    """检测 PyTorch 信息."""
    code = """
import sys
try:
    import torch
    ver = torch.__version__
    cuda_avail = torch.cuda.is_available()
    mps_avail = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_avail else 'N/A'
    print(f"VERSION:{ver}")
    print(f"CUDA:{cuda_avail}")
    print(f"MPS:{mps_avail}")
    print(f"GPU_NAME:{gpu_name}")
except ImportError:
    print("VERSION:NOT_INSTALLED")
    print("CUDA:False")
    print("MPS:False")
    print("GPU_NAME:N/A")
"""
    ret, out, _ = run_cmd([sys.executable, "-c", code])
    result: Dict[str, Any] = {
        "installed": False,
        "version": None,
        "cuda_available": False,
        "mps_available": False,
        "gpu_name": "N/A",
    }
    if ret != 0:
        return result
    for line in out.splitlines():
        if line.startswith("VERSION:"):
            ver = line.split(":", 1)[1].strip()
            if ver != "NOT_INSTALLED":
                result["installed"] = True
                result["version"] = ver
        elif line.startswith("CUDA:"):
            result["cuda_available"] = line.split(":", 1)[1].strip() == "True"
        elif line.startswith("MPS:"):
            result["mps_available"] = line.split(":", 1)[1].strip() == "True"
        elif line.startswith("GPU_NAME:"):
            result["gpu_name"] = line.split(":", 1)[1].strip()
    return result


def check_ollama() -> Dict[str, Any]:
    """检测 Ollama 服务状态和已安装模型."""
    result: Dict[str, Any] = {
        "service_running": False,
        "models": [],
        "error": None,
    }
    ret, out, err = run_cmd(["ollama", "list"])
    if ret != 0:
        result["error"] = err or "Ollama 未安装或未在 PATH 中"
        return result
    result["service_running"] = True
    # 解析模型列表 (格式: NAME  ID  SIZE  MODIFIED)
    for line in out.splitlines()[1:]:  # 跳过表头
        parts = line.split()
        if parts:
            result["models"].append(parts[0])
    return result


def check_postgresql() -> Dict[str, Any]:
    """检测 PostgreSQL 连接可用性.

    通过 .env 中的 DATABASE_URL 或默认参数尝试连接。
    """
    result: Dict[str, Any] = {
        "available": False,
        "db_url_configured": False,
        "error": None,
    }
    # 检查 .env 中的 DATABASE_URL
    env_file = PROJECT_ROOT / ".env"
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if db_url:
        result["db_url_configured"] = True
    # 尝试用 asyncpg 连接
    try:
        import asyncio
        async def _try_connect():
            try:
                import asyncpg
                if db_url:
                    # 解析 URL 格式: postgresql+asyncpg://user:pass@host:port/db
                    import re as _re
                    m = _re.match(r"postgresql\+asyncpg://([^:]*):([^@]*)@([^:]+):(\d+)/(.+)", db_url)
                    if m:
                        conn = await asyncpg.connect(
                            user=m.group(1), password=m.group(2),
                            host=m.group(3), port=int(m.group(4)),
                            database=m.group(5), timeout=5
                        )
                        await conn.close()
                        return True, None
                # 尝试默认连接
                conn = await asyncpg.connect(
                    user="postgres", password="postgres",
                    host="127.0.0.1", port=5433,
                    database="scholarflow", timeout=5
                )
                await conn.close()
                return True, None
            except Exception as e:
                return False, str(e)
        ok, err_msg = asyncio.run(_try_connect())
        result["available"] = ok
        if err_msg:
            result["error"] = err_msg
    except ImportError:
        result["error"] = "asyncpg 未安装，无法检测 PostgreSQL 连接"
    except Exception as e:
        result["error"] = str(e)
    return result


def check_faiss_index() -> Dict[str, Any]:
    """检测 FAISS 向量索引文件."""
    result: Dict[str, Any] = {
        "exists": False,
        "size_mb": 0,
        "path": str(PROJECT_ROOT / "data" / "index" / "faiss.index"),
    }
    faiss_path = PROJECT_ROOT / "data" / "index" / "faiss.index"
    if faiss_path.exists():
        result["exists"] = True
        result["size_mb"] = round(faiss_path.stat().st_size / (1024 * 1024), 1)
    return result


def check_sentence_transformer() -> Dict[str, Any]:
    """检测 Sentence Transformer 模型是否可用."""
    result: Dict[str, Any] = {
        "installed": False,
        "model_loaded": False,
        "error": None,
    }
    try:
        import sentence_transformers
        result["installed"] = True
        # 尝试快速加载（不实际下载模型，只检查库可用性）
        result["model_loaded"] = True
    except ImportError:
        result["error"] = "sentence-transformers 未安装"
    except Exception as e:
        result["error"] = str(e)
    return result


def check_disk() -> Dict[str, Any]:
    """检测磁盘空间."""
    target = PROJECT_ROOT
    usage = shutil.disk_usage(target)
    return {
        "path": str(target),
        "total_gb": round(usage.total / (1024**3), 1),
        "used_gb": round(usage.used / (1024**3), 1),
        "free_gb": round(usage.free / (1024**3), 1),
    }


# ---------------------------------------------------------------------------
# 主检测逻辑
# ---------------------------------------------------------------------------

class CheckResult:
    """单项检测结果."""
    def __init__(self, category: str, item: str, expected: str, actual: str,
                 passed: bool, required: bool = True, fix: str = ""):
        self.category = category
        self.item = item
        self.expected = expected
        self.actual = actual
        self.passed = passed
        self.required = required  # True=强制, False=条件必需
        self.fix = fix


def run_all_checks() -> List[CheckResult]:
    """运行全部检测，返回结果列表."""
    results: List[CheckResult] = []

    # ---- Conda 环境（优先查找 scholarflow 是否存在）----
    conda_info = detect_conda()
    if conda_info["conda_available"]:
        # ★ 第一步：检查 scholarflow 环境是否存在于所有环境中
        if conda_info["scholarflow_exists"]:
            results.append(CheckResult(
                "Conda", f"'{DEFAULT_CONDA_ENV}' 环境",
                "已创建",
                f"已存在 ({conda_info.get('scholarflow_path', '')})",
                True,
                required=False
            ))
            # ★ 第二步：检查当前是否激活了 scholarflow
            if conda_info["is_scholarflow_env"]:
                results.append(CheckResult(
                    "Conda", "当前已激活",
                    DEFAULT_CONDA_ENV,
                    conda_info["env_name"] or "(未知)",
                    True,
                    required=False
                ))
            else:
                current = conda_info["env_name"] or "base"
                results.append(CheckResult(
                    "Conda", "当前已激活",
                    DEFAULT_CONDA_ENV,
                    current,
                    False,
                    required=False,
                    fix=f"请切换到 scholarflow 环境: conda activate {DEFAULT_CONDA_ENV}"
                ))
        else:
            # scholarflow 不存在
            results.append(CheckResult(
                "Conda", f"'{DEFAULT_CONDA_ENV}' 环境",
                "已创建",
                "不存在",
                False,
                required=False,
                fix=f"请创建 scholarflow 环境: conda create -n {DEFAULT_CONDA_ENV} python=3.11"
            ))
            if conda_info["in_conda_env"]:
                current = conda_info["env_name"] or "(未知)"
                results.append(CheckResult(
                    "Conda", "当前环境",
                    f"(待创建 {DEFAULT_CONDA_ENV})",
                    current,
                    True,
                    required=False
                ))

        # 列出其他环境供参考
        other_envs = [e for e in conda_info["all_envs"] if e != DEFAULT_CONDA_ENV]
        if other_envs:
            results.append(CheckResult(
                "Conda", "其他环境",
                "—",
                ", ".join(other_envs[:5]) + ("..." if len(other_envs) > 5 else ""),
                True,
                required=False
            ))
    else:
        results.append(CheckResult(
            "Conda", "Conda",
            "已安装",
            "未安装或不在 PATH",
            True,
            required=False,
            fix="建议安装 Miniconda/Anaconda 以管理 Python 环境"
        ))

    # ---- Python 版本 ----
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = PYTHON_MIN <= sys.version_info[:2] <= PYTHON_MAX
    results.append(CheckResult(
        "Python", "版本",
        f"{PYTHON_MIN[0]}.{PYTHON_MIN[1]} ~ {PYTHON_MAX[0]}.{PYTHON_MAX[1]}",
        py_ver,
        py_ok,
        fix="请安装 Python 3.10 ~ 3.12，不要使用 3.9 或 3.13+"
    ))

    # ---- pip 包依赖 ----
    required_pkgs = parse_requirements(REQUIREMENTS_PATH)
    installed_pkgs = parse_pip_list()

    def _make_fix(name: str, spec_str: str) -> str:
        """生成可执行的 pip install 修复命令."""
        if spec_str == "*" or not spec_str:
            return f"pip install {name}"
        if spec_str.startswith("=="):
            return f"pip install {name}{spec_str}"
        if any(op in spec_str for op in (">=", "<=", "!=", "~=", ",")):
            return f"pip install '{name}{spec_str}'"
        if spec_str[0].isdigit():
            return f"pip install {name}=={spec_str}"
        return f"pip install '{name}{spec_str}'"

    if not required_pkgs:
        results.append(CheckResult(
            "配置文件", "requirements.txt",
            f"存在于 {REQUIREMENTS_PATH}",
            "文件不存在或无法解析",
            False,
            fix=f"确认 {REQUIREMENTS_PATH} 存在且格式正确"
        ))
    else:
        # torch 由 PyTorch 专项检测处理，此处跳过
        _PYTORCH_SKIP = {"torch"}
        for pkg_name, spec in required_pkgs.items():
            pkg_key = pkg_name.lower().replace("_", "-")
            if pkg_key in _PYTORCH_SKIP:
                continue

            installed_ver = installed_pkgs.get(pkg_key, None)

            if installed_ver is None:
                results.append(CheckResult(
                    "pip", pkg_name,
                    spec if spec != "*" else "任意版本",
                    "未安装",
                    False,
                    fix=_make_fix(pkg_name, spec)
                ))
            elif not check_version_satisfied(installed_ver, spec):
                results.append(CheckResult(
                    "pip", pkg_name,
                    spec,
                    installed_ver,
                    False,
                    fix=_make_fix(pkg_name, spec)
                ))
            else:
                results.append(CheckResult(
                    "pip", pkg_name, spec, installed_ver, True
                ))

    # ---- PyTorch + GPU 匹配 ----
    # 优先用 pip list 判断安装状态，再用 detect_torch() 获取运行时信息
    torch_pip_ver = installed_pkgs.get("torch", None)
    torch_info = detect_torch()
    gpu_info = detect_gpu()
    is_mps = torch_info.get("mps_available", False)
    has_cuda = torch_info.get("cuda_available", False)
    device_type = "CUDA" if has_cuda else ("MPS" if is_mps else "CPU")

    # torch 安装状态（以 pip list 为准）
    if not torch_pip_ver:
        # 提前判断 GPU 以给出精确的安装指引
        _gpu = detect_gpu()
        _rule = get_gpu_arch_rule(_gpu["compute_capability"]) if _gpu and _gpu.get("compute_capability") else None
        _req_hint = _rule["req_file"] if _rule else "requirements/requirements-rtx40.txt"
        results.append(CheckResult(
            "PyTorch", "torch",
            "已安装",
            "未安装",
            False,
            fix=f"请根据 GPU 型号安装对应版本 PyTorch: pip install -r {_req_hint}"
        ))
    else:
        tv_clean = torch_pip_ver.split("+")[0]

        # GPU 架构匹配检查
        if gpu_info and gpu_info.get("compute_capability"):
            cc = gpu_info["compute_capability"]
            rule = get_gpu_arch_rule(cc)
            if rule:
                expected_min = rule["min_torch"]
                expected_tag = rule["cuda_tag"]
                label = rule["label"]

                torch_version_ok = version_tuple(tv_clean) >= version_tuple(expected_min)
                cuda_tag_ok = expected_tag in torch_pip_ver

                if not torch_version_ok:
                    _req = rule.get("req_file", "requirements/requirements-rtx40.txt")
                    results.append(CheckResult(
                        "PyTorch", "torch",
                        f"≥ {expected_min}+{expected_tag} ({label})",
                        torch_pip_ver,
                        False,
                        fix=f"GPU 为 {label}，需要 PyTorch ≥ {expected_min}+{expected_tag}。运行: pip install -r {_req}"
                    ))
                elif not cuda_tag_ok:
                    _req = rule.get("req_file", "requirements/requirements-rtx40.txt")
                    results.append(CheckResult(
                        "PyTorch", "torch",
                        f"{expected_tag} 标签 ({label})",
                        torch_pip_ver,
                        True,  # 仅警告，不阻塞
                        fix=f"当前 PyTorch CUDA 标签与 GPU ({label}) 不匹配，建议: pip install -r {_req}"
                    ))
                else:
                    results.append(CheckResult(
                        "PyTorch", "torch",
                        f"≥ {expected_min}+{expected_tag} ({label})",
                        torch_pip_ver,
                        True
                    ))
            else:
                results.append(CheckResult(
                    "PyTorch", "torch",
                    "已安装",
                    torch_pip_ver,
                    True
                ))
        else:
            # 无 NVIDIA GPU — 期望 CPU 或 MPS 版本
            results.append(CheckResult(
                "PyTorch", "torch",
                "≥ 2.6.0 (CPU/MPS)",
                torch_pip_ver,
                version_tuple(tv_clean) >= (2, 6, 0),
                fix="请安装 PyTorch ≥ 2.6.0 (CPU 版)"
            ))

        # CUDA / MPS 运行时可用性
        results.append(CheckResult(
            "PyTorch", "设备加速",
            "CUDA / MPS / CPU 任一可用",
            device_type,
            True  # CPU 也通过
        ))

    # GPU 名称
    if gpu_info:
        results.append(CheckResult(
            "硬件", "GPU",
            "NVIDIA GPU",
            f"{gpu_info['name']} (CC {gpu_info['cc_str']})",
            True
        ))
    else:
        results.append(CheckResult(
            "硬件", "GPU",
            "NVIDIA GPU (可选)",
            "无 NVIDIA GPU — 将使用 CPU/MPS",
            True,
            required=False
        ))

    # ---- Ollama 服务 ----
    ollama_info = check_ollama()
    if ollama_info["service_running"]:
        models_str = ", ".join(ollama_info["models"]) if ollama_info["models"] else "(无模型)"
        results.append(CheckResult(
            "Ollama", "服务状态",
            "运行中",
            "运行中",
            True
        ))
        results.append(CheckResult(
            "Ollama", "已安装模型",
            "至少 1 个 LLM 模型",
            models_str,
            len(ollama_info["models"]) > 0,
            fix="请至少 pull 一个模型: ollama pull qwen3:latest 或 ollama pull llama3:latest"
        ))
    else:
        results.append(CheckResult(
            "Ollama", "服务状态",
            "运行中",
            ollama_info.get("error", "未运行"),
            False,
            fix="请安装并启动 Ollama: https://ollama.com/download。启动后执行 ollama pull qwen3:latest"
        ))

    # ---- PostgreSQL ----
    pg_info = check_postgresql()
    results.append(CheckResult(
        "PostgreSQL", "数据库连接",
        "可连接",
        "可连接" if pg_info["available"] else f"不可连接: {pg_info.get('error', '未知错误')}",
        pg_info["available"],
        required=False,
        fix="请确保 PostgreSQL 已启动，DATABASE_URL 已在 .env 中配置。默认: postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/scholarflow"
    ))
    if not pg_info["db_url_configured"]:
        results.append(CheckResult(
            "PostgreSQL", ".env 配置",
            "DATABASE_URL 已设置",
            "未设置 DATABASE_URL",
            True,  # 仅提示
            required=False,
            fix="建议在 .env 中配置 DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:5432/scholarflow"
        ))

    # ---- FAISS 向量索引 ----
    faiss_info = check_faiss_index()
    results.append(CheckResult(
        "FAISS", "向量索引",
        "data/index/faiss.index 存在",
        f"{'存在' if faiss_info['exists'] else '缺失'} ({faiss_info['size_mb']}MB)",
        faiss_info["exists"],
        required=False,
        fix="运行 python scripts/06_build_index.py 构建 FAISS 索引"
    ))

    # ---- Sentence Transformer ----
    st_info = check_sentence_transformer()
    results.append(CheckResult(
        "嵌入模型", "Sentence Transformer",
        "sentence-transformers 已安装",
        "已安装" if st_info["installed"] else st_info.get("error", "未安装"),
        st_info["installed"],
        fix="pip install sentence-transformers==5.6.0"
    ))

    # ---- 磁盘空间 ----
    disk = check_disk()
    disk_ok = disk["free_gb"] >= DISK_MIN_GB
    results.append(CheckResult(
        "磁盘", "可用空间",
        f"≥ {DISK_MIN_GB}GB",
        f"{disk['free_gb']}GB (总计 {disk['total_gb']}GB)",
        disk_ok,
        fix=f"磁盘空间不足，请清理至少 {DISK_MIN_GB}GB 可用空间",
        required=False
    ))

    return results


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def render_markdown(results: List[CheckResult]) -> str:
    """渲染 Markdown 报告."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    passed_count = sum(1 for r in results if r.passed)
    failed_required = sum(1 for r in results if not r.passed and r.required)
    failed_optional = sum(1 for r in results if not r.passed and not r.required)
    total = len(results)

    if failed_required == 0 and failed_optional == 0:
        overall = "✅ 全部通过"
    elif failed_required == 0:
        overall = f"⚠️ {failed_optional} 项条件依赖未满足（不影响核心功能）"
    else:
        overall = f"❌ {failed_required} 项强制依赖失败"

    lines = [
        "## 环境依赖检测报告",
        "",
        f"**检测时间**: {now}",
        f"**操作系统**: {sys.platform}",
        f"**Python 路径**: {sys.executable}",
        f"**Conda 环境**: {os.environ.get('CONDA_DEFAULT_ENV', '无')}",
        f"**项目根目录**: {PROJECT_ROOT}",
        "",
        f"### 总体结果: {overall}",
        f"",
        f"| 类别 | 检测项 | 期望 | 实际 | 状态 |",
        f"|------|--------|------|------|:--:|",
    ]

    for r in results:
        status = "✅" if r.passed else ("⚠️" if not r.required else "❌")
        req_mark = "" if r.required else " (可选)"
        lines.append(
            f"| {r.category} | {r.item}{req_mark} | {r.expected} | {r.actual} | {status} |"
        )

    # 修复建议部分
    failed_items = [r for r in results if not r.passed]
    if failed_items:
        lines.append("")
        lines.append("### 修复建议")
        lines.append("")
        for r in failed_items:
            req_label = "**[强制]**" if r.required else "[可选]"
            lines.append(f"- {req_label} **{r.item}**: {r.fix}")

    # 下一步建议
    lines.append("")
    lines.append("### 下一步")
    lines.append("")
    if failed_required == 0 and failed_optional == 0:
        lines.append("> ✅ 环境完全就绪，可直接运行：")
        lines.append("> ```bash")
        lines.append("> python -m app.main")
        lines.append("> ```")
        lines.append("> 然后访问 http://127.0.0.1:8000 打开 ScholarFlow 工作台。")
    elif failed_required == 0:
        lines.append("> ⚠️ 核心依赖全部通过。条件依赖缺失仅影响特定功能：")
        lines.append("> - PostgreSQL 不可用将无法持久化文献数据")
        lines.append("> - FAISS 索引缺失将无法进行 RAG 检索")
        lines.append("> - Ollama 模型缺失将无法使用 AI 问答和综述生成")
    else:
        lines.append("> ❌ 请先按上述修复建议解决强制依赖失败项后再尝试运行。")

    return "\n".join(lines)


def render_json(results: List[CheckResult]) -> str:
    """渲染 JSON 报告."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    passed_required = all(r.passed for r in results if r.required)
    passed_all = all(r.passed for r in results)

    items = []
    for r in results:
        items.append({
            "category": r.category,
            "item": r.item,
            "expected": r.expected,
            "actual": r.actual,
            "passed": r.passed,
            "required": r.required,
            "fix": r.fix if not r.passed else "",
        })

    return json.dumps({
        "timestamp": now,
        "platform": sys.platform,
        "python": sys.executable,
        "project_root": str(PROJECT_ROOT),
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed_required": sum(1 for r in results if not r.passed and r.required),
            "failed_optional": sum(1 for r in results if not r.passed and not r.required),
            "overall": "PASS" if passed_all else ("WARN" if passed_required else "FAIL"),
        },
        "results": items,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ScholarFlow 环境依赖检测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    parser.add_argument("--quiet", action="store_true", help="仅输出失败项")
    parser.add_argument("--target-env", type=str, default=None, metavar="NAME",
                        help=f"指定要检测的 conda 环境名称（默认: 当前环境）。"
                             f"若指定且不同于当前环境，将通过 'conda run -n NAME' 重新执行本脚本。")
    parser.add_argument("--outfile", type=str, default=None, metavar="PATH",
                        help="将 JSON 结果写入指定文件（而非 stdout）。供 fix_env.py 调用使用。")
    args = parser.parse_args()

    # 如果指定了 --target-env 且不同于当前环境，通过 conda run 重新执行
    current_env = os.environ.get("CONDA_DEFAULT_ENV", "")
    if args.target_env and args.target_env != current_env:
        # 重建命令行参数（必须把 --outfile 也传过去，否则 GUI 读不到结果）
        passthru = ["--json"]
        if args.quiet:
            passthru.append("--quiet")

        # 始终使用临时文件传递结果，避免 conda run 的退出码和 stdout 干扰
        import tempfile as _tmp
        _outfile = args.outfile
        if not _outfile:
            _tmp_fd, _outfile = _tmp.mkstemp(suffix=".json", prefix="scholarflow_check_")
            os.close(_tmp_fd)
        passthru.extend(["--outfile", _outfile])

        script_path = Path(__file__).resolve()
        cmd = ["conda", "run", "-n", args.target_env, sys.executable, str(script_path)] + passthru
        ret, out, err = run_cmd(cmd, timeout=120)

        # conda run 可能返回非零即使脚本成功执行 — 以 outfile 是否写入为准
        outpath = Path(_outfile)
        if outpath.exists():
            result_text = outpath.read_text(encoding="utf-8")
            if result_text.strip():
                if not args.outfile:
                    # 用户没指定 outfile → 打印 JSON 到 stdout
                    print(result_text)
                    try:
                        os.unlink(_outfile)
                    except OSError:
                        pass
                sys.exit(0)
            else:
                if not args.outfile:
                    try:
                        os.unlink(_outfile)
                    except OSError:
                        pass

        # outfile 不存在或为空 → 真正失败
        print(f"[ERROR] 无法在 conda 环境 '{args.target_env}' 中运行检测:")
        print(err or out)
        sys.exit(2)

    results = run_all_checks()

    # 如果指定了 --outfile，写入文件
    if args.outfile:
        json_str = render_json(results)
        Path(args.outfile).write_text(json_str, encoding="utf-8")
        # 仍然输出简短摘要到 stdout
        failed_required = sum(1 for r in results if not r.passed and r.required)
        print(f"检测完成: {sum(1 for r in results if r.passed)}/{len(results)} 通过, "
              f"{failed_required} 项强制失败 → {args.outfile}")
        sys.exit(0 if failed_required == 0 else 1)

    if args.json:
        print(render_json(results))
    elif args.quiet:
        failed = [r for r in results if not r.passed]
        if failed:
            for r in failed:
                print(f"[{'FAIL' if r.required else 'WARN'}] {r.category}/{r.item}: {r.actual} (期望: {r.expected})")
                if r.fix:
                    print(f"  → {r.fix}")
        else:
            print("✅ All checks passed.")
    else:
        print(render_markdown(results))

    # 返回码
    failed_required = sum(1 for r in results if not r.passed and r.required)
    sys.exit(0 if failed_required == 0 else 1)


if __name__ == "__main__":
    main()
