import sys

import click
import requests

from wg_client import api, auth, config, keygen, pqtls, tunnel
from wg_client.i18n import _


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
    token = auth.get_token(server, force=True)
    who = api.WireGuardAPI(server, token).whoami()
    click.echo(_("✓ Logged in as {user}.").format(user=who["username"]))
    if who["groups"]:
        click.echo(_("Groups: {groups}").format(groups=", ".join(who["groups"])))
    else:
        click.echo(_("Groups: (none)"))


@cli.command(help=_("Authenticate and bring up the WireGuard tunnel."))
def connect():
    cfg = config.load()
    server = _require_setting(cfg, "server")
    require_pq = bool(cfg.get("require_pq", False))

    # post-quantum capability pre-flight (warns, or fails closed)
    try:
        pqtls.preflight(require_pq)
    except pqtls.PostQuantumUnavailable as exc:
        raise click.ClickException(str(exc))

    # keypair
    private_key = config.get_private_key()
    if not private_key:
        click.echo(_("Generating new WireGuard keypair..."))
        private_key, public_key = keygen.generate_keypair()
        config.set_private_key(private_key)
    else:
        public_key = keygen.public_from_private(private_key)

    # auth
    click.echo(_("Authenticating..."))
    token = auth.get_token(server)

    # register + fetch config
    client = api.WireGuardAPI(server, token)
    try:
        click.echo(_("Registering peer..."))
        client.register_peer(public_key)

        click.echo(_("Fetching configuration..."))
        conf = client.get_config()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 421:
            raise click.ClickException(
                _("The server requires a post-quantum connection, which your "
                  "client could not negotiate (upgrade to OpenSSL >= 3.5).")
            )
        raise click.ClickException(str(exc))

    # verify the channel that delivered the PSK really was post-quantum
    try:
        pqtls.verify_group(client.last_headers, require_pq)
    except pqtls.PostQuantumUnavailable as exc:
        raise click.ClickException(str(exc))

    # inject private key (the server never sees it)
    conf = conf.replace("__PRIVATE_KEY__", private_key)

    # up
    click.echo(_("Bringing up tunnel..."))
    tunnel.connect(conf)
    click.echo(_("✓ Tunnel up."))


@cli.command(help=_("Bring down the WireGuard tunnel."))
def disconnect():
    tunnel.disconnect()
    click.echo(_("✓ Tunnel down."))


@cli.command(help=_("Show tunnel status."))
def status():
    if tunnel.status():
        click.echo(_("● Tunnel up."))
    else:
        click.echo(_("○ Tunnel down."))


@cli.command(help=_("Remove saved tokens (forces re-authentication)."))
def logout():
    auth.logout()
    click.echo(_("Tokens removed."))


if __name__ == "__main__":
    cli()
