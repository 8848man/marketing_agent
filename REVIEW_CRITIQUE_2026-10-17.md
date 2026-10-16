# 프로젝트 문서·아키텍처·보안 비판 검토

작성일: 2026-10-17 (Asia/Seoul)  
대상: `D:/projects/샘플_폴더/샘플프로젝트/marketing_agent`  
범위: 정적 읽기 검토. 프로그램 실행, 실제 키·`config.yaml`·`data/`·`drafts/` 내용 확인, 네트워크 호출, 게시 시험은 하지 않았다. 심각도는 제안 우선순위이며 악용 재현 판정은 아니다.

## 1. 판단 기준과 현재 강점

이 제품의 외부 원요구사항은 `C:/Users/LG/Downloads/track-2-marketing-agent (1).pdf`로 선언돼 있다. 프로젝트 안에서 추적 가능한 요구사항 원본은 [`docs/track2-agent/spec.md`](docs/track2-agent/spec.md), 문서 탐색·ID 원본은 [`.ucompany/sdd/00_index.md`](.ucompany/sdd/00_index.md), 기계 색인은 [`.ucompany/sdd/graph.json`](.ucompany/sdd/graph.json)이다. 이 관계를 문서 전반에 일관되게 적용해야 한다. 외부 PDF의 실제 내용과 프로젝트 명세의 일치 여부는 이번 검토에서 재대조하지 않았다.

좋은 방어도 이미 있다. 대시보드는 루프백 바인딩, POST의 Host·Origin·세션 토큰 검사, 게시 직전 RSS 재조회, 승인 초안 재검증, SQLite 예약과 결과 불명확 시 재시도 보류를 갖는다([`dashboard.py`](src/marketing_agent/dashboard.py), [`posting_service.py`](src/marketing_agent/posting_service.py), [`storage.py`](src/marketing_agent/storage.py)). AI 호출은 고정 제공사 호스트와 리다이렉트 차단, 응답 크기 제한, 공통 JSON 인터페이스를 사용한다([`ai_client.py`](src/marketing_agent/ai_client.py)). 아래 지적은 이 방어를 무효라고 단정하지 않고 남은 경계를 다룬다.

## 2. 우선순위별 발견

| ID / 우선순위 | 근거와 문제 | 영향·조건 | 제안 |
| --- | --- | --- | --- |
| SEC-01 / 높음 | [`dashboard.py:1361-1438`](src/marketing_agent/dashboard.py#L1361-L1438)의 `/api/videos`, `/api/videos/<id>/draft`, `/captures/<file>` GET에는 세션 토큰 확인이 없다. `/` 자체가 토큰을 HTML에 넣어 모든 루프백 클라이언트에 준다(`:1364-1367`). POST 검사는 존재하지만 로컬 사용자 인증은 아니다. | 같은 PC의 다른 프로세스가 루프백에 접근하면 영상·초안·캡처와 토큰을 읽고, Origin 헤더를 만들어 POST를 보낼 수 있다. 원격 웹사이트에서 곧바로 읽힌다는 주장은 아니다. | 로컬 위협 모델을 명시하고, 민감 GET에 인증을 적용한다. 다른 로컬 프로세스까지 막아야 한다면 포트 토큰만으로는 부족하므로 OS 권한·IPC 또는 사용자 승인 경계를 설계한다. |
| SEC-02 / 높음 | [`__main__.py:130-155`](src/marketing_agent/__main__.py#L130-L155)에서 인자 없는 레거시 CLI가 `run_cycle`로 들어간다. [`pipeline.py:161-174`](src/marketing_agent/pipeline.py#L161-L174)는 `safe`가 거짓이고 소유 검사 통과 시 `submit_comment`를 호출한다. 대시보드의 명시적 클릭 가드는 이 경로에 적용되지 않는다. | 소유 허용 목록과 키·브라우저가 준비된 환경에서 주기 실행이 별도 게시 경로가 될 수 있다. 현재 사용자의 실제 설정과 실행 여부는 확인하지 않았다. PDF/헌법의 “게시 진입점은 버튼 하나”와 충돌한다. | 기본 CLI를 읽기 전용으로 만들거나 게시 경로를 공통 승인 게이트 뒤로 통합한다. 기존 자동 게시 동작이 필요한지 제품 결정을 먼저 기록한다. |
| SEC-03 / 높음 | [`pipeline.py:37-40`](src/marketing_agent/pipeline.py#L37-L40)는 YouTube Data API 키를 URL 쿼리에 넣고 `urlopen` 기본 리다이렉트를 사용한다. 대시보드의 [`captions.py:68-79`](src/marketing_agent/captions.py#L68-L79)는 리다이렉트를 차단하므로 같은 외부 호출에도 정책이 다르다. [`pipeline.py:57-58`](src/marketing_agent/pipeline.py#L57-L58)의 예외 문자열과 [`logging.py:10-15`](src/marketing_agent/logging.py#L10-L15)의 정규식은 `key=` 쿼리 값을 확실히 가린다는 보장이 없다. | 레거시 CLI에서 오류·리다이렉트 조건에 따라 키 노출 가능성을 검증해야 한다. 실제 유출은 확인하지 않았다. | 키를 헤더로 전달할 수 있는 API는 헤더를 쓰고, 쿼리가 불가피하면 리다이렉트 금지·URL 없는 오류 코드·키 마스킹 회귀 시험을 적용한다. |
| SEC-04 / 중간 | [`captions.py:104-125`](src/marketing_agent/captions.py#L104-L125)는 외부 자막·댓글을 AI `evidence`에 합치고 [`dashboard.py:867-879`](src/marketing_agent/dashboard.py#L867-L879)는 고정 지시와 함께 보낸다. [`drafts.py:32-53`](src/marketing_agent/drafts.py#L32-L53)의 규칙은 길이·문구·인용 포함을 확인하지만, 인용된 문구의 의미·맥락과 외부 댓글 속 지시문의 무시는 증명하지 못한다. | 공격적 자막·댓글이 초안 내용에 영향을 줄 수 있다. 사람 검토가 있어 자동 게시로 직결되지는 않는다. | 근거를 출처별·길이별로 제한하고 비신뢰 데이터임을 프롬프트에서 분리한다. 승인 UI에 원문·출처를 보여 주고 지시문 삽입 사례로 평가한다. |
| SEC-05 / 중간 | [`drafts.py:56-78`](src/marketing_agent/drafts.py#L56-L78)는 `latest.json`과 개별 초안을 읽을 때 파일 유형·크기·심볼릭 링크를 검사하지 않는다. 쓰기에서만 개별 경로의 심볼릭 링크를 막는다(`:81-99`). 설정·키 저장은 심볼릭 링크 검사와 원자 쓰기가 있으나 검사 후 교체 사이 경쟁 조건은 남는다([`dashboard.py:200-255`](src/marketing_agent/dashboard.py#L200-L255)). | 앱 폴더를 쓸 수 있는 별도 로컬 행위자가 있다면 의도 밖 파일 읽기·교체 가능성을 별도로 평가해야 한다. 동일 사용자 전체를 신뢰하는 모델이면 우선순위가 낮아진다. | 파일 경계의 위협 모델을 정하고 초안 크기·정규 파일·경로 제한을 통일한다. 비밀 파일 권한과 원자 교체 시험을 Windows/macOS에서 확인한다. |
| ARCH-01 / 높음 | [`dashboard.py`](src/marketing_agent/dashboard.py)가 1,699행에 설정·키 이전·프로필 관리·서비스 조립·HTML/JS·HTTP 라우팅을 함께 담는다. UI의 이벤트와 서버 분기가 직접 맞물려 변경 영향 범위를 파악하기 어렵다. | 보안 검사 누락과 기능 변경 회귀 가능성이 커진다. 실제 결함률은 측정하지 않았다. | HTTP 인증/입력 검증, 애플리케이션 서비스, 설정·비밀 저장, UI 자산을 경계별 모듈로 나누고 공개 계약을 고정한다. |
| ARCH-02 / 높음 | 대시보드 RSS·승인·게시(`posting_service.py`)와 키워드 검색·분류·작성·CDP 게시(`pipeline.py`, `writer.py`, `poster.py:401-611`)가 병존한다. [`dashboard_contracts.py:50-55`](src/marketing_agent/dashboard_contracts.py#L50-L55)의 `DashboardService`는 화면 필수 세 메서드만 규정해 설정·AI·프로필 기능은 HTTP의 `hasattr` 분기에 의존한다. | 보안 정책, 제공사 설정, 오류 코드가 흐름별로 갈라질 수 있다. | 제품 범위를 결정한 뒤 레거시 CLI를 격리/제거하거나 동일 도메인 정책을 공유한다. 화면 서비스의 별도 명시적 인터페이스를 정의한다. |
| AI-01 / 중간 | [`ai_client.py:11-12`](src/marketing_agent/ai_client.py#L11-L12)의 `AIClient.complete_json`과 팩터리 덕분에 네 제공사 선택은 가능하다. 그러나 제공사 목록·기본 모델·키 변수는 코드 상수(`:15-20`), UI 옵션은 `dashboard.py`, 키 파일은 `DashboardSettings`, 프롬프트는 `dashboard.py:867-877`와 `writer.py`에 흩어져 있다. | 기존 네 곳의 전환은 가능하지만 새 제공사 추가·프롬프트 교체에는 여러 파일 변경이 필요하다. | 제공사 등록 정보와 `DraftGenerator`/`PromptPolicy` 계약을 정의하고 설정 UI가 등록 정보에서 선택지를 만든다. |
| AI-02 / 중간 | OpenAI 요청에는 `store=False`가 있으나 같은 `ResponsesClient`의 xAI 요청에는 없다([`ai_client.py:190-224`](src/marketing_agent/ai_client.py#L190-L224)). Gemini·Claude에도 같은 보존 옵션을 표현하는 공통 계약은 없다. 스키마·오류·토큰 예산도 어댑터별이다. | 제공사 교체가 동일한 데이터 보존·출력 품질 정책을 보장하지 않는다. 각 제공사의 실제 보존 정책은 이번 정적 검토로 판단하지 않았다. | 제공사별 데이터 처리·기능 지원 표를 작성하고, 공통 계약의 필수/선택 역량과 사용 불가 시 동작을 명시한다. |
| DOC-01 / 높음 | [`spec.md:3`](docs/track2-agent/spec.md#L3), [`constitution.md:11`](.ucompany/sdd/constitution.md#L11)은 사용자 PC의 Downloads PDF를 기준으로 든다. [`source-diff.md`](docs/track2-agent/source-diff.md)는 외부 MD와 PDF를 비교한다. 실제 PDF가 이 PC에 존재해도 프로젝트 내부에 버전·해시·취득일·보존 위치가 없다. | 다른 PC에서 요구사항 기원을 재현하거나 개정 이력을 검증하기 어렵다. | PDF의 권위와 프로젝트 내 `spec.md`의 관리 역할을 구분해 선언하고, 원문 보존 여부·버전·해시·변경 승인 절차를 정한다. |
| DOC-02 / 높음 | [`source-diff.md:18`](docs/track2-agent/source-diff.md#L18)은 현재 앱에 대시보드가 없다고 적고, [`reuse-audit.md:34`](docs/track2-agent/reuse-audit.md#L34)와 [`validation-protocol.md:57`](docs/track2-agent/validation-protocol.md#L57)은 70개 시험을 현재 기준처럼 기록한다. [`plan.md:97`](docs/track2-agent/plan.md#L97)은 103개·실 RSS 증거 없음, [`feature.md:24`](.ucompany/sdd/features/track2-dashboard/feature.md#L24)은 108개, [`README.md`](README.md)는 145개라고 한다. | 이력과 현재 판정이 섞여 수락 상태를 오판할 수 있다. | 과거 기록에는 `작성 당시` 표식을 붙이고 최신 상태는 한 상태 요약/증거 표에서만 관리한다. 이전 결정을 지우지 말고 superseded 링크를 둔다. |
| DOC-03 / 중간 | [`config.example.yaml`](config.example.yaml)은 키워드·조회수·CDP URL·`allowed_videos`가 포함된 구형 CLI 전체 설정이고, 대시보드는 주로 `profiles/channels/comment/limits`만 검증한다([`dashboard.py:305-329`](src/marketing_agent/dashboard.py#L305-L329)). README는 기본 대시보드를 설명한다. `.env.example`은 다섯 빈 변수로 실제 키 저장 코드와 대체로 맞지만 README만으로 환경변수 우선순위와 JSON 인용 저장 형식이 드러나지 않는다. | 예시를 복사한 사용자가 어떤 필드가 제품에 적용되는지 혼동한다. 실제 `config.yaml` 내용은 열지 않아 값 비교 판정은 하지 않았다. | 예시 파일의 적용 대상·필수성·기본값·민감도·지원 플랫폼을 필드별로 명시하고, 실제 로더/저장기와 구조 비교를 자동화한다. |
| DOC-04 / 중간 | [`plan.md:22-24`](docs/track2-agent/plan.md#L22-L24), [`tasks.md`](docs/track2-agent/tasks.md), [`spec.md`](docs/track2-agent/spec.md)에 표준 Chrome 프로필 연결·수동 이메일·앱 데이터 `.env`·Google 로그인 후 자동 확인 등 뒤에 교체된 단계가 현재형으로 남는다. [`00_index.md`](.ucompany/sdd/00_index.md)는 긴 날짜별 로그까지 포함해 색인과 인계의 역할이 겹친다. | 실제 지원 흐름과 향후 작업 범위가 불명확하다. | 현재 요구사항/결정/이력/증거를 분리하고 각 대체 단계의 효력 종료를 표시한다. 색인은 짧은 링크·우선순위만 둔다. |

## 3. 검증 공백과 해석 주의

- 이 검토는 코드·문서 정적 확인이다. 보안 악용, 제공사 라이브 호출, Windows/macOS 실기기 동작, PDF 원문 대조, 기존 테스트 실행은 수행하지 않았다.
- SHA-256 승인 해시는 로컬 초안의 변경 탐지 수단이다([`drafts.py:25-29`](src/marketing_agent/drafts.py#L25-L29)). 신뢰할 수 없는 로컬 사용자를 인증하는 서명으로 해석해서는 안 된다.
- README가 밝힌 Google 로그인 도메인·외부 프로필 옵션과 심사 안전 규칙의 충돌은 정책 해석 결정을 요한다([`README.md`](README.md), [`__main__.py:79-123`](src/marketing_agent/__main__.py#L79-L123)). 충돌이 해소됐다고 표시하면 안 된다.
- 라이브 AI에서 외부 자막·댓글·영상 설명이 어느 제공사로 얼마나 전송되는지, 보존 설정과 동의 범위는 별도 검토가 필요하다.

개선 순서와 문서 정리 산출물은 [개선 계획](IMPROVEMENT_PLAN_2026-10-17.md)에 적었다.
