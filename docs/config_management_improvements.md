# 설정 관리 개선 (v1.0.1)

## 개요

RAG Standard 프로젝트의 설정 관리 시스템을 개선하여 환경별 설정 분리, 검증 강화, 다층 환경 감지 기능을 추가했습니다.

**날짜**: 2026-01-08
**버전**: v1.0.1
**상태**: 완료 (1117개 테스트 통과)

---

## 주요 개선사항

### 1. 환경별 설정 분리

#### 새로운 디렉토리 구조

```
app/config/
├── environments/             # 새로 추가
│   ├── development.yaml     # 개발 환경 설정
│   ├── test.yaml            # 테스트 환경 설정
│   └── production.yaml      # 프로덕션 환경 설정
├── features/                 # 기존 유지
│   ├── embeddings.yaml
│   ├── generation.yaml
│   └── ...
└── base.yaml                 # 공통 설정
```

#### 환경별 설정 특징

**Development (개발 환경)**
- `debug: true` - 디버그 모드 활성화
- `reload: true` - 자동 리로드 활성화
- `cache.enabled: false` - 즉각적인 변경 반영
- `temperature: 0.3` - 다양한 응답 테스트
- `logging.level: DEBUG` - 상세 로깅

**Test (테스트 환경)**
- `temperature: 0.0` - 일관성 중요
- `max_tokens: 512` - 빠른 테스트
- `cache.enabled: false` - 테스트 일관성
- `timeout: 10` - 짧은 타임아웃
- `logging.level: WARNING` - 로그 최소화

**Production (프로덕션 환경)**
- `debug: false` - 디버그 비활성화
- `workers: 4` - 프로덕션 워커 수
- `cache.enabled: true` - 성능 최적화
- `circuit_breaker.enabled: true` - 안정성 확보
- `auto_fallback: true` - LLM 폴백 활성화
- `logging.level: INFO` - 적절한 로깅

---

### 2. 다층 환경 감지 로직 통합

#### 기존 문제점
- 단일 환경 변수(`NODE_ENV`)에만 의존
- 프로덕션 환경 감지가 불완전

#### 개선사항
`environment.py`의 다층 환경 감지 로직을 `ConfigLoader`에 통합:

```python
# 다층 환경 감지 로직 (4가지 지표)
if is_production_environment():
    # 1. ENVIRONMENT=production 또는 prod
    # 2. NODE_ENV=production 또는 prod
    # 3. WEAVIATE_URL이 https://로 시작
    # 4. FASTAPI_AUTH_KEY 설정 존재
    self.environment = "production"
else:
    # 개발/테스트 환경 구분
    env_value = os.getenv("ENVIRONMENT") or os.getenv("NODE_ENV") or "development"
    self.environment = env_value.lower()
```

#### 장점
- **보안**: 단일 환경 변수 조작으로 우회 불가능
- **명확성**: 프로덕션 환경 자동 감지
- **유연성**: 개발/테스트 환경 구분

---

### 3. Pydantic 검증 강화

#### 새로운 검증 모델

`app/lib/config_validator.py`에 다음 Pydantic 모델 추가:

1. **EnvironmentConfig**
   - 환경 설정 검증
   - 프로덕션에서 디버그 모드 차단

2. **ServerConfig**
   - 서버 설정 검증
   - 포트 범위 (1-65535)
   - 워커 수 제한 (1-16)

3. **LLMProviderSettings**
   - LLM 설정 검증
   - Temperature 범위 (0.0-2.0)
   - Max tokens 제한 (1-128000)
   - Timeout 제한 (1-300초)

4. **CacheConfig**
   - 캐시 설정 검증
   - TTL 검증 (≥0)

5. **CircuitBreakerConfig**
   - Circuit Breaker 설정 검증
   - 실패 임계값 검증 (≥1)

#### 검증 함수

```python
# 섹션별 검증
validate_config_section(
    section_name="cache",
    config_data={"enabled": True, "ttl": 3600},
    model=CacheConfig,
    strict=False  # Graceful Degradation
)

# 전체 설정 검증
validate_full_config(
    config=config_dict,
    strict=False  # 검증 실패해도 계속 실행
)
```

---

### 4. ConfigLoader 개선

#### 새로운 파라미터

```python
def load_config(
    validate: bool = True,
    use_modular_schema: bool = False,
    raise_on_validation_error: bool = False,
    enable_enhanced_validation: bool = True,  # 새로 추가
) -> dict[str, Any]:
```

#### 강화된 검증 플로우

```
1. base.yaml 로드
   ↓
2. 환경별 설정 병합 (environments/{environment}.yaml)
   ↓
3. 환경 변수 치환 및 오버라이드
   ↓
4. 강화된 Pydantic 검증 (신규)
   ↓
5. 레거시 Pydantic 검증 (기존)
   ↓
6. 검증된 설정 반환
```

#### 하위 호환성 유지

- `enable_enhanced_validation=False`로 레거시 동작 유지 가능
- 기존 설정 파일 구조 그대로 동작
- 환경별 설정 파일이 없어도 정상 동작

---

## 사용 예시

### 기본 사용 (권장)

```python
from app.lib.config_loader import load_config

# 강화된 검증 포함 (기본값)
config = load_config()
```

### 레거시 검증만 사용

```python
# 강화된 검증 비활성화
config = load_config(enable_enhanced_validation=False)
```

### 엄격한 검증 (개발 환경)

```python
# 검증 실패 시 즉시 예외 발생
config = load_config(raise_on_validation_error=True)
```

### 환경 변수 설정

```bash
# 개발 환경
export ENVIRONMENT=development

# 테스트 환경
export ENVIRONMENT=test

# 프로덕션 환경 (다층 감지)
export ENVIRONMENT=production
export FASTAPI_AUTH_KEY=your_key
export WEAVIATE_URL=https://prod.weaviate.com
```

---

## 테스트 결과

### 전체 검증 통과

```bash
make test        # 1117 passed, 13 skipped
make type-check  # Success: 350 files
make lint        # All checks passed!
make lint-imports # 3 kept, 0 broken
```

### 검증 항목

1. **단위 테스트**: 1117개 통과
2. **타입 체크**: 350개 파일 통과
3. **린트 체크**: 모든 규칙 통과
4. **아키텍처 계층 검증**: 3개 계약 유지
5. **하위 호환성**: 기존 코드 정상 동작

---

## 마이그레이션 가이드

### 기존 프로젝트에서 사용

1. **환경 변수 설정**
   ```bash
   # .env 파일에 추가
   ENVIRONMENT=development  # 또는 test, production
   ```

2. **환경별 설정 파일 복사** (선택사항)
   ```bash
   cp app/config/environments/development.yaml.example \
      app/config/environments/development.yaml
   ```

3. **설정 커스터마이징**
   - 환경별 설정 파일 수정
   - 프로젝트 요구사항에 맞게 조정

### 새 프로젝트에서 사용

1. **기본 설정 그대로 사용**
   - 환경별 설정 파일이 자동으로 로드됨
   - 기본값으로 바로 시작 가능

2. **필요시 설정 오버라이드**
   - 환경 변수로 세부 설정 조정
   - 환경별 YAML 파일 수정

---

## 향후 개선 계획 (선택사항)

### 1. 동적 설정 리로드 (Phase 별도)

```python
# watchdog 라이브러리 활용
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ConfigReloadHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('.yaml'):
            # 설정 리로드 로직
            reload_config_safe()
```

**주의사항**:
- 프로덕션 환경에서는 신중하게 사용
- 리로드 중 일관성 보장 필요
- 성능 오버헤드 고려

### 2. 설정 변경 이력 추적

```python
# 설정 변경 로그 저장
config_history = []

def track_config_change(old_config, new_config):
    change = {
        "timestamp": datetime.now(),
        "old": old_config,
        "new": new_config,
        "diff": compute_diff(old_config, new_config)
    }
    config_history.append(change)
```

---

## 관련 파일

### 수정된 파일

1. **app/lib/config_loader.py**
   - 다층 환경 감지 통합
   - 강화된 검증 로직 추가
   - `enable_enhanced_validation` 파라미터 추가

2. **app/lib/config_validator.py**
   - Pydantic 검증 모델 추가
   - `validate_config_section()` 함수
   - `validate_full_config()` 함수

### 새로 추가된 파일

1. **app/config/environments/development.yaml**
   - 개발 환경 최적화 설정

2. **app/config/environments/test.yaml**
   - 테스트 환경 최적화 설정

3. **app/config/environments/production.yaml**
   - 프로덕션 환경 최적화 설정

4. **docs/config_management_improvements.md**
   - 이 문서

---

## 참고 자료

- **CLAUDE.md**: 프로젝트 개요 및 개발 가이드
- **app/lib/environment.py**: 다층 환경 감지 로직
- **app/config/base.yaml**: 기본 설정 구조
- **Pydantic Documentation**: https://docs.pydantic.dev/

---

## 문의 및 피드백

설정 관리 개선사항에 대한 문의나 피드백은 프로젝트 이슈 트래커를 통해 제출해주세요.

**작성자**: AI Assistant (Claude Code)
**날짜**: 2026-01-08
**버전**: v1.0.1
