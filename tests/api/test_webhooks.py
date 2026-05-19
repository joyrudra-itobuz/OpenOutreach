from __future__ import annotations

import io
from urllib.error import HTTPError

import pytest

from linkedin.api.webhooks import post_json


class _FakeResponse:
    def __init__(self, status: int = 200, body: str = "ok"):
        self.status = status
        self._body = body

    def read(self):
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_post_json_success(monkeypatch):
    def fake_urlopen(request, timeout=10):
        return _FakeResponse(200, "received")

    monkeypatch.setattr("linkedin.api.webhooks.urlopen", fake_urlopen)
    response = post_json("https://example.com/webhook", {"hello": "world"})
    assert response == {"status": 200, "body": "received"}


def test_post_json_http_error(monkeypatch):
    def fake_urlopen(request, timeout=10):
        raise HTTPError(
            request.full_url,
            500,
            "boom",
            hdrs=None,
            fp=io.BytesIO(b"fail"),
        )

    monkeypatch.setattr("linkedin.api.webhooks.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        post_json("https://example.com/webhook", {"hello": "world"})
