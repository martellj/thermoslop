"""`thermoslop mcp`: the thermostats as MCP tools for AI clients.

stdio by default (the client launches it), or streamable HTTP on this
machine's Tailscale addresses with `--http`. Reads behave like `thermoslop status`.
Every change goes through the guardrails in guard.py and lands in the audit log.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from thermoslop import APP, ops
from thermoslop.audit import snapshot
from thermoslop.guard import Guard, Refused
from thermoslop.homekit import COMFORT, ThermoSlopError, Home, read_cache

log = logging.getLogger(__name__)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
NUDGE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

Thermostat = Annotated[
    str | None, Field(description="Thermostat alias or name prefix, e.g. 'upstairs'. See list_thermostats.")
]
House = Annotated[str | None, Field(description="Only thermostats in this house, e.g. 'cabin'.")]


def caller_of(ctx: Context) -> str:
    """Who's calling: `user@ on node` over the tailnet, `local:<client>` over stdio."""
    request = ctx.request_context.request
    caller = getattr(getattr(request, "state", None), "caller", None)
    if caller:
        return caller
    params = ctx.request_context.session.client_params
    return f"local:{params.client_info.name}" if params else "local"


class ThermostatServer:
    def __init__(self, home: Home, guard: Guard, read_only: bool = False) -> None:
        self.home = home
        self.guard = guard
        self.read_only = read_only
        self._locks: dict[str, asyncio.Lock] = {}
        self.units = home.config.units or self._cached_units()
        self.mcp = MCPServer(APP, instructions=self._instructions())
        self._register()

    def _cached_units(self) -> str:
        units = {s.get("units") for s in read_cache().get("thermostats", {}).values() if s.get("units")}
        return units.pop() if len(units) == 1 else "F"

    def _limits(self) -> str:
        low, high = self.guard.limits(self.units)
        return f"{low:g}–{high:g}°{self.units}"

    def _instructions(self) -> str:
        houses = ", ".join(self.home.config.houses) or "one house"
        text = (
            f"Local control of HomeKit ecobee thermostats ({houses}). Temperatures are in °{self.units}. "
            "Call list_thermostats or get_status first to learn aliases and houses. "
        )
        if self.read_only:
            return text + "This server is read-only."
        return text + (
            f"Allowed setpoints: {self._limits()}. Changes are rate-limited and logged; "
            "relay any refusal to the user rather than retrying."
        )

    # -- plumbing --

    async def _change(self, ctx: Context, tool: str, args: dict, pick, action) -> Any:
        """Run one guarded change: resolve targets, rate check, per-thermostat locks, audit before/after.

        `pick()` returns the aliases to change; `action(aliases)` makes the change.
        """
        caller = caller_of(ctx)
        aliases: list[str] = []
        try:
            aliases = pick()
            self.guard.check_rate(len(aliases))
            before = {s["alias"]: snapshot(s) for s in await ops.status(self.home, house=None) if s["alias"] in aliases}
            async with AsyncExitStack() as stack:
                for alias in sorted(aliases):
                    await stack.enter_async_context(self._locks.setdefault(alias, asyncio.Lock()))
                result = await action(aliases)
        except Refused as e:
            self.guard.record(tool, args, caller, "refused", aliases, error=str(e))
            raise ToolError(f"Refused: {e}") from None
        except ThermoSlopError as e:
            self.guard.record(tool, args, caller, "failed", aliases, error=str(e))
            raise ToolError(str(e)) from None
        states = result if isinstance(result, list) else [result]
        states = [s.get("state", s) for s in states]
        after = {s["alias"]: snapshot(s) for s in states}
        self.guard.record(tool, args, caller, "ok", aliases, before, after)
        return result

    def _pick(self, thermostat: str | None, house: str | None, *, single: bool):
        def pick() -> list[str]:
            try:
                return self.home.pick(thermostat, house, single=single)
            except ThermoSlopError as e:
                raise ThermoSlopError(str(e).replace("with -t", "with the `thermostat` argument")) from None

        return pick

    async def _verified(self, requested: str, states: list[dict]) -> list[dict]:
        """Some models (ecobee3 lite) accept comfort writes but ignore them."""
        def applied(state: dict) -> bool:
            reported = state.get("comfort")
            return reported in COMFORT.values() if requested == "schedule" else reported == requested

        return [
            {"alias": s["alias"], "requested": requested, "reported": s.get("comfort"), "applied": applied(s), "state": s}
            for s in states
        ]

    # -- tools --

    def _register(self) -> None:
        mcp, home, guard = self.mcp, self.home, self.guard
        units = self.units

        @mcp.tool(annotations=READ)
        async def list_thermostats(house: House = None) -> list[dict]:
            """List paired thermostats: alias, name, house, and whether the last reading succeeded."""
            try:
                return ops.list_thermostats(home, house)
            except ThermoSlopError as e:
                raise ToolError(str(e)) from None

        @mcp.tool(annotations=READ)
        async def get_status(
            thermostat: Thermostat = None,
            house: House = None,
            live: Annotated[bool, Field(description="Ask the thermostats instead of using the recent cached reading.")] = False,
        ) -> list[dict]:
            """Current temperature, humidity, HVAC mode and action, setpoints, comfort setting
            (home/away/sleep, or 'hold' for a manual hold) and remote sensors.
            With no arguments, covers every thermostat."""
            try:
                return await ops.status(home, thermostat, house, live=live)
            except ThermoSlopError as e:
                raise ToolError(str(e)) from None

        if self.read_only:
            return

        @mcp.tool(annotations=WRITE, description=(
            f"Set an absolute setpoint, in °{units}. In heat or cool mode use `target`; in auto mode use "
            f"`heat` and/or `cool`. Allowed range: {self._limits()}. Creates a hold, like changing it on the "
            "thermostat; resume_schedule clears it."
        ))
        async def set_temperature(
            thermostat: Thermostat = None,
            house: House = None,
            target: float | None = None,
            heat: float | None = None,
            cool: float | None = None,
            ctx: Context = None,
        ) -> dict:
            args = {"thermostat": thermostat, "house": house, "target": target, "heat": heat, "cool": cool}
            pick = self._pick(thermostat, house, single=True)
            return await self._change(ctx, "set_temperature", args, pick, lambda aliases: home.set_temperature(
                aliases[0], target, heat=heat, cool=cool, check=guard.check_setpoints
            ))

        @mcp.tool(annotations=NUDGE, description=(
            f"Raise or lower the setpoint by `delta` °{units} (−5 to +5). In auto mode both setpoints move. "
            f"The result must stay within {self._limits()}."
        ))
        async def adjust_temperature(
            delta: Annotated[float, Field(ge=-5, le=5)],
            thermostat: Thermostat = None,
            house: House = None,
            ctx: Context = None,
        ) -> dict:
            args = {"thermostat": thermostat, "house": house, "delta": delta}
            pick = self._pick(thermostat, house, single=True)
            return await self._change(ctx, "adjust_temperature", args, pick, lambda aliases: home.set_temperature(
                aliases[0], delta, relative=True, check=guard.check_setpoints
            ))

        @mcp.tool(annotations=WRITE, description=(
            "Set the HVAC mode." + ("" if guard.config.allow_off else " 'off' is disabled on this server.")
        ))
        async def set_mode(
            mode: Literal["heat", "cool", "auto", "off"],
            thermostat: Thermostat = None,
            house: House = None,
            ctx: Context = None,
        ) -> dict:
            args = {"thermostat": thermostat, "house": house, "mode": mode}

            async def action(aliases):
                guard.check_mode(mode)
                return await home.set_mode(aliases[0], mode)

            return await self._change(ctx, "set_mode", args, self._pick(thermostat, house, single=True), action)

        @mcp.tool(annotations=WRITE)
        async def set_comfort(
            comfort: Literal["home", "away", "sleep"],
            thermostat: Thermostat = None,
            house: House = None,
            ctx: Context = None,
        ) -> list[dict]:
            """Hold a comfort setting until resume_schedule. With `house`, applies to every thermostat
            there. Reports per thermostat whether it took effect: some models (ecobee3 lite) ignore it."""
            args = {"thermostat": thermostat, "house": house, "comfort": comfort}

            async def action(aliases):
                return await self._verified(comfort, [await home.set_comfort(a, comfort) for a in aliases])

            return await self._change(ctx, "set_comfort", args, self._pick(thermostat, house, single=not house), action)

        @mcp.tool(annotations=WRITE)
        async def resume_schedule(thermostat: Thermostat = None, house: House = None, ctx: Context = None) -> list[dict]:
            """Clear holds (setpoint or comfort) and return to the thermostat's schedule. With `house`,
            applies to every thermostat there. Reports per thermostat whether the schedule took over."""
            args = {"thermostat": thermostat, "house": house}

            async def action(aliases):
                return await self._verified("schedule", [await home.resume(a) for a in aliases])

            return await self._change(ctx, "resume_schedule", args, self._pick(thermostat, house, single=not house), action)


async def serve_stdio(config, read_only: bool) -> None:
    async with Home(config) as home:
        server = ThermostatServer(home, Guard(config.mcp), read_only=read_only or config.mcp.read_only)
        await server.mcp.run_stdio_async()


async def serve_http(config, read_only: bool, bind: str | None, port: int | None) -> None:
    """Streamable HTTP on a Tailscale address, for MCP clients elsewhere on the tailnet."""
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    from thermoslop import tailnet

    addresses = [bind] if bind else await tailnet.tailscale_ips()
    for address in addresses:
        tailnet.check_bind(address)
    port = port or config.mcp.http_port
    me = await tailnet.whois(addresses[0])
    allow = config.mcp.allow or ([me["login"]] if me else [])
    if not allow:
        raise ThermoSlopError("can't tell who owns this node; set `allow` under [mcp]")
    # Only requests addressed to this node's tailnet names, so a web page can't
    # reach the server by rebinding its own domain to this address.
    hosts = [tailnet.host_header(a, port) for a in addresses]
    if me:
        hosts += [f"{me['node']}:{port}", f"{me['fqdn']}:{port}"]
    security = TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[])

    async with Home(config) as home:
        guard = Guard(config.mcp)
        server = ThermostatServer(home, guard, read_only=read_only or config.mcp.read_only)
        app = tailnet.TailnetAuth(
            server.mcp.streamable_http_app(transport_security=security, host=addresses[0]),
            allow,
            on_refused=lambda who, reason: guard.record("http", {}, who, "refused", error=reason),
        )
        url = f"http://{me['fqdn'] if me else tailnet.host_header(addresses[0], port).rsplit(':', 1)[0]}:{port}/mcp"
        log.warning("serving MCP on %s (%s) for %s", url, ", ".join(addresses), ", ".join(allow))
        sockets = tailnet.listen(addresses, port)
        await uvicorn.Server(uvicorn.Config(app, log_level="warning")).serve(sockets=sockets)
