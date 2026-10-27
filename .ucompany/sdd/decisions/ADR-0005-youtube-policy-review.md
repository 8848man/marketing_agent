---
id: ADR-0005
type: decision
status: proposed
date: 2026-10-27
---

# ADR-0005 — YouTube 정책 검토와 게시 간격

> 상태 **제안**. 법률 검토가 아니며, 운영 전 사용자가 최신 정책 원문을 직접 확인한다. 근거: 분석 보고서 M1, 개선 계획 라운드 2.

## 맥락 (2026-10-27 확인한 정책 원문)

- [YouTube 스팸·기만 행위·사기 정책](https://support.google.com/youtube/answer/2801973?hl=en-GB)은 댓글 스팸을 "high-volume, repetitive or deceptive comments"로 정의하고, 자동화 도구·AI로 비슷한 콘텐츠를 대량 생산하는 것과 "coordinated networks of channels"를 금지 대상으로 든다.
- [YouTube 서비스 약관](https://www.youtube.com/static?gl=EN&template=terms)은 "access the Service using any automated means (such as robots, botnets or scrapers)"를 금지한다. 예외는 공개 검색 엔진과 YouTube의 사전 서면 허가다. 또 "inaccurate measurements of genuine user engagement"를 유발하는 행위를 금지한다.
- 이 앱은 Playwright로 Chrome을 띄워 댓글을 입력·게시한다. 여러 프로필(유튜브1~3)이 타 채널 영상에 브랜드명이 들어간 댓글을 단다.

## 현재 완화 조치

- 모든 게시는 사람이 문안을 검토·승인한 뒤 사람이 버튼을 눌러야 한다.
- 일일 10개(PDF 고정), 영상당 1회, 링크·해시태그·가짜 후기 차단, 2차 필터의 반복 문구 검사.
- 개발 중 우리 채널 게시 차단(`DEV_BLOCK_OUR_CHANNELS`).

## 결정(제안)

1. 제품 경로에 **같은 대상 채널 60분 간격**을 둔다(IMP-33).
2. 브라우저 자동화로 게시하는 방식 자체는 약관의 자동화 접근 금지 조항과 충돌할 소지가 있다. 이 앱은 과제(PDF) 요구로 만든 것이며, **실제 운영 전에 사용자가 정책 적합성을 판단해야 한다**. 대안은 YouTube Data API `commentThreads.insert`(OAuth, 공식 경로)로의 전환이다.
3. 여러 계정으로 같은 브랜드를 홍보하는 운영은 "coordinated networks" 해석에 걸릴 수 있으므로 운영 시 단일 계정 사용을 권장한다.

## 결과

- 최종 점검 보고서에 "운영 전 정책 판단"을 사용자 확인 항목으로 넣는다.
- 공식 API 전환은 이번 개선 범위 밖이다(인증 흐름과 할당량 설계가 필요).
