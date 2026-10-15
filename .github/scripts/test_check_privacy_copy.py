"""Self-test for check_privacy_copy.py: it passes on this repo and fails on
a copy that leaves out a phrase."""
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CHECK = HERE / "check_privacy_copy.py"
REPO = HERE.parent.parent


def run(root: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECK), str(root)], capture_output=True, text=True)


def fake_repo(tmp: pathlib.Path, copy: str) -> pathlib.Path:
    (tmp / "api/app/core").mkdir(parents=True)
    (tmp / "ui/src/copy").mkdir(parents=True)
    (tmp / "api/app/core/privacy_plaintext.py").write_text(
        'PRIVACY_PHRASES: dict[str, str] = {"email": "your email address", "dates": "dates and times"}\n'
    )
    (tmp / "ui/src/copy/privacy.ts").write_text(copy)
    return tmp


def main() -> None:
    real = run(REPO)
    assert real.returncode == 0, real.stdout + real.stderr
    with tempfile.TemporaryDirectory() as d:
        ok = run(fake_repo(pathlib.Path(d), 'export const X = ["your email address", "dates and times"]\n'))
        assert ok.returncode == 0, ok.stdout
    with tempfile.TemporaryDirectory() as d:
        bad = run(fake_repo(pathlib.Path(d), 'export const X = ["your email address"]\n'))
        assert bad.returncode == 1 and "'dates' group" in bad.stdout, bad.stdout
    print("check_privacy_copy: ok")


if __name__ == "__main__":
    main()
