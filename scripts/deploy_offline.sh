#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

docker info > /dev/null
docker compose version
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo 'Created .env from the template. Configure your LLM provider/API key, then run bash deploy.sh again.'
    exit 1
fi

echo 'Loading application and PostgreSQL images...'
docker load --input images.tar
echo 'Starting ScholarFlow with local images and persistent model files...'
docker compose up -d --pull never
docker compose ps -a
echo 'ScholarFlow: http://127.0.0.1:8000 on this machine.'
echo 'Application logs: docker compose logs -f app'
