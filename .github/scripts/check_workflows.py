"""Guard the CI wiring (T-08-15). Usage: check_workflows.py <workflows dir>.

- Every third-party action is pinned to a full commit SHA, so a moved tag
  can't change what runs with our secrets.
- audit.yml is the weekly dependency audit and must fail loudly: it runs on
  a schedule and by hand, with a read-only token, never skips (`if:`) or
  shrugs off a failure (`continue-on-error`), runs npm audit (dev included)
  through npm_audit_gate.py and pip-audit, and both read the documented
  ignores in .github/audit-ignore.txt.
- test.yml gates every deploy (T-08-26): it can be called (workflow_call);
  a PR may skip jobs whose files didn't change, but off a PR everything
  runs (the path filter only runs on pull_request and each output defaults
  to true); and a `required` job with `if: always()` needs every other job.
Line-based on purpose (no YAML library to install); tested by
test_check_workflows.py, which plants each mistake and expects it caught.
"""
import pathlib
import re
import sys

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def check(directory: pathlib.Path) -> list[str]:
    problems = []
    files = sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml"))
    for path in files:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            m = USES.match(line)
            if m and not m.group(1).startswith("./") and not PINNED.match(m.group(1)):
                problems.append(f"{path.name}:{n}: action not pinned to a commit SHA: {m.group(1)}")

    audit = directory / "audit.yml"
    if not audit.exists():
        return problems + ["audit.yml is missing (the weekly dependency audit)"]
    # Comments don't run: judge only the YAML itself.
    lines = [re.sub(r"\s+#.*$|^\s*#.*$", "", line) for line in audit.read_text().splitlines()]
    text = "\n".join(lines)
    if not re.search(r"^\s*schedule:\s*$", text, re.M) or "cron:" not in text:
        problems.append("audit.yml: no schedule (cron) trigger")
    if not re.search(r"^\s*workflow_dispatch:", text, re.M):
        problems.append("audit.yml: no workflow_dispatch trigger")
    if not re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", text, re.M):
        problems.append("audit.yml: top-level permissions must be exactly `contents: read`")
    if re.search(r"^\s+\w+:\s*write\b", text, re.M):
        problems.append("audit.yml: grants a write permission")
    for n, line in enumerate(lines, 1):
        if "continue-on-error" in line:
            problems.append(f"audit.yml:{n}: continue-on-error would hide a failing audit")
        if re.match(r"^\s*(?:-\s*)?if:", line):
            problems.append(f"audit.yml:{n}: if: could silently skip the audit")
    if "npm audit --json" not in text or "npm_audit_gate.py" not in text:
        problems.append("audit.yml: must run npm audit --json through npm_audit_gate.py (fails on high/critical)")
    if re.search(r"npm audit[^\n]*(--omit|--production|--only)", text):
        problems.append("audit.yml: npm audit must include dev dependencies")
    if text.count("audit-ignore.txt") < 2:
        problems.append("audit.yml: both audits must read .github/audit-ignore.txt")
    if "pip-audit" not in text:
        problems.append("audit.yml: must run pip-audit")
    return problems


def check_test_workflow(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    lines = [re.sub(r"\s+#.*$|^\s*#.*$", "", line) for line in path.read_text().splitlines()]
    text = "\n".join(lines)
    problems = []
    if not re.search(r"^\s*workflow_call:", text, re.M):
        problems.append("test.yml: no workflow_call trigger (deploy.yml runs it)")
    for n, line in enumerate(lines):
        if "dorny/paths-filter@" in line:
            step = _step(lines, n)
            if not any(re.match(r"^\s*if:\s*github\.event_name == 'pull_request'\s*$", s) for s in step):
                problems.append(f"test.yml:{n + 1}: the path filter must run only on pull_request")
        if "steps.filter.outputs." in line and "github.event_name != 'pull_request' ||" not in line:
            problems.append(f"test.yml:{n + 1}: a filter output must be true off a PR")
    jobs = re.findall(r"^  ([\w-]+):\s*$", text.split("\njobs:", 1)[-1], re.M)
    if "required" not in jobs:
        return problems + ["test.yml: no `required` job summarising every job"]
    block = _job(lines, "required")
    if not any(re.match(r"^\s*if:\s*always\(\)\s*$", s) for s in block):
        problems.append("test.yml: the required job must run with if: always()")
    needs = re.search(r"needs:\s*\[([^\]]*)\]", "\n".join(block))
    listed = {n.strip() for n in needs.group(1).split(",")} if needs else set()
    for job in sorted(set(jobs) - {"required"} - listed):
        problems.append(f"test.yml: the required job doesn't need `{job}`")
    return problems


def _step(lines: list[str], n: int) -> list[str]:
    """The lines of the step containing line n (from its `- ` to the next)."""
    start = n
    while start > 0 and not re.match(r"^\s*-\s", lines[start]):
        start -= 1
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines) and not (
        lines[end].strip() and len(lines[end]) - len(lines[end].lstrip()) <= indent
    ):
        end += 1
    return [lines[start].replace("-", " ", 1)] + lines[start + 1:end]


def _job(lines: list[str], name: str) -> list[str]:
    start = next(i for i, line in enumerate(lines) if re.match(rf"^  {re.escape(name)}:\s*$", line))
    end = start + 1
    while end < len(lines) and not re.match(r"^  \S", lines[end]):
        end += 1
    return lines[start + 1:end]


def main() -> int:
    directory = pathlib.Path(sys.argv[1])
    problems = check(directory) + check_test_workflow(directory / "test.yml")
    for p in problems:
        print(p)
    if problems:
        return 1
    print("workflows OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
