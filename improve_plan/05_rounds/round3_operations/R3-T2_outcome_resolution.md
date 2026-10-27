## 작업 R3-T2: 결과 불명 게시의 사람 해소 (IMP-35, M3)

### 1. 목표
`OUTCOME_UNKNOWN`(클릭 후 결과 확인 실패)으로 남은 게시를 사용자가 YouTube에서 직접 확인한 뒤 화면에서 "게시됨"(`POSTED`) 또는 "종료"(`DISMISSED`)로 정리할 수 있게 한다. 누가 언제 무엇으로 정리했는지 남긴다. 어느 쪽이든 **같은 영상에 다시 게시하지 않는다**(기존 설계 원칙 유지).

### 2. 배경과 근거 [코드 확인]
- `storage.finish_dashboard_post`만 상태를 바꾸며, 호출처는 `posting_service.py` 게시 경로뿐이다.
- 유일 인덱스는 `status != 'PRECHECK_FAILED'`인 예약을 영상당 하나로 제한한다. 따라서 `DISMISSED`도 재게시를 막는다(의도).
- 화면 ④ 실행 기록(`GET /api/history`, `dashboard_ui.py`의 `HIST_STATUS`)은 `OUTCOME_UNKNOWN`을 "결과 확인 필요"로 표시만 한다.

### 3. 사양
1. `storage.py`: 테이블 `dashboard_outcome_resolutions(attempt_id TEXT PRIMARY KEY, outcome TEXT NOT NULL, reviewer TEXT NOT NULL, resolved_at TEXT NOT NULL)`을 `CREATE TABLE IF NOT EXISTS`로 추가. `Store.resolve_dashboard_outcome(video_id, outcome, reviewer, when)`: 해당 영상의 예약이 `OUTCOME_UNKNOWN`일 때만 `BEGIN IMMEDIATE` 안에서 상태를 `POSTED`(이때 `verified_at`도 기록) 또는 `DISMISSED`로 바꾸고 해소 기록을 넣는다. 그 밖의 상태·없는 영상·잘못된 outcome·빈 reviewer(1~40자 아님)는 `ValueError`(코드: `OUTCOME_NOT_UNKNOWN`, `OUTCOME_INVALID`, `REVIEWER_INVALID`).
2. 서비스: `ConfiguredPostingService.resolve_outcome(video_id, outcome, reviewer)` (설정 락).
3. HTTP: `POST /api/posts/resolve` 본문 `{"video_id","outcome","reviewer"}` — 기존 POST 경로와 같은 Host·Origin·세션 토큰·Content-Type·크기·정확한 키 집합 검사. 성공 200 `{"video_id","status"}`, 실패 409 `{"reason_code"}`.
4. 화면: 실행 기록에서 `OUTCOME_UNKNOWN` 행에 안내 "YouTube에서 댓글이 달렸는지 직접 확인한 뒤 선택하세요"와 버튼 두 개("댓글 확인됨", "댓글 없음 — 종료")를 둔다. 검토자 이름은 승인 화면과 같은 입력값을 쓰거나 행 안 입력칸으로 받는다. 브라우저 `alert/confirm`은 쓰지 않는다. `DISMISSED`는 "종료됨(재게시 안 함)"으로 표시한다.
5. `DISMISSED`도 일일 한도 집계에 포함된다(기존 `status != 'PRECHECK_FAILED'` 규칙 그대로).
6. (라운드 2 재검토 권고 #2) 화면 사유 문구 매핑(`REASON_KO` 또는 설정 오류 표시부)에 `SECRET_STORE_UNAVAILABLE`·`SECRET_STORE_UNREADABLE`·`SECRET_STORE_INVALID`의 한국어 안내를 추가한다(예: "키 저장소를 읽을 수 없습니다. `data/dashboard/secrets.dpapi.json`을 지우고 키를 다시 입력하세요."). 테스트 `test_history_ui_has_resolve_controls`에서 함께 확인한다.

### 4. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_resolve_outcome_posted_and_dismissed` | `tests/test_storage.py` | `OUTCOME_UNKNOWN` → `POSTED`/`DISMISSED` 전이와 해소 기록 |
| `test_resolve_outcome_rejects_other_states` | `tests/test_storage.py` | `POSTED`·`RESERVED`·없는 영상·잘못된 값 거부 |
| `test_dismissed_still_blocks_repost` | `tests/test_storage.py` | `DISMISSED` 후 같은 영상 `reserve_reviewed_post` → `ALREADY_ATTEMPTED` |
| `test_resolve_api_requires_token_and_schema` | `tests/test_dashboard.py` | 토큰 없음 403, 키 누락·추가 400, 정상 200 |
| `test_history_ui_has_resolve_controls` | `tests/test_dashboard.py` | 페이지 JS에 `/api/posts/resolve` 호출과 `DISMISSED` 표시 문구가 있고, `node --check`로 생성 JS 문법 통과(node가 없으면 skip) |

### 5. 수정 범위
- 허용: `src/marketing_agent/storage.py`, `src/marketing_agent/dashboard.py`, `src/marketing_agent/dashboard_ui.py`, `src/marketing_agent/dashboard_page.py`, `src/marketing_agent/dashboard_contracts.py`, `tests/test_storage.py`, `tests/test_dashboard.py`
- 동결: `Store.reserve_reviewed_post`, `Store.begin_dashboard_submit`, `Store.finish_dashboard_post`, `posting_service.py`, `poster.py`
- 하지 말 것: 유일 인덱스·기존 상태 전이 변경, 자동 해소(사람 입력 없이 상태 변경)

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `feat(history): 결과 불명 게시의 사람 해소 (R3-T2)`, 본문 `Spec: IMP-35  Task: IMP-35` + Verify 줄

## 게이트 입력
```json
{"task_id": "R3-T2", "spec": "IMP-35",
 "allowed_files": ["src/marketing_agent/storage.py", "src/marketing_agent/dashboard.py", "src/marketing_agent/dashboard_ui.py", "src/marketing_agent/dashboard_page.py",
                   "src/marketing_agent/dashboard_contracts.py", "tests/test_storage.py", "tests/test_dashboard.py"],
 "new_tests": ["tests/test_storage.py::test_resolve_outcome_posted_and_dismissed", "tests/test_storage.py::test_resolve_outcome_rejects_other_states",
               "tests/test_dashboard.py::test_resolve_api_requires_token_and_schema", "tests/test_dashboard.py::test_history_ui_has_resolve_controls"],
 "frozen": [{"path": "src/marketing_agent/storage.py", "function": "Store.reserve_reviewed_post"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.begin_dashboard_submit"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.finish_dashboard_post"},
            {"path": "src/marketing_agent/posting_service.py"}, {"path": "src/marketing_agent/poster.py"}],
 "baseline_passed": 233}
```
