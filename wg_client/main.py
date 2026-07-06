"""
Command-line frontend. All the real work lives in :mod:`wg_client.ops`
(shared with the GUI); this module only does click plumbing and output.
"""

import functools

import click

from wg_client import ops
from wg_client.i18n import _


def _op_errors(f):
    """Translate OpError (already user-facing) into a clean CLI error."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ops.OpError as exc:
            raise click.ClickException(str(exc))
    return wrapper


@click.group(help=_("WireGuard client with SSO authentication."))
def cli():
    pass


@cli.command(help=_("Configure connection parameters."))
@click.option("--server", prompt=_("Server URL (e.g. https://vpn.example.com)"))
@click.option(
    "--require-pq/--no-require-pq",
    default=False,
    help=_("Refuse to connect unless the TLS channel is post-quantum."),
)
def configure(server, require_pq):
    ops.save_settings(server, require_pq)
    click.echo(_("Configuration saved."))


@cli.command(help=_("Authenticate via SSO and show your identity."))
@_op_errors
def login():
    who = ops.identity(progress=click.echo)
    click.echo(_("✓ Logged in as {user}.").format(user=who["username"]))
    if who["groups"]:
        click.echo(_("Groups: {groups}").format(groups=", ".join(who["groups"])))
    else:
        click.echo(_("Groups: (none)"))


def _connect():
    states = ops.connect(progress=click.echo)
    for state in states:
        click.echo(
            _("✓ {service} up via {gateway} ({iface}: {ips}).").format(
                service=state["service"], gateway=state["gateway"],
                iface=state["iface"], ips=", ".join(state["allowed_ips"]),
            )
        )


def _disconnect():
    if not ops.disconnect(progress=click.echo):
        click.echo(_("○ No tunnel recorded."))


@cli.command(help=_("Authenticate and bring up every planned WireGuard tunnel."))
@_op_errors
def connect():
    _connect()


@cli.command(help=_("Bring down the WireGuard tunnels."))
@_op_errors
def disconnect():
    _disconnect()


@cli.command(help=_("Tear down and re-establish every tunnel (fresh plan)."))
@_op_errors
def reconnect():
    _disconnect()
    _connect()


@cli.command(help=_("Show the status of each tunnel."))
@_op_errors
def status():
    entries = ops.status()
    if not entries:
        click.echo(_("○ Tunnel down."))
        return
    for entry in entries:
        if entry["up"]:
            age = entry["handshake_age"]
            detail = (
                _("handshake {age}s ago").format(age=int(age))
                if age is not None
                else _("no handshake data")
            )
            click.echo(
                _("● {service} via {gateway} ({iface}) — {detail}").format(
                    service=entry["service"], gateway=entry["gateway"],
                    iface=entry["iface"], detail=detail,
                )
            )
        else:
            click.echo(
                _("○ {service} ({iface}) is down.").format(
                    service=entry["service"], iface=entry["iface"]
                )
            )


@cli.command(help=_("Remove saved tokens (forces re-authentication)."))
@_op_errors
def logout():
    ops.logout()
    click.echo(_("Tokens removed."))


if __name__ == "__main__":
    cli()
