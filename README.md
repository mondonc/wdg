# WDG — WireGuard Distributed Gateways

> ⚠️ **Work in Progress** — This project is under active (AI-assisted) development. The architecture is stable; the implementation is ongoing. Not production-ready.

*Lire en [français](README.fr.md).*

WDG is an enterprise VPN solution built on top of [WireGuard](https://www.wireguard.com/), designed to replace existing L2TP/IPsec and WebVPN deployments.
It relies on a centralized Django control plane that dynamically provisions WireGuard configurations from an SSO (CAS/OIDC), and distributes network access across several gateways based on the user's permissions.

---

## Context

The goal is to offer an alternative to tunnel-based VPNs (L2TP, classic VPN), built along zero-trust lines, without depending on proprietary solutions — or "open-source" ones whose licensing and pricing future cannot be guaranteed.

The design stays deliberately simple, in order to drastically reduce the maintenance cost (especially on the client side) and to keep control in-house.

WDG combines WireGuard (a modern, performant, audit-friendly protocol) with a control plane that automatically orchestrates keys, configs and revocations through the SSO.

On the client side, standard WireGuard clients are used.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│               CONTROL PLANE (Django)              │
│                  (intranet only)                  │
│                                                   │
│  ┌───────────┐  ┌───────────┐  ┌───────────────┐ │
│  │   OIDC    │  │  Users /  │  │  WireGuard    │ │
│  │  Client   │  │  Groups   │  │  Config Gen   │ │
│  │  (CAS)    │  │  (DB)     │  │  (keys, IPs)  │ │
│  └───────────┘  └───────────┘  └───────────────┘ │
│                       │                           │
│               REST API (token-based)              │
└───────────┬───────────────────────┬───────────────┘
            │                       │
     ┌──────▼──────┐        ┌───────▼──────┐
     │  Client     │        │  Gateway     │
     │  (script /  │        │  Agent       │
     │   portal)   │        │  (Python)    │
     │             │        │              │
     │  → .conf    │        │  wg syncconf │
     │  → wg-quick │        │  iptables    │
     └─────────────┘        └──────────────┘
```

### Components

**Control Plane (Django)**
- Authentication via CAS (Apereo CAS v5+, exposed as OIDC)
- Group synchronization from OIDC claims
- Generation and distribution of WireGuard configurations
- REST API for clients and gateway agents
- Peer lifecycle management (creation, revocation)

**Gateway Agent (Python)**
- Runs as a systemd service on each egress node
- Polls the Control Plane and applies changes via `wg syncconf`
- Manages iptables / NAT rules

**Client**
- Cross-platform Python script (Linux, macOS, Windows)
- Retrieves the configuration from the Control Plane after SSO authentication
- Generates a `.conf` file ready for `wg-quick`
- Multiple configurations possible depending on the accessible gateways
- Bilingual UI (English / French) — see [`wg_client/locales/README.md`](wg_client/locales/README.md)

---

## Features

- [x] Architecture & specifications
- [ ] Control Plane — Django models (Users, Groups, Devices, Locations)
- [ ] OIDC / CAS integration
- [ ] Provisioning API (client endpoint)
- [ ] Sync API (gateway endpoint)
- [ ] Gateway Agent
- [ ] Python client (Linux)
- [ ] Python client (macOS / Windows)
- [ ] Web portal (enrollment, config download)
- [ ] Automatic revocation on account deactivation
- [ ] WebVPN via browser extension *(nice-to-have)*

---

## Tech stack

| Component | Technology |
|---|---|
| Control Plane | Python / Django |
| SSO auth | Apereo CAS (via OIDC) — `mozilla-django-oidc` |
| VPN | WireGuard |
| Gateway Agent | Python |
| Database | PostgreSQL |
| Deployment | Docker Compose / systemd |

---

## Requirements

- WireGuard installed on gateway nodes
- Apereo CAS v5+ configured as an OIDC Provider (`groups` scope required)
- Python 3.11+
- PostgreSQL 14+

---

## Installation

> ⚠️ Not yet available — under development.

```bash
git clone https://github.com/<org>/wdg.git
cd wdg
# TODO
```

---

## License

This project is distributed under the [GNU General Public License v3.0](LICENSE).

See the `LICENSE` file for the full terms.
