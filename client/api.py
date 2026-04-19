import requests


class WireGuardAPI:
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"

    def register_peer(self, public_key: str) -> dict:
        resp = self.session.post(
            f"{self.base_url}/api/peers/register/",
            json={"public_key": public_key},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_config(self) -> str:
        resp = self.session.get(
            f"{self.base_url}/api/config/",
            timeout=15,
        )
        resp.raise_for_status()
        return resp.text
