# WDG — WireGuard Distributed Gateways

> ⚠️ **Work in Progress** — This project is under active (AI-assisted) development. The architecture is stable and an end-to-end proof of concept runs and is tested in Docker; it is **not production-ready**.

*Lire en [français](README.fr.md).*

WDG is an enterprise VPN built on [WireGuard](https://www.wireguard.com/), designed to replace L2TP/IPsec and WebVPN deployments. A centralized Django **control plane** authenticates users through SSO (Apereo CAS), then dynamically provisions per-user WireGuard configurations and distributes network access across several **gateways** according to the user's group membership. The PSK is delivered over a **post-quantum** TLS channel while keeping **standard WireGuard clients** on every OS.

---

## Context

The goal is a zero-trust alternative to tunnel-based VPNs (L2TP, classic VPN) that does not depend on proprietary — or "open-source" but uncertainly-licensed — solutions. The design stays deliberately simple to keep maintenance cost low (especially client-side) and control in-house.

On the client side, **standard WireGuard clients** are used; WDG only generates the `.conf`.

---

## Architecture

```
   client (multi-OS, standard WireGuard)
     │  browser ─► control-plane /auth/cas ─► cas.example.org (CASv3 ticket)
     │  HTTPS over post-quantum TLS (X25519MLKEM768) + WDG token
     ▼
  nginx-pq  ─►  control-plane (Django + PostgreSQL)
                 ├─ /auth/cas/{login,callback}   validate ticket, mint WDG token
                 ├─ /api/peers/register/          register the device public key
                 ├─ /api/config/                  generate .conf (PSK + AllowedIPs by group)
                 └─ /api/gateways/sync/           gateways pull their authorized peers
                                  │
                        ┌─────────┴─────────┐
                    gateway-A            gateway-B     (Python agent + kernel WireGuard)
                    entry point          entry point
                    exit networks X,Y    exit networks Z
```

- **Authentication** is CASv3 (native ticket protocol) against your Apereo CAS server; the control plane validates the ticket server-side and issues its own signed session token. See [why CASv3 and not OIDC](docs/DEPLOYMENT.md#authentication-casv3).
- **Authorization** lives in WDG: a *group* grants entry *gateways* and exit *networks*; a user's effective access is the union over their groups. Group membership is mirrored from CAS attributes (`memberOf`, affiliations) with a fallback to manual admin assignment. See [docs/GROUPS.md](docs/GROUPS.md).
- **Post-quantum**: the PSK delivery rides TLS 1.3 with the `X25519MLKEM768` hybrid group, defeating "harvest-now-decrypt-later". Compatibility is preserved by default; PQ can be made mandatory with a server switch. See [docs/POST-QUANTUM.md](docs/POST-QUANTUM.md).

### Components

- **Control Plane** (`server/`, Django + PostgreSQL) — CAS auth, group/gateway/network model + admin, provisioning & sync APIs, config generation.
- **Gateway Agent** (`gateway/`, Python) — brings up kernel WireGuard, reconciles peers from the sync API every few seconds, programs routing/NAT and per-peer egress firewalling.
- **PQ terminator** (`deploy/nginx-pq/`) — nginx (OpenSSL ≥ 3.5) terminating client HTTPS with the post-quantum hybrid group and an optional fail-closed switch.
- **Client** (`wg_client/`, Python/Click) — cross-platform CLI: SSO login, keypair generation, config fetch, `wg-quick`/WireGuard tunnel management, bilingual (EN/FR).

---

## Status

An end-to-end proof of concept is implemented and **tested in Docker** (Linux data path exercised for real):

- [x] Control Plane — models (Users, Groups, Devices, Gateways, Networks) + admin
- [x] CASv3 authentication + WDG session tokens
- [x] Provisioning API (`register`, `config`) with per-device PSK
- [x] Sync API + Gateway Agent (kernel WireGuard, real tunnel)
- [x] Group-driven entry/exit routing + per-peer egress firewall
- [x] Revocation on account/device deactivation
- [x] Post-quantum TLS transport (`X25519MLKEM768`) + `require_pq` client switch
- [x] CAS attribute → group mapping (+ resilience to un-released attributes)
- [x] Python client (Linux) — tested end-to-end
- [ ] Python client (macOS / Windows) — code present, **not yet validated on those OSes**
- [ ] Web enrollment portal *(nice-to-have)*
- [ ] Production hardening (secrets, TLS certs, HA, persistent gateway keys)

---

## Quickstart (dev stack)

Requirements: Docker + Docker Compose, and a Linux host whose kernel provides WireGuard (standard since 5.6). The stack uses a **mock CAS** so no real SSO is needed.

```bash
cd deploy
docker compose up -d --build          # postgres, mock CAS, control-plane, nginx-pq
docker compose exec control-plane python manage.py seed_demo
docker compose exec control-plane python manage.py createsuperuser  # optional (admin UI)
```

Run the test suites:

```bash
# Django unit tests (model, resolver, provisioning, CAS mapping)
docker compose exec control-plane python manage.py test

# End-to-end integration (CASv3 login, provisioning, config, CAS groups)
docker compose run --rm tester

# Real WireGuard tunnel + group-scoped egress + revocation
docker compose --profile tunnel up -d --build gw-a exit-target exit-target-b
docker compose --profile tunnel run --rm \
  -e USERNAME=alice -e "REACH=http://10.0.0.10:8000,http://192.168.20.10:8000" client-probe

# Post-quantum transport (run from a host with OpenSSL >= 3.5)
bash tests/m5_pq_check.sh
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for how it all fits together and how to move toward production.

---

## Client usage

```bash
pip install -r wg_client/requirements.txt

python -m wg_client.main configure --server https://vpn.example.com
python -m wg_client.main login          # SSO, shows your identity + groups
python -m wg_client.main connect        # provision + bring up the tunnel
python -m wg_client.main status
python -m wg_client.main disconnect

# Require post-quantum TLS (fail closed if unavailable):
python -m wg_client.main configure --server https://vpn.example.com --require-pq
```

French UI: `WDG_LANG=fr python -m wg_client.main --help`. Post-quantum negotiation needs the client's OpenSSL ≥ 3.5 — see [docs/POST-QUANTUM.md](docs/POST-QUANTUM.md#client-side).

---

## Documentation

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — deploying the control plane and gateways, CAS registration, production notes
- [docs/GROUPS.md](docs/GROUPS.md) — the group model and how entry/exit routing is derived
- [docs/POST-QUANTUM.md](docs/POST-QUANTUM.md) — the post-quantum design, guarantees and limits

---

## Tech stack

| Component | Technology |
|---|---|
| Control Plane | Python / Django / PostgreSQL |
| SSO auth | Apereo CAS v3 (native ticket protocol) |
| VPN | WireGuard (kernel) |
| Gateway Agent | Python + `wg` + iptables |
| PQ transport | nginx + OpenSSL ≥ 3.5 (`X25519MLKEM768`) |
| Client | Python / Click / `cryptography` / `keyring` |
| Dev/Test infra | Docker Compose |

---

## License

Distributed under the [GNU Affero General Public License v3.0](LICENSE). See the `LICENSE` file for the full terms.
