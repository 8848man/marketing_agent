# 외부 요청과 비밀정보 경계

이 표는 현재 저장소 코드의 호출 지점을 기록한다. 제공사의 서버 측 보존·재전송 정책을 보증하지 않는다. 모든 라이브 호출은 해당 기능을 실행할 때만 일어난다.

| 호출 지점 | 고정 대상 | 키 전달 | 리다이렉트/응답 제한 | 오류·로그 |
| --- | --- | --- | --- | --- |
| 채널 RSS (`rss_feed.py`) | `www.youtube.com/feeds/videos.xml` | 없음 | 리다이렉트 차단, 2,000,000바이트 | 고정 `FeedError` 코드 |
| 인기 댓글 (`captions.py`) | `www.googleapis.com/youtube/v3/commentThreads` | `key` 쿼리 | 리다이렉트 차단, 200,000바이트 | 고정 `COMMENTS_*` 코드, URL 비출력 |
| 레거시 탐지 (`pipeline.py`) | `www.googleapis.com/youtube/v3/{search,videos,commentThreads}` | `key` 쿼리 | 리다이렉트 차단, 1,000,000바이트 | 고정 `YOUTUBE_API_*` 코드, URL 비출력 |
| OpenAI/xAI (`ai_client.py`) | 각각 `api.openai.com`, `api.x.ai` | `Authorization` 헤더 | 리다이렉트 차단, 1,000,000바이트 | 고정 `AI_*` 코드, 응답 본문 비출력 |
| Anthropic (`ai_client.py`) | `api.anthropic.com` | `x-api-key` 헤더 | 같은 AI 제한 | 같은 AI 오류 정책 |
| Gemini (`ai_client.py`) | `generativelanguage.googleapis.com` | `x-goog-api-key` 헤더 | 같은 AI 제한 | 같은 AI 오류 정책 |

YouTube 쿼리 키는 요청 URL에 포함되므로 URL을 예외·로그·화면에 직렬화하지 않는다. HTTP 리다이렉트는 다른 호스트로 키가 넘어가지 않도록 차단한다. AI 응답은 제한 길이를 명시한 `read(limit+1)`만 허용하며, 오류 응답 본문은 읽지 않는다. CLI 최상위 오류에도 예외 메시지를 출력하지 않는다. 새 제공사/외부 호출을 추가할 때는 고정 호스트, 키 전달 방식, 리다이렉트·크기·오류 코드를 이 표에 추가하고 모의 회귀를 작성한다.

다른 로컬 프로세스에 대한 인증, 제공사 서버의 데이터 처리, 네트워크 프록시/운영체제 로그는 이 코드 수준의 경계로 해결되지 않는다. 적용 상태는 [`.ucompany/sdd/improvements/2026-10-17/04-remediation-gap-audit.md`](../improvements/2026-10-17/04-remediation-gap-audit.md)를 따른다.
