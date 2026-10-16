# AI 제공사 교체 계약

기준일: 2026-10-17. 이 문서는 저장소 코드의 계약을 설명하며 각 제공사의 현재 가격·정책·모델 접근권을 인증하지 않는다.

## 공통 계약

- 초안 생성은 [`AIClient.complete_json`](src/marketing_agent/ai_client.py)으로 `system`, `prompt`, 선택적 `response_schema`를 전달한다. 반환값은 JSON 객체다.
- 제공사별 어댑터는 인증·요청 형식·응답 파싱을 맡는다. 선택한 제공사와 모델, 키 변수, 화면 선택지는 `PROVIDER_DETAILS`와 등록 함수에서 나온다.
- 대시보드의 [`prompt_policy.py`](src/marketing_agent/prompt_policy.py)는 제공사와 별개로 시스템 지시, 입력 JSON, 응답 스키마, 버전(`draft-v2`)을 정의한다. 외부 자막·댓글은 지시가 아닌 비신뢰 근거로 취급한다.
- [`captions.py`](src/marketing_agent/captions.py)는 자막/제목·설명 최대 12,000자, 인기 댓글 최대 10개·각 500자로 AI에 보내는 양을 제한한다. 생성 결과는 즉시 게시되지 않고 [`drafts.py`](src/marketing_agent/drafts.py)의 품질 검사와 사람 승인이 필요하다.
- 제공사 추가는 신뢰된 코드에서 `register_ai_provider(name, label, default_model, key_env, presets, factory)`를 호출한다. 새 어댑터는 `complete_json` 계약과 실패 코드·비밀정보 비노출 시험을 통과해야 한다. 임의 사용자 입력으로 API 호스트를 등록하지 않는다.

## 현재 어댑터의 차이

| 제공사 | 요청 방식 | 구조화 응답 | 저장/보존 요청에 관한 코드상 사실 |
| --- | --- | --- | --- |
| OpenAI | Responses API | strict JSON Schema | 요청 본문에 `store: false`를 넣는다. |
| xAI | Responses 형태 | strict JSON Schema | `store` 값을 보내지 않는다. 실제 보존 정책은 별도 확인이 필요하다. |
| Gemini | Generate Content | 지원되는 응답 스키마로 변환 | 코드에 공통 보존 옵션이 없다. |
| Anthropic | Messages API | 강제 도구 입력 스키마 | 코드에 공통 보존 옵션이 없다. |

네 어댑터는 같은 초안 필드 계약을 받지만 모델 가용성, 스키마 해석, 토큰 계산, 보존 정책이 같다는 뜻은 아니다. 실키 호출과 개인정보/데이터 처리 조건은 제공사별로 확인한다. 초안 근거에는 외부 영상 자막·설명·공개 댓글이 포함될 수 있으므로 실제 제공사 전송 전에 사용 목적과 데이터 범위를 검토한다.
