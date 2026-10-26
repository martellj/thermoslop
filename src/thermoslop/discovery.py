"""Find HomeKit accessories, with or without multicast.

Multicast mDNS is the normal way, but it doesn't cross NAT (a VM on a laptop)
or VLANs. Most HAP accessories also answer a plain unicast DNS-SD query sent to
port 5353, which does cross NAT, so we can scan a subnet host by host.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import asdict, dataclass

from aiohomekit.model import Categories
from aiohomekit.model.feature_flags import FeatureFlags
from aiohomekit.model.status_flags import StatusFlags
from aiohomekit.zeroconf import HomeKitService
from zeroconf import DNSIncoming, DNSOutgoing, DNSQuestion, DNSPointer, DNSService, DNSText
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf
from zeroconf.const import _CLASS_IN, _FLAGS_QR_QUERY, _TYPE_PTR, _TYPE_SRV, _TYPE_TXT

from thermoslop.text import clean

HAP_TYPE = "_hap._tcp.local."
MDNS_PORT = 5353


@dataclass
class Device:
    name: str
    id: str
    model: str
    address: str
    port: int
    config_num: int = 0
    state_num: int = 0
    feature_flags: int = 0
    status_flags: int = 0
    category: int = 1
    protocol_version: str = "1.0"

    @property
    def paired(self) -> bool:
        # Status flag bit 0 means "not paired with any controller".
        return not self.status_flags & 1

    @property
    def is_thermostat(self) -> bool:
        return self.category == Categories.THERMOSTAT

    def __post_init__(self) -> None:
        # Discovery answers are unauthenticated: clean what a device says about itself.
        for field in ("name", "id", "model", "protocol_version"):
            setattr(self, field, clean(getattr(self, field)))

    def to_service(self) -> HomeKitService:
        return HomeKitService(
            name=self.name,
            id=self.id,
            model=self.model,
            feature_flags=FeatureFlags(self.feature_flags),
            status_flags=StatusFlags(self.status_flags),
            config_num=self.config_num,
            state_num=self.state_num,
            category=Categories(self.category),
            protocol_version=self.protocol_version,
            type=HAP_TYPE,
            address=self.address,
            addresses=[self.address],
            port=self.port,
        )

    def to_dict(self) -> dict:
        return {**asdict(self), "paired": self.paired, "thermostat": self.is_thermostat}


def _device_from_txt(name: str, address: str, port: int, props: dict[str, str]) -> Device | None:
    if "id" not in props:
        return None
    return Device(
        name=name.removesuffix("." + HAP_TYPE),
        id=props["id"].lower(),
        model=props.get("md", ""),
        address=address,
        port=port,
        config_num=int(props.get("c#", 0)),
        state_num=int(props.get("s#", 0)),
        feature_flags=int(props.get("ff", 0)),
        status_flags=int(props.get("sf", 0)),
        category=int(props.get("ci", 1)),
        protocol_version=props.get("pv", "1.0"),
    )


def _parse_txt(blob: bytes) -> dict[str, str]:
    props, i = {}, 0
    while i < len(blob):
        n = blob[i]
        entry = blob[i + 1 : i + 1 + n].decode("utf-8", "replace")
        i += 1 + n
        key, _, value = entry.partition("=")
        if key:
            props[key.lower()] = value
    return props


def _query(*questions: tuple[str, int]) -> bytes:
    out = DNSOutgoing(_FLAGS_QR_QUERY)
    for name, qtype in questions:
        out.add_question(DNSQuestion(name, qtype, _CLASS_IN))
    return out.packets()[0]


class _UnicastCollector(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        # ip -> instance name -> {"port": int, "txt": dict}
        self.hosts: dict[str, dict[str, dict]] = {}

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            msg = DNSIncoming(data)
        except Exception:
            return
        instances = self.hosts.setdefault(addr[0], {})
        for rec in msg.answers():
            if isinstance(rec, DNSPointer) and rec.name.lower() == HAP_TYPE:
                instances.setdefault(rec.alias, {})
            elif isinstance(rec, DNSService):
                instances.setdefault(rec.name, {})["port"] = rec.port
            elif isinstance(rec, DNSText):
                instances.setdefault(rec.name, {})["txt"] = _parse_txt(rec.text)

    def error_received(self, exc) -> None:
        pass


async def unicast_scan(hosts: list[str], timeout: float = 3.0) -> list[Device]:
    """Ask each host directly for its HAP services."""
    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(_UnicastCollector, family=socket.AF_INET)
    try:
        ptr = _query((HAP_TYPE, _TYPE_PTR))
        for i, host in enumerate(hosts):
            transport.sendto(ptr, (host, MDNS_PORT))
            if i % 16 == 15:
                await asyncio.sleep(0.005)  # don't overrun NAT/slirp UDP buffers
        await asyncio.sleep(timeout)

        # Responders that only sent the PTR need a follow-up for SRV + TXT.
        incomplete = [
            (ip, name)
            for ip, instances in proto.hosts.items()
            for name, info in instances.items()
            if "port" not in info or "txt" not in info
        ]
        for ip, name in incomplete:
            transport.sendto(_query((name, _TYPE_SRV), (name, _TYPE_TXT)), (ip, MDNS_PORT))
        if incomplete:
            await asyncio.sleep(1.5)
    finally:
        transport.close()

    devices = []
    for ip, instances in proto.hosts.items():
        for name, info in instances.items():
            if "port" in info and "txt" in info:
                if dev := _device_from_txt(name, ip, info["port"], info["txt"]):
                    devices.append(dev)
    return devices


async def multicast_scan(timeout: float = 3.0) -> list[Device]:
    found: dict[str, Device] = {}
    tasks: set[asyncio.Task] = set()

    async with AsyncZeroconf() as azc:

        async def resolve(name: str) -> None:
            info = AsyncServiceInfo(HAP_TYPE, name)
            if not await info.async_request(azc.zeroconf, 2000):
                return
            try:
                svc = HomeKitService.from_service_info(info)
            except ValueError:
                return
            found[svc.id] = Device(
                name=svc.name,
                id=svc.id,
                model=svc.model,
                address=svc.address,
                port=svc.port,
                config_num=svc.config_num,
                state_num=svc.state_num,
                feature_flags=int(svc.feature_flags),
                status_flags=int(svc.status_flags),
                category=int(svc.category),
                protocol_version=svc.protocol_version,
            )

        def on_change(zeroconf, service_type, name, state_change) -> None:
            task = asyncio.ensure_future(resolve(name))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        browser = AsyncServiceBrowser(azc.zeroconf, [HAP_TYPE], handlers=[on_change])
        await asyncio.sleep(timeout)
        await browser.async_cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=2.5)
    return list(found.values())


def expand_subnets(subnets: list[str]) -> list[str]:
    hosts: list[str] = []
    for net in subnets:
        hosts.extend(str(h) for h in ipaddress.ip_network(net, strict=False).hosts())
    return hosts


async def discover(subnets: list[str], timeout: float = 3.0) -> list[Device]:
    """Multicast and unicast scans in parallel, merged by device id."""
    jobs = [multicast_scan(timeout)]
    if subnets:
        jobs.append(unicast_scan(expand_subnets(subnets), timeout))
    results = await asyncio.gather(*jobs, return_exceptions=True)
    merged: dict[str, Device] = {}
    for result in results:
        if isinstance(result, BaseException):
            continue
        for dev in result:
            merged.setdefault(dev.id, dev)
    return sorted(merged.values(), key=lambda d: d.name.lower())


async def locate(device_id: str, last_address: str | None, subnets: list[str]) -> Device | None:
    """Find a known device again, e.g. after its IP or HAP port changed."""
    device_id = device_id.lower()
    if last_address:
        for dev in await unicast_scan([last_address], timeout=1.5):
            if dev.id == device_id:
                return dev
    for dev in await discover(subnets):
        if dev.id == device_id:
            return dev
    return None


def choose(devices: list[Device], wanted: str) -> Device:
    """The device `wanted` names: a device id, then an address, then a unique name.

    Names aren't unique (two houses can each have a "Main Floor"), so an
    ambiguous name is an error that lists the candidates to pick by id.
    """
    from thermoslop.homekit import ThermoSlopError, slugify

    for match in (lambda d: d.id.lower() == wanted.lower(), lambda d: d.address == wanted):
        found = [d for d in devices if match(d)]
        if found:
            return found[0]
    named = [d for d in devices if slugify(d.name) == slugify(wanted)]
    if len(named) == 1:
        return named[0]
    if not named:
        raise ThermoSlopError(f"no device named {wanted!r} found; run `thermoslop discover`")
    listing = "; ".join(f"{d.name} (id {d.id}, {d.address})" for d in named)
    raise ThermoSlopError(f"{len(named)} devices are named {wanted!r}: {listing}. Pair by id instead.")
