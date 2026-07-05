# Cas 1 — accès actuels sans WDG

*Generated from the control-plane database.*

## Sites
| Site | CAS values | Gateways |
|---|---|---|
| centre-a | — | dgtw-a, rdp-a, vpn-gw-a |
| centre-b | — | dgtw-b, vpn-gw-b |
| datacenter | — | rdp-dc |

## Services
| Service | Clients | Default route | Instances |
|---|---|---|---|
| bastion-rdp-a | yes | — | rdp-a |
| bastion-rdp-dc | yes | — | rdp-dc |
| dgtw-direct-a | yes | — | dgtw-a |
| dgtw-direct-b | yes | — | dgtw-b |
| vpn-a | yes | yes | vpn-gw-a |
| vpn-b | yes | yes | vpn-gw-b |

## Gateways & addressing
| Gateway | Service | Site | Endpoint | Tunnel subnet | Direct networks | Active |
|---|---|---|---|---|---|---|
| dgtw-a | dgtw-direct-a | centre-a | dgtw-a.example.org | 172.31.1.0/24 | 10.30.0.0/23, 10.20.10.0/24 | yes |
| dgtw-b | dgtw-direct-b | centre-b | dgtw-b.example.org | 172.31.2.0/24 | 10.30.0.0/23, 10.20.20.0/24 | yes |
| rdp-a | bastion-rdp-a | centre-a | rdp-a.example.org:3389 | 172.31.5.0/24 | 10.40.10.0/24 | yes |
| rdp-dc | bastion-rdp-dc | datacenter | rdp-dc.example.org:3389 | 172.31.6.0/24 | 10.40.40.0/24 | yes |
| vpn-gw-a | vpn-a | centre-a | vpn-a.example.org:1701 | 172.31.3.0/24 | 10.30.0.0/23, 10.20.10.0/24 | yes |
| vpn-gw-b | vpn-b | centre-b | vpn-b.example.org:1701 | 172.31.4.0/24 | 10.30.0.0/23, 10.20.20.0/24 | yes |

## Relay links
| From | To |
|---|---|

## Networks
| Network | CIDR | Description | Direct legs |
|---|---|---|---|
| vlan-admin-a | 10.40.10.0/24 | VLAN admin centre A | rdp-a |
| vlan-admin-dc | 10.40.40.0/24 | VLAN admin datacenter | rdp-dc |
| vlan-metier | 10.30.0.0/23 | Applications métier (partagé) | dgtw-a, dgtw-b, vpn-gw-a, vpn-gw-b |
| vlan-users-a | 10.20.10.0/24 | VLAN utilisateurs centre A | dgtw-a, vpn-gw-a |
| vlan-users-b | 10.20.20.0/24 | VLAN utilisateurs centre B | dgtw-b, vpn-gw-b |

## Group grants
| Group | Services | Networks |
|---|---|---|
| admins | bastion-rdp-a, bastion-rdp-dc | vlan-admin-a, vlan-admin-dc |
| utilisateurs-a | dgtw-direct-a, vpn-a | vlan-metier, vlan-users-a |
| utilisateurs-b | dgtw-direct-b, vpn-b | vlan-metier, vlan-users-b |
