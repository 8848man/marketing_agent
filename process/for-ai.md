---
doc: process-for-ai
audience: AI agents (Claude, Codex) working in this repo
human_version: process/for-humans.md
router: PROCESS.md
authority: code > .ucompany/sdd (spec/tasks/ADR) > this file
updated: 2026-10-18
---

# PROCESS — AI용 구조화 기록

규칙: 사실 확인은 코드와 SDD에서 한다. 이 파일은 **무엇이 왜 그렇게 되었는지**와 **되돌리면 안 되는 것**의 색인이다. 프롬프트 원문은 복사하지 않고 코드를 가리킨다(사람용 문서의 원문은 `tests/test_process_docs.py`가 코드와 대조한다).

## 1. 고정 사실

| key | value |
| --- | --- |
| product | 로컬 대시보드: RSS 영상 목록 → 고민 한 줄·댓글 초안 → 사람 승인 → 앱 전용 Chrome 프로필로 게시·확인 |
| entry | `python -m marketing_agent dashboard --port 8770` → `src/marketing_agent/__main__.py` → `dashboard.py:ConfiguredPostingService` |
| prompt_source | `src/marketing_agent/prompt_policy.py:build_draft_prompt` (현행 `draft-v7-scene-first-reviewed`) |
| second_pass | `src/marketing_agent/draft_review.py` (`review_problems`, `MAX_REVISIONS=2`), 설정 `comment.review_filter` 기본 true |
| quality_gate | `src/marketing_agent/drafts.py:quality_failure` — 승인·게시 모두 차단 |
| legacy_cli_prompts | `src/marketing_agent/writer.py` (초안·로그만, 게시 없음) |
| posting | `src/marketing_agent/poster.py` (Playwright + 설치 Chrome, `channel="chrome"`, 앱 전용 `data/dashboard/chrome-profile-*`) |
| time_spent | 약 3일, 계측값 아님 |
| dev_os | Windows (개발·실게시 확인). macOS 실기기 없음 |
| mac_verification | GitHub Actions만: `ci.yml`(macos-latest pytest+safety), `mac-smoke.yml`(main push: 설치→Chrome 탐지→대시보드 200→앱 프로필 Chrome으로 watch 페이지 ko-KR→safety strict). 2026-10-18 통과 |
| mac_unverified | 실계정 로그인 후 `check_signed_in`=SIGNED_IN, `_open_login_window`(subprocess Chrome) 실행, 댓글 입력·게시·확인 |
| ai_tools | Codex+PowerShell(초기 구현·SDD), Claude(2026-10-18 SDD 통합·검토·v6/v7·IMP-07~20), 앱 내 AI 제공사(OpenAI/Gemini/Claude/xAI 중 설정값) |

## 2. 불변 조건 (되돌리지 말 것)

| id | invariant | enforced_by |
| --- | --- | --- |
| INV-1 | Chrome 프로필 내부 파일·쿠키·비밀번호를 읽지 않는다. CDP 접속 코드 없음 | `safety_scan.py --strict`, ADR-0003 |
| INV-2 | 프로그램이 여는 페이지는 우리 채널(+등록 테스트) watch 페이지뿐. Google 계정 URL·YouTube 홈 금지 | `safety_scan.py`, `poster._on_watch_page` |
| INV-3 | 댓글 외 동작 없음(구독·좋아요·설정 변경 금지) | poster 범위, 리뷰 |
| INV-4 | 게시 직전 실시간 RSS로 소속 재확인. 캐시·대체 목록을 쓰지 않음 | `rss_feed.recheck_video` (IMP-14, IMP-20) |
| INV-5 | 영상당 1개, 하루 10개, 결과 불확실 시 자동 재시도 없음 | `storage` 고유 인덱스·`limits.daily_max_comments` |
| INV-6 | 사람 승인(`approval_hash == content_hash`, reviewer·reviewed_at) 없이는 게시 불가 | `drafts.preview` |
| INV-7 | 이메일·키를 저장·로그·커밋하지 않음. 프로필 메모는 `@` 거부 | `save_profile_memo` (IMP-18), AGENTS.md |
| INV-8 | 개발 PC에서 우리 채널 게시 금지: `data/dashboard/DEV_BLOCK_OUR_CHANNELS` | `posting_service.dev_guard_enabled` (IMP-10) |
| INV-9 | 첫 프로필 확인 전 다른 프로필 확인·로그인 금지, 재배정은 게시 시도 없는 영상만 | `dashboard._require_primary`, `storage.rebalance_dashboard_assignments` (IMP-19) |
| INV-10 | 브랜드명은 고유명사로만, 부정적 프레이밍 금지 | `BRAND_MISUSED`, `BRAND_NEGATIVE_FRAMING` (IMP-03) |

## 3. 실패 기록

형식: `id | symptom | root_cause | fix | refs`. 사람용 서술은 [for-humans.md#실패와-개선](for-humans.md#실패와-개선).

| id | symptom | root_cause | fix | refs |
| --- | --- | --- | --- | --- |
| F1 | 계정 확인이 `확인 불가` 빈발 | 지연 렌더링, 이메일 숨김 화면, 쿠키 미사용 제약 | 대기·판별 순서 조정 → 최종적으로 F6 방식으로 대체 | U-series, H18 |
| F2 | 초안이 마음을 움직이는지 평가 늦음 | UI 기능 우선 | 인기 댓글 선택적 근거, 구체 표현 인용. 반응 측정은 미수행 | `captions.VideoEvidence` |
| F3 | 재시작 후 저장 403, 키 오류 원인 흐림 | 세션 토큰 만료, 오류 미구분 | 새로고침 안내, 키 오류 구분·설정 진입 | U13 |
| F4 | "운명원"을 일반명사·부정 문맥으로 사용 | 브랜드 설명만으로 고유명사임을 모델이 모름 | 프롬프트 v5 + 품질 검사 2종 | IMP-03, INV-10 |
| F5 | 테스트 영상 없이 우리 채널 7개에 게시 | 실화면 검증 중 대상 통제 부재 | 사용자가 7건 삭제, 개발 가드 | G-00, IMP-10, INV-8 |
| F6 | 계정 확인이 Google·YouTube 홈을 엶 | 확인 경로가 허용 범위 밖 | watch 페이지에서만 확인·로그인, 이메일 표시 폐기 → 메모 | IMP-08, ADR-0003, IMP-18 |
| F7 | v5 초안 15개 중 9개 수작업 수정 필요 | 인용 대상·칭찬·길이 규칙 부재 | 수정 사유를 v6 규칙으로 이관, 재생성 비교 | IMP-13 |
| F8 | v6: 120자 초과 4/9, 운명원 문장 반복 | 모델은 글자 수·타 초안 반복을 못 봄 | 서버 2차 필터(LENGTH·RULE·QUOTE_TOO_LONG·SAME_QUOTE·GENERIC·REPEATED_CLOSING) + AI 재작성 ≤2회, v7, RSS 재시도·캐시 | IMP-14/15/16 |
| F9 | 재시작마다 배정 흔들림, 기준 프로필 없는 조합 | 로그인 확인이 메모리에만 존재 | `dashboard_profile_status` 영속, 유튜브1 우선, 미시도 영상만 재배정 | IMP-19, INV-9 |
| F10 | 새 클론에서 영상 0개, `/api/channels/test` 503 | YouTube RSS 서버 500(브라우저에서도), 새 클론은 캐시 없음 | 승인 초안 영상 표시용 대체, RSS 오류 한국어화 | IMP-20, INV-4 |

## 4. 프롬프트 버전

| version | change | trigger |
| --- | --- | --- |
| draft-v2 | 운명원·사주 고정 문구 | — |
| draft-v3-brand | 브랜드명·설명을 데이터로 | 브랜드 설정 |
| draft-v4-comment-settings | 글자 수 설정 반영 | H21 |
| draft-v5-brand-proper-noun | 고유명사·긍정 프레이밍 규칙 | F4 |
| draft-v6-scene-first | 영상 장면 우선 인용, 인용 금지 대상, 일반 칭찬 금지, 목표 길이 | F7 |
| draft-v7-scene-first-reviewed | 고민별 마무리(재회운·궁합·결혼운·인연 시기), 2차 필터 연동 | F8 |

재작성 요청 형식: 원 요청 + `previous_draft` + `fix[]`, instruction 앞에 "Rewrite previous_draft so that every item in fix is resolved…". 버전 문자열은 초안 JSON의 `prompt_version`에 저장(재작성 시 `+refine`).

## 5. 열린 항목 (2026-10-18 기준)

| item | state | owner |
| --- | --- | --- |
| v7 미승인 초안 11건 승인·커밋 | 대기 | 사용자 |
| macOS 실기기 로그인·게시 | 미검증 (Actions 스모크만) | — |
| 시연 영상, 저장소 Public 전환 | 대기 | 사용자 |
| 게시 후 반응 측정(광고 느낌·공감도) | 미수행 | — |

## 6. 이 파일을 고칠 때

- 새 실패·개선은 `for-humans.md`(서술)와 이 파일(표 한 줄)에 **둘 다** 추가하고, 관련 IMP/ADR ID를 refs에 적는다.
- 프롬프트를 바꾸면 `prompt_policy.py` → `for-humans.md` 원문 → 4절 표 순서로 갱신한다. `tests/test_process_docs.py`가 원문 불일치를 잡는다.
- 사실이 코드·SDD와 다르면 코드·SDD를 따르고 이 파일을 고친다.
