# 공개 데이터로 한국어 문서 조사 정책 개선하기

후보를 기존 정책과 같은 문항에서 비교하고, 개선이 반복해서 확인된 경우에만 미사용 문항으로 넘어간다. 제품에 연결된 고객 대화나 외부 생성 API는 입력에 포함하지 않는다. 현재 후보는 문서 조사 모드에서 질문과 인용문의 주체·사건·기간·수량이 어긋날 단서가 있을 때 근거 문장을 한 번 더 확인한다. 제품 설정은 `mcp.agent.require_evidence_quotes`와 `mcp.agent.verify_premise_mismatch`다. 후보 실험은 후자만 바꾼다.

## 실행

1. `make rag-quality-smoke`로 모델 없이 판정기와 실제 에이전트의 인용·보류 처리를 검증한다.
2. [KLUE-MRC 고정 버전](https://huggingface.co/datasets/klue/klue/tree/349481ec73fff722f88e0453ca05c77a447d967c/mrc)의 train과 validation Parquet를 준비한다. 아래 준비기는 파일 해시를 대조한 뒤 train에서 네 표본을 동시에 만든다. 공식 validation의 질문·기사와 이전에 노출된 패널을 제외한다. 다른 회차의 모든 개발·평가 패널과 검색 방해 문서는 `--exclude-panel`을 반복해서 전달한다. 표본의 독립성은 실제로 제외한 이력 범위에서 해석한다.
3. 사용할 GGUF를 llama.cpp로 루프백 주소에 올린다. 서버의 모델 이름, 실제 파일 경로, SHA-256을 실행기가 대조한다. 평가에는 프로젝트 Python 환경과 한국어 BM25 검색기가 필요하고, 표본 준비에만 잠금 파일에 들어 있는 PyArrow가 필요하다.

```sh
# KLUE_TRAIN, KLUE_VALIDATION, MODEL_FILE, MODEL_SHA256, PANELS, RUN_DIR를 지정한다.
uv run --with pyarrow==22.0.0 python scripts/rag_growth_prepare.py \
  --train "$KLUE_TRAIN" --validation "$KLUE_VALIDATION" --round round-01 \
  --model onerag-growth-qwen --model-sha256 "$MODEL_SHA256" --output-dir "$PANELS"

# 별도 터미널에서 실행
llama-server -m "$MODEL_FILE" --alias onerag-growth-qwen --host 127.0.0.1 \
  --port 18759 --ctx-size 8192 --parallel 1 --reasoning off --no-ui

make rag-quality-local PANELS="$PANELS" RUN_DIR="$RUN_DIR" PORT=18759 MODEL_FILE="$MODEL_FILE"
```

각 회차는 새 결과 디렉터리를 사용한다. 같은 모델과 검색 코퍼스에 두 정책을 번갈아 호출하고, 매번 새 에이전트 상태에서 시작한다. 문항별로 세 번 호출하며 온도는 0이다. 같은 질문의 세 호출은 반복 안정성을 측정한다. 질문 수는 한 개로 센다. 시간 초과·잘못된 인용·형식 오류도 결과에 남는다.

각 표본의 `provenance.json`에는 실행 전에 확인한 모델 이름, 에이전트·실행기·인덱스 해시가 들어간다. 재채점 시 이를 실행 기록과 대조한다. 답할 수 있는 문항은 정답·문서 ID와 함께 실제 인용문에 정답 구절이 들어 있는지 확인한다. 준비기가 기록한 공식 답 위치가 있으면 해당 위치까지 대조한다. 인물·사건의 의미 관계는 대표 문항의 질문과 근거를 함께 읽어 판단한다. 답할 수 없는 문항의 정상 보류는 결과 지표이고, 단독으로는 에이전트가 어떤 반증을 찾았는지 설명하지 않는다.

공개 개발 표본에서 인용 검증이 실패하면 `model_diagnostic`에 실패 직전 실제 모델 출력의 앞 400자와 전체 출력의 해시를 남긴다. 이 기록을 보면 모델이 직접 보류했는지, 제품이 잘못된 인용을 감지하고 대체 문구를 표시했는지 구별할 수 있다. 제안기는 검증된 발췌 중 최대 200자를 참조한다. 최종 표본과 일반 채팅에는 이 진단 기록을 수집하지 않는다.

## 로컬 단답형 문서 QA

문서에서 이름, 날짜, 금액처럼 특정 구절을 찾는 에이전트에는 `mcp.agent.require_evidence_quotes`를 켜고 `mcp.agent.extractive_reader`를 지정할 수 있다. `generative`는 에이전트에 설정된 생성 모델을 사용한다. `ko_encoder`와 `en_encoder`는 `model_dir`의 로컬 체크포인트를 읽는다. 응답에는 실제 인용문과 검색한 원문 기준의 문자 위치가 들어간다. 보류하면 인용은 비어 있고, 모델이나 인용 처리 실패는 오류로 기록한다.

짧은 한국어 문단 코퍼스에서는 `ko_multi_passage`로 상위 8개 문단의 관련성과 답 구절을 함께 판정할 수 있다. 결합 검색기와 로컬 독해·근거 모델을 함께 설정한다. 위키백과 문단과 긴 기사에서 성능이 달라 이 모드는 선택 사항이다. [공개 데이터별 품질 결과](rag-quality-results.md)

한국어 검색 1위 기사 한 건을 로컬 Qwen과 기존 독해기로 읽는 구성에서는 `mcp.agent.extractive_reader.evidence_policy`에 `verified_korean_spans`를 지정할 수 있다. 같은 구절을 두 판독기가 각각 찾으면 질문의 수치·단위·연도와 실제 인용 위치를 확인해 근거를 보정한다. 프로필의 `reader`에 `implementation: generative`, `top_k: 1`, `rescue_refusals: true`, `sufficiency_threshold: 0.0`, `rescue_span_threshold: 4.0`을 지정한다. `sufficiency_model_dir`와 `boundary_model_dir`에는 각각 준비한 로컬 근거·독해 체크포인트의 절대 경로를 넣는다. 성적 공개 전에 설정을 고정한 KLUE 3차에서는 근거 정답 58/80, 올바른 보류 62/80이었다. [설정 검증과 판독 코드](../../app/modules/core/agent/extractive_reader.py) · [평가 결과와 적용 범위](rag-quality-results.md)

API 응답에서 원문 그대로 공개할 수 있는 단답형 인용은 `sources[].additional_metadata`에 `answer_start`, `answer_end`, `quote_start`, `quote_end`를 함께 전달한다. 검색한 청크 첫 문자에서 0부터 유니코드 코드 포인트로 세며 끝 위치는 제외한다. 개인 정보 처리로 인용문이 바뀌면 원문 위치를 생략한다.

한국어 단답형 KLUE 평가기는 512개 기사에서 검색을 수행한다. 이 평가기의 `PANELS`에는 `rag_growth_ko_panels.py`가 만든 `reservation.json`과 분할별 `*.questions.json`, `*.corpus.json`, `*.labels.json`이 필요하다. 앞의 문서 조사 회차와 입력 형식이 다르다. 답할 수 있는 질문은 정답 표현, 출처, 인용문과 공식 정답 위치가 모두 일치해야 통과한다. 보류율의 분모는 원본 데이터가 답할 수 없다고 표시한 질문 전체다. `--agent-profile`로 실행하면 실제 문서 도구와 에이전트 팩토리를 사용한다. 설정 파일의 `reader`는 제품의 `extractive_reader`에 대응한다. `gguf`에는 검증할 로컬 생성 서버의 모델 별칭(`name`), 포트(`port`), GGUF의 절대 경로(`file`)를 기록한다. [패널 준비기](../../scripts/rag_growth_ko_panels.py)

```sh
# PROFILE, PANELS, FREEZE, RESULT와 프로필에 맞는 DEVICE와 TOP_K를 지정한다.
ENVIRONMENT=test LANGFUSE_ENABLED=false python scripts/rag_growth_ko_eval.py \
  --split freeze --panels "$PANELS" --agent-profile "$PROFILE" --device "$DEVICE" \
  --top-k "$TOP_K" --freeze "$FREEZE"
ENVIRONMENT=test LANGFUSE_ENABLED=false python scripts/rag_growth_ko_eval.py \
  --split final --panels "$PANELS" --agent-profile "$PROFILE" --device "$DEVICE" \
  --top-k "$TOP_K" --freeze "$FREEZE" --output "$RESULT" --require-target
```

평가기에서 두 비율이 각각 80% 이상이면 `both_at_least_80`가 참이다. `--require-target`은 한쪽이라도 미달하면 결과 파일을 남기고 종료 코드 1을 반환한다. 새 후보는 개발 문항에서 비교하고, 한 번 결과를 확인한 최종 문항은 다음 후보의 독립 평가에서 제외한다.

### 한국어·영어 공개 표본 전수 재채점

384문항 평가의 원응답을 다시 채점하려면 보존된 실행 디렉터리, Stanford의 SQuAD 2.0 개발 JSON, 해당 실행에서 준비한 영어 TyDi 문단·질문 JSON을 지정한다. 공개 저장소에는 표본 목록과 집계가 있고, 원응답과 코퍼스는 실행 환경에 보관한다. 한국어 KLUE와 TyDi, 영어 SQuAD의 두 표본과 영어 TyDi에서 근거 있는 정답과 올바른 보류가 각각 80% 이상이어야 통과한다. 종료 코드 1은 유효한 측정의 목표 미달, 2는 입력이 없거나 원본 검증에 실패한 경우다. 동일한 결과 파일로 다시 실행하면 첫 기록과 대조한다. [표본 목록](../../output/rag-growth-03/public-suite.json) · [공개 점수 및 모델 없는 재현 방법](rag-quality-results.md)

```sh
ENVIRONMENT=test python -m scripts.rag_growth_public_gate \
  --root "$RUN_DIR" --squad "$SQUAD_JSON" --tydi-en "$TYDI_EN_JSON" \
  --receipt "$RUN_DIR/public-suite-result.json"
```

## 판정과 다음 후보

- 개발 A·B 각각에서 답할 수 있는 8문항과 보류해야 하는 4문항을 채점한다. 각 회차와 세 번 모두 성공한 문항 수에서 어느 집단도 퇴보하지 않아야 한다. 두 개발 표본 각각에서 첫 시도 또는 세 번 모두 성공한 문항 수가 늘고, 실행 오류가 없고, 후보 평균 토큰이 기존의 1.5배 이하여야 한다. 지연은 평균과 p95를 기록한다.
- 두 개발 표본을 통과하면 판정기가 개봉 기록을 남기고 최종·재현 표본을 각각 한 번 사용한다. 각 표본에서 세 번 모두 정답·출처를 맞힌 질문이 24개 중 20개 이상, 올바르게 보류하고 인용을 비운 질문이 12개 중 9개 이상이어야 한다. 개봉 기록은 공식 실행 경로에 적용된다. 결과나 정답을 본 표본은 다음 회차에 회귀용으로 분류한다.
- `round.json`은 한국어 문서 조사 정책의 채택 판단을 담는다. 각 표본의 `comparison.json`에는 기준·후보별 분모와 성공, 개선·악화, 토큰·지연이 남는다. 기존 다섯 영역의 인증에는 영어 에이전트와 운영 지표 등 별도 근거가 필요하다. [제품 품질 합격 기준](2026-11-21-rag-quality-harness-plan.md)
- `make rag-quality-local`은 평가가 끝나면 다음 개선 후보 하나를 요청한다. 모델은 개발 A·B의 같은 실패 원인과 성공 반례를 읽는다. 어떤 조건에서 무엇을 바꿀지, 어떤 결과가 나오면 아이디어를 기각할지 제안하고 실제 문서 구절을 붙인다. 제안은 `proposal.json`에 저장한다. 이미 측정한 결과로 제안만 다시 생성할 때는 아래 명령과 새 출력 파일명을 쓴다.

```sh
uv run python scripts/rag_growth_propose.py --panels "$PANELS" --run-dir "$RUN_DIR" \
  --model-file "$MODEL_FILE" --port 18759 --output "$RUN_DIR/proposal-review.json"
```

평가 명령의 종료 코드 0은 해당 단계 통과, 1은 채택 기준 미달, 2는 잘못된 입력 또는 불완전한 실행이다. Make를 통해 실행하면 하위 명령 실패는 Make의 종료 코드로 변환되므로 자동화에서는 `round.json`의 `decision`을 읽거나 Python 진입점을 직접 호출한다. 제안기의 종료 코드 1은 근거를 갖춘 제안이 생성되지 않았음을 뜻한다.
