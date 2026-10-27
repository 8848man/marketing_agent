## 작업 R5-T3: 과제 고정값 모음, 모델 기본값 단일화, 앱 루트 검증 (IMP-43, L3·L6·L8)

### 1. 목표
(1) "PDF 고정" 값(브랜드 `운명원`, 일일 10개)을 한 모듈의 상수로 모은다(값은 바꾸지 않음, D-018). (2) 레거시 `ClaudeClient`의 기본 모델을 제공사 등록부(`PROVIDERS`)의 Claude 기본값과 같게 한다. (3) 앱 루트(`APP_ROOT`)가 실제 앱 폴더인지 확인한다.

### 2. 배경과 근거 [코드 확인]
- `dashboard_settings.py`에 `"운명원"`과 `10`이 여러 곳(약 27·46·47·368·372·375·376·447·730행)에 하드코딩. `posting_service`·`storage`의 `daily_limit=10` 기본값.
- `ai_client.py` `ClaudeClient.__init__(model="claude-sonnet-4-5")` vs 등록부 기본 `claude-sonnet-4-6`. 모델명은 `validate_model` 정규식만 검사하므로 사용자가 다른 모델을 입력할 수 있다(프리셋은 제안일 뿐).
- `__main__.py` `APP_ROOT = Path(__file__).resolve().parents[2]` — editable 설치가 아니면 site-packages 상위를 가리킨다. 보고서의 macOS Chrome 경로 옵션은 IMP-02에서 이미 제거됨.

### 3. 사양
1. 새 모듈 `task_constraints.py`: `BRAND_NAME = "운명원"`, `DAILY_MAX_COMMENTS = 10`, 각 상수에 근거(PDF 쪽) 주석. 위 하드코딩을 이 상수로 바꾼다(값·오류 코드 동일).
2. `ClaudeClient` 기본 모델을 `PROVIDERS["claude"][0]`로.
3. `__main__.py`: `APP_ROOT` 계산 후 `APP_ROOT / "pyproject.toml"`이 있고 그 안에 `name = "marketing-agent"`가 있는지 확인. 아니면 환경변수 `MARKETING_AGENT_HOME`(같은 검사)을 쓰고, 그것도 아니면 `SystemExit`로 "앱 폴더에서 `pip install -e .` 후 실행하세요" 안내. 경로 제한(`_app_path`) 동작은 그대로.
4. `graph.json`·`00_index.md`에 새 모듈 노드 추가.

### 4. 먼저 작성할 실패 테스트
| 테스트 | 파일 | 기대 동작 |
| --- | --- | --- |
| `test_task_constraints_single_source` | `tests/test_config.py` | `src/marketing_agent`에서 `task_constraints.py` 밖의 `"운명원"` 문자열 리터럴이 `dashboard_settings.py`에 0개(프롬프트·UI 문구는 대상 아님) |
| `test_claude_client_default_matches_registry` | `tests/test_config.py` | `ClaudeClient(api_key="x").model == PROVIDERS["claude"][0]` |
| `test_app_root_validation` | `tests/test_config.py` | 가짜 폴더(pyproject 없음)·환경변수 지정 폴더(정상) 각각에서 루트 판정 함수가 거부/수락 |

### 5. 수정 범위
- 허용: `src/marketing_agent/task_constraints.py`, `dashboard_settings.py`, `ai_client.py`, `__main__.py`, `posting_service.py`, `tests/test_config.py`, `.ucompany/sdd/graph.json`, `.ucompany/sdd/00_index.md`
- 동결: `storage.py`, `drafts.py`, `prompt_policy.py`(프롬프트 변경 시 문서 동기화 필요하므로 금지)
- 하지 말 것: 고정값 변경, 오류 코드 변경

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `refactor(config): 과제 고정값 단일화, 모델 기본값·앱 루트 검증 (R5-T3)`, 본문 `Spec: IMP-43  Task: IMP-43` + Verify 줄

## 게이트 입력
```json
{"task_id": "R5-T3", "spec": "IMP-43",
 "allowed_files": ["src/marketing_agent/task_constraints.py", "src/marketing_agent/dashboard_settings.py", "src/marketing_agent/ai_client.py",
                   "src/marketing_agent/__main__.py", "src/marketing_agent/posting_service.py", "tests/test_config.py",
                   ".ucompany/sdd/graph.json", ".ucompany/sdd/00_index.md"],
 "new_tests": ["tests/test_config.py::test_task_constraints_single_source", "tests/test_config.py::test_claude_client_default_matches_registry",
               "tests/test_config.py::test_app_root_validation"],
 "frozen": [{"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/drafts.py"}, {"path": "src/marketing_agent/prompt_policy.py"}],
 "baseline_passed": 263}
```
