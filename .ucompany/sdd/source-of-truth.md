# SDD 원본과 문서 권위

확인일: 2026-10-17 (Asia/Seoul)

## 원요구사항의 식별

외부 원문은 `(주)제이지그룹 · AI PM 선발과제 안내`, `TRACK 2 마케팅 AI 에이전트 개발` 표지의 **6쪽 PDF**다. 이 PC에서 확인한 파일명은 `track-2-marketing-agent (1).pdf`, 크기는 1,093,302바이트, SHA-256은 아래와 같다.

```text
e3e45907c2b123affd2b70a47aa851dffd1d589836161f700682d474653d0bf3
```

원본의 현재 로컬 위치는 `C:/Users/LG/Downloads/track-2-marketing-agent (1).pdf`다. 이 경로는 다른 PC에서 유효하다고 가정하지 않는다. PDF 자체는 이 제품 폴더에 복사하지 않았으며, 원문 재배포 가능 여부는 확인되지 않았다. 이후 다른 PDF를 사용할 때는 해시와 변경 결정을 먼저 기록한다.

## 권위 순서와 역할

1. **외부 PDF:** 과제 요구의 최초 출처. 2026-10-17에 페이지 수와 주요 제목을 열어 확인했다. PDF에 없는 후속 사용자 결정은 결정 이력에서 관리한다.
2. **[`.ucompany/sdd/features/track2-dashboard/spec.md`](features/track2-dashboard/spec.md):** 제품 안에서 관리하는 현행 요구사항. PDF 조항과 후속 사용자 결정을 ID·쪽수·날짜로 연결한다. 충돌이 있으면 조용히 수정하지 않고 변경 결정과 수락 기준을 남긴다.
3. **[`.ucompany/sdd/features/track2-dashboard/plan.md`](features/track2-dashboard/plan.md) / [`tasks.md`](features/track2-dashboard/tasks.md) / [`validation-protocol.md`](features/track2-dashboard/validation-protocol.md):** 각각 구현 방침, 남은 작업, 시험 방법 및 증거. 과거 계획은 현재 요구사항보다 우선하지 않는다.
4. **[`.ucompany/sdd/00_index.md`](00_index.md):** 문서 ID·관계·탐색 순서의 원본. [`.ucompany/sdd/graph.json`](graph.json)은 파생 색인이다. 작업 절차는 [`workflow.md`](workflow.md), 루트 진입 안내는 [`AGENTS.md`](../../AGENTS.md)다(2026-10-18 `SDD.md` 삭제, ADR-0001).
5. **[`README.md`](../../README.md) / [`PROCESS.md`](../../PROCESS.md) (안내판 → `process/for-humans.md`·`process/for-ai.md`):** 사용법과 제작 기록. 현재 구현·검증 상태를 설명하지만 요구사항 변경을 단독으로 승인하지 않는다.

## 변경과 상태 표시

- 후속 사용자 결정이 PDF의 선택지 또는 이전 결정을 대체할 때는 `spec.md`에 효력 날짜와 대체 대상을 쓰고, 계획·작업·검증 문서를 따라 갱신한다.
- `구현`, `자동 회귀`, `외부 서비스 실호출`, `Windows 실환경`, `macOS 수락`, `공개 게시`는 별도 증거로 취급한다. 이전 날짜의 시험 수를 현재 수락 상태로 읽지 않는다.
- 원문 파일명·해시·페이지 수가 다르면 다른 판본으로 분류하고 `source-diff.md`의 비교를 다시 수행한다.
