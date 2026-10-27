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

## 도구

- [tools/check_structure.py](tools/check_structure.py) — 이 폴더가 작성 규칙을 지키는지 검사합니다.
  `python3 improve_plan/tools/check_structure.py`

## 현재 상태

| 항목 | 값 |
| --- | --- |
| 대상 저장소 | `D:\projects\샘플_폴더\샘플프로젝트\marketing_agent` |
| 기준 커밋 | `554e273` (main, PR #10 병합) |
| 진행 중 라운드 | 없음 — 1라운드 계획 대기 |
| 테스트 기준선 | **177개 통과, 실패 0** (2026-10-27, 테스트 함수 157개 + 파라미터화) |
| 테스트 실행 환경 | 원격 셸 `$HOME/venv-ma` (Python 3.11.17) — [04_agent_workflow/roles_and_models.md](04_agent_workflow/roles_and_models.md) 참고 |
