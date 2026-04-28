"""Build Soyle.exe via PyInstaller.

Run from the project root:
    uv run --extra build python scripts/build_exe.py

Produces dist/Soyle/Soyle.exe. The Whisper model is downloaded
on first run (not bundled) to keep the installer under 500 MB.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "soyle"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "Soyle.spec"

SEP = ";" if sys.platform == "win32" else ":"

ADD_DATA = [
    (SRC / "assets", "assets"),
    (SRC / "prompts", "prompts"),
    # IMPORTANT: destination must mirror the path `resources.qss_path()`
    # looks up — it resolves `<bundle_root>/ui/qss/<theme>.qss`.
    (SRC / "ui" / "qss", "ui/qss"),
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
    # Excludes trim ~350 MB of transitive fat: torch (only pulled via
    # silero-vad which we don't use — recorder.py does RMS-based VAD),
    # PIL (only used by scripts/generate_icon.py at build time), and
    # onnxruntime (silero's alternative inference backend).
    excludes = ("torch", "PIL", "Pillow", "onnxruntime", "silero_vad")

    # `--collect-all` grabs every submodule + data + binary. Needed for:
    # - `faster_whisper` — audio tokenizer/VAD assets
    # - `keyring` — backends registered via entry_points, not imported by
    #   name from our code.
    # `tomli` is intentionally gone: the stdlib `tomllib` is a drop-in on
    # Python 3.11+ and avoids tomli's mypyc-compiled module (which lives
    # at site-packages root as `<hash>__mypyc.pyd` and is a PyInstaller
    # footgun).
    collect_all = ("faster_whisper", "keyring")

    # `--name Soyle` (ASCII, no umlaut) keeps the output exe filename and
    # the dist directory friendly for CLI tooling, scripts, and the
    # installer.iss [Files] glob. The umlauted brand "Söyle" is reserved
    # for user-visible strings (window titles, tray tooltip, installer UI)
    # and is set there explicitly. Don't change to "Söyle" without also
    # updating installer.iss MyAppExeName / DefaultDirName / [Files] Source.
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",
        "--windowed",
        f"--icon={SRC / 'assets' / 'icon.ico'}",
        "--name",
        "Soyle",
    ]
    for pkg in collect_all:
        cmd += ["--collect-all", pkg]
    for mod in excludes:
        cmd += ["--exclude-module", mod]
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

    exe = DIST / "Soyle" / "Soyle.exe"
    print(f"\nBuild artifact: {exe}")
    print(f"Exists: {exe.exists()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
