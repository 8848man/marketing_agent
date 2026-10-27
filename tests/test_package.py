"""배포 패키징(scripts/package.py) 테스트 (R1-T5, IMP-30)."""

import importlib.util
import subprocess
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package.py"


def _load():
    spec = importlib.util.spec_from_file_location("package_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, check=True, capture_output=True,
    )


def _repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return repo


def _commit(repo, *paths, force=False):
    _git(repo, "add", *(["-f"] if force else []), *paths)
    _git(repo, "commit", "-q", "-m", "init")


def test_untracked_profile_is_not_packaged(tmp_path):
    pkg = _load()
    repo = _repo(tmp_path, {"README.md": "hi\n"})
    _commit(repo, "README.md")
    cookies = repo / "data/dashboard/chrome-profile-x/Default/Cookies"
    cookies.parent.mkdir(parents=True)
    cookies.write_text("x", encoding="utf-8")
    out = tmp_path / "out.zip"
    assert pkg.build(repo, "HEAD", out) == 0
    names = [n for n in zipfile.ZipFile(out).namelist() if not n.endswith("/")]
    assert names == ["marketing_agent/README.md"]
    assert not any("data/" in n for n in zipfile.ZipFile(out).namelist())


def test_tracked_forbidden_file_blocks_package(tmp_path):
    pkg = _load()
    repo = _repo(tmp_path, {"README.md": "hi\n", "data/x.db": "bin"})
    _commit(repo, "README.md")
    _commit(repo, "data/x.db", force=True)
    out = tmp_path / "out.zip"
    assert pkg.build(repo, "HEAD", out) == 1
    assert not out.exists()


def test_find_violations_patterns():
    pkg = _load()
    nope = lambda name: ""  # noqa: E731
    assert pkg.find_violations([".env"], nope)
    assert not pkg.find_violations([".env.example"], nope)
    assert pkg.find_violations(["a/Login Data"], nope)
    assert pkg.find_violations(["config.yaml"], nope)
    assert pkg.find_violations(["posts.sqlite3"], nope)
    assert not pkg.find_violations(["src/config.py"], nope)
    assert not pkg.find_violations(["src/config.yaml"], nope)
    assert pkg.find_violations(["data/a.txt"], nope)
    assert pkg.find_violations(["x/chrome-profile-1/a.txt"], nope)


def test_find_violations_case_insensitive():
    pkg = _load()
    nope = lambda name: ""  # noqa: E731
    for name in ("Data/x", ".ENV", "Config.yaml", "COOKIES", "login data",
                 "Chrome-Profile-1/a", "x.DB", "Data\\x"):
        assert pkg.find_violations([name], nope), name
    assert not pkg.find_violations([".env.example"], nope)
    assert not pkg.find_violations([".ENV.EXAMPLE"], nope)
    assert not pkg.find_violations(["src/config.py"], nope)


def test_secret_content_blocks_package(tmp_path):
    pkg = _load()
    fake = "sk-" + "A" * 24  # 테스트용 가짜 문자열
    repo = _repo(tmp_path, {"notes.txt": f"key={fake}\n"})
    _commit(repo, "notes.txt")
    out = tmp_path / "out.zip"
    assert pkg.build(repo, "HEAD", out) == 1
    assert not out.exists()
