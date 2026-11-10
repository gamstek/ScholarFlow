"""Prepare and validate the persistent BGE-M3 model before starting the API."""

from __future__ import annotations

import json
import os
from pathlib import Path


MODEL_REPO = "BAAI/bge-m3"
REQUIRED_FILES = (
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "1_Pooling/config.json",
)
WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
READY_FILE = ".scholarflow-model-ready.json"


def _file_signature(model_dir: Path) -> dict[str, dict[str, int]]:
    """Require complete assets, including at least one supported weight file."""
    weights = [name for name in WEIGHT_FILES if (model_dir / name).is_file()]
    if not weights:
        raise FileNotFoundError("BGE-M3 model weights are missing")
    signature = {}
    for name in (*REQUIRED_FILES, *weights):
        stat = (model_dir / name).stat()
        if stat.st_size == 0:
            raise ValueError(f"Empty model file: {name}")
        signature[name] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return signature


def _is_ready(model_dir: Path) -> bool:
    try:
        ready = json.loads((model_dir / READY_FILE).read_text(encoding="utf-8"))
        return ready.get("repo_id") == MODEL_REPO and ready.get("files") == _file_signature(model_dir)
    except (OSError, ValueError, AttributeError):
        return False


def _validate_model(model_dir: Path) -> None:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(str(model_dir), device="cpu", local_files_only=True)
    if model.get_sentence_embedding_dimension() != 1024:
        raise ValueError("Expected a 1024-dimensional BGE-M3 model")


def _mark_ready(model_dir: Path) -> None:
    ready = {"repo_id": MODEL_REPO, "files": _file_signature(model_dir)}
    # A failed or interrupted validation must never leave a successful marker.
    temporary = model_dir / (READY_FILE + ".tmp")
    temporary.write_text(json.dumps(ready, indent=2), encoding="utf-8")
    temporary.replace(model_dir / READY_FILE)


def _download_model(model_dir: Path, *, force_download: bool) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=MODEL_REPO,
        local_dir=str(model_dir),
        endpoint=os.getenv("HF_ENDPOINT", "https://huggingface.co"),
        allow_patterns=[*REQUIRED_FILES, *WEIGHT_FILES],
        force_download=force_download,
        max_workers=4,
    )


def prepare_model(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    if _is_ready(model_dir):
        print(f"[Model init] BGE-M3 ready at {model_dir}; reusing local files (no download).", flush=True)
        return
    (model_dir / READY_FILE).unlink(missing_ok=True)

    # The API stays offline; only this initializer is allowed to download.
    # Set this before importing HF libraries, which cache their environment.
    os.environ["HF_HUB_OFFLINE"] = "0"
    force_download = False
    try:
        _file_signature(model_dir)
    except (OSError, ValueError):
        print("[Model init] BGE-M3 is missing or incomplete; downloading/resuming required files.", flush=True)
    else:
        try:
            _validate_model(model_dir)
        except Exception as exc:
            print(f"[Model init] Local model validation failed: {exc}. Downloading a fresh copy.", flush=True)
            force_download = True
        else:
            _mark_ready(model_dir)
            print(f"[Model init] Existing BGE-M3 validated at {model_dir}; no download needed.", flush=True)
            return

    _download_model(model_dir, force_download=force_download)
    _file_signature(model_dir)
    print("[Model init] Download finished; validating model load on CPU.", flush=True)
    _validate_model(model_dir)
    _mark_ready(model_dir)
    print(f"[Model init] BGE-M3 ready at {model_dir}.", flush=True)


def main() -> int:
    model_dir = Path(os.getenv("BGE_MODEL_PATH", "/app/embedding/bge-m3"))
    try:
        prepare_model(model_dir)
    except Exception as exc:
        print(
            f"[Model init] FAILED: {exc}\n"
            "The API will not start until model preparation succeeds. "
            "Check download connectivity/HF_ENDPOINT and directory permissions, "
            "then run docker compose up -d again to retry.",
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
