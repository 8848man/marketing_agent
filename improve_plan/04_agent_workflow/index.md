# 04. 하위 에이전트 운용 방법론

메인(Opus 5.5)과 하위 에이전트(Sonnet 5.5) 사이의 접점을 계약서·보고서·게이트로 고정해, 모델이 바뀌어도 결과를 같은 기준으로 판정합니다.

| 파일 | 내용 |
| --- | --- |
| [roles_and_models.md](roles_and_models.md) | 역할 구분, 모델 배정, 권한 범위 |
| [round_loop.md](round_loop.md) | 계획 → 구현 → 검토 → 게이트의 라운드 루프 |
| [task_contract_template.md](task_contract_template.md) | 메인 → 구현 에이전트 작업 계약서 양식 |
| [report_format.md](report_format.md) | 구현·검토 에이전트의 결과 보고 양식 |
| [verification_gates.md](verification_gates.md) | 성공·실패를 기계적으로 판정하는 게이트 |
| [review_checklist.md](review_checklist.md) | 검토 에이전트 체크리스트와 지적 등급 |
| [escalation_and_metrics.md](escalation_and_metrics.md) | 재시도·에스컬레이션 규칙, 모델 구성 재평가 지표 |
| [repo_conventions.md](repo_conventions.md) | 저장소 자체 절차(SDD WF-1)와의 대응, 커밋·브랜치 규칙, 안전 규칙 |
| [agent_briefing.md](agent_briefing.md) | 하위 에이전트에 계약서와 함께 넘기는 공통 지시문 |

## 핵심 원칙

1. **계약서가 유일한 지시서입니다.** 하위 에이전트는 이 대화의 맥락 없이 시작하므로, 필요한 정보는 모두 계약서에 있어야 합니다.
2. **보고는 주장일 뿐입니다.** 메인은 보고 내용을 게이트로 다시 실행해 확인합니다.
3. **판단이 필요한 것만 모델이 판단합니다.** 실행으로 확인할 수 있는 것은 스크립트로 판정합니다.
4. **구현자와 검토자는 분리합니다.** 검토 에이전트는 구현 과정을 모르는 상태로 시작합니다.
