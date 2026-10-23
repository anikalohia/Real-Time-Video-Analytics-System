import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from validators import validate_stream_url


def test_validate_rtsp_ok():
    assert validate_stream_url("rtsp://example.com/stream") is True


def test_validate_file_ok():
    assert validate_stream_url("sample.mp4") is True
    assert validate_stream_url("/samples/test.mp4") is True


def test_validate_disallow_http_ssrf():
    # http not in allowlist
    assert validate_stream_url("http://169.254.169.254/latest/meta-data") is False


def test_validate_disallow_localhost():
    assert validate_stream_url("rtsp://127.0.0.1:8554/stream") is False
    assert validate_stream_url("rtsp://localhost/stream") is False


def test_validate_disallow_bad_scheme():
    assert validate_stream_url("javascript:alert(1)") is False
    assert validate_stream_url("") is False
