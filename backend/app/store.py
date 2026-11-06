"""Almacenamiento simple en archivos JSON para el MVP (luego PostgreSQL)."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

ROOT = Path(settings.data_dir)


def _path(*parts: str) -> Path:
    p = ROOT.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(kind: str, tenant_id: str, data: dict) -> str:
    rid = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    _path(tenant_id, kind, f"{rid}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return rid


def load(kind: str, tenant_id: str, rid: str) -> dict:
    return json.loads(_path(tenant_id, kind, f"{rid}.json").read_text())


def tenants() -> dict:
    p = _path("tenants.json")
    return json.loads(p.read_text()) if p.exists() else {}


def add_tenant(tenant_id: str, name: str) -> None:
    t = tenants()
    t[tenant_id] = {"name": name, "onboarded": now()}
    _path("tenants.json").write_text(json.dumps(t, indent=2, ensure_ascii=False))


def audit(tenant_id: str, action: str, detail: dict) -> None:
    with _path(tenant_id, "audit.log").open("a") as f:
        f.write(json.dumps({"at": now(), "action": action, **detail}, ensure_ascii=False) + "\n")
