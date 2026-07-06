import contextlib

import click
import keyring.errors
import requests

from wg_client import api, auth, config, keygen, plan, pqtls, tunnel
from wg_client.i18n import _


@contextlib.contextmanager
def _keyring_guard():
    """Turn a missing OS keyring into an actionable error, not a traceback."""
    try:
        yield
    except keyring.errors.KeyringError as exc:
        raise click.ClickException(
            _("The system keyring is unavailable ({err}). Keys and tokens are "
              "stored there; on a headless Linux, install a backend such as "
              "gnome-keyring or the 'keyrings.alt' package.").format(
                err=exc.__class__.__name__)
        )


def _require_setting(cfg: dict, key: str) -> str:
    val = cfg.get(key)
    if not val:
        raise click.ClickException(
            _("'{key}' is missing. Run 'wg-client configure' first.").format(key=key)
        )
    return val


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
    cfg = config.load()
    cfg.update({"server": server, "require_pq": require_pq})
    config.save(cfg)
    click.echo(_("Configuration saved."))


@cli.command(help=_("Authenticate via SSO and show your identity."))
def login():
    cfg = config.load()
    server = _require_setting(cfg, "server")
    click.echo(_("Authenticating..."))
    with _keyring_guard():
        token = auth.get_token(server, force=True)
    who = api.WireGuardAPI(server, token).whoami()
    click.echo(_("✓ Logged in as {user}.").format(user=who["username"]))
    if who["groups"]:
        click.echo(_("Groups: {groups}").format(groups=", ".join(who["groups"])))
    else:
        click.echo(_("Groups: (none)"))


def _connect():
    cfg = config.load()
    server = _require_setting(cfg, "server")
    require_pq = bool(cfg.get("require_pq", False))

    # post-quantum capability pre-flight (warns, or fails closed)
    try:
        pqtls.preflight(require_pq)
    except pqtls.PostQuantumUnavailable as exc:
        raise click.ClickException(str(exc))

    # keypair
    with _keyring_guard():
        private_key = config.get_private_key()
        if not private_key:
            click.echo(_("Generating new WireGuard keypair..."))
            private_key, public_key = keygen.generate_keypair()
            config.set_private_key(private_key)
        else:
            public_key = keygen.public_from_private(private_key)

        # auth (token cache lives in the keyring too)
        click.echo(_("Authenticating..."))
        token = auth.get_token(server)

    # register + fetch the multi-tunnel plan
    client = api.WireGuardAPI(server, token)
    try:
        click.echo(_("Registering peer..."))
        client.register_peer(public_key)

        click.echo(_("Fetching tunnel plan..."))
        tunnel_plan = client.get_plan()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 421:
            raise click.ClickException(
                _("The server requires a post-quantum connection, which your "
                  "client could not negotiate (upgrade to OpenSSL >= 3.5).")
            )
        raise click.ClickException(str(exc))

    # verify the channel that delivered the PSKs really was post-quantum
    try:
        pqtls.verify_group(client.last_headers, require_pq)
    except pqtls.PostQuantumUnavailable as exc:
        raise click.ClickException(str(exc))

    # bring up every planned tunnel, failing over between instances
    try:
        states = plan.connect_plan(tunnel_plan, private_key)
    except plan.TunnelError as exc:
        raise click.ClickException(str(exc))
    config.save_tunnels(states)
    for state in states:
        click.echo(
            _("✓ {service} up via {gateway} ({iface}: {ips}).").format(
                service=state["service"], gateway=state["gateway"],
                iface=state["iface"], ips=", ".join(state["allowed_ips"]),
            )
        )


def _disconnect():
    states = config.load_tunnels()
    if not states:
        click.echo(_("○ No tunnel recorded."))
        return
    for iface in plan.disconnect_all(states):
        click.echo(_("✓ {iface} down.").format(iface=iface))
    config.clear_tunnels()


@cli.command(help=_("Authenticate and bring up every planned WireGuard tunnel."))
def connect():
    _connect()


@cli.command(help=_("Bring down the WireGuard tunnels."))
def disconnect():
    _disconnect()


@cli.command(help=_("Tear down and re-establish every tunnel (fresh plan)."))
def reconnect():
    _disconnect()
    _connect()


@cli.command(help=_("Show the status of each tunnel."))
def status():
    states = config.load_tunnels()
    if not states:
        click.echo(_("○ Tunnel down."))
        return
    for state in states:
        if tunnel.is_up(state["iface"]):
            age = tunnel.handshake_age(state["iface"])
            detail = (
                _("handshake {age}s ago").format(age=int(age))
                if age is not None
                else _("no handshake data")
            )
            click.echo(
                _("● {service} via {gateway} ({iface}) — {detail}").format(
                    service=state["service"], gateway=state["gateway"],
                    iface=state["iface"], detail=detail,
                )
            )
        else:
            click.echo(
                _("○ {service} ({iface}) is down.").format(
                    service=state["service"], iface=state["iface"]
                )
            )


@cli.command(help=_("Remove saved tokens (forces re-authentication)."))
def logout():
    with _keyring_guard():
        auth.logout()
    click.echo(_("Tokens removed."))


if __name__ == "__main__":
    cli()
