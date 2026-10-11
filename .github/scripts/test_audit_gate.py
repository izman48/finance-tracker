"""Tests for the audit ignore list and the npm audit gate (T-08-15).

Run: python3 .github/scripts/test_audit_gate.py
"""
import json
import pathlib
import subprocess
import sys
import tempfile
from datetime import date

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from audit_ignores import IgnoreFileError, load_ignores  # noqa: E402
from npm_audit_gate import blocking_advisories  # noqa: E402

TODAY = date(2026, 10, 11)


def write(text: str) -> pathlib.Path:
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write(text)
    f.close()
    return pathlib.Path(f.name)


def raises(text: str, needle: str):
    try:
        load_ignores(write(text), TODAY)
    except IgnoreFileError as e:
        assert needle in str(e), (needle, str(e))
        return
    raise AssertionError(f"expected IgnoreFileError mentioning {needle!r}")


def advisory(ghsa: str, severity: str) -> dict:
    return {"source": 1, "name": "pkg", "title": "t", "severity": severity,
            "url": f"https://github.com/advisories/{ghsa}"}


def report(*advisories, error=None) -> dict:
    if error:
        return {"error": {"code": "ENOAUDIT", "summary": error}}
    vulns = {f"p{i}": {"name": f"p{i}", "severity": a["severity"], "via": [a, "other-pkg"]}
             for i, a in enumerate(advisories)}
    return {"auditReportVersion": 2, "vulnerabilities": vulns,
            "metadata": {"vulnerabilities": {"high": len(advisories)}}}


def test_ignore_file():
    ok = load_ignores(write(
        "# comment\n\n"
        "GHSA-aaaa-bbbb-cccc review-by:2026-12-31 dev-only build tool, not reachable (sec 2026-10-11)\n"
        "PYSEC-2026-3483 review-by:2026-11-30 fixed by T-08-19\n"
    ), TODAY)
    assert ok == {"GHSA-aaaa-bbbb-cccc", "PYSEC-2026-3483"}
    raises("GHSA-aaaa-bbbb-cccc review-by:2026-12-31\n", "reason")
    raises("GHSA-aaaa-bbbb-cccc dev only\n", "review-by")
    raises("GHSA-aaaa-bbbb-cccc review-by:2026-10-10 expired one\n", "expired")
    raises("not-an-id review-by:2026-12-31 reason\n", "id")
    raises("GHSA-aaaa-bbbb-cccc review-by:31/12/2026 reason\n", "review-by")


def test_npm_gate():
    high, crit, mod = advisory("GHSA-hhhh-hhhh-hhhh", "high"), advisory("GHSA-cccc-cccc-cccc", "critical"), advisory("GHSA-mmmm-mmmm-mmmm", "moderate")
    assert blocking_advisories(report(high, crit, mod), set()) == ["GHSA-cccc-cccc-cccc", "GHSA-hhhh-hhhh-hhhh"]
    assert blocking_advisories(report(high, crit), {"GHSA-hhhh-hhhh-hhhh"}) == ["GHSA-cccc-cccc-cccc"]
    assert blocking_advisories(report(mod), set()) == []
    assert blocking_advisories(report(), set()) == []
    try:
        blocking_advisories(report(error="network down"), set())
    except RuntimeError as e:
        assert "network down" in str(e)
    else:
        raise AssertionError("an npm audit error must fail the gate, never pass it")


def test_a_report_without_its_sections_fails():
    """sec on #115: `{}` passed the gate. An unexpected shape must fail it,
    never turn the weekly audit silently green."""
    full = report()
    cases = [{}, {k: v for k, v in full.items() if k != "auditReportVersion"},
             {k: v for k, v in full.items() if k != "vulnerabilities"},
             {k: v for k, v in full.items() if k != "metadata"},
             {**full, "metadata": {}},
             {**full, "auditReportVersion": 1}]
    for bad in cases:
        try:
            blocking_advisories(bad, set())
        except RuntimeError:
            continue
        raise AssertionError(f"accepted a malformed report: {bad}")


def test_gate_cli_exit_codes():
    gate = HERE / "npm_audit_gate.py"
    ignores = write("GHSA-hhhh-hhhh-hhhh review-by:2027-01-31 test reason\n")
    for rep, code in [(report(advisory("GHSA-hhhh-hhhh-hhhh", "high")), 0),
                      (report(advisory("GHSA-zzzz-zzzz-zzzz", "high")), 1),
                      (report(error="boom"), 1),
                      ({}, 1)]:
        f = write(json.dumps(rep))
        r = subprocess.run([sys.executable, str(gate), str(f), str(ignores)], capture_output=True, text=True)
        assert r.returncode == code, (rep, r.stdout, r.stderr)


def test_the_repo_ignore_file_is_valid():
    load_ignores(HERE.parent / "audit-ignore.txt", date.today())


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("audit gate tests passed")
