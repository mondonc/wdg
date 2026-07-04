"""
Authentication for the WDG client (Apereo CAS v3, via the control plane).

The client never speaks the CAS protocol itself: it opens the browser at the
control plane's ``/auth/cas/login`` endpoint (passing its loopback callback as
the ``redirect``), lets the control plane handle the CAS ticket round-trip, and
receives a WDG session token on the loopback redirect. That token is stored in
the OS keyring and sent as a bearer token on subsequent API calls.
"""

import http.server
import threading
import time
import urllib.parse
import webbrowser

import keyring

from wg_client.i18n import _

KEYRING_SERVICE = "wg-client"
KEYRING_TOKEN = "wdg_token"
CALLBACK_PORT = 51820
CALLBACK_PATH = "/callback"
CALLBACK_TIMEOUT = 120


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict | None = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if "wdg_token" in params:
            _CallbackHandler.result = {"token": params["wdg_token"][0]}
            message = _("Authentication successful. You may close this tab.")
        else:
            error = params.get("error", ["unknown"])[0]
            _CallbackHandler.result = {"error": error}
            message = _("Error: {error}. You may close this tab.").format(error=error)

        self.wfile.write(("<h2>" + message + "</h2>").encode())

    def log_message(self, *args):
        pass


def login(server: str) -> str:
    """
    Interactive login: open the browser at the control plane, wait for the
    loopback redirect, store and return the WDG token.
    """
    redirect_uri = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
    login_url = (
        server.rstrip("/")
        + "/auth/cas/login?"
        + urllib.parse.urlencode({"redirect": redirect_uri})
    )

    _CallbackHandler.result = None
    httpd = http.server.HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    thread = threading.Thread(target=httpd.handle_request)
    thread.daemon = True
    thread.start()

    print(_("Opening browser for authentication..."))
    webbrowser.open(login_url)

    deadline = time.time() + CALLBACK_TIMEOUT
    while _CallbackHandler.result is None and time.time() < deadline:
        time.sleep(0.2)

    httpd.server_close()

    if _CallbackHandler.result is None:
        raise TimeoutError(_("Timeout: no response from browser."))
    if "error" in _CallbackHandler.result:
        raise RuntimeError(
            _("Authentication error: {error}").format(error=_CallbackHandler.result["error"])
        )

    token = _CallbackHandler.result["token"]
    keyring.set_password(KEYRING_SERVICE, KEYRING_TOKEN, token)
    return token


def get_token(server: str, force: bool = False) -> str:
    """Return a stored WDG token, logging in via the browser if needed."""
    if not force:
        token = keyring.get_password(KEYRING_SERVICE, KEYRING_TOKEN)
        if token:
            return token
    return login(server)


def logout():
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_TOKEN)
    except keyring.errors.PasswordDeleteError:
        pass
