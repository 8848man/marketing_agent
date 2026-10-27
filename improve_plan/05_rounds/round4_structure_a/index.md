# 라운드 4 — 구조 개선 A

- 상태: 구현
- 브랜치: `refactor/IMP-38-40-round4-structure-a` (라운드 3 브랜치 위, D-014)
- 모델: 계획 메인 / 구현 Sonnet / 검토 Sonnet
- 기준선: 250 passed

## 1. 목표

외부 호출 공통 계층, 제품·레거시 경계 고정, DB 스키마 버전 틀을 만듭니다. 공개 동작은 바꾸지 않습니다.

## 2. 작업 목록

| ID | IMP | 내용 | 대상 | 계약서 | 상태 |
| --- | --- | --- | --- | --- | --- |
| R4-T1 | IMP-38 | 리다이렉트 차단·크기 제한 공통 계층 | M5 | [R4-T1_http_client.md](R4-T1_http_client.md) | 완료 (3a0b43a, 게이트 PASS) |
| R4-T2 | IMP-39 | 제품·레거시 import 경계 시험 | M4 | [R4-T2_legacy_boundary.md](R4-T2_legacy_boundary.md) | 완료 (7236893, 게이트 PASS) |
| R4-T3 | IMP-40 | 스키마 버전·마이그레이션 틀 | L5 | [R4-T3_schema_version.md](R4-T3_schema_version.md) | 계획 |
| R4-T4 | IMP-35·36 | 라운드 3 권고(로그 회전 잠금, 검토자 제어문자) | 검토 권고 | [R4-T4_round3_advisories.md](R4-T4_round3_advisories.md) | 계획 |

## 3. 결정 사항 (D-017)

- [x] M4: 레거시 모듈 이동·삭제와 레거시 테이블 폐기는 하지 않음. CDP 게시 코드는 IMP-01에서 이미 제거됨. 경계를 자동 시험으로 고정
- [x] L5: 버전 1 = 현재 스키마(+ IMP-35 재구성). 연결 수명 정리는 범위 밖

## 4. 수동 점검 (사용자)

- 없음 (내부 구조 변경. 기존 `posts.db`를 가진 PC에서 대시보드가 정상 시작되는지는 최종 점검에 포함)

## 5. 게이트 판정

라운드 종료 시 기록합니다.
