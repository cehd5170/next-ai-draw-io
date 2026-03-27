from app.services.chat_service import ChatService


class TestMissingDiagramRetryHeuristic:
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
