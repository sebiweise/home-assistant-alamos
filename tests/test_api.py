"""Tests for the Alamos API client."""

from unittest.mock import MagicMock

import aiohttp
import pytest

from custom_components.alamos.api import AlamosApiClient, AlamosApiError

API_KEY = "secret/key+1"


class _FailingSession:
    """Session whose requests always fail with an error containing the URL."""

    def request(self, method, url, params):
        raise aiohttp.ClientError(f"Failed {url}?authToken={params['authToken']}")


async def test_error_message_does_not_contain_api_key() -> None:
    """The API key never ends up in the error message or its cause."""
    client = AlamosApiClient(_FailingSession(), API_KEY, "https://example.invalid")
    with pytest.raises(AlamosApiError) as exc_info:
        await client.async_send_feedback("accept")
    assert API_KEY not in str(exc_info.value)
    assert "ClientError" in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_redact_encoded_key() -> None:
    """URL-encoded forms of the key are redacted, too."""
    client = AlamosApiClient(MagicMock(), API_KEY, "https://example.invalid")
    err = aiohttp.ClientError("url=?authToken=secret%2Fkey%2B1 and secret/key%2B1")
    text = client._redact(err)
    assert "secret" not in text
