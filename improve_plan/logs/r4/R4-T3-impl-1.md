## 구현 보고 R4-T3
- 결과: 완료
- 커밋: 903001f feat(storage): 스키마 버전과 마이그레이션 틀 (R4-T3)
- 변경 파일: storage.py, tests/test_storage.py
- 추가·수정한 테스트: 새 4개, 기존 재구성 테스트에 user_version=0 한 줄
- 실패 확인: 수정 전 ImportError(SCHEMA_VERSION)
- 통과 확인: 전체 261 passed, V1 0·0
- 계약서와 다르게 한 점: 기존 테스트 1줄 보정, SCHEMA_VERSION=len(MIGRATIONS), _allow_dismissed_status 모듈 함수화
- 확신이 없는 점: 없음
- 열지 않은 비밀 파일 확인: 예
