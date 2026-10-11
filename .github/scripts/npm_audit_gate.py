"""Fail on any high or critical npm advisory not in the ignore list (T-08-15).

npm audit has no ignore option, so the audit job saves `npm audit --json`
and this decides: usage npm_audit_gate.py <audit.json> <audit-ignore.txt>.
Only the advisories themselves count (the `via` entries that are objects),
not the packages that depend on them. An npm error is a failure, never a pass.
"""
import json
import pathlib
import sys
from datetime import date

from audit_ignores import IgnoreFileError, load_ignores

BLOCKING = {"high", "critical"}


def blocking_advisories(report: dict, ignored: set[str]) -> list[str]:
    if "error" in report:
        raise RuntimeError(f"npm audit failed: {report['error'].get('summary', report['error'])}")
    found = set()
    for vuln in report.get("vulnerabilities", {}).values():
        for via in vuln.get("via", []):
            if isinstance(via, dict) and via.get("severity") in BLOCKING:
                advisory = via.get("url", "").rstrip("/").rsplit("/", 1)[-1] or str(via.get("source"))
                if advisory not in ignored:
                    found.add(advisory)
    return sorted(found)


def main() -> int:
    report_path, ignore_path = map(pathlib.Path, sys.argv[1:3])
    try:
        ignored = load_ignores(ignore_path, date.today())
        blocking = blocking_advisories(json.loads(report_path.read_text()), ignored)
    except (IgnoreFileError, RuntimeError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    for advisory in blocking:
        print(f"high/critical advisory, not ignored: https://github.com/advisories/{advisory}")
    if blocking:
        return 1
    print(f"npm audit: no unignored high or critical advisories ({len(ignored)} documented ignores)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
