## 작업 R5-T4: 라운드 5 검토 권고 정리 (IMP-41·42)

### 1. 목표
라운드 5 검토 권고 #1·#2를 고친다.

### 2. 수정
| # | 파일 | 문제 | 수정 |
| --- | --- | --- | --- |
| 1 | `tests/test_dashboard.py`의 "accounts.google.com 미사용" 소스 검사 | 분리 후 `chrome_launch.py`만 검사(이전에는 `dashboard.py` 전체) | `dashboard.py`·`dashboard_service.py`·`chrome_launch.py` 세 파일 모두 검사 |
| 2 | `dashboard_page.py` `render_page`의 nonce 태그 수 `assert` | `python -O`에서 제거됨 | `if …: raise RuntimeError("SCRIPT_NONCE_MISMATCH")`로 바꾸고, nonce가 빈 문자열이면 `ValueError("NONCE_REQUIRED")` |

### 3. 먼저 작성할 실패 테스트 (`tests/test_dashboard.py`)
| 테스트 | 기대 동작 |
| --- | --- |
| `test_render_page_requires_nonce` | `render_page(token, nonce="")` → `ValueError` |
| `test_render_page_nonce_check_survives_optimize` | `dashboard_page.py` 소스에 `assert`로 nonce를 검사하는 문이 없음(ast) |

### 4. 수정 범위
- 허용: `src/marketing_agent/dashboard_page.py`, `tests/test_dashboard.py`
- 동결: `dashboard.py`, `dashboard_service.py`, `chrome_launch.py`

### 5. 완료 조건
- [ ] 3번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(dashboard): nonce 검사 RuntimeError화, 소스 검사 범위 복원 (R5-T4)`, 본문 `Spec: IMP-41 IMP-42  Task: R5-T4` + Verify 줄

## 게이트 입력
```json
{"task_id": "R5-T4", "spec": "IMP-41",
 "allowed_files": ["src/marketing_agent/dashboard_page.py", "tests/test_dashboard.py"],
 "new_tests": ["tests/test_dashboard.py::test_render_page_requires_nonce", "tests/test_dashboard.py::test_render_page_nonce_check_survives_optimize"],
 "frozen": [{"path": "src/marketing_agent/dashboard.py"}, {"path": "src/marketing_agent/dashboard_service.py"}, {"path": "src/marketing_agent/chrome_launch.py"}],
 "baseline_passed": 276}
```
