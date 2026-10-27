# 저장소 자체 절차(SDD)와의 정합

이 저장소는 `AGENTS.md`와 `.ucompany/sdd/workflow.md`(WF-1)로 작업 절차를 정해 두었습니다. 개선 작업은 이 절차를 **대체하지 않고 그 안에서** 진행합니다.

## 대응표

| WF-1 단계 | 개선 작업에서의 수행 | 담당 |
| --- | --- | --- |
| 1 Spec (G1) | 라운드 계획 단계에서 `features/track2-dashboard/spec.md`에 IMP 항목(근거·결정·수락 기준), `plan.md`에 방침, `tasks.md`에 `- [ ] IMP-NN` 추가 → `docs(spec): …` 커밋 | 메인 |
| 2 구현 (G2) | 작업 계약서대로 테스트 먼저, 작업당 커밋 1개 | 구현 에이전트 |
| 3 검증 (G3) | 작업 게이트 G2에 V1(`check_sdd.py`, `safety_scan.py --strict`)과 V2(pytest)를 포함. V3·V4는 해당 시 사용자 수행, 못 하면 "미수행" 기록 | 메인 |
| 4 GitHub (G4) | push·PR·병합은 사용자. 리뷰는 "작성자가 아닌 별도 AI 세션" 요건을 검토 에이전트로 충족 | 사용자 / 검토 에이전트 |
| 5 마감 (G5) | 라운드 게이트 후 `tasks.md` 체크, `handoff.md`, 필요 시 `00_index.md`·`graph.json` 갱신 → `docs(sdd): …` 커밋 | 메인 |

## 번호와 이름

- 라운드 작업 ID(`R1-T3`)와 저장소 IMP 번호를 1:1로 연결합니다. 라운드 파일의 작업 표에 둘 다 적습니다.
- IMP 번호는 `spec.md`의 마지막 번호 다음부터 씁니다(라운드 1 시작 시 마지막 IMP-26).
- 브랜치: `<유형>/IMP-<처음>-<끝>-roundN-<주제>` (예: `fix/IMP-27-30-round1-immediate`). WF-1의 `<유형>/<작업ID>-<설명>` 규칙을 라운드 단위로 적용한 것입니다.

## 커밋 메시지

```text
<유형>(<범위>): <무엇을 했는지 한 줄> (R1-T3)

Spec: IMP-28  Task: IMP-28
Verify: V1 ok, V2 <N> passed, V3 n/a, V4 미수행

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BbDhi7fjHug1udb1wScSkQ
```

## 자동 검사가 요구하는 것 (`check_sdd.py`)

- 대시보드가 import하는 모듈을 새로 만들면 `graph.json` 노드로 등록하거나 `contracts/legacy-scope.md`에 적습니다.
- 프롬프트(`prompt_policy.py`)를 바꾸면 `00_index.md`의 버전 표기와 `PROCESS.md` 원문도 고칩니다.
- 저장소의 모든 상대 마크다운 링크는 실제로 있어야 합니다(`improve_plan/` 포함).

## 안전 규칙 (AGENTS.md, 어기면 실격)

- Chrome 프로필 내부 파일·쿠키·비밀번호를 읽지 않습니다.
- 우리 채널 영상에는 개발 중 게시하지 않습니다.
- API 키와 이메일을 로그·테스트 출력·커밋에 기록하지 않습니다.
- `.env`, `config.yaml`, `data/`를 커밋하지 않습니다.
- `submitment` 브랜치에 직접 커밋하지 않습니다.
