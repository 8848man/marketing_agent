# marketing_agent 작업 지침 (AI 작업자용)

이 폴더가 제품의 루트이고, 모든 SDD 문서는 `.ucompany/sdd/` 한 곳에 있다(2026-10-18 통합, [ADR-0001](.ucompany/sdd/decisions/ADR-0001-sdd-consolidation.md)).

## 문서 지도 — 누가 무엇을 읽나

| 문서 | 독자 | 용도 |
| --- | --- | --- |
| `AGENTS.md` (이 파일) | 이 저장소를 고치는 AI 작업자 | 작업 순서·금지사항 |
| [00_index.md](.ucompany/sdd/00_index.md) · `graph.json` | AI 작업자 | 요구사항·작업·코드 위치 색인 |
| `README.md` | 심사자·사용자 | 실행 파일·사용법·안전 규칙·오픈소스 출처 |
| `HOW_TO_SETTING.md` | 사용자의 설치를 돕는 AI 도우미 | 사용자에게 필요한 값을 역으로 묻는 대화 절차(코드 수정용 아님) |
| `PROCESS.md` | 심사자 | 제작 노트(과제 PDF 04) |

## 작업 순서

1. 작업 전에 [00_index.md](.ucompany/sdd/00_index.md)와 `graph.json`의 `focus`에서 관련 문서를 찾는다.
2. 모든 변경은 [워크플로우](.ucompany/sdd/workflow.md)의 **Spec → 구현 → 검증 → GitHub → 마감** 순서를 따른다. 기능 변경은 `spec.md`에 IMP 번호로 먼저 기록하고(→ `plan.md` → `tasks.md`) 코드를 바꾼다. 사용자의 명시적 구현 요청은 단계 전환 승인으로 기록할 수 있다.
3. 검증은 `python .ucompany/scripts/check_sdd.py`, `python .ucompany/scripts/safety_scan.py --strict`, `python -m pytest -q`를 실행하고 V1~V4 수준을 구분해 기록한다.
4. 작업 브랜치·PR로만 `main`에 합치고(Merge commit), 병합한 브랜치는 삭제한다. 작업 후 `tasks.md`, `00_index.md`/`graph.json`, `handoff.md`를 갱신한다.
5. 제출 버전은 `submitment` 브랜치로 고정되어 있다. 이 브랜치에는 직접 커밋하지 않는다.

## 문서와 코드가 어긋나지 않게 (자동 검사)

- 대시보드가 import하는 모듈을 새로 만들면 `graph.json` 노드로 등록하거나 `contracts/legacy-scope.md`에 적는다(`check_sdd.py`가 검사).
- 프롬프트(`src/marketing_agent/prompt_policy.py`)를 바꾸면 `00_index.md`의 버전 표기와 `PROCESS.md`의 원문도 함께 고친다(`check_sdd.py`, `tests/test_process_docs.py`가 검사).
- 이 파일에 적은 파일 경로는 실제로 있어야 한다(`check_sdd.py`가 검사).

## 안전 규칙 (어기면 실격)

Chrome 프로필 내부 파일·쿠키·비밀번호는 직접 읽지 않는다. 실제 댓글 게시에는 대상과 문안에 대한 사용자 승인을 적용하고, 우리 채널 영상에는 개발 중 게시하지 않는다(개발·시연은 본인 테스트 영상만, 개발 PC에는 `data/dashboard/DEV_BLOCK_OUR_CHANNELS`). API 키와 이메일은 로그·테스트 출력·커밋에 기록하지 않는다. `.env`, `config.yaml`, `data/`는 커밋하지 않는다.
