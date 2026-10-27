## 작업 R2-T2: Windows DPAPI 키 저장소 (IMP-32, H3)

### 1. 목표
Windows에서 AI·YouTube API 키를 `.env` 평문 대신 DPAPI로 암호화한 파일(`data/dashboard/secrets.dpapi.json`)에 저장한다. macOS·Linux는 지금처럼 `.env`(0600)를 쓴다. 사용자가 `.env`에 직접 넣은 키도 계속 동작하고, Windows에서는 첫 실행 시 보안 저장소로 옮겨진다.

### 2. 배경과 근거 [코드 확인]
- `dashboard_settings.py`: `_ai_env_path()`(54행), `youtube_api_key()`(57행, `.env` → 환경변수), `save_youtube_api_key()`(85행), `_read_ai_env()`(113행), `_write_ai_env()`(139행, `chmod 0o600` — Windows에서는 효과 없음), `save_ai()`(516행), `ai_public()`의 키 조회(342행).
- 보고서가 제안한 `profile_emails` DPAPI 재사용은 불가(IMP-18에서 삭제). 새로 구현한다.
- `data/`는 git·패키징(IMP-30)에서 제외된다. DPAPI 암호문은 같은 Windows 사용자만 복호화할 수 있어 다른 PC·다른 사용자·백업 유출에 안전하다(같은 사용자 프로세스는 ADR-0002상 범위 밖).

### 3. 저장소와 실행 환경
- 경로: `$HOME/mnt/marketing_agent`, 라운드 2 브랜치
- 좁은 테스트: `PYTHONDONTWRITEBYTECODE=1 $HOME/venv-ma/bin/python -m pytest -q -p no:cacheprovider tests/test_secret_store.py tests/test_dashboard.py`
- 이 환경은 Linux다. DPAPI(ctypes) 호출 자체는 실행할 수 없으므로 암호화 함수는 주입 가능하게 만들고, 테스트는 가짜 암호화 함수로 한다.

### 4. 사양
1. 새 모듈 `src/marketing_agent/secret_store.py`:
   - `DpapiFileStore(path, protect, unprotect)`: `get(name) -> str | None`, `set(name, value)`, `delete(name)`, `names()`. 파일은 `{"version": 1, "secrets": {이름: base64(암호문)}}`. 쓰기는 임시파일 + fsync + `os.replace`, 심볼릭 링크·64KB 초과·형식 오류는 `ValueError("SECRET_STORE_INVALID")`.
   - `dpapi_protect(data: bytes) -> bytes`, `dpapi_unprotect(data: bytes) -> bytes`: `ctypes.windll.crypt32.CryptProtectData`/`CryptUnprotectData`, `CRYPTPROTECT_UI_FORBIDDEN`(0x1), 엔트로피 `b"marketing_agent/v1"`, `LocalFree`로 버퍼 해제. Windows가 아니면 호출 시 `OSError`.
   - `default_store(app_root: Path) -> DpapiFileStore | None`: `os.name == "nt"`이면 `app_root/"data"/"dashboard"/"secrets.dpapi.json"` 저장소, 아니면 `None`.
2. `DashboardSettings.__init__`에 키워드 `secret_store=_DEFAULT`를 추가(기본값이면 `default_store(self.path.parent)`). 
   - 읽기: 보안 저장소 → `.env` → 환경변수 순.
   - 쓰기(`save_ai`의 키, `save_youtube_api_key`): 저장소가 있으면 `store.set` 후 `.env`에서 그 키 줄만 제거. 저장소가 없으면 지금과 같다.
   - 이전: 저장소가 있고 `.env`에 키 줄이 있으면 첫 읽기 때 저장소로 옮기고 `.env`에서 제거한다. `protect`가 실패하면 `.env`를 그대로 두고 계속 동작한다(키를 잃지 않음).
3. 키 값은 예외 메시지·로그·응답에 넣지 않는다.
4. `check_sdd.py`가 대시보드 import 모듈의 색인 등록을 검사하므로 `.ucompany/sdd/graph.json`과 `00_index.md`에 `secret_store.py` 노드를 기존 노드 형식대로 추가한다.
5. README의 키 안내에 "Windows에서는 저장 시 암호화되어 `data/dashboard/`에 보관되고 `.env`에서 지워진다" 한 줄을 추가한다.

### 5. 먼저 작성할 실패 테스트 (`tests/test_secret_store.py`, 새 파일)
가짜 암호화: `protect=lambda b: b[::-1] + b"!"`, `unprotect`는 그 역. 실패 주입용 `protect`는 `OSError`.

| 테스트 | 기대 동작 |
| --- | --- |
| `test_store_roundtrip_and_file_has_no_plaintext` | set/get 왕복, 파일 내용에 원문 키 문자열 없음 |
| `test_store_rejects_symlink_and_corrupt_file` | 심볼릭 링크·깨진 JSON → `SECRET_STORE_INVALID` |
| `test_save_ai_key_goes_to_store_not_env` | 저장소 주입한 `DashboardSettings`로 `save_ai` → `.env`에 키 줄 없음, `ai_public()["has_key"]` True |
| `test_youtube_key_goes_to_store_not_env` | `save_youtube_api_key` → `.env`에 없음, `youtube_api_key()`가 값 반환 |
| `test_existing_env_keys_migrate_to_store` | `.env`에 AI·YouTube 키가 있으면 첫 읽기 후 저장소로 옮겨지고 `.env`의 다른 줄은 유지 |
| `test_migration_keeps_env_when_protect_fails` | `protect`가 실패하면 `.env` 키 유지, 읽기는 계속 성공 |
| `test_default_store_only_on_windows` | `monkeypatch.setattr(os, "name", "posix")` → `None` |
| `test_no_store_keeps_env_behavior` | `secret_store=None`이면 기존처럼 `.env`에 저장 |

### 6. 수정 범위
- 허용: `src/marketing_agent/secret_store.py`, `src/marketing_agent/dashboard_settings.py`, `tests/test_secret_store.py`, `tests/test_dashboard.py`, `.ucompany/sdd/graph.json`, `.ucompany/sdd/00_index.md`, `README.md`, `HOW_TO_SETTING.md`
- 동결: `dashboard.py`, `storage.py`, `posting_service.py`, `drafts.py`, `ai_client.py`
- 하지 말 것: 실제 `.env`·`data/` 열기, 키 값 출력, 외부 패키지(`keyring` 등) 추가

### 7. 완료 조건
- [ ] 5번 테스트가 수정 전 실패, 수정 후 통과
- [ ] 전체 테스트 실패 0, V1 0·0
- [ ] 커밋 1개: `fix(settings): Windows에서 API 키를 DPAPI 저장소에 보관 (R2-T2)`, 본문 `Spec: IMP-32  Task: IMP-32` + Verify 줄(V4: Windows 실기 미수행)

## 게이트 입력
```json
{"task_id": "R2-T2", "spec": "IMP-32",
 "allowed_files": ["src/marketing_agent/secret_store.py", "src/marketing_agent/dashboard_settings.py", "tests/test_secret_store.py", "tests/test_dashboard.py",
                   ".ucompany/sdd/graph.json", ".ucompany/sdd/00_index.md", "README.md", "HOW_TO_SETTING.md"],
 "new_tests": ["tests/test_secret_store.py"],
 "frozen": [{"path": "src/marketing_agent/dashboard.py"}, {"path": "src/marketing_agent/storage.py"},
            {"path": "src/marketing_agent/posting_service.py"}, {"path": "src/marketing_agent/drafts.py"}, {"path": "src/marketing_agent/ai_client.py"}],
 "baseline_passed": 206}
```
