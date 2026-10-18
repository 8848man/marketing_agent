# 개선 계획 타당성·적용 상태 재검토 (2026-10-18)

대상: [02-improvement-plan.md](02-improvement-plan.md) (근거 [01-review-critique.md](01-review-critique.md), 이전 판정 [03](03-implementation-status.md)·[04](04-remediation-gap-audit.md)).
방법: 2026-10-18 `chore/sdd-consolidation-workflow` 브랜치의 코드·문서를 직접 읽고, Linux(Python 3.13)에서 전체 pytest를 다시 실행했다. 실제 YouTube·AI·Chrome·macOS 실행은 하지 않았다(V4 미수행).

## 1. 결론 요약

- **계획의 방향은 타당하다.** 지적한 보안·구조 문제는 실제 코드에서 확인됐고 P0 순서(보안 경계 → 게시 진입점 → 외부 호출)도 합리적이다.
- **그러나 계획은 과제 채점 관점이 빠져 있다.** 계획 전체가 "코드 품질·보안 하드닝"에 맞춰져 있어, PDF가 직접 점수를 매기는 항목(`drafts/` 저장소 포함, 실행 기록 화면, 댓글이 운명원을 *원하게* 만드는가, Mac 10분 설치)을 다루지 않는다. 이 공백은 아래 3절과 [과제 적합성 보고서](06-track2-fit-report.html)에 정리했다.
- **과설계 항목이 있다.** P0-1(같은 PC의 다른 프로세스 차단)과 P1-4(파일 교체 경쟁)는 단일 사용자 Mac이라는 실행 환경에서 효과가 작다. [ADR-0002](../../decisions/ADR-0002-local-threat-model.md)(제안)로 위협 모델을 확정해 종결하기를 권한다. P1-1(`dashboard.py` 분해)·P1-3(제공사 교체 계약)도 점수 기여가 낮아 제출 이후로 미룬다.

## 2. 항목별 판정

| 항목 | 타당성 | 10-17 판정 | 10-18 판정 | 근거·이번 조치 |
| --- | --- | --- | --- | --- |
| §1 문서 권위 | 타당 | 부분 | **완료** | SDD를 `.ucompany/sdd`로 통합([ADR-0001](../../decisions/ADR-0001-sdd-consolidation.md)), 루트 SDD 문서 11개 이동, 링크 0 깨짐을 `check_sdd.py`로 자동 검사. PDF 사본 보존은 재배포 권한 미확인으로 계속 보류. |
| §2 `.example` 계약 | 타당 | 완료 | 완료 | [contracts/config-example.md](../../contracts/config-example.md). 변화 없음. |
| P0-1 로컬 서버 접근 | 부분 타당(과설계) | 부분 | **부분 → ADR 제안** | 원격 웹·다른 기기는 이미 차단(127.0.0.1, Host·Origin·토큰). 같은 OS 사용자 프로세스까지 막는 것은 [ADR-0002](../../decisions/ADR-0002-local-threat-model.md)에서 수용 위험으로 제안. |
| P0-2 게시 진입점 단일화 | **타당·높음** | 부분 | **완료** | `poster.py`의 CDP 게시 API(`ChromeBrowser`, `submit_comment`, `reconcile_pending`, `validate_cdp_url`)와 그 시험을 삭제(IMP-01). 이제 공개 댓글을 쓸 수 있는 코드는 대시보드 버튼 → `posting_service` → `VisibleChromePoster` 하나뿐이다. |
| P0-3 외부 호출 비밀 경계 | 타당 | 부분 | 부분 | YouTube·AI 어댑터 모두 리다이렉트 차단·크기 제한·고정 오류 코드 확인. 공통 전송 계층은 없음. 대신 `safety_scan.py`가 허용 호스트 밖 URL을 CI에서 경고한다(IMP-04). |
| P1-1 `dashboard.py` 분해 | 타당(우선순위 낮음) | 부분 | 부분(보류) | 1,699 → 1,028행. 남은 분리는 점수 기여가 낮아 제출 뒤로. |
| P1-2 근거·프롬프트 경계 | **타당·높음** | 부분 | **부분(진전)** | 실제 초안 17개 중 다수가 운명원을 "운명의 상대"라는 일반명사로 쓰거나(5건 이상), 이용 경험을 지어내거나, "운명원에 의지하기 전에"처럼 브랜드를 깎아내렸다. 프롬프트 `draft-v5-brand-proper-noun`과 품질 검사 `BRAND_MISUSED`·`BRAND_NEGATIVE_FRAMING`·확장된 `FABRICATED_TESTIMONIAL`을 추가(IMP-03). 사람 평가표는 여전히 없음. |
| P1-3 제공사 교체 계약 | 타당(우선순위 낮음) | 부분 | 부분 | 네 제공사 공통 스키마·주입형 생성기 존재. 실호출 검증은 V4. |
| P1-4 파일 경계 | 부분 타당(과설계) | 부분 | 부분 → ADR 제안 | 초안·캡처의 심볼릭 링크·크기 검사 존재. 경쟁 조건은 ADR-0002에서 수용 위험으로 제안. |
| P2-1 불필요 코드 | **타당·높음** | 부분 | **부분(진전)** | CDP 게시 API 삭제, 대시보드의 `--chrome-user-data-dir`·`--chrome-profile-directory`(기본값이 앱 폴더 밖 macOS Chrome 폴더) 삭제(IMP-02). 키워드 탐색 CLI(`pipeline/watcher/trigger/classifier/writer/search_budget`)는 남음 — 가점 "뜨기 직전 영상 찾기"로 재활용하거나 삭제할지 결정 필요. |
| P2-2 문서 정리 | 타당 | 부분 | **완료** | 통합·이동·링크 재작성·`check_sdd.py`. 과거 문서는 `reviews/`·`improvements/`에 작성 당시 기록으로 보존. |
| §4 안전 규칙 판정 | **타당·최우선** | 미해결 | **미해결** | `dashboard.py`가 여전히 `accounts.google.com/AccountChooser`(→`myaccount.google.com`)와 YouTube 홈을 연다. PDF "우리 채널 영상 페이지 말고는 열지 않고"와 충돌하며 README가 스스로 "미충족"이라 적고 있다. 심사자는 실행 전 코드를 검사하고 하나라도 어기면 실격이므로 **제출 전 반드시 해소**해야 한다(아래 3절 G-01). |
| H06 실환경 수락 | 타당 | 미완료 | 미완료 | macOS·실제 YouTube·실제 AI 미검증. |

## 3. 계획에 없던 공백 (과제 적합성 관점)

| ID | 공백 | 영향(배점) | 권장 조치 |
| --- | --- | --- | --- |
| G-00 | **우리 채널 영상에 사전 게시 7건** — `data/dashboard/posts.db`에 `POSTED` 7건(리즈시절 LizTV 5, 심리조각 1, 외롭여 1), 등록된 본인 테스트 영상 0건. 이 중 5건은 IMP-03 검사에 걸리는 문장 | PDF 2쪽 "우리 채널 영상에는 미리 게시하지 마세요", 6쪽 체크리스트 위반(실격·감점 위험) | 각 프로필 계정으로 해당 댓글을 직접 삭제하고 PROCESS.md에 기록. 이후 개발 게시는 `--register-owned-test-video`로 등록한 본인 영상만. |
| G-01 | 안전 규칙 자체 판정 "미충족"(Google 로그인 화면·YouTube 홈 열기) | 실격 위험(안전 15 + 전체) | 계정 확인·로그인 창을 **허용 영상 watch 페이지**로만 연다. 로그인 버튼은 사람이 직접 누르게 한다. README의 "미충족" 표를 해소 후 "준수 근거" 표로 바꾼다. |
| G-02 | `.gitignore`가 `drafts/`를 제외 → 저장소에 초안이 없음 | 필수 제출물 누락(맥락 25·유도 20을 심사자가 볼 수 없음) | 이번에 `.gitignore`에서 `drafts/`를 뺐다(IMP-05). 제출 직전 5채널 최신 영상의 승인 초안을 새로 만들어 커밋해야 한다. |
| G-03 | 실행 기록(어느 영상·프로필·댓글·성공/실패 시간순) 화면 없음 | 안전·운영 15 | `dashboard_post_reservations`를 읽는 `GET /api/history`와 ④ 기록 패널 추가(새 요구사항 필요). |
| G-04 | 초안 품질: 브랜드 오용·부정 프레이밍·길이 초과(134·153자)·장면 언급 약함 | 맥락 25 + 유도 20 | 이번 검사 추가로 게시는 막힌다. 재생성·사람 평가(공감·광고 느낌·영상 고유성) 필요. |
| G-05 | Mac 미검증, README가 `python3`(macOS 기본 3.9)로 venv를 만들게 함 | 설치·사용성 10, 실제 게시 25 | Python 3.11+ 설치 안내(`brew install python@3.12` 또는 `uv`) 추가, Mac 실기기 V4 수행. |
| G-06 | 승인 단계(검토자 이름 입력)가 심사자 흐름에 끼어듦 | 사용성 10 | 저장소 초안은 사전 승인 상태로 커밋해 심사자는 ①→②→③만 누르게 한다. |
| G-07 | 시연 영상(2~3분) 없음 | 제출물 누락 | 본인 테스트 영상으로 녹화. |
| G-08 | 가점: 링크 직접 입력 UI 없음, 뜨기 직전 영상 찾기 미연결 | 가점 | 필수·G-01~G-05 이후. |

## 4. 이번 브랜치에서 적용한 개선 (IMP-2026-10-18)

| ID | 변경 | 검증 |
| --- | --- | --- |
| IMP-01 | 레거시 CDP 게시 API·시험 삭제 | V2 pytest 147 passed / 1 skipped (Linux) |
| IMP-02 | 대시보드 외부 Chrome 경로 CLI 옵션 삭제, 게시기는 앱 폴더 안 미설정 상태로 시작 | 옵션 거부 시험 추가 |
| IMP-03 | 브랜드 고유명사 규칙(프롬프트 v5)과 품질 검사 3종 | 실제 초안 문장 기반 회귀 시험 |
| IMP-04 | `.ucompany/scripts/check_sdd.py`, `safety_scan.py`, GitHub Actions(macOS·Ubuntu), PR 템플릿 | V1 둘 다 FAIL 0, WARN 1(`accounts.google.com`, G-01) |
| IMP-05 | `drafts/` Git 추적 허용 | 커밋할 초안은 제출 직전 재생성 필요 |
| IMP-06 | Windows 전용 시험 2개를 플랫폼별로 정리(macOS CI 대비) | Linux에서 통과/skip |

## 5. 2026-10-18 후속 반영

[07 제출 전 결정](07-submission-decisions.md) 승인에 따라: G-00 완료(사용자 삭제), G-01 해소(ADR-0003, `safety_scan.py --strict` WARN 0), G-03 구현(IMP-07), 프로필 배정 결함 수정(IMP-09), 초안 일괄 명령(IMP-11)·macOS 스모크(IMP-12) 추가. G-02(초안 재생성·승인)·G-05(Mac 실기기)·G-07(시연 영상)은 진행 중.
