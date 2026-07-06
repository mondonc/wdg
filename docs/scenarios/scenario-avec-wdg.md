# Cas 2 — architecture cible WDG

*Generated from the control-plane database.*

## Sites
| Site | CAS values | Gateways |
|---|---|---|
| centre-a | centre-a | gw-admins-a, gw-users-a, relay-admin-a |
| centre-b | centre-b | gw-admins-b, gw-users-b, relay-admin-b |
| datacenter | — | relay-admin-dc |

## Services
| Service | Clients | Default route | Instances |
|---|---|---|---|
| relay-admin | relay-only | — | relay-admin-a, relay-admin-b, relay-admin-dc |
| wdg-admins | yes | — | gw-admins-a, gw-admins-b |
| wdg-users | yes | — | gw-users-a, gw-users-b |

## Gateways & addressing
| Gateway | Service | Site | Endpoint | Tunnel subnet | Direct networks | Active |
|---|---|---|---|---|---|---|
| gw-admins-a | wdg-admins | centre-a | gw-admins-a.vpn.example.org:51820 | 10.10.11.0/24 | 10.30.0.0/23 | yes |
| gw-admins-b | wdg-admins | centre-b | gw-admins-b.vpn.example.org:51820 | 10.10.21.0/24 | 10.30.0.0/23 | yes |
| gw-users-a | wdg-users | centre-a | gw-users-a.vpn.example.org:51820 | 10.10.10.0/24 | 10.30.0.0/23, 10.20.10.0/24 | yes |
| gw-users-b | wdg-users | centre-b | gw-users-b.vpn.example.org:51820 | 10.10.20.0/24 | 10.30.0.0/23, 10.20.20.0/24 | yes |
| relay-admin-a | relay-admin | centre-a | relay-admin-a.vpn.example.org:51820 | 10.10.12.0/24 | 10.40.10.0/24 | yes |
| relay-admin-b | relay-admin | centre-b | relay-admin-b.vpn.example.org:51820 | 10.10.22.0/24 | 10.40.20.0/24 | yes |
| relay-admin-dc | relay-admin | datacenter | relay-admin-dc.vpn.example.org:51820 | 10.10.40.0/24 | 10.40.40.0/24 | yes |

## Relay links
| From | To |
|---|---|
| gw-admins-a | relay-admin-a |
| gw-admins-a | relay-admin-b |
| gw-admins-a | relay-admin-dc |
| gw-admins-b | relay-admin-a |
| gw-admins-b | relay-admin-b |
| gw-admins-b | relay-admin-dc |

## Networks
| Network | CIDR | Description | Direct legs |
|---|---|---|---|
| vlan-admin-a | 10.40.10.0/24 | VLAN admin centre A | relay-admin-a |
| vlan-admin-b | 10.40.20.0/24 | VLAN admin centre B | relay-admin-b |
| vlan-admin-dc | 10.40.40.0/24 | VLAN admin datacenter | relay-admin-dc |
| vlan-metier | 10.30.0.0/23 | Applications métier (partagé) | gw-admins-a, gw-admins-b, gw-users-a, gw-users-b |
| vlan-users-a | 10.20.10.0/24 | VLAN utilisateurs centre A | gw-users-a |
| vlan-users-b | 10.20.20.0/24 | VLAN utilisateurs centre B | gw-users-b |

## Group grants
| Group | Services | Networks |
|---|---|---|
| admins | relay-admin, wdg-admins | vlan-admin-a, vlan-admin-b, vlan-admin-dc, vlan-metier |
| utilisateurs | wdg-users | vlan-metier, vlan-users-a, vlan-users-b |
