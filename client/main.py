import sys

import click

from wg_client import api, auth, config, keygen, tunnel


def _require_setting(cfg: dict, key: str) -> str:
    val = cfg.get(key)
    if not val:
        raise click.ClickException(
            f"'{key}' manquant. Lancez d'abord : wg-client configure"
        )
    return val


@click.group()
def cli():
    """Client WireGuard avec authentification SSO."""


@cli.command()
@click.option("--server", prompt="URL du serveur (ex: https://vpn.example.com)")
@click.option("--issuer", prompt="OIDC Issuer URL (ex: https://cas.example.com/oidc)")
@click.option("--client-id", prompt="OIDC client_id")
def configure(server, issuer, client_id):
    """Configure les paramètres de connexion."""
    cfg = config.load()
    cfg.update({"server": server, "issuer": issuer, "client_id": client_id})
    config.save(cfg)
    click.echo("Configuration sauvegardée.")


@cli.command()
def connect():
    """Authentifie et active le tunnel WireGuard."""
    cfg = config.load()
    server = _require_setting(cfg, "server")
    issuer = _require_setting(cfg, "issuer")
    client_id = _require_setting(cfg, "client_id")

    # keypair
    private_key = config.get_private_key()
    if not private_key:
        click.echo("Génération d'une nouvelle paire de clés WireGuard...")
        private_key, public_key = keygen.generate_keypair()
        config.set_private_key(private_key)
    else:
        public_key = keygen.public_from_private(private_key)

    # auth
    click.echo("Authentification...")
    token = auth.get_token(issuer, client_id)

    # register + fetch config
    client = api.WireGuardAPI(server, token)
    click.echo("Enregistrement du peer...")
    client.register_peer(public_key)

    click.echo("Récupération de la configuration...")
    conf = client.get_config()

    # inject private key (le serveur ne la connaît pas)
    conf = conf.replace("__PRIVATE_KEY__", private_key)

    # up
    click.echo("Activation du tunnel...")
    tunnel.connect(conf)
    click.echo("✓ Tunnel actif.")


@cli.command()
def disconnect():
    """Désactive le tunnel WireGuard."""
    tunnel.disconnect()
    click.echo("✓ Tunnel arrêté.")


@cli.command()
def status():
    """Affiche l'état du tunnel."""
    if tunnel.status():
        click.echo("● Tunnel actif.")
    else:
        click.echo("○ Tunnel inactif.")


@cli.command()
def logout():
    """Supprime les tokens sauvegardés (force une ré-authentification)."""
    auth.logout()
    click.echo("Tokens supprimés.")


if __name__ == "__main__":
    cli()
