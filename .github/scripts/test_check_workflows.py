"""Self-test for check_workflows.py (T-08-15): every rule must fire on a
workflow that breaks it, and pass on the repo's real workflows."""
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CHECK = HERE / "check_workflows.py"
REPO_WORKFLOWS = HERE.parent / "workflows"

GOOD_AUDIT = """name: Dependency audit
on:
  schedule:
    - cron: "17 6 * * 1"
  workflow_dispatch:
permissions:
  contents: read
jobs:
  npm:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0
      - run: npm audit --audit-level=high
  python:
    runs-on: ubuntu-latest
    steps:
      - run: pip-audit -r api/requirements.txt
"""


def run(files: dict) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as d:
        for name, text in files.items():
            (pathlib.Path(d) / name).write_text(text)
        return subprocess.run([sys.executable, str(CHECK), d], capture_output=True, text=True)


def expect_fail(files, needle):
    r = run(files)
    assert r.returncode != 0, f"expected a failure mentioning {needle!r}"
    assert needle in r.stdout + r.stderr, (needle, r.stdout, r.stderr)


def main():
    assert run({"audit.yml": GOOD_AUDIT}).returncode == 0, "a good audit workflow must pass"
    expect_fail({"audit.yml": GOOD_AUDIT.replace("@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09", "@v5")}, "not pinned")
    expect_fail({"audit.yml": GOOD_AUDIT, "x.yml": "jobs:\n  a:\n    steps:\n      - uses: org/act@main\n"}, "not pinned")
    expect_fail({"audit.yml": GOOD_AUDIT.replace('  schedule:\n    - cron: "17 6 * * 1"\n', "")}, "schedule")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("  workflow_dispatch:\n", "")}, "workflow_dispatch")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("  contents: read\n", "  contents: write\n")}, "contents: read")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("      - run: npm audit", "      - continue-on-error: true\n        run: npm audit")}, "continue-on-error")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("    runs-on: ubuntu-latest\n    steps:\n      - run: pip", "    if: github.event_name == 'schedule'\n    runs-on: ubuntu-latest\n    steps:\n      - run: pip")}, "if:")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("--audit-level=high", "--audit-level=critical")}, "npm audit --audit-level=high")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("pip-audit", "echo")}, "pip-audit")
    expect_fail({}, "audit.yml")
    # A comment mentioning a banned word is fine; the same word as YAML is not.
    assert run({"audit.yml": "# never continue-on-error\n" + GOOD_AUDIT}).returncode == 0
    real = subprocess.run([sys.executable, str(CHECK), str(REPO_WORKFLOWS)], capture_output=True, text=True)
    assert real.returncode == 0, real.stdout + real.stderr
    print("check_workflows self-test: all rules fire; the repo's workflows pass")


if __name__ == "__main__":
    main()
