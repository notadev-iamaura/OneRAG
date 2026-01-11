# RAG_Standard (v1.0.7 - Zero Technical Debt)

[한국어](README.md) | **English**

[![CI](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml/badge.svg)](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

A production-ready RAG (Retrieval-Augmented Generation) chatbot backend system. High-performance async web service built with FastAPI, featuring enterprise-grade security and cutting-edge GraphRAG technology.

## 🏆 Project Status: Zero Technical Debt

This project has achieved **production-grade quality** with zero technical debt:

- **Test Coverage**: 1,295 unit/integration/failure scenario tests - 100% passing
- **Zero Tech Debt**: All deprecated functions removed, DI pattern complete, 80+ providers structured
- **Static Analysis**: Full compliance with `Ruff` (Lint) and `Mypy` (Strict Type Check)
- **Security**: Unified PII masking system with API Key authentication on all admin endpoints
- **Multi Vector DB**: 6 vector databases supported (Weaviate, Chroma, Pinecone, Qdrant, pgvector, MongoDB)

## 🚀 Key Features

### 🧠 Intelligent Search & Reasoning (Hybrid GraphRAG)
- **Vector + Graph**: Combines Weaviate's vector search with knowledge graph relationship reasoning
- **Fuzzy Entity Matching**: Vector search on knowledge graph entities handles typos, abbreviations, and semantic synonyms
- **ColBERT Reranking**: Token-level precision reranking with Jina ColBERT v2

### 🛡️ Enterprise Security & Reliability
- **Unified PII Processor**: Consolidated security logic with AI-powered review system
- **Defense-in-Depth**: Dual authentication at middleware and router levels
- **Circuit Breaker**: Prevents cascading failures from external LLM/DB outages

### ⚙️ Flexible Operations & Scalability
- **YAML Dynamic Config**: Runtime modification of service keywords and routing rules
- **Clean Architecture**: DI pattern with `dependency-injector` for vendor-agnostic flexibility
- **Multi-LLM Support**: Google Gemini, OpenAI GPT, Anthropic Claude, OpenRouter with automatic fallback

## 🏃 Quick Start (5 minutes)

### Prerequisites

```bash
# Python 3.11+
python --version  # Requires Python 3.11.x or higher

# Docker & Docker Compose
docker --version          # Docker 20.10+
docker compose version    # Docker Compose v2+

# UV package manager
uv --version || pip install uv
```

### Step 1: Clone & Install (2 min)

```bash
git clone https://github.com/youngouk/RAG_Standard.git
cd RAG_Standard

# Install all dependencies (including spaCy Korean model)
uv sync
```

### Step 2: Environment Setup (1 min)

```bash
cp .env.example .env
```

Edit `.env` with **minimum 2 settings**:

```bash
# Required 1: API authentication key (any string, 32+ chars)
FASTAPI_AUTH_KEY=your_secure_random_key_here_at_least_32_chars

# Required 2: LLM API key (choose one)
GOOGLE_API_KEY=AIza...    # Recommended - free tier: https://makersuite.google.com/app/apikey
# or OPENAI_API_KEY=sk-...
# or ANTHROPIC_API_KEY=sk-ant-...
```

### Step 3: Start Infrastructure (1 min)

```bash
# Start Weaviate vector database
docker compose -f docker-compose.weaviate.yml up -d

# Verify (wait ~30s for healthy status)
docker compose -f docker-compose.weaviate.yml ps
```

### Step 4: Run Server

```bash
make dev-reload
```

### Step 5: Verify

| Endpoint | URL | Description |
|----------|-----|-------------|
| **API Docs** | http://localhost:8000/docs | Swagger UI - test all APIs |
| **Health** | http://localhost:8000/health | Server status |

### Run Tests (Optional)

```bash
ENVIRONMENT=test make test
```

## 📂 Project Structure

```
app/
├── api/           # REST API & auth layer
├── modules/core/  # RAG core (Graph, Retrieval, Privacy, Generation)
├── core/          # Interfaces & DI container
└── config/        # Environment-specific configs
```

## 🔧 Supported Vector Databases

| Provider | Hybrid Search | Best For |
|----------|---------------|----------|
| **Weaviate** (default) | ✅ Dense + BM25 | Self-hosted, hybrid built-in |
| **Chroma** | ❌ Dense only | Lightweight, local dev |
| **Pinecone** | ✅ Dense + Sparse | Serverless cloud |
| **Qdrant** | ✅ Dense + Full-Text | High-performance self-hosted |
| **pgvector** | ❌ Dense only | PostgreSQL extension |
| **MongoDB Atlas** | ❌ Dense only | Atlas Vector Search |

## 📜 License

MIT License - see [LICENSE](LICENSE) for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
