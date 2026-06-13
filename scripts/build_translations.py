"""Compile src/soyle/i18n/*.ts into .qm files next to them.

Run before packaging (and after editing translations) so the bundled
QTranslator has up-to-date .qm files.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "src" / "soyle" / "i18n"


def main() -> int:
    ts_files = sorted(I18N.glob("*.ts"))
    if not ts_files:
        print(f"no .ts files in {I18N}")
        return 1
    rc = 0
    for ts in ts_files:
        qm = ts.with_suffix(".qm")
        cmd = ["pyside6-lrelease", str(ts), "-qm", str(qm)]
        print(" ".join(cmd))
        rc |= subprocess.call(cmd)
    return rc


if __name__ == "__main__":
    sys.exit(main())
