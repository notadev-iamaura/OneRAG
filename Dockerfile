# Python FastAPI build
FROM python:3.11-slim

# Install system dependencies (including Playwright requirements)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    python3-dev \
    # Playwright/Chromium dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy all files
COPY . .

# Install uv and dependencies (as root, WITHOUT Playwright browsers yet)
ARG INSTALL_LOCAL_EMBEDDING_DEPS=false
RUN pip install --no-cache-dir --upgrade pip uv && \
    if [ "$INSTALL_LOCAL_EMBEDDING_DEPS" = "true" ]; then \
        uv export --frozen --no-dev --extra local-embedding --format requirements.txt --no-hashes --output-file /tmp/requirements.txt; \
    else \
        uv export --frozen --no-dev --format requirements.txt --no-hashes --output-file /tmp/requirements.txt; \
    fi && \
    uv pip install --system --no-cache --requirement /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt

# Create directories
RUN mkdir -p logs uploads/temp

# Create non-root user for running the application
RUN useradd --create-home --shell /bin/bash app

# Copy entrypoint script (as root for proper permissions)
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

# Set proper file permissions and ownership (after all installations)
RUN chown -R app:app /app && \
    chmod +x /app/docker-entrypoint.sh

# Switch to non-root user
USER app

ENV HF_HOME=/home/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/app/.cache/huggingface
ENV TORCHINDUCTOR_CACHE_DIR=/home/app/.cache/torchinductor

# 로컬 임베딩 모델 사전 다운로드 (Qwen3-Embedding-0.6B)
# app 사용자로 다운로드하여 런타임에 캐시 접근 가능
# 약 1.2GB, HuggingFace Hub에서 다운로드
ARG PRELOAD_LOCAL_EMBEDDING_MODEL=false
RUN if [ "$PRELOAD_LOCAL_EMBEDDING_MODEL" = "true" ]; then \
    python -c "from sentence_transformers import SentenceTransformer; \
        print('📥 로컬 임베딩 모델 다운로드 중 (Qwen3-Embedding-0.6B)...'); \
        model = SentenceTransformer('Qwen/Qwen3-Embedding-0.6B', trust_remote_code=True); \
        print('✅ 임베딩 모델 다운로드 완료!')"; \
    else \
        echo "Skipping local embedding model preload. Set PRELOAD_LOCAL_EMBEDDING_MODEL=true to enable."; \
    fi

# Install Playwright browsers as app user (in /home/app/.cache/ms-playwright/)
ARG INSTALL_PLAYWRIGHT_BROWSERS=false
RUN if [ "$INSTALL_PLAYWRIGHT_BROWSERS" = "true" ]; then \
    playwright install chromium; \
    else \
        echo "Skipping Playwright browser install. Set INSTALL_PLAYWRIGHT_BROWSERS=true to enable."; \
    fi

# Set environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

# Start application with entrypoint script
# 진입점 스크립트가 환경변수를 올바르게 확장하고 uvicorn 실행
ENTRYPOINT ["/app/docker-entrypoint.sh"]
