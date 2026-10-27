## 작업 R1-T4: 자막 라이브러리 선언과 누락 안내 (IMP-29, M6)

### 1. 목표
`youtube-transcript-api`를 선택 의존성으로 선언해 기본 설치에 포함하고, 라이브러리가 없을 때 초안 근거 안내에 그 사유가 표시되게 한다.

### 2. 배경과 근거 [코드 확인]
- `src/marketing_agent/captions.py` `YouTubeCaptions.fetch`가 `from youtube_transcript_api import YouTubeTranscriptApi`를 지연 import하고, 모든 예외를 `CaptionResult(failure_reason=f"{type(exc).__name__}: {exc}")`로 삼킨다.
- `VideoEvidence.collect`는 자막이 없으면 제목·설명으로 폴백하지만 `notice`에 사유를 넣지 않는다. `notice`는 화면에 `evidence_notice`로 표시된다(`dashboard.py` 약 587행, `dashboard_ui.py`).
- `pyproject.toml`·`requirements.txt` 어디에도 이 패키지가 없다. `requirements.txt`는 `-e .[test]`와 `playwright`.
- README 부록 D(약 107행)가 의존 패키지와 라이선스를 나열한다.

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 브랜치 `fix/IMP-27-30-round1-immediate`
- 좁은 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_captions.py tests/test_process_docs.py`
- 패키지 API 확인용 설치는 허용: `uv pip install -p $HOME/venv-ma/bin/python "youtube-transcript-api>=1.0,<2"` (네트워크 요청은 설치만, 실제 자막 조회 금지)

### 4. 먼저 작성할 실패 테스트 (`tests/test_captions.py`, 새 파일)
| 테스트 | 기대 동작 |
| --- | --- |
| `test_missing_caption_library_reports_code` | `monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)` 후 `YouTubeCaptions().fetch("AbCdEfGhI12")`의 `failure_reason == "CAPTIONS_LIBRARY_MISSING"` |
| `test_evidence_notice_explains_missing_library` | 가짜 captions(위 코드 반환)·가짜 comments(빈 튜플)로 `VideoEvidence.collect(card)`를 부르면 `sources`는 제목 기반이고 `notice`에 `youtube-transcript-api`가 포함됨 |
| `test_evidence_notice_combines_comment_notice` | 라이브러리 없음 + 댓글 키 없음(`ValueError("COMMENTS_KEY_MISSING")`)이면 두 안내가 모두 `notice`에 포함됨 |
| `test_captions_extra_is_declared_and_installed_by_default` | `tomllib`로 `pyproject.toml`을 읽어 `optional-dependencies.captions`에 `youtube-transcript-api`가 있고, `requirements.txt`의 `-e .[…]`에 `captions`가 포함됨 |

### 5. 수정 범위
- 허용: `pyproject.toml`, `requirements.txt`, `src/marketing_agent/captions.py`, `tests/test_captions.py`, `README.md`(부록 D 표에 한 줄 추가만)
- 동결: `captions.py`의 `YouTubeDataComments` 클래스, `MAX_PRIMARY_CHARS`·`MAX_COMMENT_CHARS` 값, `dashboard_ui.py`, `dashboard.py`
- 하지 말 것: 테스트에서 실제 자막·댓글 조회, 다른 예외 처리 동작 변경

### 6. 구현 지침
1. `pyproject.toml` `[project.optional-dependencies]`에 `captions = ["youtube-transcript-api>=1.0,<2"]`. 설치한 버전에 `YouTubeTranscriptApi().fetch(video_id, languages=[...])`가 있는지 확인하고, 없으면 진행하지 말고 보고.
2. `requirements.txt`의 `-e .[test]` → `-e .[test,captions]`.
3. `YouTubeCaptions.fetch`: `ImportError`를 먼저 잡아 `CaptionResult(failure_reason="CAPTIONS_LIBRARY_MISSING")`, 나머지 예외는 기존 그대로.
4. `VideoEvidence.collect`: 자막 실패 사유가 `CAPTIONS_LIBRARY_MISSING`이면 `"자막 라이브러리(youtube-transcript-api)가 설치되지 않아 제목·설명을 근거로 사용합니다."`를 안내에 넣는다. 댓글 안내가 있으면 공백 하나로 이어 붙인다.
5. README 부록 D 표에 `| youtube-transcript-api | 영상 자막을 초안 근거로 사용(선택) | <설치본 METADATA의 라이선스> | https://github.com/jdepoix/youtube-transcript-api |` 추가.

### 7. 완료 조건
- [ ] 4번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(captions): 자막 라이브러리 선언과 누락 사유 안내 (R1-T4)`, 본문 `Spec: IMP-29  Task: IMP-29` + Verify 줄

### 게이트 입력
```json
{"task_id": "R1-T4", "spec": "IMP-29",
 "allowed_files": ["pyproject.toml", "requirements.txt", "src/marketing_agent/captions.py", "tests/test_captions.py", "README.md"],
 "new_tests": ["tests/test_captions.py"],
 "frozen": [{"path": "src/marketing_agent/captions.py", "function": "YouTubeDataComments.fetch"},
            {"path": "src/marketing_agent/dashboard.py"}, {"path": "src/marketing_agent/dashboard_ui.py"}],
 "baseline_passed": 177}
```
