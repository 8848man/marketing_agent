## 작업 R1-T7: G6 이메일 검사 한글 접두 회귀 수정 (IMP-27)

재검토 2회차 차단 지적 #1 반영. G6에서 추가 줄의 이스케이프 시퀀스(`\n` 등)를 공백으로 바꾼 뒤 ASCII 후방 탐색 이메일 정규식으로 검사한다. 한글 접두·따옴표·공백·줄 시작·괄호·`mailto:` 뒤 이메일은 FAIL, `\n@functools.cache`와 데코레이터 줄은 PASS.

## 게이트 입력
```json
{"task_id": "R1-T7", "spec": "IMP-27",
 "allowed_files": ["scripts/round_gate.py", "tests/test_round_gate.py"],
 "new_tests": ["tests/test_round_gate.py"],
 "frozen": [{"path": "scripts/package.py"}, {"path": "src/marketing_agent/posting_service.py"}],
 "baseline_passed": 205}
```
