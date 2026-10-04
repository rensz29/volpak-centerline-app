"""Read-only to the plant (invariant 1, ADR-0006 M7): the Timebase client sends nothing but GET."""

from __future__ import annotations

import ast
from pathlib import Path

from centerline_common import historian


def methods(path: Path) -> list[str]:
    """The method of every HTTP request a module makes, or its expression when it isn't a constant."""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("request", "putrequest"):
            arg = node.args[0] if node.args else None
            out.append(arg.value if isinstance(arg, ast.Constant) else ast.unparse(arg) if arg is not None else "?")
    return out


def test_the_timebase_client_only_ever_sends_get():
    assert set(methods(Path(historian.__file__))) == {"GET"}  # no POST, PUT or DELETE can reach the historian
