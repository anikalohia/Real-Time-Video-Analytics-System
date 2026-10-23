import ipaddress
from urllib.parse import urlparse
from typing import Optional

ALLOWED_SCHEMES = {"rtsp", "rtmp", "file"}
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".mjpg", ".webm"}
BLOCKED_HOSTS = {"localhost", "0.0.0.0", "metadata.google.internal"}


def _is_private_host(host: str) -> bool:
    if host in BLOCKED_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return False


def validate_stream_url(url: str) -> bool:
    """Validate a stream source URL. Allows rtsp/rtmp/file schemes and local file paths,
    blocks SSRF targets (private/loopback/link-local hosts)."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    parsed = urlparse(url)

    # bare file path or file:// URL
    if parsed.scheme in ("", "file"):
        if "://" in url:
            path = parsed.path
        else:
            path = url
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        return ext in ALLOWED_EXTENSIONS

    if parsed.scheme not in ALLOWED_SCHEMES:
        return False

    host = parsed.hostname or ""
    if not host:
        return False
    if _is_private_host(host):
        return False
    return True
