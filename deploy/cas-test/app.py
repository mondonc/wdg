"""
Minimal mock Apereo CAS server for WDG integration tests.

Implements just enough of the CAS v3 protocol for the control plane:
    GET /cas/login?service=<url>[&username=<u>]   -> issue ST ticket, redirect
    GET /cas/p3/serviceValidate?service=&ticket=  -> JSON with user + attributes

Users and their released attributes (incl. group membership) are read from
``users.json``. Passwords are not checked — this is a test double, not CAS.
"""

import json
import os
import secrets
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, request

app = Flask(__name__)

USERS_FILE = os.environ.get("CAS_USERS_FILE", os.path.join(os.path.dirname(__file__), "users.json"))

# Issued, not-yet-validated tickets: ticket -> {"user", "service"}. One-time use.
_TICKETS: dict[str, dict] = {}


def _users() -> dict:
    with open(USERS_FILE) as fh:
        return json.load(fh)


_LOGIN_FORM = """<!doctype html>
<title>Mock CAS login</title>
<h2>Mock CAS — sign in</h2>
<form method="get" action="/cas/login">
  <input type="hidden" name="service" value="{service}">
  <label>Username <input name="username" autofocus></label>
  <button type="submit">Login</button>
</form>
<p>Known users: {users}</p>
"""


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.get("/cas/login")
def login():
    service = request.args.get("service", "")
    username = request.args.get("username")
    if not username:
        return _LOGIN_FORM.format(service=service, users=", ".join(_users()))

    if username not in _users():
        return f"unknown user: {username}", 400

    ticket = "ST-" + secrets.token_urlsafe(24)
    _TICKETS[ticket] = {"user": username, "service": service}
    return redirect(service + ("&" if "?" in service else "?") + urlencode({"ticket": ticket}))


@app.get("/cas/p3/serviceValidate")
def service_validate():
    service = request.args.get("service", "")
    ticket = request.args.get("ticket", "")

    entry = _TICKETS.pop(ticket, None)
    if entry is None:
        return jsonify(serviceResponse={"authenticationFailure": {"code": "INVALID_TICKET"}})
    if entry["service"] != service:
        return jsonify(serviceResponse={"authenticationFailure": {"code": "INVALID_SERVICE"}})

    user = entry["user"]
    attributes = _users()[user]
    return jsonify(
        serviceResponse={
            "authenticationSuccess": {"user": user, "attributes": attributes}
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
