"""Tests for CloudSync — Google Drive sync of dictionary.toml."""
from __future__ import annotations

import base64
import hashlib
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from soyle.core.cloud_sync import (
    _derive_code_challenge,
    _generate_code_verifier,
    _OAuthCallbackListener,
)


def test_code_verifier_is_url_safe_string_of_correct_length() -> None:
    verifier = _generate_code_verifier()
    # RFC 7636: verifier is 43-128 chars from [A-Z][a-z][0-9]-._~
    assert 43 <= len(verifier) <= 128
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    )
    assert all(c in allowed for c in verifier)


def test_code_verifier_is_random() -> None:
    """Two consecutive calls produce different verifiers."""
    a = _generate_code_verifier()
    b = _generate_code_verifier()
    assert a != b


def test_derive_code_challenge_is_sha256_base64url_of_verifier() -> None:
    """RFC 7636 §4.2: challenge = base64url(sha256(verifier)) without padding."""
    verifier = "test-verifier-known-value-1234567890abcdefABCDEF~_."
    expected_hash = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(expected_hash).decode("ascii").rstrip("=")
    assert _derive_code_challenge(verifier) == expected


def test_derive_code_challenge_has_no_padding() -> None:
    """base64url with padding is not accepted by Google's token endpoint."""
    verifier = _generate_code_verifier()
    challenge = _derive_code_challenge(verifier)
    assert "=" not in challenge


def test_callback_listener_picks_free_port_above_1024() -> None:
    listener = _OAuthCallbackListener()
    listener.start()
    try:
        assert listener.port > 1024
        assert listener.redirect_uri == f"http://localhost:{listener.port}/callback"
    finally:
        listener.shutdown()


def test_callback_listener_captures_query_params() -> None:
    listener = _OAuthCallbackListener()
    listener.start()
    try:
        # Simulate browser hitting the redirect_uri
        params = {"code": "auth-code-123", "state": "xyz"}
        url = f"{listener.redirect_uri}?{urlencode(params)}"
        with urlopen(url, timeout=2) as resp:
            assert resp.status == 200

        result = listener.wait_for_callback(timeout=2)
        assert result == {"code": "auth-code-123", "state": "xyz"}
    finally:
        listener.shutdown()


def test_callback_listener_times_out_when_no_callback() -> None:
    """If user never authorizes, wait_for_callback raises TimeoutError."""
    listener = _OAuthCallbackListener()
    listener.start()
    try:
        with pytest.raises(TimeoutError):
            listener.wait_for_callback(timeout=0.5)
    finally:
        listener.shutdown()


def test_callback_listener_returns_user_friendly_html() -> None:
    """Page shown in browser after callback — short Russian confirmation."""
    listener = _OAuthCallbackListener()
    listener.start()
    try:
        url = f"{listener.redirect_uri}?code=x"
        with urlopen(url, timeout=2) as resp:
            body = resp.read().decode("utf-8")
        assert "Söyle" in body
        # User can now close the browser tab
        assert "можно закрыть" in body.lower() or "can close" in body.lower()
    finally:
        listener.shutdown()
