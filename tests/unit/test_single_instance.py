"""Tests for single-instance mutex."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from whisperflow.platform.single_instance import SingleInstance


def test_acquire_succeeds_once() -> None:
    inst = SingleInstance(name="WhisperFlowTest-Acquire")
    assert inst.acquire() is True
    inst.release()


def test_second_acquire_fails_while_held() -> None:
    a = SingleInstance(name="WhisperFlowTest-Double")
    b = SingleInstance(name="WhisperFlowTest-Double")

    assert a.acquire() is True
    assert b.acquire() is False
    a.release()


def test_release_allows_reacquire() -> None:
    a = SingleInstance(name="WhisperFlowTest-Reacquire")
    assert a.acquire() is True
    a.release()

    b = SingleInstance(name="WhisperFlowTest-Reacquire")
    assert b.acquire() is True
    b.release()
