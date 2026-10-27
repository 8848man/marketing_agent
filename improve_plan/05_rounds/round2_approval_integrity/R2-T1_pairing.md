## 작업 R2-T1: 페어링 주소로만 대시보드 페이지 발급 (IMP-31, H1)

### 1. 목표
세션 토큰이 담긴 대시보드 페이지(`GET /`)를 **페어링 쿠키가 있는 브라우저에만** 준다. 페어링 쿠키는 실행 시 콘솔에 출력·자동으로 열리는 `/pair?code=<코드>` 주소로만 받는다. 같은 PC의 다른 OS 사용자가 `http://127.0.0.1:<포트>/`를 요청해 토큰을 얻는 경로를 막는다.

### 2. 배경과 근거 [코드 확인]
- `dashboard.py` `create_server`(약 873행): `token = secrets.token_urlsafe(32)`, `do_GET`에서 `self.path == "/"`면 `_page(token, …)`를 조건 없이 반환.
- API는 `X-Session-Token` 헤더로 검사(`_session_ok` 등). 이 부분은 바꾸지 않는다.
- `run_dashboard`(약 1350행)가 `print(f"Dashboard: {url}")`(실행 파일이 이 줄을 읽음)와 `webbrowser.open(url)`.
- `.github/workflows/mac-smoke.yml`이 `curl http://127.0.0.1:8770/`의 200과 `launcher.log`의 `http://127.0.0.1:[0-9]*/` 주소를 사용.
- 위협 모델: ADR-0002. 같은 OS 사용자 프로세스는 범위 밖(수용), 다른 OS 사용자·원격 웹사이트는 막아야 함.

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 라운드 2 브랜치
- 좁은 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_dashboard.py tests/test_dashboard_posting.py tests/test_hardening.py`

### 4. 사양
1. `create_server`가 `pair_code = secrets.token_urlsafe(24)`를 만들고 서버 객체에 `server.pair_code`로 노출한다.
2. `GET /pair?code=<코드>`: Host 검사 통과 + `secrets.compare_digest(code, pair_code)`이면 `303` → `Location: /`, `Set-Cookie: ma_pair=<세션 토큰과 다른 별도 난수>; HttpOnly; SameSite=Strict; Path=/`. 코드가 틀리거나 없으면 `403` HTML(한국어: "대시보드를 실행한 창에 표시된 주소로 다시 여세요"). 코드는 프로세스가 끝날 때까지 여러 번 쓸 수 있다.
3. `GET /`: 유효한 `ma_pair` 쿠키(`compare_digest`)가 있을 때만 지금 페이지를 준다. 없으면 `403` HTML(같은 안내, 토큰·meta 태그 없음).
4. `run_dashboard`: 출력과 브라우저 열기 주소를 `http://127.0.0.1:<포트>/pair?code=<코드>`로 바꾼다. 출력 줄의 접두어 `Dashboard: `는 유지한다.
5. 응답 헤더(CSP 등)는 `/pair`·403 응답에도 지금과 같이 붙인다. `/pair`는 Referrer 누출을 막기 위해 기존 `Referrer-Policy: no-referrer` 유지.
6. mac-smoke: 첫 단계는 `dashboard.log`의 `Dashboard: ` 줄에서 주소를 읽어 `curl -c jar -b jar -L`로 페어링 후 페이지를 받는다. 실행 파일 단계도 `grep -o 'http://127.0.0.1:[0-9]*/pair?code=[A-Za-z0-9_-]*'`로 주소를 읽어 같은 방식으로 받는다.
7. README·HOW_TO_SETTING의 접속 주소 안내가 `http://127.0.0.1:8770/`를 직접 열라고 하면 "실행 창에 표시된 주소(자동으로 열림)"로 고친다.

### 5. 먼저 작성할 실패 테스트 (`tests/test_dashboard.py`)
| 테스트 | 기대 동작 |
| --- | --- |
| `test_page_requires_pairing_cookie` | 쿠키 없이 `GET /` → 403, 응답에 `session-token` 문자열 없음 |
| `test_pair_sets_cookie_and_page_has_token` | `GET /pair?code=<server.pair_code>` → 303, `Set-Cookie`에 `HttpOnly`·`SameSite=Strict`; 그 쿠키로 `GET /` → 200, meta 토큰 있음 |
| `test_pair_rejects_wrong_code` | 틀린 코드·코드 없음 → 403, `Set-Cookie` 없음 |
| `test_pair_checks_host` | 잘못된 Host로 `/pair` → 403 |
| `test_run_dashboard_prints_pair_url` | `run_dashboard(open_browser=False)`를 스레드로 띄워 출력(capsys 또는 stdout 대체)에 `Dashboard: http://127.0.0.1:<포트>/pair?code=`가 나오는지 (서버는 테스트에서 종료) |

기존 테스트의 `request(port, "GET", "/")` 호출은 페어링 후 쿠키를 붙이도록 헬퍼를 고친다(예: `running_server`가 서버를 넘겨주거나, `paired_page(port, server)` 헬퍼 추가). 기존 테스트의 단언은 바꾸지 않는다.

### 6. 수정 범위
- 허용: `src/marketing_agent/dashboard.py`, `tests/test_dashboard.py`, `tests/test_dashboard_posting.py`, `tests/test_hardening.py`, `.github/workflows/mac-smoke.yml`, `README.md`, `HOW_TO_SETTING.md`
- 동결: `storage.py`, `posting_service.py`, `drafts.py`, `dashboard_page.py`
- 하지 말 것: API의 `X-Session-Token` 검사 제거·완화, 승인 해시 방식 변경, 세션 토큰을 쿠키로 대체

### 7. 완료 조건
- [ ] 5번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0, 수집 테스트 수 감소 없음
- [ ] 커밋 1개: `fix(dashboard): 페어링 주소로만 대시보드 페이지 발급 (R2-T1)`, 본문 `Spec: IMP-31  Task: IMP-31` + Verify 줄

## 게이트 입력
```json
{"task_id": "R2-T1", "spec": "IMP-31",
 "allowed_files": ["src/marketing_agent/dashboard.py", "tests/test_dashboard.py", "tests/test_dashboard_posting.py", "tests/test_hardening.py",
                   ".github/workflows/mac-smoke.yml", "README.md", "HOW_TO_SETTING.md"],
 "new_tests": ["tests/test_dashboard.py::test_page_requires_pairing_cookie", "tests/test_dashboard.py::test_pair_sets_cookie_and_page_has_token",
               "tests/test_dashboard.py::test_pair_rejects_wrong_code", "tests/test_dashboard.py::test_pair_checks_host",
               "tests/test_dashboard.py::test_run_dashboard_prints_pair_url"],
 "frozen": [{"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/posting_service.py"},
            {"path": "src/marketing_agent/drafts.py"}, {"path": "src/marketing_agent/dashboard_page.py"}],
 "baseline_passed": 206}
```
