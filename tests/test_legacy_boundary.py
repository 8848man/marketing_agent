"""제품(대시보드)·레거시 CLI 모듈 사이의 import 경계를 고정한다 (IMP-39)."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "marketing_agent"
SCOPE_DOC = ROOT / ".ucompany" / "sdd" / "contracts" / "legacy-scope.md"

# .ucompany/sdd/contracts/legacy-scope.md 표의 레거시 모듈
LEGACY_MODULES = {"pipeline", "watcher", "search_budget", "trigger", "classifier", "writer", "config"}
# 제품 게시 경로
POSTING_MODULES = {"poster", "posting_service"}


def collect_imports(source: str) -> set[str]:
    """소스가 직접 가져오는 패키지 내부 모듈 이름: 상대 import(모든 level)와 marketing_agent 절대 import."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.level >= 1:
                if node.module:
                    found.add(node.module.split(".")[0])
                else:
                    found.update(alias.name for alias in node.names)
            elif node.module == "marketing_agent":
                found.update(alias.name for alias in node.names)
            elif node.module and node.module.startswith("marketing_agent."):
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "marketing_agent" and len(parts) > 1:
                    found.add(parts[1])
    return found


def relative_imports(name: str) -> set[str]:
    """한 모듈이 직접 가져오는 패키지 내부 모듈 이름 (상대·절대 import)."""
    return collect_imports((PACKAGE / f"{name}.py").read_text(encoding="utf-8"))


def dashboard_modules() -> set[str]:
    """dashboard.py에서 import로 도달 가능한 모듈. __main__.py는 두 진입점을 모두 가져 제외한다."""
    seen: set[str] = set()
    stack = ["dashboard"]
    while stack:
        name = stack.pop()
        if name in seen or not (PACKAGE / f"{name}.py").exists():
            continue
        seen.add(name)
        stack.extend(relative_imports(name))
    return seen


def test_dashboard_does_not_import_legacy() -> None:
    reachable = dashboard_modules()
    assert "dashboard" in reachable and "posting_service" in reachable
    assert reachable & LEGACY_MODULES == set()


def test_legacy_never_imports_posting_path() -> None:
    for name in sorted(LEGACY_MODULES):
        assert (PACKAGE / f"{name}.py").exists(), name
        assert relative_imports(name) & POSTING_MODULES == set(), name


def test_legacy_scope_doc_mentions_boundary_test() -> None:
    assert "test_legacy_boundary.py" in SCOPE_DOC.read_text(encoding="utf-8")


def test_boundary_collector_follows_absolute_imports() -> None:
    assert collect_imports("import marketing_agent.pipeline") == {"pipeline"}
    assert collect_imports("from marketing_agent import watcher, trigger") == {"watcher", "trigger"}
    assert collect_imports("from marketing_agent.classifier import Foo") == {"classifier"}
    assert collect_imports("from .writer import x\nfrom . import config") == {"writer", "config"}
