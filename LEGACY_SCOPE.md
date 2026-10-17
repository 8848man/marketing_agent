# 레거시 코드 사용 범위

기본 제품 흐름은 RSS 목록 → AI 초안 → 사람 승인 → 대시보드의 명시적 게시 클릭이다. 아래 보조 흐름은 이 경로와 동일한 공개 게시 권한을 갖지 않는다.

| 모듈 | 현재 사용처 | 결정 | 남은 정리 |
| --- | --- | --- | --- |
| `pipeline.py` | `__main__.py`의 보조 CLI `run_cycle` | 탐지·초안·로그만 유지, 게시 호출 0회 | 대시보드와 별도 데이터 모델·오류 계약을 유지할지 결정 |
| `watcher.py`, `search_budget.py`, `trigger.py` | 보조 CLI의 키워드·조회수 탐지 | 기본 RSS 대시보드와 분리 | B04 필요성 확정 전 기본 제품에 연결하지 않음 |
| `classifier.py`, `writer.py` | 보조 CLI와 오프라인 fixture | 초안 작성·품질 규칙 일부 재사용 | 공통 초안 계약으로 통합 가능성 평가 |
| `poster.py`의 `ChromeBrowser`, `submit_comment`, `reconcile_pending` | 직접 호출 가능한 과거 CDP 게시 API와 회귀 시험 | 기본/주기 CLI에서 호출하지 않음 | 지원 API로 유지할지, 마이그레이션 후 제거할지 결정. 무단 공개 게시 진입점으로 문서화하지 않음 |
| `posting_service.py`, `poster.py`의 `VisibleChromePoster` | 현재 대시보드의 승인·예약·Chrome 경로 | 제품 게시 경로 | 실환경 수락 전 유지 |

레거시 SQLite 테이블·과거 시도 기록은 데이터 마이그레이션 설계와 복구 시험 없이 삭제하지 않는다. 레거시 함수가 import 가능하다는 사실과 제품 UI에서 접근 가능하다는 사실을 구분한다. 공개 게시의 현재 사용자 흐름은 대시보드의 승인된 대상·문안에 대한 클릭뿐이다. 보조 CLI는 `config.legacy.example.yaml`을 사용한다.
