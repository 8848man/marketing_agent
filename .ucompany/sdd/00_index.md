# marketing_agent — SDD 색인

현재 H 개선 적용 결과와 미완료 실환경 수락은 [IMPLEMENTATION_STATUS_2026-10-17.md](../../IMPLEMENTATION_STATUS_2026-10-17.md)에 기록한다. 비판·계획 대비 전체 공백은 [REMEDIATION_GAP_AUDIT_2026-10-17.md](../../REMEDIATION_GAP_AUDIT_2026-10-17.md)를 따른다. H01~H05와 H07~H10은 로컬 자동 시험을 통과했고 H06은 남아 있다.

현재 요구사항 출처와 권위는 [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md)에 고정한다. 2026-10-17 H 개선은 [비판 검토](../../REVIEW_CRITIQUE_2026-10-17.md) → [개선 계획](../../IMPROVEMENT_PLAN_2026-10-17.md) → `docs/track2-agent`의 H 작업 순서로 추적한다. 아래 날짜별 서술은 당시 이력이며 현행 수락 판정이 아니다.

2026-10-17부터 이 폴더와 `docs/track2-agent`가 제품 SDD의 원본이다. 상위 샘플프로젝트 경로를 참조하지 않는다. Windows 자동 회귀는 통과했으며 macOS 실기기 설치·계정 확인·게시 검수는 남아 있다.

2026-10-17 U40 감사: README의 안전 규칙 표와 PROCESS 제작 노트가 현재 판정의 진입점이다. `marketing_agent/`를 대시보드 폴더로 해석하므로 앱 루트의 설정·초안 파일은 그 폴더 내부다. Google 로그인 URL과 외부 프로필 옵션 등 남은 경계는 검토가 필요하다.

이 폴더는 U 컴퍼니 SDD v0 구조다. 이 색인이 ID·관계 어휘·읽는 순서의 원본이고, `graph.json`은 같은 내용을 기계가 읽도록 옮긴 파생 색인이다. 둘이 다르면 이 파일이 이긴다.

## 읽는 순서

1. `graph.json`의 `focus`인 `FEAT-TRACK2` 기능 문서를 연다.
2. 기능에 연결된 `DOC-TRACK2` 작업 목록의 미완료 체크박스와 현재 우선순위를 확인한다.
3. 작업과 연결된 요구사항·계획·검증 절차 및 필요한 코드만 연다.
4. 작업 후 `tasks.md` 체크박스와 이 색인, `graph.json`, `handoff.md`를 갱신한다.

## 노드

| ID | 종류 | 파일 | 소유하는 사실 |
| --- | --- | --- | --- |
| CON-1 | constitution | [constitution.md](constitution.md) | 프로젝트 원칙, 금지사항, 기술 스택 |
| FEAT-TRACK2 | feature | [feature.md](features/track2-dashboard/feature.md) | Track 2 목표, 현재 판정, 다음 증거 |
| REQ-TRACK2 | requirement | [spec.md](../../docs/track2-agent/spec.md) | PDF 기반 R/B 요구사항 |
| PLAN-TRACK2 | plan | [plan.md](../../docs/track2-agent/plan.md) | 구현 방침과 수락 관문 |
| DOC-TRACK2 | task | [tasks.md](../../docs/track2-agent/tasks.md) | T01~T12의 미완료 수락 작업 |
| VAL-TRACK2 | validation | [validation-protocol.md](../../docs/track2-agent/validation-protocol.md) | G1~G3 및 수락 증거 절차 |
| CODE-TRACK2 | code | [dashboard.py](../../src/marketing_agent/dashboard.py) | 제품의 로컬 HTTP 진입점 |
| CODE-RSS | code | [rss_feed.py](../../src/marketing_agent/rss_feed.py) | RSS 파싱·영상 소속 재조회 |
| CODE-DRAFT | code | [drafts.py](../../src/marketing_agent/drafts.py) | 초안 저장·사람 승인 해시 검증 |
| CODE-TRACK2-UI | code | [dashboard_ui.py](../../src/marketing_agent/dashboard_ui.py) | 3단계 화면과 상태 안내 |
| CODE-AI | code | [ai_client.py](../../src/marketing_agent/ai_client.py) | 제공사별 공통 JSON 호출 인터페이스 |
| DOC-PRODUCT | document | [SDD.md](../../SDD.md) | 제품 폴더의 SDD 안내 |
| DOC-ORIGIN | document | [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md) | 외부 PDF 판본과 내부 문서 권위 |

## 관계 어휘

| 관계 | 방향 | 의미 |
| --- | --- | --- |
| `governed_by` | 기능 → 헌법 | 기능이 따르는 원칙 |
| `has_requirement` | 기능 → 요구사항 | 기능이 만족할 요구사항 |
| `planned_by` | 기능 → 계획 | 기능의 구현 방침 |
| `has_task` | 기능 → 작업 | 기능의 실행 작업 목록 |
| `implements` | 작업 → 요구사항 | 작업이 구현하는 요구사항 |
| `decided_by` | 계획 → 결정 | 계획이 근거로 삼는 결정 기록 |
| `touches` | 작업 → 코드 | 작업이 바꾸는 코드 |
| `validated_by` | 작업 → 검증 | 작업의 수락 근거 |
| `documented_by` | 기능 → 안내 | 제품 폴더 진입 문서 |

2026-10-16 U12 앱 전용 프로필: 사용자 승인으로 일반 기본 Chrome 프로필 대신 앱의 data/dashboard/chrome-profile-youtube1/Default를 준비·연결하는 버튼과 localhost 설정 경계를 추가했다. Windows Chrome 150/Playwright 1.64에서 빈 비표준 임시 프로필의 persistent context 생성은 성공했다. 실제 앱 전용 Chrome 로그인 창과 Default 폴더 생성·설정 연결을 확인했고 전체 pytest 122개, 생성 JS 문법 검사가 통과했다. Google/YouTube 로그인 완료, 영상 탐색·댓글 입력·게시, Mac 수락은 아직 미검증이다.

2026-10-16 U13 만료 세션 안내: 이전 대시보드 탭의 세션 토큰이 서버 재시작으로 무효화되어 프로필 준비·저장 POST가 403으로 거부됐다. 새로고침 후 정상 연결을 확인했고 UI에 새로고침 안내 및 앱 전용 프로필 표시를 추가했다. 전체 pytest 122개 통과.

2026-10-16 U14 전용 로그인 창 점유: 앱이 연 로그인 Chrome 프로세스가 살아 있으면 `PROFILE_LOCKED`로 게시 전 차단하고 창 종료 후 재선택을 안내한다. 미확인 실행 실패는 `BROWSER_LAUNCH_FAILED`와 재시도 안내를 유지한다. Windows 전체 pytest 123개 통과. 전용 프로필 단독 실행과 YouTube HTTP 200·계정 버튼 표시를 확인했으나 댓글 입력·공개 게시 성공은 아직 미검증이다.

2026-10-16 U12/U15 실제 게시 수락: 사용자가 영상 `QXmBHgPqEUE`와 승인 문안의 공개 게시를 명시 승인했다. Windows 앱 전용 `chrome-profile-youtube1/Default`로 Chrome·YouTube 탐색·한국어 댓글 입력창·한 글자씩 입력·게시 클릭·작성자/정확한 문안 화면 확인을 통과했다. 대시보드 예약 기록은 `POSTED`, 검증 시각 2026-10-15T22:08:50Z(한국 시간 2026-10-16 07:08:50)다. 앞선 `YOUTUBE_NAVIGATION_FAILED`는 숨겨진 참여 패널과 영상 댓글 영역의 중복 `ytd-comments` 선택자로 인한 strict mode 오류였고, 표시되는 `ytd-comments#comments`로 수정했다. 현재 댓글 작성자 링크는 입력창에 없어서 계정 메뉴의 내 채널 공개 링크로 확인했다. 전체 pytest 124개 통과. Mac 심사 환경의 G2는 별도 미검증이다.

## 새 기능을 추가할 때

현재 `focus`는 `FEAT-TRACK2`다. 기존 PDF 기반 `spec.md`·`plan.md`·`tasks.md`를 원본으로 유지하고 제품 폴더의 `SDD.md`에서 연결한다. 2026-10-15 기준 Windows의 대시보드·옵션 메뉴·채널/AI API 관리 다이얼로그·오프라인 데모와 회귀 시험 108개, G3 거부 요청 시험을 확인했다. `R-SETTINGS-UI-01`과 `R-AI-SETTINGS-01`은 각각 구현 전에 명세했다. 네 제공사 모의 호출과 AI 키 비노출/요청 경계는 시험했지만 실 RSS 성공·실 AI 키 호출·Mac 확인은 아직 없다. T01~T12의 PDF 수락 체크박스는 열려 있다. **다음 우선순위:** G1 실제 5채널 RSS 및 게시 직전 재조회 증거 → 최신 영상별 사람 승인 초안 → G2 Mac 프로필·한국어 댓글 화면 → 본인 테스트 영상 실게시·시연. 실증 전에는 기능을 완료로 표시하지 않는다.

같은 날짜에 벤큐베이터 UX 원칙을 참고해 현재 단계 강조·상태별 안내·반응형/접근성 스타일을 UI에 반영했다. 생성 JS 구문 검사와 오프라인 데모 3단계 및 320/390/1440px 가로 넘침을 브라우저에서 확인했다. U01의 키보드·스크린리더·모션 감소·실제 RSS 오류 화면 점검은 남았다. 체험형 튜토리얼은 `spec.md`의 추후 요구사항(U02)으로만 기록했으며 현재 앱에는 없다.

2026-10-15 실제 5채널 RSS의 상단 `yt:channelId`가 `UC`를 생략하고 엔트리는 전체 ID를 반환하는 것을 확인했다. 파서와 명세를 수정해 다섯 피드의 각 15개 영상을 읽었으며 Windows 회귀 108개가 통과했다. 연결 테스트 UI의 재확인, 게시 직전 재조회, Mac 수락은 계속 미완료다.

같은 날짜에 선택 영상의 명시적 AI 초안 생성과 사람 승인 흐름(B03), 영상 목록 내부 스크롤(U05)을 명세→계획→작업 순으로 추가했다. AI 생성은 저장된 키가 있는 실제 모드에서만 명시적 클릭으로 실행하고, 생성본은 미승인으로 저장된다. 사람 검토·서버 재검증·승인 해시가 있어야 게시 후보가 된다. Windows localhost에서 실제 75개 목록, `DRAFT_MISSING` 선택 후 `AI 초안 만들기` 표시, 목록 내부 스크롤을 확인했고 전체 pytest 111개가 통과했다. 실제 AI 호출과 자막·인기 댓글 근거, Mac/실게시 검증은 미완료다.

Gemini의 실제 초안 생성에서 일반 문장이 와 `AI_RESPONSE_INVALID`가 발생한 것을 확인했다. 이후 B03의 공통 응답 계약을 `worry_summary`·`cited_detail`·`comment` 세 필드로 고정했다. OpenAI·xAI는 strict JSON Schema, Gemini는 JSON 모드·응답 스키마, Claude는 강제 도구 입력 스키마로 같은 계약을 요청하고 서버가 정확한 세 필드와 비어 있지 않은 값을 다시 확인한다. 제공사별 모의 요청 형식과 잘못된 생성 결과의 저장 차단을 포함한 Windows 회귀 113개가 통과했다. 실제 키 재호출 결과는 아직 사용자 확인이 필요하다.

같은 날짜에 PDF의 선택·게시 상세 요구사항을 다시 대조했다. 새 AI 초안은 자막을 우선 사용하고, 자막이 없으면 RSS 제목·설명을 사용하며, `YOUTUBE_API_KEY`가 있는 경우에만 공개 인기 댓글을 추가한다. 근거 출처는 초안 화면·저장 레코드에 남기고 근거 밖 인용은 승인에서 막는다. 기존 visible Chrome persistent profile·글자별 입력·내 댓글 확인·이벤트 폴링 경로를 확인해 단계 표기를 한국어로 보완하고 실패 캡처를 최종 결과에도 연결했다. 모의 근거 수집과 전체 회귀 114개가 통과했다. 실제 YouTube Data API·자막, Mac 유튜브1 프로필/한국어 화면, 실게시 수락은 아직 없다.

`PROFILE_NOT_CONFIGURED`를 게시 실패로만 보이던 흐름도 보완했다. 승인 초안 선택 시 `Chrome 프로필 연결` 다이얼로그에서 사용자 데이터 폴더와 `Default`/`Profile N` 식별자를 로컬 `config.yaml`에 저장하고, 존재 검사 후 현재 게시기에 반영한다. 앱은 프로필 내부 파일·계정·쿠키를 읽지 않는다. 유효/잘못된 경로 검증을 포함한 Windows 회귀 115개가 통과했고 8770 대시보드를 재시작했다. 실제 Mac 유튜브1의 `chrome://version` 경로·로그인·잠금 수락은 남아 있다.

현재 Windows 환경에서는 `playwright` 패키지가 없어서 지정 프로필을 실제로 여는 단계에 도달할 수 없던 것을 확인하고 설치했다. 프로필 연결은 승인 초안이 없을 때도 ③ 패널에서 열 수 있도록 바꿨다. 사용자는 경로를 저장한 뒤 본인 테스트 영상에서만 실제 창 열기와 한국어 댓글 흐름을 검증해야 한다.

같은 날짜에 U07의 직접 경로 입력 흐름을 개선했다. 옵션 메뉴의 `Chrome 프로필 관리`와 프로필 미설정 상태의 `댓글 달기`가 같은 선택 다이얼로그를 연다. Windows/Mac 표준 Chrome 사용자 데이터 폴더에서 `Default`·`Profile N` **폴더 이름만** 나열하고, 선택 저장 뒤 승인 초안을 다시 확인해 실제 게시 조건으로 돌아간다. 계정·쿠키·세션 파일은 읽지 않는다. `/api/profile-options`는 localhost 세션 토큰이 있어야 하며, 유효 저장은 Chrome·RSS·AI·DB 예약을 일으키지 않는다. 전체 Windows 회귀 115개가 통과했고 최신 소스로 8770을 재시작했다. 실제 계정 로그인·프로필 잠금·한국어 YouTube 게시의 G2는 여전히 미완료다.

2026-10-16 Gemini 실호출에서 `generationConfig.responseSchema.additionalProperties`가 400으로 거부되는 것을 확인했다. Gemini 어댑터는 이 Generate Content 비지원 키를 전송 전 제거하고, 서버의 세 필드 응답 검증은 유지한다. 전체 Windows 회귀 115개가 통과했다. 이후 현재 활성 설정은 OpenAI `gpt-5.4-mini`이며 연결 검사는 `AI_AUTH_FAILED`다. 유효한 OpenAI 키/모델 권한을 저장하거나 Gemini 설정으로 되돌린 뒤 실제 초안 생성을 다시 확인해야 한다.

2026-10-16 화면 재시험에서 실제 RSS 75개를 불러오고 승인된 심리조각 영상을 선택했다. `latest.json`이 존재해 개별 승인 초안을 가리던 결함을 확인해, 묶음에 선택 영상이 없을 때만 `drafts/<video_id>.json`으로 대체 조회하도록 고쳤다. 승인 초안 표시와 댓글 버튼 활성화를 브라우저에서 확인했고 전체 pytest 118개가 통과했다. 현재 설정된 Chrome 프로필 때문에 다음 댓글 버튼 클릭은 실제 게시 경로가 될 수 있어 실행하지 않았다. Mac G2와 실게시 수락은 미완료다.

같은 날짜 Windows의 실제 게시 시작에서 Playwright 기본 인수가 설치된 Chrome에 `--no-sandbox`를 붙여 보안 경고·빈 탭을 띄우는 것을 확인했다. persistent 실행에서 이 기본 인수만 제외하고 프로필 인수는 유지했다. 모의 게시·프로필·대시보드 회귀 46개가 통과했고 8770을 재시작했다. 새 창의 실제 YouTube 탐색·로그인·게시 검증은 수행하지 않았으므로 G2와 실게시 수락은 미완료다.

새 기능은 `features/<기능>/feature.md`로 진입점을 만들고 요구사항·계획·작업 문서와 그래프 관계를 연결한다. Track 2는 이미 작성된 `docs/track2-agent/`를 원본으로 참조한다. 새 결정은 `decisions/ADR-####.md`에 남긴다.

2026-10-16 B03-A에서 Gemini 실제 초안의 `MAX_TOKENS` 잘림을 확인했다. Gemini 3은 낮은 생각 수준과 4096 토큰 상한을 요청하며, OpenAI·xAI·Claude는 512 출력 토큰 상한을 명시한다. 코드 펜스/설명문 속 단일 JSON도 복원하되 세 필드 계약 외 결과는 저장하지 않는다. Windows에서 실제 Gemini 초안 생성·사람 검토 화면과 39개 관련 회귀를 확인했다. 다른 제공사의 실키 및 Mac 수락은 미완료다.

2026-10-16 AI API 관리 모델 드롭다운에 추천 균형 모델과 경량 보조 모델을 추가하고 `추천` 표기를 넣었다. 직접 입력과 저장 모델 복원은 유지하며, 실제 모델 접근 권한은 연결 테스트로 확인한다. 관련 Windows 회귀 29개가 통과했다.


2026-10-16 persistent Chrome의 첫 `about:blank` 탭이 사용자가 보는 탭으로 남고 별도 탭에서만 영상 이동을 하던 결함을 확인했다. 첫 빈 탭을 재사용해 선택 영상 URL로 이동하도록 명세·계획·구현·모의 회귀를 갱신했다. 게시/입력/예약은 실행하지 않았고 게시·프로필·대시보드 관련 회귀 46개가 통과했다. 8770을 새 코드로 재시작했다. 실제 YouTube 탐색·로그인·한국어 댓글 화면 및 실게시 G2는 계속 미완료다.


2026-10-16 첨부된 Chrome 자동화 조사 지시에 따라 Windows Chrome 150/Python Playwright 1.64에서 기본 Chrome 사용자 데이터 루트와 `Profile 1`으로 독립 persistent context 탐색을 재현했다. 컨텍스트는 `page.goto()` 전에 `TargetClosedError`로 닫혔고, Chrome 136+ 기본 데이터 루트의 `remote-debugging-pipe` 차단 정책과 일치한다. 기본 루트는 이제 `DEFAULT_CHROME_USER_DATA_DIR_UNSUPPORTED`로 Chrome·게시 DB·입력 전에 차단한다. 관련 49개 회귀가 통과했다. 실제 YouTube 탐색 성공은 비표준 자동화 데이터 루트에서 사용자가 직접 최초 로그인하는 정책 결정을 받은 뒤에만 검증한다.

2026-10-16 U16 앱 전용 프로필 목록: 일반 Chrome 폴더 탐색을 제거하고 앱 전용 유튜브1~3만 목록으로 표시한다. 로그인 필요 시 같은 프로필의 수동 로그인 창과 명시적 재개를 제공한다. 상세 흐름과 남은 실환경 검증은 `R-APP-PROFILE-03`, U16 작업, 인계에 기록한다.

2026-10-16 U17 댓글 확인 창 유지·이메일 표시: ③ 댓글 버튼 옆 기본 꺼짐 토글과 프로필별 수동 이메일 입력을 추가하고 ③의 관리 버튼을 제거했다. 게시 성공에 한해 Playwright 연결을 작업 스레드에서 유지하며 새 게시를 막는다. Windows 사용자 범위 암호문만 `data/dashboard`에 저장한다. 전체 pytest 130개 및 생성 JS 문법 통과. 실제 Chrome 창 유지와 Mac 저장은 미검증이다.

2026-10-16 U18~U25 영상별 자동 배정 **기획만**: 공유 영상 카탈로그, 프로필별 페르소나·담당 초안/이력, 파랑/초록 영상 카드와 영속 라운드 로빈 배정을 `spec.md`에 정의했다. 사용자가 PDF의 “유튜브1~3 선택 또는 영상별 자동 배정” 중 **영상별 자동 배정**을 선택해, 앞선 프로필마다 같은 영상 댓글 1개 허용안은 폐기했다. 영상 ID 전역 댓글 1개·앱 전체 하루 10개를 유지한다. 계획·작업·검증 문서만 갱신했으며 제품 코드는 변경하지 않았고 모든 신규 수락 항목은 미완료다.

2026-10-16 U26~U28: 사용자 구현 요청을 단계 전환 근거로 `R-PROFILE-EMAIL-VERIFY-01`, `R-PROFILE-AUTO-UI-01`, `R-AI-ENV-01`을 스펙→계획→작업→코드 순으로 추가했다. 수동 이메일/프로필 선택 버튼을 제거하고, 담당 프로필 영속 순환 배정과 파랑/초록/기본 카드 상태를 연결했다. 기존 AI 키는 앱 데이터 `.env`로 이전했고 실제 YAML에 키 필드가 없음을 확인했다. 한국어 YouTube에서 계정 전환 메뉴의 Google 계정 헤더 이메일을 읽기 전용으로 확인했다. 모의 회귀 135개 통과. U26의 다중 프로필/HTTP 실환경 수락과 U27의 페르소나·공유 카탈로그 전체 수락은 남는다.

2026-10-16 U29 로그인 창 첫 화면: 이전 구현은 영상 ID 없이 `/api/profile/setup`을 호출해 `about:blank`를 열었고, 선택 영상도 `profileRequired` 조건을 만족할 때만 전달했다. UI는 선택 영상 또는 불러온 첫 허용 영상 ID를 필수로 전달하며 목록이 비면 빈 창 없이 안내한다. 서버는 로그인 준비용 영상이 불러온 허용 채널 또는 소유 검증 테스트 영상인지 재확인한다. 게시·AI·예약 호출 없이 관련 시험 3개와 생성 JS 문법 검사 통과. 실제 버튼 클릭의 시각 수락은 남는다.

2026-10-16 U30 직접 Google 로그인: 사용자 정정에 따라 이전 U29의 watch 페이지 선행 조건을 폐기했다. 앱 전용 Chrome 로그인 준비는 고정 `https://accounts.google.com/ServiceLogin`을 직접 열며 영상/RSS·계정 이메일 확인 기능과 분리한다. `GET /api/profile/setup`·임의 URL/영상 ID는 거부하고 localhost 토큰/Origin과 앱 전용 루트 경계를 유지한다. Google 로그인 URL은 실제 공식 로그인 화면으로 리다이렉트되는 것을 확인했다. 모의 설정/잠금 경계 시험 4개와 JS 구문 검사 통과. 실제 계정 로그인은 사용자가 직접 수행한다.

2026-10-16 U31 로그인 뒤 계정 확인: 별도 일반 Chrome 창은 이메일을 앱에 반환하지 않는다. 창 종료를 관찰해 허용 YouTube 영상의 현재 계정 메뉴에서 이메일을 읽기 전용으로 확인한다. 영상 선택·댓글 담당 배정 없이 각 앱 전용 프로필을 확인하며, 불러온 영상이 없으면 허용 채널 RSS를 조회하고 실패하면 기존 허용 채널의 `POSTED` 영상 한 개를 재사용한다. 영상 저장소/배정/게시를 바꾸지 않는다. Chrome 프로필 저장 파일·쿠키를 읽지 않고 확인값은 서버 메모리에만 보관한다. 모의 및 JavaScript 문법 검증 완료, 실제 창 종료 후 UI 표시 수락은 남는다.

2026-10-16 U32 루트 AI 환경 파일: `.env.example`에 YouTube 및 OpenAI/Gemini/Anthropic/xAI 키 이름을 명시하고 실제 키는 Git 제외 루트 `.env`에 둔다. 기존 `data/dashboard/.env`와 YAML 키는 무손실로 이전하며 AI 제공사 변경·키 삭제 때 다른 제공사 및 YouTube 키를 보존한다. 선택 제공사 키가 없으면 AI 호출 전 `AI_KEY_MISSING`으로 막는다. 전체 회귀 140개 통과.

2026-10-16 U33 초안·버튼·계정 선택 수정: `DRAFT_MISSING`은 정상 준비 안내로 표시하고 주요 비활성 버튼은 접근 가능한 토스트로 다음 단계를 설명한다. 키 누락 AI 초안 버튼과 미승인 게시 버튼의 비활성 클릭에서 외부/게시 호출 0회를 임시 Chrome DOM으로 확인했다. `현재 계정 확인`과 `로그인 창 열기`는 레이블별 분리 루트의 Google 계정 선택 화면으로 통일하고, 로그인 창 종료 후 자동 YouTube 확인을 제거했다. 기존 U31 자동 흐름은 이 사용자 정정으로 대체한다. 프로필2 버튼·창 종료에서 YouTube 요청 0회를 모의 Chrome DOM으로 확인했다. 전체 회귀 140개 통과. 실제 Google 계정 선택 화면은 사용자 환경 확인이 남는다.

2026-10-16 U34 YouTube 키 루트 연결: `YOUTUBE_API_KEY`가 루트 `.env`에 있어도 인기 댓글 조회가 프로세스 환경변수만 읽어 키 없음 안내를 내던 누락을 수정했다. 명시적 초안 생성 시 루트 값을 다시 읽고, 비어 있으면 프로세스 환경변수를 사용한다. 모의 댓글 요청·키 변경·AI 설정 저장 보존과 전체 회귀 141개가 통과했다. 실제 YouTube API 키 유효성과 해당 영상 댓글 제공 여부는 외부 호출 없이 판정하지 않았다.

2026-10-16 U35 채널명 관리와 U36 프로필 UX 계획: 채널 관리에 필수 채널명과 선택 채널 ID를 추가했다. ID가 없으면 명시적 연결 테스트에서 Data API 후보를 표시하고 사람 선택 뒤 RSS로 검증하며 이름·ID를 함께 저장한다. YAML 고급 설정 UI를 제거했고 전체 회귀 143개가 통과했다. 프로필은 현재 화면에서 이메일이 확인될 때만 로그인으로 판정하고, 명확한 로그아웃에서만 계정 선택으로 잇는 단일 확인 흐름을 스펙·계획으로 작성했으며 구현은 U36으로 남겼다.

2026-10-16 U35 정정/U36 구현/U37 동적 프로필: 채널 입력을 사용자 정정대로 ID 필수·이름 선택으로 바꾸고 이름 검색 API를 제거했다. 계정 확인은 허용 YouTube 화면의 이메일/로그인 링크로 로그인·로그아웃·확인 불가를 구분하며 로그아웃에서만 계정 선택을 연다. 별도 로그인 버튼은 제거했다. 고유 이름의 새 프로필은 무작위 내부 ID와 전용 루트를 사용하며 최대 20개, 목록은 3행 높이 스크롤이다. 전체 회귀 144개와 JS 문법이 통과했고 한국어 YouTube 세 상태 실환경 수락은 남는다.
