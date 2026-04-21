"""Build WhisperFlow.exe via PyInstaller.

Run from the project root:
    uv run --extra build python scripts/build_exe.py

Produces dist/WhisperFlow/WhisperFlow.exe. The Whisper model is downloaded
on first run (not bundled) to keep the installer under 500 MB.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "whisperflow"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "WhisperFlow.spec"

SEP = ";" if sys.platform == "win32" else ":"

ADD_DATA = [
    (SRC / "assets", "assets"),
    (SRC / "prompts", "prompts"),
    (SRC / "ui" / "qss", "qss"),
]
CUDNN_DIR = ROOT / "vendor" / "cudnn"


def clean_previous() -> None:
    for p in (DIST, BUILD, SPEC):
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()


def build_cmd() -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",
        "--windowed",
        f"--icon={SRC / 'assets' / 'icon.ico'}",
        "--name",
        "WhisperFlow",
        "--collect-all",
        "faster_whisper",
        "--collect-all",
        "silero_vad",
    ]
    for src_dir, dest in ADD_DATA:
        if src_dir.is_dir():
            cmd += ["--add-data", f"{src_dir}{SEP}{dest}"]
    if CUDNN_DIR.is_dir():
        for dll in CUDNN_DIR.glob("*.dll"):
            cmd += ["--add-binary", f"{dll}{SEP}."]
    cmd.append(str(SRC / "app.py"))
    return cmd


def main() -> int:
    clean_previous()
    cmd = build_cmd()
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode

    exe = DIST / "WhisperFlow" / "WhisperFlow.exe"
    print(f"\nBuild artifact: {exe}")
    print(f"Exists: {exe.exists()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
