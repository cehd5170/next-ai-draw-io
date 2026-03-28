import logging

from app.middleware.request_context import (
    get_request_id,
    install_request_id_log_record_factory,
    reset_request_id,
    set_request_id,
)


def test_log_records_include_request_id(caplog):
    install_request_id_log_record_factory()
    token = set_request_id("req-test-123")
    try:
        with caplog.at_level(logging.INFO):
            logging.getLogger("app.test").info("hello world")

        assert any(record.request_id == "req-test-123" for record in caplog.records)
    finally:
        reset_request_id(token)


def test_request_id_context_defaults_to_dash():
    install_request_id_log_record_factory()
    assert get_request_id() == "-"
