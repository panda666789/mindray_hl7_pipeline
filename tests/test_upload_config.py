"""Tests for upload configuration safety helpers."""

import sys
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parents[1] / "apps" / "client"
sys.path.insert(0, str(CLIENT_DIR))

from upload_config import validate_upload_enabled


def test_upload_disabled_by_default_blocks_manual_start():
    ok, message = validate_upload_enabled({"upload": {"enabled": False, "base_url": "http://example.test:10000"}})

    assert ok is False
    assert "upload.enabled=false" in message


def test_upload_requires_base_url_when_enabled():
    ok, message = validate_upload_enabled({"upload": {"enabled": True, "base_url": ""}})

    assert ok is False
    assert "upload.base_url" in message


def test_upload_enabled_with_base_url_can_start():
    ok, message = validate_upload_enabled({"upload": {"enabled": True, "base_url": "http://example.test:10000"}})

    assert ok is True
    assert message == ""
