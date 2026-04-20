"""Tests for domain exception hierarchy."""
from __future__ import annotations

from whisperflow.core.errors import (
    AudioDeviceError,
    ConfigError,
    CudaOOMError,
    CudaUnavailableError,
    ModelNotLoadedError,
    PermissionDeniedError,
    PostProcessError,
    WhisperFlowError,
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
        assert issubclass(exc_type, WhisperFlowError)


def test_base_error_is_exception() -> None:
    assert issubclass(WhisperFlowError, Exception)


def test_error_carries_message() -> None:
    err = AudioDeviceError("microphone not found")
    assert str(err) == "microphone not found"


def test_error_with_module_attr() -> None:
    err = CudaOOMError("vram exhausted")
    err.module = "transcriber"
    assert err.module == "transcriber"
