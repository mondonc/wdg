# Deployment

This guide covers how the WDG control plane, gateways and PQ terminator fit
together, how authentication is wired to Apereo CAS, and what remains before a
production rollout. For the local dev stack, see the Quickstart in the
[README](../README.md).

## Components

| Component | Path | Role |
|---|---|---|
| Control plane | `server/` | CAS auth, model + admin, provisioning & sync APIs, config generation |
| PQ terminator | `deploy/nginx-pq/` | TLS 1.3 termination with `X25519MLKEM768`, optional fail-closed |
| Gateway agent | `gateway/` | kernel WireGuard, peer reconciliation, routing/NAT, egress firewall |
| Client | `wg_client/` | cross-platform CLI |
| Mock CAS (dev only) | `deploy/cas-test/` | stand-in CAS server for tests |

## Authentication (CASv3)

WDG authenticates against **Apereo CAS** using the **native CAS v3 ticket
protocol**, not OIDC. A CAS server often exposes both, but CASv3 is chosen
because:

- Group/affiliation attributes (`memberOf`, `eduPersonAffiliation`, …) are the
  native output of `/p3/serviceValidate`, whereas a CAS OIDC discovery may
  expose **no** group claim.
- The control plane validates the ticket **server-to-server** and issues its
  **own** signed session token — no per-request dependency on the IdP, no
  jwks/introspection/refresh machinery.

Flow:

1. The client opens the browser at `<control-plane>/auth/cas/login?redirect=<loopback>`.
2. The control plane redirects to `<cas-server>/cas/login?service=<control-plane>/auth/cas/callback`.
3. CAS returns to the callback with a ticket; the control plane validates it via
   `/cas/p3/serviceValidate`, reads identity + attributes, upserts the user and
   mirrors group membership, then issues a **single-use code** (60 s lifetime).
4. The code is handed back to the client on the loopback redirect; the client
   exchanges it with a `POST /auth/cas/exchange` for the **WDG token**, used as
   `Authorization: Bearer` for the API. The bearer token itself never appears
   in a URL (browser history, proxies, access logs).

### What to request from the SSO team

- **Register the service**: the exact `service` URL, i.e.
  `https://<control-plane-public-host>/auth/cas/callback`.
- **Attribute release**: ask for the group/affiliation attributes to be released
  to this service (e.g. `memberOf`, `eduPersonAffiliation`). Until they are,
  membership can be assigned by hand in the admin — see [GROUPS.md](GROUPS.md).
  List the attribute names in `WDG_CAS_GROUP_ATTRIBUTES`.

## Control plane configuration

All settings come from the environment (see `server/wdg_server/settings.py`):

| Variable | Meaning |
|---|---|
| `WDG_SECRET_KEY` | Django secret (also signs WDG tokens) — set a strong value; **required** unless `WDG_DEBUG=1` |
| `WDG_DEBUG` | `1`/`0` (default `0`) |
| `WDG_ALLOWED_HOSTS` | comma-separated hostnames |
| `WDG_CAS_BASE_URL` | CAS base, e.g. `https://cas.example.org` |
| `WDG_PUBLIC_BASE_URL` | public base of the control plane (the CAS `service` root) |
| `WDG_CAS_GROUP_ATTRIBUTES` | CAS attributes carrying groups (default `memberOf`) |
| `WDG_CAS_SITE_ATTRIBUTE` | CAS attribute carrying the user's home site/centre (default `ou`) |
| `WDG_TOKEN_MAX_AGE` | WDG token lifetime, seconds |
| `WDG_AUTH_CODE_MAX_AGE` | lifetime of the one-time login code, seconds (default 60) |
| `POSTGRES_*` | database connection |

## Gateways

Each gateway runs the agent (`gateway/agent.py`). It:

1. loads its WireGuard keypair from `WDG_STATE_DIR` (generated once, then
   persistent across restarts) and self-reports the public key at sync time;
2. brings up kernel WireGuard (`ip link add … type wireguard`), assigns the
   gateway's tunnel address, enables forwarding and MASQUERADE;
3. every few seconds POSTs `/api/gateways/sync/` with its sync token, receives
   its authorized peers, and reconciles `wg` peers + the per-peer egress chain.

Agent environment:

| Variable | Meaning |
|---|---|
| `WDG_CONTROL_PLANE` | control plane base URL |
| `WDG_GATEWAY_TOKEN` | the gateway's `sync_token` (see the `Gateway` admin) |
| `WDG_WG_IFACE` | interface name (default `wg0`) |
| `WDG_POLL_INTERVAL` | sync interval in seconds (default 5) |
| `WDG_STATE_DIR` | where the private key persists (default `/var/lib/wdg`) — back it by a volume in containers |

Runtime requirements: `NET_ADMIN` capability, `net.ipv4.ip_forward=1`, and a host
kernel with WireGuard. In containers this is `cap_add: [NET_ADMIN]` +
`sysctls: [net.ipv4.ip_forward=1]` (see `deploy/docker-compose.yml`). On bare
metal, run the agent as a systemd service.

Register a gateway in the admin (or `seed_demo`): set `name`, `endpoint`
(the public `host:port` clients dial), `tunnel_subnet`, `sync_token`, and the
`networks` it can route to.

## PQ terminator

`deploy/nginx-pq/` builds nginx (OpenSSL ≥ 3.5) that terminates client HTTPS and
proxies to the control plane. `REQUIRE_PQ=on` makes the sensitive endpoints
refuse non-post-quantum connections. See [POST-QUANTUM.md](POST-QUANTUM.md).

It also rate-limits the unauthenticated auth endpoints (`/auth/cas/login`,
`/auth/cas/exchange`): 10 requests/minute per client IP with a burst of 5,
then `429` — enough for any human login, a wall for code-guessing or
session-minting abuse.

If nginx-pq itself sits behind a load balancer, set `REAL_IP_FROM` to the
LB's address(es)/CIDR(s) (comma-separated): the client IP is then recovered
from `X-Forwarded-For` so the rate limit keys on the real client, not the LB.
Leave it empty when clients connect directly — trusting `X-Forwarded-For`
from arbitrary peers would let anyone dodge the limit by forging the header.

## Toward production (not done yet)

The dev stack cuts corners a real deployment must fix:

- **Secrets**: `WDG_SECRET_KEY`, gateway `sync_token`s and DB credentials are
  demo values — generate and inject real secrets.
- **TLS certificates**: `nginx-pq` uses a self-signed cert. Use a real cert
  (internal CA or ACME) and remove `-k`/`verify=False` from clients.
- **Database/HA**: managed PostgreSQL, backups, multiple control-plane replicas.
- **Runserver → gunicorn**: the compose uses Django's dev server; serve via
  gunicorn behind nginx.
- **Client packaging**: ship an installable console script and validate the
  macOS/Windows tunnel paths on real machines.
