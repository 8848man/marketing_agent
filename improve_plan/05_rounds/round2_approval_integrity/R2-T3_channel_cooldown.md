## 작업 R2-T3: 같은 대상 채널 게시 간격 (IMP-33, M1)

### 1. 목표
제품 경로(대시보드)에서 같은 대상 채널에 연달아 댓글을 다는 것을 막는다. 직전 게시 시도(예약 이후 상태, `PRECHECK_FAILED` 제외)로부터 60분이 지나기 전에는 같은 채널 영상의 예약을 `CHANNEL_COOLDOWN`으로 거부한다. 판정은 예약과 같은 트랜잭션에서, Chrome 실행 전에 한다.

### 2. 배경과 근거 [코드 확인]
- `storage.py` `reserve_reviewed_post`(335행): `BEGIN IMMEDIATE` 안에서 영상 중복(`ALREADY_ATTEMPTED`)·일일 한도(`DAILY_LIMIT`)를 검사하고 `dashboard_post_reservations`에 `RESERVED`를 넣는다. 채널 간격 검사 없음.
- 레거시 `reserve_post`(416행)는 `channel_cooldowns` 테이블로 24시간 간격을 둔다(대시보드 경로에는 미적용).
- 정책 근거: YouTube 스팸 정책은 "high-volume, repetitive" 댓글을 금지한다(ADR-0005에 정리).
- PDF 고정 일일 10개 한도는 바꾸지 않는다. 간격은 추가 제한이다.

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 라운드 2 브랜치
- 좁은 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_storage.py tests/test_posting_service.py tests/test_dashboard.py`

### 4. 사양
1. `reserve_reviewed_post(..., cooldown_minutes: int = 0)`: 0이면 지금과 같다. 양수면 같은 `channel_id`의 `dashboard_post_reservations` 중 `status != 'PRECHECK_FAILED'`이고 `reserved_at`이 `when - cooldown_minutes` 이후인 행이 있으면 `ReservationBlocked("CHANNEL_COOLDOWN")`. 음수·bool·정수 아님은 `ValueError`. 검사 순서: 영상 중복 → 일일 한도 → 채널 간격.
2. `PostingService.__init__`에 `channel_cooldown_minutes=0`을 추가해 `reserve_reviewed_post`에 넘긴다(기존 테스트 영향 없음).
3. `ConfiguredPostingService`: `kwargs.setdefault("channel_cooldown_minutes", 60)`.
4. 화면에 사유가 코드로만 보이면 안 된다. `dashboard_ui.py`(또는 사유 문구를 만드는 곳)에 기존 사유 문구 방식대로 `CHANNEL_COOLDOWN` → "같은 채널에는 60분 간격으로만 댓글을 달 수 있습니다. 다른 채널 영상을 선택하거나 잠시 뒤 다시 시도하세요." 를 추가한다. 문구 방식이 없으면 이 항목은 하지 말고 보고서에 적는다.

### 5. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_reviewed_post_channel_cooldown_blocks_within_window` | `tests/test_storage.py` | 같은 채널 두 번째 예약이 59분 뒤면 `CHANNEL_COOLDOWN`, 61분 뒤면 성공 |
| `test_reviewed_post_cooldown_ignores_precheck_failed_and_other_channels` | `tests/test_storage.py` | 직전 시도가 `PRECHECK_FAILED`면 막지 않음, 다른 채널은 막지 않음 |
| `test_reviewed_post_cooldown_rejects_invalid_value` | `tests/test_storage.py` | `cooldown_minutes=-1`·`True` → `ValueError` |
| `test_post_video_channel_cooldown_blocks_before_poster` | `tests/test_posting_service.py` | `channel_cooldown_minutes=60`, 같은 채널 두 영상 연속 게시 → 두 번째는 `blocked`/`CHANNEL_COOLDOWN`, poster 1회만 호출 |
| `test_configured_service_uses_60_minute_cooldown` | `tests/test_dashboard.py` | `ConfiguredPostingService(..., settings=…).channel_cooldown_minutes == 60` |

### 6. 수정 범위
- 허용: `src/marketing_agent/storage.py`, `src/marketing_agent/posting_service.py`, `src/marketing_agent/dashboard.py`, `src/marketing_agent/dashboard_ui.py`, `tests/test_storage.py`, `tests/test_posting_service.py`, `tests/test_dashboard.py`
- 동결: `storage.py`의 `Store.reserve_post`, `Store.begin_dashboard_submit`, `Store.finish_dashboard_post`; `guard.py`; `drafts.py`
- 하지 말 것: 일일 한도·유일 인덱스·상태 전이 변경, 레거시 `channel_cooldowns` 테이블 사용

### 7. 완료 조건
- [ ] 5번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(storage): 같은 대상 채널 게시 간격 60분 (R2-T3)`, 본문 `Spec: IMP-33  Task: IMP-33` + Verify 줄

## 게이트 입력
```json
{"task_id": "R2-T3", "spec": "IMP-33",
 "allowed_files": ["src/marketing_agent/storage.py", "src/marketing_agent/posting_service.py", "src/marketing_agent/dashboard.py", "src/marketing_agent/dashboard_ui.py",
                   "tests/test_storage.py", "tests/test_posting_service.py", "tests/test_dashboard.py"],
 "new_tests": ["tests/test_storage.py::test_reviewed_post_channel_cooldown_blocks_within_window",
               "tests/test_storage.py::test_reviewed_post_cooldown_rejects_invalid_value",
               "tests/test_posting_service.py::test_post_video_channel_cooldown_blocks_before_poster",
               "tests/test_dashboard.py::test_configured_service_uses_60_minute_cooldown"],
 "frozen": [{"path": "src/marketing_agent/storage.py", "function": "Store.reserve_post"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.begin_dashboard_submit"},
            {"path": "src/marketing_agent/storage.py", "function": "Store.finish_dashboard_post"},
            {"path": "src/marketing_agent/guard.py"}, {"path": "src/marketing_agent/drafts.py"}],
 "baseline_passed": 206}
```
