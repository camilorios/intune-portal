"""Vista previa, despliegue y reversión de baselines."""
import json
from pathlib import Path

from . import store
from .backup import take_backup
from .config import settings
from .graph import GraphClient
from .resources import BY_KEY, name_of

ALL_DEVICES = {"@odata.type": "#microsoft.graph.allDevicesAssignmentTarget"}
READONLY = {"id", "createdDateTime", "lastModifiedDateTime", "version"}


def load_baseline(name: str) -> list[dict]:
    """Cada archivo JSON de la carpeta es: {"resource": "<key>", "assignAllDevices": bool, "body": {...}}"""
    folder = Path(settings.baselines_dir) / name
    if not folder.is_dir():
        raise FileNotFoundError(f"Baseline {name} no existe")
    return [json.loads(f.read_text()) for f in sorted(folder.glob("*.json"))]


def _prefixed(res: dict, body: dict) -> dict:
    body = {k: v for k, v in body.items() if k not in READONLY}
    field = res.get("name_field", "displayName")
    if not body.get(field, "").startswith(settings.object_prefix):
        body[field] = f"{settings.object_prefix} {body.get(field, '')}".strip()
    return body


def preview(tenant_id: str, baseline: str) -> list[dict]:
    g = GraphClient(tenant_id)
    plan, cache = [], {}
    for item in load_baseline(baseline):
        res = BY_KEY[item["resource"]]
        body = _prefixed(res, item["body"])
        if res["key"] not in cache:
            cache[res["key"]] = {name_of(res, o) for o in g.list_all(res["path"], res["version"])}
        exists = name_of(res, body) in cache[res["key"]]
        plan.append({"resource": res["key"], "name": name_of(res, body), "action": "skip (ya existe)" if exists else "create"})
    return plan


def deploy(tenant_id: str, baseline: str) -> dict:
    snapshot = take_backup(tenant_id, f"antes de desplegar {baseline}")
    g = GraphClient(tenant_id)
    plan = {(p["resource"], p["name"]): p["action"] for p in preview(tenant_id, baseline)}
    created, errors = [], []
    for item in load_baseline(baseline):
        res = BY_KEY[item["resource"]]
        body = _prefixed(res, item["body"])
        if plan.get((res["key"], name_of(res, body))) != "create":
            continue
        try:
            obj = g.create(res["path"], body, res["version"])
            created.append({"resource": res["key"], "id": obj["id"], "name": name_of(res, body)})
            if item.get("assignAllDevices") and res.get("assign"):
                g.create(f"{res['path']}/{obj['id']}/assign", {"assignments": [{"target": ALL_DEVICES}]}, res["version"])
        except RuntimeError as e:
            errors.append({"resource": res["key"], "name": name_of(res, body), "error": str(e)})
    record = {"baseline": baseline, "snapshot": snapshot, "created": created, "errors": errors, "at": store.now()}
    rid = store.save("deployments", tenant_id, record)
    store.audit(tenant_id, "deploy", {"deployment_id": rid, "baseline": baseline, "created": len(created), "errors": len(errors)})
    return {"deployment_id": rid, **record}


def rollback(tenant_id: str, deployment_id: str) -> dict:
    """Modo 1 del restablecimiento: elimina lo que creó un despliegue concreto."""
    record = store.load("deployments", tenant_id, deployment_id)
    backup_id = take_backup(tenant_id, f"antes de revertir {deployment_id}")
    g = GraphClient(tenant_id)
    removed, errors = [], []
    for obj in reversed(record["created"]):
        res = BY_KEY[obj["resource"]]
        try:
            g.delete(f"{res['path']}/{obj['id']}", res["version"])
            removed.append(obj)
        except RuntimeError as e:
            errors.append({**obj, "error": str(e)})
    store.audit(tenant_id, "rollback", {"deployment_id": deployment_id, "backup_id": backup_id, "removed": len(removed)})
    return {"backup_id": backup_id, "removed": removed, "errors": errors}
