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

# 레거시 .doc(.doc→.docx) 변환 지원 (opt-in, 기본 OFF).
# docx_loader가 soffice/libreoffice 바이너리로 .doc를 변환하므로, 이 의존성이
# 없으면 .doc 업로드는 항상 ValueError가 된다(rag.yaml #26 안내와 정합).
# 기본 OFF로 이미지를 경량(~300MB 절감) 유지하되, INSTALL_DOC_SUPPORT=true일 때만
# libreoffice-writer + fonts-noto-cjk(CJK 텍스트 렌더 범용)를 설치한다.
ARG INSTALL_DOC_SUPPORT=false
RUN if [ "$INSTALL_DOC_SUPPORT" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            libreoffice-writer \
            fonts-noto-cjk \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skipping .doc conversion deps. Set INSTALL_DOC_SUPPORT=true to enable libreoffice-writer."; \
    fi

# Set working directory
WORKDIR /app

# Install uv and dependencies (as root, WITHOUT Playwright browsers yet)
# extraction-quality(pymupdf)는 순수 파이썬·경량이라 기본 포함한다. PDF 품질게이트
# (mojibake 폴백)가 env opt-in으로 켜질 때 PyMuPDF 재추출 폴백이 실제로 동작하도록
# 보장한다(게이트가 꺼져 있으면 미사용이므로 무영향).
ARG INSTALL_LOCAL_EMBEDDING_DEPS=false
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir --upgrade pip uv && \
    if [ "$INSTALL_LOCAL_EMBEDDING_DEPS" = "true" ]; then \
        uv export --frozen --no-dev --no-emit-project --extra local-embedding --extra extraction-quality --format requirements.txt --no-hashes --output-file /tmp/requirements.txt; \
    else \
        uv export --frozen --no-dev --no-emit-project --extra extraction-quality --format requirements.txt --no-hashes --output-file /tmp/requirements.txt; \
    fi && \
    uv pip install --system --no-cache --requirement /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt

# Create runtime directories and non-root user
RUN mkdir -p logs uploads/temp && \
    useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app

ENV HF_HOME=/home/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/app/.cache/huggingface
ENV TORCHINDUCTOR_CACHE_DIR=/home/app/.cache/torchinductor

# Switch to non-root user before optional runtime cache downloads
USER app

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

# BGE 리랭커 모델(BAAI/bge-reranker-v2-m3) 빌드타임 사전 다운로드 (opt-in, 기본 OFF).
# 미설정 시 BGE 리랭커 활성 배포의 첫 리랭킹 요청에서 모델(~수백MB)을 런타임에
# 다운로드해 cold-start 지연 + 런타임 HF Hub 가용성 의존이 생긴다. true로 켜면
# 이미지에 모델을 사전 포함해 첫 요청 지연·네트워크 의존을 제거한다(에어갭/사내망 유용).
# 주의: transformers/torch가 필요하므로 INSTALL_LOCAL_EMBEDDING_DEPS=true와 함께 켤 것.
# 기본 OFF는 이미지 크기 증가를 피하기 위한 OneRAG 경량 정책이다.
ARG PRELOAD_BGE_RERANKER_MODEL=false
RUN if [ "$PRELOAD_BGE_RERANKER_MODEL" = "true" ]; then \
    python -c "from transformers import AutoModelForSequenceClassification, AutoTokenizer; \
        model_name = 'BAAI/bge-reranker-v2-m3'; \
        print(f'📥 BGE 리랭커 모델 다운로드 중 ({model_name})...'); \
        AutoTokenizer.from_pretrained(model_name); \
        AutoModelForSequenceClassification.from_pretrained(model_name); \
        print('✅ BGE 리랭커 모델 다운로드 완료!')"; \
    else \
        echo "Skipping BGE reranker model preload. Set PRELOAD_BGE_RERANKER_MODEL=true to enable."; \
    fi

# Install Playwright browsers as app user (in /home/app/.cache/ms-playwright/)
ARG INSTALL_PLAYWRIGHT_BROWSERS=false
RUN if [ "$INSTALL_PLAYWRIGHT_BROWSERS" = "true" ]; then \
    playwright install chromium; \
    else \
        echo "Skipping Playwright browser install. Set INSTALL_PLAYWRIGHT_BROWSERS=true to enable."; \
    fi

# Copy application source after dependency and optional cache layers.
# Source-only changes should not invalidate dependency downloads.
COPY --chown=app:app . .
RUN chmod +x /app/docker-entrypoint.sh

# Set environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

# Start application with entrypoint script
# 진입점 스크립트가 환경변수를 올바르게 확장하고 uvicorn 실행
ENTRYPOINT ["/app/docker-entrypoint.sh"]
