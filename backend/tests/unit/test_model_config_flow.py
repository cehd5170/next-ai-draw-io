from app.models.server_models import ServerModelEntry
from app.models.validate_model import ValidateModelRequest
from app.routes.server_models import resolve_server_model_credentials
from app.routes.validate_model import _build_openai_client_kwargs


class TestResolveServerModelCredentials:
    def test_resolves_custom_api_key_and_base_url_envs(self, monkeypatch):
        monkeypatch.setenv("OPENAI_KEY_TEAM_A", "sk-team-a")
        monkeypatch.setenv("OPENAI_BASE_URL_TEAM_A", "https://example.com/v1")

        entry = ServerModelEntry(
            id="server:team-a:gpt-4o",
            modelId="gpt-4o",
            provider="openai",
            providerLabel="Team A",
            apiKeyEnv="OPENAI_KEY_TEAM_A",
            baseUrlEnv="OPENAI_BASE_URL_TEAM_A",
        )

        api_key, base_url = resolve_server_model_credentials(entry)

        assert api_key == "sk-team-a"
        assert base_url == "https://example.com/v1"

    def test_picks_first_available_api_key_from_env_list(self, monkeypatch):
        monkeypatch.delenv("OPENAI_KEY_1", raising=False)
        monkeypatch.setenv("OPENAI_KEY_2", "sk-team-b")

        entry = ServerModelEntry(
            id="server:team-b:gpt-4o",
            modelId="gpt-4o",
            provider="openai",
            providerLabel="Team B",
            apiKeyEnv=["OPENAI_KEY_1", "OPENAI_KEY_2"],
        )

        api_key, base_url = resolve_server_model_credentials(entry)

        assert api_key == "sk-team-b"
        assert base_url is None


class TestValidateModelKwargs:
    def test_validate_model_uses_base_url_for_custom_base_urls(self, settings_override):
        body = ValidateModelRequest(
            provider="openai",
            modelId="gpt-4o",
            apiKey="sk-test",
            baseUrl="https://custom-openai.example/v1",
        )

        kwargs = _build_openai_client_kwargs(body, "openai", settings_override)

        assert kwargs["api_key"] == "sk-test"
        assert kwargs["base_url"] == "https://custom-openai.example/v1"
