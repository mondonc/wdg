# Groups, entry & exit routing

WDG owns authorization. The IdP authenticates the user and (when configured)
provides group attributes; WDG decides what that user may reach. This document
describes the model and how a user's WireGuard config is derived from it.

## The model (`server/core/models.py`)

- **Gateway** — a WireGuard egress node clients dial (the tunnel *entry* point).
  Has an `endpoint`, a `tunnel_subnet` (client addresses are allocated from it),
  a `sync_token`, and the set of `networks` it can route to.
- **Network** — a destination CIDR reachable through the tunnel (an *exit*
  resource), e.g. `192.168.20.0/24`.
- **Group** — grants a set of entry `gateways` and exit `networks` to its
  `members`. `cas_names` lists the CAS values that map onto this group.
- **Device** — a user's enrolled peer on a gateway (public key, allocated
  address, PSK).

## How access is resolved (`server/core/resolve.py`)

A user's effective access is the **union over their groups**:

- **entry gateways** = every active gateway granted by any of their groups;
- **exit networks** = every network granted by any of their groups.

Per gateway, the pushed `AllowedIPs` are scoped for coherence:

```
AllowedIPs(user, gateway) = networks_granted_to_user ∩ networks_routable_by_gateway
```

So a network is only routed through a gateway that can actually reach it, and
only for users whose groups grant it. The gateway additionally enforces this at
the packet level: the agent builds a per-peer egress firewall (default-deny)
allowing each client only to its permitted networks.

### Example (from `seed_demo`)

| Group | Entry gateways | Exit networks |
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
   and can be wired to gateways/networks later).

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
