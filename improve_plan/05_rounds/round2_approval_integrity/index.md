# 라운드 2 — 보안·승인 무결성

- 상태: 구현
- 브랜치: `fix/IMP-31-33-round2-approval-integrity` (라운드 1 브랜치 위, D-014)
- 모델: 계획 메인 / 구현 Sonnet / 검토 Sonnet + **메인 diff 정독**

## 1. 목표

ADR-0002(로컬 위협 모델)가 막아야 한다고 정한 경계 밖 공격자(같은 PC의 다른 OS 사용자, 원격 웹사이트)가 대시보드를 조작할 수 없게 하고, Windows에서 API 키를 평문으로 두지 않으며, 같은 채널 연속 게시를 막습니다.

## 2. 작업 목록

| ID | IMP | 내용 | 대상 | 계약서 | 상태 |
| --- | --- | --- | --- | --- | --- |
| R2-T1 | IMP-31 | 페어링 주소로만 대시보드 페이지(세션 토큰) 발급 | H1 | [R2-T1_pairing.md](R2-T1_pairing.md) | 완료 (31e3fe6, 게이트 PASS) |
| R2-T2 | IMP-32 | Windows DPAPI 키 저장소 | H3 | [R2-T2_windows_secret_store.md](R2-T2_windows_secret_store.md) | 완료 (cba7c75, 게이트 PASS) |
| R2-T3 | IMP-33 | 같은 대상 채널 게시 간격(제품 기본 60분) | M1 | [R2-T3_channel_cooldown.md](R2-T3_channel_cooldown.md) | 완료 (b43a347, 게이트 PASS) |
| R2-T4 | IMP-31·32·33 | 검토 지적 반영 | 검토 #1~#3·#5·#6 | [R2-T4_review_fixes.md](R2-T4_review_fixes.md) | 계획 |
| R2-T5 | — | 정책 검토·위협 모델 보완 ADR (메인 작성) | M1, H1 | [ADR-0004](../../../.ucompany/sdd/decisions/ADR-0004-pairing-and-key-storage.md), [ADR-0005](../../../.ucompany/sdd/decisions/ADR-0005-youtube-policy-review.md) | 완료 (제안 상태) |

## 3. 결정 사항 (D-013, D-015, D-016)

- [x] H1: 보고서의 HMAC 승인 해시·게시 nonce는 채택하지 않음. 같은 OS 사용자 프로세스는 ADR-0002가 수용한 위험이고, 메모리 키 HMAC은 커밋된 승인 초안(IMP-23)을 재시작마다 무효화해 심사 흐름을 깨뜨림. 대신 다른 OS 사용자가 `/`에서 토큰을 얻는 허점을 페어링으로 막음
- [x] H3: Windows만 DPAPI. macOS·Linux는 `.env` 0600 권한이 실제로 동작하므로 유지
- [x] M1: 제품 경로에 대상 채널별 최소 간격 60분. PDF 고정 일일 10개는 그대로

## 4. 수동 점검 (사용자)

- R2-T1: `start.bat`·`start-review.bat` 실행 시 브라우저가 열리고 바로 대시보드가 보이는지, 주소창의 `/pair?code=…`로 다른 브라우저에서 열 수 있는지 (V4)
- R2-T2: Windows에서 AI 키 저장 후 `.env`에 키가 없고 재시작 뒤에도 초안 생성이 되는지 (V4)
- mac-smoke(GitHub Actions)가 통과하는지 (push 후)

## 5. 게이트 판정

라운드 종료 시 기록합니다.
