"""Domain exception hierarchy."""
from __future__ import annotations


class SoyleError(Exception):
    """Base for all Söyle domain exceptions."""


class AudioDeviceError(SoyleError):
    """Microphone device unavailable or not found."""


class PermissionDeniedError(SoyleError):
    """Windows privacy settings blocked mic access."""


class CudaUnavailableError(SoyleError):
    """CUDA runtime not available; caller should fallback to CPU."""


class CudaOOMError(SoyleError):
    """VRAM exhausted during model load or inference."""


class ModelNotLoadedError(SoyleError):
    """Whisper model not loaded or file corrupted."""


class PostProcessError(SoyleError):
    """OpenRouter call failed irrecoverably (surfaced to caller only when fallback impossible)."""


class ConfigError(SoyleError):
    """Config file missing, unreadable, or invalid."""
