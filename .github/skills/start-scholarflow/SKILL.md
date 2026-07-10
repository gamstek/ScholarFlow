---
name: start-scholarflow
description: "Use when: user says start/launch/run/open ScholarFlow, 启动/打开/运行项目, startup fails, 启动失败, service won't start, 服务起不来, or needs environment diagnosis. Auto-detects Docker, Ollama/cloud API, BGE-M3, Python env from .env with mismatch prompts for all known failure modes."
---

# ScholarFlow 项目启动

**核心原则**：所有环境相关值**从 `.env` 读取**，不硬编码。检测到不匹配时**提示用户修改 `.env`**。

---

## 执行流程

每一步模式：**读 .env → 自动检测 → 对比 → 不匹配则提示修 .env**

### 1. 加载并校验 `.env`

```powershell
Test-Path .env
```

不存在 → 按底部「.env 最小模板」创建，提示用户填写。

存在 → 校验必填变量：

| 变量 | 规则 |
|:---|:---|
| `DATABASE_URL` | 必须含 `@127.0.0.1` 而非 `localhost`（WSL2 IPv6 超时） |
| `LLM_BACKEND` | 必须为 `ollama` / `deepseek` / `openai` / `qwen` |
| `HF_HUB_OFFLINE` | 必须为 `1` |
| `BGE_MODEL_PATH` | 必须存在 |

校验失败 → **输出具体修复建议**，停止，等用户修改。

### 2. LLM 后端就绪检查

读 `.env` 的 `LLM_BACKEND`，按分支处理：

**分支 A：`ollama`（本地）**
```powershell
curl -s $env:OLLAMA_BASE_URL/api/tags
```
- 未运行 → `ollama serve`
- 缺模型 → `ollama pull $env:OLLAMA_MODEL`

**分支 B：`deepseek|openai|qwen`（云端）**
- `CLOUD_API_KEY` 为空或为占位值 `sk-your-key-here` → **提示填写真实 Key**
- `CLOUD_API_BASE` 为空 → **提示填写平台地址**
- `CLOUD_MODEL` 为空 → **提示填写模型名**（如 `deepseek-chat`、`gpt-4o-mini`）
- 验证命令：
```powershell
python -c "
import os, httpx; from dotenv import load_dotenv; load_dotenv()
r = httpx.post(os.getenv('CLOUD_API_BASE')+'/chat/completions',
    headers={'Authorization': f'Bearer {os.getenv(\"CLOUD_API_KEY\")}'},
    json={'model': os.getenv('CLOUD_MODEL'), 'messages': [{'role':'user','content':'hi'}], 'max_tokens':1},
    timeout=10)
print('Cloud API:', 'OK' if r.status_code==200 else f'FAIL({r.status_code})')
"
```

### 3. 数据库就绪检查

从 `DATABASE_URL` 解析 host:port → 定位 Docker 容器：

```powershell
python -c "
import os, re
url = os.getenv('DATABASE_URL')
m = re.match(r'.+://(.+):(.+)@(.+):(\d+)/(.+)', url)
user, pwd, host, port, db = m.groups()
print(f'{host}:{port} user={user} db={db}')
"
```

按解析出的 `port` 找容器：
```powershell
docker ps -a --filter "publish=$port" --format "{{.Names}} {{.Status}}"
```

| 检测结果 | 操作 |
|:---|:---|
| 无容器 | 用 `.env` 中的参数拼 `docker run` 命令 |
| 已停止 | `docker start <容器名>` |
| 运行但 TCP 不通 | `docker restart <容器名>`，等 5s |
| 端口不匹配 | **提示修改 `.env` 端口号** |

### 4. BGE-M3 缓存检查

```powershell
python -c "
import os; from huggingface_hub import try_to_load_from_cache
model = os.getenv('BGE_MODEL_PATH', 'BAAI/bge-m3')
cached = try_to_load_from_cache(model, 'config.json')
print('Cached:', cached if cached else 'NOT FOUND')
"
```

缓存缺失 → **提示临时注释 `HF_HUB_OFFLINE=1`**，运行下载命令，完成后恢复。

### 5. Python 环境检查

```powershell
conda env list | findstr scholarflow
python -c "
import torch, transformers
print(f'torch={torch.__version__} transformers={transformers.__version__}')
if torch.__version__<'2.6' and transformers.__version__>='5.0':
    print('CONFLICT: run: pip install transformers==4.48.3')
"
```

### 6. 启动

```powershell
python -m app.main
```

---

## `.env` 不匹配提示模板

```
⚠ .env 与当前环境不匹配：

  问题 1：DATABASE_URL 端口 5432，但 Docker 容器实际监听 5433
  → 修改 .env 第 X 行端口号

  问题 2：LLM_BACKEND=deepseek 但 CLOUD_API_KEY 仍为占位值
  → 修改 .env 第 Y 行，填入真实 API Key

请修改后重新启动。
```

---

## `.env` 最小模板（不存在时创建）

```bash
DATABASE_URL=postgresql+asyncpg://postgres:scholarflow@127.0.0.1:5432/scholarflow
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://localhost:11434
CLOUD_API_KEY=sk-your-key-here
CLOUD_API_BASE=
CLOUD_MODEL=
BGE_MODEL_PATH=BAAI/bge-m3
HF_HUB_OFFLINE=1
```

---

## 故障速查

| 报错关键字 | 根因 | 解决 |
|:---|:---|:---|
| `ConnectionRefusedError` | PG 容器未启动或端口不匹配 | 回步骤 3 |
| `init_db` 耗时 >10s | `DATABASE_URL` 用了 `localhost` | 改为 `127.0.0.1` |
| `ImportError: AgentExecutor` | langchain 版本过新 | 已修复 |
| `ValueError: upgrade torch to at least v2.6` | torch/transformers 冲突 | `pip install transformers==4.48.3` |
| 模型加载超时 / HF HEAD | `HF_HUB_OFFLINE` 或 `local_files_only` 缺失 | 检查 `.env` 和 `embedder.py` |
| 云端 API 401/403 | API Key 无效 | 修改 `CLOUD_API_KEY` |
| 前端"后端未连接" | 浏览器早于服务就绪 | 等重试或 `F5` 刷新 |

---

## 新机器首次部署

```powershell
# 1. 按模板创建 .env，填写实际配置
# 2. Python 环境
conda create -n scholarflow python=3.11 -y && conda activate scholarflow
pip install -r requirements.txt
pip install transformers==4.48.3
# 3. LLM: ollama pull 模型 或填写 CLOUD_API_KEY
# 4. 下载 BGE-M3（仅首次，临时关 HF_HUB_OFFLINE）
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
# 5. 启动
python -m app.main
```
