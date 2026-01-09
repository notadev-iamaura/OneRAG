# 데이터 적재 가이드 (Data Ingestion) - v1.0.0

Blank RAG 시스템은 범용 데이터 커넥터 아키텍처를 통해 다양한 소스의 데이터를 표준 지식으로 변환합니다.

---

## 1. 지원되는 데이터 소스

### 1.1 Notion 데이터베이스 (현재 지원)
Notion API를 통해 페이지와 속성 정보를 실시간으로 가져옵니다.
- **URL**: `POST /api/ingest/notion`
- **핵심 파라미터**: `database_id`, `category_name`
- **특징**: 문서 본문(Content)은 벡터 DB로, 속성(Properties)은 메타데이터 DB로 이중 저장됩니다.

### 1.2 범용 웹 및 사이트맵 (준비 중)
사이트맵(`sitemap.xml`)을 분석하여 공식 페이지를 자동 수집합니다.
- **주요 기능**: 보일러플레이트(메뉴, 푸터) 제거, 변경된 페이지만 자동 갱신.

### 1.3 로컬 폴더 및 S3 (준비 중)
파일 저장소를 실시간 모니터링하여 PDF, DOCX, XLSX 등을 즉시 인덱싱합니다.

---

## 2. 표준 데이터 규격 (`StandardDocument`)

어떤 소스에서 오든 시스템 내부에서는 다음 규격을 준수합니다:
- `content`: 정제된 순수 텍스트.
- `metadata`: 제목, 카테고리, 원본 URL 등 (JSON).
- `raw_hash`: 내용 변경 감지용 (중복 적재 방지).

---

## 3. 적재 파이프라인 흐름

1.  **Extract**: 커넥터 인터페이스(`IIngestionConnector`)를 통한 원본 데이터 획득.
2.  **Transform**: `MetadataChunker`를 사용한 전략적 텍스트 분할.
3.  **Load**:
    - **Vector Store**: 고차원 벡터 임베딩 저장 (Weaviate).
    - **Graph Store**: 엔티티 관계 추출 및 연결 (NetworkX/Neo4j).
    - **Metadata Store**: 구조화된 검색을 위한 RDB 저장 (PostgreSQL).

---

## 4. 실행 및 모니터링

```bash
# Notion 적재 예시
curl -X POST "http://localhost:8000/api/ingest/notion" \
     -H "X-API-Key: <your_key>" \
     -H "Content-Type: application/json" \
     -d '{
           "database_id": "your_db_id",
           "category_name": "manual"
         }'
```

- **로그**: `[app.modules.ingestion]` 태그를 통해 진행 상황 확인 가능.
- **비동기**: 대량 작업은 `BackgroundTasks`를 통해 수행되므로 시스템 지연이 없습니다.
