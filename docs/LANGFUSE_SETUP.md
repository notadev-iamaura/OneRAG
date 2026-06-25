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
- ✅ **LLM 호출별 generation** — model·토큰(input/output/total)·생성 파라미터가
  `generation` 객체로 기록됨. Langfuse가 등록된 모델 가격표로 호출 단위 **비용을
  자동 계산**한다(앱 내부 CostTracker + `/api/admin/realtime-metrics`와 별개로 호출별
  분해 가능).
- ✅ **스트리밍(SSE `/chat/stream`, WebSocket `/chat-ws`) 트레이싱** —
  `RAG Pipeline (Streaming)` 트레이스 + 스트리밍 generation(실제 usage,
  첫 토큰 시각=TTFT). 세션 ID로 트레이스를 그룹핑한다.
  - 스트리밍 토큰은 `stream_options={"include_usage": True}`로 받은 usage 청크에서
    추출하며, 게이트웨이가 usage를 주지 않으면 청크 수 기반 추정으로 폴백한다.
- ✅ 단계별 지연시간, 트레이스 메타데이터

> 개인정보 주의:
> - **출력(LLM 답변)**: generation output은 비스트리밍·스트리밍 **모두 PII 마스킹 후**
>   기록된다(관측 채널로의 raw 답변 유출 방지). generation observation은 입력 자동
>   캡처를 끄고(capture_input=False) 출력만 마스킹해 명시 기록한다.
> - **입력(사용자 질문)**: high-level RAG/stream/retrieval/generation span은
>   `capture_input=False`, `capture_output=False`로 raw 질문·답변·컨텍스트 자동
>   캡처를 끈다. 모델·토큰·지연시간처럼 운영에 필요한 메타데이터만 명시 기록한다.
> - **관리자 대시보드**: `/api/admin/langfuse/*`는 Langfuse 키를 서버에만 두고,
>   trace 목록은 redacted summary로만 반환한다. 전체 raw trace 검수는 Langfuse 접근
>   권한이 있는 운영자가 Langfuse UI에서 별도 정책에 따라 수행한다.
> - 관측은 운영자가 명시적으로 켜는 내부 디버깅 채널이므로, 민감 데이터 정책에 따라
>   Langfuse 프로젝트 접근을 통제하라.

## 5. 종료 시 트레이스 유실 방지

앱 graceful shutdown 시 버퍼에 남은 트레이스를 비우기 위해
`main.py` 종료 훅에서 `langfuse_context.flush()`를 호출합니다(자동).

## 참고

- 인프라 메트릭(CPU/메모리/가동시간)은 Langfuse가 아니라 **배포 플랫폼**(Railway 등)
  내장 기능으로 확인합니다.
- LangSmith도 별도로 공존 지원됩니다(`LANGSMITH_*`). 네임스페이스가 분리돼 충돌하지 않습니다.
