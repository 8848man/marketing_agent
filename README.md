# YouTube 댓글 대시보드

Python 3.11 이상과 Google Chrome이 있는 Windows·macOS에서 실행하는 로컬 앱이다. 설치와 실행은 **이 폴더**에서 한다. 사용자 데이터(`config.yaml`, `.env`, `data/`, `drafts/`)는 배포본에 포함하지 않는다. 각 PC에서 앱 전용 Chrome 프로필을 만들고 직접 Google 계정에 로그인한다. 다른 PC의 Chrome 프로필이나 로그인 정보는 복사하지 않는다.

원요구사항 PDF의 판본·해시와 SDD 문서 권위는 [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md)에 있다. 기본 실행은 `dashboard`이며, 이전 키워드 탐색 CLI는 초안·로그를 만드는 읽기 전용 보조 경로다. 보조 CLI는 공개 댓글을 게시하지 않는다.

대시보드 설정 예시는 [`config.example.yaml`](config.example.yaml), 보조 CLI 설정 예시는 [`config.legacy.example.yaml`](config.legacy.example.yaml)이다. 실제 설정 파일 `config.yaml`은 이 제품 폴더에만 두고 Git에서 제외한다.

각 예시 필드의 필수성·파서·사용처는 [예시 설정 계약](CONFIG_EXAMPLE_CONTRACT.md)에 정리했다.

비판 검토와 개선 계획의 항목별 적용·미완료 판정은 [개선 공백 감사](REMEDIATION_GAP_AUDIT_2026-10-17.md)를 따른다. 외부 요청 경계는 [외부 요청 정책](EXTERNAL_IO_POLICY.md), 보조 CLI와 과거 CDP 코드의 범위는 [레거시 코드 범위](LEGACY_SCOPE.md)에 기록한다.

## 설치·실행

Windows PowerShell:

```powershell
cd <압축을 푼 marketing_agent 폴더>
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m marketing_agent dashboard --port 8770
```

macOS Terminal:

```sh
cd /path/to/marketing_agent
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pip install playwright
.venv/bin/python -m marketing_agent dashboard --port 8770
```

브라우저에서 `http://127.0.0.1:8770/`을 연다. Chrome이 설치되어 있지 않으면 프로필 창을 열 수 없다. 앱은 앱 폴더의 `data/dashboard/chrome-profile-*`만 사용한다. Windows의 `.venv/Scripts`와 macOS의 `.venv/bin` 차이 외에 설정 파일 형식은 같다. Chrome 실제 실행과 한국어 YouTube 선택자는 macOS 실기기에서 별도 확인이 필요하다.

Windows에서 기존 가상환경으로 실행할 때 `ZoneInfoNotFoundError: No time zone found with key Asia/Seoul`이 나오면, 업데이트된 프로젝트 폴더에서 `.\.venv\Scripts\python.exe -m pip install -e ".[test]"`를 다시 실행한다. 새 의존성에 `tzdata`가 포함된다. 재설치 전 즉시 복구하려면 `.\.venv\Scripts\python.exe -m pip install tzdata`를 실행할 수 있다. 8770 포트를 다른 대시보드가 사용 중이면 다른 포트를 지정하거나 기존 서버를 종료한다.

## 설정과 사용

1. `.env.example`을 참고해 루트 `.env`를 만든다. AI 키는 선택 사항이며 **옵션 → AI API 관리**에서도 입력할 수 있다. AI 키가 없으면 AI 초안 생성은 실행되지 않는다. `YOUTUBE_API_KEY`는 인기 댓글 근거에만 필요하며, 유효하지 않으면 초안 안내 옆 **키 설정하기**에서 같은 다이얼로그를 열어 새 키를 저장한다. 키 값은 화면에 다시 표시하지 않는다.
2. **채널 관리**에서 `UC`로 시작하는 24자리 채널 ID를 5~20개 등록한다. 채널명은 선택 사항이며 연결 테스트로 RSS 이름을 채울 수 있다.
3. **Chrome 프로필 관리**에서 `유튜브1`, `유튜브2`, `유튜브3`을 각각 확인한다. 각 행의 **현재 계정 확인**을 누르고, 로그인이 필요하면 열린 **그 프로필의 전용 Chrome 창**에서 계정을 선택한다. 창을 정상 종료한 뒤 다시 **현재 계정 확인**을 누른다. 세 프로필은 서로 다른 `data/dashboard/chrome-profile-youtube1`~`youtube3` 폴더를 쓴다. 같은 Google 계정을 세 프로필에 자동 복사하거나 기존 Chrome의 기본 프로필을 가져오지 않는다. 실제 이메일이 YouTube 메뉴에 보이면 이메일을 표시한다. YouTube가 숨기면 `로그인 확인 · 이메일 비공개`로 표시한다. **계정 변경**은 해당 프로필의 계정 선택 창을 연다.
4. **영상 불러오기 → 초안 생성·검토·승인 → 댓글 달기** 순서로 진행한다. 실제 게시 여부는 화면과 캡처에서 확인한다.

## 프로그램의 동작과 심사 안전 규칙 감사

앱은 등록된 채널의 YouTube RSS로 영상을 불러오고, 자막 또는 제목·설명과 선택적인 인기 댓글을 근거로 AI 초안을 만든다. 사람이 초안을 검토·승인하고 **댓글 달기**를 누르면 앱 전용 Chrome에서 해당 영상의 댓글을 한 글자씩 입력·게시하고 화면에서 확인한다. 구독·좋아요·YouTube 설정 변경을 수행하는 코드는 없다. 실패 화면 캡처와 결과는 로컬 `data/dashboard`에 남긴다. 초안 생성만으로 댓글을 게시하지 않는다.

아래 평가는 코드의 **현재 상태**다. 심사 규칙을 문자 그대로 적용하면 **전체 통과가 아니므로 심사자 계정에서 실행 전 수정·재검토가 필요하다.**

대시보드는 영상·초안·실패 캡처 GET에 세션 토큰을 요구한다. 루트 화면은 같은 PC의 브라우저가 토큰을 받도록 열려 있으므로 이 토큰은 **다른 로컬 프로세스에 대한 사용자 인증이 아니다.** PC의 다른 사용자·프로세스를 신뢰하지 않는 환경이라면 OS 권한을 쓰는 별도 접근 제어가 필요하다.

| 규칙 | 현재 코드에서 확인한 사실 | 판정 |
| --- | --- | --- |
| 쿠키·비밀번호·브라우저 저장 정보 직접 읽기·저장 금지 | Python 코드가 Chrome 프로필 내부 파일을 직접 열거나 쿠키를 추출하는 경로는 확인되지 않았다. 다만 Playwright의 지속 프로필 Chrome이 로그인 데이터를 자체적으로 저장·사용한다. | 브라우저 자체의 저장까지 금지하는 해석이면 미충족 |
| AI 키 화면·로그·외부 유출 금지 | 키 입력은 비밀번호형이며 조회 API는 값을 돌려주지 않는다. 앱 루트 `.env`에 저장하고 선택한 AI 서비스의 인증 헤더로 전달한다. `YOUTUBE_API_KEY`는 YouTube Data API 요청에 사용한다. | AI 서비스로도 전송 금지라는 문자 그대로의 해석이면 미충족 |
| 우리 채널·본인 테스트 영상 페이지만 열기 | 댓글·계정 확인의 명시적 watch 이동은 허용 영상으로 제한한다. **계정 선택은 `accounts.google.com`과 `myaccount.google.com`을 연다.** | 미충족 |
| 댓글 외 구독·좋아요·설정 변경 금지 | 게시 자동화는 댓글 입력·게시·확인을 수행한다. 계정 선택 화면은 사람이 직접 조작한다. | 코드상 충족, 실제 브라우저 동작 검수 필요 |
| YouTube·AI 서비스 외 외부 전송 금지 | RSS·YouTube Data API·AI 제공사 외에 Google 로그인 화면 접속이 있다. | Google 계정 서비스를 별도 외부 대상이라 보면 미충족 |
| 대시보드 폴더 밖 파일 읽기 금지 | 여기서 대시보드 폴더를 배포 앱 루트 `marketing_agent/`로 해석한다. 기본 실행의 `.env`, `config.yaml`, `drafts/`, `data/dashboard/`는 모두 그 안에 있으며, 대시보드 CLI의 경로 인자는 앱 루트 밖을 거부한다. 다만 `--chrome-user-data-dir`로 외부 Chrome 프로필 경로를 지정하는 레거시 옵션은 별도 검토가 필요하다. | **기본 앱 파일 경로는 충족; 외부 프로필 옵션은 미확인** |

`marketing_agent/` 안의 `.env`·`config.yaml`·`drafts/`를 `data/dashboard/`로 옮길 필요는 없다. 남은 불일치는 Google 계정 선택 화면과 외부 프로필 옵션의 허용 범위, 지속 프로필과 AI 인증 방식의 해석이다. 이 기준을 확정하고 Windows·macOS 실제 실행을 검증하기 전에는 **안전 규칙 준수 완료**로 제출하지 않는다.

## 검증과 SDD

```sh
python -m pytest -q
```

2026-10-17 Windows 로컬 환경에서 자동 테스트 157개가 통과했다. 실제 `유튜브3`의 로그인 상태는 Windows에서 확인했다. 타인의 Windows PC와 macOS의 설치·Chrome 프로필·실제 댓글 게시까지 통과했다는 뜻은 아니다. 각 PC에서 위 설치, 대시보드 접속, 전용 프로필 로그인, 계정 확인, 허용된 테스트 영상의 게시 검수를 수행해야 한다.

SDD 문서의 ID·관계 원본은 [.ucompany/sdd/00_index.md](.ucompany/sdd/00_index.md), 관리되는 요구사항은 [docs/track2-agent/spec.md](docs/track2-agent/spec.md)에 있다. 작업 지침은 [AGENTS.md](AGENTS.md)를 따른다.
