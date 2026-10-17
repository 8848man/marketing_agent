---
id: ADR-0001
type: decision
status: accepted
date: 2026-10-18
---

# ADR-0001 — SDD 문서를 `.ucompany/sdd` 한 곳으로 통합

## 맥락

요구사항·계획·작업·검증 문서는 `docs/track2-agent/`에, 색인·헌법·기능 진입점은 `.ucompany/sdd/`에, 문서 권위·계약·개선 기록은 프로젝트 루트에 흩어져 있었다. 그 결과 (1) 루트에 SDD 문서 11개가 쌓여 심사자가 보는 README·PROCESS가 묻혔고, (2) 같은 사실이 세 위치에서 서로 다른 시점으로 서술됐으며(REVIEW DOC-02/04), (3) 깃허브 흐름이 어느 문서에도 정의되지 않았다.

## 결정

사용자 요청(2026-10-18)에 따라 `.ucompany/sdd/`를 유일한 SDD 위치로 정한다.

| 이전 위치 | 새 위치 |
| --- | --- |
| `docs/track2-agent/spec.md`·`plan.md`·`tasks.md`·`validation-protocol.md`·`checklist.md` | `features/track2-dashboard/` |
| `docs/track2-agent/three-pass-review.md`·`fourth-pass-review.md`·`reuse-audit.md`·`source-diff.md` | `features/track2-dashboard/reviews/` (작성 당시 기록) |
| `SOURCE_OF_TRUTH.md` | `source-of-truth.md` |
| `AI_PROVIDER_CONTRACT.md`·`CONFIG_EXAMPLE_CONTRACT.md`·`EXTERNAL_IO_POLICY.md`·`LEGACY_SCOPE.md` | `contracts/` |
| `REVIEW_CRITIQUE_…`·`IMPROVEMENT_PLAN_…`·`IMPLEMENTATION_STATUS_…`·`REMEDIATION_GAP_AUDIT_…` (2026-10-17) | `improvements/2026-10-17/01~04-*.md` |
| `SDD.md` (진입 안내) | 삭제 — `AGENTS.md`와 `00_index.md`가 대신한다 |

추가로 [workflow.md](../workflow.md)(Spec → 구현 → 검증 → GitHub), `.ucompany/scripts/`(검증 스크립트), `.github/`(CI·PR 템플릿)를 만든다. 루트에는 제품 실행과 PDF 제출물에 필요한 파일(README, PROCESS, AGENTS, 설정 예시, `src/`, `tests/`, `drafts/`)만 남긴다.

## 결과

- 문서 이동은 `git mv`로 이력을 보존했다. 내부 상대 링크는 스크립트로 일괄 재작성했고 `check_sdd.py`가 깨진 링크 0개를 확인한다.
- `docs/track2-agent` 경로를 언급하는 과거 기록(이력·개선 기록)은 당시 표현으로 남긴다. 현행 문서에서 이 경로가 나오면 `check_sdd.py`가 오류로 잡는다.
- 원본 PDF는 재배포 권한이 확인되지 않아 여전히 저장소에 넣지 않는다([source-of-truth.md](../source-of-truth.md)).
