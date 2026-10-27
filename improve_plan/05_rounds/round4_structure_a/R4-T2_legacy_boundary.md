## 작업 R4-T2: 제품·레거시 경계를 테스트로 고정 (IMP-39, M4)

### 1. 목표
대시보드(제품) 경로가 레거시 CLI 모듈을 import하지 않음을 자동 시험으로 고정하고, 레거시 범위 문서를 현행화한다. 레거시 모듈 이동·삭제와 레거시 테이블 폐기는 하지 않는다(D-017).

### 2. 배경과 근거 [코드 확인]
- 보고서 M4의 CDP 게시 함수는 IMP-01(2026-10-18)에서 이미 제거됐다.
- 남은 레거시: `pipeline.py`, `watcher.py`, `search_budget.py`, `trigger.py`, `classifier.py`, `writer.py`, `config.py`(레거시 설정). `.ucompany/sdd/contracts/legacy-scope.md`가 범위를 정의하고 "레거시 테이블은 마이그레이션 설계와 복구 시험 없이 삭제하지 않는다"고 정한다.
- `storage._dashboard_count`가 레거시 `post_results`를 합산한다. 이는 PDF 일일 한도를 넘지 않게 하는 보수적 동작이라 유지한다.

### 3. 사양
1. `tests/test_legacy_boundary.py`: `ast`로 `dashboard.py`에서 시작하는 상대 import 그래프(`check_sdd.py`의 `dashboard_modules`와 같은 방식)를 만들어, 레거시 모듈 집합과의 교집합이 비어 있음을 단언한다. `__main__.py`는 대시보드·레거시 두 진입점을 모두 가지므로 제외한다.
2. 같은 파일에서 레거시 모듈들이 `poster`·`posting_service`(게시 경로)를 import하지 않음을 단언한다(레거시의 게시 호출 0회 고정).
3. `legacy-scope.md`에 이 시험을 "자동 검사" 항목으로 적고, CDP 제거 완료와 `_dashboard_count` 합산 유지 이유를 한 줄씩 적는다.

### 4. 먼저 작성할 실패 테스트
| 테스트 | 기대 동작 |
| --- | --- |
| `test_dashboard_does_not_import_legacy` | 위 1 |
| `test_legacy_never_imports_posting_path` | 위 2 |
| `test_legacy_scope_doc_mentions_boundary_test` | `legacy-scope.md`에 `test_legacy_boundary.py`가 언급됨 |

(1·2는 현재 코드에서 통과할 수 있다. 그 경우 G1을 위해 3번을 둔다.)

### 5. 수정 범위
- 허용: `tests/test_legacy_boundary.py`, `.ucompany/sdd/contracts/legacy-scope.md`
- 동결: `src/` 전체
- 하지 말 것: 모듈 이동·삭제, 테이블 변경

### 6. 완료 조건
- [ ] 3번 테스트가 수정 전 실패, 수정 후 통과. 1·2가 실패하면 진행하지 말고 보고(경계 위반 발견)
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `test(legacy): 제품·레거시 import 경계 고정 (R4-T2)`, 본문 `Spec: IMP-39  Task: IMP-39` + Verify 줄

## 게이트 입력
```json
{"task_id": "R4-T2", "spec": "IMP-39",
 "allowed_files": ["tests/test_legacy_boundary.py", ".ucompany/sdd/contracts/legacy-scope.md"],
 "new_tests": ["tests/test_legacy_boundary.py::test_legacy_scope_doc_mentions_boundary_test"],
 "frozen": [{"path": "src/marketing_agent/dashboard.py"}, {"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/pipeline.py"}],
 "baseline_passed": 250}
```
