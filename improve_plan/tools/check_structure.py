"""improve_plan 폴더가 00_document_rules.md의 규칙을 지키는지 검사한다.

규칙
1. 모든 .md 파일은 150줄 이하
2. 모든 하위 폴더에 index.md 존재 (최상위는 README.md, tools/ 제외)
3. 인덱스는 같은 폴더의 모든 파일과 하위 폴더를 링크
   (하위 폴더는 "<폴더>/index.md"로 링크)
4. 인덱스의 상대 링크가 실제로 존재

사용: python3 improve_plan/tools/check_structure.py   (위반 시 종료 코드 1)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_LINES = 150
ROOT = Path(__file__).resolve().parents[1]
EXEMPT_DIRS = {"tools"}
LOG_DIR = "logs"  # logs/ 아래 하위 폴더는 인덱스 규칙 제외 (150줄 규칙은 적용)
LINK = re.compile(r"\]\(([^)#\s]+)")


def index_of(folder: Path) -> Path:
    return folder / ("README.md" if folder == ROOT else "index.md")


def check() -> list[str]:
    problems: list[str] = []
    for md in sorted(ROOT.rglob("*.md")):
        lines = len(md.read_text(encoding="utf-8").splitlines())
        if lines > MAX_LINES:
            problems.append(f"{md.relative_to(ROOT)}: {lines}줄 > {MAX_LINES}줄 — 폴더로 분할 필요")
    folders = [ROOT] + sorted(p for p in ROOT.rglob("*") if p.is_dir()
                              and not set(p.relative_to(ROOT).parts) & EXEMPT_DIRS
                              and not (p.relative_to(ROOT).parts[0] == LOG_DIR
                                       and len(p.relative_to(ROOT).parts) > 1))
    for folder in folders:
        index = index_of(folder)
        rel = folder.relative_to(ROOT) if folder != ROOT else Path(".")
        if not index.is_file():
            problems.append(f"{rel}: {index.name} 없음")
            continue
        text = index.read_text(encoding="utf-8")
        links = set(LINK.findall(text))
        for target in links:
            if "://" in target:
                continue
            if not (folder / target).exists():
                problems.append(f"{index.relative_to(ROOT)}: 깨진 링크 {target}")
        if folder == ROOT / LOG_DIR:
            continue  # 기록 보관 폴더: 하위 항목을 개별 링크하지 않음
        for child in sorted(folder.iterdir()):
            if child == index or child.name.startswith("."):
                continue
            if child.is_dir():
                if child.name in EXEMPT_DIRS and folder == ROOT:
                    wanted = {f"{child.name}/", *(f"{child.name}/{p.name}" for p in child.iterdir())}
                    if not wanted & links:
                        problems.append(f"{index.relative_to(ROOT)}: {child.name}/ 링크 없음")
                    continue
                if f"{child.name}/index.md" not in links:
                    problems.append(f"{index.relative_to(ROOT)}: 하위 폴더 {child.name}/index.md 링크 없음")
            elif child.suffix == ".md" and child.name not in links:
                problems.append(f"{index.relative_to(ROOT)}: {child.name} 링크 없음")
    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        print("위반:", problem)
    count = sum(1 for _ in ROOT.rglob("*.md"))
    print(f"검사한 문서 {count}개, 위반 {len(problems)}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
