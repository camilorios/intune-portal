"""Cliente de Microsoft Graph por tenant (client credentials)."""
import time
import httpx
import msal

from .config import settings

GRAPH = "https://graph.microsoft.com"


class GraphClient:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._app = msal.ConfidentialClientApplication(
            settings.client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=settings.client_secret,
        )
        self._http = httpx.Client(timeout=60)

    def _token(self) -> str:
        res = self._app.acquire_token_for_client(scopes=[f"{GRAPH}/.default"])
        if "access_token" not in res:
            raise RuntimeError(f"No se obtuvo token para {self.tenant_id}: {res.get('error_description')}")
        return res["access_token"]

    def request(self, method: str, path: str, version: str = "v1.0", **kw) -> httpx.Response:
        url = path if path.startswith("http") else f"{GRAPH}/{version}/{path.lstrip('/')}"
        for attempt in range(5):
            r = self._http.request(method, url, headers={"Authorization": f"Bearer {self._token()}"}, **kw)
            if r.status_code in (429, 503, 504):  # throttling de Graph/Intune
                time.sleep(int(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text}")
            return r
        raise RuntimeError(f"{method} {url}: demasiados reintentos")

    def list_all(self, path: str, version: str = "v1.0", query: str = "") -> list[dict]:
        if query:
            path = f"{path}?{query}"
        items, r = [], self.request("GET", path, version).json()
        items += r.get("value", [])
        while r.get("@odata.nextLink"):
            r = self.request("GET", r["@odata.nextLink"]).json()
            items += r.get("value", [])
        return items

    def create(self, path: str, body: dict, version: str = "v1.0") -> dict:
        return self.request("POST", path, version, json=body).json()

    def get(self, path: str, version: str = "v1.0") -> dict:
        return self.request("GET", path, version).json()

    def patch(self, path: str, body: dict, version: str = "v1.0") -> None:
        self.request("PATCH", path, version, json=body)

    def delete(self, path: str, version: str = "v1.0") -> None:
        self.request("DELETE", path, version)
