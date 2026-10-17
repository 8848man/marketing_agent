# marketing_agent — SDD 색인

이 폴더(`.ucompany/sdd/`)가 제품의 **유일한 SDD 위치**다(2026-10-18 통합, [ADR-0001](decisions/ADR-0001-sdd-consolidation.md)). 이 색인이 ID·관계 어휘·읽는 순서의 원본이고, `graph.json`은 같은 내용을 기계가 읽도록 옮긴 파생 색인이다. 둘이 다르면 이 파일이 이긴다. 정합성은 `python .ucompany/scripts/check_sdd.py`로 검사한다.

**현재 상태(2026-10-18):** 개선 사이클의 현행 판정은 [improvements/2026-10-17/05-plan-validity-review.md](improvements/2026-10-17/05-plan-validity-review.md)를 따른다. 제출 전 최우선 공백은 안전 규칙 G-01(Google 로그인·YouTube 홈 열기), 초안 저장소 포함 G-02, 실행 기록 화면 G-03, 초안 품질 G-04, Mac 수락 H06이다.

## 폴더 구조

```text
.ucompany/
├─ scripts/                  check_sdd.py · safety_scan.py (V1 검증, CI에서도 실행)
└─ sdd/
   ├─ 00_index.md            이 색인 (ID·관계·읽는 순서의 원본)
   ├─ graph.json             파생 기계 색인 (focus = FEAT-TRACK2)
   ├─ constitution.md        프로젝트 원칙·금지사항
   ├─ workflow.md            Spec → 구현 → 검증 → GitHub → 마감
   ├─ source-of-truth.md     원요구사항 PDF 판본·문서 권위 순서
   ├─ handoff.md             최신 인계 (맨 위가 최신)
   ├─ history.md             날짜별 작업 이력 (현행 판정 아님)
   ├─ contracts/             설정 예시·AI 제공사·외부 요청·레거시 범위 계약
   ├─ decisions/             ADR-####
   ├─ features/track2-dashboard/
   │  ├─ feature.md          기능 진입점
   │  ├─ spec.md · plan.md · tasks.md · validation-protocol.md · checklist.md
   │  └─ reviews/            작성 당시 검토 기록 (3·4차 검토, 재사용 감사, 원문 대조)
   └─ improvements/2026-10-17/   01~05 개선 사이클 문서 + 06 과제 적합성 보고서
```

## 읽는 순서

1. [workflow.md](workflow.md)로 작업 단계를 확인한다.
2. `graph.json`의 `focus`인 `FEAT-TRACK2` 기능 문서를 연다.
3. 기능에 연결된 `DOC-TRACK2` 작업 목록의 미완료 체크박스와 현재 우선순위를 확인한다.
4. 작업과 연결된 요구사항·계획·검증 절차 및 필요한 코드만 연다.
5. 작업 후 `tasks.md` 체크박스(증거가 있을 때만), 이 색인, `graph.json`, `handoff.md`를 갱신한다.

## 노드

| ID | 종류 | 파일 | 소유하는 사실 |
| --- | --- | --- | --- |
| CON-1 | constitution | [constitution.md](constitution.md) | 프로젝트 원칙, 금지사항, 기술 스택 |
| WF-1 | workflow | [workflow.md](workflow.md) | Spec→구현→검증→GitHub→마감 단계와 관문 |
| FEAT-TRACK2 | feature | [feature.md](features/track2-dashboard/feature.md) | Track 2 목표, 현재 판정, 다음 증거 |
| REQ-TRACK2 | requirement | [spec.md](features/track2-dashboard/spec.md) | PDF 기반 R/B 요구사항 |
| PLAN-TRACK2 | plan | [plan.md](features/track2-dashboard/plan.md) | 구현 방침과 수락 관문 |
| DOC-TRACK2 | task | [tasks.md](features/track2-dashboard/tasks.md) | T/U/H/IMP 작업과 체크박스 |
| VAL-TRACK2 | validation | [validation-protocol.md](features/track2-dashboard/validation-protocol.md) | G1~G3 및 수락 증거 절차 |
| CHK-TRACK2 | validation | [checklist.md](features/track2-dashboard/checklist.md) | PDF 수락 체크리스트(증거 기준) |
| REV-TRACK2 | document | [reviews/](features/track2-dashboard/reviews/three-pass-review.md) | 작성 당시 검토·재사용 감사·원문 대조 |
| ADR-0001 | decision | [ADR-0001](decisions/ADR-0001-sdd-consolidation.md) | SDD 통합 위치와 이동표 |
| ADR-0002 | decision | [ADR-0002](decisions/ADR-0002-local-threat-model.md) | 로컬 위협 모델(제안) |
| IMP-2026-10-17 | improvement | [improvements/2026-10-17/](improvements/2026-10-17/README.md) | 비판 검토·계획·적용·감사·재검토·적합성 보고서 |
| DOC-ORIGIN | document | [source-of-truth.md](source-of-truth.md) | 외부 PDF 판본과 내부 문서 권위 |
| DOC-HISTORY | document | [history.md](history.md) | 날짜별 작업 이력과 당시 시험 기록 |
| DOC-HANDOFF | document | [handoff.md](handoff.md) | 최신 인계 |
| DOC-CONFIG-EXAMPLES | contract | [config-example.md](contracts/config-example.md) | 예시 설정의 필드·파서·소비 위치 |
| DOC-AI-CONTRACT | contract | [ai-provider.md](contracts/ai-provider.md) | AI 제공사 어댑터 차이 |
| DOC-EXTERNAL-IO | contract | [external-io-policy.md](contracts/external-io-policy.md) | 외부 요청 정책 |
| DOC-LEGACY | contract | [legacy-scope.md](contracts/legacy-scope.md) | 레거시 코드 범위와 제거 기록 |
| TOOL-SDD | tool | [check_sdd.py](../scripts/check_sdd.py) | SDD 링크·그래프 검사 |
| TOOL-SAFETY | tool | [safety_scan.py](../scripts/safety_scan.py) | 안전 규칙 정적 검사 |
| CODE-TRACK2 | code | [dashboard.py](../../src/marketing_agent/dashboard.py) | 제품의 로컬 HTTP 진입점 |
| CODE-RSS | code | [rss_feed.py](../../src/marketing_agent/rss_feed.py) | RSS 파싱·영상 소속 재조회 |
| CODE-DRAFT | code | [drafts.py](../../src/marketing_agent/drafts.py) | 초안 저장·품질 검사·사람 승인 해시 검증 |
| CODE-TRACK2-UI | code | [dashboard_ui.py](../../src/marketing_agent/dashboard_ui.py) | 3단계 화면과 상태 안내 |
| CODE-AI | code | [ai_client.py](../../src/marketing_agent/ai_client.py) | 제공사별 공통 JSON 호출 인터페이스 |
| CODE-SETTINGS | code | [dashboard_settings.py](../../src/marketing_agent/dashboard_settings.py) | 대시보드 설정·키 파일 경계 |
| CODE-CONTRACTS | code | [dashboard_contracts.py](../../src/marketing_agent/dashboard_contracts.py) | 대시보드 기본·선택 기능 계약 |
| CODE-GENERATOR | code | [draft_generation.py](../../src/marketing_agent/draft_generation.py) | 주입 가능한 AI 초안 생성 계약 |
| CODE-PROMPT | code | [prompt_policy.py](../../src/marketing_agent/prompt_policy.py) | 공통 프롬프트 원본(현행 `draft-v5-brand-proper-noun`) |
| CODE-PAGE | code | [dashboard_page.py](../../src/marketing_agent/dashboard_page.py) | 설정·브랜드 관리 다이얼로그 |
| CODE-POSTER | code | [poster.py](../../src/marketing_agent/poster.py) | 앱 전용 프로필 Chrome 게시(유일한 게시 경로) |

## 관계 어휘

| 관계 | 방향 | 의미 |
| --- | --- | --- |
| `governed_by` | 기능 → 헌법·워크플로우 | 기능이 따르는 원칙과 작업 절차 |
| `has_requirement` | 기능 → 요구사항 | 기능이 만족할 요구사항 |
| `planned_by` | 기능 → 계획 | 기능의 구현 방침 |
| `has_task` | 기능 → 작업 | 기능의 실행 작업 목록 |
| `implements` | 작업 → 요구사항 | 작업이 구현하는 요구사항 |
| `decided_by` | 계획 → 결정 | 계획이 근거로 삼는 결정 기록 |
| `touches` | 작업 → 코드 | 작업이 바꾸는 코드 |
| `validated_by` | 작업 → 검증 | 작업의 수락 근거·검사 도구 |
| `documented_by` | 기능 → 안내·계약·기록 | 관련 문서 |
| `improved_by` | 기능 → 개선 사이클 | 비판 검토 기반 개선 기록 |

## 변경 이력

- [날짜별 작업 기록](history.md)은 당시 판정과 시험 수를 보존한다. 현재 수락은 개선 재검토(05)와 `checklist.md`를 따른다.
- 2026-10-17까지 색인 머리말에 있던 "H01~H21 로컬 통과, H06 남음" 요약은 [03-implementation-status.md](improvements/2026-10-17/03-implementation-status.md)에 보존돼 있다.
