## 작업 R3-T1: 설정 락과 브라우저 락 분리 (IMP-34, M2)

### 1. 목표
게시(Chrome 수십 초)와 AI 초안 생성(네트워크) 동안 영상 목록·선택·승인·상태 조회가 멈추지 않게 한다. 동시에 **게시 중에 다른 작업이 Chrome 프로필 설정(`poster.user_data_dir`)을 바꿔 다른 계정으로 게시되는 일이 없게** 한다.

### 2. 배경과 근거 [코드 확인]
- `ConfiguredPostingService`(dashboard.py)는 `self._settings_lock`(RLock) 하나로 모든 상태를 보호한다(20곳).
- `_post_video_on_worker`는 이 락을 잡은 채 `super().post_video(video_id)`(Chrome 실행·입력·확인)를 호출한다.
- `generate_draft`·`refine_draft`는 락을 잡은 채 `evidence_provider.collect`와 `draft_generator.generate`(외부 AI)를 호출한다.
- Chrome 설정을 바꾸는 곳: `verify_profile`(`poster.user_data_dir = root` 후 `check_signed_in`), 프로필 선택 저장(약 486행), `_use_assigned_profile`, 로그인 창 열기(`_login_window_*`).

### 3. 사양
1. `self._browser_lock = RLock()`을 추가한다. **락 순서는 항상 브라우저 락 → 설정 락**이다. 설정 락을 잡은 상태에서 브라우저 락을 잡지 않는다.
2. `_post_video_on_worker`: 브라우저 락을 처음부터 끝까지 잡는다. 설정 락은 사전 검사 구간(브랜드 일치, `_use_assigned_profile`, poster 준비, `_profile_reason`)과 결과 후처리(`LOGIN_REQUIRED` 상태 갱신)에만 잡는다. `super().post_video`는 설정 락 밖·브라우저 락 안에서 호출한다.
3. `poster`의 프로필 경로·창 상태를 바꾸거나 Chrome·로그인 창을 여는 메서드(`verify_profile`, 프로필 선택 저장, 로그인 창 열기 등 `self.poster.` 대입이나 `_open_login_window` 호출이 있는 공개 메서드)는 브라우저 락 → 설정 락 순서로 잡는다.
4. `generate_draft`·`refine_draft`: 설정 락 안에서 필요한 값(카드, 담당 프로필, 제공사·모델·키, 브랜드, 글자 수, 2차 필터 여부)을 스냅샷으로 복사하고, 근거 수집과 AI 호출은 락 밖에서 한다. 저장 직전에 다시 설정 락을 잡고 브랜드명·글자 수·카드가 스냅샷과 같은지 확인한다. 다르면 저장하지 않고 `ValueError("BRAND_CHANGED_REGENERATE")`.
5. 그 밖의 메서드(목록·선택·승인·상태·설정 저장)는 설정 락만 쓴다.

### 4. 먼저 작성할 실패 테스트 (`tests/test_dashboard.py`)
가짜 poster는 `threading.Event`로 게시 도중 멈춘다. 각 테스트는 5초 타임아웃을 둔다.

| 테스트 | 기대 동작 |
| --- | --- |
| `test_reads_do_not_wait_for_posting` | 게시가 멈춘 동안 다른 스레드의 `video_states()`·`select_video()`·`list_videos()`가 1초 안에 끝난다 |
| `test_verify_profile_waits_for_posting` | 게시가 멈춘 동안 다른 프로필 `verify_profile`을 호출하면 게시가 끝날 때까지 시작하지 않고, 게시 시점의 `poster.user_data_dir`는 담당 프로필 경로 그대로다 |
| `test_generate_draft_does_not_hold_settings_lock` | 가짜 `draft_generator.generate`가 멈춘 동안 `video_states()`가 1초 안에 끝난다 |
| `test_generate_draft_discards_when_brand_changed` | 생성 도중 브랜드명을 바꾸면 결과를 저장하지 않고 `BRAND_CHANGED_REGENERATE` |

### 5. 수정 범위
- 허용: `src/marketing_agent/dashboard.py`, `tests/test_dashboard.py`, `tests/test_dashboard_posting.py`
- 동결: `posting_service.py`, `storage.py`, `drafts.py`, `poster.py`
- 하지 말 것: 단일 게시 워커(`max_workers=1`) 변경, 사전 검사 순서 변경, 락 제거

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과 (전체 실행을 5회 반복해도 통과)
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(dashboard): 설정 락과 브라우저 락 분리 (R3-T1)`, 본문 `Spec: IMP-34  Task: IMP-34` + Verify 줄

## 게이트 입력
```json
{"task_id": "R3-T1", "spec": "IMP-34",
 "allowed_files": ["src/marketing_agent/dashboard.py", "tests/test_dashboard.py", "tests/test_dashboard_posting.py"],
 "new_tests": ["tests/test_dashboard.py::test_reads_do_not_wait_for_posting", "tests/test_dashboard.py::test_verify_profile_waits_for_posting",
               "tests/test_dashboard.py::test_generate_draft_does_not_hold_settings_lock", "tests/test_dashboard.py::test_generate_draft_discards_when_brand_changed"],
 "frozen": [{"path": "src/marketing_agent/posting_service.py"}, {"path": "src/marketing_agent/storage.py"},
            {"path": "src/marketing_agent/drafts.py"}, {"path": "src/marketing_agent/poster.py"}],
 "baseline_passed": 233}
```
