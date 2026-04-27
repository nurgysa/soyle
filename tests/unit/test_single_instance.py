"""Tests for single-instance mutex."""
from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only", allow_module_level=True)

from soyle.platform.single_instance import SingleInstance


def test_acquire_succeeds_once() -> None:
    inst = SingleInstance(name="SöyleTest-Acquire")
    assert inst.acquire() is True
    inst.release()


def test_second_acquire_fails_while_held() -> None:
    a = SingleInstance(name="SöyleTest-Double")
    b = SingleInstance(name="SöyleTest-Double")

    assert a.acquire() is True
    assert b.acquire() is False
    a.release()


def test_release_allows_reacquire() -> None:
    a = SingleInstance(name="SöyleTest-Reacquire")
    assert a.acquire() is True
    a.release()

    b = SingleInstance(name="SöyleTest-Reacquire")
    assert b.acquire() is True
    b.release()
