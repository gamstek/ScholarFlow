# Embedding 模型目录

将嵌入模型放在此目录下，ScholarFlow 会自动从本地加载，无需联网。

## 目录结构

```
embedding/
├── README.md
└── bge-m3/                  # BGE-M3 模型文件
    ├── config.json
    ├── pytorch_model.bin     # ~2.2 GB（核心权重）
    ├── sentencepiece.bpe.model
    ├── tokenizer.json
    ├── tokenizer_config.json
    ├── special_tokens_map.json
    ├── sentence_bert_config.json
    ├── modules.json
    └── 1_Pooling/
        └── config.json
```

## 手动下载 BGE-M3

### 方法一：Python 脚本（推荐，最稳定）

```powershell
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', local_dir='embedding/bge-m3', ignore_patterns=['*.onnx*', 'onnx/**', 'imgs/**', '*.jpg', '*.png', '*.webp', '*.pt', '*.md', '.gitattributes'])"
```

国内镜像加速（在命令末尾加 `endpoint` 参数）：

```powershell
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', local_dir='embedding/bge-m3', ignore_patterns=['*.onnx*', 'onnx/**', 'imgs/**', '*.jpg', '*.png', '*.webp', '*.pt', '*.md', '.gitattributes'], endpoint='https://hf-mirror.com')"
```

### 方法二：hf 命令

```powershell
hf download BAAI/bge-m3 --local-dir embedding/bge-m3
```

> 注意：如果 `hf` 命令找不到，尝试完整路径 `C:\Users\<用户名>\.conda\envs\scholarflow\Scripts\hf.exe`

### 方法三：Git LFS

```powershell
git lfs install
git clone https://huggingface.co/BAAI/bge-m3 embedding/bge-m3
```

## 加载优先级

ScholarFlow 按以下优先级查找模型：

1. `.env` 中 `BGE_MODEL_PATH` 指向的有效本地路径
2. `embedding/bge-m3/`（本目录下的默认路径）
3. `BAAI/bge-m3`（HuggingFace Hub 自动下载）

## 添加其他模型

在此目录下新建子文件夹放入模型文件，然后在 `.env` 中设置 `BGE_MODEL_PATH=embedding/你的模型文件夹` 即可。
