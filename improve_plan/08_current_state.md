# 08. 현재 상태

> 새 세션은 이 파일부터 읽습니다. 절차는 [07_resume_protocol.md](07_resume_protocol.md).

| 항목 | 값 |
| --- | --- |
| 갱신 시각 | 2026-10-27 15:15 KST |
| 브랜치 / HEAD | `improve/r1-immediate` / 이 파일을 포함한 커밋 (`git log -1`로 확인) |
| 현재 라운드 · 단계 | 라운드 1 · 계획 |
| 테스트 기준선 | 177 passed, 0 failed (`$HOME/venv-ma`, Python 3.11.17) |
| V1 정적 검사 | `check_sdd.py` 0 error, `safety_scan.py --strict` 0 fail (improve_plan 추가 후) |

## 작업별 상태 (라운드 1)

| ID | 상태 | 비고 |
| --- | --- | --- |
| R1-T0 | 완료 | 테스트 환경 (D-007) |
| R1-T1 | 완료 | 기준선 177 |
| R1-T2 | 계획 | 게이트 도구 `scripts/round_gate.py` |
| R1-T3 | 계획 | H2 — 코드 확인 완료: `guard.check_rss_membership`이 `rss_feed.CHANNELS`만 허용, `posting_service.py` 222행 호출부. `__main__.py`는 이미 `recheck`에 `settings.channels()`를 넘김 |
| R1-T4 | 계획 | M6 — `captions.YouTubeCaptions.fetch`가 ImportError를 `failure_reason`으로 삼키고 `VideoEvidence.collect`가 사유를 알리지 않음 |
| R1-T5 | 계획 | H4 — README에 "폴더 압축 배포" 안내는 현재 없음. `git archive`(추적 파일만) 기반 패키징 + 금지 패턴 검사로 설계 예정 |

## 다음 행동

**저장소 자체 작업 절차(SDD, `.ucompany/sdd/workflow.md` WF-1)를 improve_plan 방법론에 반영한 뒤 라운드 1 계약서를 작성합니다.**

## 진행 중이던 것

- `AGENTS.md`와 `workflow.md`를 읽던 중. 확인된 저장소 규칙:
  - 기능 변경은 `features/track2-dashboard/spec.md`(R-… ID, 수락 기준) → `plan.md` → `tasks.md` 순으로 먼저 기록
  - 커밋 메시지에 `Spec: R-…  Task: …  Verify: V1 …, V2 …` 포함
  - 검증 V1 = `check_sdd.py` + `safety_scan.py --strict`, V2 = pytest
  - 브랜치 규칙 `<유형>/<작업ID>-<설명>`, Merge commit, 마감 시 `tasks.md`·`00_index.md`·`graph.json`·`handoff.md` 갱신
  - 대시보드가 import하는 새 모듈은 `graph.json` 노드 등록 필요 (`check_sdd.py` 검사)
- 아직 확인 못 한 것: `spec.md`·`tasks.md`의 마지막 IMP/R 번호와 항목 형식

## 미결 질문

- 라운드 브랜치 이름을 저장소 규칙(`<유형>/<작업ID>-<설명>`)에 맞춰 바꿀지 (현재 `improve/r1-immediate`)
- `chore/normalize-eol` push·병합 (사용자가 Windows에서 수행)
