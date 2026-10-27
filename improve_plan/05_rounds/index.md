# 05. 라운드별 계획

각 파일은 라운드의 작업 목록, 작업 계약서(계획 단계에서 작성), 게이트 판정 기록을 담습니다.

| 파일 | 라운드 | 상태 | 브랜치 |
| --- | --- | --- | --- |
| [round1_immediate/](round1_immediate/index.md) | 1. 즉시 조치 | 완료 | `fix/IMP-27-30-round1-immediate` |
| [round2_approval_integrity/](round2_approval_integrity/index.md) | 2. 보안·승인 무결성 | 완료 | `fix/IMP-31-33-round2-approval-integrity` |
| [round3_operations/](round3_operations/index.md) | 3. 운영 안정성 | 완료 | `fix/IMP-34-37-round3-operations` |
| [round4_structure_a/](round4_structure_a/index.md) | 4. 구조 개선 A | 구현 | `refactor/IMP-38-40-round4-structure-a` |
| [round5_structure_b.md](round5_structure_b.md) | 5. 구조 개선 B | 대기 | 계획 시 결정 |

## 라운드 파일 공통 구성

1. 목표 — 라운드가 끝나면 달라지는 것
2. 작업 목록 — ID, 내용, 대상 위험, 상태
3. 작업 계약서 — 계획 단계에서 채움 (150줄을 넘으면 `roundN_…/` 폴더로 분리)
4. 결정 필요 사항
5. 게이트 판정 — 라운드 종료 시 기록
