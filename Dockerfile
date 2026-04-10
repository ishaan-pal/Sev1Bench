ARG BASE_IMAGE=ghcr.io/meta-pytorch/openenv-base:latest
FROM ${BASE_IMAGE}

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/app/env/.venv
ENV PATH="${UV_PROJECT_ENVIRONMENT}/bin:$PATH"

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

COPY . /app/env
WORKDIR /app/env

RUN if ! command -v uv >/dev/null 2>&1; then \
        curl -LsSf https://astral.sh/uv/install.sh | sh && \
        mv /root/.local/bin/uv /usr/local/bin/uv && \
        mv /root/.local/bin/uvx /usr/local/bin/uvx; \
    fi

RUN python3 -m venv --copies "${UV_PROJECT_ENVIRONMENT}"

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --frozen --no-editable; \
    else \
        uv sync --no-editable; \
    fi

# Install LiteLLM proxy
RUN pip install 'litellm[proxy]'

ENV VIRTUAL_ENV="${UV_PROJECT_ENVIRONMENT}"
ENV PYTHONPATH="/app/env:$PYTHONPATH"
ENV ENABLE_WEB_INTERFACE=true

# LiteLLM proxy will run on 4000, main server on 8000
ENV API_BASE_URL=http://localhost:4000
ENV API_KEY=${HF_TOKEN}
ENV MODEL_NAME=huggingface/Qwen/Qwen2.5-72B-Instruct

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

COPY start.sh /app/env/start.sh
RUN chmod +x /app/env/start.sh

CMD ["/app/env/start.sh"]