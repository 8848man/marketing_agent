#!/usr/bin/env python3
"""라운드 작업 게이트 도구 (IMP-27).

작업 커밋 하나가 계약서를 지켰는지 G0~G6을 자동 판정한다.
정의: improve_plan/04_agent_workflow/verification_gates.md
표준 라이브러리만 사용한다.

종료 코드: 0 = PASS, 1 = FAIL(하나라도 실패), 2 = HOLD(실행 불가).
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PASS, FAIL, HOLD = "PASS", "FAIL", "HOLD"

REPORT_ITEMS = [
    "## 구현 보고",
    "- 결과:",
    "- 커밋:",
    "- 변경 파일:",
    "- 실패 확인:",
    "- 통과 확인:",
]

SECRET_PATTERNS = [
    ("sk 키", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("Google 키", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("xai 키", re.compile(r"xai-[A-Za-z0-9]{20,}")),
    ("이메일", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
]


def default_wt_root() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))) / "gate-wt"


def run(cmd, cwd, env=None, timeout=None):
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=timeout,
    )


def git(repo, *args, check=True):
    r = run(["git", *args], repo)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {r.stderr.strip()[:200]}")
    return r.stdout


def show(repo, rev, path):
    """rev:path 내용. 없으면 None."""
    r = run(["git", "show", f"{rev}:{path}"], repo)
    return r.stdout if r.returncode == 0 else None


# ---------------------------------------------------------------- 계약서

def parse_contract(text: str) -> dict:
    m = re.search(r"^##\s*게이트 입력\s*$(.*)", text, re.S | re.M)
    if not m:
        raise ValueError("'## 게이트 입력' 절이 없다")
    b = re.search(r"```json\s*\n(.*?)```", m.group(1), re.S)
    if not b:
        raise ValueError("게이트 입력 아래에 ```json 블록이 없다")
    data = json.loads(b.group(1))
    for key in ("task_id", "spec", "allowed_files", "new_tests", "frozen", "baseline_passed"):
        if key not in data:
            raise ValueError(f"게이트 입력에 '{key}' 키가 없다")
    return data


# ---------------------------------------------------------------- G0

def check_g0(report_text: str):
    missing = [item for item in REPORT_ITEMS if item not in report_text]
    if missing:
        return FAIL, "보고서 항목 누락: " + ", ".join(i.strip("-# :") for i in missing)
    return PASS, "보고서 필수 항목 모두 있음"


# ---------------------------------------------------------------- G1

def _test_env(wt: Path):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    src = wt / "src"
    if src.is_dir():
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _pytest(wt: Path, args):
    return run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        wt, env=_test_env(wt),
    )


def _add_worktree(repo, wt_root: Path, rev: str, suffix: str = ""):
    wt_root.mkdir(parents=True, exist_ok=True)
    wt = wt_root / (rev[:10] + suffix)
    git(repo, "worktree", "add", "--detach", "--force", str(wt), rev)
    return wt


def _remove_worktree(repo, wt: Path):
    run(["git", "worktree", "remove", "--force", str(wt)], repo)
    run(["git", "worktree", "prune"], repo)


def check_g1(repo, base, head, new_tests, wt_root=None):
    repo = Path(repo)
    wt_root = Path(wt_root) if wt_root else default_wt_root()
    if not new_tests:
        return HOLD, "new_tests가 비어 있다"
    files = sorted({t.split("::")[0] for t in new_tests})
    wts = []
    try:
        base_wt = _add_worktree(repo, wt_root, base)
        wts.append(base_wt)
        for f in files:
            content = show(repo, head, f)
            if content is None:
                return FAIL, f"head에 테스트 파일 없음: {f}"
            dest = base_wt / f
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        before = _pytest(base_wt, new_tests)
        if before.returncode == 0:
            return FAIL, "새 테스트가 base에서도 통과함(선행 실패 아님)"
        head_wt = _add_worktree(repo, wt_root, head, "-h")
        wts.append(head_wt)
        after = _pytest(head_wt, new_tests)
        if after.returncode != 0:
            tail = " | ".join(after.stdout.strip().splitlines()[-2:])
            return FAIL, f"새 테스트가 head에서 실패함: {tail}"
        return PASS, f"base 실패(코드 {before.returncode}) -> head 통과"
    except Exception as e:  # noqa: BLE001
        return HOLD, f"G1 실행 불가: {e}"
    finally:
        for wt in wts:
            _remove_worktree(repo, wt)
        run(["git", "worktree", "prune"], repo)
        try:
            wt_root.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------- G2

def _collected(out: str):
    m = re.search(r"(\d+) tests? collected", out)
    if m:
        return int(m.group(1))
    n = sum(1 for ln in out.splitlines() if "::" in ln)
    return n if n else None


def _passed(out: str):
    m = re.search(r"(\d+) passed", out)
    return int(m.group(1)) if m else 0


def check_g2(repo, base, head, baseline_passed, wt_root=None):
    repo = Path(repo)
    wt_root = Path(wt_root) if wt_root else default_wt_root()
    try:
        if git(repo, "rev-parse", "HEAD").strip() != git(repo, "rev-parse", head).strip():
            return HOLD, "저장소 HEAD가 head와 다름(G2는 head 체크아웃 상태에서 실행)"
        problems = []
        for name, cmd in (
            ("check_sdd", [sys.executable, ".ucompany/scripts/check_sdd.py"]),
            ("safety_scan", [sys.executable, ".ucompany/scripts/safety_scan.py", "--strict"]),
        ):
            r = run(cmd, repo)
            if r.returncode != 0:
                problems.append(f"{name} 종료 코드 {r.returncode}")
        full = _pytest(repo, [])
        passed = _passed(full.stdout)
        if full.returncode != 0:
            problems.append(f"전체 pytest 실패(코드 {full.returncode})")
        if passed < baseline_passed:
            problems.append(f"통과 {passed} < 기준선 {baseline_passed}")
        head_n = _collected(_pytest(repo, ["--collect-only"]).stdout)
        base_wt = _add_worktree(repo, wt_root, base)
        try:
            base_n = _collected(_pytest(base_wt, ["--collect-only"]).stdout)
        finally:
            _remove_worktree(repo, base_wt)
            try:
                wt_root.rmdir()
            except OSError:
                pass
        if head_n is None or base_n is None:
            return HOLD, "수집 수를 읽지 못함"
        if head_n < base_n:
            problems.append(f"수집 수 감소 {base_n} -> {head_n}")
        if problems:
            return FAIL, "; ".join(problems)
        return PASS, f"V1 0, 통과 {passed} >= {baseline_passed}, 수집 {base_n} -> {head_n}"
    except Exception as e:  # noqa: BLE001
        return HOLD, f"G2 실행 불가: {e}"


# ---------------------------------------------------------------- G3

def check_g3(repo, base, head, allowed):
    names = [n for n in git(repo, "diff", "--name-only", f"{base}..{head}").splitlines() if n]
    outside = [n for n in names if not any(fnmatch.fnmatch(n, g) for g in allowed)]
    if outside:
        return FAIL, "허용 밖 변경: " + ", ".join(outside)
    return PASS, f"변경 {len(names)}개 모두 허용 범위"


# ---------------------------------------------------------------- G4

def extract_function_source(source: str, name: str):
    """최상위 함수 또는 'Class.method'의 소스. 없으면 None."""
    tree = ast.parse(source)
    parts = name.split(".")
    nodes = tree.body
    node = None
    for i, part in enumerate(parts):
        node = None
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part:
                node = n
                break
        if node is None:
            return None
        if i < len(parts) - 1:
            nodes = node.body
    return ast.get_source_segment(source, node)


def check_g4(repo, base, head, frozen):
    changed = []
    for item in frozen:
        path, func = item["path"], item.get("function")
        b, h = show(repo, base, path), show(repo, head, path)
        if func:
            if b is None and h is None:
                continue
            if b is None or h is None:
                changed.append(f"{path}::{func}")
                continue
            if extract_function_source(b, func) != extract_function_source(h, func):
                changed.append(f"{path}::{func}")
        elif b != h:
            changed.append(path)
    if changed:
        return FAIL, "동결 영역 변경: " + ", ".join(changed)
    return PASS, f"동결 {len(frozen)}건 변경 없음"


# ---------------------------------------------------------------- G5

def check_g5(repo, base, head, task_id, spec):
    problems = []
    count = int(git(repo, "rev-list", "--count", f"{base}..{head}").strip())
    if count != 1:
        problems.append(f"커밋 수 {count} (1이어야 함)")
    subject = git(repo, "log", "-1", "--format=%s", head).strip()
    body = git(repo, "log", "-1", "--format=%B", head)
    if task_id not in subject:
        problems.append(f"제목에 {task_id} 없음")
    if not re.search(rf"^Spec:\s*{re.escape(spec)}(\s|$)", body, re.M):
        problems.append(f"본문에 'Spec: {spec}' 없음")
    if git(repo, "status", "--porcelain").strip():
        problems.append("작업 트리가 깨끗하지 않음")
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, "커밋 1개, ID·Spec 있음, 작업 트리 깨끗함"


# ---------------------------------------------------------------- G6

def _forbidden_path(p: str) -> bool:
    parts = p.split("/")
    return (
        ".env" in parts
        or parts[-1] == "config.yaml"
        or "data" in parts[:-1]
        or any(x.startswith("chrome-profile-") for x in parts)
    )


def check_g6(repo, base, head):
    problems = []
    names = [n for n in git(repo, "diff", "--name-only", f"{base}..{head}").splitlines() if n]
    bad_paths = [n for n in names if _forbidden_path(n)]
    if bad_paths:
        problems.append("금지 경로 변경: " + ", ".join(bad_paths))
    diff = git(repo, "diff", "-U0", "--no-color", f"{base}..{head}")
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        line = line[1:]  # diff의 '+' 접두어 제거(이메일 로컬 파트로 오인 방지)
        if "noreply" in line:
            continue
        for label, pat in SECRET_PATTERNS:
            if pat.search(line):
                problems.append(f"추가된 줄에 {label} 패턴")
                break
    if problems:
        return FAIL, "; ".join(dict.fromkeys(problems))
    return PASS, "비밀 패턴·금지 경로 없음"


# ---------------------------------------------------------------- 실행

def run_gates(args):
    repo = Path.cwd()
    contract = parse_contract(Path(args.contract).read_text(encoding="utf-8"))
    base = git(repo, "rev-parse", args.base).strip()
    head = git(repo, "rev-parse", args.head).strip()
    results = []

    def add(gid, fn):
        try:
            status, msg = fn()
        except Exception as e:  # noqa: BLE001
            status, msg = HOLD, f"실행 불가: {e}"
        results.append((gid, status, msg))

    if args.report:
        add("G0", lambda: check_g0(Path(args.report).read_text(encoding="utf-8")))
    add("G1", lambda: check_g1(repo, base, head, contract["new_tests"]))
    add("G2", lambda: check_g2(repo, base, head, contract["baseline_passed"]))
    add("G3", lambda: check_g3(repo, base, head, contract["allowed_files"]))
    add("G4", lambda: check_g4(repo, base, head, contract["frozen"]))
    add("G5", lambda: check_g5(repo, base, head, contract["task_id"], contract["spec"]))
    add("G6", lambda: check_g6(repo, base, head))
    return contract, results


def overall(results):
    statuses = [s for _, s, _ in results]
    if FAIL in statuses:
        return FAIL
    if HOLD in statuses:
        return HOLD
    return PASS


def main(argv=None):
    ap = argparse.ArgumentParser(description="라운드 작업 게이트 G0~G6 판정")
    ap.add_argument("--contract", required=True, help="작업 계약서 마크다운")
    ap.add_argument("--base", required=True, help="작업 전 커밋")
    ap.add_argument("--head", required=True, help="작업 후 커밋")
    ap.add_argument("--report", help="하위 에이전트 보고서(G0)")
    ap.add_argument("--log", help="결과를 저장할 마크다운 경로")
    args = ap.parse_args(argv)
    try:
        contract, results = run_gates(args)
    except (ValueError, RuntimeError, OSError) as e:
        print(f"RESULT HOLD ({e})")
        return 2
    lines = [f"{gid} {st} {msg}" for gid, st, msg in results]
    final = overall(results)
    lines.append(f"RESULT {final}")
    print("\n".join(lines))
    if args.log:
        md = [f"## 게이트 결과 {contract['task_id']}", "", f"- base: `{args.base}`  head: `{args.head}`", ""]
        md += [f"- {ln}" for ln in lines]
        Path(args.log).write_text("\n".join(md) + "\n", encoding="utf-8")
    return {PASS: 0, FAIL: 1, HOLD: 2}[final]


if __name__ == "__main__":
    sys.exit(main())
