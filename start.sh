#!/bin/bash
set -e

echo "[start.sh] Starting LiteLLM proxy on port 4000..."
HUGGINGFACE_API_KEY="${HF_TOKEN}" litellm \
  --model huggingface/Qwen/Qwen2.5-72B-Instruct \
  --port 4000 &

# Wait until LiteLLM proxy is ready
echo "[start.sh] Waiting for LiteLLM proxy to be ready..."
for i in $(seq 1 20); do
  if curl -sf http://localhost:4000/health > /dev/null 2>&1; then
    echo "[start.sh] LiteLLM proxy is up."
    break
  fi
  echo "[start.sh] Attempt $i/20 — proxy not ready yet, retrying in 2s..."
  sleep 2
done

echo "[start.sh] Starting main server on port 8000..."
exec python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
