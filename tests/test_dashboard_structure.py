"""dashboard.py 분리 후 구조를 고정한다 (IMP-41)."""
from __future__ import annotations

import ast
from pathlib import Path

from test_legacy_boundary import collect_imports

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "marketing_agent"
DASHBOARD = PACKAGE / "dashboard.py"
ALLOWED_COMPARE_OWNERS = {"_session_ok", "_pair_match"}


def test_dashboard_module_size_limit() -> None:
    assert len(DASHBOARD.read_text(encoding="utf-8").splitlines()) <= 800


def test_session_token_compare_only_in_helpers() -> None:
    tree = ast.parse(DASHBOARD.read_text(encoding="utf-8"))
    owners: set[str] = set()

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, stack + [child.name])
                continue
            if isinstance(child, ast.Call):
                fn = child.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name == "compare_digest":
                    owners.add(stack[-1] if stack else "<module>")
            walk(child, stack)

    walk(tree, [])
    assert owners and owners <= ALLOWED_COMPARE_OWNERS, owners


def test_boundary_collector_follows_absolute_imports() -> None:
    assert collect_imports("import marketing_agent.chrome_launch") == {"chrome_launch"}
    assert collect_imports("from marketing_agent import dashboard_service") == {"dashboard_service"}
    assert collect_imports("from marketing_agent.dashboard import create_server") == {"dashboard"}


def test_public_names_still_importable() -> None:
    from marketing_agent.dashboard import (  # noqa: F401
        ConfiguredPostingService, DemoService, check_channel_connection,
        create_server, run_dashboard, watch_url,
    )


def test_split_modules_do_not_import_dashboard() -> None:
    assert "dashboard" not in collect_imports((PACKAGE / "dashboard_service.py").read_text(encoding="utf-8"))
    assert "dashboard" not in collect_imports((PACKAGE / "chrome_launch.py").read_text(encoding="utf-8"))
