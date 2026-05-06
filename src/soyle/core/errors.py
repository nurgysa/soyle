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


class OAuthAuthRevokedError(SoyleError):
    """Google OAuth refresh token has been revoked.

    Distinct from network/transient errors — caller must clear local
    keyring state and prompt the user to re-authorize. Distinguished
    from generic OAuth failures (misconfigured client_id, scope drift)
    which surface as httpx.HTTPStatusError.
    """
