# marketing_agent 작업 지침

이 폴더가 제품과 SDD의 루트다. 작업 전에 `.ucompany/sdd/00_index.md`와 `graph.json`에서 관련 문서를 찾는다. 기능 변경은 `docs/track2-agent/spec.md` → `plan.md` → `tasks.md` → 코드 순서로 반영한다. 사용자의 명시적 구현 요청은 단계 전환 승인으로 기록할 수 있다. 작업 후 테스트 결과와 남은 검증을 작업 목록, 색인, handoff에 갱신한다.

Chrome 프로필 내부 파일·쿠키·비밀번호는 직접 읽지 않는다. 실제 댓글 게시에는 대상과 문안에 대한 사용자 승인을 적용한다. API 키와 이메일은 로그·테스트 출력에 기록하지 않는다.
