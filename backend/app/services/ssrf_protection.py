"""
SSRF (Server-Side Request Forgery) protection utilities.

Ported from lib/ssrf-protection.ts.  Checks whether a URL points to a
private or internal network address and optionally raises if private URLs
are not permitted.
"""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blocked hostnames (exact match)
# ---------------------------------------------------------------------------

_BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        # AWS / cloud metadata endpoints
        "169.254.169.254",
        "metadata.google.internal",
    }
)

# ---------------------------------------------------------------------------
# Blocked TLD suffixes
# ---------------------------------------------------------------------------

_BLOCKED_SUFFIXES: tuple[str, ...] = (".local", ".internal", ".localhost")


def is_private_url(url: str) -> bool:
    """
    Return True if *url* points to a private or internal network resource.

    Blocked addresses / ranges:
    - ``localhost``, ``127.x.x.x`` (loopback)
    - ``::1`` (IPv6 loopback)
    - ``169.254.169.254``, ``metadata.google.internal`` (cloud metadata)
    - ``10.0.0.0/8`` (private class A)
    - ``172.16.0.0/12`` (private class B)
    - ``192.168.0.0/16`` (private class C)
    - ``169.254.0.0/16`` (link-local)
    - Hostnames ending in ``.local``, ``.internal``, or ``.localhost``

    Invalid or unparseable URLs are treated as private (blocked) to fail
    safe.
    """
    if not url:
        return True

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
    except Exception:  # noqa: BLE001
        return True  # Invalid URL — block it.

    if not hostname:
        return True

    # Exact hostname matches.
    if hostname in _BLOCKED_HOSTNAMES:
        return True

    # TLD suffix matches.
    if any(hostname.endswith(suffix) for suffix in _BLOCKED_SUFFIXES):
        return True

    # IPv4 range checks.
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # Not a bare IP address — hostname-only, already covered above.
        return False

    if isinstance(addr, ipaddress.IPv4Address):
        private_networks = [
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("169.254.0.0/16"),  # link-local
            ipaddress.ip_network("127.0.0.0/8"),     # loopback
        ]
        return any(addr in network for network in private_networks)

    if isinstance(addr, ipaddress.IPv6Address):
        # Block loopback and link-local IPv6.
        return addr.is_loopback or addr.is_link_local or addr.is_private

    return False


def validate_url(url: str, allow_private: bool = True) -> str:
    """
    Validate *url* and return it unchanged if it passes all checks.

    Raises ``ValueError`` when:
    - ``allow_private`` is False **and** the URL resolves to a private
      address (SSRF protection).

    The URL itself is not fetched; only the hostname / IP is inspected.
    """
    if not allow_private and is_private_url(url):
        raise ValueError(
            f"URL '{url}' points to a private or internal address and is not allowed."
        )
    return url
