# OneRAG Architecture Diagrams

아래 다이어그램들을 README나 docs에 포함할 수 있습니다. GitHub에서 Mermaid를 자동으로 렌더링합니다.

---

## 1. 전체 시스템 아키텍처

```mermaid
flowchart TB
    subgraph Client["클라이언트"]
        API[REST API]
        WS[WebSocket]
        Stream[Streaming]
    end

    subgraph Core["OneRAG Core"]
        Router[Query Router]
        Expansion[Query Expansion]
        Retriever[Retriever]
        Cache[Cache Layer]
        Reranker[Reranker]
        Generator[Generator]
        PII[PII Masking]
    end

    subgraph VectorDB["Vector DB (택 1)"]
        Weaviate
        Chroma
        Pinecone
        Qdrant
        pgvector
        MongoDB
    end

    subgraph LLM["LLM Provider (택 1)"]
        Gemini[Google Gemini]
        OpenAI
        Claude[Anthropic Claude]
        OpenRouter
    end

    subgraph Features["Optional Features"]
        GraphRAG[GraphRAG]
        Agent[Agent Tools]
        Korean[한국어 NLP]
    end

    Client --> Router
    Router --> Expansion
    Expansion --> Retriever
    Retriever --> VectorDB
    Retriever --> Cache
    Cache --> Reranker
    Reranker --> Generator
    Generator --> LLM
    Generator --> PII
    PII --> Client

    Features -.-> Core

    style Core fill:#1f6feb,color:#fff
    style VectorDB fill:#238636,color:#fff
    style LLM fill:#8957e5,color:#fff
    style Features fill:#db61a2,color:#fff
```

---

## 2. RAG 파이프라인 상세

```mermaid
flowchart LR
    Q[Query] --> R[Router]
    R -->|분류| E[Expansion]
    E -->|동의어/불용어| S[Search]

    subgraph Search["검색 단계"]
        S --> V[Vector Search]
        S --> H[Hybrid Search]
        V --> M[Merge]
        H --> M
    end

    M --> C{Cache?}
    C -->|Hit| RES[Response]
    C -->|Miss| RR[Reranker]
    RR --> G[Generator]
    G --> P[PII Mask]
    P --> RES

    style Search fill:#238636,color:#fff
```

---

## 3. 컴포넌트 교체 가능 구조

```mermaid
graph TB
    subgraph Config["설정 파일"]
        ENV[".env"]
        YAML["YAML configs"]
    end

    subgraph Providers["교체 가능한 Provider"]
        VDB["Vector DB Provider"]
        LLMP["LLM Provider"]
        RRP["Reranker Provider"]
        CP["Cache Provider"]
    end

    subgraph Implementations["구현체"]
        VDB --> W[Weaviate]
        VDB --> CH[Chroma]
        VDB --> PI[Pinecone]
        VDB --> QD[Qdrant]

        LLMP --> GE[Gemini]
        LLMP --> OA[OpenAI]
        LLMP --> AN[Anthropic]

        RRP --> JI[Jina]
        RRP --> CO[Cohere]
        RRP --> GO[Google]

        CP --> ME[Memory]
        CP --> RE[Redis]
        CP --> SE[Semantic]
    end

    ENV -->|1줄 변경| VDB
    ENV -->|1줄 변경| LLMP
    YAML -->|2줄 변경| RRP
    YAML -->|1줄 변경| CP

    style Config fill:#d29922,color:#fff
    style Providers fill:#1f6feb,color:#fff
```

---

## 4. 단계별 확장 가이드

```mermaid
graph LR
    subgraph Basic["Basic"]
        B1[Vector Search]
        B2[LLM]
    end

    subgraph Standard["Standard (권장)"]
        S1[Hybrid Search]
        S2[Reranker]
        S3[Cache]
    end

    subgraph Advanced["Advanced"]
        A1[GraphRAG]
        A2[Agent]
        A3[PII Masking]
    end

    Basic -->|필요시 추가| Standard
    Standard -->|필요시 추가| Advanced

    style Basic fill:#238636,color:#fff
    style Standard fill:#1f6feb,color:#fff
    style Advanced fill:#8957e5,color:#fff
```

---

## 5. 한국어 처리 파이프라인 (Optional)

```mermaid
flowchart LR
    Q[한국어 쿼리] --> T[형태소 분석]
    T --> SY[동의어 확장]
    SY --> SW[불용어 제거]
    SW --> UD[사용자 사전]
    UD --> S[검색]

    style Q fill:#f778ba,color:#fff
```
