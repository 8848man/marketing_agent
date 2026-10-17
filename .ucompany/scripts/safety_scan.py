"""Static safety scan for the Track 2 reviewer rules (PDF p.4 "안전 규칙").

Run from the project root:  python .ucompany/scripts/safety_scan.py [--strict]

* FAIL  - hard violations: browser credential/cookie access, CDP attach to a user
          Chrome, tracked secrets or local config. Always exit 1.
* WARN  - outbound hosts outside the PDF allowance (YouTube + AI providers).
          Exit 1 only with --strict (use --strict before submission).

This is a guard rail for reviewers and CI, not a proof of compliance; the
human code review in workflow.md stage 3 still applies.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

FORBIDDEN = {
    r"connect_over_cdp": "attaches to a user-launched Chrome (CDP)",
    r"--remote-debugging-port": "opens a debugging port on Chrome",
    r"\.cookies\(": "reads browser cookies",
    r"add_cookies|storage_state": "exports/imports browser session state",
    r"Login Data|Cookies['\"]|Local State|Web Data": "opens Chrome profile internals",
    r"browser_cookie3|pycookiecheat|keyring\.get_password|security find-generic-password":
        "reads stored browser secrets",
}
ALLOWED_HOSTS = {
    # YouTube (RSS, watch pages, thumbnails, Data API)
    "www.youtube.com", "youtube.com", "i.ytimg.com", "www.googleapis.com",
    # AI providers (only the configured one is called)
    "api.openai.com", "generativelanguage.googleapis.com", "api.anthropic.com", "api.x.ai",
    # local dashboard / documentation-only values
    "127.0.0.1", "localhost", "example.com",
}
NAMESPACE_HOSTS = {"www.w3.org", "search.yahoo.com", "purl.org"}  # XML namespaces, never fetched
URL = re.compile(r"https?://([A-Za-z0-9.\-]+)(?::\d+)?")
SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,}|xai-[A-Za-z0-9]{20,}|"
                    r"sk-ant-[A-Za-z0-9_\-]{20,})")
NEVER_TRACKED = (".env", "config.yaml")


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
        return out.stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        return []


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    fails: list[str] = []
    warns: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, why in FORBIDDEN.items():
                if re.search(pattern, line):
                    fails.append(f"{rel}:{lineno}: {why}: {line.strip()[:100]}")
            for host in URL.findall(line):
                if "{" in host or host in ALLOWED_HOSTS or host in NAMESPACE_HOSTS:
                    continue
                warns.append(f"{rel}:{lineno}: outbound host outside PDF allowance: {host}")
    files = tracked_files()
    for name in NEVER_TRACKED:
        if name in files:
            fails.append(f"{name}: local secret/config file is tracked by git")
    for rel in files:
        path = ROOT / rel
        if path.suffix.lower() in {".png", ".jpg", ".pdf", ".db", ".tgz"} or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if SECRET.search(text):
            fails.append(f"{rel}: looks like it contains an API key")
    for line in fails:
        print("FAIL", line)
    for line in warns:
        print("WARN", line)
    print(f"safety_scan: {len(fails)} fail, {len(warns)} warn")
    return 1 if fails or (strict and warns) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
