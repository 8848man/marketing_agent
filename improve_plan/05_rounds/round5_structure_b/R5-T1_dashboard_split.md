## 작업 R5-T1: dashboard.py 분리와 세션 토큰 검사 단일화 (IMP-41, M7)

### 1. 목표
`dashboard.py`(1,400줄 이상)를 역할별 모듈로 나누고, 반복되는 세션 토큰 비교를 `_session_ok` 하나로 모은다. **공개 동작(경로·응답·오류 코드)은 바꾸지 않는다.**

### 2. 배경과 근거 [코드 확인]
- `dashboard.py`에 HTTP 핸들러, `ConfiguredPostingService`, `DemoService`, Chrome 찾기·로그인 창(`_installed_chrome`, `_is_default_chrome_user_data_dir`, `_open_login_window`, `watch_url`, `PDF_EXAMPLE_VIDEOS`), `check_channel_connection`이 함께 있다.
- `do_POST`의 여러 경로가 `secrets.compare_digest(self.headers.get("X-Session-Token", ""), token)`을 직접 반복한다.

### 3. 사양
1. 새 모듈 `chrome_launch.py`: Chrome 찾기·기본 프로필 판정·로그인 창·`watch_url`·`PDF_EXAMPLE_VIDEOS`.
2. 새 모듈 `dashboard_service.py`: `ConfiguredPostingService`, `DemoService`, `check_channel_connection`과 그 보조 함수.
3. `dashboard.py`: `create_server`, `run_dashboard`, 페어링, `_capture_url` 등 HTTP 계층만. 기존 import 경로 호환을 위해 옮긴 공개 이름(`ConfiguredPostingService`, `DemoService`, `DashboardSettings`, `check_channel_connection`, `watch_url`)을 `dashboard.py`에서 다시 내보낸다.
4. 세션 토큰 검사는 모두 `_session_ok()`를 거친다. `dashboard.py`에서 `compare_digest`는 `_session_ok`와 페어링 검사 함수 안에만 남는다.
5. 테스트가 `monkeypatch.setattr(dashboard, "_installed_chrome", …)`처럼 옮긴 함수를 바꾸고 있으면 새 모듈을 대상으로 고친다(단언은 그대로).
6. `graph.json`·`00_index.md`에 새 모듈 노드를 추가하고 `AGENTS.md`·문서의 경로 언급을 확인한다(`check_sdd.py` 0).
7. 목표 크기: `dashboard.py` 800줄 이하.
8. (라운드 4 검토 권고 #1) `tests/test_legacy_boundary.py`의 import 수집이 상대 import(모든 level)뿐 아니라 절대 import(`import marketing_agent.x`, `from marketing_agent import x`, `from marketing_agent.x import y`)도 따라가게 한다. 이번 분리로 생기는 새 모듈도 자동으로 그래프에 포함된다.
9. (라운드 4 검토 권고 #2) `logging.py`의 `RequestLogger`에 "한 프로세스·한 인스턴스가 파일 하나를 쓴다는 전제" 주석을 한 줄 단다.

### 4. 먼저 작성할 실패 테스트 (`tests/test_dashboard_structure.py`, 새 파일)
| 테스트 | 기대 동작 |
| --- | --- |
| `test_dashboard_module_size_limit` | `dashboard.py` 줄 수 ≤ 800 |
| `test_session_token_compare_only_in_helpers` | `ast`로 `dashboard.py`에서 `compare_digest` 호출을 찾아, 감싸는 함수 이름이 `_session_ok` 또는 페어링 검사 함수뿐 |
| `test_boundary_collector_follows_absolute_imports` | `tests/test_legacy_boundary.py`의 수집 함수가 절대 import 형태 3가지를 모두 잡는다(임시 소스 문자열로 시험) |
| `test_public_names_still_importable` | `from marketing_agent.dashboard import ConfiguredPostingService, DemoService, create_server, run_dashboard, check_channel_connection, watch_url` 성공 |

### 5. 수정 범위
- 허용: `src/marketing_agent/dashboard.py`, `src/marketing_agent/dashboard_service.py`, `src/marketing_agent/chrome_launch.py`, `src/marketing_agent/logging.py`(주석만), `src/marketing_agent/__main__.py`, `tests/*.py`, `.ucompany/sdd/graph.json`, `.ucompany/sdd/00_index.md`, `AGENTS.md`
- 동결: `posting_service.py`, `storage.py`, `poster.py`, `drafts.py`, `dashboard_settings.py`
- 하지 말 것: 함수 본문 동작 변경(이동만), 경로·응답 형식 변경, 테스트 단언 변경

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 기존 테스트 전부 단언 변경 없이 통과, V1 0·0
- [ ] 커밋 1개: `refactor(dashboard): HTTP·서비스·Chrome 모듈 분리 (R5-T1)`, 본문 `Spec: IMP-41  Task: IMP-41` + Verify 줄

## 게이트 입력
```json
{"task_id": "R5-T1", "spec": "IMP-41",
 "allowed_files": ["src/marketing_agent/dashboard.py", "src/marketing_agent/dashboard_service.py", "src/marketing_agent/chrome_launch.py", "src/marketing_agent/logging.py",
                   "src/marketing_agent/__main__.py", "tests/*.py", ".ucompany/sdd/graph.json", ".ucompany/sdd/00_index.md", "AGENTS.md"],
 "new_tests": ["tests/test_dashboard_structure.py", "tests/test_legacy_boundary.py::test_boundary_collector_follows_absolute_imports"],
 "frozen": [{"path": "src/marketing_agent/posting_service.py"}, {"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/poster.py"},
            {"path": "src/marketing_agent/drafts.py"}, {"path": "src/marketing_agent/dashboard_settings.py"}],
 "baseline_passed": 263}
```
