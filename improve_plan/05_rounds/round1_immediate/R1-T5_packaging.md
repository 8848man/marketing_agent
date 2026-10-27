## 작업 R1-T5: 추적 파일 기반 배포 패키징 (IMP-30, H4)

### 1. 목표
배포용 zip을 **git이 추적하는 파일만으로** 만들고, 금지 항목(로그인 정보·키·DB·실행 데이터)이 들어가면 zip을 만들지 않는 스크립트를 제공한다.

### 2. 배경과 근거 [코드 확인]
- `data/dashboard/chrome-profile-*`에 `Cookies`·`Login Data`가 있다(D-008: 위치는 유지). `.gitignore`가 `data/`·`.env`·`config.yaml`을 제외하므로 git 경로로는 안전하지만, 폴더를 직접 압축하면 섞인다.
- 추적 파일만 쓰면 허용 목록을 따로 관리할 필요가 없다(`git archive`).

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 브랜치 `fix/IMP-27-30-round1-immediate`
- 좁은 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_package.py`

### 4. 명령행 사양
```
python scripts/package.py [--ref HEAD] [--out dist/marketing_agent-<짧은해시>.zip]
```
- `git archive --format=zip --prefix=marketing_agent/ <ref>`로 만든 뒤 zip 항목을 검사한다.
- 금지 이름 규칙(경로 기준, `marketing_agent/` 접두어 제외): `.env`(단 `.env.example` 허용), 루트 `config.yaml`, `data/` 아래 전부, `chrome-profile` 포함 경로, 파일명 `Cookies`·`Login Data`·`Local State`, 확장자 `.db`·`.sqlite`·`.sqlite3`, `.git/`.
- 금지 내용 규칙(텍스트 파일만): `sk-[A-Za-z0-9_-]{20,}`, `AIza[0-9A-Za-z_-]{35}`, `xai-[A-Za-z0-9]{20,}`.
- 위반이 있으면 출력 파일을 지우고 위반 목록을 출력, 종료 코드 1. 없으면 경로와 항목 수 출력, 종료 코드 0.
- 작업 트리에 미커밋 변경이 있으면 "커밋되지 않은 변경은 포함되지 않습니다" 경고만 출력한다.
- 함수로도 쓸 수 있게 `find_violations(names, read_text) -> list[str]`와 `build(repo, ref, out) -> int`를 둔다.

### 5. 먼저 작성할 실패 테스트 (`tests/test_package.py`, 새 파일)
`importlib.util.spec_from_file_location`으로 `scripts/package.py`를 불러온다. git 저장소는 `tmp_path`에 만든다.

| 테스트 | 기대 동작 |
| --- | --- |
| `test_untracked_profile_is_not_packaged` | 추적 파일 `README.md` + 추적 안 된 `data/dashboard/chrome-profile-x/Default/Cookies`가 있는 저장소에서 `build` → 종료 0, zip에 `README.md`만 있고 `data/` 없음 |
| `test_tracked_forbidden_file_blocks_package` | `git add -f data/x.db`로 강제 추적하면 `build` → 종료 1, 출력 파일 없음 |
| `test_find_violations_patterns` | `.env` 금지, `.env.example` 허용, `Login Data`·`config.yaml`(루트)·`posts.sqlite3` 금지, `src/config.py` 허용 |
| `test_secret_content_blocks_package` | 추적 파일 내용에 `sk-` 패턴(테스트용 가짜 문자열)이 있으면 종료 1 |

### 6. 수정 범위
- 허용: `scripts/package.py`, `tests/test_package.py`, `.gitignore`(`dist/` 한 줄 추가), `README.md`(배포 안내 절 추가)
- 동결: `src/` 전체
- 하지 말 것: 실제 `data/` 폴더 열기·목록 출력, 실제 저장소에서 zip 생성 후 남겨 두기(확인용으로 만들었으면 지운다)

### 7. 구현 지침
1. 위 사양대로 표준 라이브러리(`subprocess`, `zipfile`, `re`, `argparse`, `pathlib`)만 사용.
2. README에 `## 다른 PC로 옮기거나 배포할 때` 절을 부록 앞에 추가: 폴더를 직접 압축하지 말고 GitHub에서 받거나 `python scripts/package.py`를 쓰라는 안내, 이유 한 줄(앱 폴더 `data/`에 로그인된 Chrome 프로필이 있음), 받은 PC에서는 처음 한 번 직접 로그인한다는 안내.
3. 구현 후 실제 저장소에서 `$HOME/venv-ma/bin/python scripts/package.py --out $HOME/pkg-check.zip`을 실행해 위반 0건을 확인하고 결과 줄을 보고서에 적은 뒤 그 zip을 지운다.

### 8. 완료 조건
- [ ] 5번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `feat(package): 추적 파일만 담는 배포 패키징과 금지 항목 검사 (R1-T5)`, 본문 `Spec: IMP-30  Task: IMP-30` + Verify 줄

### 게이트 입력
```json
{"task_id": "R1-T5", "spec": "IMP-30",
 "allowed_files": ["scripts/package.py", "tests/test_package.py", ".gitignore", "README.md"],
 "new_tests": ["tests/test_package.py"],
 "frozen": [{"path": "src/marketing_agent/dashboard.py"}, {"path": "src/marketing_agent/posting_service.py"}],
 "baseline_passed": 177}
```
