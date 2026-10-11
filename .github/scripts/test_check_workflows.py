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
      - run: |
          npm audit --json > /tmp/a.json || true
          python3 ../.github/scripts/npm_audit_gate.py /tmp/a.json ../.github/audit-ignore.txt
  python:
    runs-on: ubuntu-latest
    steps:
      - run: |
          ignore=$(python3 .github/scripts/audit_ignores.py --pip-args .github/audit-ignore.txt)
          pip-audit $ignore -r api/requirements.txt
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
    expect_fail({"audit.yml": GOOD_AUDIT.replace("      - run: |\n          npm audit", "      - continue-on-error: true\n        run: |\n          npm audit")}, "continue-on-error")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("  python:\n    runs-on", "  python:\n    if: github.event_name == 'schedule'\n    runs-on")}, "if:")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("npm_audit_gate.py", "true.py")}, "npm_audit_gate.py")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("npm audit --json", "npm audit --omit=dev --json")}, "dev dependencies")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("--pip-args .github/audit-ignore.txt", "--pip-args x")}, "audit-ignore.txt")
    expect_fail({"audit.yml": GOOD_AUDIT.replace("pip-audit", "echo")}, "pip-audit")
    expect_fail({}, "audit.yml")
    # A comment mentioning a banned word is fine; the same word as YAML is not.
    assert run({"audit.yml": "# never continue-on-error\n" + GOOD_AUDIT}).returncode == 0
    # test.yml (T-08-26): a PR may skip jobs, a deploy never does.
    good_test = (REPO_WORKFLOWS / "test.yml").read_text()
    both = lambda t: {"audit.yml": GOOD_AUDIT, "test.yml": t}  # noqa: E731
    assert run(both(good_test)).returncode == 0, "the repo's test.yml must pass"
    expect_fail(both(good_test.replace("  workflow_call:\n", "")), "workflow_call")
    expect_fail(both(good_test.replace(
        "        id: filter\n        if: github.event_name == 'pull_request'\n", "        id: filter\n")),
        "only on pull_request")
    expect_fail(both(good_test.replace(
        "api: ${{ github.event_name != 'pull_request' || steps.filter.outputs.api == 'true' }}",
        "api: ${{ steps.filter.outputs.api == 'true' }}")), "true off a PR")
    expect_fail(both(good_test.replace("  required:\n    if: always()\n", "  required:\n")), "always()")
    expect_fail(both(good_test.replace(", ui-image, workflows]", ", workflows]")), "`ui-image`")
    expect_fail(both(good_test.replace("  required:", "  summary:")), "no `required` job")
    real = subprocess.run([sys.executable, str(CHECK), str(REPO_WORKFLOWS)], capture_output=True, text=True)
    assert real.returncode == 0, real.stdout + real.stderr
    print("check_workflows self-test: all rules fire; the repo's workflows pass")


if __name__ == "__main__":
    main()
