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

from thermoslop import APP, __version__, ops
from thermoslop.audit import snapshot
from thermoslop.guard import Guard, Refused
from thermoslop.homekit import COMFORT, Home, ThermoSlopError, Unconfirmed

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


Unit = Annotated[
    Literal["F", "C"] | None,
    Field(description="Unit of the temperatures in this call; defaults to the server's (see the description)."),
]


class ThermostatServer:
    def __init__(self, home: Home, guard: Guard, read_only: bool = False) -> None:
        self.home = home
        self.guard = guard
        self.read_only = read_only
        self._locks: dict[str, asyncio.Lock] = {}
        # The unit tool arguments are in when a call doesn't say: fixed by config,
        # never guessed from whichever thermostats happen to be in the cache.
        self.units = guard.config.units or home.config.units or "F"
        self.mcp = MCPServer(APP, version=__version__, instructions=self._instructions())
        self._register()

    def _limits(self) -> str:
        low, high = self.guard.limits(self.units)
        return f"{low:g}–{high:g}°{self.units}"

    def _instructions(self) -> str:
        houses = ", ".join(self.home.config.houses) or "one house"
        text = (
            f"Local control of HomeKit ecobee thermostats ({houses}). Temperatures you pass are in °{self.units} "
            "unless a call sets `unit`; readings come back in each thermostat's own units (its `units` field). "
            "Call list_thermostats or get_status first to learn aliases and houses. "
        )
        if self.read_only:
            return text + "This server is read-only."
        return text + (
            f"Allowed setpoints: {self._limits()}. Changes are rate-limited and logged; "
            "relay any refusal to the user rather than retrying."
        )

    # -- plumbing --

    def _resolve(self, ctx: Context, tool: str, args: dict, pick) -> list[str]:
        """Resolve targets; a failure is logged like any refused change."""
        try:
            return pick()
        except ThermoSlopError as e:
            self.guard.record(tool, args, caller_of(ctx), "failed", error=str(e))
            raise ToolError(str(e)) from None

    async def _change(self, ctx: Context, tool: str, args: dict, aliases: list[str], action, precheck=None) -> Any:
        """Run one guarded change: reserve quota, lock the thermostats, log before/after.

        The quota is reserved before anything slow happens, under a lock shared
        with every other ThermoSlop process, so concurrent calls can't both slip
        under the limit. It's given back only if nothing was written.
        """
        caller = caller_of(ctx)
        token = None
        try:
            if precheck:
                precheck()
            token = self.guard.reserve(len(aliases))
            before = {s["alias"]: snapshot(s) for s in await ops.status(self.home, house=None) if s["alias"] in aliases}
            async with AsyncExitStack() as stack:
                for alias in sorted(aliases):
                    await stack.enter_async_context(self._locks.setdefault(alias, asyncio.Lock()))
                result = await action(aliases)
        except Refused as e:
            self.guard.record(tool, args, caller, "refused", aliases, error=str(e), reservation=token)
            raise ToolError(f"Refused: {e}") from None
        except Unconfirmed as e:
            self.guard.record(tool, args, caller, "uncertain", aliases, error=str(e), reservation=token)
            raise ToolError(str(e)) from None
        except ThermoSlopError as e:
            self.guard.record(tool, args, caller, "failed", aliases, error=str(e), reservation=token)
            raise ToolError(str(e)) from None
        except Exception as e:
            # Something broke mid-write (a dropped connection, a timeout): it may
            # or may not have changed, so it keeps its quota.
            self.guard.record(tool, args, caller, "uncertain", aliases, error=f"{e.__class__.__name__}: {e}",
                              reservation=token)
            raise ToolError(f"{', '.join(aliases)}: outcome unknown ({e.__class__.__name__}: {e})") from None
        states = result if isinstance(result, list) else [result]
        states = [s.get("state", s) for s in states]
        after = {s["alias"]: snapshot(s) for s in states}
        outcome = "unconfirmed" if any(s.get("confirmed") is False for s in states) else "ok"
        self.guard.record(tool, args, caller, outcome, aliases, before, after, reservation=token)
        return result

    async def _each(self, ctx: Context, tool: str, args: dict, aliases: list[str], change) -> list[dict]:
        """Change several thermostats one at a time: each is reserved, logged and
        reported on its own, so one failure doesn't hide changes already made."""
        results, errors = [], []
        for alias in aliases:
            try:
                results.append(await self._change(ctx, tool, args, [alias], lambda a, alias=alias: change(alias)))
            except ToolError as e:
                results.append({"alias": alias, "error": str(e)})
                errors.append(str(e))
        if errors and len(errors) == len(aliases):
            raise ToolError("; ".join(errors))
        return results

    def _pick(self, thermostat: str | None, house: str | None, *, single: bool):
        def pick() -> list[str]:
            try:
                return self.home.pick(thermostat, house, single=single)
            except ThermoSlopError as e:
                raise ThermoSlopError(str(e).replace("with -t", "with the `thermostat` argument")) from None

        return pick

    @staticmethod
    def _verified(requested: str, state: dict) -> dict:
        """Some models (ecobee3 lite) accept comfort writes but ignore them."""
        reported = state.get("comfort")
        applied = reported in COMFORT.values() if requested == "schedule" else reported == requested
        return {"alias": state["alias"], "requested": requested, "reported": reported, "applied": applied, "state": state}

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
            (home/away/sleep, or 'hold' for a manual hold) and remote sensors, in each thermostat's
            own units (`units`). With no arguments, covers every thermostat."""
            try:
                return await ops.status(home, thermostat, house, live=live)
            except ThermoSlopError as e:
                raise ToolError(str(e)) from None

        if self.read_only:
            return

        @mcp.tool(annotations=WRITE, description=(
            f"Set an absolute setpoint, in °{units} unless `unit` says otherwise. In heat or cool mode use "
            f"`target`; in auto mode use `heat` and/or `cool`. Allowed range: {self._limits()}. Creates a hold, "
            "like changing it on the thermostat; resume_schedule clears it."
        ))
        async def set_temperature(
            thermostat: Thermostat = None,
            house: House = None,
            target: float | None = None,
            heat: float | None = None,
            cool: float | None = None,
            unit: Unit = None,
            ctx: Context = None,
        ) -> dict:
            args = {"thermostat": thermostat, "house": house, "target": target, "heat": heat, "cool": cool,
                    "unit": unit or units}
            aliases = self._resolve(ctx, "set_temperature", args, self._pick(thermostat, house, single=True))
            return await self._change(ctx, "set_temperature", args, aliases, lambda a: home.set_temperature(
                a[0], target, heat=heat, cool=cool, check=guard.check_setpoints, unit=unit or units
            ))

        @mcp.tool(annotations=NUDGE, description=(
            f"Raise or lower the setpoint by `delta` degrees ({units} unless `unit` says otherwise; at most 5). "
            f"In auto mode both setpoints move. The result must stay within {self._limits()}."
        ))
        async def adjust_temperature(
            delta: Annotated[float, Field(ge=-5, le=5)],
            thermostat: Thermostat = None,
            house: House = None,
            unit: Unit = None,
            ctx: Context = None,
        ) -> dict:
            args = {"thermostat": thermostat, "house": house, "delta": delta, "unit": unit or units}
            aliases = self._resolve(ctx, "adjust_temperature", args, self._pick(thermostat, house, single=True))
            return await self._change(ctx, "adjust_temperature", args, aliases, lambda a: home.set_temperature(
                a[0], delta, relative=True, check=guard.check_setpoints, unit=unit or units
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
            aliases = self._resolve(ctx, "set_mode", args, self._pick(thermostat, house, single=True))
            return await self._change(ctx, "set_mode", args, aliases, lambda a: home.set_mode(a[0], mode),
                                      precheck=lambda: guard.check_mode(mode))

        @mcp.tool(annotations=WRITE)
        async def set_comfort(
            comfort: Literal["home", "away", "sleep"],
            thermostat: Thermostat = None,
            house: House = None,
            ctx: Context = None,
        ) -> list[dict]:
            """Hold a comfort setting until resume_schedule. With `house`, applies to every thermostat
            there, each reported on its own (`error` for one that failed). Reports whether it took effect:
            some models (ecobee3 lite) ignore it. The comfort setting's temperatures are the thermostat's
            own presets, which this server's setpoint limits don't cover."""
            args = {"thermostat": thermostat, "house": house, "comfort": comfort}
            aliases = self._resolve(ctx, "set_comfort", args, self._pick(thermostat, house, single=not house))

            async def change(alias):
                return self._verified(comfort, await home.set_comfort(alias, comfort))

            return await self._each(ctx, "set_comfort", args, aliases, change)

        @mcp.tool(annotations=WRITE)
        async def resume_schedule(thermostat: Thermostat = None, house: House = None, ctx: Context = None) -> list[dict]:
            """Clear holds (setpoint or comfort) and return to the thermostat's schedule. With `house`,
            applies to every thermostat there, each reported on its own. The schedule's temperatures are
            the thermostat's own, which this server's setpoint limits don't cover."""
            args = {"thermostat": thermostat, "house": house}
            aliases = self._resolve(ctx, "resume_schedule", args, self._pick(thermostat, house, single=not house))

            async def change(alias):
                return self._verified("schedule", await home.resume(alias))

            return await self._each(ctx, "resume_schedule", args, aliases, change)


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
