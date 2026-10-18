# marketing_agent 작업 지침

이 폴더가 제품의 루트이고, 모든 SDD 문서는 `.ucompany/sdd/` 한 곳에 있다(2026-10-18 통합, [ADR-0001](.ucompany/sdd/decisions/ADR-0001-sdd-consolidation.md)).

1. 작업 전에 [.ucompany/sdd/00_index.md](.ucompany/sdd/00_index.md)와 `graph.json`의 `focus`에서 관련 문서를 찾는다.
2. 모든 변경은 [워크플로우](.ucompany/sdd/workflow.md)의 **Spec → 구현 → 검증 → GitHub → 마감** 순서를 따른다. 기능 변경은 `features/track2-dashboard/spec.md` → `plan.md` → `tasks.md` → 코드 순서로 반영한다. 사용자의 명시적 구현 요청은 단계 전환 승인으로 기록할 수 있다.
3. 검증은 `python .ucompany/scripts/check_sdd.py`, `python .ucompany/scripts/safety_scan.py`, `python -m pytest -q`를 실행하고 V1~V4 수준을 구분해 기록한다.
4. 작업 브랜치·PR로만 `main`에 합친다. 작업 후 `tasks.md`, `00_index.md`/`graph.json`, `handoff.md`를 갱신한다.

Chrome 프로필 내부 파일·쿠키·비밀번호는 직접 읽지 않는다. 실제 댓글 게시에는 대상과 문안에 대한 사용자 승인을 적용하고, 우리 채널 영상에는 개발 중 게시하지 않는다. API 키와 이메일은 로그·테스트 출력·커밋에 기록하지 않는다.
