# Post-quantum transport

WDG makes the WireGuard **preshared key (PSK)** delivery resistant to
"harvest-now-decrypt-later" (HNDL) without touching the WireGuard protocol or
requiring non-standard clients.

## The approach

WireGuard's PSK is a static field in the `.conf` (`[Peer] PresharedKey = …`) that
any standard client consumes unchanged. WDG already delivers each per-device PSK
over the HTTPS channel the client uses to fetch its config after SSO. We make
**that channel post-quantum**: TLS 1.3 with the `X25519MLKEM768` hybrid
key-exchange group (classical X25519 + ML-KEM-768).

An attacker who records the WireGuard UDP traffic today and later breaks
Curve25519 recovers the ECDH output but **not** the PSK — to get the PSK they
would have had to break ML-KEM-768 at capture time, which is what the PQ exchange
prevents. The WireGuard session key `f(ECDH, PSK)` therefore stays protected.

### What it protects — and what it does not

- ✅ **Confidentiality against HNDL** on the PSK delivery. This is the property
  that matters for a confidentiality-focused enterprise VPN.
- ❌ The WireGuard **handshake authentication** stays classical (Curve25519), so
  this does not defend against a *future active* quantum MITM.
- ❌ No per-handshake PQ forward secrecy (that would need a real PQ-WireGuard,
  which breaks the "standard clients" invariant). Rotation is by re-provisioning:
  the client re-fetches its config, which the lifecycle already supports.

## Server side (authoritative)

`deploy/nginx-pq/` terminates client HTTPS with an OpenSSL ≥ 3.5 nginx:

```nginx
ssl_protocols TLSv1.3;
ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1;   # PQ first, classic fallback
```

Compatibility is preserved by default: clients that can't do the hybrid group
fall back to classic X25519 transparently.

### The "make PQ mandatory tomorrow" switch

The server is authoritative because it *knows* the negotiated group
(`$ssl_curve`). Setting `REQUIRE_PQ=on` makes the sensitive endpoints
(`/api/config/`, `/api/peers/register/`) refuse a non-PQ connection with **HTTP
421** before serving anything, while leaving the login/enrollment path open in
classic so users aren't locked out:

```nginx
map $ssl_curve $pq_ok { default 0; X25519MLKEM768 1; }
location = /api/config/ {
    if ($pq_ok = 0) { return 421; }   # injected only when REQUIRE_PQ=on
    proxy_pass http://control-plane:8000;
}
```

Flip the switch when your fleet is ready — no client change required. nginx also
adds an `X-PQ-Group` response header exposing the negotiated group, which the
client uses to verify (below).

## Client side

Python's stdlib `ssl` can neither read the negotiated group nor force the hybrid
one, so the client uses two complementary controls (`wg_client/pqtls.py`):

1. **Capability pre-flight** — the client's linked OpenSSL must be ≥ 3.5 for the
   hybrid group to even be offered (`ssl.OPENSSL_VERSION_INFO`). On Linux with a
   current distro this is automatic; some Windows/macOS Python builds ship an
   older OpenSSL and would silently fall back to classic — hence the check.
2. **Actual-group verification** — the client reads the `X-PQ-Group` header the
   PQ proxy returns and confirms the connection that delivered the PSK really was
   `X25519MLKEM768`, not a silent classic fallback.

The `require_pq` client setting turns warnings into hard failures (fail-closed):

```bash
python -m wg_client.main configure --server https://vpn.example.com --require-pq
```

With `require_pq`, a client that can't confirm PQ refuses to bring up the tunnel,
and a `421` from a PQ-mandatory server yields a clear message instead of a stack
trace.

## Verifying

```bash
# server negotiates the hybrid group
echo | openssl s_client -groups X25519MLKEM768 -connect <host>:8443 2>&1 \
  | grep "Negotiated TLS1.3 group"

# full check (compat + fail-closed), from a host with OpenSSL >= 3.5
bash deploy/tests/m5_pq_check.sh
```

Requirements: nginx/OpenSSL ≥ 3.5 on the server (Debian 13/trixie ships it); the
client's OpenSSL ≥ 3.5 to actually negotiate PQ.
