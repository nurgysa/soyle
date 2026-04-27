"""Tests for the module-level crash-report writer.

We exercise `_write_crash_report` directly against a tmp dir so the
file-write contract is verified without poking at `sys.excepthook`.
"""
from __future__ import annotations

from pathlib import Path

from soyle.app import _write_crash_report


def _raise_and_capture() -> tuple[type[BaseException], BaseException, object]:
    try:
        raise ValueError("something went wrong in the pipeline")
    except ValueError as exc:
        return type(exc), exc, exc.__traceback__


def test_crash_report_includes_exception_and_traceback(tmp_path: Path) -> None:
    exc_type, exc_value, tb = _raise_and_capture()
    path = _write_crash_report(tmp_path, exc_type, exc_value, tb)

    assert path.exists()
    assert path.parent == tmp_path
    content = path.read_text(encoding="utf-8")
    assert "ValueError" in content
    assert "something went wrong in the pipeline" in content
    assert "Traceback" in content
    assert "Söyle crash report" in content


def test_crash_report_creates_log_dir(tmp_path: Path) -> None:
    """`log_dir` may not exist yet (first-run crash before Qt loop)."""
    nested = tmp_path / "logs" / "nested"
    assert not nested.exists()
    exc_type, exc_value, tb = _raise_and_capture()
    path = _write_crash_report(nested, exc_type, exc_value, tb)
    assert path.exists()
    assert path.parent == nested


def test_crash_report_filename_is_timestamped(tmp_path: Path) -> None:
    exc_type, exc_value, tb = _raise_and_capture()
    path = _write_crash_report(tmp_path, exc_type, exc_value, tb)
    name = path.name
    # crash-YYYYMMDDTHHMMSSZ.log
    assert name.startswith("crash-")
    assert name.endswith(".log")
    assert "T" in name  # ISO-ish timestamp separator
