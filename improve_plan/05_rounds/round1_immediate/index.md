# 라운드 1 — 즉시 조치

- 상태: 완료 (2026-10-27)
- 브랜치: `fix/IMP-27-30-round1-immediate` (`chore/normalize-eol` 위, D-009)
- 모델: 계획 메인 / 구현 Sonnet / 검토 Sonnet
- 기준선: 177 passed, 0 failed, V1 0·0

## 1. 목표

게이트 도구를 갖추고, 설정 채널 게시 결함(H2)·자막 의존성 누락(M6)·배포물 로그인 정보 유출 경로(H4)를 막습니다.

## 2. 작업 목록

| ID | IMP | 내용 | 대상 | 계약서 | 상태 |
| --- | --- | --- | --- | --- | --- |
| R1-T0 | — | 테스트 실행 환경 | N1 | — | 완료 (D-007) |
| R1-T1 | — | 기준선 측정 | — | — | 완료 (177) |
| R1-T2 | IMP-27 | 게이트 도구 `scripts/round_gate.py` | 방법론 | [R1-T2_gate_tool.md](R1-T2_gate_tool.md) | 완료 (6604f3e, 게이트 PASS) |
| R1-T3 | IMP-28 | 게시 가드가 설정 채널 사용 | H2 | [R1-T3_channel_guard.md](R1-T3_channel_guard.md) | 완료 (d6a1065, 게이트 PASS) |
| R1-T4 | IMP-29 | 자막 라이브러리 선언·누락 안내 | M6 | [R1-T4_captions_dependency.md](R1-T4_captions_dependency.md) | 완료 (21abd03, 게이트 PASS) |
| R1-T6 | IMP-27·28·30 | 검토 차단 지적 반영 | 검토 #1~#4 | [R1-T6_review_fixes.md](R1-T6_review_fixes.md) | 완료 (0982ba6, 게이트 PASS) |
| R1-T7 | IMP-27 | G6 이메일 검사 회귀 수정 | 재검토 #1 | [R1-T7_email_regex_fix.md](R1-T7_email_regex_fix.md) | 완료 (60273ba, 게이트 PASS) |
| R1-T5 | IMP-30 | 추적 파일 기반 배포 패키징 | H4 | [R1-T5_packaging.md](R1-T5_packaging.md) | 완료 (57629b0, 게이트 PASS) |

실행 순서: T2 → T3 → T4 → T5. T2가 이후 작업의 게이트를 판정합니다.
T2는 자기 자신을 판정할 수 없으므로, T2 커밋 이후의 `round_gate.py`로 T2 커밋을 판정하고 메인이 결과를 직접 검토합니다.

## 3. 결정 사항

- [x] 브랜치는 `chore/normalize-eol` 위에서 시작 (D-009)
- [x] Chrome 프로필 위치 유지, 배포물에서만 제외 (D-008)
- [x] 저장소 SDD 절차 준수 (D-011)

## 4. 수동 점검 (사용자)

- R1-T4: Windows에서 `start.bat` 실행 시 `youtube-transcript-api`가 설치되는지 (V4)
- R1-T5: 만든 zip을 다른 폴더에 풀어 `start.bat`으로 실행되는지 (V4)

## 5. 게이트 판정 (2026-10-27)

| 게이트 | 결과 |
| --- | --- |
| 작업 게이트 | R1-T2~T7 모두 PASS (logs/r1/) |
| G2' 브랜치 전체 | 206 passed, 0 failed, V1 0·0 (기준선 177 → 206) |
| G7 검토 | 1회차 차단 3 → R1-T6 반영, 2회차 차단 1 → R1-T7 반영, 최종 차단 0 |
| G8 기록 | 이 절, `tasks.md`·`handoff.md` 갱신 |

| 측정 | 값 |
| --- | --- |
| 재작업 | T2 0, T3 0, T4 0, T5 1(G6 테스트 이메일), T6 1(G6 오탐) → 평균 0.4 |
| 에스컬레이션 | 0 |
| 검토 1회차 차단 | 3 |
| 메인 재조사량 | src 변경 파일 3개의 diff만 정독 |

모델 구성 재평가(escalation_and_metrics.md): 평균 재작업 0.4 < 2, 메인 재조사량이 변경 파일의 절반 미만 → **D-003 유지**.
남은 권고: 비UTF-8 파일 키 검사(R1-T5), round_gate·package 금지 경로 규칙 차이(G6가 더 엄격), fnmatch `*`가 `/` 포함 → 계약서 작성 시 주의.
