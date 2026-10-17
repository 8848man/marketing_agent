# marketing_agent — SDD 색인

현재 H 개선 적용 결과와 미완료 실환경 수락은 [IMPLEMENTATION_STATUS_2026-10-17.md](../../IMPLEMENTATION_STATUS_2026-10-17.md)에 기록한다. 비판·계획 대비 전체 공백은 [REMEDIATION_GAP_AUDIT_2026-10-17.md](../../REMEDIATION_GAP_AUDIT_2026-10-17.md)를 따른다. H01~H05와 H07~H16은 로컬 자동·정적 확인을 통과했고 H06과 사용자 Python 3.13 재설치 확인은 남아 있다.

현재 요구사항 출처와 권위는 [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md)에 고정한다. 2026-10-17 H 개선은 [비판 검토](../../REVIEW_CRITIQUE_2026-10-17.md) → [개선 계획](../../IMPROVEMENT_PLAN_2026-10-17.md) → `docs/track2-agent`의 H 작업 순서로 추적한다. 날짜별 기록은 [history.md](history.md)의 당시 이력이며 현행 수락 판정이 아니다.

이 폴더는 U 컴퍼니 SDD v0 구조다. 이 색인이 ID·관계 어휘·읽는 순서의 원본이고, `graph.json`은 같은 내용을 기계가 읽도록 옮긴 파생 색인이다. 둘이 다르면 이 파일이 이긴다.

## 읽는 순서

1. `graph.json`의 `focus`인 `FEAT-TRACK2` 기능 문서를 연다.
2. 기능에 연결된 `DOC-TRACK2` 작업 목록의 미완료 체크박스와 현재 우선순위를 확인한다.
3. 작업과 연결된 요구사항·계획·검증 절차 및 필요한 코드만 연다.
4. 작업 후 `tasks.md` 체크박스와 이 색인, `graph.json`, `handoff.md`를 갱신한다.

## 노드

| ID | 종류 | 파일 | 소유하는 사실 |
| --- | --- | --- | --- |
| CON-1 | constitution | [constitution.md](constitution.md) | 프로젝트 원칙, 금지사항, 기술 스택 |
| FEAT-TRACK2 | feature | [feature.md](features/track2-dashboard/feature.md) | Track 2 목표, 현재 판정, 다음 증거 |
| REQ-TRACK2 | requirement | [spec.md](../../docs/track2-agent/spec.md) | PDF 기반 R/B 요구사항 |
| PLAN-TRACK2 | plan | [plan.md](../../docs/track2-agent/plan.md) | 구현 방침과 수락 관문 |
| DOC-TRACK2 | task | [tasks.md](../../docs/track2-agent/tasks.md) | T01~T12의 미완료 수락 작업 |
| VAL-TRACK2 | validation | [validation-protocol.md](../../docs/track2-agent/validation-protocol.md) | G1~G3 및 수락 증거 절차 |
| CODE-TRACK2 | code | [dashboard.py](../../src/marketing_agent/dashboard.py) | 제품의 로컬 HTTP 진입점 |
| CODE-RSS | code | [rss_feed.py](../../src/marketing_agent/rss_feed.py) | RSS 파싱·영상 소속 재조회 |
| CODE-DRAFT | code | [drafts.py](../../src/marketing_agent/drafts.py) | 초안 저장·사람 승인 해시 검증 |
| CODE-TRACK2-UI | code | [dashboard_ui.py](../../src/marketing_agent/dashboard_ui.py) | 3단계 화면과 상태 안내 |
| CODE-AI | code | [ai_client.py](../../src/marketing_agent/ai_client.py) | 제공사별 공통 JSON 호출 인터페이스 |
| CODE-SETTINGS | code | [dashboard_settings.py](../../src/marketing_agent/dashboard_settings.py) | 대시보드 설정·키 파일 경계 |
| CODE-CONTRACTS | code | [dashboard_contracts.py](../../src/marketing_agent/dashboard_contracts.py) | 대시보드 기본·선택 기능 계약 |
| CODE-GENERATOR | code | [draft_generation.py](../../src/marketing_agent/draft_generation.py) | 주입 가능한 AI 초안 생성 계약과 기본 제공사 구현 |
| DOC-PRODUCT | document | [SDD.md](../../SDD.md) | 제품 폴더의 SDD 안내 |
| DOC-ORIGIN | document | [SOURCE_OF_TRUTH.md](../../SOURCE_OF_TRUTH.md) | 외부 PDF 판본과 내부 문서 권위 |
| DOC-HISTORY | document | [history.md](history.md) | 날짜별 작업 이력과 당시 시험 기록 |
| DOC-CONFIG-EXAMPLES | document | [CONFIG_EXAMPLE_CONTRACT.md](../../CONFIG_EXAMPLE_CONTRACT.md) | 예시 설정의 필드·파서·소비 위치 |

## 관계 어휘

| 관계 | 방향 | 의미 |
| --- | --- | --- |
| `governed_by` | 기능 → 헌법 | 기능이 따르는 원칙 |
| `has_requirement` | 기능 → 요구사항 | 기능이 만족할 요구사항 |
| `planned_by` | 기능 → 계획 | 기능의 구현 방침 |
| `has_task` | 기능 → 작업 | 기능의 실행 작업 목록 |
| `implements` | 작업 → 요구사항 | 작업이 구현하는 요구사항 |
| `decided_by` | 계획 → 결정 | 계획이 근거로 삼는 결정 기록 |
| `touches` | 작업 → 코드 | 작업이 바꾸는 코드 |
| `validated_by` | 작업 → 검증 | 작업의 수락 근거 |
| `documented_by` | 기능 → 안내 | 제품 폴더 진입 문서 |

## 변경 이력

- [날짜별 작업 기록](history.md)은 당시 판정과 시험 수를 보존한다. 현재 수락은 적용 상태와 공백 감사 문서를 따른다.
