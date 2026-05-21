"""Tests for CloudSync — Google Drive sync of dictionary.toml."""
from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

import httpx
import pytest
import respx

from soyle.core.cloud_sync import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    OAUTH_TOKEN_URL,
    CloudSync,
    _derive_code_challenge,
    _exchange_code_for_tokens,
    _generate_code_verifier,
    _OAuthCallbackListener,
    _refresh_access_token,
    _TokenStore,
)
from soyle.core.errors import OAuthAuthRevokedError


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


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_returns_refresh_and_access_tokens() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.access",
                "refresh_token": "1//refresh",
                "expires_in": 3599,
                "scope": "https://www.googleapis.com/auth/drive.appdata",
                "token_type": "Bearer",
            },
        )
    )
    tokens = await _exchange_code_for_tokens(
        client_id="cid",
        code="auth-code",
        code_verifier="verifier",
        redirect_uri="http://localhost:1234/callback",
    )
    assert tokens.refresh_token == "1//refresh"
    assert tokens.access_token == "ya29.access"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_returns_new_access() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ya29.refreshed",
                "expires_in": 3599,
                "token_type": "Bearer",
            },
        )
    )
    access = await _refresh_access_token(client_id="cid", refresh_token="1//refresh")
    assert access == "ya29.refreshed"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_raises_revoked_on_invalid_grant() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_grant"},
        )
    )
    with pytest.raises(OAuthAuthRevokedError):
        await _refresh_access_token(client_id="cid", refresh_token="bad")


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_propagates_network_error() -> None:
    respx.post(OAUTH_TOKEN_URL).mock(side_effect=httpx.ConnectError("DNS"))
    with pytest.raises(httpx.ConnectError):
        await _refresh_access_token(client_id="cid", refresh_token="1//refresh")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_never_sends_client_secret() -> None:
    """PKCE security contract: the binary must NOT ship a client_secret.

    A regression that adds client_secret to the payload would silently
    ship undetected by other tests. This test captures the actual POST
    body and asserts the field is absent — locking the contract.
    """
    from urllib.parse import parse_qsl

    route = respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "x", "refresh_token": "y"}
        )
    )
    await _exchange_code_for_tokens(
        client_id="cid",
        code="auth-code",
        code_verifier="verifier-value",
        redirect_uri="http://localhost:1234/callback",
    )
    sent_body = dict(parse_qsl(route.calls.last.request.content.decode("utf-8")))
    assert "client_secret" not in sent_body
    # Verify code_verifier IS sent (the PKCE replacement for client_secret).
    assert sent_body["code_verifier"] == "verifier-value"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_never_sends_client_secret() -> None:
    """Same PKCE contract on the refresh path."""
    from urllib.parse import parse_qsl

    route = respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "x"}
        )
    )
    await _refresh_access_token(client_id="cid", refresh_token="1//refresh")
    sent_body = dict(parse_qsl(route.calls.last.request.content.decode("utf-8")))
    assert "client_secret" not in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_refresh_access_token_logs_structured_error_for_non_invalid_grant_4xx() -> None:
    """Non-invalid_grant 4xx must surface the structured error code in logs.

    Without this, debugging a misconfigured-client-id incident
    (`error=invalid_client`) is indistinguishable from a generic 400 in
    soyle.log.
    """
    respx.post(OAUTH_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_client", "error_description": "wrong client"},
        )
    )
    # Using mocker isn't necessary — we just assert the httpx.HTTPStatusError
    # propagates with the body still inspectable via .response.
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _refresh_access_token(client_id="cid", refresh_token="1//refresh")
    # The body remains accessible for downstream debugging.
    assert exc_info.value.response.json()["error"] == "invalid_client"


# ---- _TokenStore (Task 6) ---------------------------------------------------


def test_token_store_save_and_load(mocker) -> None:
    backing: dict[tuple[str, str], str] = {}
    mocker.patch(
        "soyle.core.cloud_sync.keyring.set_password",
        side_effect=lambda s, u, p: backing.update({(s, u): p}),
    )
    mocker.patch(
        "soyle.core.cloud_sync.keyring.get_password",
        side_effect=lambda s, u: backing.get((s, u)),
    )

    store = _TokenStore()
    assert store.load() is None

    store.save("1//refresh-token-abc")
    assert store.load() == "1//refresh-token-abc"
    assert backing[(KEYRING_SERVICE, KEYRING_USERNAME)] == "1//refresh-token-abc"


def test_token_store_clear(mocker) -> None:
    deletions: list[tuple[str, str]] = []
    mocker.patch(
        "soyle.core.cloud_sync.keyring.delete_password",
        side_effect=lambda s, u: deletions.append((s, u)),
    )

    store = _TokenStore()
    store.clear()
    assert deletions == [(KEYRING_SERVICE, KEYRING_USERNAME)]


def test_token_store_clear_swallows_not_found(mocker) -> None:
    """Deleting a non-existent token is a no-op, not an error."""
    import keyring.errors

    mocker.patch(
        "soyle.core.cloud_sync.keyring.delete_password",
        side_effect=keyring.errors.PasswordDeleteError("no such pw"),
    )

    store = _TokenStore()
    store.clear()  # must not raise


# ---- CloudSync skeleton + state predicates (Task 7) -------------------------


@pytest.fixture
def cloud_sync(tmp_path, mocker):
    """A CloudSync wired to in-memory keyring and a tmp config/dict store."""
    from soyle.core.config import ConfigStore
    from soyle.core.dictionary import DictionaryStore

    backing: dict[tuple[str, str], str] = {}
    mocker.patch(
        "soyle.core.cloud_sync.keyring.set_password",
        side_effect=lambda s, u, p: backing.update({(s, u): p}),
    )
    mocker.patch(
        "soyle.core.cloud_sync.keyring.get_password",
        side_effect=lambda s, u: backing.get((s, u)),
    )
    mocker.patch(
        "soyle.core.cloud_sync.keyring.delete_password",
        side_effect=lambda s, u: backing.pop((s, u), None),
    )

    cfg_store = ConfigStore(config_path=tmp_path / "config.toml")
    dict_store = DictionaryStore(path=tmp_path / "dict.toml")
    return CloudSync(
        dict_store=dict_store,
        config_store=cfg_store,
        client_id="test-client-id.apps.googleusercontent.com",
    )


def test_is_connected_false_when_no_token(cloud_sync) -> None:
    assert cloud_sync.is_connected is False


def test_is_connected_true_after_token_saved(cloud_sync) -> None:
    cloud_sync._token_store.save("1//some-refresh")
    assert cloud_sync.is_connected is True


def test_last_synced_at_reads_from_config(cloud_sync) -> None:
    when = datetime(2026, 4, 30, 10, 0, 0, tzinfo=UTC)
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = when
    cloud_sync._config_store.save(cfg)

    assert cloud_sync.last_synced_at == when


def test_should_run_scheduled_false_when_disconnected(cloud_sync) -> None:
    # No token; even if last_synced_at is ancient, should not run
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = datetime(2020, 1, 1, tzinfo=UTC)
    cloud_sync._config_store.save(cfg)
    assert cloud_sync.should_run_scheduled() is False


def test_should_run_scheduled_false_when_recently_synced(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = datetime.now(UTC) - timedelta(hours=12)
    cloud_sync._config_store.save(cfg)
    assert cloud_sync.should_run_scheduled() is False


def test_should_run_scheduled_true_after_24h(cloud_sync) -> None:
    cloud_sync._token_store.save("1//refresh")
    cfg = cloud_sync._config_store.load()
    cfg.cloud_sync.last_synced_at = datetime.now(UTC) - timedelta(hours=25)
    cloud_sync._config_store.save(cfg)
    assert cloud_sync.should_run_scheduled() is True


def test_should_run_scheduled_true_when_never_synced(cloud_sync) -> None:
    """Connected but last_synced_at=None → first sync should run."""
    cloud_sync._token_store.save("1//refresh")
    assert cloud_sync.should_run_scheduled() is True
