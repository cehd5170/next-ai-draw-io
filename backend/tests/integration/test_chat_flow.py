"""
Integration tests for the FastAPI application routes.

Covers:
- GET  /api/config           – returns public server configuration
- POST /api/verify-access-code – validates access codes (no code required in tests)
- POST /api/export-pptx      – rejects empty/invalid XML with 400

All tests use a TestClient with settings overrides so no real AI provider
or DynamoDB connection is needed.
"""

import pytest
from fastapi.testclient import TestClient


class TestChatEndpoint:
    def test_config_endpoint_returns_200(self, test_client: TestClient):
        """GET /api/config returns HTTP 200."""
        response = test_client.get("/api/config")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )

    def test_config_endpoint_has_max_file_size(self, test_client: TestClient):
        """GET /api/config includes the maxFileSize field."""
        response = test_client.get("/api/config")
        data = response.json()
        assert "maxFileSize" in data, "Response must include 'maxFileSize'"

    def test_config_endpoint_has_max_files(self, test_client: TestClient):
        """GET /api/config includes the maxFiles field."""
        response = test_client.get("/api/config")
        data = response.json()
        assert "maxFiles" in data, "Response must include 'maxFiles'"

    def test_config_endpoint_has_all_expected_fields(self, test_client: TestClient):
        """GET /api/config response contains all documented fields."""
        response = test_client.get("/api/config")
        data = response.json()
        expected_fields = {
            "maxFileSize",
            "maxFiles",
            "accessCodeRequired",
            "dailyRequestLimit",
            "dailyTokenLimit",
            "tpmLimit",
            "enableVlmValidation",
        }
        missing = expected_fields - set(data.keys())
        assert not missing, f"Config response is missing fields: {missing}"

    def test_config_vlm_validation_disabled(self, test_client: TestClient):
        """VLM validation flag matches the test settings override (False)."""
        response = test_client.get("/api/config")
        data = response.json()
        assert data["enableVlmValidation"] is False, (
            "Settings override sets ENABLE_VLM_VALIDATION=False"
        )

    def test_config_max_file_size_matches_settings(self, test_client: TestClient):
        """maxFileSize matches the value from settings_override (2 MB)."""
        response = test_client.get("/api/config")
        data = response.json()
        assert data["maxFileSize"] == 2 * 1024 * 1024, (
            f"Expected {2 * 1024 * 1024} bytes, got {data['maxFileSize']}"
        )

    def test_verify_access_no_code_required(self, test_client: TestClient):
        """POST /api/verify-access-code returns 200 when no code is configured."""
        # settings_override has no ACCESS_CODE_LIST, so any request is valid.
        response = test_client.post("/api/verify-access-code")
        assert response.status_code == 200, (
            f"Expected 200 when no access code is required, got {response.status_code}"
        )

    def test_verify_access_returns_valid_true(self, test_client: TestClient):
        """POST /api/verify-access-code returns {valid: true} with no code configured."""
        response = test_client.post("/api/verify-access-code")
        data = response.json()
        assert data.get("valid") is True, (
            "Should return valid=True when no access code is required"
        )

    def test_export_pptx_empty_xml_returns_400(self, test_client: TestClient):
        """POST /api/export-pptx with empty xml returns HTTP 400."""
        response = test_client.post("/api/export-pptx", json={"xml": ""})
        assert response.status_code == 400, (
            f"Expected 400 for empty XML, got {response.status_code}: {response.text}"
        )

    def test_export_pptx_missing_xml_field_returns_422(self, test_client: TestClient):
        """POST /api/export-pptx without an xml field returns HTTP 422 (validation error)."""
        response = test_client.post("/api/export-pptx", json={})
        assert response.status_code == 422, (
            f"Expected 422 for missing xml field, got {response.status_code}"
        )

    def test_export_pptx_whitespace_xml_returns_400(self, test_client: TestClient):
        """POST /api/export-pptx with whitespace-only xml returns HTTP 400."""
        response = test_client.post("/api/export-pptx", json={"xml": "   \n  "})
        assert response.status_code == 400, (
            f"Expected 400 for whitespace-only XML, got {response.status_code}"
        )

    def test_health_endpoint(self, test_client: TestClient):
        """GET /health returns HTTP 200 with status=ok."""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok", f"Health check should return status=ok, got: {data}"

    def test_config_content_type_is_json(self, test_client: TestClient):
        """GET /api/config response Content-Type is application/json."""
        response = test_client.get("/api/config")
        assert "application/json" in response.headers.get("content-type", ""), (
            "Config endpoint must return JSON content type"
        )

    def test_access_code_required_false_when_not_configured(self, test_client: TestClient):
        """accessCodeRequired is False when ACCESS_CODE_LIST is not set."""
        response = test_client.get("/api/config")
        data = response.json()
        assert data["accessCodeRequired"] is False, (
            "No access code should be required when ACCESS_CODE_LIST is not configured"
        )
