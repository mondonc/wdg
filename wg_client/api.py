import requests


class WireGuardAPI:
    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"
        # Headers of the most recent response (carries X-PQ-Group; see pqtls).
        self.last_headers: dict = {}

    def _record(self, resp):
        self.last_headers = resp.headers
        return resp

    def register_peer(self, public_key: str) -> dict:
        resp = self._record(
            self.session.post(
                f"{self.base_url}/api/peers/register/",
                json={"public_key": public_key},
                timeout=15,
            )
        )
        resp.raise_for_status()
        return resp.json()

    def get_config(self) -> str:
        resp = self._record(self.session.get(f"{self.base_url}/api/config/", timeout=15))
        resp.raise_for_status()
        return resp.text

    def get_plan(self) -> dict:
        resp = self._record(self.session.get(f"{self.base_url}/api/plan/", timeout=15))
        resp.raise_for_status()
        return resp.json()

    def whoami(self) -> dict:
        resp = self._record(self.session.get(f"{self.base_url}/api/whoami/", timeout=15))
        resp.raise_for_status()
        return resp.json()
