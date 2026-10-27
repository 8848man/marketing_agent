# 02. 위험 항목 현황

2026-10-27, 커밋 `554e273` 기준. 근거 표기는 [00_document_rules.md](00_document_rules.md) 5절을 따릅니다.

| ID | 심각도 | 내용 | 현재 상태 | 라운드 |
| --- | --- | --- | --- | --- |
| H1 | 높음 | 로컬 프로세스가 사람 승인 없이 생성→승인→게시 가능 | 유효 [코드 확인] 토큰이 `/` HTML에 포함(`dashboard.py` `_page(token, …)`), 승인 해시는 비밀 없는 `content_hash` | 2 |
| H2 | 높음 | 설정 채널과 게시 가드 불일치 | 유효 [코드 확인] `guard.py`가 하드코딩 `rss_feed.CHANNELS`만 허용 | 1 |
| H3 | 높음 | API 키가 평문 `.env` | 유효 [코드 확인] `dashboard_settings._write_ai_env` + `chmod 0o600`(Windows에서 효과 미미) | 2 |
| H4 | 높음 | 로그인 정보가 배포물에 섞일 위험 | 대상 변경 [코드 확인] 보고서의 `keep-window-probe`는 없음. 대신 `data/dashboard/chrome-profile-*`에 `Cookies`·`Login Data` 존재. git에는 `data/` 제외로 안 올라가지만 폴더 압축 배포 시 위험 | 1 |
| M1 | 중간 | 정책 리스크, 대시보드 경로에 쿨다운 없음 | 유효 [코드 확인] `channel_cooldowns`는 레거시 `reserve_post`에만 적용 | 2 |
| M2 | 중간 | 락 범위가 넓어 UI 멈춤 | 재확인 필요 [보고서] `dashboard.py`에 `_settings_lock` 사용 20곳 | 3 |
| M3 | 중간 | `OUTCOME_UNKNOWN` 복구 경로 없음 | 유효 [코드 확인] `finish_dashboard_post` 호출은 `posting_service.py` 게시 경로뿐 | 3 |
| M4 | 중간 | 레거시 CLI와 이중 데이터 모델 | 재확인 필요 [보고서] 레거시 모듈(`pipeline`, `watcher` 등) 존재. `poster.py`는 362줄로 줄어 CDP 구간 잔존 여부 확인 필요 | 4 |
| M5 | 중간 | `_NoRedirect` 중복, 공통 HTTP 계층 없음 | 유효 [코드 확인] `ai_client`·`captions`·`pipeline`·`rss_feed` 4곳 | 4 |
| M6 | 중간 | 자막 라이브러리 미선언 | 유효 [코드 확인] `pyproject.toml`·`requirements.txt`에 없음 | 1 |
| M7 | 중간 | `dashboard.py` 비대 | 악화 [코드 확인] 1,028줄 → 1,372줄 | 5 |
| M8 | 중간 | JS가 Python 문자열 안, CSP `unsafe-inline` | 재확인 필요 [보고서] | 5 |
| L1 | 낮음 | 일일 한도 날짜가 머신 시간대 기준 | 유효 [코드 확인] `posting_service.local_tz` | 3 |
| L2 | 낮음 | `latest.json`이 개별 초안을 가림 | 재확인 필요 [코드 확인] 목록에서는 제외(83행), 로딩 경로(158행) 확인 필요 | 3 |
| L3 | 낮음 | "PDF 고정" 값이 설정을 장식으로 만듦 | 재확인 필요 [보고서] | 5 |
| L4 | 낮음 | 대시보드 경로 로깅 없음 | 유효 [코드 확인] `log_message` no-op, `EventLogger` 미사용 | 3 |
| L5 | 낮음 | DB 마이그레이션 체계 없음 | 유효 [코드 확인] `user_version` 사용 0곳 | 4 |
| L6 | 낮음 | 모델명 하드코딩 | 재확인 필요 [보고서] | 5 |
| L7 | 낮음 | 저장소 위생 | 대부분 해소 [코드 확인] git·`.gitignore` 존재, 이중 구현본 없음. 줄바꿈 정규화 완료(D-002) | — |
| L8 | 낮음 | 경로 이식성 | 재확인 필요 [추정] | 5 |

## 새로 발견한 항목

| ID | 심각도 | 내용 | 라운드 |
| --- | --- | --- | --- |
| N1 | 중간 | 원격 셸 기본 Python이 3.10이고 pytest가 없음. 프로젝트는 3.11 이상 요구 | **해소** (D-007) |
