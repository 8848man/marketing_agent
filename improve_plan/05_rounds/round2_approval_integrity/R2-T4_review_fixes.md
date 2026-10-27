## 작업 R2-T4: 라운드 2 검토 지적 반영 (IMP-31·32·33)

### 1. 목표
라운드 2 검토(logs/r2/R2-review-1.md)의 차단 #1·#2와 권고 #3·#5·#6을 고친다. 각 수정마다 재현 테스트를 먼저 쓴다.

### 2. 지적과 수정
| # | 파일 | 문제 | 수정 |
| --- | --- | --- | --- |
| 1 | `posting_service.py` 예약 거부 처리(`except ReservationBlocked`) | `CHANNEL_COOLDOWN`·`DAILY_LIMIT`으로 막히면 `PostStatus`에 안내 문구가 없어 화면에 코드만 보임 | 두 사유에 한국어 message를 넣는다: 간격 "같은 채널에는 60분 간격으로만 댓글을 달 수 있습니다. 다른 채널 영상을 선택하거나 잠시 뒤 다시 시도하세요.", 한도 "오늘 게시 한도(10개)에 도달했습니다. 내일 다시 시도하세요." 간격 문구의 분은 `channel_cooldown_minutes` 값으로 채운다 |
| 2 | `dashboard_settings.py` 저장소 쓰기 실패 처리 | 일시적 DPAPI 오류로 복호화가 실패해도 저장소 파일을 `.bad`로 격리해 키 전체를 잃음, 이전 `.bad`도 덮어씀 | 격리는 파일 형식 오류(`SECRET_STORE_INVALID`)일 때만. `SECRET_STORE_UNREADABLE`·`OSError`는 격리 없이 저장 실패(`ValueError("SECRET_STORE_UNAVAILABLE")`)로 올린다. 격리 파일명은 `secrets.dpapi.json.bad-<UTC 타임스탬프>` |
| 3 | `dashboard.py` 페어링 코드·쿠키 비교 | 비ASCII 입력에서 `compare_digest`가 `TypeError` → 응답 없이 연결 종료 | 두 비교를 UTF-8 bytes로 한다. 세션 토큰 헤더 비교(`_session_ok` 등)도 같은 방식으로 |
| 5 | `dashboard.py` 쿠키 이름 | 같은 PC에서 대시보드를 둘 띄우면 쿠키가 서로 덮어씀 | 쿠키 이름을 `ma_pair_<포트>` |
| 6 | `dashboard.py` `/pair` 303 응답 | CSP 등 공통 보안 헤더 없음 | 303에도 `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`(기존 값과 같게)를 붙인다 |

권고 #4(프로세스 간 파일 잠금 없음)는 알려진 한계로 기록만 한다.

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 브랜치 `fix/IMP-31-33-round2-approval-integrity`
- 좁은 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_posting_service.py tests/test_secret_store.py tests/test_dashboard.py`

### 4. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_cooldown_and_daily_limit_have_korean_message` | `tests/test_posting_service.py` | 두 사유의 `PostStatus.message`가 비어 있지 않고 한국어 안내를 포함 |
| `test_transient_unreadable_store_is_not_quarantined` | `tests/test_secret_store.py` | `unprotect`·`protect`가 모두 OSError일 때 저장 → `SECRET_STORE_UNAVAILABLE`, 원래 저장소 파일 그대로, `.bad-*` 없음 |
| `test_corrupt_store_quarantine_keeps_previous_backups` | `tests/test_secret_store.py` | 깨진 파일 두 번 격리 → `.bad-*` 파일 2개 |
| `test_pair_rejects_non_ascii_code_and_cookie` | `tests/test_dashboard.py` | `/pair?code=%C3%A9` → 403, 비ASCII 쿠키로 `/` → 403(연결 끊김 아님) |
| `test_pair_cookie_name_includes_port_and_redirect_has_security_headers` | `tests/test_dashboard.py` | `Set-Cookie`가 `ma_pair_<포트>=`로 시작, 303에 CSP·nosniff·X-Frame-Options |

### 5. 수정 범위
- 허용: `src/marketing_agent/posting_service.py`, `src/marketing_agent/dashboard_settings.py`, `src/marketing_agent/secret_store.py`, `src/marketing_agent/dashboard.py`, `tests/test_posting_service.py`, `tests/test_secret_store.py`, `tests/test_dashboard.py`
- 동결: `storage.py`, `guard.py`, `drafts.py`
- 하지 말 것: 페어링·간격·저장소 설계 변경(지적 범위 밖)

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(dashboard,settings,posting): 라운드 2 검토 지적 반영 (R2-T4)`, 본문 `Spec: IMP-31 IMP-32 IMP-33  Task: R2-T4` + Verify 줄

## 게이트 입력
```json
{"task_id": "R2-T4", "spec": "IMP-31",
 "allowed_files": ["src/marketing_agent/posting_service.py", "src/marketing_agent/dashboard_settings.py", "src/marketing_agent/secret_store.py",
                   "src/marketing_agent/dashboard.py", "tests/test_posting_service.py", "tests/test_secret_store.py", "tests/test_dashboard.py"],
 "new_tests": ["tests/test_posting_service.py::test_cooldown_and_daily_limit_have_korean_message",
               "tests/test_secret_store.py::test_transient_unreadable_store_is_not_quarantined",
               "tests/test_secret_store.py::test_corrupt_store_quarantine_keeps_previous_backups",
               "tests/test_dashboard.py::test_pair_rejects_non_ascii_code_and_cookie",
               "tests/test_dashboard.py::test_pair_cookie_name_includes_port_and_redirect_has_security_headers"],
 "frozen": [{"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/guard.py"}, {"path": "src/marketing_agent/drafts.py"}],
 "baseline_passed": 228}
```
