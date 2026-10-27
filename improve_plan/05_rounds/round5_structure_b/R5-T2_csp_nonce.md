## 작업 R5-T2: 스크립트 CSP에서 unsafe-inline 제거 (IMP-42, M8)

### 1. 목표
대시보드 페이지의 `script-src 'unsafe-inline'`을 요청마다 새로 만드는 nonce로 바꾼다. 페이지의 모든 `<script>`에 그 nonce를 붙인다. 스타일(`style-src 'unsafe-inline'`)은 인라인 `style` 속성이 많아 이번 범위에서 유지한다(기록).

### 2. 배경과 근거 [코드 확인]
- 공통 헤더(`_headers`)의 CSP: `script-src 'unsafe-inline'; style-src 'unsafe-inline'`.
- `dashboard_page.render_page(token, demo=...)`가 여러 스크립트 조각을 `</script>` 앞에 끼워 넣어 페이지를 만든다. 인라인 이벤트 핸들러(`onclick=` 등)는 없다(grep 확인).

### 3. 사양
1. 페이지 응답마다 `secrets.token_urlsafe(16)` nonce를 만들고, `render_page(token, demo=..., nonce=...)`가 모든 `<script` 여는 태그에 `nonce="…"`를 붙인다.
2. 페이지 응답의 CSP는 `script-src 'nonce-<값>'`(unsafe-inline 없음). JSON·403·303 응답의 CSP는 `script-src 'none'`.
3. 나머지 CSP 지시어는 그대로 둔다.
4. 렌더링된 페이지에서 스크립트 본문을 뽑아 `node --check`로 문법을 확인하는 테스트를 둔다(node 없으면 skip).
5. 가능하면(Playwright Chromium이 설치되어 있으면) 헤드리스로 페이지를 열어 CSP 위반 콘솔 메시지가 0건인지 확인하는 테스트를 두고, 브라우저가 없으면 skip.

### 4. 먼저 작성할 실패 테스트 (`tests/test_dashboard.py`)
| 테스트 | 기대 동작 |
| --- | --- |
| `test_page_csp_uses_nonce_without_unsafe_inline_script` | 페이지 응답 CSP의 `script-src`에 `unsafe-inline` 없음, `nonce-` 있음 |
| `test_every_script_tag_has_matching_nonce` | 페이지의 모든 `<script` 태그 nonce가 헤더 nonce와 같음 |
| `test_nonce_changes_per_request` | 두 번 받은 페이지의 nonce가 다름 |
| `test_rendered_scripts_pass_node_check` | 위 4 |

### 5. 수정 범위
- 허용: `src/marketing_agent/dashboard.py`, `src/marketing_agent/dashboard_page.py`, `src/marketing_agent/dashboard_ui.py`, `tests/test_dashboard.py`
- 동결: `posting_service.py`, `storage.py`, `dashboard_settings.py`
- 하지 말 것: 스크립트 동작 변경, 외부 스크립트 파일 도입

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(dashboard): 스크립트 CSP를 요청별 nonce로 (R5-T2)`, 본문 `Spec: IMP-42  Task: IMP-42` + Verify 줄

## 게이트 입력
```json
{"task_id": "R5-T2", "spec": "IMP-42",
 "allowed_files": ["src/marketing_agent/dashboard.py", "src/marketing_agent/dashboard_page.py", "src/marketing_agent/dashboard_ui.py", "tests/test_dashboard.py"],
 "new_tests": ["tests/test_dashboard.py::test_page_csp_uses_nonce_without_unsafe_inline_script", "tests/test_dashboard.py::test_every_script_tag_has_matching_nonce",
               "tests/test_dashboard.py::test_nonce_changes_per_request"],
 "frozen": [{"path": "src/marketing_agent/posting_service.py"}, {"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/dashboard_settings.py"}],
 "baseline_passed": 263}
```
