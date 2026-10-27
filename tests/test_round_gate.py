"""round_gate.py 단위 테스트. 모두 tmp_path의 임시 git 저장소를 사용한다."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

GATE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "round_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("round_gate", GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["round_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def rg():
    return _load()


def git(repo, *args):
    r = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def commit(repo, files, message="init"):
    for rel, content in files.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    return r


GOOD_MSG = "feat(x): 무엇 (T1)\n\nSpec: IMP-1  Task: IMP-1\nVerify: ok\n"


def test_parse_contract_reads_gate_json(rg):
    text = (
        "# 계약\n\n## 게이트 입력\n```json\n"
        '{"task_id": "T1", "spec": "IMP-1", "allowed_files": ["a.py"],'
        ' "new_tests": ["tests/test_a.py"], "frozen": [], "baseline_passed": 3}\n'
        "```\n\n```json\n{\"x\": 1}\n```\n"
    )
    data = rg.parse_contract(text)
    assert data["task_id"] == "T1"
    assert data["allowed_files"] == ["a.py"]
    assert data["baseline_passed"] == 3
    with pytest.raises(ValueError):
        rg.parse_contract("## 게이트 입력\n없음")


def test_g3_rejects_file_outside_allowed(rg, repo):
    base = commit(repo, {"a.py": "1\n"})
    head = commit(repo, {"a.py": "2\n", "b.py": "x\n"}, GOOD_MSG)
    status, _ = rg.check_g3(repo, base, head, ["a.py"])
    assert status == "FAIL"
    status, _ = rg.check_g3(repo, base, head, ["a.py", "b.*"])
    assert status == "PASS"


def test_g4_detects_frozen_function_change(rg, repo):
    src = "def f():\n    return 1\n\n\nclass C:\n    def m(self):\n        return 1\n\n\ndef g():\n    return 1\n"
    base = commit(repo, {"m.py": src})
    h1 = commit(repo, {"m.py": src.replace("def g():\n    return 1", "def g():\n    return 2")})
    frozen_f = [{"path": "m.py", "function": "f"}]
    assert rg.check_g4(repo, base, h1, frozen_f)[0] == "PASS"
    assert rg.check_g4(repo, base, h1, [{"path": "m.py"}])[0] == "FAIL"
    h2 = commit(repo, {"m.py": src.replace("def f():\n    return 1", "def f():\n    return 9")})
    assert rg.check_g4(repo, base, h2, frozen_f)[0] == "FAIL"
    h3 = commit(repo, {"m.py": src.replace("def m(self):\n        return 1", "def m(self):\n        return 5")})
    assert rg.check_g4(repo, base, h3, [{"path": "m.py", "function": "C.m"}])[0] == "FAIL"
    assert rg.check_g4(repo, base, h3, frozen_f)[0] == "PASS"


def test_g5_requires_single_commit_with_ids(rg, repo):
    base = commit(repo, {"a": "1"})
    head = commit(repo, {"a": "2"}, GOOD_MSG)
    assert rg.check_g5(repo, base, head, "T1", "IMP-1")[0] == "PASS"
    # 제목에 ID 없음
    assert rg.check_g5(repo, base, head, "T9", "IMP-1")[0] == "FAIL"
    # Spec 줄 없음
    assert rg.check_g5(repo, base, head, "T1", "IMP-2")[0] == "FAIL"
    # 커밋 2개
    head2 = commit(repo, {"a": "3"}, GOOD_MSG)
    assert rg.check_g5(repo, base, head2, "T1", "IMP-1")[0] == "FAIL"
    # 미커밋 변경
    (repo / "dirty.txt").write_text("x")
    assert rg.check_g5(repo, head, head2, "T1", "IMP-1")[0] == "FAIL"


def test_g6_flags_secret_and_forbidden_paths(rg, repo):
    base = commit(repo, {"a.py": "x = 1\n"})
    ok = commit(repo, {"a.py": "@dec\nx = 2\nmail = 'bot" + "@" + "noreply.example.com'\n"})
    assert rg.check_g6(repo, base, ok)[0] == "PASS"
    key = "sk" + "-" + "A" * 24
    bad1 = commit(repo, {"a.py": f"k = '{key}'\n"})
    assert rg.check_g6(repo, ok, bad1)[0] == "FAIL"
    mail = "person" + "@" + "example.com"
    bad2 = commit(repo, {"a.py": f"m = '{mail}'\n"})
    assert rg.check_g6(repo, bad1, bad2)[0] == "FAIL"
    bad3 = commit(repo, {"data/x.json": "{}\n"})
    assert rg.check_g6(repo, bad2, bad3)[0] == "FAIL"


def test_g1_requires_fail_before_pass_after(rg, repo, tmp_path):
    base = commit(repo, {"lib.py": "def v():\n    return 1\n", "tests/test_n.py": "def test_ok():\n    assert True\n"})
    wt = tmp_path / "wt"
    # base에서도 통과하는 새 테스트
    head_same = commit(repo, {"lib.py": "def v():\n    return 2\n"}, GOOD_MSG)
    status, _ = rg.check_g1(repo, base, head_same, ["tests/test_n.py"], wt_root=wt)
    assert status == "FAIL"
    # base 실패, head 통과
    base2 = head_same
    head_ok = commit(
        repo,
        {"lib.py": "def v():\n    return 3\n\n\ndef w():\n    return 1\n",
         "tests/test_n.py": "from lib import w\n\n\ndef test_w():\n    assert w() == 1\n"},
        GOOD_MSG,
    )
    status, msg = rg.check_g1(repo, base2, head_ok, ["tests/test_n.py::test_w"], wt_root=wt)
    assert status == "PASS", msg
    # head에서도 실패
    head_bad = commit(repo, {"tests/test_n.py": "from lib import w\n\n\ndef test_w():\n    assert w() == 2\n"})
    status, _ = rg.check_g1(repo, base2, head_bad, ["tests/test_n.py::test_w"], wt_root=wt)
    assert status == "FAIL"
    # worktree 정리 확인
    assert not (wt.exists() and any(wt.iterdir()))
    assert "gate-wt" not in git(repo, "worktree", "list")


def test_g0_checks_report_sections(rg):
    full = (
        "## 구현 보고 R1-T2\n- 결과: 완료\n- 커밋: abc msg\n- 변경 파일: a\n"
        "- 실패 확인: x\n- 통과 확인: y\n"
    )
    assert rg.check_g0(full)[0] == "PASS"
    status, msg = rg.check_g0(full.replace("- 통과 확인: y\n", ""))
    assert status == "FAIL" and "통과 확인" in msg
    assert rg.check_g0("아무 말")[0] == "FAIL"


def test_g3_g6_detect_renamed_files(rg, repo):
    base = commit(repo, {"secret.py": "x = 1\n" * 20, "data/a.txt": "hello\n" * 20, "tests/keep.py": "k\n"})
    git(repo, "mv", "secret.py", "tests/x.py")
    head = commit(repo, {}, GOOD_MSG)
    status, msg = rg.check_g3(repo, base, head, ["tests/*"])
    assert status == "FAIL" and "secret.py" in msg
    git(repo, "mv", "data/a.txt", "tests/a.txt")
    head2 = commit(repo, {}, GOOD_MSG)
    status, msg = rg.check_g6(repo, head, head2)
    assert status == "FAIL" and "data/a.txt" in msg


def test_g4_missing_frozen_target_fails(rg, repo):
    src = "def f():\n    return 1\n"
    base = commit(repo, {"m.py": src})
    head = commit(repo, {"other.py": "y = 1\n"})
    status, msg = rg.check_g4(repo, base, head, [{"path": "m.py", "function": "nope"}])
    assert status == "FAIL" and "nope" in msg
    status, _ = rg.check_g4(repo, base, head, [{"path": "absent.py", "function": "f"}])
    assert status == "FAIL"
    assert rg.check_g4(repo, base, head, [{"path": "m.py", "function": "f"}])[0] == "PASS"


def test_g4_detects_decorator_change(rg, repo):
    src = "import functools\n\n\n@functools.cache\ndef f():\n    return 1\n"
    base = commit(repo, {"m.py": src})
    head = commit(repo, {"m.py": src.replace("@functools.cache", "@functools.lru_cache")})
    assert rg.check_g4(repo, base, head, [{"path": "m.py", "function": "f"}])[0] == "FAIL"
    same = commit(repo, {"m.py": src.replace("import functools", "import functools  # c")})
    assert rg.check_g4(repo, base, same, [{"path": "m.py", "function": "f"}])[0] == "PASS"


def test_g6_forbids_env_variants_case_insensitive(rg, repo):
    base = commit(repo, {"a.py": "x = 1\n"})
    for name in (".env.local", ".ENV", "Config.yaml", "Data/x.json", "Chrome-Profile-1/a"):
        head = commit(repo, {name: "v\n"})
        status, _ = rg.check_g6(repo, base, head)
        assert status == "FAIL", name
        git(repo, "rm", "-rq", "--cached", name.split("/")[0])
        base = commit(repo, {"a.py": f"x = '{name}'\n"})
    ok = commit(repo, {".env.example": "A=\n"})
    assert rg.check_g6(repo, base, ok)[0] == "PASS"


def test_g6_email_pattern_ignores_escaped_newline(rg, repo):
    base = commit(repo, {"a.py": "x = 1\n"})
    ok = commit(repo, {"a.py": 'x = "a\\n@functools.cache"\n'})
    assert rg.check_g6(repo, base, ok)[0] == "PASS"
    addr = "user" + "@" + "example.org"
    bad = commit(repo, {"a.py": f'owner = "{addr}"\n'})
    assert rg.check_g6(repo, ok, bad)[0] == "FAIL"
