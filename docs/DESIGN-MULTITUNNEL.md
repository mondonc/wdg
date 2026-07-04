# Multi-tunnel architecture (design)

> Status: **M8–M11 implemented** (control plane, gateway agent, multi-tunnel
> client, e2e failover); M12 hardening pending (2026-07-04). The dev stack
> exercises two simultaneous tunnels, a real gw-a → gw-dc relay chain, and
> failover to the gw-a2 instance (both dead-DNS and silent-instance cases).

## Goals

- A client holds **several simultaneous WireGuard tunnels**, one per gateway,
  using standard WireGuard clients.
- Gateways are grouped into **services**: pools of interchangeable instances,
  one per **site** (centre). A user connects to their own site's instance
  (site derived from a CAS attribute), and **fails over** to another site's
  instance when it doesn't answer.
- A per-service **default-route** flag: that tunnel captures all traffic not
  matched elsewhere (traditional full VPN to the internet).
- Exits are **networks** (gateway has a leg in the target network — the
  existing model) *or* **relays**: another gateway reached through an
  inter-gateway WireGuard link, itself carrying networks or further relays
  (**chainable** — it is a graph).
- Authorization stays group-driven and **server-authoritative**: groups grant
  *targets*; the control plane computes which gateways the client may (and
  needs to) connect to, and with which routes.

### Reference use case

```
clientA (site "centre", groups: grp-chercheurs, grp-gw-centre)
│
├─ tun0 → svc internet-egress   @centre   AllowedIPs: 0.0.0.0/0   (default_route)
├─ tun1 → svc si-chercheurs     @centre   AllowedIPs: SI nets + DC nets
│            └─ relay link → svc dc-access @centre → DC networks
└─ (svc si-dsi / si-presta: not a member → no tunnel)

instance @centre down → next instance of the same service (other site)
```

## Data model

New:

- **Site** — a centre. `name`, `cas_values` (CAS attribute values that map a
  user to this site). The user's site is resolved at login (attribute name in
  `WDG_CAS_SITE_ATTRIBUTE`) and stored on a user profile; manual override in
  the admin (same resilience philosophy as group mapping).
- **Service** — a pool of interchangeable gateways. `name`, `description`,
  `accepts_clients` (entry service: clients connect directly; relays-only
  services like `dc-access` set it false), `default_route` (this service's
  tunnel is the client's catch-all). *Note: `default_route` lives on the
  Service, not the Gateway — instances must be interchangeable for failover,
  so behaviour cannot differ per instance.*
- **RelayLink** — a directed edge `from_gateway → to_gateway`: a WireGuard
  tunnel between the two gateways over which `from` forwards traffic toward
  the networks (and further relays) behind `to`.

Changed:

- **Gateway** gains `service` (FK) and `site` (FK). `tunnel_subnet` becomes
  **unique across the fleet** (control-plane-validated): client tunnel
  addresses must be unambiguous inside the overlay for relayed, un-NATed
  traffic and return routes.
- **Group** grants become: `services` (M2M — the right to *use* gateways of
  that service, as entry point or as relay hop) and `networks` (M2M — the
  right to *reach*, unchanged). `Group.gateways` disappears: groups no longer
  reference individual gateways, the resolver picks instances.

Unchanged: `Network`, `Device` (one per user × gateway), PSK handling, tokens.

## Resolver (per-user plan)

1. **Grants**: union over the user's groups → set of services, set of networks.
2. **Entry services** = granted services with `accepts_clients`. For each,
   order instances: the user's site first, then the rest (stable order —
   this is the failover sequence).
3. **Reachability walk**: from each entry service's gateway, walk `RelayLink`
   edges, but only *into* gateways whose service is also granted (a relay hop
   is a privilege: `grp-gw-centre` grants `dc-access`). Collect, at every
   visited gateway, its attached networks ∩ granted networks.
4. **Deterministic partition**: a network reachable through several tunnels is
   assigned to exactly **one** — the first in plan order (site-local entry
   first, then service name). No AllowedIPs overlap ever reaches the client;
   "first come, first served" remains only as the client-side guard during
   failover races. The `default_route` service contributes `0.0.0.0/0` and is
   always last in bring-up order.

Output = the **plan**: an ordered list of tunnels, each with its service, its
instance list (failover order, each with endpoint / server public key / client
address / PSK), its AllowedIPs, and the default-route flag.

## APIs

- **`GET /api/plan/`** (client, bearer token) — the full multi-tunnel plan
  above. `/api/config/` remains during the transition and serves the plan's
  first tunnel as a flat `.conf`.
- **`POST /api/gateways/sync/`** (agent) gains:
  - `relay_peers`: the gateway's inter-gateway WireGuard peers (both
    directions of its RelayLinks), each with endpoint, public key, and
    AllowedIPs covering *what lives behind that peer*: client tunnel subnets
    (return path) and/or target networks (forward path). Kernel routes follow.
  - `peers[*].networks` continues to drive per-client egress rules, now
    including clients that arrive **via a relay** (their source addresses
    belong to another gateway's tunnel_subnet — hence fleet-wide uniqueness).

## Enforcement (decided: per hop, no inter-gateway NAT)

Client tunnel IPs survive inside the inter-gateway tunnels (pure overlay —
underlay networks never see them). Every gateway, entry or relay, applies its
own per-client egress rules pushed by the control plane; a compromised entry
gateway cannot widen access behind a relay. MASQUERADE stays on the **last
leg** only (relay → target network), so target networks keep seeing the local
gateway's address and no real-network routing changes are ever needed.
Consequences handled by the control plane: fleet-unique tunnel subnets,
computed return routes on every hop of a chain.

## Failover (decided: at connect time)

`connect` brings tunnels up in plan order; for each tunnel, try instances in
order — no WireGuard handshake within N seconds (~10 s) → tear down, next
instance. A `reconnect` command re-runs the sequence. No resident daemon in
this iteration; continuous monitoring is a possible later step.

## Client

- One conf per tunnel (`wg-client-<service>`), brought up specifics-first,
  default-route last; same keypair everywhere (already the case).
- Windows: the official client requires the
  `HKLM\Software\WireGuard\MultipleSimultaneousTunnels=1` registry value for
  multiple active tunnels — set/documented by our client.
- `status` shows one line per tunnel (service, instance, handshake age).

## Migration path

A data migration creates one Service per existing gateway (`accepts_clients`
on, `default_route` off) and a placeholder Site, then maps `Group.gateways` →
`Group.services`. Existing clients keep working through `/api/config/` until
the multi-tunnel client ships.

## Milestones

- **M8 — control plane**: Site / Service / RelayLink models + user site
  profile + admin; CAS site attribute mapping; resolver rewrite (graph walk +
  partition); `/api/plan/`; data migration; unit tests. `/api/config/`
  backward-compatible.
- **M9 — gateway agent**: inter-gateway tunnels from `relay_peers`, kernel +
  return routes, per-hop egress incl. relayed clients.
- **M10 — client**: multi-tunnel connect/disconnect/status, connect-time
  failover, `reconnect`, Windows multi-tunnel registry handling.
- **M11 — e2e (Docker)**: two sites × {internet-egress, si-entry} + a relay
  chain to a DC network; probes for reach/deny, relay enforcement, failover
  (instance down), default-route capture.
- **M12 — hardening**: subnet allocation/validation UX, plan versioning
  (ETag), docs.
