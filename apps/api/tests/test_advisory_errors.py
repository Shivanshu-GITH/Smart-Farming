"""Provider failures must never leak keys, and rate limits read as 'busy'."""
import httpx
from fastapi.testclient import TestClient

from app.advisory import providers, service
from app.main import app

SECRET = "AQ.test-secret-key-123"


def _settings(monkeypatch):
    s = providers.get_settings()
    monkeypatch.setattr(s, "gemini_api_key", SECRET)
    return s


def test_gemini_key_goes_in_a_header_not_the_url(monkeypatch):
    _settings(monkeypatch)
    assert SECRET not in providers._gemini_url()
    assert providers._gemini_headers()["x-goog-api-key"] == SECRET


def _raise(status: int):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/m:generateContent?key={SECRET}"
    req = httpx.Request("POST", url)
    raise httpx.HTTPStatusError(f"Client error '{status}' for url '{url}'", request=req,
                                response=httpx.Response(status, request=req))


def _post(monkeypatch, status):
    async def boom(*_a, **_k):
        _raise(status)

    monkeypatch.setattr(service, "advisory_available", lambda: True)
    monkeypatch.setattr(service, "chat", boom)
    return TestClient(app).post("/advisory/chat",
                                json={"messages": [{"role": "user", "content": "hi"}]})


def test_rate_limit_is_reported_as_busy_without_the_url(monkeypatch):
    r = _post(monkeypatch, 429)
    assert r.status_code == 503
    assert SECRET not in r.text and "googleapis" not in r.text
    assert "busy" in r.json()["detail"].lower()


def test_other_provider_errors_do_not_echo_the_exception(monkeypatch):
    r = _post(monkeypatch, 500)
    assert r.status_code == 502
    assert SECRET not in r.text and "googleapis" not in r.text


def test_reply_language_from_the_message_script():
    assert service.reply_language("What is wrong with my paddy?", "hi") == "English"
    assert service.reply_language("मेरे धान में क्या रोग है?", "en") == "Hindi"
    assert service.reply_language("నా వరికి ఏ వ్యాధి?", "en") == "Telugu"
    assert service.reply_language("12 kg?", "te") == "Telugu"         # unclear -> UI language
    assert service.reply_language("ok", None) == "English"
