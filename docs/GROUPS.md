# Groups, entry & exit routing

WDG owns authorization. The IdP authenticates the user and (when configured)
provides group attributes; WDG decides what that user may reach. This document
describes the model and how a user's WireGuard config is derived from it.

## The model (`server/core/models.py`)

- **Site** — a physical centre. Gateways belong to one; the user's home site
  (from the CAS attribute `WDG_CAS_SITE_ATTRIBUTE`) makes its instances the
  preferred ones in their plan.
- **Service** — a pool of interchangeable gateways rendering one function,
  one instance per site (failover order). `accepts_clients` distinguishes
  entry services from relay-only ones; `default_route` marks the full-VPN
  internet-egress tunnel. See docs/DESIGN-MULTITUNNEL.md.
- **Gateway** — a WireGuard node: one site's instance of a service. Has an
  `endpoint`, a fleet-unique `tunnel_subnet`, a `sync_token`, and the set of
  `networks` it has a direct leg into.
- **RelayLink** — a directed inter-gateway link: traffic entering
  `from_gateway` may be forwarded toward what lives behind `to_gateway`
  (chainable).
- **Network** — a destination CIDR reachable through the tunnel (an *exit*
  resource), e.g. `192.168.20.0/24`.
- **Group** — grants `services` (the right to *use* their gateways, as entry
  point or relay hop) and exit `networks` (the right to *reach*) to its
  `members`. `cas_names` lists the CAS values that map onto this group.
- **Device** — a user's enrolled peer on a gateway (public key, allocated
  address, PSK).

## How access is resolved (`server/core/resolve.py`)

A user's grants are the **union over their groups**: a set of services and a
set of networks. `plan_for_user` then computes the multi-tunnel plan:

1. one tunnel per granted entry service (`accepts_clients`), instances ordered
   the user's site first (failover order);
2. per tunnel, the reachable networks: the instance's direct legs **plus**
   everything found by walking `RelayLink` edges — but only into gateways
   whose service is also granted (a relay hop is a privilege);
3. overlapping networks are assigned to exactly one tunnel (deterministic
   partition) so client AllowedIPs never collide; the `default_route` tunnel
   carries `0.0.0.0/0` and always comes last.

The legacy single-tunnel path (`/api/config/`) still applies the direct-leg
scoping:

```
AllowedIPs(user, gateway) = networks_granted_to_user ∩ networks_routable_by_gateway
```

Every gateway additionally enforces access at the packet level: the agent
builds a per-peer egress firewall (default-deny) allowing each client only to
its permitted networks.

### Example (from `seed_demo`)

| Group | Services (entry) | Exit networks |
|---|---|---|
| `vpn-users` | gw-a | net-common |
| `vpn-admins` | gw-a, gw-b | net-common, net-lab-a, net-lab-b |
| `research-lab-a` | gw-a | net-lab-a |
| `research-lab-b` | gw-b | net-lab-b |

Gateways route: `gw-a → {net-common, net-lab-a}`, `gw-b → {net-common, net-lab-b}`.

- **alice** (`vpn-users, vpn-admins, research-lab-a`): enters via gw-a **and**
  gw-b; via gw-a she reaches net-common + net-lab-a, via gw-b net-common +
  net-lab-b.
- **bob** (`vpn-users, research-lab-b`): via gw-a only net-common; net-lab-b is
  reachable only via gw-b. He cannot reach net-lab-a at all.

## CAS attribute → group mapping (`server/core/sync.py`)

At each login, the CAS attributes named in `WDG_CAS_GROUP_ATTRIBUTES`
(e.g. `memberOf`, `eduPersonAffiliation`) are collected and each value is mapped
to a WDG group:

1. a group that lists the value in its `cas_names` (configurable mapping — a full
   LDAP DN or an affiliation string can map to a friendly group), else
2. a group whose `name` equals the value, else
3. a new group auto-created with that name (so unknown CAS groups still surface
   and can be wired to services/networks later).

The user's **home site** follows the same idea with one difference: the CAS
value (attribute `WDG_CAS_SITE_ATTRIBUTE`, e.g. `ou`) is matched against
`Site.cas_values` then `Site.name`, but an unknown value is **ignored, never
auto-created** (sites are infrastructure), and an empty release preserves an
admin-assigned site.

### Resilience when attributes aren't released

If CAS releases **no** group attributes (empty set), membership is **left
untouched** — this preserves assignments made by hand in the Django admin. Set
`replace_when_empty=True` in `sync_membership` to instead treat CAS as strictly
authoritative (empty = no groups).

This means WDG works from day one with identity only: assign users to groups in
the admin; switch to CAS-driven membership once the SSO team releases the
attributes, without changing anything else.

## Administering

- Seed a demo topology: `python manage.py seed_demo`.
- Manage gateways, networks, groups (including `cas_names` and members) and
  devices from the Django admin (`/admin/`).
