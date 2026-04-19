# WDG — WireGuard Distributed Gateways

> ⚠️ **Work in Progress** — Ce projet est en cours de développement (assisté IA). L'architecture est stabilisée, l'implémentation est en cours. Ne pas utiliser en production.

WDG est une solution de VPN d'entreprise basée sur [WireGuard](https://www.wireguard.com/), conçue pour remplacer des infrastructures L2TP/IPsec et WebVPN existantes.
Elle repose sur un plan de contrôle centralisé (Django) qui provisionne dynamiquement les configurations WireGuard à partir d'un SSO (CAS/OIDC), et distribue les accès réseau via plusieurs passerelles en fonction des droits de l'utilisateur.

---

## Contexte

L'objectif est de proposer une alternative aux tunnels (L2TP, VPN classique), orientée zero trust ,sans dépendre de solutions propriétaires, ou "opensource" dont l'avenir de licensing et de tarification n'est pas garanti.

L'idée est de rester résolument simple, pour réduire drastiquement le coût de maitenance (notamment des clients), et de garder le contrôle.

WDG répond combine WireGuard (protocole moderne, performant, audit-friendly) avec un plan de contrôle qui orchestre automatiquement clés, configs et révocations via le SSO.

Côté client, utilisation des clients standard wireguard.

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
│  │  (CAS)    │  │  (DB)     │  │  (clés, IPs)  │ │
│  └───────────┘  └───────────┘  └───────────────┘ │
│                       │                           │
│               API REST (token-based)              │
└───────────┬───────────────────────┬───────────────┘
            │                       │
     ┌──────▼──────┐        ┌───────▼──────┐
     │  Client     │        │  Gateway     │
     │  (script /  │        │  Agent       │
     │   portail)  │        │  (Python)    │
     │             │        │              │
     │  → .conf    │        │  wg syncconf │
     │  → wg-quick │        │  iptables    │
     └─────────────┘        └──────────────┘
```

### Composants

**Control Plane (Django)**
- Authentification via CAS (Apereo CAS v5+, exposé en OIDC)
- Synchronisation des groupes depuis les claims OIDC
- Génération et distribution des configurations WireGuard
- API REST pour les clients et les agents de passerelle
- Gestion du cycle de vie des pairs (création, révocation)

**Gateway Agent (Python)**
- Tourne en tant que service systemd sur chaque nœud de sortie
- Poll le Control Plane et applique les changements via `wg syncconf`
- Gère les règles iptables / NAT

**Client**
- Script Python multiplateforme (Linux, macOS, Windows)
- Récupère la configuration depuis le Control Plane après authentification SSO
- Génère un fichier `.conf` prêt pour `wg-quick`
- Plusieurs configurations possibles selon les passerelles accessibles

---

## Fonctionnalités

- [x] Architecture & spécifications
- [ ] Control Plane — modèles Django (Users, Groups, Devices, Locations)
- [ ] Intégration OIDC / CAS
- [ ] API de provisioning (endpoint client)
- [ ] API de synchronisation (endpoint gateway)
- [ ] Gateway Agent
- [ ] Client Python (Linux)
- [ ] Client Python (macOS / Windows)
- [ ] Portail web (enrollment, téléchargement de conf)
- [ ] Révocation automatique à la désactivation du compte
- [ ] WebVPN via extension navigateur *(nice-to-have)*

---

## Stack technique

| Composant | Technologie |
|---|---|
| Control Plane | Python / Django |
| Auth SSO | Apereo CAS (via OIDC) — `mozilla-django-oidc` |
| VPN | WireGuard |
| Gateway Agent | Python |
| Base de données | PostgreSQL |
| Déploiement | Docker Compose / systemd |

---

## Prérequis

- WireGuard installé sur les nœuds de passerelle
- Apereo CAS v5+ configuré en OIDC Provider (scope `groups` requis)
- Python 3.11+
- PostgreSQL 14+

---

## Installation

> ⚠️ Pas encore disponible — en cours de développement.

```bash
git clone https://github.com/<org>/wdg.git
cd wdg
# À compléter
```

---

## Licence

Ce projet est distribué sous licence [GNU General Public License v3.0](LICENSE).

Voir le fichier `LICENSE` pour les termes complets.
