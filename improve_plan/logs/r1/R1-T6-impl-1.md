## 구현 보고 R1-T6
- 결과: 완료
- 커밋: ef3480b fix(gate,package,guard): 라운드 1 검토 차단 지적 반영 (R1-T6)
- 변경 파일: scripts/round_gate.py, scripts/package.py, src/marketing_agent/posting_service.py, tests/test_round_gate.py, tests/test_package.py, tests/test_posting_service.py
- 추가·수정한 테스트: 새 테스트 7개 (회귀 방지 1 포함)
- 실패 확인: 수정 전 6 failed
- 통과 확인: 전체 204 passed, V1 0·0
- 계약서와 다르게 한 점: 없음. G6의 data/ 규칙은 모든 깊이 금지(package.py는 루트만) — G6이 더 엄격
- 확신이 없는 점: 위 data/ 깊이 차이
- 열지 않은 비밀 파일 확인: 예
