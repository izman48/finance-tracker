"""Guard the CI wiring (T-08-15). Usage: check_workflows.py <workflows dir>.

- Every third-party action is pinned to a full commit SHA, so a moved tag
  can't change what runs with our secrets.
- audit.yml is the weekly dependency audit and must fail loudly: it runs on
  a schedule and by hand, with a read-only token, never skips (`if:`) or
  shrugs off a failure (`continue-on-error`), and runs both `npm audit
  --audit-level=high` and `pip-audit`.
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
    if "npm audit --audit-level=high" not in text:
        problems.append("audit.yml: must run npm audit --audit-level=high")
    if "pip-audit" not in text:
        problems.append("audit.yml: must run pip-audit")
    return problems


def main() -> int:
    problems = check(pathlib.Path(sys.argv[1]))
    for p in problems:
        print(p)
    if problems:
        return 1
    print("workflows OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
