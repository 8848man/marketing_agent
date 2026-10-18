<!-- .ucompany/sdd/workflow.md 4단계. 빈 칸이 있으면 머지하지 않는다. -->

## Spec (1단계)
- 요구사항 ID: `R-…` / 작업 ID: `T…`·`U…`·`H…`·`IMP-…`
- 변경한 SDD 문서: spec.md · plan.md · tasks.md · (ADR-…)
- 사용자 승인 근거: <!-- 요청 메시지 날짜·요지 -->

## 구현 (2단계)
- 무엇을 바꿨나:
- 하지 않은 것 / 범위 밖:

## 검증 (3단계) — 수준별로 분리해 기록
- [ ] V1 `python .ucompany/scripts/check_sdd.py` 통과
- [ ] V1 `python .ucompany/scripts/safety_scan.py` FAIL 0 (WARN 내용 기재: )
- [ ] V2 `python -m pytest -q` — 통과 수: 
- [ ] V3 로컬 화면 확인(해당 시): 
- [ ] V4 실환경(Mac·YouTube·실제 AI)은 **수행 / 미수행** — 미수행이면 tasks 체크박스를 닫지 않음

## 안전 규칙 체크 (PDF 4쪽)
- [ ] 쿠키·비밀번호·브라우저 저장 정보를 읽거나 저장하는 코드 없음
- [ ] API 키가 화면·로그·커밋에 없음 (`.env`, `config.yaml` 미추적)
- [ ] 우리 채널 영상(+본인 테스트 영상) 외 페이지를 프로그램이 열지 않음
- [ ] 댓글 외 동작(구독·좋아요·설정 변경) 없음, 대시보드 폴더 밖 파일 읽기 없음
- [ ] 우리 채널 영상에 사전 게시하지 않음

## 문서 마감 (5단계)
- [ ] tasks.md 체크박스(증거가 있을 때만) · handoff.md · 00_index.md/graph.json 갱신
