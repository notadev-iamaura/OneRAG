# OneRAG 시스템 분석 및 개선 계획

> **문서 버전**: 1.0.0
> **분석 일자**: 2026-01-24
> **분석 도구**: Claude Code Systematic Debugging
> **대상 버전**: OneRAG v1.2.1

---

## 1. Executive Summary

### 현재 상태: ✅ **안정적 (Production Ready)**

| 영역 | 점수 | 상태 |
|------|------|------|
| **코드 품질** | 98/100 | ✅ 우수 |
| **테스트** | 99/100 | ✅ 우수 (1,672 통과) |
| **보안** | 98/100 | ✅ 패치 완료 |
| **설정 관리** | 95/100 | ✅ 양호 |
| **안정성** | 85/100 | ⚠️ 개선 가능 |
| **코드 위생** | 95/100 | ✅ 양호 |
| **종합** | 95/100 | ✅ **안정적** |

---

## 2. 검증 완료 항목 (Pass)

### 2.1 코드 품질 ✅
- **Ruff 린트**: All checks passed (429개 소스 파일)
- **Mypy 타입 체크**: No issues found (429개 소스 파일)
- **Import Linter**: 계층 구조 준수
- **전체 테스트**: 1,672개 통과, 15개 스킵 (선택적 의존성)

### 2.2 보안 패치 완료 ✅
- **P0 Critical 4개**: Documents API, Ingest API 인증 추가
- **P1 High 6개**: Monitoring, Prompts, Tools, LangSmith API 인증 추가
- **CORS 설정**: 명시적 메서드 지정 완료
- **환경 감지 버그**: FASTAPI_AUTH_KEY 로직 수정 완료

### 2.3 하드코딩 시크릿 ✅
- 모든 API 키가 `os.getenv()`를 통해 로드됨
- 하드코딩된 비밀번호/토큰 없음

### 2.4 보안 위험 함수 ✅
- `os.system()`, `subprocess.call()`, `eval()` 사용 없음
- 와일드카드 import 없음

---

## 3. 발견된 문제점 및 개선 계획

### 3.1 P2 (Medium) - 코드 위생

#### 3.1.1 디버그용 print 문 ✅ (대부분 해결됨)

**현황**: 핵심 모듈의 print 문은 logger로 교체 완료. CLI 스크립트용 print 문만 남아있음.

| 파일 | 라인 | 상태 | 비고 |
|------|------|------|------|
| ~~`app/config/schemas/root.py`~~ | - | ✅ 해결 | logger.warning/debug로 교체 |
| ~~`app/config/schemas.py`~~ | - | ✅ 해결 | logger.warning로 교체 |
| ~~`app/lib/config_loader.py`~~ | - | ✅ 해결 | logger.info/debug/warning로 교체 |
| `app/batch/notion_batch.py` | 818-831 | 🟢 의도적 | CLI 결과 출력용 |
| `app/batch/external_crawler.py` | 657-663 | 🟢 의도적 | CLI 결과 출력용 |
| `app/batch/metadata_chunker.py` | 504-509 | 🟢 의도적 | CLI 테스트 결과용 |

**결론**: CLI 스크립트(`if __name__ == "__main__":`)의 print 문은 사용자 대화형 출력으로 의도적인 사용입니다.

**우선순위**: ✅ 완료 (추가 작업 불필요)

---

#### 3.1.2 광범위한 예외 처리 (19개)

**현황**: `except Exception:` 패턴이 여러 곳에서 사용됨

| 파일 | 위치 | 컨텍스트 |
|------|------|----------|
| `app/middleware/error_logger.py` | 90, 119 | 미들웨어 폴백 |
| `app/core/di_container.py` | 174 | 리랭커 초기화 |
| `app/batch/external_crawler.py` | 270, 474 | 크롤링 에러 핸들링 |
| `app/api/upload.py` | 302 | 업로드 정리 |
| `app/api/documents.py` | 216 | 문서 조회 |
| `app/infrastructure/storage/vector/chroma_store.py` | 184, 264, 279, 298, 314 | 벡터 DB 연산 |

**권장 조치**:
```python
# 현재: 모든 예외를 동일하게 처리
except Exception:
    pass

# 개선: 예상되는 예외만 명시적으로 처리
except (ConnectionError, TimeoutError) as e:
    logger.warning(f"연결 실패: {e}")
except ValueError as e:
    logger.error(f"잘못된 값: {e}")
    raise
```

**우선순위**: P2 (Graceful Degradation을 위한 의도적 패턴일 수 있음)

---

#### 3.1.3 Deprecated 경고

**현황**: 일부 deprecated 패턴 사용

| 항목 | 위치 | 내용 |
|------|------|------|
| `duckduckgo_search` | `app/modules/core/tools/web_search.py:327` | `ddgs` 패키지로 교체 필요 |
| `tool.uv.dev-dependencies` | `pyproject.toml` | `dependency-groups.dev`로 마이그레이션 |
| `agent.timeout` | `app/modules/core/agent/interfaces.py` | `timeout_seconds` 사용 권장 |

**권장 조치**:
```bash
# duckduckgo_search → ddgs
pip uninstall duckduckgo_search && pip install ddgs

# pyproject.toml 마이그레이션
# [tool.uv.dev-dependencies] → [dependency-groups.dev]
```

**우선순위**: P2 (기능 동작에는 문제 없음)

---

### 3.2 P2 (Medium) - 설정 및 기능

#### 3.2.1 비활성화된 기능

| 기능 | 설정 파일 | 비활성화 사유 |
|------|-----------|---------------|
| **Self-RAG** | `self_rag.yaml:9` | Google API Rate Limit |
| **LLM Router** | `routing.yaml:12,66` | OpenRouter 연결 문제 |
| **GraphRAG** | `graph_rag.yaml:18` | 선택적 기능 |
| **Privacy Review** | `privacy.yaml:102` | 선택적 기능 |
| **Query Expansion** | `query_expansion.yaml:6` | 선택적 기능 |
| **Evaluation** | `evaluation.yaml:8` | 선택적 기능 |

**권장 조치**:
- Self-RAG: Rate Limit 재시도 로직 추가 후 활성화
- LLM Router: OpenRouter 연결 진단 후 활성화

**우선순위**: P2 (현재 대체 기능으로 동작 중)

---

#### 3.2.2 테스트용 설정값

| 설정 | 파일 | 현재 값 | 권장 값 |
|------|------|---------|---------|
| `min_score` | `reranking.yaml:22` | `0.0` | `0.05` (프로덕션) |
| `collection_weight_enabled` | `rag.yaml:67` | `false` | 도메인별 조정 |
| `file_type_weight_enabled` | `rag.yaml:81` | `false` | 도메인별 조정 |

**권장 조치**: 환경별 설정 분리 (`environments/production.yaml`)

**우선순위**: P2

---

#### 3.2.3 Chat API Rate Limit 제외

**파일**: `main.py:564-576`

```python
excluded_paths=[
    "/api/chat",         # ⚠️ 제외됨
    "/api/chat/session",
    "/api/chat/stream",
]
```

**문제**: StreamingResponse에서 body 읽기 타임아웃 방지를 위해 제외됨

**권장 조치**: StreamingResponse 호환 Rate Limiter 구현 (Phase 4에서 해결 예정)

**우선순위**: P2

---

### 3.3 P3 (Low) - 코드 품질

#### 3.3.1 대형 파일 (>500 LOC)

| 파일 | 라인 수 | 권장 조치 |
|------|---------|-----------|
| `di_container.py` | 2,324 | 모듈 분리 검토 |
| `rag_pipeline.py` | 2,080 | 단계별 분리 검토 |
| `errors/messages.py` | 1,666 | 정상 (에러 메시지 저장소) |
| `orchestrator.py` | 1,194 | 정상 (복잡한 검색 로직) |
| `admin.py` | 1,174 | 엔드포인트별 분리 검토 |

**우선순위**: P3 (기능 동작에 영향 없음)

---

#### 3.3.2 전역 변수 사용 (21개)

**현황**: 싱글톤 패턴 구현을 위한 전역 변수 사용

| 파일 | 변수 | 용도 |
|------|------|------|
| `score_normalizer.py` | `_default_normalizer` | 싱글톤 |
| `auth.py` | `_auth_instance` | 싱글톤 |
| `metrics.py` | `_global_performance_metrics` | 싱글톤 |
| `llm_client.py` | `_global_factory` | 싱글톤 |
| 각 라우터 | `modules`, `config` 등 | 지연 초기화 |

**권장 조치**: DI Container로 마이그레이션 검토 (이미 80+ Provider 구현됨)

**우선순위**: P3 (현재 패턴이 동작 중)

---

#### 3.3.3 Type Ignore 주석 (30개)

**현황**: 타입 시스템 한계로 인한 `# type: ignore` 사용

**대부분 정당한 사용**:
- 동적 타입 캐스팅 (`# type: ignore[assignment]`)
- 서드파티 라이브러리 타입 불일치 (`# type: ignore[arg-type]`)
- 스트리밍 응답 처리 (`# type: ignore[union-attr]`)

**우선순위**: P3 (mypy 통과, 기능 정상)

---

## 4. 리소스 정리 패턴

### 4.1 정상 패턴 ✅

- Weaviate 클라이언트: `close()` 메서드 존재
- MongoDB 클라이언트: `close()` 메서드 존재
- 벡터 스토어: 컨텍스트 매니저 및 `close()` 지원
- 배치 클라이언트: `async with` 및 명시적 `close()` 사용

### 4.2 경고 사항 ⚠️

**Weaviate 연결 경고** (테스트 중 발생):
```
ResourceWarning: The connection to Weaviate was not closed properly.
```

**원인**: 테스트 환경에서 비동기 컨텍스트 정리 순서 문제

**권장 조치**: 테스트 fixture에서 명시적 cleanup 추가

---

## 5. 개선 작업 우선순위

### 5.1 즉시 작업 불필요 (현재 안정적)

| 항목 | 이유 |
|------|------|
| 보안 패치 | ✅ P0, P1 모두 완료 |
| 테스트 | ✅ 1,672개 통과 |
| 린트/타입 | ✅ 모두 통과 |
| 핵심 기능 | ✅ 정상 동작 |

### 5.2 P2 개선 권장 (1개월 내)

| 항목 | 예상 소요 | 영향도 | 상태 |
|------|-----------|--------|------|
| Self-RAG 활성화 | 2일 | 답변 품질 향상 | ⏳ 대기 |
| LLM Router 활성화 | 1일 | 라우팅 정확도 향상 | ⏳ 대기 |
| ~~print → logger 교체~~ | - | 로깅 일관성 | ✅ 완료 |
| 설정 환경 분리 | 1일 | 배포 안정성 | ⏳ 대기 |
| Chat Rate Limit | 2일 | 보안 강화 | ⏳ 대기 |

### 5.3 P3 개선 선택적 (분기별)

| 항목 | 예상 소요 | 영향도 |
|------|-----------|--------|
| 대형 파일 분리 | 3일 | 유지보수성 |
| 전역변수 DI 마이그레이션 | 2일 | 테스트 용이성 |
| duckduckgo → ddgs 교체 | 0.5일 | deprecated 해소 |

---

## 6. 검증 명령어

```bash
# 코드 품질 검증
make lint           # ruff 린트 검사 ✅ All checks passed
make type-check     # mypy 타입 체크 ✅ No issues found
make lint-imports   # 아키텍처 계층 검증

# 테스트 실행
make test           # 전체 테스트 ✅ 1,672 passed
make test-cov       # 커버리지 리포트

# 보안 검사 (추가 권장)
uv run bandit -r app/  # Python 보안 검사
uv run safety check    # 의존성 취약점 검사
```

---

## 7. 결론

### 7.1 시스템 상태

```
┌─────────────────────────────────────────────────────────────┐
│  OneRAG v1.2.1 시스템 상태: ✅ 안정적 (Production Ready)     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ✅ 코드 품질: 린트/타입 체크 100% 통과                      │
│  ✅ 테스트: 1,672개 통과                                    │
│  ✅ 보안: P0 4개, P1 6개 모두 해결                          │
│  ✅ DI 패턴: 80+ Provider, 9개 팩토리 완비                   │
│  ✅ 코드 위생: print → logger 교체 완료                     │
│                                                             │
│  ⚠️ 개선 가능: Self-RAG, LLM Router 활성화 (P2)            │
│  ⚠️ 개선 가능: 대형 파일 분리 (P3)                          │
│                                                             │
│  결론: 현재 상태로 프로덕션 배포 가능                        │
│        P2 항목은 배포 후 1개월 내 개선 권장                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 다음 단계

1. **즉시**: 현재 상태 유지 (안정적)
2. **1주일 내**: Self-RAG, LLM Router 활성화 테스트
3. **1개월 내**: 설정 환경 분리, Chat Rate Limit 구현
4. **분기별**: 코드 구조 개선 (대형 파일 분리)

---

**문서 작성자**: Claude Code (Systematic Debugging)
**검증 일자**: 2026-01-24
**검토 필요**: Tech Lead, DevOps Team
