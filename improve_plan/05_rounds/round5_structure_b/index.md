# 라운드 5 — 구조 개선 B

- 상태: 구현
- 브랜치: `refactor/IMP-41-43-round5-structure-b` (라운드 4 브랜치 위, D-014)
- 모델: 계획 메인 / 구현 Sonnet / 검토 Sonnet
- 기준선: 263 passed

## 1. 목표

대시보드 코드를 역할별로 나누고, 스크립트 CSP를 nonce로 강화하며, 과제 고정값·모델 기본값·앱 루트를 정리합니다. 공개 동작은 바꾸지 않습니다.

## 2. 작업 목록

| ID | IMP | 내용 | 대상 | 계약서 | 상태 |
| --- | --- | --- | --- | --- | --- |
| R5-T1 | IMP-41 | `dashboard.py` 분리, 토큰 검사 단일화, 경계 시험 보강 | M7 | [R5-T1_dashboard_split.md](R5-T1_dashboard_split.md) | 계획 |
| R5-T2 | IMP-42 | 스크립트 CSP nonce | M8 | [R5-T2_csp_nonce.md](R5-T2_csp_nonce.md) | 계획 |
| R5-T3 | IMP-43 | 과제 고정값 모음, 모델 기본값, 앱 루트 검증 | L3, L6, L8 | [R5-T3_constants_and_root.md](R5-T3_constants_and_root.md) | 계획 |

## 3. 결정 사항

- [x] 스타일 CSP(`style-src 'unsafe-inline'`)는 인라인 style 속성이 많아 유지(기록)
- [x] "PDF 고정" 값은 바꾸지 않고 상수로만 모음(D-018)
- [x] 모델 프리셋은 코드에 두되 사용자 임의 모델 입력이 이미 가능하므로 기본값 일치만 정리

## 4. 수동 점검 (사용자)

- R5-T2: 브라우저 개발자 도구 콘솔에 CSP 위반 메시지가 없는지, 모든 버튼이 동작하는지 (V3)
- R5-T3: 일반 실행(`start.bat`)이 그대로 동작하는지 (V4)

## 5. 게이트 판정

라운드 종료 시 기록합니다.
