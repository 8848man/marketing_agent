## 작업 R3-T3: 대시보드 경로 구조화 로그 (IMP-36, L4)

### 1. 목표
대시보드 API 요청과 게시 결과를 비밀 없이 JSONL로 남겨, 문제가 생겼을 때 무슨 일이 있었는지 추적할 수 있게 한다.

### 2. 배경과 근거 [코드 확인]
- `logging.py`의 `EventLogger`는 레거시 CLI용으로 필드가 고정되어 있다(`event, run_id, video_id, input_source, reason`, 게시 이벤트는 `attempt_id` 필수). 비밀 마스킹 `_redact` 있음.
- `dashboard.py` Handler의 `log_message`는 아무것도 하지 않고, 예외는 `503 INTERNAL_ERROR`로만 응답한다.

### 3. 사양
1. `logging.py`에 `RequestLogger(path)`를 추가한다: `emit(*, request_id, method, route, status, reason_code="", duration_ms, error_type="")` → JSONL 한 줄(`timestamp`, 위 필드). `route`는 경로의 영상 ID 부분을 `{video_id}`로 바꾼 값, `reason_code`·`error_type`은 `^[A-Za-z][A-Za-z0-9_]*$`가 아니면 `"INVALID"`로 대체. 쿼리 문자열·본문·헤더·예외 메시지는 기록하지 않는다. 파일이 5MB를 넘으면 `.1`로 한 번 돌린다.
2. `create_server(..., request_log=None)`: 주어지면 GET·POST마다 위 레코드를 남긴다. 503을 반환하는 `except Exception` 경로는 `error_type=type(exc).__name__`을 남긴다. 응답에 `X-Request-Id` 헤더를 붙인다(`uuid4().hex[:12]`).
3. `__main__.py`의 대시보드 실행 경로는 `data/dashboard/logs/dashboard-requests.jsonl`로 `RequestLogger`를 넘긴다.
4. 로그 쓰기 실패(OSError)는 요청 처리를 막지 않는다.

### 4. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_request_logger_writes_safe_fields` | `tests/test_hardening.py` | 기록에 허용 필드만 있고, `route`의 영상 ID는 `{video_id}` |
| `test_request_logger_rejects_unsafe_codes_and_rotates` | `tests/test_hardening.py` | 공백·특수문자 코드 → `INVALID`, 5MB 초과 시 `.1` 회전 |
| `test_server_logs_requests_without_secrets` | `tests/test_dashboard.py` | 토큰 헤더를 보낸 요청의 로그 파일에 토큰 문자열이 없고 `X-Request-Id`가 응답과 같다 |
| `test_server_logs_error_type_on_503` | `tests/test_dashboard.py` | 서비스가 예외를 던지면 503, 로그에 `error_type`(예외 클래스 이름)만 있고 메시지는 없음 |

### 5. 수정 범위
- 허용: `src/marketing_agent/logging.py`, `src/marketing_agent/dashboard.py`, `src/marketing_agent/__main__.py`, `tests/test_hardening.py`, `tests/test_dashboard.py`, `.ucompany/sdd/graph.json`, `.ucompany/sdd/00_index.md`
- 동결: `EventLogger.emit`, `posting_service.py`, `storage.py`
- 하지 말 것: 레거시 `EventLogger` 동작 변경, 요청 본문·쿼리·헤더 기록

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0 (`logging.py`가 대시보드 import 대상이 되면 graph 노드 확인)
- [ ] 커밋 1개: `feat(logging): 대시보드 요청 구조화 로그 (R3-T3)`, 본문 `Spec: IMP-36  Task: IMP-36` + Verify 줄

## 게이트 입력
```json
{"task_id": "R3-T3", "spec": "IMP-36",
 "allowed_files": ["src/marketing_agent/logging.py", "src/marketing_agent/dashboard.py", "src/marketing_agent/__main__.py", "tests/test_hardening.py",
                   "tests/test_dashboard.py", ".ucompany/sdd/graph.json", ".ucompany/sdd/00_index.md"],
 "new_tests": ["tests/test_hardening.py::test_request_logger_writes_safe_fields", "tests/test_hardening.py::test_request_logger_rejects_unsafe_codes_and_rotates",
               "tests/test_dashboard.py::test_server_logs_requests_without_secrets", "tests/test_dashboard.py::test_server_logs_error_type_on_503"],
 "frozen": [{"path": "src/marketing_agent/logging.py", "function": "EventLogger.emit"},
            {"path": "src/marketing_agent/posting_service.py"}, {"path": "src/marketing_agent/storage.py"}],
 "baseline_passed": 233}
```
