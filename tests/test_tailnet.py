import asyncio

import pytest

from thermoslop.homekit import ThermoSlopError
from thermoslop.tailnet import TailnetAuth, check_bind, is_allowed

ME = {"login": "alice@example.com", "node": "alices-laptop", "fqdn": "alices-laptop.tailnet-name.ts.net", "stable_id": "nLAPTOP1CNTRL"}
GUEST = {"login": "guest@example.com", "node": "guest-phone", "fqdn": "guest-phone.tailnet-name.ts.net", "stable_id": "nPHONE1CNTRL"}


def test_check_bind():
    check_bind("100.100.100.100")
    check_bind("fd7a:115c:a1e0::1")
    for bad in ("0.0.0.0", "::", "192.168.1.5", "127.0.0.1", "omarchy"):
        with pytest.raises(ThermoSlopError):
            check_bind(bad)


def test_is_allowed():
    assert is_allowed(ME, ["alice@example.com"])
    assert not is_allowed({**ME, "login": "alice@evil.example"}, ["alice@example.com"])
    # One device: by stable id, and only while its owner matches.
    assert is_allowed(GUEST, ["node:nPHONE1CNTRL@guest@example.com"])
    assert not is_allowed({**GUEST, "login": "mallory@example.com"}, ["node:nPHONE1CNTRL@guest@example.com"])
    # Renaming doesn't move access: names aren't identities.
    assert not is_allowed({**GUEST, "node": "alices-laptop"}, ["alice@example.com", "node:nLAPTOP1CNTRL@alice@example.com"])
    assert is_allowed({**ME, "node": "renamed"}, ["node:nLAPTOP1CNTRL@alice@example.com"])


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

    return TailnetAuth(None, ["alice@example.com"], on_refused=lambda who, why: refused.append((who, why)), lookup=lookup)


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


def test_cached_identity_expires_and_failure_is_not_cached():
    answers = [ME, None, ME]

    async def lookup(ip):
        return answers.pop(0)

    refused = []
    auth = TailnetAuth(None, ["alice@example.com"], on_refused=lambda who, why: refused.append(why), lookup=lookup, ttl=0)
    assert request(auth, "100.1.1.1")[0] == 200
    assert request(auth, "100.1.1.1")[0] == 403  # tailscaled gone: the earlier success isn't reused
    assert request(auth, "100.1.1.1")[0] == 200  # and the failure wasn't cached either
    assert refused == ["not on the tailnet"]
