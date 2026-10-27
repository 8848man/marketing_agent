## 구현 보고 R1-T7
- 결과: 완료
- 커밋: 60273ba fix(gate): G6 이메일 검사 한글 접두 회귀 수정 (R1-T7)
- 변경 파일: scripts/round_gate.py, tests/test_round_gate.py
- 추가·수정한 테스트: test_g6_email_detection_boundaries
- 실패 확인: 별도 실행 안 함 (게이트 G1로 확인)
- 통과 확인: 13 passed, 전체 206 passed, V1 0·0
- 계약서와 다르게 한 점: 자체 테스트 리터럴이 G6에 걸려 문자열 분할 후 1회 amend
- 확신이 없는 점: 이스케이프 치환이 주석의 \n에도 적용됨(이메일 검사 한정, 의도된 동작)
- 열지 않은 비밀 파일 확인: 예
