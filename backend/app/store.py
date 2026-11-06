"""Almacenamiento simple en archivos JSON para el MVP (luego PostgreSQL).

Los backups y snapshots contienen la configuración completa del cliente, así que se cifran
en reposo con AES-256-GCM cuando BACKUP_KEY está definida (idea tomada de TenuVault).
"""
import base64
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

ROOT = Path(settings.data_dir)
ENCRYPTED_KINDS = {"backups"}


def _path(*parts: str) -> Path:
    p = ROOT.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- cifrado ----------
def _key() -> bytes | None:
    if not settings.backup_key:
        return None
    key = base64.b64decode(settings.backup_key)
    if len(key) != 32:
        raise RuntimeError("BACKUP_KEY debe ser de 32 bytes en base64")
    return key


def _encode(kind: str, tenant_id: str, data: dict) -> str:
    raw = json.dumps(data, indent=2, ensure_ascii=False)
    key = _key()
    if kind not in ENCRYPTED_KINDS or key is None:
        return raw
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    # El tenant va como dato asociado: un backup no se puede descifrar como si fuera de otro cliente
    ct = AESGCM(key).encrypt(nonce, raw.encode(), tenant_id.encode())
    return json.dumps({"enc": "AES-256-GCM", "nonce": base64.b64encode(nonce).decode(),
                       "data": base64.b64encode(ct).decode()})


def _decode(tenant_id: str, text: str) -> dict:
    d = json.loads(text)
    if d.get("enc") != "AES-256-GCM":
        return d
    key = _key()
    if key is None:
        raise RuntimeError("Backup cifrado y BACKUP_KEY no está configurada")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pt = AESGCM(key).decrypt(base64.b64decode(d["nonce"]), base64.b64decode(d["data"]), tenant_id.encode())
    return json.loads(pt)


# ---------- registros ----------
def save(kind: str, tenant_id: str, data: dict) -> str:
    rid = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    _path(tenant_id, kind, f"{rid}.json").write_text(_encode(kind, tenant_id, data))
    return rid


def load(kind: str, tenant_id: str, rid: str) -> dict:
    if "/" in rid or ".." in rid:
        raise ValueError("id inválido")
    return _decode(tenant_id, _path(tenant_id, kind, f"{rid}.json").read_text())


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


def read_audit(tenant_id: str, limit: int = 100) -> list[dict]:
    p = ROOT / tenant_id / "audit.log"
    if not p.exists():
        return []
    lines = p.read_text().splitlines()[-limit:]
    return [json.loads(x) for x in reversed(lines)]


def list_records(kind: str, tenant_id: str) -> list[dict]:
    folder = ROOT / tenant_id / kind
    if not folder.exists():
        return []
    out = []
    for f in sorted(folder.glob("*.json"), reverse=True):
        d = _decode(tenant_id, f.read_text())
        out.append({"id": f.stem, "baseline": d.get("baseline"), "mode": d.get("mode"), "at": d.get("at"),
                    "reason": d.get("reason"), "created": len(d.get("created", [])),
                    "updated": len(d.get("updated", [])), "errors": len(d.get("errors", []))})
    return out
