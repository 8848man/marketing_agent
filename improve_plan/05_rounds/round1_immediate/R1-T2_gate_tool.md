## 작업 R1-T2: 게이트 도구 `scripts/round_gate.py` (IMP-27)

### 1. 목표
작업 커밋 하나가 계약서를 지켰는지 G1~G6을 자동 판정하는 명령행 도구를 만든다. 정의는 `improve_plan/04_agent_workflow/verification_gates.md`.

### 2. 배경과 근거
- 하위 에이전트 보고를 믿지 않고 실행으로 확인하기 위한 도구(D-003, 방법론 원칙 2).
- 표준 라이브러리만 쓴다. pytest는 `sys.executable -m pytest`로 호출한다.

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 브랜치 `fix/IMP-27-30-round1-immediate`
- 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_round_gate.py`

### 4. 명령행 사양
```
python scripts/round_gate.py --contract <계약서.md> --base <커밋> --head <커밋> [--report <보고서.md>] [--log <기록.md>]
```
- 계약서에서 `## 게이트 입력` 아래 첫 번째 ```json 블록을 읽는다. 키: `task_id`, `spec`(예 "IMP-28"), `allowed_files`(glob 목록), `new_tests`(pytest 노드 ID 목록), `frozen`(`{"path"}` 또는 `{"path","function"}` 목록), `baseline_passed`(정수).
- 게이트 (각각 통과/실패, 하나라도 실패면 종료 코드 1; 실행 불가는 "보류"로 종료 코드 2):
  - G0: `--report`가 주어지면 `## 구현 보고`, `- 결과:`, `- 커밋:`, `- 변경 파일:`, `- 실패 확인:`, `- 통과 확인:` 항목이 모두 있는지.
  - G1: base를 임시 worktree(`$HOME/gate-wt/<짧은해시>`, 저장소 밖)로 꺼내 `new_tests`가 들어 있는 테스트 파일들을 head 버전으로 덮어쓴 뒤 `new_tests` 실행 → 통과하면 실패. head에서 실행 → 모두 통과해야 함. 끝나면 worktree 제거(`git worktree remove --force`).
  - G2: head에서 `check_sdd.py`·`safety_scan.py --strict` 종료 코드 0, 전체 pytest 실패 0·통과 수 ≥ `baseline_passed`, `--collect-only -q`의 수집 수가 base 이상.
  - G3: `git diff --name-only base..head`의 모든 경로가 `allowed_files` glob 중 하나에 맞음(`fnmatch`).
  - G4: `frozen` 항목마다 base·head 내용 동일. `function`이 있으면 `ast`로 해당 최상위 함수/메서드(`Class.method` 표기 허용) 소스를 추출해 비교.
  - G5: `git rev-list --count base..head` = 1, 제목에 `task_id`, 본문에 `Spec: <spec>`, `git status --porcelain` 비어 있음.
  - G6: diff에 추가된 줄에 비밀 패턴(`sk-[A-Za-z0-9_-]{20,}`, `AIza[0-9A-Za-z_-]{35}`, `xai-[A-Za-z0-9]{20,}`, 이메일 주소 패턴 — 단 `noreply` 포함 줄 제외) 없음, 변경 경로에 `.env`, `config.yaml`, `data/` 없음.
- 출력: 게이트별 한 줄(`G1 PASS …`/`G1 FAIL <이유>`) + 마지막 줄 `RESULT PASS|FAIL|HOLD`. `--log`가 주어지면 같은 내용을 마크다운으로 저장.

### 5. 먼저 작성할 실패 테스트 (`tests/test_round_gate.py`)
모든 테스트는 `tmp_path`에 임시 git 저장소를 만들어 쓴다(실제 저장소를 건드리지 않음). G2는 실제 pytest 전체 실행이 무거우므로 테스트에서는 G2를 끌 수 있는 내부 함수 단위로 검사한다.

| 테스트 | 기대 동작 |
| --- | --- |
| `test_parse_contract_reads_gate_json` | 계약서 마크다운에서 게이트 입력 JSON을 읽는다 |
| `test_g3_rejects_file_outside_allowed` | 허용 밖 파일 변경 시 G3 FAIL |
| `test_g4_detects_frozen_function_change` | 동결 함수 본문이 바뀌면 G4 FAIL, 다른 함수만 바뀌면 PASS |
| `test_g5_requires_single_commit_with_ids` | 커밋 2개, 또는 제목에 작업 ID 없음, 또는 `Spec:` 줄 없음이면 FAIL |
| `test_g6_flags_secret_and_forbidden_paths` | 추가된 줄의 키 패턴, `data/` 경로 변경 시 FAIL |
| `test_g1_requires_fail_before_pass_after` | base에서도 통과하는 새 테스트면 FAIL, base 실패·head 통과면 PASS |
| `test_g0_checks_report_sections` | 필수 항목 누락 보고서면 FAIL |

### 6. 수정 범위
- 허용: `scripts/round_gate.py`, `tests/test_round_gate.py`
- 금지: `src/` 전체, 기존 테스트 파일
- 하지 말 것: 외부 패키지 추가, 실제 저장소에서 worktree를 만든 채 남겨 두기

### 7. 완료 조건
- [ ] 5번 테스트가 구현 전 실패, 구현 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `chore(gate): 라운드 작업 게이트 도구 (R1-T2)`, 본문 `Spec: IMP-27  Task: IMP-27` + Verify 줄

## 게이트 입력
```json
{"task_id": "R1-T2", "spec": "IMP-27",
 "allowed_files": ["scripts/round_gate.py", "tests/test_round_gate.py"],
 "new_tests": ["tests/test_round_gate.py"],
 "frozen": [{"path": "src/marketing_agent/posting_service.py"}, {"path": "src/marketing_agent/storage.py"}],
 "baseline_passed": 177}
```
