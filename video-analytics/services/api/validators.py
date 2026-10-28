import ipaddress
import os
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {'rtsp', 'rtmp', 'file'}
ALLOWED_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov', '.mjpg', '.webm'}
BLOCKED_HOSTS = {'localhost', '0.0.0.0', 'metadata.google.internal'}


def _allowed_private_hosts() -> set[str]:
    return {h.strip().lower() for h in os.getenv('ALLOW_PRIVATE_HOSTS', '').split(',') if h.strip()}


def _is_private_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _is_private_host(host: str) -> bool:
    host = host.strip('[]').lower()
    if host in BLOCKED_HOSTS:
        return True
    if _is_private_ip(host):
        return True
    # Resolve DNS names too, otherwise a public name can point at 127.0.0.1.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Unresolvable URLs will fail at connection time anyway.
        return False
    return any(_is_private_ip(info[4][0]) for info in infos)


def _host_allowed(host: str) -> bool:
    allowed = _allowed_private_hosts()
    return '*' in allowed or host.strip('[]').lower() in allowed


def _validate_file(path: str) -> bool:
    if '..' in path:
        return False
    ext = '.' + path.rsplit('.', 1)[-1].lower() if '.' in path else ''
    return ext in ALLOWED_EXTENSIONS


def validate_stream_url(url: str) -> bool:
    """Validate a stream source URL.

    Allows rtsp/rtmp/file schemes and local file paths, and blocks private,
    loopback and link-local targets unless ALLOW_PRIVATE_HOSTS explicitly
    allow-lists the hostname (e.g. mediamtx for the bundled demo).
    """
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme in ('', 'file'):
        path = parsed.path if '://' in url else url
        return _validate_file(path)

    if parsed.scheme not in ALLOWED_SCHEMES:
        return False

    host = parsed.hostname or ''
    if not host:
        return False
    if _host_allowed(host):
        return True
    return not _is_private_host(host)


def validate_webhook_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url.strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return False
    if _host_allowed(parsed.hostname):
        return True
    return not _is_private_host(parsed.hostname)
