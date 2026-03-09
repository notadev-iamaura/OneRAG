# Documents Module - 문서 처리 시스템

MVP Phase 문서 유형별 처리 전략을 제공하는 모듈입니다.

## 📁 디렉토리 구조

```
documents/
├── __init__.py                  # 모듈 진입점
├── base.py                      # BaseDocumentProcessor (추상 베이스)
├── factory.py                   # DocumentProcessorFactory (팩토리 패턴)
├── document_processing.py       # 기존 DocumentProcessor (Low-level)
│
├── models/                      # 데이터 모델
│   ├── document.py              # Document 클래스
│   └── chunk.py                 # Chunk 클래스
│
├── chunking/                    # 청킹 전략 (Strategy 패턴)
│   ├── base.py                  # BaseChunker
│   └── simple_chunker.py        # SimpleChunker (FAQ용)
│
├── metadata/                    # 메타데이터 추출 (Strategy 패턴)
│   ├── base.py                  # BaseMetadataExtractor
│   └── rule_based.py            # RuleBasedExtractor (규칙 기반)
│
├── processors/                  # 문서 유형별 프로세서
│   └── faq_processor.py         # FAQProcessor (MVP)
│
└── loaders/                     # 파일 로더 (기존)
    ├── base.py
    ├── factory.py
    └── ... (다양한 로더)
```

## 🚀 빠른 시작

### 1. FAQ 문서 처리 (MVP)

```python
from app.modules.core.documents import DocumentProcessorFactory

# 1. 팩토리로 프로세서 생성
processor = DocumentProcessorFactory.create('faq')

# 2. FAQ 파일 처리
chunks = processor.process('data/FAQ.xlsx')

# 3. 결과 확인
print(f"생성된 청크 수: {len(chunks)}")
for chunk in chunks[:3]:
    print(f"- {chunk.metadata.get('section')}: {chunk.content[:50]}...")
```

**출력 예시**:
```
생성된 청크 수: 175
- 서비스안내: 질문: 이용 시간은 어떻게 되나요? 답변: 평일 09:00~18:00입니다...
- 요금안내: 질문: 이용 요금은 얼마인가요? 답변: 1시간 기준 10,000원입니다...
- 위치안내: 질문: 주차 가능한가요? 답변: 네, 무료 주차 지원합니다...
```

### 2. 커스텀 템플릿 사용

```python
processor = DocumentProcessorFactory.create(
    'faq',
    content_template='Q: {question}\nA: {answer}'
)

chunks = processor.process('data/FAQ.xlsx')
```

### 3. 개별 컴포넌트 사용

```python
from app.modules.core.documents import (
    Document,
    Chunk,
    SimpleChunker,
    RuleBasedExtractor,
    FAQProcessor
)

# 커스텀 전략 조합
chunker = SimpleChunker(content_template='질문: {question}\n답변: {answer}')
extractor = RuleBasedExtractor(use_konlpy=True)

# 프로세서 생성
processor = FAQProcessor(
    chunker=chunker,
    metadata_extractor=extractor
)

# 처리
chunks = processor.process('data/FAQ.xlsx')
```

## 📊 데이터 모델

### Document

원본 문서를 표현하는 데이터 모델:

```python
from app.modules.core.documents import Document

doc = Document(
    source='data/faq.xlsx',
    doc_type='FAQ',
    data=[{'질문': '...', '답변': '...'}],
    metadata={'category': 'general'}
)

print(doc.total_items)      # 175
print(doc.is_structured)    # True
```

### Chunk

분할된 문서 조각을 표현하는 데이터 모델:

```python
from app.modules.core.documents import Chunk

chunk = Chunk(
    content='질문: ... 답변: ...',
    metadata={'section': '서비스'},
    chunk_index=0
)

print(chunk.char_count)     # 문자 수
print(chunk.word_count)     # 단어 수
print(chunk.has_embedding)  # False

# 임베딩 설정
chunk.set_embedding([0.1, 0.2, ...])
```

## 🔧 청킹 전략

### SimpleChunker (MVP)

1:1 매핑 청킹 - FAQ에 최적화:

```python
from app.modules.core.documents.chunking import SimpleChunker

chunker = SimpleChunker(
    content_template='{question}\n{answer}'
)

chunks = chunker.chunk(document)
```

### Phase 2 예정

- **SemanticChunker**: 의미 기반 청킹 (Guidebook용)
- **ConversationChunker**: 대화 로그 청킹

## 🏷️ 메타데이터 추출

### RuleBasedExtractor (MVP)

규칙 기반 메타데이터 추출:

```python
from app.modules.core.documents.metadata import RuleBasedExtractor

extractor = RuleBasedExtractor(use_konlpy=True)
metadata = extractor.extract(chunk)

print(metadata['keywords'])          # ['서비스', '이용', '시간']
print(metadata['contains_price'])    # True
print(metadata['categories'])        # ['서비스', '이용']
```

**추출 항목**:
- `contains_price`: 가격 정보 포함 여부
- `keywords`: 핵심 키워드 리스트 (정규식 + 단어 분리)
- `has_date`: 날짜 정보 포함 여부
- `categories`: 도메인 카테고리
- `content_type`: 콘텐츠 유형 ('question', 'info', etc.)

**주의**: LLM을 사용하지 않습니다 (비용 0원)

## 💾 MongoDB 문서 구조

파이프라인으로 생성되는 MongoDB 문서 스키마:

```javascript
{
  // 벡터 검색용 (3072차원)
  "embedding": [0.123, -0.456, ...],

  // 전문 검색용 본문
  "content": "질문: 서비스 이용 시간은 언제인가요? 답변: ...",

  // 메타데이터 (이중 구조)
  "metadata": {
    "metadata": {
      "section": "서비스",              // FAQ 섹션
      "doc_type": "FAQ",                 // 문서 유형
      "source": "data/FAQ.xlsx",         // 원본 파일
      "original_index": 0,               // FAQ 파일 내 순서 (0부터)
      "question": "서비스 이용 시간은..."     // 선택적
    }
  },

  // RuleBasedExtractor 출력 (LLM 미사용)
  "llm_enrichment": {
    "keywords": ["서비스", "이용", "시간"]
  },

  // 검색 최적화 필드 (선택적)
  "contains_price": true,
  "categories": ["서비스", "이용"],
  "content_type": "question"
}
```

**핵심 필드**:
- `embedding`: 벡터 검색 ($vectorSearch)
- `content`: 전문 검색 (Full-Text Search)
- `metadata.metadata`: 필터링용
- `llm_enrichment.keywords`: 하이브리드 검색 보조
- `original_index`: FAQ 파일에서의 원래 순서 (추적용)

### Phase 2 예정

- **LLMBasedExtractor**: LLM 기반 메타데이터 추출

## 🏭 팩토리 패턴

### 기본 사용

```python
from app.modules.core.documents import DocumentProcessorFactory

# 지원 타입 확인
print(DocumentProcessorFactory.get_supported_types())
# ['faq']

# 프로세서 생성
processor = DocumentProcessorFactory.create('faq')
```

### 커스텀 프로세서 등록

```python
from app.modules.core.documents import (
    BaseDocumentProcessor,
    DocumentProcessorFactory
)

class MyProcessor(BaseDocumentProcessor):
    def load(self, source):
        # 커스텀 로딩 로직
        return Document(...)

# 등록
DocumentProcessorFactory.register('custom', MyProcessor)

# 사용
processor = DocumentProcessorFactory.create('custom')
```

## 📝 파일 형식 요구사항

### FAQ (.xlsx, .xls, .csv)

필수 컬럼:
- `질문` 또는 `question` (Q, query도 가능)
- `답변` 또는 `answer` (A, response도 가능)

선택 컬럼:
- `섹션명` 또는 `section`
- `카테고리` 또는 `category`

예시:

| 섹션명 | 질문 | 답변 |
|--------|------|------|
| 서비스 | 이용 시간은? | 09:00~18:00 |
| 요금 | 가격대는? | 10,000원~ |

## 🔄 전체 처리 파이프라인

```python
from app.modules.core.documents import DocumentProcessorFactory

# 1. 프로세서 생성
processor = DocumentProcessorFactory.create('faq')

# 2. 전체 파이프라인 실행
chunks = processor.process('data/FAQ.xlsx')
# 내부적으로 실행되는 단계:
# - load(): 파일 로드 → Document 생성
# - validate(): 문서 검증
# - chunk(): 청킹 → Chunk 리스트 생성
# - extract_metadata(): 메타데이터 추출

# 3. 기존 RAG 파이프라인과 연결 (임베딩 생성)
from app.modules.core.embedding import GeminiEmbeddings

embedder = GeminiEmbeddings(...)
for chunk in chunks:
    embedding = embedder.embed_query(chunk.content)
    chunk.set_embedding(embedding)

# 4. 벡터 DB 저장
from app.database import vector_store

for chunk in chunks:
    vector_store.save({
        'content': chunk.content,
        'embedding': chunk.embedding,
        'metadata': chunk.metadata
    })
```

## 🧪 테스트

간단한 통합 테스트:

```python
# tests/integration/test_faq_processor.py
from app.modules.core.documents import DocumentProcessorFactory

def test_faq_processing():
    processor = DocumentProcessorFactory.create('faq')
    chunks = processor.process('tests/fixtures/sample_faq.xlsx')

    assert len(chunks) > 0
    assert chunks[0].content is not None
    assert 'section' in chunks[0].metadata
    assert 'keywords' in chunks[0].metadata
```

## 📈 Phase 2 확장 계획

### Guidebook Processor
```python
processor = DocumentProcessorFactory.create('guidebook')
chunks = processor.process('data/guidebook.pdf')
```

### ChatLog Processor (개인정보 마스킹)
```python
processor = DocumentProcessorFactory.create('chatlog')
chunks = processor.process('data/conversation.txt')
```

## 🔗 기존 시스템과의 통합

### Low-level (기존)
```python
from app.modules.core.documents import DocumentProcessor

# 기존 방식 (파일 로딩 + 청킹 + 임베딩)
processor = DocumentProcessor(config)
embedded_chunks = await processor.process_document_full('file.pdf')
```

### High-level (MVP Phase)
```python
from app.modules.core.documents import DocumentProcessorFactory

# 새로운 방식 (비즈니스 로직 특화)
processor = DocumentProcessorFactory.create('faq')
chunks = processor.process('data/FAQ.xlsx')
```

**두 시스템은 독립적이며 병행 사용 가능합니다.**

## 📚 추가 자료

- [processingDocument.md](../../../../processingDocument.md) - RAG 문서 처리 전략 가이드
- [CLAUDE.md](../../../../CLAUDE.md) - 프로젝트 개발 가이드라인

## 🤝 기여

새로운 문서 유형 프로세서를 추가하려면:

1. `BaseDocumentProcessor`를 상속하는 클래스 작성
2. `load()` 메서드 구현
3. `processors/` 디렉토리에 파일 생성
4. `DocumentProcessorFactory`에 등록

**예시**: `processors/guidebook_processor.py` (Phase 2)
