import asyncio

import pytest

from ecobee.homekit import EcobeeError
from ecobee.tailnet import TailnetAuth, check_bind, is_allowed

ME = {"login": "alice@example.com", "node": "alices-laptop", "fqdn": "alices-laptop.tailnet-name.ts.net"}
GUEST = {"login": "guest@example.com", "node": "guest-phone", "fqdn": "guest-phone.tailnet-name.ts.net"}


def test_check_bind():
    check_bind("100.100.100.100")
    check_bind("fd7a:115c:a1e0::1")
    for bad in ("0.0.0.0", "::", "192.168.1.5", "127.0.0.1", "omarchy"):
        with pytest.raises(EcobeeError):
            check_bind(bad)


def test_is_allowed():
    assert is_allowed(ME, ["alice@"])
    assert is_allowed(ME, ["alice@example.com"])
    assert is_allowed(GUEST, ["guest-phone"])
    assert not is_allowed(GUEST, ["alice@", "alices-laptop"])


def request(auth, ip):
    """Send one HTTP request through the middleware; return (status, scope seen by the app)."""
    seen, sent = {}, []

    async def app(scope, receive, send):
        seen.update(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    auth.app = app
    asyncio.run(auth({"type": "http", "client": (ip, 5555)}, receive, send))
    return sent[0]["status"], seen


def make_auth(refused):
    async def lookup(ip):
        return {"100.1.1.1": ME, "100.2.2.2": GUEST}.get(ip)

    return TailnetAuth(None, ["alice@"], on_refused=lambda who, why: refused.append((who, why)), lookup=lookup)


def test_allowed_caller_reaches_app_with_identity():
    refused = []
    status, scope = request(make_auth(refused), "100.1.1.1")
    assert status == 200 and scope["state"]["caller"] == "alice@example.com on alices-laptop"
    assert refused == []


def test_unknown_tailnet_member_gets_403():
    refused = []
    status, scope = request(make_auth(refused), "100.2.2.2")
    assert status == 403 and scope == {}
    assert refused == [("guest@example.com on guest-phone", "not in [mcp] allow")]


def test_source_whois_cannot_place_gets_403():
    refused = []
    status, _ = request(make_auth(refused), "192.168.1.50")
    assert status == 403
    assert refused == [("unknown (192.168.1.50)", "not on the tailnet")]
