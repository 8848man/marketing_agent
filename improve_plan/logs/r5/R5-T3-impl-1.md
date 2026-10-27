## 구현 보고 R5-T3
- 결과: 완료
- 커밋: 0a4bfd6 refactor(config): 과제 고정값 단일화, 모델 기본값·앱 루트 검증 (R5-T3)
- 변경 파일: task_constraints.py(신규), dashboard_settings.py, posting_service.py, ai_client.py, __main__.py, tests/test_config.py, graph.json, 00_index.md
- 추가·수정한 테스트: 새 3개
- 실패 확인: 수정 전 3 failed
- 통과 확인: 전체 276 passed 1 skipped, V1 0·0 (51 nodes)
- 계약서와 다르게 한 점: 없음 (앱 루트 검사는 main 진입 시)
- 확신이 없는 점: start.bat·start.command 미실행
- 열지 않은 비밀 파일 확인: 예
