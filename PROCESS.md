# 제작 노트

## 목표와 댓글 설계

이 앱의 목표는 영상 시청자가 자신의 연애 고민을 떠올리게 하면서 운명원에 대한 호기심을 자연스럽게 갖도록 돕는 것이다. 영상의 자막을 우선 사용하고, 없으면 제목·설명을 사용한다. YouTube Data API 키가 유효하면 인기 댓글도 참고한다. AI는 `worry_summary`(고민 한 줄), `cited_detail`(영상 근거), `comment`(댓글)를 함께 만들며, `cited_detail`은 실제 근거 문구와 댓글에 모두 있어야 한다. 댓글은 40~120자의 한국어 시청자 시점으로 쓰고 운명원·사주를 자연스럽게 넣는다. 링크·해시태그·확인되지 않은 장면·허위 이용 후기는 금지한다. 최종 문안은 사람이 읽고 고쳐 승인한다. 이 규칙이 실제로 광고 느낌을 줄이고 사람의 마음을 움직였는지는 아직 사용자 반응 자료로 검증하지 못했다.

## 실제 앱의 프롬프트 원문

현재 대시보드의 초안 생성 호출은 선택한 AI 제공사에 다음 **시스템 프롬프트 원문**을 보낸다.

```text
You draft Korean YouTube comments. Return only compact JSON with the required fields. Never claim to have used a service.
```

**사용자 입력의 `instruction` 원문**은 다음과 같다. 함께 전송되는 `evidence`에는 자막 또는 제목·설명과 가져온 인기 댓글이, `sources`에는 사용한 근거 종류가 들어간다.

```text
Use only evidence. Return worry_summary, cited_detail, comment. The cited_detail must be an exact phrase from evidence and also appear in comment. Write a distinct 40-120 Korean character viewer-perspective comment. Include 운명원 and 사주 naturally. No links, hashtags, fabricated testimonials, or invented people, scenes, or quotes.
```

기존 CLI의 댓글 작성 및 적합성 재검사 경로는 대시보드와 별개로 남아 있다. 댓글 작성 시스템 프롬프트 원문:

```text
Write a Korean relationship advice comment. Return JSON with "worry_summary", "cited_detail", "keyword", "body". Quote a concrete detail and keyword exactly from video_text. Use the concern, video evidence and existing comments. Do not invent details or add links.
```

적합성 검사 프롬프트 원문:

```text
Check whether the comment fits the video and its stated concern. Return JSON {"fits": boolean, "reason": string}. Reject invented evidence, generic advice and irrelevant comments.
```

위 내용은 [dashboard.py](src/marketing_agent/dashboard.py)와 [writer.py](src/marketing_agent/writer.py)에 있는 문자열이다. 실제 입력에는 영상 내용과 기존 댓글, 재작성 피드백 등이 JSON으로 추가된다. 어떤 개인 계정의 댓글이 실제로 게시됐는지를 이 제작 노트만으로 증명하지는 않는다.

## 사용 도구와 역할

| 도구 | 사용 위치 |
| --- | --- |
| Codex와 PowerShell | SDD 정리, 코드 수정, 로컬 테스트와 화면 동작 확인 보조 |
| Python·pytest | 로컬 대시보드, 규칙 검사, 회귀 테스트 |
| Playwright와 설치된 Chrome | 앱 전용 프로필의 보이는 YouTube 계정 확인과 댓글 입력·게시·확인 경로 |
| YouTube RSS·자막·Data API | 대상 영상 확인, 영상 근거와 선택적 인기 댓글 수집 |
| 사용자가 설정한 OpenAI·Gemini·Claude·xAI 중 한 제공사 | AI 초안 생성 및 선택적 연결 테스트. 제공사 선택은 설정값이며 모든 제공사를 실제 호출했다는 뜻은 아님 |

## 실패와 개선

1. **보안 제약과 프로필 확인 UX.** 브라우저 저장 파일이나 쿠키를 직접 읽지 않으면서 어느 계정으로 로그인됐는지 확인해야 했다. 앱 전용 Chrome에서 허용된 YouTube 화면을 보이는 상태로 열어 계정 UI를 확인하도록 설계했지만, 지연 렌더링과 이메일을 숨기는 채널 화면 때문에 `확인 불가`가 발생했다. 계정 UI를 기다리고, 이메일 표시를 우선하며, 이메일이 숨겨진 경우에는 보이는 활성 채널명·핸들로 로그인 상태만 확인하도록 하나씩 테스트했다. 앱 내부 상태만으로 판단하기 어려워 로컬 자동 보조와 실제 외부 페이지 UX 검증을 병행했다. 이 경로는 Google 계정 선택 페이지를 여는 현재 안전 규칙의 충돌도 드러냈다.
2. **제품 UX에 치우친 초안 품질.** 프로필 추가, 상태 표시, 오류 복구에 집중하면서 정작 댓글이 사람의 마음을 움직이는지 충분히 평가하지 못했다. 문구만 더 강하게 쓰는 대신 YouTube Data API의 인기 댓글을 근거에 선택적으로 넣고, 영상 자막·제목·설명의 구체 표현을 인용하도록 했다. 그 결과 초안이 더 체험적인 시청자 말투를 낼 수 있는 구조가 됐지만, 실제 반응 향상은 측정하지 못했다. 다음에는 사람 평가와 게시 후 반응을 별도로 확인해야 한다.
3. **설정·상태 불일치.** 대시보드 재시작 후 이전 탭의 세션 토큰이 만료되어 저장 요청이 거부됐고, YouTube API 키가 있어도 인기 댓글 요청이 실패하면 원인이 흐려졌다. 새로고침 안내와 키 오류 구분·설정 진입 버튼을 추가했다. 안전 감사에서는 이 버튼의 클릭 표현 오류도 발견해 수정했다.

## 시간과 다음 개선

총 소요 시간은 **약 3일**이다. 정확한 시작·종료 시각을 계측한 값은 아니다. 다시 만든다면 첫날에 안전 규칙의 허용 예외와 파일 경계를 확정하고, 로그인 상태 세 가지를 실제 Windows·macOS에서 먼저 검증하겠다. 이후 UI를 넓히기 전에 댓글 초안의 공감도·광고 느낌·영상 관련성을 사람 평가표로 반복 측정하겠다. 현재의 안전 규칙 미충족 항목은 [README](README.md)에 공개했고, 그 항목을 해소하기 전에는 심사자 계정에서 안전 준수 완료로 실행·제출하지 않는다.
