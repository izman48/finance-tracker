"""The documented exceptions to the weekly dependency audit (T-08-15).

.github/audit-ignore.txt holds one advisory per line:

    <ID> review-by:<YYYY-MM-DD> <why it is safe to ignore, and who decided>

IDs are GHSA-… (npm and PyPI) or PYSEC-…/CVE-…. A line without a reason or
with a past review-by date fails the audit, so no exception outlives its
review. `--pip-args` prints the ids as pip-audit `--ignore-vuln` arguments.
"""
import pathlib
import re
import sys
from datetime import date

LINE = re.compile(r"^(?P<id>\S+)\s+review-by:(?P<when>\S+)(?:\s+(?P<why>.+))?$")
ID = re.compile(r"^(GHSA(-[a-z0-9]{4}){3}|PYSEC-\d{4}-\d+|CVE-\d{4}-\d+)$")


class IgnoreFileError(ValueError):
    pass


def load_ignores(path: pathlib.Path, today: date) -> set[str]:
    ids = set()
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            raise IgnoreFileError(f"{path.name}:{n}: expected '<ID> review-by:<YYYY-MM-DD> <reason>'")
        if not ID.match(m["id"]):
            raise IgnoreFileError(f"{path.name}:{n}: not an advisory id: {m['id']}")
        try:
            when = date.fromisoformat(m["when"])
        except ValueError:
            raise IgnoreFileError(f"{path.name}:{n}: review-by must be YYYY-MM-DD") from None
        if when < today:
            raise IgnoreFileError(f"{path.name}:{n}: {m['id']} expired on {when}: review it again")
        if not m["why"]:
            raise IgnoreFileError(f"{path.name}:{n}: {m['id']} needs a reason")
        ids.add(m["id"])
    return ids


def main() -> int:
    path = pathlib.Path(sys.argv[-1])
    try:
        ids = load_ignores(path, date.today())
    except IgnoreFileError as e:
        print(e, file=sys.stderr)
        return 1
    if "--pip-args" in sys.argv:
        print(" ".join(f"--ignore-vuln {i}" for i in sorted(ids)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
