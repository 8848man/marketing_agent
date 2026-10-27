# 운명원 YouTube 댓글 대시보드 (TRACK 2)

내려받아 실행하면 내 컴퓨터에 대시보드가 뜹니다(실행 창에 표시된 주소로 브라우저가 자동으로 열립니다). **① 영상 불러오기 → ② 영상 선택(고민 한 줄·댓글 초안 확인·승인) → ③ 댓글 달기**를 차례로 누르면, 앱 전용 Chrome 프로필이 열리고 선택한 영상에 댓글을 한 글자씩 입력·게시한 뒤 내 댓글이 보이는지 확인합니다. **④ 실행 기록**에 어느 영상에 어느 프로필로 무슨 댓글을 달았는지, 성공/실패가 최신순으로 남습니다.

> **심사자분께 — 실행 파일 하나면 됩니다.**
> 필요한 것은 **Python 3.11 이상**과 **Google Chrome**뿐입니다.
> - macOS: 저장소 폴더의 **`start-review.command`** 를 더블클릭합니다. (ZIP으로 받아 "확인되지 않은 개발자" 경고가 뜨면 파일을 **오른쪽 클릭 → 열기**, 또는 터미널에서 `bash start-review.command`)
> - Windows: **`start-review.bat`** 을 더블클릭합니다.
>
> 처음 한 번 1~3분간 필요한 패키지를 이 폴더 안(`.venv`)에 설치하고, 대시보드를 **심사 모드**로 띄운 뒤 브라우저를 엽니다. 실행 파일은 설치·실행만 하는 짧은 텍스트 스크립트라 내용을 먼저 열어 보실 수 있습니다([scripts/launch.sh](scripts/launch.sh), [scripts/launch.bat](scripts/launch.bat)).
> 심사 모드에서는 ① 영상 불러오기 후 목록 맨 위에 **'테스트용'** 뱃지가 붙은 영상이 하나 올라옵니다. AI 초안은 있지만 아직 승인·게시 전인 영상이라, ② 검토·승인 → ③ 댓글 달기 흐름을 처음부터 끝까지 해 볼 수 있습니다. 실제 우리 채널 영상이므로 게시하면 실제 댓글이 달립니다.

- `drafts/`에 채널별 최신 영상의 고민 한 줄·댓글 초안이 들어 있어 **AI 키 없이** 쓸 수 있습니다. 일부는 승인된 상태이고, 나머지는 ② 검토·승인 화면에서 문안을 읽고 승인하면 게시할 수 있습니다. 초안이 없는 새 영상은 AI 키를 넣으면 그 자리에서 만들 수 있습니다.
- 게시는 사람이 ③을 눌렀을 때만, 우리 채널 5개(+ 등록한 본인 테스트 영상)에만, 영상당 1개·하루 10개까지 됩니다.
- AI 도우미(Claude·ChatGPT 등)와 함께 설치하려면 그 도우미에게 [HOW_TO_SETTING.md](HOW_TO_SETTING.md)를 읽게 하세요. 필요한 값을 도우미가 차례로 물어봅니다.

## 1. 설치·실행

**가장 쉬운 방법:** 위의 실행 파일을 더블클릭합니다. 일반 모드(테스트용 뱃지 없음)는 `start.command`(macOS)·`start.bat`(Windows)입니다. 포트 8770이 쓰이고 있으면 8771~8779 중 빈 포트로 자동으로 뜹니다.

**직접 명령으로 실행하려면** (실행 파일이 하는 일과 같습니다):

### macOS (Terminal)

```sh
python3 --version          # 3.11 미만이면: brew install python@3.12  후 아래 python3 → python3.12
cd /path/to/marketing_agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m marketing_agent dashboard --port 8770 --review
```

### Windows (PowerShell)

```powershell
cd <marketing_agent 폴더>
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m marketing_agent dashboard --port 8770 --review
```

`--review`를 빼면 일반 모드입니다. 브라우저가 자동으로 열리지 않으면 실행 창에 표시된 `Dashboard: …/pair?code=…` 주소를 그대로 엽니다(`http://127.0.0.1:8770/`을 직접 열면 거부됩니다). 브라우저 자동화 패키지(Playwright)는 위 설치에 포함되며, 브라우저는 설치된 Google Chrome을 사용합니다(별도 브라우저 내려받기 없음).

## 2. 처음 한 번: 유튜브1 프로필 로그인 (약 1분)

1. 대시보드 오른쪽 위 **설정 → Chrome 프로필 관리**에서 `유튜브1`의 **현재 계정 확인**을 누릅니다.
2. 로그아웃 상태면 우리 채널 영상 페이지가 앱 전용 Chrome 창으로 열립니다. 오른쪽 위 **로그인**을 **직접** 눌러 유튜브1 계정으로 로그인하고 창을 닫습니다.
3. 다시 **현재 계정 확인** → `로그인됨`이 보이면 끝입니다. 어느 계정인지는 각 프로필의 **메모** 칸에 별칭(예: 운명원 마케팅 1호)을 적어 두고 대조합니다. 프로그램은 계정 이메일을 읽거나 저장하지 않으며, 메모에도 이메일 주소는 저장되지 않습니다. `유튜브2`·`유튜브3`은 선택이고 **유튜브1 확인 뒤에만** 설정할 수 있습니다. 처음에는 모든 영상이 유튜브1에 배정되고, 유튜브2·3의 로그인이 확인되면 아직 댓글을 달지 않은 영상이 확인된 프로필들에 돌아가며 다시 배정됩니다(이미 게시를 시도한 영상은 그대로). 확인 결과는 다시 실행해도 유지되며, 로그아웃이 확인되거나 그 프로필의 로그인 창을 다시 열면 배정에서 빠집니다. 같은 Google 계정을 두 프로필에 로그인했는지는 프로그램이 알 수 없으니 메모로 확인하세요.

**왜 평소 쓰는 Chrome 프로필을 바로 쓰지 않나요?** Chrome(136 이후)은 평소 쓰는 기본 데이터 폴더의 자동 제어를 막습니다. 과제 안내대로 프로필 폴더를 지정해 여는 방식(`--user-data-dir`)을 쓰며, 그 폴더는 이 앱 폴더 안의 `data/dashboard/chrome-profile-youtube1`~`3`입니다. 기존 프로필의 쿠키·로그인 정보를 복사하거나 읽지 않기 위해 처음 한 번만 직접 로그인합니다.

## 3. 사용법

오른쪽 위 **필수 설정 n/m** 버튼을 누르면 이 PC에 채널 ID, Chrome, 프로필 로그인, 승인 초안, AI·YouTube 키 등이 제대로 들어가 있는지 한눈에 보이고, **설정하기**로 해당 입력칸에 바로 이동할 수 있습니다.

| 칸 | 하는 일 |
| --- | --- |
| ① 영상 불러오기 | 우리 채널 5개의 최신 영상을 썸네일·제목·채널·올린 날짜로 보여줍니다(API 키 불필요, YouTube RSS). |
| ② 영상 선택 | 고민 한 줄과 댓글 초안이 보입니다. 승인 전 초안은 **검토·승인 화면 열기**에서 문안을 읽고(필요하면 고쳐) 검토자 이름과 함께 승인합니다. 초안이 없는 새 영상은 AI 키가 있으면 **AI 초안 만들기**로 즉석 생성 → 검토 → 승인합니다. 생성 직후 2차 필터(글자 수·금지 규칙·다른 영상과 같은 표현 검사 후 AI 재작성)가 돌고, 저장된 초안은 **검토·승인 화면 열기**·**2차 필터 다시 적용**으로 다시 볼 수 있습니다. 필터는 **설정 → 댓글 생성 관리**에서 끌 수 있습니다(기본 켬). |
| ③ 댓글 달기 | 배정된 프로필의 Chrome이 열리고 댓글 창 → 한 글자씩 입력 → 게시 → 내 댓글 확인까지 화면에 보이게 진행합니다. 진행 상태와 실패 이유·캡처가 표시됩니다. |
| ④ 실행 기록 | 시간·영상·프로필·댓글·성공/실패, 오늘 게시 수/하루 상한. |

**AI 키(선택):** `.env.example`을 `.env`로 복사해 키를 넣거나, **설정 → AI API 관리**에서 입력합니다(OpenAI·Gemini·Claude·xAI 중 하나). `YOUTUBE_API_KEY`는 인기 댓글을 초안 근거로 쓸 때만 필요합니다. 키는 화면·로그에 다시 표시되지 않습니다. Windows에서는 저장 시 암호화되어 `data/dashboard/`에 보관되고 `.env`에서 지워집니다.

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

## 다른 PC로 옮기거나 배포할 때

앱 폴더를 직접 압축해 옮기지 마세요. GitHub에서 내려받거나 `python scripts/package.py`로 만든 zip(`dist/`)을 쓰세요. 이유: 앱 폴더의 `data/`에 로그인된 Chrome 프로필(쿠키·로그인 정보)이 있기 때문입니다. 이 스크립트는 git이 추적하는 파일만 담고, 키·DB·프로필이 섞이면 zip을 만들지 않습니다. 받은 PC에서는 처음 한 번 직접 로그인합니다(2절).

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

설정 채널별 최신 3개 영상 중 승인 초안이 없는 것만 현재 AI 설정으로 생성해 **미승인**으로 `drafts/`에 저장합니다. 게시·Chrome 실행은 하지 않습니다. 현재 품질 검사를 통과한 초안만 커밋하며, 승인 전 초안은 심사자가 ② 검토·승인 화면에서 직접 승인합니다.

## 부록 C. 문제 해결

- 영상 목록에 "YouTube RSS 서버 오류(500)"처럼 나오면 YouTube 쪽 일시 장애입니다(브라우저로 RSS 주소를 열어도 같은 오류가 납니다). 장애 중에는 승인 초안이 있는 영상만 목록에 보이며, 게시 직전 확인도 실패하므로 댓글은 달리지 않습니다. 잠시 뒤 **영상 불러오기**를 다시 누르세요.
- `ZoneInfoNotFoundError ... Asia/Seoul`(Windows): 설치 명령을 다시 실행하면 `tzdata`가 설치됩니다.
- 8770 포트 사용 중: 실행 파일은 8771~8779로 자동으로 바꿉니다. 직접 실행할 때는 `--port 8771`처럼 바꿉니다.
- `PROFILE_LOCKED`: 같은 프로필의 Chrome 창(로그인 창 포함)을 닫고 다시 시도합니다.
- "연결이 만료" 오류: 서버를 다시 시작했다면 브라우저를 새로고침합니다.

## 부록 D. 사용한 오픈소스

이 저장소는 아래 오픈소스 패키지를 **설치해서 사용**합니다(소스를 복사해 넣지 않음). 각 패키지의 라이선스는 해당 프로젝트를 따릅니다.

| 패키지 | 용도 | 라이선스 | 출처 |
| --- | --- | --- | --- |
| Playwright for Python | 앱 전용 Chrome 프로필 실행, 댓글 입력·게시·확인 | Apache-2.0 | https://github.com/microsoft/playwright-python |
| PyYAML | `config.yaml` 읽기·쓰기 | MIT | https://github.com/yaml/pyyaml |
| tzdata (Windows만) | `Asia/Seoul` 시간대 데이터 | Apache-2.0 | https://github.com/python/tzdata |
| pytest (개발·검증용) | 자동 회귀 시험 | MIT | https://github.com/pytest-dev/pytest |
| youtube-transcript-api | 영상 자막을 초안 근거로 사용(선택) | MIT | https://github.com/jdepoix/youtube-transcript-api |

그 밖에 Python 표준 라이브러리만 씁니다. Google Chrome은 사용자가 설치한 브라우저를 그대로 쓰며 저장소에 포함하지 않습니다. 외부 서비스는 YouTube(RSS·영상 페이지·선택적 Data API)와 사용자가 고른 AI 서비스(OpenAI·Gemini·Claude·xAI 중 하나, 선택)뿐입니다.

## 부록 E. 검증과 설계 문서

```sh
python .ucompany/scripts/check_sdd.py              # 설계 문서 링크·그래프
python .ucompany/scripts/safety_scan.py --strict   # 안전 규칙 정적 검사
python -m pytest -q                                # 자동 회귀
```

GitHub Actions가 PR마다 macOS·Ubuntu에서 위 검사를 실행하고, `mac-smoke` 워크플로가 macOS에서 README 설치·대시보드 기동·Chrome으로 우리 채널 영상 페이지 열기를 확인합니다. 제작 노트는 [PROCESS.md](PROCESS.md), 설계 문서(SDD)는 [.ucompany/sdd/00_index.md](.ucompany/sdd/00_index.md), 작업 절차는 [workflow.md](.ucompany/sdd/workflow.md)에 있습니다. 원요구사항과 문서 권위는 [source-of-truth.md](.ucompany/sdd/source-of-truth.md), 설정 필드는 [예시 설정 계약](.ucompany/sdd/contracts/config-example.md)을 참고하세요.
