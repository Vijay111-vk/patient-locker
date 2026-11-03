#!/bin/sh
# Container entrypoint: optionally load sample data (idempotent), then serve.
set -e
if [ "${SEED_ON_START:-false}" = "true" ]; then
  python -m scripts.seed --data "${SEED_DATA_DIR:-sample_data}"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
