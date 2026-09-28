"""Protected previews must keep internal engine calls on the deployment."""

from engine.core.config import Settings
from engine.orchestrator import runner


def test_vercel_defaults_use_current_deployment(monkeypatch):
    monkeypatch.setenv("VERCEL_URL", "stellar-agents-preview.vercel.app")
    settings = Settings(_env_file=None)
    assert settings.app_base_url == "https://stellar-agents-preview.vercel.app"
    assert settings.dashboard_origins == "https://stellar-agents-preview.vercel.app"


def test_dispatch_self_call_sends_protection_bypass(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs["headers"]))

    monkeypatch.setattr(runner.httpx, "post", fake_post)
    settings = Settings(
        _env_file=None,
        app_base_url="https://stellar-agents-preview.vercel.app",
        internal_secret="internal-test-secret",
        vercel_automation_bypass_secret="bypass-test-secret",
    )
    runner.trigger_dispatch(settings)

    assert calls[0][0] == "https://stellar-agents-preview.vercel.app/api/v1/internal/dispatch"
    assert calls[0][1]["x-vercel-protection-bypass"] == "bypass-test-secret"
    assert calls[0][1]["X-Signature"] == runner.sign("dispatch", "internal-test-secret")
