# 제작 노트 (PROCESS)

이 파일은 제작 노트의 **안내판**입니다. 같은 내용을 읽는 사람에 맞춰 두 파일로 나눴습니다.

| 이런 분은 | 이 파일을 보세요 | 형태 |
| --- | --- | --- |
| 심사자·사람 | **[process/for-humans.md](process/for-humans.md)** | 처음부터 읽기 좋은 서술형. 프롬프트 원문 포함 |
| AI 에이전트(Claude·Codex 등) | [process/for-ai.md](process/for-ai.md) | 표 중심. 고정 사실·불변 조건·실패 기록·프롬프트 버전·열린 항목, 코드·SDD 위치 |

## 과제 요구 항목 바로가기 (PDF 04 제작 노트)

| 요구 항목 | 위치 |
| --- | --- |
| 댓글이 광고 같지 않으면서 운명원이 궁금해지게 한 설계 | [댓글 설계](process/for-humans.md#댓글-설계-광고-같지-않게-운명원이-궁금해지게) |
| 고민 정리 · 댓글 작성 프롬프트 원문 | [프롬프트 원문](process/for-humans.md#프롬프트-원문-고민-정리--댓글-작성) (코드: [prompt_policy.py](src/marketing_agent/prompt_policy.py)) |
| 사용한 AI 도구와 각각 어디에 썼는지 | [사용한 AI 도구](process/for-humans.md#사용한-ai-도구와-쓴-곳) |
| 실패와 개선 2가지 이상 | [실패와 개선 10건](process/for-humans.md#실패와-개선) |
| 총 소요 시간, 다시 한다면 바꿀 점 | [총 소요 시간과 다시 한다면](process/for-humans.md#총-소요-시간과-다시-한다면) — 약 3일 |
| (참고) Mac 환경 검증 범위 | [Mac 환경 검증](process/for-humans.md#mac-환경-검증) — 개발 PC가 Windows라 실제 Mac 테스트는 못 했고 GitHub Actions 스모크 테스트만 진행 |

## 관리 규칙

- 두 파일이 다르면 코드와 설계 문서([.ucompany/sdd](.ucompany/sdd/00_index.md))가 기준입니다.
- 새 실패·개선은 두 파일에 함께 추가합니다. 프롬프트 원문은 `tests/test_process_docs.py`가 코드와 대조합니다.
