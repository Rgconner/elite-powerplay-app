"""Spansh search retries: transient failures are retried, others are not."""

import pytest
import requests

from services import ingestion


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self.content = b"{}"
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(ingestion.time, "sleep", lambda s: None)


def _metrics():
    return {"api_calls": 0, "api_errors": 0, "errors": [], "bytes_downloaded": 0, "pages_fetched": 0}


def test_502_then_success_is_retried(monkeypatch):
    responses = iter([_Resp(502), _Resp(503), _Resp(200, {"results": [1]})])
    monkeypatch.setattr(ingestion.requests, "post", lambda *a, **k: next(responses))
    m = _metrics()
    assert ingestion._post_search({}, "test", m) == {"results": [1]}
    assert m["api_calls"] == 3 and m["api_errors"] == 2 and m["pages_fetched"] == 1


def test_connection_error_is_retried(monkeypatch):
    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("reset")
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(ingestion.requests, "post", post)
    assert ingestion._post_search({}, "test") == {"ok": True}


def test_400_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        return _Resp(400)

    monkeypatch.setattr(ingestion.requests, "post", post)
    with pytest.raises(requests.HTTPError):
        ingestion._post_search({}, "test")
    assert calls["n"] == 1


def test_gives_up_after_all_retries(monkeypatch):
    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        return _Resp(502)

    monkeypatch.setattr(ingestion.requests, "post", post)
    with pytest.raises(requests.HTTPError):
        ingestion._post_search({}, "test")
    assert calls["n"] == len(ingestion.RETRY_DELAYS) + 1
