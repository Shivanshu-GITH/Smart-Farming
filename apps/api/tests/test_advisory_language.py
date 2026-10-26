"""The advisor answers in the farmer's language, not an assumed one."""
import asyncio

from fastapi.testclient import TestClient

from app.advisory import service
from app.main import app


def _captured_system(monkeypatch, **kw):
    seen = {}

    async def fake_chat(system, messages):
        seen["system"] = system
        return "ok"

    monkeypatch.setattr(service.providers, "chat", fake_chat)
    asyncio.run(service.chat([{"role": "user", "content": "hi"}], {"crop": "paddy"}, **kw))
    return seen["system"]


def test_prompt_follows_the_latest_message_language(monkeypatch):
    system = _captured_system(monkeypatch)
    assert "same language as the farmer's latest message" in system


def test_app_language_is_the_fallback(monkeypatch):
    assert "Telugu" in _captured_system(monkeypatch, language="te")
    assert "English" in _captured_system(monkeypatch, language="xx")   # unknown -> English


def test_chat_route_accepts_language(monkeypatch):
    seen = {}

    async def fake(messages, context=None, language=None):
        seen["language"] = language
        return "ok"

    monkeypatch.setattr(service, "advisory_available", lambda: True)
    monkeypatch.setattr(service, "chat", fake)
    r = TestClient(app).post("/advisory/chat", json={
        "messages": [{"role": "user", "content": "hello"}], "language": "hi"})
    assert r.status_code == 200 and seen["language"] == "hi"
