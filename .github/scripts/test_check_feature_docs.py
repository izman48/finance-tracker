"""Self-test for check_feature_docs.py: every rule must fire on a repo that
breaks it, and pass on this repo's real code and docs."""
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CHECK = HERE / "check_feature_docs.py"
REPO = HERE.parent.parent

MAIN = """
from app.routers import foo_router, wk_router
app.include_router(foo_router, prefix="/api/v1")
app.include_router(wk_router)
"""
ROUTERS_INIT = """
from .foo import router as foo_router
from .foo import well_known_router as wk_router
"""
FOO = """
router = APIRouter(prefix="/foo", tags=["foo"])
well_known_router = APIRouter(tags=["oauth"])

@router.get("/bar/{bar_id}")
def bar(): ...

@router.post(
    "/baz",
    response_model=None,
)
def baz(): ...

@well_known_router.get("/.well-known/thing")
def wk(): ...
"""
MODEL = 'class Thing(Base):\n    __tablename__ = "things"\n'
SERVER = """
def create_server():
    @mcp.tool(annotations=READ_ONLY)
    async def do_thing() -> dict:
        ...
"""
APP = '<Route path="/" element={<Layout />}>\n  <Route path="home" element={<Home />} />\n'
DOC = """# Foo

`GET /api/v1/foo/bar/{bar_id}`, `POST /api/v1/foo/baz`, `GET /.well-known/thing`.
Table `things`, MCP tool `do_thing`, UI routes `/` and `/home`.

## Touchpoints

Demo mode: yes.
"""

GOOD = {
    "api/app/main.py": MAIN,
    "api/app/routers/__init__.py": ROUTERS_INIT,
    "api/app/routers/foo.py": FOO,
    "api/app/models/thing.py": MODEL,
    "api/mcp/server.py": SERVER,
    "ui/src/App.tsx": APP,
    "docs/features/README.md": "# Index\n",
    "docs/features/foo.md": DOC,
}


def run(files: dict) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as d:
        for name, text in files.items():
            path = pathlib.Path(d) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return subprocess.run([sys.executable, str(CHECK), d], capture_output=True, text=True)


def with_doc(text: str) -> dict:
    return {**GOOD, "docs/features/foo.md": text}


def expect_fail(files, needle):
    r = run(files)
    assert r.returncode != 0, f"expected a failure mentioning {needle!r}"
    assert needle in r.stdout + r.stderr, (needle, r.stdout, r.stderr)


def main():
    r = run(GOOD)
    assert r.returncode == 0, ("a fully documented repo must pass", r.stdout, r.stderr)

    # Something in the code that no feature doc mentions.
    expect_fail(with_doc(DOC.replace("`GET /api/v1/foo/bar/{bar_id}`, ", "")), "GET /api/v1/foo/bar/{bar_id}")
    expect_fail(with_doc(DOC.replace("`POST /api/v1/foo/baz`, ", "")), "POST /api/v1/foo/baz")
    expect_fail(with_doc(DOC.replace("`GET /.well-known/thing`", "")), "GET /.well-known/thing")
    expect_fail(with_doc(DOC.replace("Table `things`", "Table")), "table things")
    expect_fail(with_doc(DOC.replace("MCP tool `do_thing`", "")), "MCP tool do_thing")
    expect_fail(with_doc(DOC.replace("and `/home`", "")), "UI route /home")
    # A mention in the index doesn't count: it must be in a feature doc.
    expect_fail(
        {**with_doc(DOC.replace("MCP tool `do_thing`", "")), "docs/features/README.md": "`do_thing`\n"},
        "MCP tool do_thing",
    )

    # Docs that describe code which no longer exists.
    expect_fail(with_doc(DOC + "\nAlso `DELETE /api/v1/foo/gone`.\n"), "DELETE /api/v1/foo/gone")

    # Every feature doc answers the touchpoints checklist.
    expect_fail(with_doc(DOC.replace("## Touchpoints", "## Notes")), "Touchpoints")

    # A holding kind's DOCS declaration names a feature doc that exists.
    registry = 'Surface.DOCS: "docs/features/foo.md",\n'
    r = run({**GOOD, "api/app/services/holdings/registry.py": registry})
    assert r.returncode == 0, ("an existing holding doc must pass", r.stdout, r.stderr)
    expect_fail(
        {**GOOD, "api/app/services/holdings/registry.py": registry.replace("foo.md", "gone.md")},
        "docs/features/gone.md",
    )

    # The check above only runs if the registry is where it looks.
    assert (REPO / "api/app/services/holdings/registry.py").is_file(), "holding registry moved"

    # And this repo's own docs are complete.
    r = subprocess.run([sys.executable, str(CHECK), str(REPO)], capture_output=True, text=True)
    assert r.returncode == 0, ("the repo's feature docs are out of date", r.stdout, r.stderr)
    print("check_feature_docs self-test: ok")


if __name__ == "__main__":
    main()
