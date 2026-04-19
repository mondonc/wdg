import hashlib
import http.server
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser

import keyring
import requests

KEYRING_SERVICE = "wg-client"
KEYRING_ACCESS_TOKEN = "access_token"
KEYRING_REFRESH_TOKEN = "refresh_token"
CALLBACK_PORT = 51820
CALLBACK_TIMEOUT = 120


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict | None = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if "code" in params:
            _CallbackHandler.result = {"code": params["code"][0]}
            body = "<h2>Authentification réussie. Vous pouvez fermer cet onglet.</h2>".encode()
        else:
            error = params.get("error", ["unknown"])[0]
            _CallbackHandler.result = {"error": error}
            body = f"<h2>Erreur : {error}. Vous pouvez fermer cet onglet.</h2>".encode()

        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = (
        __import__("base64")
        .urlsafe_b64encode(digest)
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _discover(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def login(issuer: str, client_id: str) -> str:
    """
    Full PKCE authorization code flow.
    Opens browser, waits for callback, exchanges code for token.
    Returns access_token.
    """
    meta = _discover(issuer)
    auth_endpoint = meta["authorization_endpoint"]
    token_endpoint = meta["token_endpoint"]

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://localhost:{CALLBACK_PORT}/callback"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = auth_endpoint + "?" + urllib.parse.urlencode(params)

    _CallbackHandler.result = None
    server = http.server.HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.daemon = True
    thread.start()

    print(f"Ouverture du navigateur pour l'authentification...")
    webbrowser.open(auth_url)

    deadline = time.time() + CALLBACK_TIMEOUT
    while _CallbackHandler.result is None and time.time() < deadline:
        time.sleep(0.2)

    server.server_close()

    if _CallbackHandler.result is None:
        raise TimeoutError("Timeout : aucune réponse du navigateur.")
    if "error" in _CallbackHandler.result:
        raise RuntimeError(f"Erreur OIDC : {_CallbackHandler.result['error']}")

    code = _CallbackHandler.result["code"]

    resp = requests.post(
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": verifier,
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()

    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCESS_TOKEN, tokens["access_token"])
    if "refresh_token" in tokens:
        keyring.set_password(KEYRING_SERVICE, KEYRING_REFRESH_TOKEN, tokens["refresh_token"])

    return tokens["access_token"]


def refresh(issuer: str, client_id: str) -> str | None:
    """Attempts a silent refresh. Returns new access_token or None."""
    refresh_token = keyring.get_password(KEYRING_SERVICE, KEYRING_REFRESH_TOKEN)
    if not refresh_token:
        return None

    meta = _discover(issuer)
    token_endpoint = meta["token_endpoint"]

    try:
        resp = requests.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        tokens = resp.json()
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCESS_TOKEN, tokens["access_token"])
        if "refresh_token" in tokens:
            keyring.set_password(KEYRING_SERVICE, KEYRING_REFRESH_TOKEN, tokens["refresh_token"])
        return tokens["access_token"]
    except Exception:
        return None


def get_token(issuer: str, client_id: str) -> str:
    """Returns a valid access_token, refreshing or re-logging as needed."""
    token = refresh(issuer, client_id)
    if token:
        return token
    return login(issuer, client_id)


def logout():
    keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCESS_TOKEN)
    keyring.delete_password(KEYRING_SERVICE, KEYRING_REFRESH_TOKEN)
