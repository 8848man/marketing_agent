## 작업 R4-T1: 공통 외부 호출 계층 (IMP-38, M5)

### 1. 목표
4곳에 흩어진 리다이렉트 차단 클래스와 응답 크기 제한 읽기를 `http_client.py` 하나로 모은다. **각 모듈의 바깥 동작(반환값·오류 코드)은 바꾸지 않는다.**

### 2. 배경과 근거 [코드 확인]
| 모듈 | 리다이렉트 처리 | 크기 상한 | 오류 매핑 |
| --- | --- | --- | --- |
| `ai_client.py` | `_NoRedirect` → `None`(urllib가 3xx `HTTPError`) | `MAX_RESPONSE` | 제공사별 코드 |
| `captions.py` | 같음 | 200,000 | `COMMENTS_KEY_INVALID`/`COMMENTS_UNAVAILABLE` |
| `pipeline.py`(레거시) | 같음 | 1,000,000 | `YOUTUBE_API_FAILED` |
| `rss_feed.py` | `FeedError("RSS_REDIRECT_BLOCKED")` 예외 | `MAX_FEED_BYTES` | `RSS_HTTP_<코드>`/`RSS_NETWORK` |
- `posting_service.py`가 `rss_feed._NoRedirect`를 import한다(`recheck_test_video`).

### 3. 사양
1. 새 모듈 `src/marketing_agent/http_client.py`:
   - `class NoRedirectHandler(HTTPRedirectHandler)`: 생성자 `on_redirect: Callable[[], Exception] | None = None`. `on_redirect`가 있으면 그 예외를 던지고, 없으면 `None`을 반환한다(기존 두 동작 모두 표현).
   - `def opener(on_redirect=None)`: `build_opener(NoRedirectHandler(on_redirect))`.
   - `def read_limited(response, max_bytes) -> bytes`: `max_bytes + 1`바이트를 읽고, 넘으면 `ResponseTooLarge`(ValueError 하위) 예외.
2. 네 모듈의 `_NoRedirect` 정의를 지우고 `http_client`를 쓴다. `rss_feed`는 `on_redirect=lambda: FeedError("RSS_REDIRECT_BLOCKED")`. 각 모듈의 크기 초과 처리는 기존 오류 코드로 바꿔 올린다(예: rss는 기존과 같은 코드).
3. `rss_feed._NoRedirect`를 import하던 곳은 `http_client`를 쓰도록 바꾼다. 하위 호환 별칭은 두지 않는다.
4. `check_sdd.py`가 대시보드 import 모듈의 색인 등록을 검사하므로 `graph.json`·`00_index.md`에 노드를 추가한다.

### 4. 먼저 작성할 실패 테스트 (`tests/test_http_client.py`, 새 파일)
| 테스트 | 기대 동작 |
| --- | --- |
| `test_no_redirect_returns_none_by_default` | 로컬 `http.server`가 302를 주면 `opener().open()`이 `HTTPError`(code 302), 대상 URL 요청 0회 |
| `test_no_redirect_raises_custom_error` | `on_redirect`를 주면 그 예외가 그대로 올라옴 |
| `test_read_limited_rejects_oversize` | 상한+1 바이트 응답 → `ResponseTooLarge`, 상한 이하는 그대로 |
| `test_single_redirect_handler_definition` | `src/marketing_agent` 아래 `class .*Redirect.*HTTPRedirectHandler` 정의가 `http_client.py` 한 곳뿐 |

### 5. 수정 범위
- 허용: `src/marketing_agent/http_client.py`, `ai_client.py`, `captions.py`, `pipeline.py`, `rss_feed.py`, `posting_service.py`, `tests/test_http_client.py`, `.ucompany/sdd/graph.json`, `.ucompany/sdd/00_index.md`, `EXTERNAL_IO_POLICY.md`(있으면 "공통 전송 계층 미완" 문구 갱신)
- 동결: `posting_service.PostingService.post_video`, `storage.py`, `dashboard.py`
- 하지 말 것: 타임아웃·재시도 횟수·오류 코드·호스트 검사 변경

### 6. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 기존 테스트 전부 단언 변경 없이 통과, V1 0·0
- [ ] 커밋 1개: `refactor(http): 리다이렉트 차단·크기 제한 공통 계층 (R4-T1)`, 본문 `Spec: IMP-38  Task: IMP-38` + Verify 줄

## 게이트 입력
```json
{"task_id": "R4-T1", "spec": "IMP-38",
 "allowed_files": ["src/marketing_agent/http_client.py", "src/marketing_agent/ai_client.py", "src/marketing_agent/captions.py", "src/marketing_agent/pipeline.py",
                   "src/marketing_agent/rss_feed.py", "src/marketing_agent/posting_service.py", "tests/test_http_client.py",
                   ".ucompany/sdd/graph.json", ".ucompany/sdd/00_index.md", "EXTERNAL_IO_POLICY.md", ".ucompany/sdd/contracts/*.md"],
 "new_tests": ["tests/test_http_client.py"],
 "frozen": [{"path": "src/marketing_agent/posting_service.py", "function": "PostingService.post_video"},
            {"path": "src/marketing_agent/storage.py"}, {"path": "src/marketing_agent/dashboard.py"}],
 "baseline_passed": 250}
```
