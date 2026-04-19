"""Domain exception hierarchy."""
from __future__ import annotations


class WhisperFlowError(Exception):
    """Base for all WhisperFlow domain exceptions."""


class AudioDeviceError(WhisperFlowError):
    """Microphone device unavailable or not found."""


class PermissionDeniedError(WhisperFlowError):
    """Windows privacy settings blocked mic access."""


class CudaUnavailableError(WhisperFlowError):
    """CUDA runtime not available; caller should fallback to CPU."""


class CudaOOMError(WhisperFlowError):
    """VRAM exhausted during model load or inference."""


class ModelNotLoadedError(WhisperFlowError):
    """Whisper model not loaded or file corrupted."""


class PostProcessError(WhisperFlowError):
    """OpenRouter call failed irrecoverably (surfaced to caller only when fallback impossible)."""


class ConfigError(WhisperFlowError):
    """Config file missing, unreadable, or invalid."""
