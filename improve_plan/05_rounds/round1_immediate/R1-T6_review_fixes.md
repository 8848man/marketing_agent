## 작업 R1-T6: 라운드 1 검토 차단 지적 반영 (IMP-27·28·30)

### 1. 목표
라운드 1 검토(logs/r1/R1-review-1.md)의 차단 지적 #1·#2·#3과 권고 #4를 고친다. 각 수정마다 그 허점을 재현하는 테스트를 먼저 쓴다.

### 2. 지적과 수정 내용
| # | 파일 | 문제 | 수정 |
| --- | --- | --- | --- |
| 1 | `scripts/round_gate.py` `check_g3`, `check_g6` | `git diff --name-only`가 이름 변경을 감지해 이전 경로가 빠짐 → 허용 밖 파일을 허용 경로로 옮기면 잘못된 PASS | 두 곳(및 diff를 쓰는 다른 곳)에 `--no-renames` |
| 2 | `scripts/package.py` 금지 이름 판정 | 대소문자 구분 → `Data/`, `.ENV`, `Config.yaml`, `COOKIES`, `login data`, `Chrome-Profile-1` 통과 | 판정 전에 경로를 `\`→`/` 치환 후 `casefold()` |
| 3a | `round_gate.py` `check_g4` | 동결 함수가 base·head 모두 없으면 PASS | 둘 다 없으면 FAIL("동결 대상 없음: <이름>"). 한쪽에만 있으면 지금처럼 변경으로 FAIL |
| 3b | `round_gate.py` 함수 추출 | 데코레이터가 비교에서 빠짐 | 데코레이터 줄부터 함수 끝까지 비교 |
| 3c | `round_gate.py` G6 금지 경로 | `.env`만 정확 일치 | package.py와 같은 규칙: `.env`, `.env.*`(`.env.example` 제외), 루트 `config.yaml`, `data/` — 대소문자 무시 |
| 4 | `src/marketing_agent/posting_service.py` `post_video` | `self.allowed_channels()`가 예외를 던지면 예외가 그대로 전파 | 예외 시 `PostStatus("blocked", "CHANNEL_CONFIG_UNAVAILABLE")` 반환(예약·Chrome 전) |

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 브랜치 `fix/IMP-27-30-round1-immediate`
- 좁은 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_round_gate.py tests/test_package.py tests/test_posting_service.py`

### 4. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_g3_g6_detect_renamed_files` | `tests/test_round_gate.py` | 허용 밖 `secret.py`를 허용 경로 `tests/x.py`로 이동한 커밋 → G3 FAIL. `data/a.txt`를 `tests/a.txt`로 이동 → G6 FAIL |
| `test_g4_missing_frozen_target_fails` | `tests/test_round_gate.py` | 존재하지 않는 함수 이름을 동결하면 FAIL |
| `test_g4_detects_decorator_change` | `tests/test_round_gate.py` | 동결 함수의 데코레이터만 바뀌면 FAIL |
| `test_g6_forbids_env_variants_case_insensitive` | `tests/test_round_gate.py` | `.env.local`, `.ENV` 추가 → FAIL, `.env.example` → PASS |
| `test_find_violations_case_insensitive` | `tests/test_package.py` | `Data/x`, `.ENV`, `Config.yaml`, `COOKIES`, `login data`, `Chrome-Profile-1/a`, `x.DB` 금지, `.env.example`·`src/config.py` 허용 |
| `test_post_video_blocks_when_channel_config_fails` | `tests/test_posting_service.py` | `allowed_channels`가 예외를 던지면 `reason_code == "CHANNEL_CONFIG_UNAVAILABLE"`, poster 미호출, 예약 없음 |
| `test_post_video_blocks_when_channel_config_empty` | `tests/test_posting_service.py` | `allowed_channels=lambda: {}` → `CHANNEL_NOT_ALLOWED`, poster 미호출 (회귀 방지, 수정 전에도 통과 가능) |

### 5. 수정 범위
- 허용: `scripts/round_gate.py`, `scripts/package.py`, `src/marketing_agent/posting_service.py`, `tests/test_round_gate.py`, `tests/test_package.py`, `tests/test_posting_service.py`
- 동결: `storage.py`, `guard.py`
- 하지 말 것: 기존 게이트 출력 형식 변경, 다른 지적(권고 #5~#8) 처리

### 6. 완료 조건
- [ ] 4번 테스트(회귀 방지 제외)가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(gate,package,guard): 라운드 1 검토 차단 지적 반영 (R1-T6)`, 본문 `Spec: IMP-27 IMP-28 IMP-30  Task: R1-T6` + Verify 줄

## 게이트 입력
```json
{"task_id": "R1-T6", "spec": "IMP-27",
 "allowed_files": ["scripts/round_gate.py", "scripts/package.py", "src/marketing_agent/posting_service.py",
                   "tests/test_round_gate.py", "tests/test_package.py", "tests/test_posting_service.py"],
 "new_tests": ["tests/test_round_gate.py::test_g3_g6_detect_renamed_files", "tests/test_round_gate.py::test_g4_missing_frozen_target_fails",
               "tests/test_round_gate.py::test_g4_detects_decorator_change", "tests/test_round_gate.py::test_g6_forbids_env_variants_case_insensitive",
               "tests/test_package.py::test_find_violations_case_insensitive",
               "tests/test_posting_service.py::test_post_video_blocks_when_channel_config_fails"],
 "frozen": [{"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/guard.py"}],
 "baseline_passed": 197}
```
