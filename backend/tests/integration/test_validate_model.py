from fastapi.testclient import TestClient

import app.routes.validate_model as validate_model_route


class _FakeCompletions:
    def __init__(self, calls: list[dict]):
        self.calls = calls

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class _FakeChat:
    def __init__(self, calls: list[dict]):
        self.completions = _FakeCompletions(calls)


class _FakeAsyncOpenAI:
    instances: list["_FakeAsyncOpenAI"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[dict] = []
        self.chat = _FakeChat(self.calls)
        _FakeAsyncOpenAI.instances.append(self)


def test_validate_model_uses_openai_sdk_for_compatible_provider(
    monkeypatch, test_client: TestClient
):
    monkeypatch.setattr(validate_model_route, "AsyncOpenAI", _FakeAsyncOpenAI)
    _FakeAsyncOpenAI.instances.clear()

    response = test_client.post(
        "/api/validate-model",
        json={
            "provider": "openai",
            "modelId": "gpt-4o-mini",
            "apiKey": "sk-test",
            "baseUrl": "https://api.openai.example/v1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert isinstance(data["responseTime"], int)
    assert _FakeAsyncOpenAI.instances, "Expected the OpenAI client to be instantiated"
    client = _FakeAsyncOpenAI.instances[0]
    assert client.kwargs["api_key"] == "sk-test"
    assert client.kwargs["base_url"] == "https://api.openai.example/v1"
    assert client.calls[0]["model"] == "gpt-4o-mini"
    assert client.calls[0]["max_tokens"] == 20


def test_validate_model_uses_provider_default_base_url_when_missing(
    monkeypatch, test_client: TestClient
):
    monkeypatch.setattr(validate_model_route, "AsyncOpenAI", _FakeAsyncOpenAI)
    _FakeAsyncOpenAI.instances.clear()

    response = test_client.post(
        "/api/validate-model",
        json={
            "provider": "openrouter",
            "modelId": "openai/gpt-4o-mini",
            "apiKey": "sk-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True
    client = _FakeAsyncOpenAI.instances[0]
    assert client.kwargs["base_url"] == "https://openrouter.ai/api/v1"


def test_validate_model_uses_max_completion_tokens_for_gpt5_models(
    monkeypatch, test_client: TestClient
):
    monkeypatch.setattr(validate_model_route, "AsyncOpenAI", _FakeAsyncOpenAI)
    _FakeAsyncOpenAI.instances.clear()

    response = test_client.post(
        "/api/validate-model",
        json={
            "provider": "openai",
            "modelId": "gpt-5.4-nano",
            "apiKey": "sk-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True
    client = _FakeAsyncOpenAI.instances[0]
    assert client.calls[0]["max_completion_tokens"] == 20
    assert "max_tokens" not in client.calls[0]
