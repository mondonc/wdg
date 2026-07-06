"""
UI-agnostic operations shared by the CLI (``main.py``) and the GUI
(``gui.py``). Functions report progress through a plain callback and raise
:class:`OpError` with a translated, user-facing message — no click and no Qt
in this module, so both frontends stay thin.
"""

import contextlib

import keyring.errors
import requests

from wg_client import api, auth, config, keygen, plan, pqtls, tunnel
from wg_client.i18n import _


class OpError(RuntimeError):
    """User-facing operation failure (message already translated)."""


def _noop(_message: str):
    pass


@contextlib.contextmanager
def keyring_guard():
    """Turn a missing OS keyring into an actionable error, not a traceback."""
    try:
        yield
    except keyring.errors.KeyringError as exc:
        raise OpError(
            _("The system keyring is unavailable ({err}). Keys and tokens are "
              "stored there; on a headless Linux, install a backend such as "
              "gnome-keyring or the 'keyrings.alt' package.").format(
                err=exc.__class__.__name__)
        )


def settings() -> dict:
    return config.load()


def save_settings(server: str, require_pq: bool):
    cfg = config.load()
    cfg.update({"server": server, "require_pq": require_pq})
    config.save(cfg)


def _server(cfg: dict) -> str:
    server = cfg.get("server")
    if not server:
        raise OpError(_("'{key}' is missing. Run 'wg-client configure' first.").format(key="server"))
    return server


def identity(progress=_noop) -> dict:
    """Fresh SSO login; returns the whoami payload (username, groups, site)."""
    cfg = config.load()
    server = _server(cfg)
    progress(_("Authenticating..."))
    with keyring_guard():
        token = auth.get_token(server, force=True)
    return api.WireGuardAPI(server, token).whoami()


def connect(progress=_noop) -> list[dict]:
    """Authenticate, register, fetch the plan and bring every tunnel up."""
    cfg = config.load()
    server = _server(cfg)
    require_pq = bool(cfg.get("require_pq", False))

    # post-quantum capability pre-flight (warns, or fails closed)
    try:
        pqtls.preflight(require_pq)
    except pqtls.PostQuantumUnavailable as exc:
        raise OpError(str(exc))

    with keyring_guard():
        private_key = config.get_private_key()
        if not private_key:
            progress(_("Generating new WireGuard keypair..."))
            private_key, public_key = keygen.generate_keypair()
            config.set_private_key(private_key)
        else:
            public_key = keygen.public_from_private(private_key)

        # auth (token cache lives in the keyring too)
        progress(_("Authenticating..."))
        token = auth.get_token(server)

    client = api.WireGuardAPI(server, token)
    try:
        progress(_("Registering peer..."))
        client.register_peer(public_key)

        progress(_("Fetching tunnel plan..."))
        tunnel_plan = client.get_plan()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 421:
            raise OpError(
                _("The server requires a post-quantum connection, which your "
                  "client could not negotiate (upgrade to OpenSSL >= 3.5).")
            )
        raise OpError(str(exc))
    except requests.RequestException as exc:
        raise OpError(str(exc))

    # verify the channel that delivered the PSKs really was post-quantum
    try:
        pqtls.verify_group(client.last_headers, require_pq)
    except pqtls.PostQuantumUnavailable as exc:
        raise OpError(str(exc))

    try:
        states = plan.connect_plan(tunnel_plan, private_key)
    except plan.TunnelError as exc:
        raise OpError(str(exc))
    config.save_tunnels(states)
    return states


def disconnect(progress=_noop) -> list[str]:
    """Bring every recorded tunnel down; returns the interfaces removed."""
    states = config.load_tunnels()
    if not states:
        return []
    downed = plan.disconnect_all(states)
    for iface in downed:
        progress(_("✓ {iface} down.").format(iface=iface))
    config.clear_tunnels()
    return downed


def status() -> list[dict]:
    """One entry per recorded tunnel: liveness + handshake age (or None)."""
    entries = []
    for state in config.load_tunnels():
        up = tunnel.is_up(state["iface"])
        entries.append({
            "service": state["service"],
            "gateway": state["gateway"],
            "iface": state["iface"],
            "allowed_ips": state.get("allowed_ips", []),
            "up": up,
            "handshake_age": tunnel.handshake_age(state["iface"]) if up else None,
        })
    return entries


def logout():
    with keyring_guard():
        auth.logout()
