#!/usr/bin/env python3
"""추적 파일 기반 배포 패키징 (IMP-30).

git이 추적하는 파일만 `git archive`로 zip에 담고, 금지 항목(로그인 정보·키·DB·
실행 데이터)이 들어 있으면 zip을 만들지 않는다. 표준 라이브러리만 사용한다.

종료 코드: 0 = 생성됨, 1 = 위반으로 생성 안 함, 2 = 실행 불가.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

PREFIX = "marketing_agent/"
FORBIDDEN_FILENAMES = {"Cookies", "Login Data", "Local State"}
FORBIDDEN_SUFFIXES = (".db", ".sqlite", ".sqlite3")
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"xai-[A-Za-z0-9]{20,}"),
]


def _name_violation(name: str) -> str | None:
    """경로(접두어 제외) 하나의 금지 이름 규칙 위반 사유. 없으면 None."""
    parts = [p for p in name.split("/") if p]
    if not parts:
        return None
    base = parts[-1]
    if ".git" in parts:
        return ".git/"
    if parts[0] == "data":
        return "data/ 아래 파일"
    if any("chrome-profile" in p for p in parts):
        return "chrome-profile 경로"
    if base == ".env" or (base.startswith(".env.") and base != ".env.example"):
        return ".env 파일"
    if name == "config.yaml":
        return "루트 config.yaml"
    if base in FORBIDDEN_FILENAMES:
        return f"브라우저 파일 {base}"
    if base.lower().endswith(FORBIDDEN_SUFFIXES):
        return "DB 파일"
    return None


def find_violations(names, read_text) -> list[str]:
    """항목 이름 목록과 내용 읽기 함수(read_text(name) -> str|None)로 위반 목록을 만든다."""
    found: list[str] = []
    for name in names:
        reason = _name_violation(name)
        if reason:
            found.append(f"{name}: 금지 이름 ({reason})")
            continue
        if name.endswith("/"):
            continue
        text = read_text(name)
        if not text:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                found.append(f"{name}: 금지 내용 (키 패턴 {pat.pattern[:6]}…)")
                break
    return found


def _strip(name: str) -> str:
    return name[len(PREFIX):] if name.startswith(PREFIX) else name


def build(repo, ref: str, out) -> int:
    repo, out = Path(repo), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "archive", "--format=zip", f"--prefix={PREFIX}",
             "-o", str(out), ref],
            cwd=repo, check=True, capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        out.unlink(missing_ok=True)
        detail = getattr(exc, "stderr", b"") or b""
        print(f"git archive 실패: {detail.decode('utf-8', 'replace').strip()}")
        return 2

    with zipfile.ZipFile(out) as zf:
        raw_names = zf.namelist()
        names = [_strip(n) for n in raw_names]
        lookup = dict(zip(names, raw_names))

        def read_text(name: str):
            data = zf.read(lookup[name])
            if b"\0" in data:
                return None
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return None

        violations = find_violations(names, read_text)

    if violations:
        out.unlink(missing_ok=True)
        print("패키지를 만들지 않았습니다. 위반 항목:")
        for v in violations:
            print(f"  - {v}")
        return 1

    count = sum(1 for n in names if n and not n.endswith("/"))
    print(f"{out} ({count}개 항목, 위반 0)")
    return 0


def _dirty(repo: Path) -> bool:
    res = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                         cwd=repo, capture_output=True, text=True)
    return bool(res.stdout.strip())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="git 추적 파일만으로 배포 zip 생성")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    out = args.out
    if out is None:
        res = subprocess.run(["git", "rev-parse", "--short", args.ref],
                             cwd=repo, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"ref를 찾을 수 없습니다: {args.ref}")
            return 2
        out = repo / "dist" / f"marketing_agent-{res.stdout.strip()}.zip"
    if _dirty(repo):
        print("경고: 커밋되지 않은 변경은 포함되지 않습니다.")
    return build(repo, args.ref, out)


if __name__ == "__main__":
    sys.exit(main())
