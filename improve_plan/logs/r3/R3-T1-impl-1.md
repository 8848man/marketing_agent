## 구현 보고 R3-T1
- 결과: 완료
- 커밋: c2a31a2 fix(dashboard): 설정 락과 브라우저 락 분리 (R3-T1)
- 변경 파일: src/marketing_agent/dashboard.py, tests/test_dashboard.py
- 추가·수정한 테스트: 새 테스트 4개 (5회 반복 통과)
- 실패 확인: 수정 전 3 failed (verify 대기 테스트는 회귀 방지로 통과)
- 통과 확인: 전체 237 passed, V1 0·0
- 계약서와 다르게 한 점: select_video는 브라우저 락 non-blocking 시도(게시 중이면 poster 미변경), _use_assigned_profile을 검증/대입으로 분리, refine_draft도 스냅샷 방식
- 확신이 없는 점: 브라우저→설정 락: _post_video_on_worker, _verify_profile_on_worker, save_profile, open_app_profile, select_video(non-blocking)
- 열지 않은 비밀 파일 확인: 예
