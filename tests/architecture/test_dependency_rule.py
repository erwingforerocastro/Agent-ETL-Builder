from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src"

OUTWARD_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset({"application", "infrastructure", "interfaces"}),
    "application": frozenset({"infrastructure", "interfaces"}),
    "infrastructure": frozenset({"interfaces"}),
    "interfaces": frozenset({"infrastructure"}),
}

FRAMEWORK_MODULES = frozenset(
    {
        "fastapi",
        "langgraph",
        "pandas",
        "pydantic",
        "postgresql",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "starlette",
        "uvicorn",
    }
)


def _layer_for(path: Path) -> str | None:
    relative = path.relative_to(PACKAGE_ROOT)
    if len(relative.parts) < 2:
        return None
    layer = relative.parts[0]
    return layer if layer in OUTWARD_IMPORTS else None


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def _matches(imported: str, target: str) -> bool:
    return imported == target or imported.startswith(f"{target}.")


def test_inner_layers_do_not_import_outer_layers() -> None:
    violations: list[str] = []

    for path in PACKAGE_ROOT.rglob("*.py"):
        layer = _layer_for(path)
        if layer is None:
            continue
        for imported in _imported_modules(path):
            if any(_matches(imported, target) for target in OUTWARD_IMPORTS[layer]):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)} imports {imported}")

    assert not violations, "Dependency Rule violations:\n" + "\n".join(sorted(violations))


def test_core_layers_do_not_import_frameworks() -> None:
    violations: list[str] = []

    for path in PACKAGE_ROOT.rglob("*.py"):
        layer = _layer_for(path)
        if layer not in {"domain", "application"}:
            continue
        for imported in _imported_modules(path):
            if imported.split(".", maxsplit=1)[0] in FRAMEWORK_MODULES:
                violations.append(f"{path.relative_to(PACKAGE_ROOT)} imports {imported}")

    assert not violations, "Framework imports in core layers:\n" + "\n".join(sorted(violations))


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _internal_imports(path: Path, modules: set[str]) -> set[str]:
    return {imported for imported in _imported_modules(path) if imported in modules}


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visited: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in on_stack:
            start = stack.index(node)
            return [*stack[start:], node]
        if node in visited:
            return None

        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for dependency in sorted(graph[node]):
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        stack.pop()
        on_stack.remove(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return None


def test_internal_import_graph_is_acyclic() -> None:
    paths = {_module_name(path): path for path in PACKAGE_ROOT.rglob("*.py")}
    graph = {module: _internal_imports(path, set(paths)) for module, path in paths.items()}

    cycle = _find_cycle(graph)

    assert cycle is None, "Import cycle: " + " -> ".join(cycle or [])
