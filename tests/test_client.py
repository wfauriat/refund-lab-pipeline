from unittest.mock import Mock
import pytest
import time
import base64
import json

from refund_lab.client import (fetch_page_with_retry, decode_cursor,
                                classify_response)
from refund_lab.client import RetryableAuth, RetryableBackoff

def test_fetch_page_with_retry_recovers_from_429(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    resp_429 = Mock(status_code=429, headers={}, text={})
    resp_200 = Mock(status_code=200)
    mock_payload = {"cursor":None, "next_cursor":None,
                    "as_of":None, "total_count":5}
    resp_200.json.return_value = mock_payload
    fake_client = Mock()
    fake_client.get = Mock(side_effect=[resp_429, resp_200])
    payload = fetch_page_with_retry(fake_client, "orders", None)
    assert payload == resp_200.json.return_value
    assert fake_client.get.call_count == 2


def test_decode_cursor_maps_to_correct_dict():
    # Arrange
    raw = {"a": "2026-01-15T00:00:00", "n": 5, "r": 10,
         "v": "2026-01-15T05:00:00", "t": "orders",
         "s": "2026-01-01T00:00:00", "u": "2026-01-31T00:00:00"}
    cursor_str = base64.b64encode(json.dumps(raw).encode()).decode()
    # Act
    cursor_dict = decode_cursor(cursor_str)
    # Assert
    assert cursor_dict is not None
    assert cursor_dict["as_of"] == "2026-01-15T00:00:00"
    assert cursor_dict["total_count"] == 5
    assert cursor_dict["rows_served"] == 10
    assert cursor_dict["last_seen_value"] == "2026-01-15T05:00:00"
    assert cursor_dict["since"] == "2026-01-01T00:00:00"
    assert cursor_dict["until"] == "2026-01-31T00:00:00"


def test_classify_response_raises_on_401():
    resp = Mock(status_code=401)
    with pytest.raises(RetryableAuth):
        classify_response(resp)

def test_classify_response_raises_on_429():
    resp = Mock(status_code=429, headers={"retry-after":0.1})
    with pytest.raises(RetryableBackoff) as exc_info: 
        classify_response(resp)
    assert exc_info.value.retry_after == 0.1