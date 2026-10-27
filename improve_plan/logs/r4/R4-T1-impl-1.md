## 구현 보고 R4-T1
- 결과: 완료
- 커밋: 3a0b43a refactor(http): 리다이렉트 차단·크기 제한 공통 계층 (R4-T1)
- 변경 파일: http_client.py(신규), ai_client.py, captions.py, pipeline.py, rss_feed.py, posting_service.py, tests/test_http_client.py, graph.json, 00_index.md
- 추가·수정한 테스트: 새 4개, 기존 수정 0
- 실패 확인: 수정 전 ModuleNotFoundError
- 통과 확인: 전체 254 passed, V1 0·0 (48 nodes)
- 계약서와 다르게 한 점: 기존 테스트가 build_opener를 patch해 3곳은 build_opener(NoRedirectHandler) 사용, pipeline 크기 초과 코드는 실제 값 유지
- 확신이 없는 점: 없음 (예외 흐름 모듈별 대조 완료)
- 열지 않은 비밀 파일 확인: 예
