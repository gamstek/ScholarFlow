# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
ARG NPM_REGISTRY=https://registry.npmjs.org
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry="${NPM_REGISTRY}" --replace-registry-host=always --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM condaforge/miniforge3:latest AS runtime
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG CONDA_CHANNEL=https://conda.anaconda.org/conda-forge
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_WHEEL_URL=https://download.pytorch.org/whl/cpu/torch/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    HF_HUB_OFFLINE=1 \
    BGE_MODEL_PATH=/app/embedding/bge-m3 \
    PATH=/opt/conda/envs/scholarflow/bin:$PATH

WORKDIR /app
COPY requirements/requirements-docker.txt /tmp/requirements-docker.txt
RUN conda create --name scholarflow python=3.11 pip libgomp --override-channels --channel "${CONDA_CHANNEL}" --yes \
    && source /opt/conda/etc/profile.d/conda.sh \
    && conda activate scholarflow \
    && PIP_CONFIG_FILE=/dev/null python -m pip install --no-cache-dir \
        --index-url "${PIP_INDEX_URL}" --find-links "${TORCH_WHEEL_URL}" \
        --requirement /tmp/requirements-docker.txt \
    && python -m pip check \
    && python -c "import torch, fastapi, sentence_transformers, faiss, dotenv; print('Runtime imports OK:', torch.__version__)" \
    && conda clean --all --yes \
    && rm /tmp/requirements-docker.txt

COPY app/ ./app/
COPY --from=frontend /build/frontend/dist/ ./frontend/dist/
RUN mkdir -p /app/data /app/embedding

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8)" || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
