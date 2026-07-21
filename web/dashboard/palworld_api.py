import logging
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class PalworldAPIError(Exception):
    pass


class PalworldAPIClient:
    def __init__(self, base_url=None, user=None, password=None, timeout=10):
        self.base_url = (base_url or settings.PALWORLD_API_URL).rstrip("/")
        if not self.base_url:
            raise PalworldAPIError("PALWORLD_API_URL is not configured")
        self.auth = (user or settings.PALWORLD_API_USER, password or settings.PALWORLD_API_PASSWORD)
        if not self.auth[1]:
            raise PalworldAPIError("PALWORLD_API_PASSWORD is not configured")
        self.timeout = timeout

    def _request(self, method, path, json_body=None):
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        try:
            response = requests.request(
                method,
                url,
                json=json_body,
                auth=self.auth,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 401:
                raise PalworldAPIError("authentication failed")
            if response.status_code == 400:
                raise PalworldAPIError(f"bad request: {response.text}")
            if not response.ok:
                raise PalworldAPIError(f"HTTP {response.status_code}: {response.text}")
            if response.text:
                return response.json()
            return {}
        except requests.RequestException as exc:
            raise PalworldAPIError(f"request error: {exc}") from exc

    def get_players(self):
        data = self._request("GET", "/v1/api/players")
        return data.get("players", [])

    def get_info(self):
        return self._request("GET", "/v1/api/info")

    def get_metrics(self):
        return self._request("GET", "/v1/api/metrics")

    def get_settings(self):
        return self._request("GET", "/v1/api/settings")

    def announce(self, message):
        return self._request("POST", "/v1/api/announce", {"message": message})

    def kick(self, player_uid):
        return self._request("POST", "/v1/api/kick", {"userid": player_uid})

    def ban(self, player_uid):
        return self._request("POST", "/v1/api/ban", {"userid": player_uid})

    def unban(self, player_uid):
        return self._request("POST", "/v1/api/unban", {"userid": player_uid})

    def save(self):
        return self._request("POST", "/v1/api/save")
