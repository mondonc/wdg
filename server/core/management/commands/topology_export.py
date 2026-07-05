"""
Export the topology stored in the database, for humans.

Two formats, both written to stdout (see ``make doc``):

- ``--format dot``: a Graphviz diagram of the network plan — sites as
  clusters, gateways coloured by service (relay-only ones dashed), relay
  links, direct network legs, and a legend. Render with ``dot -Tpdf``.
- ``--format markdown``: the addressing plan as tables (sites, services,
  gateways/subnets, relay links, networks, group grants).
"""

from django.core.management.base import BaseCommand

from core.models import Gateway, Group, Network, RelayLink, Service, Site

PALETTE = [
    "#4e79a7", "#f28e2b", "#59a14f", "#e15759",
    "#b07aa1", "#76b7b2", "#d4a017", "#9c755f",
]


def _service_colors() -> dict[int, str]:
    services = list(Service.objects.order_by("name"))
    return {s.pk: PALETTE[i % len(PALETTE)] for i, s in enumerate(services)}


def _q(text: str) -> str:
    """Escape for a double-quoted DOT string literal (quotes, backslashes)."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _gateway_label(g: Gateway) -> str:
    lines = [g.name, f"{g.endpoint}", f"tunnel {g.tunnel_subnet}"]
    if not g.is_active:
        lines.append("(inactive)")
    return "\\n".join(_q(line) for line in lines)


DEFAULT_TITLE = "WDG network plan (generated from the control-plane database)"


def render_dot(title: str | None = None) -> str:
    title = DEFAULT_TITLE if title is None else title
    colors = _service_colors()
    out = [
        "digraph wdg {",
        '  rankdir=LR;',
        '  fontname="Helvetica"; labelloc="t";',
        f'  label="{_q(title)}";',
        '  node [fontname="Helvetica", fontsize=10, shape=box, style="rounded,filled"];',
        '  edge [fontname="Helvetica", fontsize=9];',
        "",
        '  clients [label="clients\\n(standard WireGuard)", shape=oval, fillcolor="#eeeeee"];',
        "",
    ]

    def gateway_node(g: Gateway, indent: str) -> str:
        color = colors.get(g.service_id, "#cccccc")
        style = "rounded,filled"
        if g.service and not g.service.accepts_clients:
            style += ",dashed"  # relay-only: no direct clients
        return (
            f'{indent}gw_{g.pk} [label="{_gateway_label(g)}", '
            f'fillcolor="{color}40", color="{color}", style="{style}"];'
        )

    for site in Site.objects.all():
        out.append(f"  subgraph cluster_site_{site.pk} {{")
        out.append(f'    label="{_q(site.name)}"; style="rounded"; color="#999999";')
        for g in site.gateways.select_related("service"):
            out.append(gateway_node(g, "    "))
        out.append("  }")
        out.append("")
    for g in Gateway.objects.filter(site__isnull=True).select_related("service"):
        out.append(gateway_node(g, "  "))

    out.append("")
    for n in Network.objects.all():
        desc = f"\\n{_q(n.description)}" if n.description else ""
        out.append(
            f'  net_{n.pk} [label="{_q(n.name)}\\n{_q(n.cidr)}{desc}", '
            f'shape=box, fillcolor="#f5f5f5", color="#888888"];'
        )

    out.append("")
    for g in Gateway.objects.filter(service__accepts_clients=True, is_active=True):
        out.append(f'  clients -> gw_{g.pk} [style=dotted, color="#777777"];')
    for g in Gateway.objects.prefetch_related("networks"):
        for n in g.networks.all():
            out.append(f'  gw_{g.pk} -> net_{n.pk} [color="#888888"];')
    for link in RelayLink.objects.select_related("from_gateway", "to_gateway"):
        out.append(
            f"  gw_{link.from_gateway_id} -> gw_{link.to_gateway_id} "
            f'[penwidth=2, color="#e15759", label="relay", fontcolor="#e15759"];'
        )

    # Legend: one entry per service, with its flags.
    out += ["", "  subgraph cluster_legend {", '    label="services"; style="rounded"; color="#bbbbbb";']
    for s in Service.objects.all():
        flags = []
        flags.append("entry" if s.accepts_clients else "relay-only")
        if s.default_route:
            flags.append("default route → internet")
        color = colors[s.pk]
        style = "rounded,filled" + ("" if s.accepts_clients else ",dashed")
        out.append(
            f'    svc_{s.pk} [label="{_q(s.name)}\\n({", ".join(flags)})", '
            f'fillcolor="{color}40", color="{color}", style="{style}"];'
        )
    out += ["  }", "}"]
    return "\n".join(out)


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines + [""]


def render_markdown(title: str | None = None) -> str:
    title = "WDG network plan" if title is None else title
    out = [f"# {title}", "", "*Generated from the control-plane database.*", ""]

    out.append("## Sites")
    out += _table(
        ["Site", "CAS values", "Gateways"],
        [
            [s.name, ", ".join(s.cas_values) or "—",
             ", ".join(g.name for g in s.gateways.all()) or "—"]
            for s in Site.objects.all()
        ],
    )

    out.append("## Services")
    out += _table(
        ["Service", "Clients", "Default route", "Instances"],
        [
            [s.name, "yes" if s.accepts_clients else "relay-only",
             "yes" if s.default_route else "—",
             ", ".join(g.name for g in s.instances.all()) or "—"]
            for s in Service.objects.all()
        ],
    )

    out.append("## Gateways & addressing")
    out += _table(
        ["Gateway", "Service", "Site", "Endpoint", "Tunnel subnet", "Direct networks", "Active"],
        [
            [g.name, g.service.name if g.service else "—",
             g.site.name if g.site else "—", g.endpoint, g.tunnel_subnet,
             ", ".join(n.cidr for n in g.networks.all()) or "—",
             "yes" if g.is_active else "no"]
            for g in Gateway.objects.select_related("service", "site")
        ],
    )

    out.append("## Relay links")
    out += _table(
        ["From", "To"],
        [
            [l.from_gateway.name, l.to_gateway.name]
            for l in RelayLink.objects.select_related("from_gateway", "to_gateway")
        ],
    )

    out.append("## Networks")
    out += _table(
        ["Network", "CIDR", "Description", "Direct legs"],
        [
            [n.name, n.cidr, n.description or "—",
             ", ".join(g.name for g in n.gateways.all()) or "—"]
            for n in Network.objects.prefetch_related("gateways")
        ],
    )

    out.append("## Group grants")
    out += _table(
        ["Group", "Services", "Networks"],
        [
            [g.name,
             ", ".join(s.name for s in g.services.all()) or "—",
             ", ".join(n.name for n in g.networks.all()) or "—"]
            for g in Group.objects.prefetch_related("services", "networks")
        ],
    )

    return "\n".join(out)


class Command(BaseCommand):
    help = "Export the topology as a Graphviz diagram or Markdown tables."

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=["dot", "markdown"], default="dot")
        parser.add_argument("--title", help="Diagram/document title override")

    def handle(self, *args, **options):
        renderer = render_dot if options["format"] == "dot" else render_markdown
        self.stdout.write(renderer(options["title"]))
