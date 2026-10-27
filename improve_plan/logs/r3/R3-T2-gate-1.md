## 게이트 결과 R3-T2

- base: `2fcbe07`  head: `23a3e3a`

- G0 PASS 보고서 필수 항목 모두 있음
- G1 PASS base 실패(코드 1) -> head 통과
- G2 PASS V1 0, 통과 243 >= 233, 수집 237 -> 243
- G3 PASS 변경 6개 모두 허용 범위
- G4 PASS 동결 5건 변경 없음
- G5 PASS 커밋 1개, ID·Spec 있음, 작업 트리 깨끗함
- G6 PASS 비밀 패턴·금지 경로 없음
- RESULT PASS
- 메인 검증(R3-T2): 계약서 밖 변경인 예약 테이블 재구성(_allow_dismissed_status)을 이전 버전 코드로 만든 DB에서 직접 실행 — 행 동일, 인덱스 2개 재생성, 본문 유지, integrity ok, DISMISSED 후 재게시 차단. 외래 키 참조 없음 확인. 통과.
