## 작업 R1-T3: 게시 가드가 설정 채널을 쓰도록 수정 (IMP-28, H2)

### 1. 목표
설정(`config.yaml` → `DashboardSettings.channels()`)에 등록한 채널의 영상이 게시 가드에서 `CHANNEL_NOT_ALLOWED`로 막히지 않게 하고, 설정에 없는 채널은 고정 목록에 있더라도 막는다.

### 2. 배경과 근거 [코드 확인]
- `src/marketing_agent/guard.py` `check_rss_membership(video, channel_id, *, recheck=None)`가 `from .rss_feed import CHANNELS` 후 `if channel_id not in CHANNELS` 로 고정 5개 채널만 허용한다.
- `posting_service.py` `PostingService.post_video` (약 220행)가 `check_rss_membership(video_id, card.channel_id, recheck=lambda *_: fresh)`로 호출한다.
- `__main__.py`는 이미 `recheck`와 `feed_loader`에 `settings.channels()`를 넘긴다. 가드만 고정 목록을 본다.
- `ConfiguredPostingService.__init__` (`dashboard.py` 약 167행)는 `settings`를 받고 `super().__init__(*args, **kwargs)`를 호출한다.

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 브랜치 `fix/IMP-27-30-round1-immediate`
- 좁은 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_guard.py tests/test_posting_service.py tests/test_dashboard.py`

### 4. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_rss_membership_allows_injected_channel` | `tests/test_guard.py` | `CHANNELS`에 없는 `UC` 채널을 `allowed_channels`로 넘기고 recheck가 일치 카드를 주면 `allowed=True`, `reason="POST_ALLOWED"` |
| `test_rss_membership_rejects_channel_outside_injected` | `tests/test_guard.py` | `CHANNELS`에 있는 채널이라도 `allowed_channels`에 없으면 `CHANNEL_NOT_ALLOWED` |
| `test_rss_membership_defaults_to_fixed_channels` | `tests/test_guard.py` | `allowed_channels`를 안 넘기면 기존처럼 `CHANNELS` 기준 |
| `test_post_video_allows_configured_channel_outside_fixed_list` | `tests/test_posting_service.py` | `prepare_service`와 같은 방식으로 만들되 카드 채널을 고정 목록 밖 `UC…`로, `allowed_channels=lambda: {채널: "이름"}`을 넘기면 `post_video` 결과가 `CHANNEL_NOT_ALLOWED`가 아니고 poster가 호출됨 |
| `test_configured_service_uses_settings_channels` | `tests/test_dashboard.py` | `ConfiguredPostingService`를 settings와 함께 만들면 `service.allowed_channels()`가 `settings.channels()`와 같은 키를 반환 (기존 `tests/test_dashboard.py` 200행 부근의 settings 생성 방식 재사용) |

### 5. 수정 범위
- 허용: `src/marketing_agent/guard.py`, `src/marketing_agent/posting_service.py`, `src/marketing_agent/dashboard.py`, `tests/test_guard.py`, `tests/test_posting_service.py`, `tests/test_dashboard.py`
- 동결: `storage.py` 전체, `rss_feed.py` 전체, `guard.check_ownership`
- 하지 말 것: `rss_feed.CHANNELS` 삭제·변경, 테스트 영상(`test_videos`) 경로 변경, RSS 재확인(`recheck`) 생략

### 6. 구현 지침
1. `check_rss_membership(video, channel_id, *, recheck=None, allowed_channels=None)`: `allowed = CHANNELS if allowed_channels is None else allowed_channels`, 판정은 `channel_id not in allowed`. docstring의 "fixed feeds"를 "configured feeds (default: fixed list)"로 고친다.
2. `PostingService.__init__`에 키워드 `allowed_channels=None`(인자 없는 호출 가능 객체) 추가, `self.allowed_channels`에 저장. `post_video`에서 `check_rss_membership(..., allowed_channels=self.allowed_channels() if self.allowed_channels else None)`.
3. `ConfiguredPostingService.__init__`: `super().__init__` 전에 `if settings is not None: kwargs.setdefault("allowed_channels", settings.channels)`.
4. 가드 거부는 지금처럼 DB 예약·Chrome 실행 전에 일어나야 한다(기존 순서 유지).

### 7. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(guard): 게시 가드가 설정 채널 목록을 사용 (R1-T3)`, 본문 `Spec: IMP-28  Task: IMP-28` + Verify 줄

### 게이트 입력
```json
{"task_id": "R1-T3", "spec": "IMP-28",
 "allowed_files": ["src/marketing_agent/guard.py", "src/marketing_agent/posting_service.py", "src/marketing_agent/dashboard.py",
                   "tests/test_guard.py", "tests/test_posting_service.py", "tests/test_dashboard.py"],
 "new_tests": ["tests/test_guard.py::test_rss_membership_allows_injected_channel",
               "tests/test_guard.py::test_rss_membership_rejects_channel_outside_injected",
               "tests/test_posting_service.py::test_post_video_allows_configured_channel_outside_fixed_list",
               "tests/test_dashboard.py::test_configured_service_uses_settings_channels"],
 "frozen": [{"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/rss_feed.py"},
            {"path": "src/marketing_agent/guard.py", "function": "check_ownership"}],
 "baseline_passed": 177}
```
`test_rss_membership_defaults_to_fixed_channels`는 수정 전에도 통과하는 회귀 방지 테스트이므로 G1 대상에서 뺐다.
