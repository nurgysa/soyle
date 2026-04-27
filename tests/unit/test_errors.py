"""Tests for domain exception hierarchy."""
from __future__ import annotations

from soyle.core.errors import (
    AudioDeviceError,
    ConfigError,
    CudaOOMError,
    CudaUnavailableError,
    ModelNotLoadedError,
    PermissionDeniedError,
    PostProcessError,
    SoyleError,
)


def test_all_errors_inherit_base() -> None:
    for exc_type in [
        AudioDeviceError,
        PermissionDeniedError,
        CudaUnavailableError,
        CudaOOMError,
        ModelNotLoadedError,
        PostProcessError,
        ConfigError,
    ]:
        assert issubclass(exc_type, SoyleError)


def test_base_error_is_exception() -> None:
    assert issubclass(SoyleError, Exception)


def test_error_carries_message() -> None:
    err = AudioDeviceError("microphone not found")
    assert str(err) == "microphone not found"


def test_error_with_module_attr() -> None:
    err = CudaOOMError("vram exhausted")
    err.module = "transcriber"
    assert err.module == "transcriber"
