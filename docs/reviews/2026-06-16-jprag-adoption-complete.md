# JapanRAG → OneRAG 차용 완료 기록 (수렴 검증)

- **일자**: 2026-06-16
- **레퍼런스**: `/Users/youngouksong/projects/JapanRAG`(프로덕션 다운스트림 포크) → OneRAG(범용 OSS RAG)
- **결과**: **5차 수렴 스윕으로 전 표면 GAP 0 — 차용 소진(수렴) 확인**. PR #96~#113로 약 78건 차용·머지, `main` CI 전 잡 그린.
- **선행**: `docs/reviews/2026-06-10-jprag-adoption-review.md`(1차 리뷰 75건, TOP 15 백포트).

## 방법

1. **신선 트리아지**: 1차 리뷰의 후보를 현재 `main`(PR #70~#84로 대폭 개선됨) 기준으로 59건 재검증(GAP/DONE/BLOCKED/OBSOLETE) — 대형 코드베이스가 양쪽 다 진화했으므로 stale 작업목록을 그대로 쓰지 않음.
2. **수렴 스윕 ×5**: 차용 후 매 라운드 JapanRAG 전체 인벤토리(BE app/ · FE frontend/ · config·infra·scripts · 최근 진화 delta) 4표면을 현재 `main`과 재대조. 이름이 유사한 인접 항목, dead-plumbing, orphaned-frontend 클래스를 추가로 발견하며 0건 수렴까지 반복.

## 차용 범위 (웨이브별, 백엔드/프론트엔드 분리)

| 영역 | 대표 항목 |
|---|---|
| BE 검색·리랭킹 | query_expansion 경량모델, RerankerChain init/close, weaviate return_properties, hybrid fusion_type, 리랭크 fusion guardrail, 동적 alpha, exact-identifier 검색보강+안정화, 멀티턴 anchor soft-boost, mongodb client-side RRF 하이브리드, BGE 로컬 리랭커, GraphRAG filters |
| BE 문서 처리 | PPTX 노트, 표(xlsx/csv) 행 청킹, PDF mojibake 게이트·스캔페이지 보존, 파일명 연도/분기, .doc(LibreOffice), XLSX 날짜 ISO |
| BE 파이프라인·생성 | self-rag options, source_contract 사설참조 필터, `_is_simple_query` 임계, /v1 RAG 재사용·멀티턴, 임베딩 재시도, 다국어 응답 프로파일, 답변 완전성 스캐폴딩, named-document rescue, 환각 게이트, extractive fallback, SSE 페이싱 |
| BE 업로드·스토리지 | 원본 보관(local/GCS), chunked 업로드, 단기 토큰, 잡 취소, audit/ledger store, JobStatus 프로비넌스, 채팅 영속화(Postgres opt-in), 빈화면 서버설정 |
| BE provider(선택) | Vertex 임베딩/LLM/리랭커(extra+가드) |
| 런타임 활성화 | Dockerfile(.doc libreoffice·extraction-quality·BGE preload), nginx(same-origin proxy·frame-ancestors), entrypoint(FEATURE/EMBED 주입), main.py(/v1 chat_service 주입) |
| FE | adminService same-origin, 업로드 표기/진행률/동시성/chunked 클라이언트, RAG trace, 청크 소스상세, POST-SSE 폴백, SSE 타이프라이터, i18n 레이어, embed bridge, PDF bbox·인용좌표, empty-state 서버결선, 세션 보존, 모바일 사이드바 버그, 모델명 정규화 |
| 검증 하니스 | 인프로세스 동시성/업로드 smoke, groundedness E2E, 부하/PDF사이즈/reindex 스크립트 |

## 차용 원칙 (전 항목 공통)

1. **OneRAG 우월 패턴 보존** + 차용분만 통합(코드 복붙 금지). 항상 양쪽 대응 파일을 먼저 읽어 판별.
2. **회귀 0**: 신규 기능은 config opt-in 기본 OFF / no-op 기본값.
3. **범용화**: 일본어·도메인·멀티테넌시(company_id) 하드코딩 제거, 언어/패턴은 config 외부화.
4. **0-dependency 기본**: 무거운 의존성(GCS/Vertex/PyMuPDF/LibreOffice/sentence-transformers)은 선택적 extra + import 가드 + graceful, 코어 미변경.
5. **런타임 정합**: 차용 코드가 컨테이너/배포에서 실제 동작하도록 Docker/nginx/entrypoint/DI 배선까지 완성(dead plumbing 금지).

## 핵심 교훈 — dead plumbing / orphaned half

차용에서 가장 많이 놓친 클래스는 *"코드는 가져왔으나 그것을 실제로 동작시키는 반대편 배선이 빠진 것"*이었다(이 프로젝트가 본래 싸워온 "설계는 좋은데 배선이 깨진" 패턴의 배포·계층 버전):

- **borrowed-backend + orphaned-frontend**: empty-state 서버설정(BE 차용/FE localStorage), chunked 업로드(BE API/FE 미호출).
- **borrowed-consumer + missing-producer**: FE가 `RUNTIME_CONFIG.FEATURES`/`EMBED_ALLOWED_ORIGINS`를 읽지만 entrypoint가 안 채움; same-origin FE인데 nginx 프록시 부재.
- **borrowed-code + missing-runtime**: .doc 로더는 있는데 Dockerfile에 libreoffice 미설치; /v1이 chat_service를 읽는데 main.py 미주입.

수렴 스윕은 소비자 코드만 보고 "차용 완료"로 종결하지 않고 생산자/런타임까지 대조해 이 갭을 드러냈다.

## 의도적 미차용 / 보류 (사유 명확, 재추진 가능)

| 항목 | 사유 |
|---|---|
| Document AI OCR | JapanRAG 854줄이 GCS lifecycle/batch 폴링/언어힌트에 강결합. 깨끗한 선택적 통합은 `OCRBackend` Protocol 신규 빌드 필요, 범용 가치 낮음. `document-ai` extra 격리 시 재추진 가능 |
| document_ledger_store upload 통합 | 모듈·테스트·DI 완비. 단일 출처를 원장으로 바꾸면 검색 경로 전반 파급 + 소비처(PDF 인용/source-detail) 부재로 dead store가 됨 → 인용 하이라이트 피처와 함께 통합 |
| mongodb_hybrid di_container 런타임 와이어링 | RetrieverFactory 등록·config·테스트 완비. 런타임 선택 분기는 별도(JapanRAG도 orphaned였음) |
| 연도 메타 필터 0건 방어 | OneRAG 검색 아키텍처와 불일치(OBSOLETE) |
| 교차 테넌트 negative smoke | 멀티테넌트 전용(BLOCKED) |
| route-mock prod E2E | JapanRAG 프로덕션 특화(config 주입 + i18n 정규식), 범용 가치 낮음 |

## 재현/유지

JapanRAG가 더 진화하면 동일한 수렴 스윕(4표면 × JapanRAG 인벤토리 vs 현재 `main`)으로 신규 델타만 추려 동일 원칙으로 차용하면 된다.
