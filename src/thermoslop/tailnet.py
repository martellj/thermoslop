"""Serving MCP over HTTP to the tailnet only.

The listener binds to this machine's Tailscale address, and every request is
attributed to a tailnet user and node with `tailscale whois` and checked
against `[mcp] allow`. The tailnet has already authenticated the device, so
there are no tokens to manage. Anything whois can't place is refused.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
import time
from collections.abc import Awaitable, Callable

from thermoslop.homekit import ThermoSlopError

log = logging.getLogger(__name__)

TAILNET = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
# A successful lookup is trusted this long; failures are never cached. Within it,
# a device removed from the tailnet can still be served (SECURITY.md says so).
WHOIS_TTL = 30


def check_bind(address: str) -> None:
    """Refuse anything but a single tailnet address: no wildcards, no LAN or public IPs."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        raise ThermoSlopError(f"--bind needs a Tailscale IP address, not {address!r}") from None
    if not any(ip in net for net in TAILNET):
        raise ThermoSlopError(f"refusing to listen on {address}: only Tailscale addresses (100.64.0.0/10, fd7a:115c:a1e0::/48)")


async def _tailscale(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "tailscale", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode()


async def tailscale_ips() -> list[str]:
    """This machine's Tailscale addresses, IPv4 first."""
    code, out = await _tailscale("ip")
    if code != 0 or not out.split():
        raise ThermoSlopError("can't get this machine's Tailscale address (is tailscaled running and logged in?)")
    return out.split()


def listen(addresses: list[str], port: int) -> list[socket.socket]:
    sockets = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((address, port))
        sockets.append(sock)
    return sockets


def host_header(address: str, port: int) -> str:
    return f"[{address}]:{port}" if ":" in address else f"{address}:{port}"


async def whois(ip: str) -> dict | None:
    """{"login": ..., "node": ..., "fqdn": ...} for a tailnet address, or None."""
    code, out = await _tailscale("whois", "--json", ip)
    if code != 0:
        return None
    try:
        data = json.loads(out)
        return {
            "login": data["UserProfile"]["LoginName"],
            "node": data["Node"].get("ComputedName") or data["Node"]["Name"].split(".")[0],
            "fqdn": data["Node"]["Name"].rstrip("."),
            "stable_id": data["Node"].get("StableID", ""),
        }
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def is_allowed(identity: dict, allow: list[str]) -> bool:
    """`allow` entries: an exact login ("alice@example.com"), or one device as
    "node:<StableID>@<owner login>". Names and prefixes aren't identities:
    machines can be renamed, and a prefix like "alice@" matches other domains."""
    for entry in allow:
        if entry.startswith("node:"):
            node, _, login = entry[5:].partition("@")
            if identity.get("stable_id") == node and identity["login"] == login:
                return True
        elif identity["login"] == entry:
            return True
    return False


def caller_name(identity: dict) -> str:
    return f"{identity['login']} on {identity['node']}"


class TailnetAuth:
    """ASGI middleware: 403 unless whois places the peer in `allow`.

    Sets `scope["state"]["caller"]`, which the tools read for the audit log.
    """

    def __init__(
        self,
        app,
        allow: list[str],
        on_refused: Callable[[str, str], None],
        lookup: Callable[[str], Awaitable[dict | None]] = whois,
        ttl: float = WHOIS_TTL,
    ) -> None:
        self.app = app
        self.allow = allow
        self.on_refused = on_refused
        self.lookup = lookup
        self.ttl = ttl
        self._cache: dict[str, tuple[float, dict | None]] = {}

    async def _identity(self, ip: str) -> dict | None:
        now = time.monotonic()
        hit = self._cache.get(ip)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        identity = await self.lookup(ip)
        if identity is None:
            self._cache.pop(ip, None)  # fail closed, and ask again next time
        else:
            self._cache[ip] = (now, identity)
        return identity

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        ip = (scope.get("client") or ("", 0))[0]
        identity = await self._identity(ip) if ip else None
        if identity is None or not is_allowed(identity, self.allow):
            who = caller_name(identity) if identity else f"unknown ({ip or 'no address'})"
            reason = "not on the tailnet" if identity is None else "not in [mcp] allow"
            log.warning("refused HTTP request from %s: %s", who, reason)
            self.on_refused(who, reason)
            await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": f"forbidden: {reason}\n".encode()})
            return
        scope.setdefault("state", {})["caller"] = caller_name(identity)
        await self.app(scope, receive, send)
