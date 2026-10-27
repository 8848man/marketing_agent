## 구현 보고 R3-T4
- 결과: 완료
- 커밋: 8a73e53 fix(posting,drafts): 일일 한도 KST 통일, 개별 초안 우선 (R3-T4)
- 변경 파일: posting_service.py, drafts.py, tests 2개
- 추가·수정한 테스트: 새 3개 (회귀 방지 1)
- 실패 확인: 수정 전 2 failed
- 통과 확인: 전체 250 passed, V1 0·0
- 계약서와 다르게 한 점: 없음
- 확신이 없는 점: 개별 파일이 dict가 아니면 latest.json으로 넘어가지 않고 None
- 열지 않은 비밀 파일 확인: 예
