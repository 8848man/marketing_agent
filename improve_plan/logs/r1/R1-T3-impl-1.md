## 구현 보고 R1-T3
- 결과: 완료
- 커밋: d6a1065 fix(guard): 게시 가드가 설정 채널 목록을 사용 (R1-T3)
- 변경 파일: src/marketing_agent/guard.py, src/marketing_agent/posting_service.py, src/marketing_agent/dashboard.py, tests/test_guard.py, tests/test_posting_service.py, tests/test_dashboard.py
- 추가·수정한 테스트: 새 테스트 5개 (+ prepare_service에 channel·service_kwargs 선택 인자)
- 실패 확인: 새 테스트 4 failed, 회귀 방지 1 통과
- 통과 확인: 좁은 70 passed, 전체 189 passed, check_sdd 0, safety_scan 0·0
- 계약서와 다르게 한 점: 없음
- 확신이 없는 점: 없음
- 열지 않은 비밀 파일 확인: 예
