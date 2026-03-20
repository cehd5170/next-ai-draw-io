import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
import app.dependencies as _deps


@pytest.fixture
def settings_override():
    """Override settings for testing."""
    return Settings(
        AI_PROVIDER="openai",
        AI_MODEL="gpt-4o",
        MAX_FILE_SIZE_BYTES=2 * 1024 * 1024,
        MAX_FILES_PER_MESSAGE=5,
        MAX_OUTPUT_TOKENS=16384,
        MAX_TOOL_STEPS=5,
        ENABLE_VLM_VALIDATION=False,
        ENABLE_HISTORY_XML_REPLACE=False,
    )


@pytest.fixture
def test_client(settings_override):
    """Create a TestClient with settings dependency overridden."""
    app = create_app()
    # Override the get_settings dependency so every route sees settings_override
    app.dependency_overrides[_deps.get_settings] = lambda: settings_override
    return TestClient(app)


@pytest.fixture
def sample_mxcell_xml():
    return '''<mxCell id="2" value="Start" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>
</mxCell>
<mxCell id="3" value="End" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="300" y="100" width="120" height="60" as="geometry"/>
</mxCell>
<mxCell id="4" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="3">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>'''


@pytest.fixture
def sample_full_xml(sample_mxcell_xml):
    return f'''<mxGraphModel>
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    {sample_mxcell_xml}
  </root>
</mxGraphModel>'''


@pytest.fixture
def mock_litellm():
    """Mock litellm.acompletion for testing."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def sample_validation_result():
    return {
        "valid": False,
        "issues": [
            {"type": "overlap", "severity": "critical", "description": "Box A overlaps Box B"},
            {"type": "layout", "severity": "warning", "description": "Poor spacing between elements"}
        ],
        "suggestions": ["Move Box A 50px to the left"]
    }
