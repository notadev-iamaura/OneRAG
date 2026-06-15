# Scripts 디렉토리

프로젝트 관리 및 분석 스크립트 모음

## 📊 의존성 그래프 생성 (`generate_dependency_graph.py`)

pydeps를 사용하여 프로젝트의 의존성 그래프를 시각화합니다.

### 사전 준비

#### 1. Python 의존성 설치
```bash
make install-dev
# 또는
uv sync
```

#### 2. Graphviz 설치 (필수)
```bash
# macOS
brew install graphviz

# Ubuntu/Debian
sudo apt-get install graphviz

# Windows (Chocolatey)
choco install graphviz

# 설치 확인
dot -V
```

### 기본 사용법

#### 1. 전체 프로젝트 그래프 생성 (기본값)
```bash
python scripts/generate_dependency_graph.py
```
- **출력**: `docs/diagrams/dependencies.svg`
- **형식**: SVG (확대/축소 가능)
- **깊이**: 2단계
- **클러스터링**: 활성화

#### 2. Makefile 사용 (권장)
```bash
make deps-graph
```

### 고급 사용법

#### 특정 모듈만 분석
```bash
# Retrieval 모듈만 분석
python scripts/generate_dependency_graph.py --module app.modules.core.retrieval

# API 레이어만 분석
python scripts/generate_dependency_graph.py --module app.api
```

#### 출력 형식 변경
```bash
# PNG 형식
python scripts/generate_dependency_graph.py --format png

# PDF 형식
python scripts/generate_dependency_graph.py --format pdf

# 커스텀 출력 경로
python scripts/generate_dependency_graph.py --output custom/path/graph.svg
```

#### 깊이 조절
```bash
# 1단계만 (직접 의존성만)
python scripts/generate_dependency_graph.py --max-depth 1

# 3단계까지
python scripts/generate_dependency_graph.py --max-depth 3
```

#### 클러스터링 제거 (간단한 그래프)
```bash
python scripts/generate_dependency_graph.py --no-cluster
```

#### 그래프 방향 변경
```bash
# 왼쪽에서 오른쪽 (수평)
python scripts/generate_dependency_graph.py --rankdir LR

# 오른쪽에서 왼쪽
python scripts/generate_dependency_graph.py --rankdir RL

# 아래에서 위
python scripts/generate_dependency_graph.py --rankdir BT
```

#### 특정 모듈 제외
```bash
# tests와 scripts 제외
python scripts/generate_dependency_graph.py --exclude "tests,scripts"
```

#### 외부 의존성 표시
```bash
# site-packages의 외부 라이브러리도 표시
python scripts/generate_dependency_graph.py --show-deps
```

### 조합 예시

#### 1. API 레이어 상세 분석 (PNG)
```bash
python scripts/generate_dependency_graph.py \
  --module app.api \
  --format png \
  --max-depth 3 \
  --no-cluster \
  --output docs/diagrams/api_dependencies.png
```

#### 2. Retrieval 시스템 수평 그래프
```bash
python scripts/generate_dependency_graph.py \
  --module app.modules.core.retrieval \
  --rankdir LR \
  --max-depth 2 \
  --output docs/diagrams/retrieval_flow.svg
```

#### 3. 전체 시스템 단순화 (1단계만)
```bash
python scripts/generate_dependency_graph.py \
  --max-depth 1 \
  --no-cluster \
  --exclude "tests,scripts" \
  --output docs/diagrams/overview.svg
```

#### 4. Dry Run (명령어 확인만)
```bash
python scripts/generate_dependency_graph.py --dry-run --verbose
```

### 옵션 전체 목록

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--module` | `app` | 분석할 모듈 경로 |
| `--output` | `docs/diagrams/dependencies.{format}` | 출력 파일 경로 |
| `--format` | `svg` | 출력 형식 (svg, png, pdf) |
| `--max-depth` | `2` | 최대 의존성 깊이 |
| `--no-cluster` | `False` | 클러스터링 비활성화 |
| `--rankdir` | `TB` | 그래프 방향 (TB, LR, BT, RL) |
| `--no-config` | `False` | `.pydeps` 파일 무시 |
| `--show-deps` | `False` | 외부 의존성 표시 |
| `--exclude` | `""` | 제외할 모듈 (쉼표 구분) |
| `--verbose` | `False` | 상세 출력 모드 |
| `--dry-run` | `False` | 명령어만 출력 (실행 X) |

### 그래프 해석 가이드

#### 화살표 의미
- **A → B**: A가 B를 import함
- **색상 클러스터**: 같은 패키지/모듈 그룹
- **점선**: 선택적 의존성 (일부 경우에만 import)

#### 문제 패턴 식별
1. **순환 참조**: A → B → C → A 형태의 사이클
2. **과도한 결합**: 한 모듈이 너무 많은 모듈에 의존
3. **계층 위반**: 하위 레이어가 상위 레이어를 import

### 문제 해결

#### "pydeps를 찾을 수 없습니다"
```bash
make install-dev
# 또는
uv sync
```

#### "dot 명령을 찾을 수 없습니다"
```bash
# Graphviz가 설치되지 않음
brew install graphviz  # macOS
```

#### "ImportError" 발생
```bash
# 프로젝트 루트에서 실행하는지 확인
pwd
# /Users/youngouksong/Development/MW_RAGchat

# Python 경로 확인
uv run python -c "import sys; print(sys.path)"
```

#### 그래프가 너무 복잡함
```bash
# 깊이를 1로 줄이고 클러스터링 제거
python scripts/generate_dependency_graph.py --max-depth 1 --no-cluster
```

### CI/CD 통합

#### GitHub Actions 예시
```yaml
- name: Generate Dependency Graph
  run: |
    uv sync
    python scripts/generate_dependency_graph.py --format png

- name: Upload Artifact
  uses: actions/upload-artifact@v3
  with:
    name: dependency-graph
    path: docs/diagrams/dependencies.png
```

### 참고 자료

- [pydeps 공식 문서](https://github.com/thebjorn/pydeps)
- [Graphviz 문법](https://graphviz.org/doc/info/lang.html)
- 프로젝트 의존성 규칙: `.import-linter.ini`

---

## 🔬 운영 스모크/E2E 하니스 (라이브 서버 대상)

아래 스크립트들은 **실행 중인 API 서버**를 대상으로 동작하는 운영 진단 도구입니다.
모두 `--json`(또는 JSON 출력)과 종료 코드(성공 0 / 실패 1) 컨벤션을 따르며,
인증은 `FASTAPI_AUTH_KEY` 환경변수(또는 `--api-key*` 인자)에서 `X-API-Key`를 구성합니다.
키/서버가 없으면 graceful하게 보고합니다.

### 동시 /chat 부하 스모크 (`chat_concurrency_smoke.py`)

N개의 동시 `/chat` 요청을 발사하고 요청별 게이트(지연 임계, 소스 존재, 폴백 마커
부재, 기대 용어)를 적용합니다. 순차 e2e로는 못 잡는 동시 부하 회귀를 진단합니다.

```bash
uv run python scripts/chat_concurrency_smoke.py \
    --backend-url http://localhost:8000 \
    --question "RAG란 무엇인가요?" \
    --concurrency 10 --threshold-seconds 10 \
    --expect-term RAG --fallback-marker "AI 답변 생성 중 오류"
```

### 업로드 사이즈 스모크 (`upload_size_smoke.py`)

바이트 정밀 PDF를 합성해 direct 경로로 업로드하고 처리 완료까지 검증합니다.
`--max-size-mib`로 경계 초과 시 HTTP 413(또는 4xx) 거부를 확인합니다(앱+프록시+플랫폼
3개 층이 겹쳐 결정되는 한계는 로컬 단위 테스트로 검증 불가).

```bash
uv run python scripts/upload_size_smoke.py \
    --base-url http://localhost:8000 \
    --direct-sizes-mib 3 4 --max-size-mib 60
```

### 배치 재색인 (`reindex_documents.py`)

로컬 코퍼스를 실행 중인 API를 통해 일괄 재색인합니다(stdlib만 사용). 안전 가드 내장:
`--allow-remote-reset`(비로컬 인덱스 삭제 방지), `--allow-zero-embeddings`(서버 미준비
상태에서 리셋 방지).

```bash
# 미리보기(업로드 없이 계획만)
uv run python scripts/reindex_documents.py --source-dir ./data/sample_corpus --dry-run

# 리셋 후 재색인
uv run python scripts/reindex_documents.py \
    --backend-url http://localhost:8000 \
    --source-dir ./data/sample_corpus --reset --json
```

### 실코퍼스 groundedness E2E (`production_corpus_e2e.py`)

임의 로컬 코퍼스를 다포맷 추출 → 근거 기반 골든질문 자동 생성 → 라이브 서버에
업로드 후 질의 → 답변 근거성(기대 용어 + 출처 파일명) 채점. 언어/도메인 중립.

```bash
# 1) 골든질문 생성(서버 불필요)
uv run python scripts/production_corpus_e2e.py generate \
    --corpus-dir ./data/sample_corpus --output-dir ./reports/run1

# 2) 라이브 서버에 업로드 + 채점
uv run python scripts/production_corpus_e2e.py run-production \
    --corpus-dir ./data/sample_corpus \
    --golden ./reports/run1/golden_questions.json \
    --output-dir ./reports/run1 \
    --backend-url http://localhost:8000
```

> 예시 코퍼스: `data/sample_corpus/`(언어 중립 무라이선스 문서). 질문 템플릿은
> `--question-template`, 외부 정답 사실은 `--manual-facts-json`으로 주입할 수 있습니다.

## 🧪 인프로세스 검증 테스트 (서버 불필요)

운영 도구와 별개로, 외부 서버 없이 동작하는 in-process 테스트 2종을 추가했습니다.
무거우므로 기본 `tests/unit` 게이트에서 제외되도록 마커를 분류했습니다.

- `tests/integration/test_operational_performance_acceptance.py`
  (`integration`, `performance` 마커): httpx ASGITransport로 실제 라우터 스택을
  통과시켜 N개 동시 `/chat`이 이벤트 루프에서 직렬화되지 않는지 검증.
- `tests/local_smoke/test_local_upload_flow.py` (`integration` 마커): stub 모듈을
  주입해 업로드→워커→상태→목록→삭제 상태 전이를 외부 의존성 0으로 검증.

```bash
ENVIRONMENT=test uv run python -m pytest \
    tests/integration/test_operational_performance_acceptance.py \
    tests/local_smoke/test_local_upload_flow.py -q
```
