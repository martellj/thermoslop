# Networking and discovery

Most "it doesn't see my thermostat" problems are networking, not ThermoSlop.
This page explains how ThermoSlop finds and reaches thermostats, then works
through the usual causes, each with a way to check it.

!!! note "Addresses on this page"
    The examples use documentation ranges: `192.0.2.0/24` for a home LAN,
    `198.51.100.0/24` for a second house, `203.0.113.0/24` for a network behind
    a second router. Substitute your own.

## How it finds and reaches a thermostat

1. **Multicast (mDNS).** `thermoslop discover` listens for HomeKit
   announcements on this machine's LAN interfaces. That only works on the same
   LAN segment: multicast doesn't cross routers, NAT, VLANs or VPNs.
2. **Unicast DNS-SD.** For every subnet in the config (`subnets`, and each
   house's subnets), it also asks every address directly on UDP port 5353.
   Those queries *do* cross NAT and routed links, which is how a VM, another
   VLAN or another house can be reached.
3. **Connecting.** After pairing, ThermoSlop connects straight to the stored
   address and port. If that fails, it looks the thermostat up again by device
   id (first at its last address, then by scanning the subnets) and saves the
   new address. A DHCP reservation for each thermostat makes this rare.

## The thermostat doesn't show up

Work down this list.

### 1. Is the thermostat on the network you think?

On the ecobee: **Main Menu → Settings → Wi‑Fi** shows the network and its
address. If it's on a guest network or a second SSID, it's on a different
subnet from what you're scanning. Try that address directly:

```bash
thermoslop discover --subnet 192.0.2.40/32 --all -v
```

Nothing at all from `--all` means nothing answered HomeKit queries there.
Check the model too: not every ecobee supports HomeKit (the Smart Si and the
original EMS don't), and an old ecobee3 may need a firmware update. Rebooting
the thermostat sometimes brings back HomeKit answers.

### 2. Is this machine on the same LAN?

Compare this machine's address with the thermostat's. A **VM with NAT
networking** (QEMU/UTM "shared network", VirtualBox NAT) has its own private
address behind the host and never sees the LAN's multicast. Add the LAN to the config so it
is scanned by unicast, which does get through the NAT:

```toml
[houses]
home = ["192.0.2.0/24"]
```

### 3. Is there a second router in the way?

Mesh Wi‑Fi systems (Google/Nest Wifi, eero, Deco and similar) usually run in
**router mode**: they make their own private LAN behind whatever router is
upstream. Your Wi‑Fi devices and the thermostat then live on the mesh's LAN
(`203.0.113.0/24` here), not the upstream router's (`192.0.2.0/24`).

- **Check:** your laptop's address is in a different subnet from the
  upstream router's LAN, or you can reach the upstream router but no Wi‑Fi
  device answers on its subnet.
- **Fix for scanning:** put the mesh's subnet in the config, not the upstream
  router's.
- **Fix for remote access:** see
  [a house behind a second router](#a-house-behind-a-second-router) below.
  Bridge mode removes the second NAT, but some mesh systems lose their mesh
  points in bridge mode.

A static address for the mesh router doesn't help on its own: a router in
router mode drops connections arriving on its internet side for devices
behind it, and HomeKit's ports change too often for port forwarding.

### 4. Did advertising a route cut off the LAN?

If a router advertises its own LAN as a **Tailscale subnet route**, devices
*on that LAN* that accept subnet routes send their LAN traffic into Tailscale
instead of straight over Wi‑Fi. If the router's firewall then drops it, the
whole LAN goes dark for that device, router included.

- **Check:** the LAN came back the moment you turned off subnet routes on the
  device, or `ip route show table 52` (Linux) lists your own LAN on
  `tailscale0`.
- **Fix:** on devices that live on that LAN, turn off "Use Tailscale subnets"
  (macOS/iOS/Android app settings), or `tailscale set --accept-routes=false`
  (Linux). The lasting fix is the router firewall zone below, so the route
  works either way.

### 5. Over Tailscale: are routes accepted, and forwarded?

- The route must be **advertised and approved** in the Tailscale admin console.
- **Linux doesn't accept routes by default:** run
  `tailscale set --accept-routes` on the machine running ThermoSlop.
  `tailscale status` warns "Some peers are advertising routes but
  --accept-routes is false" when this is the problem.
- **The router must forward Tailscale traffic to its LAN.** If
  `tailscale ping <router>` works but the router's own LAN address doesn't
  answer, its firewall is dropping it: see the OpenWrt zone below.

## Reaching another house over Tailscale

Run Tailscale on a router (or any always-on device) **on that house's LAN**,
advertising the LAN as a subnet route. With OpenWrt 23 or newer:

```sh
opkg update && opkg install tailscale     # apk add tailscale on OpenWrt 25
tailscale up --advertise-routes=198.51.100.0/24
```

Approve the route in the admin console, then let Tailscale traffic through
OpenWrt's firewall to the LAN. Check your own interface names first
(`uci show network`); these are the defaults:

```sh
uci set network.tailscale=interface
uci set network.tailscale.proto='none'
uci set network.tailscale.device='tailscale0'
uci set firewall.tailscale=zone
uci set firewall.tailscale.name='tailscale'
uci set firewall.tailscale.input='ACCEPT'
uci set firewall.tailscale.output='ACCEPT'
uci set firewall.tailscale.forward='REJECT'
uci add_list firewall.tailscale.network='tailscale'
uci set firewall.ts_lan=forwarding
uci set firewall.ts_lan.src='tailscale'
uci set firewall.ts_lan.dest='lan'
uci commit && service network reload && service firewall restart
```

Then, from the ThermoSlop machine, the router's LAN address should answer and
discovery should find the house's thermostats:

```bash
ping -c1 198.51.100.1
thermoslop discover --house cabin
```

### A house behind a second router

If the house's Wi‑Fi is a mesh in router mode behind the Tailscale router (see
[step 3](#3-is-there-a-second-router-in-the-way)), the thermostat is on the
mesh's LAN, which the Tailscale router can't reach in to. The subnet router
has to be **inside** the mesh's LAN:

- connect a spare port of the Tailscale router to a LAN port on the mesh, as a
  client of the mesh's network, and advertise the mesh subnet from there (with
  masquerading on that interface, since the mesh can't add routes); or
- run Tailscale on any always-on device on the mesh Wi‑Fi (an Apple TV, a
  Raspberry Pi) and advertise the mesh subnet from it.

Reserve that device's address on the mesh, and keep "Use Tailscale subnets"
off on the other devices in that house ([step 4](#4-did-advertising-a-route-cut-off-the-lan)).

## Messages you might see

| Where | Message | Meaning |
|---|---|---|
| Panel header | can't reach thermostats · retrying | The watcher runs; the thermostats don't answer. Usually you're away and the remote route isn't set up, or the network is down. |
| Panel header | watcher offline · run: thermoslop setup | The state file is over 10 minutes old: the watcher stopped. |
| Panel card | CAN'T READ | The card's live read failed; the note says why. A press retries. |
| Panel card | thermostat set 66.5° | The thermostat took a different value from the one sent. |
| CLI | exit code 2 | Sent, but the thermostat didn't confirm within 8 seconds. Check with `thermoslop status --live`. |
| CLI | another change is still being confirmed | Another ThermoSlop process is changing that thermostat; try again. |
| `thermoslop bar` | The watcher can't reach these thermostats | As "can't reach thermostats" above. |
