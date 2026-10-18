# 운명원 YouTube 댓글 대시보드 (TRACK 2)

내려받아 실행하면 내 컴퓨터에 대시보드(`http://127.0.0.1:8770/`)가 뜹니다. **① 영상 불러오기 → ② 영상 선택(고민 한 줄·댓글 초안 확인) → ③ 댓글 달기**를 차례로 누르면, 앱 전용 Chrome 프로필이 열리고 선택한 영상에 댓글을 한 글자씩 입력·게시한 뒤 내 댓글이 보이는지 확인합니다. **④ 실행 기록**에 어느 영상에 어느 프로필로 무슨 댓글을 달았는지, 성공/실패가 최신순으로 남습니다.

- 우리 채널 5개의 최신 영상 초안은 `drafts/`에 사람이 승인한 상태로 들어 있어 **AI 키 없이** 바로 쓸 수 있습니다.
- 게시는 사람이 ③을 눌렀을 때만, 우리 채널 5개(+ 등록한 본인 테스트 영상)에만, 영상당 1개·하루 10개까지 됩니다.

## 1. 설치·실행 (약 5분)

필요한 것: **Python 3.11 이상**, **Google Chrome**.

### macOS (Terminal)

```sh
python3 --version          # 3.11 미만이면: brew install python@3.12  후 아래 python3 → python3.12
cd /path/to/marketing_agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m marketing_agent dashboard --port 8770
```

### Windows (PowerShell)

```powershell
cd <marketing_agent 폴더>
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m marketing_agent dashboard --port 8770
```

브라우저로 `http://127.0.0.1:8770/`을 엽니다. 브라우저 자동화 패키지(Playwright)는 위 설치 명령에 포함되며, 브라우저는 설치된 Google Chrome을 사용합니다(별도 브라우저 내려받기 없음).

## 2. 처음 한 번: 유튜브1 프로필 로그인 (약 1분)

1. 대시보드 오른쪽 위 **옵션 → Chrome 프로필 관리**에서 `유튜브1`의 **현재 계정 확인**을 누릅니다.
2. 로그아웃 상태면 우리 채널 영상 페이지가 앱 전용 Chrome 창으로 열립니다. 오른쪽 위 **로그인**을 **직접** 눌러 유튜브1 계정으로 로그인하고 창을 닫습니다.
3. 다시 **현재 계정 확인** → `로그인됨`이 보이면 끝입니다. `유튜브2`·`유튜브3`은 선택이며, 로그인이 확인된 프로필이 있으면 새 영상이 그 프로필들에 돌아가며 배정됩니다(확인된 프로필이 없으면 모두 유튜브1).

**왜 평소 쓰는 Chrome 프로필을 바로 쓰지 않나요?** Chrome(136 이후)은 평소 쓰는 기본 데이터 폴더의 자동 제어를 막습니다. 과제 안내대로 프로필 폴더를 지정해 여는 방식(`--user-data-dir`)을 쓰며, 그 폴더는 이 앱 폴더 안의 `data/dashboard/chrome-profile-youtube1`~`3`입니다. 기존 프로필의 쿠키·로그인 정보를 복사하거나 읽지 않기 위해 처음 한 번만 직접 로그인합니다.

## 3. 사용법

오른쪽 위 **필수 설정 n/m** 버튼을 누르면 이 PC에 채널 ID, Chrome, 프로필 로그인, 승인 초안, AI·YouTube 키 등이 제대로 들어가 있는지 한눈에 보이고, **설정하기**로 해당 입력칸에 바로 이동할 수 있습니다.

| 칸 | 하는 일 |
| --- | --- |
| ① 영상 불러오기 | 우리 채널 5개의 최신 영상을 썸네일·제목·채널·올린 날짜로 보여줍니다(API 키 불필요, YouTube RSS). |
| ② 영상 선택 | 고민 한 줄과 승인된 댓글 초안이 보입니다. 초안이 없는 새 영상은 AI 키가 있으면 **AI 초안 만들기**로 즉석 생성 → 검토 → 승인합니다. 생성 직후 2차 필터(글자 수·금지 규칙·다른 영상과 같은 표현 검사 후 AI 재작성)가 돌고, 저장된 초안은 **검토·승인 화면 열기**·**2차 필터 다시 적용**으로 다시 볼 수 있습니다. 필터는 **설정 → 댓글 생성 관리**에서 끌 수 있습니다(기본 켬). |
| ③ 댓글 달기 | 배정된 프로필의 Chrome이 열리고 댓글 창 → 한 글자씩 입력 → 게시 → 내 댓글 확인까지 화면에 보이게 진행합니다. 진행 상태와 실패 이유·캡처가 표시됩니다. |
| ④ 실행 기록 | 시간·영상·프로필·댓글·성공/실패, 오늘 게시 수/하루 상한. |

**AI 키(선택):** `.env.example`을 `.env`로 복사해 키를 넣거나, **옵션 → AI API 관리**에서 입력합니다(OpenAI·Gemini·Claude·xAI 중 하나). `YOUTUBE_API_KEY`는 인기 댓글을 초안 근거로 쓸 때만 필요합니다. 키는 화면·로그에 다시 표시되지 않습니다.

## 4. 프로그램이 하는 일과 하지 않는 일 (안전 규칙)

| 안전 규칙 | 지킨 방법 |
| --- | --- |
| 쿠키·비밀번호·브라우저 저장 정보를 읽거나 저장하지 않음 | 코드는 Chrome 프로필 내부 파일을 열지 않습니다. 프로필 폴더 경로만 Chrome에 넘기고, 로그인 상태는 Chrome이 스스로 관리합니다. 다른 Chrome에 붙는(CDP) 코드는 없습니다. |
| AI 키를 화면·로그·외부로 내보내지 않음 | 키는 이 폴더의 `.env`에만 저장되고, 선택한 AI 서비스의 인증 헤더로만 전송됩니다. 조회 API와 로그에는 값이 나오지 않습니다. |
| 우리 채널 영상(+본인 테스트 영상) 페이지만 열기 | 게시·계정 확인·로그인 창 모두 **우리 채널 영상의 watch 페이지만** 엽니다. 프로그램은 YouTube 홈이나 Google 계정 페이지를 열지 않으며, 로그인 화면으로의 이동은 사람이 YouTube의 "로그인" 버튼을 눌렀을 때만 일어납니다. |
| 댓글 외 동작(구독·좋아요·설정 변경) 금지 | 자동화는 댓글 입력·게시·내 댓글 확인만 합니다. 작성자 확인을 위해 계정 메뉴를 열어 내 채널 링크를 읽고 바로 닫을 수 있습니다(변경 없음). |
| YouTube·AI 서비스 외 전송 금지 | 외부 요청은 YouTube(RSS·영상 페이지·Data API)와 선택한 AI 서비스뿐입니다. |
| 대시보드 폴더 밖 파일 읽기 금지 | 설정·키·초안·프로필·기록이 모두 이 폴더 안(`config.yaml`, `.env`, `drafts/`, `data/dashboard/`)에 있고, 폴더 밖 경로를 받는 옵션은 없습니다. |

운영 규칙은 코드에서 강제합니다: 게시 직전 RSS로 영상이 허용 채널 소속인지 다시 확인, 영상당 댓글 1개(DB 고유 제약), 하루 상한 `limits.daily_max_comments`(기본 10), 모든 시도를 ④ 실행 기록에 저장. 결과가 불확실하면 자동 재시도하지 않습니다.

`python .ucompany/scripts/safety_scan.py --strict`로 위 규칙의 정적 검사를 직접 돌려 볼 수 있습니다.

## 부록 A. 개발·시연용 본인 테스트 영상 등록

우리 채널 영상에는 미리 게시하지 않습니다. 개발 중 게시 시험과 시연 영상은 **본인 채널의 테스트 영상**으로 합니다.

1. `config.yaml`(없으면 `config.example.yaml`을 복사)에 `dashboard_test_videos`를 채웁니다: `video_id`, `channel_id`(본인 채널), `title`(정확한 제목). 영상은 그 채널 RSS의 최신 15개 안에 있어야 합니다.
2. 본인 채널임을 보여 주는 캡처 등 증거 파일을 `data/dashboard/` 안에 둡니다.
3. 등록(게시하지 않음):
   `python -m marketing_agent dashboard --test-videos-config config.yaml --register-owned-test-video <VIDEO_ID> --ownership-evidence data/dashboard/<증거파일>`
4. 실행: `python -m marketing_agent dashboard --port 8770 --test-videos-config config.yaml`
5. 개발 PC에서는 `data/dashboard/DEV_BLOCK_OUR_CHANNELS`라는 빈 파일을 만들어 두면 우리 채널 영상 게시가 Chrome 실행 전에 차단됩니다(이 폴더는 Git에 올라가지 않습니다).

## 부록 B. 제출용 초안 일괄 생성 (제작자용)

```sh
python -m marketing_agent drafts --latest 3
```

설정 채널별 최신 3개 영상 중 승인 초안이 없는 것만 현재 AI 설정으로 생성해 **미승인**으로 `drafts/`에 저장합니다. 게시·Chrome 실행은 하지 않습니다. 생성 후 대시보드에서 검토·승인한 파일만 커밋합니다.

## 부록 C. 문제 해결

- `ZoneInfoNotFoundError ... Asia/Seoul`(Windows): 설치 명령을 다시 실행하면 `tzdata`가 설치됩니다.
- 8770 포트 사용 중: `--port 8771`처럼 바꿉니다.
- `PROFILE_LOCKED`: 같은 프로필의 Chrome 창(로그인 창 포함)을 닫고 다시 시도합니다.
- "연결이 만료" 오류: 서버를 다시 시작했다면 브라우저를 새로고침합니다.

## 부록 D. 검증과 설계 문서

```sh
python .ucompany/scripts/check_sdd.py              # 설계 문서 링크·그래프
python .ucompany/scripts/safety_scan.py --strict   # 안전 규칙 정적 검사
python -m pytest -q                                # 자동 회귀
```

GitHub Actions가 PR마다 macOS·Ubuntu에서 위 검사를 실행하고, `mac-smoke` 워크플로가 macOS에서 README 설치·대시보드 기동·Chrome으로 우리 채널 영상 페이지 열기를 확인합니다. 제작 노트는 [PROCESS.md](PROCESS.md), 설계 문서(SDD)는 [.ucompany/sdd/00_index.md](.ucompany/sdd/00_index.md), 작업 절차는 [workflow.md](.ucompany/sdd/workflow.md)에 있습니다. 원요구사항과 문서 권위는 [source-of-truth.md](.ucompany/sdd/source-of-truth.md), 설정 필드는 [예시 설정 계약](.ucompany/sdd/contracts/config-example.md)을 참고하세요.
