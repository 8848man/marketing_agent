# improve_plan — marketing_agent 개선 계획

코드베이스 분석 보고서(2026-10-27)의 위험 항목을 5라운드에 걸쳐 해소하기 위한 정책·진행 방식·라운드별 계획 모음입니다.
메인 에이전트(Opus 5.5)가 계획·판정을 맡고, 하위 에이전트(Sonnet 5.5)가 구현·검토를 맡습니다.

## 읽는 순서

1. [00_document_rules.md](00_document_rules.md) — 이 폴더의 작성 규칙 (150줄 규칙, 인덱스)
2. [01_policy.md](01_policy.md) — 개선 목표, 원칙, 성공 기준
3. [02_risk_register.md](02_risk_register.md) — 위험 항목과 현재 코드 기준 상태
4. [03_roadmap.md](03_roadmap.md) — 5라운드 개요, 브랜치 전략, 라운드 게이트
5. [04_agent_workflow/](04_agent_workflow/index.md) — 하위 에이전트 운용 방법론
6. [05_rounds/](05_rounds/index.md) — 라운드별 작업 계획과 진행 상태
7. [06_decision_log.md](06_decision_log.md) — 결정 기록
8. [07_resume_protocol.md](07_resume_protocol.md) — 중단·재개 프로토콜 (토큰 소진 대비)
9. [08_current_state.md](08_current_state.md) — **현재 진행 상태와 다음 행동 (새 세션은 여기부터)**
10. [logs/](logs/index.md) — 하위 에이전트 보고·게이트 기록
11. [09_final_report/](09_final_report/index.md) — **최종 점검 보고서 (사용자 확인 항목)**

## 도구

- [tools/check_structure.py](tools/check_structure.py) — 이 폴더가 작성 규칙을 지키는지 검사합니다.
  `python3 improve_plan/tools/check_structure.py`

## 현재 상태

[08_current_state.md](08_current_state.md)에서 관리합니다.
