"""SDD consistency check (workflow.md stage 3, V1).

Run from the project root:  python .ucompany/scripts/check_sdd.py

Checks that
* every relative markdown link in the repository resolves,
* every graph.json node path exists and every edge points at known node IDs,
* every graph node ID appears in 00_index.md (the index is the source of truth),
* no current document still points at a file under the retired docs/track2-agent path.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDD = ROOT / ".ucompany" / "sdd"
SKIP = {".git", "data", ".venv", "venv", ".pytest_cache", "__pycache__", "node_modules"}
LINK = re.compile(r"\]\(([^)\s]+)\)")


def markdown_files():
    for path in ROOT.rglob("*.md"):
        if not SKIP.intersection(path.relative_to(ROOT).parts):
            yield path


def main() -> int:
    errors: list[str] = []
    for path in markdown_files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            if re.match(r"^(https?:|mailto:|#)", target):
                continue
            if not (path.parent / target.split("#", 1)[0]).exists():
                errors.append(f"{rel}: broken link -> {target}")
        if re.search(r"docs/track2-agent/[\w\-]+\.md", text) and not any(
                part in rel for part in ("improvements/", "decisions/", "history.md", "handoff.md")):
            errors.append(f"{rel}: points at a file under the retired docs/track2-agent path")
    graph = json.loads((SDD / "graph.json").read_text(encoding="utf-8"))
    index = (SDD / "00_index.md").read_text(encoding="utf-8")
    ids = set()
    for node in graph["nodes"]:
        ids.add(node["id"])
        if not (ROOT / node["path"]).exists():
            errors.append(f"graph.json: {node['id']} path missing -> {node['path']}")
        if node["id"] not in index:
            errors.append(f"00_index.md: node {node['id']} not listed")
    for edge in graph["edges"]:
        if edge["from"] not in ids or edge["to"] not in ids:
            errors.append(f"graph.json: dangling edge {edge}")
    if graph.get("focus") not in ids:
        errors.append("graph.json: focus is not a node")
    for line in errors:
        print("ERROR", line)
    print(f"check_sdd: {len(errors)} error(s), {len(ids)} nodes")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
