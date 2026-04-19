import sys

import click

from wg_client import api, auth, config, keygen, tunnel
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
@click.option("--issuer", prompt=_("OIDC Issuer URL (e.g. https://cas.example.com/oidc)"))
@click.option("--client-id", prompt=_("OIDC client_id"))
def configure(server, issuer, client_id):
    cfg = config.load()
    cfg.update({"server": server, "issuer": issuer, "client_id": client_id})
    config.save(cfg)
    click.echo(_("Configuration saved."))


@cli.command(help=_("Authenticate and bring up the WireGuard tunnel."))
def connect():
    cfg = config.load()
    server = _require_setting(cfg, "server")
    issuer = _require_setting(cfg, "issuer")
    client_id = _require_setting(cfg, "client_id")

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
    token = auth.get_token(issuer, client_id)

    # register + fetch config
    client = api.WireGuardAPI(server, token)
    click.echo(_("Registering peer..."))
    client.register_peer(public_key)

    click.echo(_("Fetching configuration..."))
    conf = client.get_config()

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
