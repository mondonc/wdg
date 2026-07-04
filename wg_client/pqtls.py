"""
Post-quantum TLS checks for the client.

Two complementary controls, because Python's stdlib ``ssl`` can neither read nor
force the negotiated key-exchange group:

1. **Capability pre-flight** (``client_pq_capable``): the client's linked OpenSSL
   must be >= 3.5 for the ``X25519MLKEM768`` hybrid group to even be offered.
2. **Actual-group verification** (``verify_group``): the control plane's PQ
   reverse proxy echoes the negotiated group in the ``X-PQ-Group`` response
   header, so the client can confirm the connection that delivered its config
   really was post-quantum — not a silent fallback to classic X25519.

``require_pq`` (client config) turns warnings into hard failures (fail-closed).
"""

import ssl

from wg_client.i18n import _

PQ_GROUP = "X25519MLKEM768"
PQ_HEADER = "X-PQ-Group"
MIN_OPENSSL = (3, 5)


class PostQuantumUnavailable(Exception):
    """Raised, when require_pq is set, if the connection is not post-quantum."""


def client_pq_capable() -> bool:
    """True if the client's OpenSSL is new enough to offer the PQ hybrid group."""
    return ssl.OPENSSL_VERSION_INFO[:2] >= MIN_OPENSSL


def preflight(require_pq: bool) -> None:
    """Check local capability before connecting. Warn, or fail-closed."""
    if client_pq_capable():
        return
    msg = _(
        "Post-quantum TLS unavailable: client OpenSSL is {ver} (needs >= 3.5)."
    ).format(ver=ssl.OPENSSL_VERSION)
    if require_pq:
        raise PostQuantumUnavailable(msg)
    print(_("Warning: {msg} Falling back to classic TLS.").format(msg=msg))


def verify_group(headers, require_pq: bool) -> str | None:
    """
    Check the group the server reports it negotiated (``X-PQ-Group``).

    Returns the group name (or None if the proxy didn't report one). Prints a
    confirmation when PQ; warns or raises when it wasn't, per ``require_pq``.
    """
    group = headers.get(PQ_HEADER)
    if group == PQ_GROUP:
        print(_("✓ Post-quantum TLS negotiated ({group}).").format(group=group))
        return group

    if group is None:
        msg = _("Server did not report a TLS group; cannot confirm post-quantum.")
    else:
        msg = _("Connection used '{group}', not post-quantum.").format(group=group)
    if require_pq:
        raise PostQuantumUnavailable(msg)
    print(_("Warning: {msg}").format(msg=msg))
    return group
