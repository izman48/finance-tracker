"""Keep docs/features/ in step with the code. Usage: check_feature_docs.py <repo root>.

Fails when:
- an API route, database table, MCP tool or UI route exists in the code but
  no feature doc (docs/features/*.md, not README.md) mentions it, written in
  backticks as `METHOD /api/v1/path`, `table_name`, `tool_name`, `/ui/path`;
- a feature doc names an API route (`METHOD /path`) that no longer exists;
- a feature doc has no "## Touchpoints" section (the cross-cutting checklist
  in docs/features/README.md, answered for that feature).

Static (ast + regex, no app imports), so it runs with a bare python3 in CI.
Tested by test_check_feature_docs.py, which plants each mistake.
"""
import ast
import pathlib
import re
import sys

METHODS = ("get", "post", "put", "patch", "delete")
DOC_ROUTE = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`\s]*)`")
UI_ROUTE = re.compile(r'<Route\s+path="([^"]*)"')


def _str_kwarg(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def api_routes(root: pathlib.Path) -> set[str]:
    """`METHOD /full/path` for every route the app mounts."""
    app = root / "api/app"
    # routers/__init__.py: exported name -> (module, router variable)
    exported = {}
    for node in ast.walk(ast.parse((app / "routers/__init__.py").read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                exported[alias.asname or alias.name] = (node.module.split(".")[-1], alias.name)
    # main.py: which exported routers are mounted, under what prefix
    mounts = []
    for node in ast.walk(ast.parse((app / "main.py").read_text())):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router" and isinstance(node.args[0], ast.Name)):
            module, var = exported[node.args[0].id]
            mounts.append((module, var, _str_kwarg(node, "prefix") or ""))

    routes = set()
    for module, var, mount in mounts:
        tree = ast.parse((app / "routers" / f"{module}.py").read_text())
        prefix = ""
        for node in tree.body:
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and any(isinstance(t, ast.Name) and t.id == var for t in node.targets)):
                prefix = _str_kwarg(node.value, "prefix") or ""
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in METHODS and isinstance(dec.func.value, ast.Name)
                        and dec.func.value.id == var and dec.args
                        and isinstance(dec.args[0], ast.Constant)):
                    routes.add(f"{dec.func.attr.upper()} {mount}{prefix}{dec.args[0].value}")
    return routes


def tables(root: pathlib.Path) -> set[str]:
    found = set()
    for path in (root / "api/app/models").glob("*.py"):
        found.update(re.findall(r'__tablename__\s*=\s*"([^"]+)"', path.read_text()))
    return found


def mcp_tools(root: pathlib.Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse((root / "api/mcp/server.py").read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr == "tool":
                    found.add(node.name)
    return found


def ui_routes(root: pathlib.Path) -> set[str]:
    paths = UI_ROUTE.findall((root / "ui/src/App.tsx").read_text())
    return {p if p.startswith("/") else f"/{p}" for p in paths}


def check(root: pathlib.Path) -> list[str]:
    docs = sorted(p for p in (root / "docs/features").glob("*.md") if p.name != "README.md")
    if not docs:
        return ["docs/features/ has no feature docs"]
    text = "\n".join(p.read_text() for p in docs)
    problems = []

    for doc in docs:
        if not re.search(r"^## Touchpoints\s*$", doc.read_text(), re.M):
            problems.append(f"{doc.relative_to(root)}: no '## Touchpoints' section")

    routes = api_routes(root)
    for route in sorted(routes):
        if f"`{route}`" not in text:
            problems.append(f"API route {route} is not in any docs/features/*.md")
    for method, path in sorted(set(DOC_ROUTE.findall(text))):
        if f"{method} {path}" not in routes:
            problems.append(f"docs mention `{method} {path}` but there is no such route")

    for table in sorted(tables(root)):
        if f"`{table}`" not in text:
            problems.append(f"table {table} is not in any docs/features/*.md")
    for tool in sorted(mcp_tools(root)):
        if f"`{tool}`" not in text:
            problems.append(f"MCP tool {tool} is not in any docs/features/*.md")
    for path in sorted(ui_routes(root)):
        if f"`{path}`" not in text:
            problems.append(f"UI route {path} is not in any docs/features/*.md")
    for doc in sorted(holding_docs(root)):
        if not (root / doc).is_file():
            problems.append(f"holding registry names {doc}, which does not exist")
    return problems


def holding_docs(root: pathlib.Path) -> set[str]:
    """Feature docs the holding kind registry declares (ADR-002): the API
    tests run without the docs folder, so their existence is checked here."""
    registry = root / "api/app/services/holdings/registry.py"
    if not registry.is_file():
        return set()
    return set(re.findall(r"docs/features/[a-z0-9-]+\.md", registry.read_text()))


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    problems = check(root)
    for p in problems:
        print(p)
    if problems:
        print(f"\n{len(problems)} problem(s). Update docs/features/ (see docs/features/README.md).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
