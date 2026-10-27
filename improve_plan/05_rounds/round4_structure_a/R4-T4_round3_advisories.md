## 작업 R4-T4: 라운드 3 검토 권고 정리 (IMP-35·36)

### 1. 목표
라운드 3 검토 권고 #1(로그 회전 경쟁)과 #4(검토자 이름 제어문자)를 고친다.

### 2. 수정
| # | 파일 | 문제 | 수정 |
| --- | --- | --- | --- |
| 1 | `logging.py` `RequestLogger.emit` | 회전(stat → replace)과 쓰기에 락이 없어 동시 요청 시 `.1`이 덮이거나 기록이 유실될 수 있음 | 인스턴스 `threading.Lock`으로 회전 판정·회전·쓰기를 한 구간으로 감싼다 |
| 4 | `storage.py` `Store.resolve_dashboard_outcome` | 검토자 이름에 개행·제어문자 허용 | `\x00-\x1f`, `\x7f` 포함 시 `ValueError("REVIEWER_INVALID")` |

### 3. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_request_logger_concurrent_writes_keep_all_records` | `tests/test_hardening.py` | 회전 상한을 작게(생성자 인자 `max_bytes`) 둔 로거에 8스레드×50건 기록 → 현재 파일과 `.1`의 줄 수 합이 마지막 회전 이후 기록 수와 모순 없음(각 줄이 온전한 JSON), 예외 0 |
| `test_resolve_outcome_rejects_control_characters` | `tests/test_storage.py` | 검토자 `"a\nb"`, `"a\x00"` → `REVIEWER_INVALID` |

### 4. 수정 범위
- 허용: `src/marketing_agent/logging.py`, `src/marketing_agent/storage.py`, `tests/test_hardening.py`, `tests/test_storage.py`
- 동결: `Store.reserve_reviewed_post`, `Store.finish_dashboard_post`, `EventLogger.emit`
- `RequestLogger`의 기본 회전 상한(5MB)은 그대로, 테스트용 `max_bytes` 키워드만 추가

### 5. 완료 조건
- [ ] 3번 테스트가 수정 전 실패, 수정 후 통과(동시성 테스트는 10회 반복)
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(logging,storage): 로그 회전 잠금, 검토자 이름 제어문자 거부 (R4-T4)`, 본문 `Spec: IMP-35 IMP-36  Task: R4-T4` + Verify 줄

## 게이트 입력
```json
{"task_id": "R4-T4", "spec": "IMP-35",
 "allowed_files": ["src/marketing_agent/logging.py", "src/marketing_agent/storage.py", "tests/test_hardening.py", "tests/test_storage.py"],
 "new_tests": ["tests/test_hardening.py::test_request_logger_concurrent_writes_keep_all_records", "tests/test_storage.py::test_resolve_outcome_rejects_control_characters"],
 "frozen": [{"path": "src/marketing_agent/storage.py", "function": "Store.reserve_reviewed_post"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.finish_dashboard_post"},
            {"path": "src/marketing_agent/logging.py", "function": "EventLogger.emit"}],
 "baseline_passed": 250}
```
