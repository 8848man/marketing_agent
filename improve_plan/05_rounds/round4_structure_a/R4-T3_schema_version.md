## 작업 R4-T3: DB 스키마 버전과 마이그레이션 틀 (IMP-40, L5)

### 1. 목표
`posts.db`에 스키마 버전(`PRAGMA user_version`)을 두고, 앞으로의 스키마 변경을 순서 있는 마이그레이션으로 적용하는 틀을 만든다. 기존 DB와 빈 DB가 모두 같은 최신 버전이 되어야 하며 기존 데이터는 그대로다.

### 2. 배경과 근거 [코드 확인]
- `storage.py`의 `Store.__init__`이 `CREATE TABLE IF NOT EXISTS`만 실행한다. 버전 관리가 없다.
- 라운드 3에서 `dashboard_outcome_resolutions` 테이블이 추가되었고(IMP-35), 기존 DB의 상태 CHECK 제약에 `DISMISSED`를 넣기 위해 `Store._allow_dismissed_status()`가 시작 시 예약 테이블을 한 번 재구성한다(메인이 이전 버전 DB로 검증함).

### 3. 사양
1. `storage.py`에 `SCHEMA_VERSION = 1`과 `MIGRATIONS: list[Callable[[sqlite3.Connection], None]]`를 둔다. 버전 1은 "현재 `CREATE TABLE IF NOT EXISTS` 묶음 전체 + `_allow_dismissed_status` 재구성"이다(기존 DB에도 안전). 재구성 로직은 그대로 버전 1 마이그레이션 안으로 옮기고 동작을 바꾸지 않는다. 재구성 함수 안의 `BEGIN IMMEDIATE`·`COMMIT`이 바깥 마이그레이션 트랜잭션과 겹치지 않게(중첩 트랜잭션 오류) 조정한다. 이전 버전 DB(예약 1건·OUTCOME_UNKNOWN)를 열었을 때 행·인덱스·본문이 유지되는 테스트를 하나 더 둔다.
2. `Store.__init__`: `user_version`을 읽어, 그보다 큰 마이그레이션을 `BEGIN IMMEDIATE` 안에서 순서대로 적용하고 `PRAGMA user_version`을 갱신한다. DB 버전이 `SCHEMA_VERSION`보다 크면 `ValueError("DB_SCHEMA_NEWER")`(앱을 옛 버전으로 되돌린 경우 쓰기 방지).
3. 마이그레이션 실패 시 롤백되고 예외가 올라온다(반쯤 적용된 상태 금지).
4. 연결 수명은 바꾸지 않는다(보고서의 "연결 수명 정리"는 이번 범위 밖, 기록만).

### 4. 먼저 작성할 실패 테스트 (`tests/test_storage.py`)
| 테스트 | 기대 동작 |
| --- | --- |
| `test_new_db_gets_schema_version` | 빈 DB → `user_version == SCHEMA_VERSION` |
| `test_existing_unversioned_db_is_upgraded_without_data_loss` | 버전 0인 기존 스키마 DB에 예약 1건 → 열면 버전 갱신, 예약 그대로 |
| `test_newer_db_is_rejected` | `user_version = SCHEMA_VERSION + 1` → `DB_SCHEMA_NEWER` |
| `test_failed_migration_rolls_back` | 일부러 실패하는 마이그레이션을 덧붙이면 버전·테이블 변경이 남지 않음 |

### 5. 수정 범위
- 허용: `src/marketing_agent/storage.py`, `tests/test_storage.py`
- 동결: `Store.reserve_reviewed_post`, `Store.begin_dashboard_submit`, `Store.finish_dashboard_post`, `Store.reserve_post`, `Store.resolve_dashboard_outcome`
- 하지 말 것: 컬럼명 변경·테이블 삭제, 기존 인덱스 변경

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `feat(storage): 스키마 버전과 마이그레이션 틀 (R4-T3)`, 본문 `Spec: IMP-40  Task: IMP-40` + Verify 줄

## 게이트 입력
```json
{"task_id": "R4-T3", "spec": "IMP-40",
 "allowed_files": ["src/marketing_agent/storage.py", "tests/test_storage.py"],
 "new_tests": ["tests/test_storage.py::test_new_db_gets_schema_version", "tests/test_storage.py::test_newer_db_is_rejected",
               "tests/test_storage.py::test_existing_unversioned_db_is_upgraded_without_data_loss"],
 "frozen": [{"path": "src/marketing_agent/storage.py", "function": "Store.reserve_reviewed_post"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.begin_dashboard_submit"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.finish_dashboard_post"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.reserve_post"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.resolve_dashboard_outcome"}],
 "baseline_passed": 250}
```
