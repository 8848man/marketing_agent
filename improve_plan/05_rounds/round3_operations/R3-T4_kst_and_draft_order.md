## 작업 R3-T4: 일일 한도 KST 통일과 초안 로딩 순서 (IMP-37, L1·L2)

### 1. 목표
(1) 일일 한도의 날짜를 머신 시간대가 아니라 KST로 계산한다. (2) 초안을 읽을 때 개별 파일 `drafts/<video_id>.json`을 `latest.json`보다 먼저 본다.

### 2. 배경과 근거 [코드 확인]
- `posting_service.py` `PostingService.__init__`: `self.local_tz = datetime.now().astimezone().tzinfo`(머신 시간대). 이 값으로 날짜를 계산해 `attempt_date_kst` 컬럼에 넣는다(`reserve_reviewed_post(local_tz=…)`, `begin_dashboard_submit(local_tz=…)`, `video_states` 등 174행 부근). 머신이 KST가 아니면 컬럼명과 실제가 다르고 레거시 KST 집계와 어긋난다.
- `drafts.py` `_load_record`(약 152행)는 `latest.json`을 먼저 찾고, 그 안에 해당 영상이 있으면 개별 파일을 보지 않는다. 앱은 개별 파일만 쓴다(IMP-23에서 `latest.json` 제외).

### 3. 사양
1. `PostingService.local_tz`의 기본값을 `ZoneInfo("Asia/Seoul")`로 바꾼다(`storage.KST`가 있으면 그것을 재사용). 생성자 인자 `local_tz=None`을 추가해 테스트에서 바꿀 수 있게 한다.
2. `_load_record`: 개별 파일이 있으면 그것을 반환하고, 없을 때만 `latest.json`을 본다. 심볼릭 링크·크기 검사는 그대로 유지한다.

### 4. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_daily_limit_day_is_kst_regardless_of_machine_tz` | `tests/test_posting_service.py` | `monkeypatch.setenv("TZ","UTC")` + `time.tzset()`(가능한 OS에서만, 아니면 skip) 후 만든 서비스의 `local_tz`가 KST이고, UTC 15:30(KST 다음날 00:30) 예약의 `attempt_date_kst`가 KST 날짜 |
| `test_individual_draft_wins_over_latest_json` | `tests/test_rss_drafts.py` | 같은 영상이 `latest.json`(옛 문안)과 개별 파일(새 문안)에 있으면 개별 파일 문안 반환 |
| `test_latest_json_used_only_as_fallback` | `tests/test_rss_drafts.py` | 개별 파일이 없으면 `latest.json` 문안 반환(회귀 방지) |

### 5. 수정 범위
- 허용: `src/marketing_agent/posting_service.py`, `src/marketing_agent/drafts.py`, `tests/test_posting_service.py`, `tests/test_rss_drafts.py`
- 동결: `storage.py`, `drafts.content_hash`, `drafts.quality_failure`, `dashboard.py`
- 하지 말 것: 컬럼명 변경(라운드 4 마이그레이션 범위), 승인 해시 변경

### 6. 완료 조건
- [ ] 4번 테스트(회귀 방지 제외)가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(posting,drafts): 일일 한도 KST 통일, 개별 초안 우선 (R3-T4)`, 본문 `Spec: IMP-37  Task: IMP-37` + Verify 줄

## 게이트 입력
```json
{"task_id": "R3-T4", "spec": "IMP-37",
 "allowed_files": ["src/marketing_agent/posting_service.py", "src/marketing_agent/drafts.py", "tests/test_posting_service.py", "tests/test_rss_drafts.py"],
 "new_tests": ["tests/test_posting_service.py::test_daily_limit_day_is_kst_regardless_of_machine_tz", "tests/test_rss_drafts.py::test_individual_draft_wins_over_latest_json"],
 "frozen": [{"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/drafts.py", "function": "content_hash"},
            {"path": "src/marketing_agent/drafts.py", "function": "quality_failure"}, {"path": "src/marketing_agent/dashboard.py"}],
 "baseline_passed": 233}
```
