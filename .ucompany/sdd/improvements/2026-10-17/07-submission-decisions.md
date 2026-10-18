# 제출 전 결정 기록 (2026-10-18)

사용자가 [결정표](07-submission-decisions.html)의 추천안을 모두 승인했다("이대로 진행"). 요구사항은 `features/track2-dashboard/spec.md`의 `R-SUBMIT-2026-10-18`, 계정 확인 결정은 [ADR-0003](../../decisions/ADR-0003-watch-page-account-check.md).

| 번호 | 사용자 답 | 결정 | 반영 |
| --- | --- | --- | --- |
| 1 | 우리 채널 댓글 7개 삭제 완료 | PROCESS.md 실패 5로 짧게 기록, 개발용 차단 가드 추가 | G-00 완료, IMP-10 |
| 2 | 계정 확인·로그인은 불가피했다 | A안: 허용 영상 watch 페이지에서 아바타/로그인 링크만 판정, 로그인은 사람이 클릭, 이메일 표시 제거 | IMP-08, ADR-0003 |
| 3 | 출제처 문의 불가(휴일) | 앱 전용 프로필 + 1회 로그인 유지, 로그인 확인된 프로필에만 배정, README 첫 화면 3단계 | IMP-09, README §2 |
| 4 | 실행 기록 패널은 Claude가 | ④ 실행 기록 패널·`GET /api/history` | IMP-07 |
| 5 | 초안 작업을 맡겨도 되나 | 생성 명령은 사용자 PC에서 1회 실행(작업 환경이 YouTube·Gemini 접속 불가), 평가·재작성·커밋은 Claude, 승인은 사용자. 채널당 최신 3개 | IMP-11, G-02 진행 |
| 6 | Mac 없음 | GitHub Actions macOS 스모크(설치·기동·Chrome·한국어 영상 페이지) | IMP-12 |
| 7 | 시연 영상·Public 전환은 추후 | 대본·테스트 영상 등록 절차(README 부록 A)·Public 전 체크 준비 | 사용자 진행 |
