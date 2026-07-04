from types import SimpleNamespace

from app.advisory import providers


def _settings(**kw):
    base = dict(anthropic_api_key="", gemini_api_key="", groq_api_key="",
                openai_api_key="", advisory_provider="auto")
    base.update(kw)
    return SimpleNamespace(**base)


def _patch(monkeypatch, **kw):
    monkeypatch.setattr(providers, "get_settings", lambda: _settings(**kw))


def test_no_provider(monkeypatch):
    _patch(monkeypatch)
    assert providers.any_configured() is False
    assert providers.select_provider() is None


def test_priority_prefers_anthropic(monkeypatch):
    _patch(monkeypatch, anthropic_api_key="a", gemini_api_key="g", groq_api_key="q")
    assert providers.select_provider() == "anthropic"


def test_falls_back_to_gemini_then_groq(monkeypatch):
    _patch(monkeypatch, gemini_api_key="g", groq_api_key="q")
    assert providers.select_provider() == "gemini"
    _patch(monkeypatch, groq_api_key="q")
    assert providers.select_provider() == "groq"


def test_vision_skips_groq_but_uses_gemini(monkeypatch):
    _patch(monkeypatch, groq_api_key="q")
    assert providers.select_provider(vision=True) is None  # groq: text-only here
    _patch(monkeypatch, groq_api_key="q", gemini_api_key="g")
    assert providers.select_provider(vision=True) == "gemini"


def test_explicit_override_respected(monkeypatch):
    _patch(monkeypatch, gemini_api_key="g", groq_api_key="q", advisory_provider="groq")
    assert providers.select_provider() == "groq"


def test_override_not_configured_returns_none(monkeypatch):
    _patch(monkeypatch, advisory_provider="openai")  # no openai key
    assert providers.select_provider() is None
