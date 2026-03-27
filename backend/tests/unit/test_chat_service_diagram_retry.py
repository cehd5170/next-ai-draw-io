from app.services.chat_service import ChatService


class TestMissingDiagramRetryHeuristic:
    def test_create_verbs_trigger_diagram_expectation(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Build a deployment view for this service"}],
            }
        ]

        assert ChatService._expects_diagram_tool(
            messages=messages,
            current_xml="",
        )

    def test_requests_with_diagram_keywords_trigger_retry(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Create an AWS architecture diagram"}],
            }
        ]

        assert ChatService._should_retry_for_missing_diagram(
            messages=messages,
            current_xml="",
            assistant_text="Here is the design approach.",
        )

    def test_existing_diagram_allows_text_only_explanation(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Explain what this does"}],
            }
        ]

        assert not ChatService._should_retry_for_missing_diagram(
            messages=messages,
            current_xml='<mxCell id="2" value="Node" vertex="1" parent="1" />',
            assistant_text="This diagram shows the main data flow.",
        )

    def test_attachments_trigger_retry_for_visual_replication(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Replicate this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ]

        assert ChatService._should_retry_for_missing_diagram(
            messages=messages,
            current_xml="",
            assistant_text="I can recreate that layout.",
        )

    def test_edit_verbs_trigger_diagram_expectation_when_canvas_exists(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Update the layout and add a cache"}],
            }
        ]

        assert ChatService._expects_diagram_tool(
            messages=messages,
            current_xml='<mxCell id="2" value="Node" vertex="1" parent="1" />',
        )


class TestToolChoiceSelection:
    def test_prefers_shape_library_before_any_diagram_tool(self):
        assert ChatService._select_tool_choice(
            step=0,
            force_diagram_tool=True,
            preferred_shape_library="aws4",
            shape_library_consulted=False,
            diagram_tool_emitted=False,
        ) == {
            "type": "function",
            "function": {"name": "get_shape_library"},
        }

    def test_requires_diagram_tool_after_library_lookup(self):
        assert ChatService._select_tool_choice(
            step=1,
            force_diagram_tool=True,
            preferred_shape_library="aws4",
            shape_library_consulted=True,
            diagram_tool_emitted=False,
        ) == "required"

    def test_returns_auto_after_diagram_tool_emitted(self):
        assert ChatService._select_tool_choice(
            step=2,
            force_diagram_tool=True,
            preferred_shape_library=None,
            shape_library_consulted=True,
            diagram_tool_emitted=True,
        ) == "auto"
