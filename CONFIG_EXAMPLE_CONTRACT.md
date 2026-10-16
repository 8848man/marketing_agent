# 예시 설정 파일 계약

이 표는 저장소에 포함된 예시 파일과 현재 파서의 대응이다. 실제 `config.yaml`·`.env` 값은 검사하거나 이 문서에 기록하지 않는다. 대시보드와 레거시 CLI는 서로 다른 스키마를 사용하며 같은 파일로 합치지 않는다.

## `config.example.yaml` — 대시보드

`DashboardSettings`는 `config.yaml`이 없으면 이 예시를 읽는다. 화면에서 저장하는 YAML은 아래 네 최상위 필드가 정확히 있어야 한다. 시작 시 기존 파일에는 누락 필드의 기본값을 채우지만, 새 파일을 편집할 때는 예시를 유지한다.

| 필드 | 필수/제약 | 소비 위치 |
| --- | --- | --- |
| `profiles` | 1~20개 고유 표시 이름. 기본 3개 이름은 전용 Chrome 프로필에 대응하며 경로가 아니다. | `dashboard_settings.py`의 `_validate`, 프로필 목록·선택 |
| `channels` | 중복 없는 `UC` 채널 ID 5~20개. RSS와 게시 대상 범위를 제한한다. | `dashboard_settings.py`의 `_validate`, `rss_feed.py`, `posting_service.py` |
| `comment.min_chars`, `comment.max_chars`, `comment.brand` | 각각 `40`, `120`, `운명원`으로 고정. | `dashboard_settings.py`의 `_validate`, 초안 품질 검사 |
| `limits.daily_max_comments` | `10`으로 고정. | `dashboard_settings.py`의 `_validate`, `posting_service.py` |
| `dashboard_test_videos` | 기본 빈 목록. 소유 증거 등록 명령에만 사용하며 항목은 `video_id`, `channel_id`, `title`을 가진다. 목록 등록만으로 게시 권한이 생기지 않는다. | `__main__.py`의 `_load_test_videos`, `posting_service.py`의 `_test_cards` |

## `config.legacy.example.yaml` — 읽기 중심 보조 CLI

`config.py`의 `load_config`가 읽는다. `topic`과 `keywords`가 필수이며 나머지는 기본값이 있다. 이 파일의 `comment`·`limits`는 레거시 분석/초안 설정이며 대시보드의 고정 PDF 계약을 바꾸지 않는다. 보조 CLI의 공개 게시 호출은 비활성화되어 있다.

| 필드 | 필수/기본값 | 소비 위치 |
| --- | --- | --- |
| `topic`, `keywords` | 필수 비어 있지 않은 문자열, 비어 있지 않은 문자열 목록 | `config.py`의 `load_config`, 레거시 키워드 탐색 |
| `poll_interval_min` | 기본 30분 | `config.py`, 레거시 주기 실행 |
| `trigger.min_views`, `max_views`, `max_age_hours`, `min_views_per_hour` | 기본 1000, 5000, 12, 150 | `config.py`, 레거시 후보 판정 |
| `comment.min_chars`, `max_chars` | 기본 40, 120 | `config.py`, 레거시 초안 |
| `limits.daily_max_comments`, `channel_cooldown_hours` | 기본 10, 24 | `config.py`, 레거시 제한 정보 |
| `chrome_debug_url` | 기본 `http://localhost:9222`; 로컬 HTTP CDP URL만 허용 | `config.py`, 레거시 연결 설정. 보조 CLI 공개 게시 비활성화 |
| `allowed_videos` | 기본 빈 목록 | `config.py`, 레거시 후보 필터 |
| `daily_search_budget` | 기본 100 | `config.py`, 레거시 검색 제한 |

## `.env.example` — 선택적인 대시보드 키

`DashboardSettings`가 앱 루트 `.env`를 읽고 화면에서 입력한 키도 그 파일에 저장한다. 비어 있는 변수는 허용된다. AI 초안 생성에는 **선택한 제공사의 키**가 필요하다. `YOUTUBE_API_KEY`는 인기 댓글 근거 조회에만 사용한다.

| 변수 | 사용처 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI 어댑터 |
| `GEMINI_API_KEY` | Gemini 어댑터 |
| `ANTHROPIC_API_KEY` | Claude 어댑터 |
| `XAI_API_KEY` | Grok 어댑터 |
| `YOUTUBE_API_KEY` | YouTube Data API 인기 댓글 근거 |

실제 `.env`, `config.yaml`, `data/`, `drafts/`는 Git에 넣지 않는다. 예시의 로더 시험과 최신 수락 결과는 [적용 상태](IMPLEMENTATION_STATUS_2026-10-17.md)를 따른다.
