"""Fail if the privacy page leaves out an unencrypted field group (T-12-13).

`api/app/core/privacy_plaintext.py` lists every plaintext column, grouped,
with the exact phrase the privacy page must show for each group (its
completeness against the models is tested in the API suite). This checks,
without importing the app, that each phrase appears verbatim in
`ui/src/copy/privacy.ts`, which the privacy page renders.

Usage: check_privacy_copy.py [REPO_ROOT]
"""
import ast
import pathlib
import sys

PHRASES = pathlib.Path("api/app/core/privacy_plaintext.py")
COPY = pathlib.Path("ui/src/copy/privacy.ts")


def phrases(source: str) -> dict[str, str]:
    for node in ast.parse(source).body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id == "PRIVACY_PHRASES":
            return ast.literal_eval(node.value)
    raise SystemExit(f"{PHRASES}: no PRIVACY_PHRASES")


def main(root: pathlib.Path) -> int:
    wanted = phrases((root / PHRASES).read_text())
    page = (root / COPY).read_text()
    missing = {key: text for key, text in wanted.items() if f'"{text}"' not in page}
    for key, text in missing.items():
        print(f"{COPY}: missing the '{key}' group: \"{text}\"")
    if missing:
        print(f"\n{len(missing)} problem(s). Copy each phrase from {PHRASES} into {COPY} exactly.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(".")))
