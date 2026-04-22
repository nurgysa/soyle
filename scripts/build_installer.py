"""Build the Windows installer (`WhisperFlow-Setup-<version>.exe`).

Pipeline:
    pyproject.toml  →  version string
    build_exe.py    →  dist/WhisperFlow/           (if missing or --rebuild)
    iscc            →  release/WhisperFlow-Setup-<version>.exe

Inno Setup 6 must be installed; the script searches the usual paths.
If you installed it elsewhere, set INNOSETUP_ISCC env var to the full
iscc.exe path.

Run from the project root:

    uv run python scripts/build_installer.py
    uv run python scripts/build_installer.py --rebuild   # force PyInstaller re-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "WhisperFlow"
RELEASE = ROOT / "release"
ISS = ROOT / "installer" / "installer.iss"

ISCC_CANDIDATES = (
    r"C:\Program Files (x86)\Inno Setup 6\iscc.exe",
    r"C:\Program Files\Inno Setup 6\iscc.exe",
)


def read_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def find_iscc() -> Path:
    env = os.environ.get("INNOSETUP_ISCC")
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise SystemExit(f"INNOSETUP_ISCC={env} does not point to an existing file")

    for candidate in ISCC_CANDIDATES:
        p = Path(candidate)
        if p.is_file():
            return p

    raise SystemExit(
        "iscc.exe not found. Install Inno Setup 6 from https://jrsoftware.org/isdl.php\n"
        "or set INNOSETUP_ISCC to its full path."
    )


def run_pyinstaller() -> None:
    """Produce dist/WhisperFlow/ via the existing build_exe.py."""
    cmd = [sys.executable, str(ROOT / "scripts" / "build_exe.py")]
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit("PyInstaller build failed")


def run_iscc(iscc: Path, version: str) -> None:
    RELEASE.mkdir(parents=True, exist_ok=True)
    cmd = [str(iscc), f"/DMyAppVersion={version}", str(ISS)]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit("iscc failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Re-run PyInstaller even if dist/WhisperFlow already exists.",
    )
    args = parser.parse_args()

    version = read_version()
    print(f"WhisperFlow {version}")

    if args.rebuild or not DIST.is_dir():
        print("Running PyInstaller…")
        run_pyinstaller()
    else:
        print(f"Reusing existing {DIST}")

    iscc = find_iscc()
    print(f"Using iscc at: {iscc}")
    run_iscc(iscc, version)

    installer = RELEASE / f"WhisperFlow-Setup-{version}.exe"
    if installer.is_file():
        size_mb = installer.stat().st_size / 1_048_576
        print(f"\nInstaller: {installer} ({size_mb:.1f} MB)")
    else:
        print("\nWarning: expected installer file not found at", installer)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
