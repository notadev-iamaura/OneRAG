# Langfuse 활성화 가이드 (LLM 관측)

OneRAG는 LLM 관측(observability)을 위해 [Langfuse](https://langfuse.com)를 통합해
두었습니다. RAG 파이프라인 트레이싱과 Self-RAG 품질 점수가 코드에 이미 배선돼
있으며, 아래처럼 **환경변수만 설정하면** 켜집니다(코드 변경 불필요).

> 버전 주의: 코드는 Langfuse **v2 데코레이터 API**(`langfuse.decorators`)를 사용합니다.
> 의존성은 `langfuse>=2.36.2,<3.0.0`으로 고정돼 있어 breaking change가 있는 v3가
> 자동 설치되지 않습니다.

## 1. 호스팅 선택 (둘 중 하나)

| 방식 | `LANGFUSE_HOST` | 비고 |
|---|---|---|
| **Cloud (EU)** | `https://cloud.langfuse.com` | 매니지드 SaaS, 무료 티어. 운영 부담 없음(권장: 소규모 서비스) |
| **Cloud (US)** | `https://us.cloud.langfuse.com` | 미국 리전 |
| **자체호스팅** | `http://localhost:3001` (기본값) | `docker-compose.langfuse.yml`로 기동. 인프라 직접 운영 |

자체호스팅:

```bash
docker compose -f docker-compose.langfuse.yml up -d
```

## 2. API 키 발급

Langfuse 프로젝트 → **Settings → API Keys**에서 발급:
- Public Key: `pk-lf-...`
- Secret Key: `sk-lf-...`

## 3. 환경변수 설정 (4개)

```bash
LANGFUSE_ENABLED=true
LANGFUSE_HOST=https://cloud.langfuse.com   # 또는 us.cloud / localhost:3001
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

- 키가 하나라도 비어 있으면 트레이싱은 **안전하게 비활성화**됩니다(본 기능에는 영향 없음 — graceful degradation, 크래시 없음).
- **on/off 권위 스위치는 `LANGFUSE_ENABLED` 환경변수**입니다(import 시점 게이트). `ENVIRONMENT=test`이거나 `LANGFUSE_ENABLED`가 false 계열(`false`/`0`/`no`/`off`, 대소문자 무관)이면 SDK 자체를 로드하지 않습니다. 미설정/`true`면 로드(키 없으면 inert).
  - 주의: config(YAML)의 `langfuse.enabled`는 import 시점 게이트를 제어하지 않습니다(미사용 래퍼 전용). 끄려면 반드시 `LANGFUSE_ENABLED=false`(또는 `ENVIRONMENT=test`)를 쓰세요.

## 4. 무엇이 보이나 (현재 캡처 범위)

켜면 Langfuse 대시보드에서:
- ✅ **RAG 파이프라인 트레이스 트리** — 검색 → 재순위 → 생성 등 단계별 `@observe`
- ✅ **Self-RAG 품질 점수** — 트레이스에 score로 기록
- ✅ 단계별 지연시간, 트레이스 메타데이터

현재 **미캡처(향후 보강 예정)**:
- ⏳ LLM 호출별 **모델/토큰/비용**이 Langfuse `generation`으로 기록되지는 않음
  (비용은 앱 내부 CostTracker + `/api/admin/realtime-metrics`로 확인).
- ⏳ SSE/WebSocket **스트리밍 경로** 트레이싱.

## 5. 종료 시 트레이스 유실 방지

앱 graceful shutdown 시 버퍼에 남은 트레이스를 비우기 위해
`main.py` 종료 훅에서 `langfuse_context.flush()`를 호출합니다(자동).

## 참고

- 인프라 메트릭(CPU/메모리/가동시간)은 Langfuse가 아니라 **배포 플랫폼**(Railway 등)
  내장 기능으로 확인합니다.
- LangSmith도 별도로 공존 지원됩니다(`LANGSMITH_*`). 네임스페이스가 분리돼 충돌하지 않습니다.
