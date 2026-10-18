---
id: WF-1
type: workflow
status: active
since: 2026-10-18
---

# AI 작업 워크플로우 — Spec → 구현 → 검증 → GitHub

사람이든 AI 에이전트(Codex, Claude 등)든 이 저장소의 모든 변경은 아래 다섯 단계를 순서대로 지난다. 각 단계는 **관문(Gate)** 을 통과해야 다음으로 넘어간다. 관문을 건너뛴 변경은 머지하지 않는다. 문서 위치는 [00_index.md](00_index.md), 원칙은 [constitution.md](constitution.md)를 따른다.

```text
 0 접수 ─▶ 1 Spec ─▶ 2 구현 ─▶ 3 검증 ─▶ 4 GitHub ─▶ 5 마감
            │G1        │G2        │G3        │G4         │G5
            spec/plan  브랜치·    V1~V4      PR·CI·     tasks·handoff
            tasks 기록  커밋 단위  증거 분리   리뷰·머지   graph 갱신
```

## 0. 접수 (Intake)

| 할 일 | 산출물 |
| --- | --- |
| 요청을 `feat`(기능) · `fix`(결함) · `docs`(문서) · `chore`(구조·도구) · `refactor` 중 하나로 분류한다. | 작업 유형 |
| [00_index.md](00_index.md) → [graph.json](graph.json)의 `focus` → `feature.md` 순으로 관련 요구사항 ID를 찾는다. 없으면 1단계에서 새 ID를 만든다. | 관련 `R-…` ID |
| 요청이 PDF 원문([source-of-truth.md](source-of-truth.md))이나 기존 결정과 충돌하는지 확인한다. 충돌하면 조용히 고치지 않고 사용자에게 묻거나 ADR 초안을 만든다. | 충돌 여부 |

## 1. Spec 정의 — 관문 G1

코드보다 문서가 먼저다. 사용자의 명시적 요청 메시지는 "단계 전환 승인"으로 기록할 수 있다.

1. **요구사항** — [features/track2-dashboard/spec.md](features/track2-dashboard/spec.md)에 `R-…` 항목을 추가·수정한다. 반드시 *근거(PDF 쪽수 또는 사용자 결정 날짜)*, *수락 기준*, *대체하는 이전 항목*(있다면 `대체:` 표기)을 적는다.
2. **결정** — 선택지가 둘 이상이었거나 PDF 해석이 필요한 결정은 [decisions/](decisions/)에 `ADR-####-slug.md`로 남긴다(상태·맥락·결정·결과).
3. **계획** — [plan.md](features/track2-dashboard/plan.md)에 구현 방침과 영향을 받는 모듈을 쓴다.
4. **작업** — [tasks.md](features/track2-dashboard/tasks.md)에 `- [ ] <작업ID> …` 체크박스를 추가하고 요구사항 ID를 괄호로 연결한다.

**G1 통과 조건:** 요구사항 ID·수락 기준·작업 ID가 존재하고, 사용자 승인 근거가 적혀 있다. 이 상태로 `docs(spec): …` 커밋을 먼저 남겨도 된다.

## 2. 구현 — 관문 G2

1. `main`에서 브랜치를 만든다: `<유형>/<작업ID>-<짧은-설명>` (예: `feat/U41-post-history-panel`, `fix/IMP-03-brand-misuse`).
2. 수락 기준을 먼저 테스트로 옮기고(가능하면 실패하는 테스트부터), 그 다음 코드를 고친다. 게시·외부 호출 경계는 "거부 시 Chrome·DB 예약·외부 요청 0회"를 테스트로 고정한다.
3. 커밋은 **한 가지 의도**만 담는다. 메시지 형식:

   ```text
   <유형>(<범위>): <무엇을 했는지 한 줄>

   Spec: R-…  Task: …
   Verify: V1 ok, V2 147 passed, V3 n/a, V4 미수행
   ```

4. 금지: `.env`, `config.yaml`, `data/`, Chrome 프로필, 실제 키·이메일의 커밋. 안전 규칙(PDF 4쪽)을 약화하는 변경은 ADR 없이 하지 않는다.

**G2 통과 조건:** 작업 ID에 연결된 커밋만 브랜치에 있고, 새 동작마다 테스트가 있다.

## 3. 검증 — 관문 G3

검증은 수준을 나눠 기록한다. **높은 수준의 증거를 낮은 수준으로 대신하지 않는다.**

| 수준 | 내용 | 명령 / 방법 | 기록 위치 |
| --- | --- | --- | --- |
| V1 정적 | SDD 링크·그래프 일관성, 안전 규칙 정적 검사 | `python .ucompany/scripts/check_sdd.py`<br>`python .ucompany/scripts/safety_scan.py` (제출 직전 `--strict`) | PR 본문 |
| V2 자동 회귀 | 모의 YouTube·AI·Chrome 기반 pytest | `python -m pytest -q` (CI: macOS + Ubuntu) | PR 본문, 커밋 메시지 |
| V3 로컬 화면 | 대시보드 세 칸 조작, 오프라인 데모 | `python -m marketing_agent dashboard --demo` 등 | [validation-protocol.md](features/track2-dashboard/validation-protocol.md) |
| V4 실환경 | Mac·한국어 YouTube·실제 AI·**본인 테스트 영상** 게시 | 사람이 수행, 공개 게시는 대상·문안 승인 후 | [checklist.md](features/track2-dashboard/checklist.md) |

**G3 통과 조건:** V1·V2가 통과했다. V3·V4는 해당할 때 수행하고, 하지 못했으면 "미수행"이라고 명시한다. 우리 채널 영상에는 개발 중 게시하지 않는다.

## 4. GitHub — 관문 G4

1. `git push -u origin <브랜치>` 후 `main` 대상 PR을 연다. 본문은 [PR 템플릿](../../.github/pull_request_template.md)을 채운다(Spec·구현·검증·안전 체크).
2. [CI](../../.github/workflows/ci.yml)가 V1·V2를 macOS·Ubuntu에서 다시 실행한다. 빨간불이면 머지하지 않는다.
3. 리뷰: 사람 리뷰어 1명, 또는 이 작업을 만들지 않은 별도 AI 세션이 PR diff와 spec을 대조한다(작성자가 자기 작업을 채점하지 않는다).
4. **Merge commit**으로 `main`에 합쳐 Spec 커밋과 구현 커밋의 쌍을 이력에 남기고, 병합한 작업 브랜치는 원격에서 삭제한다. 커밋 제목은 1단계의 작업 ID를 포함한다.
5. 제출 시점에는 `main`에서 **`submitment` 브랜치**를 만들어 제출 버전을 고정하고 `submission-YYYYMMDD` 태그를 단다. `submitment`에는 직접 커밋하지 않는다(제출 후 수정은 `main`에서). 저장소 공개(Public) 전환은 사용자 승인 후에만 한다.

권장 저장소 설정: `main` 보호(직접 push 금지, CI 통과 필수, 선형 이력).

**G4 통과 조건:** PR이 CI 통과 상태로 머지됐다.

## 5. 마감 — 관문 G5

- [tasks.md](features/track2-dashboard/tasks.md) 체크박스는 **수락 기준의 증거가 있을 때만** 닫는다(V4가 필요한 항목은 V4 증거 필요).
- [handoff.md](handoff.md) 맨 위에 날짜·작업 ID·검증 수준별 결과·남은 일을 한 단락으로 추가한다.
- 문서를 추가·이동했다면 [00_index.md](00_index.md)와 [graph.json](graph.json)(`version` +1)을 함께 갱신하고 `check_sdd.py`를 다시 돌린다.
- 오래된 서술은 지우지 말고 `대체:`/`이력` 표시 후 [history.md](history.md)로 옮긴다.

## AI 에이전트용 요약 (프롬프트에 그대로 붙여 쓸 수 있음)

```text
1) 00_index.md와 graph.json focus로 관련 R-ID를 찾는다.
2) spec.md → plan.md → tasks.md를 먼저 수정하고 `docs(spec)` 커밋한다.
3) <유형>/<작업ID>-slug 브랜치에서 테스트 먼저, 코드 다음. 한 커밋 한 의도.
4) check_sdd.py, safety_scan.py, pytest를 돌리고 결과를 V1~V4로 나눠 적는다.
5) PR 템플릿을 채워 PR을 연다. CI 통과 + 리뷰 후 squash merge.
6) tasks 체크박스는 증거가 있을 때만 닫고 handoff/graph를 갱신한다.
금지: 키·쿠키·프로필 파일 접근/커밋, 우리 채널 사전 게시, 승인 없는 공개 게시·Public 전환.
```
