"""SDD consistency check (workflow.md stage 3, V1).

Run from the project root:  python .ucompany/scripts/check_sdd.py

Checks that
* every relative markdown link in the repository resolves,
* every graph.json node path exists and every edge points at known node IDs,
* every graph node ID appears in 00_index.md (the index is the source of truth),
* no current document still points at a file under the retired docs/track2-agent path,
* every module the dashboard imports (and the CLI entry) is a graph node or is named in
  contracts/legacy-scope.md, so no product code is invisible to the SDD (IMP-25),
* the index names the prompt version that prompt_policy.py actually sends,
* every file path AGENTS.md mentions in backticks exists.
"""
from __future__ import annotations

import ast
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


def dashboard_modules() -> set[str]:
    """Package modules reachable from dashboard.py through relative imports, plus __main__."""
    package = ROOT / "src" / "marketing_agent"
    seen: set[str] = set()
    stack = ["dashboard"]
    while stack:
        name = stack.pop()
        path = package / f"{name}.py"
        if name in seen or not path.exists():
            continue
        seen.add(name)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                stack.extend([node.module.split(".")[0]] if node.module else [a.name for a in node.names])
    return seen | {"__main__"}


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
    node_paths = {node["path"] for node in graph["nodes"]}
    legacy = (SDD / "contracts" / "legacy-scope.md").read_text(encoding="utf-8")
    for module in sorted(dashboard_modules()):
        path = f"src/marketing_agent/{module}.py"
        if path not in node_paths and f"`{module}.py`" not in legacy:
            errors.append(f"graph.json: product module {path} has no node and no legacy-scope entry")
    prompt = (ROOT / "src" / "marketing_agent" / "prompt_policy.py").read_text(encoding="utf-8")
    version = re.search(r'PROMPT_VERSION\s*=\s*"([^"]+)"', prompt)
    if version and version.group(1) not in index:
        errors.append(f"00_index.md: current prompt version {version.group(1)} not named")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for mention in re.findall(r"`([\w./-]+\.(?:md|py|json|sh|bat|command))`", agents):
        if "/" in mention:
            found = (ROOT / mention).exists() or (SDD / mention).exists()
        else:  # a bare file name: look it up under the repo and the SDD/scripts folders
            found = (ROOT / mention).exists() or any(
                path.name == mention for base in (SDD, ROOT / ".ucompany" / "scripts", ROOT / "src")
                for path in base.rglob(mention))
        if not found:
            errors.append(f"AGENTS.md: mentions missing file {mention}")
    for line in errors:
        print("ERROR", line)
    print(f"check_sdd: {len(errors)} error(s), {len(ids)} nodes")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
