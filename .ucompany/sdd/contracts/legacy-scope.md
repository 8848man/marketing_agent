# 레거시 코드 사용 범위

기본 제품 흐름은 RSS 목록 → AI 초안 → 사람 승인 → 대시보드의 명시적 게시 클릭이다. 아래 보조 흐름은 이 경로와 동일한 공개 게시 권한을 갖지 않는다.

| 모듈 | 현재 사용처 | 결정 | 남은 정리 |
| --- | --- | --- | --- |
| `pipeline.py` | `__main__.py`의 보조 CLI `run_cycle` | 탐지·초안·로그만 유지, 게시 호출 0회 | 대시보드와 별도 데이터 모델·오류 계약을 유지할지 결정 |
| `watcher.py`, `search_budget.py`, `trigger.py` | 보조 CLI의 키워드·조회수 탐지 | 기본 RSS 대시보드와 분리 | B04 필요성 확정 전 기본 제품에 연결하지 않음 |
| `classifier.py`, `writer.py` | 보조 CLI와 오프라인 fixture | 초안 작성·품질 규칙 일부 재사용 | 공통 초안 계약으로 통합 가능성 평가 |
| ~~`poster.py`의 `ChromeBrowser`, `submit_comment`, `reconcile_pending`, `validate_cdp_url`~~ | **2026-10-18 제거(IMP-01)** | 사용자가 띄운 Chrome에 CDP로 붙는 과거 게시 API. 호출처가 시험뿐이었고 심사 코드 검사에서 위험 신호가 되므로 삭제했다. | 없음. `config.legacy.example.yaml`의 `chrome_debug_url`은 보조 CLI 설정 호환용으로만 파싱되고 어떤 코드도 연결하지 않는다. |
| ~~`dashboard --chrome-user-data-dir`, `--chrome-profile-directory`~~ | **2026-10-18 제거(IMP-02)** | 기본값이 macOS 기본 Chrome 데이터 폴더(앱 폴더 밖)를 가리켰다. | 게시기는 앱 폴더 안에서 미설정 상태로 시작하고, 저장된 앱 전용 프로필(`data/dashboard/chrome-profile-*`)만 적용한다. |
| `posting_service.py`, `poster.py`의 `VisibleChromePoster` | 현재 대시보드의 승인·예약·Chrome 경로 | 제품 게시 경로 | 실환경 수락 전 유지 |

레거시 SQLite 테이블·과거 시도 기록은 데이터 마이그레이션 설계와 복구 시험 없이 삭제하지 않는다. 레거시 함수가 import 가능하다는 사실과 제품 UI에서 접근 가능하다는 사실을 구분한다. 공개 게시의 현재 사용자 흐름은 대시보드의 승인된 대상·문안에 대한 클릭뿐이다. 보조 CLI는 `config.legacy.example.yaml`을 사용한다.

## 자동 검사

- `tests/test_legacy_boundary.py`가 대시보드 import 그래프(`dashboard.py`에서 상대 import를 따라감, `__main__.py` 제외)에 레거시 모듈(pipeline, watcher, search_budget, trigger, classifier, writer, config)이 없음을, 그리고 레거시 모듈이 게시 경로(`poster`, `posting_service`)를 import하지 않음을 고정한다. 레거시가 제품을 참조하는 것은 허용하고 제품이 레거시를 참조하는 것은 금지한다.
- CDP 게시 API는 IMP-01(2026-10-18)에서 제거를 마쳤다.
- `storage._dashboard_count`가 레거시 `post_results`를 합산하는 동작은 PDF 일일 한도를 넘지 않게 하는 보수적 동작이라 유지한다.
- D-019: 제품 `drafts.py`가 레거시 `writer.py`에서 가져오던 `LINK` 정규식을 `drafts.py`로 옮겼다(값 동일). `writer.py`가 `drafts`에서 가져온다.
