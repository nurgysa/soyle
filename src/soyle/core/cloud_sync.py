"""Google Drive sync of dictionary.toml — Phase 1.

This module owns:
- OAuth 2.0 PKCE flow (no client_secret in distributable binary)
- Drive REST calls (httpx, no google-api-python-client dependency)
- Refresh token storage via keyring (Windows Credential Manager)
- Daily-cadence scheduled sync coordination

See docs/superpowers/specs/2026-04-30-cloud-sync-design.md for the
design rationale, locked decisions, and error-handling matrix.
"""
from __future__ import annotations

import base64
import hashlib
import secrets

# ---- PKCE helpers (RFC 7636) ------------------------------------------------

def _generate_code_verifier() -> str:
    """Cryptographically random PKCE code_verifier.

    Returns a 43-128 char URL-safe string per RFC 7636 §4.1. We pick 64
    bytes of entropy → ~86 chars after base64url, comfortably in range.
    """
    return secrets.token_urlsafe(64)


def _derive_code_challenge(verifier: str) -> str:
    """PKCE code_challenge for the S256 method.

    challenge = base64url(sha256(verifier)) without trailing '=' padding,
    per RFC 7636 §4.2. Google's token endpoint rejects challenges with
    padding.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
