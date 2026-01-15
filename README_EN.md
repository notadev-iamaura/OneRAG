# RAG_Standard (v1.0.7)

[한국어](README.md) | **English**

[![CI](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml/badge.svg)](https://github.com/youngouk/RAG_Standard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

A production-ready RAG (Retrieval-Augmented Generation) chatbot backend system. High-performance async web service built with FastAPI, featuring enterprise-grade security and cutting-edge GraphRAG technology.

## 🏆 Project Status (v1.0.7)

This project has achieved **production-grade quality**:

- **Test Coverage**: 1,295 unit/integration/failure scenario tests - 100% passing
- **Clean Codebase**: All deprecated functions removed, DI pattern complete, 80+ providers structured
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

## 🚀 Quickstart (3 Steps)

**First time?** Just follow 3 steps to experience the RAG system.

### Prerequisites

```bash
# Check required tools
docker --version          # Docker 20.10+
docker compose version    # Docker Compose v2+
uv --version || curl -LsSf https://astral.sh/uv/install.sh | sh  # UV package manager
```

### Step 1: Clone & Install

```bash
git clone https://github.com/youngouk/RAG_Standard.git
cd RAG_Standard
uv sync
```

### Step 2: Configure

```bash
# Copy quickstart environment file
cp quickstart/.env.quickstart .env

# Edit .env and set just ONE API key
# GOOGLE_API_KEY=your-key  (Free: https://aistudio.google.com/apikey)
```

### Step 3: Run

```bash
make quickstart
```

Done! 🎉 Test the API at http://localhost:8000/docs

```bash
# Stop
make quickstart-down
```

---

## 📖 Detailed Setup Guide

For more granular configuration, see [docs/SETUP.md](docs/SETUP.md).

### Development Environment (Local)

```bash
# 1. Run only Weaviate with Docker
docker compose -f docker-compose.weaviate.yml up -d

# 2. Configure detailed environment
cp .env.example .env
# Edit .env (API keys, auth keys, etc.)

# 3. Run dev server (with hot reload)
make dev-reload
```

### Run Tests

```bash
# Run 1,295 tests
make test
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
